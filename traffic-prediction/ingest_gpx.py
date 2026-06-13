#!/usr/bin/env python3
"""Turn a recorded GPX trace of the actual commute into ground-truth data:
real travel time, a speed-vs-distance profile, and the locations where you
actually crawled (the "pockets"). Appends to two CSVs:

  data/gpx_summary.csv  one row per trace (date, duration, mean speed, #pockets)
  data/gpx_pockets.csv  one row per slow stretch (location, duration, speed)

A pocket is a contiguous run slower than pocket_speed_kmh (config.json) lasting
at least --min-pocket-sec seconds, so brief signal stops don't all count.

Usage:
    python3 ingest_gpx.py path/to/20260613-173000.gpx [more.gpx ...]
"""

import argparse
import csv
import json
import os
import sys

import gpxpy

DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, "data")
CFG_PATH = os.path.join(DIR, "config.json")

SUMMARY_FIELDS = [
    "date", "start_time", "end_time", "duration_min", "distance_km",
    "mean_speed_kmh", "slow_time_min", "n_pockets", "gpx_file",
]
POCKET_FIELDS = [
    "date", "dist_km_along", "lat", "lon",
    "duration_s", "mean_speed_kmh",
]


def load_cfg() -> dict:
    with open(CFG_PATH) as f:
        return json.load(f)


def read_points(path: str) -> list[tuple]:
    """Flatten a GPX file to (time, lat, lon, cum_dist_m) tuples."""
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
                pts.append((p.time, p.latitude, p.longitude, cum))
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


def summarize(pts: list[tuple], pockets: list[dict], path: str) -> dict:
    start, end = pts[0][0], pts[-1][0]
    dur_s = (end - start).total_seconds()
    dist_km = pts[-1][3] / 1000
    slow_s = sum(p["duration_s"] for p in pockets)
    return {
        "date": start.strftime("%Y-%m-%d"),
        "start_time": start.strftime("%H:%M:%S"),
        "end_time": end.strftime("%H:%M:%S"),
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

    for path in args.gpx:
        pts = read_points(path)
        if len(pts) < 2:
            print(f"skip {path}: no timed points", file=sys.stderr)
            continue
        pockets = find_pockets(pts, max_kmh, args.min_pocket_sec)
        summary = summarize(pts, pockets, path)
        append(os.path.join(DATA, "gpx_summary.csv"), SUMMARY_FIELDS, [summary])
        append(os.path.join(DATA, "gpx_pockets.csv"), POCKET_FIELDS,
               [{"date": summary["date"], **p} for p in pockets])
        print(f"{summary['date']} {summary['start_time']}: "
              f"{summary['duration_min']} min, {summary['distance_km']} km, "
              f"{summary['n_pockets']} pockets ({summary['slow_time_min']} min slow)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
