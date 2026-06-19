#!/usr/bin/env python3
"""Turn recorded GPX traces of the actual commute into ground-truth data:
real travel time, and the locations where you actually crawled (the "pockets").

Each trace is auto-classified by direction from where it *starts*:

  return  office -> home   (start nearer the office)
  onward  home -> office   (start nearer home)

so you can just throw the whole folder at it and the two commutes stay in
separate pipelines. Per direction it appends three CSVs:

  data/<dir>_summary.csv   one row per trace (date, duration, #pockets, ...)
  data/<dir>_pockets.csv   one row per slow stretch (location, duration, speed)
  data/<dir>_sections.csv  one row per 200 m section of each full trace
                           (date, start_time, dist_m, sec) for the 2D profile

A trace that starts more than partial_gap_m from its origin (you forgot to
record from the start) is flagged partial=True — kept, but excluded from the
travel-time plot since its duration is an undercount.

A pocket is a contiguous run slower than pocket_speed_kmh (config.json) lasting
at least --min-pocket-sec seconds, so brief signal stops don't all count.

Usage:
    python3 ingest_gpx.py gps/*.gpx
"""

import argparse
import csv
import datetime as dt
import json
import math
import os
import sys

import gpxpy
import numpy as np

DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, "data")
CFG_PATH = os.path.join(DIR, "config.json")

SUMMARY_FIELDS = [
    "date", "start_time", "end_time", "direction", "partial",
    "duration_min", "distance_km", "mean_speed_kmh",
    "slow_time_min", "n_pockets", "trim_head_s", "trim_tail_s", "gpx_file",
]
POCKET_FIELDS = [
    "date", "dist_km_along", "lat", "lon",
    "duration_s", "mean_speed_kmh",
]
SECTION_FIELDS = ["date", "start_time", "dist_m", "sec"]


def load_cfg() -> dict:
    with open(CFG_PATH) as f:
        return json.load(f)


def parse_offset(off: str) -> dt.timezone:
    """'+05:30' -> tzinfo, so UTC GPS timestamps display in local time."""
    sign = 1 if off[0] == "+" else -1
    h, m = int(off[1:3]), int(off[4:6])
    return dt.timezone(sign * dt.timedelta(hours=h, minutes=m))


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def classify(lat: float, lon: float, cfg: dict) -> tuple[str, float]:
    """Return (direction, metres-from-origin) for a trace starting at lat,lon.

    Nearer the office -> 'return' (office->home); nearer home -> 'onward'.
    """
    o, d = cfg["origin"], cfg["destination"]
    d_office = haversine(lat, lon, o["lat"], o["lon"])
    d_home = haversine(lat, lon, d["lat"], d["lon"])
    if d_office <= d_home:
        return "return", d_office
    return "onward", d_home


def _local_xy(lat, lon, lat0, lon0):
    """Equirectangular projection to metres about (lat0, lon0)."""
    k = math.cos(math.radians(lat0))
    x = (np.asarray(lon) - lon0) * k * 111320.0
    y = (np.asarray(lat) - lat0) * 111320.0
    return x, y


def build_route(pts: list[tuple]) -> dict:
    """A reference route axis from a trace: vertices + cumulative arc-length (m).
    Every trace's points get projected onto this so the same physical place maps
    to the same x, independent of per-trip GPS noise and path wiggle.
    """
    lat = [p[1] for p in pts]
    lon = [p[2] for p in pts]
    lat0, lon0 = sum(lat) / len(lat), sum(lon) / len(lon)
    x, y = _local_xy(lat, lon, lat0, lon0)
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    return {"lat": lat, "lon": lon, "lat0": lat0, "lon0": lon0,
            "x": x.tolist(), "y": y.tolist(), "s": s.tolist()}


def project_arc_length(route: dict, pts: list[tuple]) -> np.ndarray:
    """Constrain each GPS point to the route axis: its along-route position is
    the arc-length of the nearest route vertex, searched only within a window
    that advances forward by at most a plausible distance (speed x elapsed time)
    from the previous point. This keeps progress monotonic AND stops a point from
    snapping to a spatially-close but far-along leg where the route nearly meets
    itself (e.g. a U-turn), which would otherwise teleport the arc-length."""
    rx, ry, rs = np.array(route["x"]), np.array(route["y"]), np.array(route["s"])
    px, py = _local_xy([p[1] for p in pts], [p[2] for p in pts],
                       route["lat0"], route["lon0"])
    s = np.empty(len(pts))
    s_prev = 0.0
    for i in range(len(pts)):
        dt = (pts[i][0] - pts[i - 1][0]).total_seconds() if i else 1.0
        adv = 25.0 * max(dt, 1.0) + 40.0     # ~90 km/h ceiling + slack (metres)
        idx = np.where((rs >= s_prev - 10) & (rs <= s_prev + adv))[0]
        if len(idx) == 0:
            idx = np.array([int(np.argmin(np.abs(rs - s_prev)))])
        k = idx[int(np.argmin((rx[idx] - px[i]) ** 2 + (ry[idx] - py[i]) ** 2))]
        s_prev = max(float(rs[k]), s_prev)
        s[i] = s_prev
    return s


