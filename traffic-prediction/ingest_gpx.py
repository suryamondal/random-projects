#!/usr/bin/env python3
"""Turn recorded GPX traces of the actual commute into ground-truth data:
real travel time, and the locations where you actually crawled (the "pockets").

Each trace is auto-classified by direction from where it *starts*:

  evening  office -> home   (start nearer the office)
  morning  home -> office   (start nearer home)

so you can just throw the whole folder at it and the two commutes stay in
separate pipelines. Per direction it appends two CSVs:

  data/<dir>_summary.csv  one row per trace (date, duration, #pockets, ...)
  data/<dir>_pockets.csv  one row per slow stretch (location, duration, speed)

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

DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, "data")
CFG_PATH = os.path.join(DIR, "config.json")

SUMMARY_FIELDS = [
    "date", "start_time", "end_time", "direction", "partial",
    "duration_min", "distance_km", "mean_speed_kmh",
    "slow_time_min", "n_pockets", "gpx_file",
]
POCKET_FIELDS = [
    "date", "dist_km_along", "lat", "lon",
    "duration_s", "mean_speed_kmh",
]


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

    Nearer the office -> 'evening' (office->home); nearer home -> 'morning'.
    """
    o, d = cfg["origin"], cfg["destination"]
    d_office = haversine(lat, lon, o["lat"], o["lon"])
    d_home = haversine(lat, lon, d["lat"], d["lon"])
    if d_office <= d_home:
        return "evening", d_office
    return "morning", d_home


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
              direction: str, partial: bool) -> dict:
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gpx", nargs="+", help="GPX trace file(s)")
    ap.add_argument("--min-pocket-sec", type=float, default=30,
                    help="ignore slow runs shorter than this (default 30s)")
    args = ap.parse_args()

    cfg = load_cfg()
    max_kmh = cfg.get("pocket_speed_kmh", 10)
    partial_gap = cfg.get("partial_gap_m", 400)
    tz = parse_offset(cfg["timezone_offset"])

    for path in args.gpx:
        pts = read_points(path, tz)
        if len(pts) < 2:
            print(f"skip {path}: no timed points", file=sys.stderr)
            continue
        direction, origin_gap = classify(pts[0][1], pts[0][2], cfg)
        partial = origin_gap > partial_gap
        pockets = find_pockets(pts, max_kmh, args.min_pocket_sec)
        summary = summarize(pts, pockets, path, direction, partial)
        append(os.path.join(DATA, f"{direction}_summary.csv"), SUMMARY_FIELDS, [summary])
        append(os.path.join(DATA, f"{direction}_pockets.csv"), POCKET_FIELDS,
               [{"date": summary["date"], **p} for p in pockets])
        flag = " [PARTIAL]" if partial else ""
        print(f"{summary['date']} {summary['start_time']} {direction}{flag}: "
              f"{summary['duration_min']} min, {summary['distance_km']} km, "
              f"{summary['n_pockets']} pockets ({summary['slow_time_min']} min slow)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
