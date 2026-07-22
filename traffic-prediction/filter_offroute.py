#!/usr/bin/env python3
"""Salvage traces that took a partly different route.

Some drives share most of the commute but detour onto a different road for a
stretch (a shortcut, a diversion). Projected onto the fixed reference route
axis, that off-route stretch produces garbage section times — a frozen "stall"
bin plus impossibly fast bins where the arc-length jumps back on rejoin.

This is a *preprocessing* step (the core ingest is left untouched). It does ONE
thing: find where the trace strays off the reference route by more than
--corridor metres for a real distance (>= --min-detour along the route, so a
lone GPS spike doesn't count), and CUT the trace there. Each remaining on-route
run is written as its own GPX. Because the pieces are split at the detour (not
bridged across it), ingest treats each as a normal/partial trace and computes
valid section times only where the drive actually followed the route.

Everything else is preserved. Clamping to the start/end stations, head/tail
trimming, partial detection — all of that stays with ingest, so:

  * a trace with no real detour is copied through **verbatim** (byte-for-byte,
    elevation and all), just renamed with the vehicle tag;
  * a split trace keeps every original point (elevation included) except the
    off-route detour itself — the full run up to the station is retained for
    ingest to clamp.

Output filenames are `<YYYYMMDD>-<HHMMSS>-<bike>.gpx`. A verbatim copy keeps the
original file's timestamp; each split piece takes the time of its first point
(so the pieces get distinct, truthful timestamps).

Usage:
    python3 filter_offroute.py --bike honda-jazz --out gps/ new/*.gpx
"""

import argparse
import json
import os
import shutil
import sys

import gpxpy
import gpxpy.gpx
import numpy as np

import ingest_gpx as ig


def _points(gpx):
    """All track points across every segment, in order."""
    return [p for t in gpx.tracks for s in t.segments for p in s.points
            if p.time is not None]


def detours(pts, route, corridor_m, min_detour_m, min_depth_m, max_kmh):
    """Index ranges [i, j) that are a real diversion onto a different road: the
    trace leaves the corridor (> corridor_m off the reference route) for at least
    min_detour_m along the route AND peaks at least min_depth_m off it. The depth
    test is what separates a genuine parallel-road detour (which mis-projects into
    stall/jump artifacts) from merely driving a lane or slightly different line out
    of a station — that stays offset by a modest, roughly-constant amount and
    still projects onto the right along-route position, so it is kept.
    Returns the ranges and the projected arc-length array (for reporting)."""
    tuples = [(p.time, p.latitude, p.longitude) for p in pts]
    s = ig.project_arc_length(route, tuples, max_kmh)
    rx, ry = np.array(route["x"]), np.array(route["y"])
    px, py = ig._local_xy([p.latitude for p in pts], [p.longitude for p in pts],
                          route["lat0"], route["lon0"])
    dev = np.array([np.sqrt(float(np.min((rx - px[i]) ** 2 + (ry - py[i]) ** 2)))
                    for i in range(len(pts))])
    off = dev > corridor_m
    out, i, n = [], 0, len(pts)
    while i < n:
        if off[i]:
            j = i
            while j < n and off[j]:
                j += 1
            if (abs(float(s[j - 1] - s[i])) >= min_detour_m
                    and dev[i:j].max() >= min_depth_m):
                out.append((i, j))
            i = j
        else:
            i += 1
    return out, s


def on_route_runs(n, det_ranges):
    """Complement of the detour ranges over [0, n): the on-route runs to keep."""
    runs, cur = [], 0
    for a, b in det_ranges:
        if a > cur:
            runs.append((cur, a))
        cur = b
    if cur < n:
        runs.append((cur, n))
    return runs


def write_gpx(seg_pts, path):
    """Write gpxpy track points to a minimal GPX track, preserving elevation
    and the original (untouched) timestamps."""
    gpx = gpxpy.gpx.GPX()
    trk = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(trk)
    seg = gpxpy.gpx.GPXTrackSegment()
    trk.segments.append(seg)
    for p in seg_pts:
        seg.points.append(gpxpy.gpx.GPXTrackPoint(
            p.latitude, p.longitude, elevation=p.elevation, time=p.time))
    with open(path, "w") as f:
        f.write(gpx.to_xml())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gpx", nargs="+", help="GPX trace file(s) to filter")
    ap.add_argument("--bike", required=True, help="vehicle tag for output names")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--corridor", type=float, default=60,
                    help="metres off the reference route before a point counts "
                         "as off-route (default 60)")
    ap.add_argument("--min-detour", type=float, default=300,
                    help="an off-route stretch shorter than this along the route "
                         "is treated as GPS noise and kept, not cut (default 300 m)")
    ap.add_argument("--min-depth", type=float, default=200,
                    help="an off-route stretch must peak at least this far off the "
                         "route to be cut; a shallower, roughly-constant offset (a "
                         "lane / different line out of a station) is kept, since it "
                         "still projects onto the right position (default 200 m)")
    ap.add_argument("--min-seg-m", type=float, default=400,
                    help="drop a leftover on-route run shorter than this along "
                         "the route (default 400 m)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the split without writing files")
    args = ap.parse_args()

    cfg = ig.load_cfg()
    tz = ig.parse_offset(cfg["timezone_offset"])
    stations = cfg["stations"]
    max_kmh = cfg.get("sanity_max_kmh", 150)
    os.makedirs(args.out, exist_ok=True)

    routes = {}
    for d in ("onward", "return"):
        p = ig.route_path(d)
        if os.path.exists(p):
            routes[d] = json.load(open(p))

    written = 0
    for path in args.gpx:
        with open(path) as f:
            gpx = gpxpy.parse(f)
        pts = _points(gpx)
        if len(pts) < 2:
            print(f"skip {path}: no timed points", file=sys.stderr)
            continue
        first = pts[0].time.astimezone(tz)
        direction = ig.classify(pts[0].latitude, pts[0].longitude, cfg)[0]
        route = routes.get(direction)
        if route is None:
            print(f"skip {path}: no {direction} reference route", file=sys.stderr)
            continue
        det, s = detours(pts, route, args.corridor, args.min_detour,
                         args.min_depth, max_kmh)
        base = os.path.basename(path)[:15]              # YYYYMMDD-HHMMSS

        if not det:                                      # clean — copy verbatim
            out = os.path.join(args.out, f"{base}-{args.bike}.gpx")
            print(f"{base} {direction}: clean, copied verbatim ({len(pts)} pts)")
            if not args.dry_run:
                shutil.copyfile(path, out)
                written += 1
            continue

        runs = on_route_runs(len(pts), det)
        kept = [(a, b) for a, b in runs
                if abs(float(s[b - 1] - s[a])) >= args.min_seg_m]
        dropped = len(pts) - sum(b - a for a, b in kept)
        spans = ", ".join(f"{abs(s[b-1]-s[a])/1000:.1f}km" for a, b in kept)
        print(f"{base} {direction}: {len(det)} detour(s), split into "
              f"{len(kept)} segment(s) [{spans}], {dropped} detour pts removed")
        for a, b in kept:
            hhmmss = pts[a].time.astimezone(tz).strftime("%H%M%S")
            day = pts[a].time.astimezone(tz).strftime("%Y%m%d")
            out = os.path.join(args.out, f"{day}-{hhmmss}-{args.bike}.gpx")
            if not args.dry_run:
                write_gpx(pts[a:b], out)
                written += 1
    if not args.dry_run:
        print(f"\nwrote {written} file(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