def compute_sections(pts: list[tuple], route: dict, bin_m: float) -> list[dict]:
    """Time to cross each fixed-length section, measured along the reference
    route axis (not raw path length). A section only counts where this trace
    actually covers the route, so partial coverage at the ends is skipped.
    A stop inside a section is absorbed (position flat while time runs) = a jam.
    """
    s = project_arc_length(route, pts)
    t = np.array([(p[0] - pts[0][0]).total_seconds() for p in pts], dtype=float)
    edges = np.arange(0, route["s"][-1], bin_m)
    enter = np.interp(edges, s, t)
    out = []
    for k in range(len(edges) - 1):
        if edges[k] >= s[0] and edges[k + 1] <= s[-1]:  # within this trace's span
            out.append({"dist_m": int(edges[k]),
                        "sec": round(enter[k + 1] - enter[k], 1)})
    return out


def read_points(path: str, tz: dt.timezone) -> list[tuple]:
    """Flatten a GPX file to (time, lat, lon, cum_dist_m) tuples.

    GPS loggers stamp points in UTC; convert to tz so the date and clock
    times we report match the local commute, not UTC.
    """
    with open(path) as f:
        gpx = gpxpy.parse(f)
    pts, prev, cum = [], None, 0.0
    for track in gpx.tracks:
        for seg in track.segments:
            for p in seg.points:
                if p.time is None:
                    continue
                if prev is not None:
                    cum += p.distance_2d(prev) or 0.0
                pts.append((p.time.astimezone(tz), p.latitude, p.longitude, cum))
                prev = p
    return pts


def smoothed_speeds(pts: list[tuple], smooth_n: int) -> list[float]:
    """Per-point speed in km/h, smoothed over a centred window to ride out GPS
    noise (so a single jittery fix during the walk doesn't look like driving)."""
    n = len(pts)
    raw = [0.0] * n
    for i in range(1, n):
        sec = (pts[i][0] - pts[i - 1][0]).total_seconds()
        raw[i] = (pts[i][3] - pts[i - 1][3]) / sec * 3.6 if sec > 0 else raw[i - 1]
    half = max(0, smooth_n // 2)
    sm = [0.0] * n
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        sm[i] = sum(raw[lo:hi]) / (hi - lo)
    return sm


def stations_for(direction: str, stations: dict) -> tuple[dict, dict]:
    """(origin station, destination station) for a direction."""
    if direction == "onward":            # home -> office
        return stations["home"], stations["office"]
    return stations["office"], stations["home"]   # return: office -> home


def clamp_to_stations(pts: list[tuple], origin: dict, dest: dict,
                      station_radius: float) -> tuple[list[tuple], dict]:
    """Clamp a trace to the ride between its two terminating stations by where it
    crosses each station's gate (a circle of station_radius), not by speed:

      start = the FIRST departure from the origin gate (exit of the first time
              the trace is within the radius) -> excludes parking/helmet/idle but
              keeps the whole route, including a U-turn taken further along.
      end   = the arrival at the destination gate (first time within its radius)
              -> excludes the in-society / parking maneuvers at the end.

    A return that loops out, U-turns and comes back past the office still starts
    at the original office departure (not the later pass-by), so its distance
    rightly exceeds the onward leg.
    origin_gap/dest_gap report how close the trace got to each station.
    """
    do = [haversine(p[1], p[2], origin["lat"], origin["lon"]) for p in pts]
    dd = [haversine(p[1], p[2], dest["lat"], dest["lon"]) for p in pts]
    io, idd = int(np.argmin(do)), int(np.argmin(dd))
    info = {"origin_gap": round(do[io]), "dest_gap": round(dd[idd])}
    n = len(pts)

    near_o = [i for i in range(n) if do[i] <= station_radius and i < idd]
    if near_o:                                       # exit of the FIRST cluster
        start = near_o[0]
        for a, b in zip(near_o, near_o[1:]):
            if b - a > 20:                           # big gap = left the gate
                break
            start = b
    else:
        start = io
    cand_d = [i for i in range(n) if dd[i] <= station_radius and i > start]
    end = min(cand_d) if cand_d else (idd if idd > start else n - 1)  # arrival
    if start >= end:                                 # degenerate; keep it all
        start, end = 0, n - 1

    info.update({
        "head_s": round((pts[start][0] - pts[0][0]).total_seconds()),
        "tail_s": round((pts[-1][0] - pts[end][0]).total_seconds()),
        "head_m": round(pts[start][3] - pts[0][3]),
        "tail_m": round(pts[-1][3] - pts[end][3]),
    })
    off = pts[start][3]
    clamped = [(t, la, lo, cum - off) for (t, la, lo, cum) in pts[start:end + 1]]
    return clamped, info


def trim_to_drive(pts: list[tuple], drive_kmh: float,
                  smooth_n: int) -> tuple[list[tuple], dict]:
    """Clip leading/trailing non-driving points (idle before starting, a late
    stop, the walk to/from the car) by keeping only from the first to the last
    point moving at >= drive_kmh. The interior is untouched, so mid-route
    traffic crawls are preserved. Cumulative distance is re-zeroed to the new
    start so distance/pockets measure the drive only.
    """
    zero = {"head_s": 0, "tail_s": 0, "head_m": 0, "tail_m": 0}
    if len(pts) < 3:
        return pts, zero
    sm = smoothed_speeds(pts, smooth_n)
    driving = [i for i, s in enumerate(sm) if s >= drive_kmh]
    if not driving:
        return pts, zero  # nothing looked like driving; leave it alone
    a, b = driving[0], driving[-1]
    info = {
        "head_s": round((pts[a][0] - pts[0][0]).total_seconds()),
        "tail_s": round((pts[-1][0] - pts[b][0]).total_seconds()),
        "head_m": round(pts[a][3] - pts[0][3]),
        "tail_m": round(pts[-1][3] - pts[b][3]),
    }
    off = pts[a][3]
    trimmed = [(t, la, lo, cum - off) for (t, la, lo, cum) in pts[a:b + 1]]
    return trimmed, info


def find_pockets(pts: list[tuple], max_kmh: float, min_sec: float) -> list[dict]:
    """Return contiguous slow stretches as pocket dicts."""
    pockets: list[dict] = []
    run: list[tuple] = []  # (lat, lon, dist_m, dt_s)

    def flush() -> None:
        if not run:
            return
        dur = sum(r[3] for r in run)
        dist = run[-1][2] - run[0][2]
        if dur >= min_sec:
            speed = (dist / dur) * 3.6 if dur else 0.0
            mid = run[len(run) // 2]
            pockets.append({
                "dist_km_along": round(run[0][2] / 1000, 2),
                "lat": round(mid[0], 6), "lon": round(mid[1], 6),
                "duration_s": round(dur),
                "mean_speed_kmh": round(speed, 1),
            })

    for i in range(1, len(pts)):
        t0, _, _, d0 = pts[i - 1]
        t1, lat, lon, d1 = pts[i]
        dt_s = (t1 - t0).total_seconds()
        if dt_s <= 0:
            continue
        kmh = ((d1 - d0) / dt_s) * 3.6
        if kmh <= max_kmh:
            run.append((lat, lon, d1, dt_s))
        else:
            flush()
            run = []
    flush()
    return pockets


def summarize(pts: list[tuple], pockets: list[dict], path: str,
              direction: str, partial: bool, trim: dict) -> dict:
    start, end = pts[0][0], pts[-1][0]
    dur_s = (end - start).total_seconds()
    dist_km = pts[-1][3] / 1000
    slow_s = sum(p["duration_s"] for p in pockets)
    return {
        "date": start.strftime("%Y-%m-%d"),
        "start_time": start.strftime("%H:%M:%S"),
        "end_time": end.strftime("%H:%M:%S"),
        "direction": direction,
        "partial": partial,
        "duration_min": round(dur_s / 60, 1),
        "distance_km": round(dist_km, 2),
        "mean_speed_kmh": round(dist_km / (dur_s / 3600), 1) if dur_s else 0.0,
        "slow_time_min": round(slow_s / 60, 1),
        "n_pockets": len(pockets),
        "trim_head_s": trim["head_s"],
        "trim_tail_s": trim["tail_s"],
        "gpx_file": os.path.basename(path),
    }


def append(path: str, fields: list[str], rows: list[dict]) -> None:
    os.makedirs(DATA, exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def route_path(direction: str) -> str:
    return os.path.join(DATA, f"{direction}_route.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gpx", nargs="+", help="GPX trace file(s)")
    ap.add_argument("--min-pocket-sec", type=float, default=30,
                    help="ignore slow runs shorter than this (default 30s)")
    ap.add_argument("--rebuild-route", action="store_true",
                    help="rebuild each direction's reference route axis from the "
                         "longest trace in this batch")
    args = ap.parse_args()

    cfg = load_cfg()
    max_kmh = cfg.get("pocket_speed_kmh", 10)
    partial_gap = cfg.get("partial_gap_m", 400)
    drive_kmh = cfg.get("drive_speed_kmh", 10)
    smooth_n = cfg.get("trim_smooth_points", 5)
    section_bin = cfg.get("section_bin_m", 200)
    stations = cfg.get("stations")
    station_radius = cfg.get("station_radius_m", 150)
    tz = parse_offset(cfg["timezone_offset"])

    # pass 1: read, clamp/trim, classify
    recs = []
    for path in args.gpx:
        raw = read_points(path, tz)
        if len(raw) < 2:
            print(f"skip {path}: no timed points", file=sys.stderr)
            continue
        direction = classify(raw[0][1], raw[0][2], cfg)[0]
        if stations:
            o_st, d_st = stations_for(direction, stations)
            pts, trim = clamp_to_stations(raw, o_st, d_st, station_radius)
            partial = max(trim["origin_gap"], trim["dest_gap"]) > partial_gap
        else:
            pts, trim = trim_to_drive(raw, drive_kmh, smooth_n)
            partial = classify(pts[0][1], pts[0][2], cfg)[1] > partial_gap
        if len(pts) < 2:
            print(f"skip {path}: not enough driving", file=sys.stderr)
            continue
        recs.append({"path": path, "pts": pts, "trim": trim,
                     "direction": direction, "partial": partial})

    # establish the reference route axis per direction (the longest full trace),
    # reused once built so the distance axis stays stable as new traces arrive
    os.makedirs(DATA, exist_ok=True)
    routes = {}
    for direction in {r["direction"] for r in recs}:
        if not args.rebuild_route and os.path.exists(route_path(direction)):
            with open(route_path(direction)) as f:
                routes[direction] = json.load(f)
            continue
        full = [r for r in recs if r["direction"] == direction and not r["partial"]]
        if not full:
            continue
        ref = max(full, key=lambda r: r["pts"][-1][3])
        routes[direction] = build_route(ref["pts"])
        with open(route_path(direction), "w") as f:
            json.dump(routes[direction], f)
        print(f"built {direction} route axis "
              f"({routes[direction]['s'][-1] / 1000:.2f} km) from "
              f"{os.path.basename(ref['path'])}")

    # pass 2: summarise, pockets, sections
    for r in recs:
        pts, direction, partial, trim = r["pts"], r["direction"], r["partial"], r["trim"]
        pockets = find_pockets(pts, max_kmh, args.min_pocket_sec)
        summary = summarize(pts, pockets, r["path"], direction, partial, trim)
        append(os.path.join(DATA, f"{direction}_summary.csv"), SUMMARY_FIELDS, [summary])
        append(os.path.join(DATA, f"{direction}_pockets.csv"), POCKET_FIELDS,
               [{"date": summary["date"], **p} for p in pockets])
        if direction in routes:  # partials still cover valid sections of the axis
            sections = compute_sections(pts, routes[direction], section_bin)
            append(os.path.join(DATA, f"{direction}_sections.csv"), SECTION_FIELDS,
                   [{"date": summary["date"], "start_time": summary["start_time"], **s}
                    for s in sections])
        flag = " [PARTIAL]" if partial else ""
        print(f"{summary['date']} {summary['start_time']} {direction}{flag}: "
              f"{summary['duration_min']} min, {summary['distance_km']} km, "
              f"{summary['n_pockets']} pockets ({summary['slow_time_min']} min slow) "
              f"| trimmed {trim['head_s']}s/{trim['head_m']}m head, "
              f"{trim['tail_s']}s/{trim['tail_m']}m tail")
    return 0


if __name__ == "__main__":
    sys.exit(main())
