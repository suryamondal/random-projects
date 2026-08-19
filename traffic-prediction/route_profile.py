#!/usr/bin/env python3
"""Geometric profile of each route (lat, lon, altitude) from ALL recorded traces.

For every direction, every office-route trace is gate-clamped, projected onto
the reference route axis, and its points (with GPS elevation where the source
recorded it) are pooled into fixed arc-length bins (default 3 m). Per bin the profile keeps
the MEDIAN lat/lon/elevation — where the pool covers a bin, ~50 independent
drives put tens of samples in it, so the median position is far more precise
than any single GPS fix and the elevation median tames the +/-10-20 m per-fix
noise. At 3 m a 1 Hz logger skips bins while moving fast; those stay empty and
fill in as more traces accumulate — the frame is meant to be rebuilt.

Contract: an uncovered bin is an ABSENT row, never a zero — s_m simply has
gaps. Consumers that need continuity may interpolate between adjacent covered
bins; this tool never does it for them.

Output (rebuilt from scratch on every run, so it absorbs new traces):

  data/<dir>_route_profile.csv with columns
    s_m          arc-length along the reference route (bin start)
    lat, lon     median position of the road at this s
    ele_m        median GPS elevation (empty if no source carried elevation)
    n, n_ele     samples behind the position / elevation medians
    lateral_sd_m robust spread of the pooled points across the road
                 (1.4826*MAD of the distance to the bin median — lane spread +
                 GPS noise; a wide value can flag a junction or parallel lanes)

Points farther than --corridor (default 60 m) from the reference route are
excluded so detours never pollute the geometry. A verification figure goes to
plots/route_profile.svg (elevation & coverage vs distance-from-home).

Usage:
    python3 route_profile.py            # rebuild both directions
"""

import argparse
import glob
import json
import os

import gpxpy
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import ingest_gpx as ig

DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, "data")
PLOTS = os.path.join(DIR, "plots")


def points_with_ele(path, tz):
    """(time, lat, lon, ele-or-nan) per trackpoint."""
    with open(path) as f:
        gpx = gpxpy.parse(f)
    out = []
    for trk in gpx.tracks:
        for seg in trk.segments:
            for p in seg.points:
                if p.time is None:
                    continue
                out.append((p.time.astimezone(tz), p.latitude, p.longitude,
                            p.elevation if p.elevation is not None else np.nan))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bin-m", type=float, default=3.0)
    ap.add_argument("--corridor", type=float, default=60.0)
    args = ap.parse_args()

    cfg = ig.load_cfg()
    tz = ig.parse_offset(cfg["timezone_offset"])
    st, R = cfg["stations"], cfg.get("station_radius_m", 50)
    mx = cfg.get("sanity_max_kmh", 150)

    fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex="col")
    for col, dirn in enumerate(("onward", "return")):
        rt = json.load(open(ig.route_path(dirn)))
        tot = rt["s"][-1]
        rx, ry = np.array(rt["x"]), np.array(rt["y"])
        edges = np.arange(0, tot + args.bin_m, args.bin_m)
        nb = len(edges) - 1
        acc = [[] for _ in range(nb)]          # (lat, lon, ele) tuples per bin

        n_traces = 0
        for f in sorted(glob.glob(os.path.join(DIR, "gps", "office-route", "*.gpx"))):
            raw = ig.read_points(f, tz)
            if len(raw) < 20:
                continue
            d = ig.classify(raw[0][1], raw[0][2], cfg, raw[-1][1], raw[-1][2])[0]
            if d != dirn:
                continue
            ele_pts = points_with_ele(f, tz)
            # clamp indices via times: clamp_to_stations works on ig tuples
            pts, _ = ig.clamp_to_stations(raw, *ig.stations_for(d, st), R)
            t0, t1 = pts[0][0], pts[-1][0]
            kept = [(t, la, lo, el) for t, la, lo, el in ele_pts if t0 <= t <= t1]
            if len(kept) < 20:
                continue
            tup = [(t, la, lo, 0.0) for t, la, lo, _ in kept]
            s = ig.project_arc_length(rt, tup, mx)
            px, py = ig._local_xy([k[1] for k in kept], [k[2] for k in kept],
                                  rt["lat0"], rt["lon0"])
            n_traces += 1
            for i, (t, la, lo, el) in enumerate(kept):
                dev = np.sqrt(np.min((rx - px[i]) ** 2 + (ry - py[i]) ** 2))
                if dev > args.corridor:
                    continue
                b = int(s[i] // args.bin_m)
                if 0 <= b < nb:
                    acc[b].append((la, lo, el))

        rows = []
        for b in range(nb):
            if not acc[b]:
                continue
            a = np.array(acc[b], dtype=float)
            lat, lon = np.median(a[:, 0]), np.median(a[:, 1])
            ele_v = a[:, 2][np.isfinite(a[:, 2])]
            ele = np.median(ele_v) if len(ele_v) else np.nan
            # robust lateral spread about the median position
            k = np.cos(np.radians(lat))
            dx = (a[:, 1] - lon) * k * 111320
            dy = (a[:, 0] - lat) * 111320
            r = np.hypot(dx, dy)
            sd = 1.4826 * np.median(np.abs(r - np.median(r)))
            rows.append((edges[b], lat, lon, ele, len(a), len(ele_v), sd))

        out = os.path.join(DATA, f"{dirn}_route_profile.csv")
        with open(out, "w") as f:
            f.write("s_m,lat,lon,ele_m,n,n_ele,lateral_sd_m\n")
            for s_m, lat, lon, ele, n, ne, sd in rows:
                e = f"{ele:.1f}" if np.isfinite(ele) else ""
                f.write(f"{s_m:.0f},{lat:.6f},{lon:.6f},{e},{n},{ne},{sd:.1f}\n")
        med_n = int(np.median([r[4] for r in rows]))
        print(f"{dirn}: {len(rows)}/{nb} bins from {n_traces} traces, "
              f"median {med_n} samples/bin -> {out}")

        xs = np.array([r[0] for r in rows]) / 1000.0
        xkm = xs if dirn == "onward" else (tot / 1000.0 - xs)
        ele = np.array([r[3] for r in rows])
        n = np.array([r[4] for r in rows])
        axes[0][col].plot(xkm, ele, ".", ms=2, color="#2e4a62")
        axes[0][col].set_title(f"{dirn}: elevation profile")
        axes[0][col].set_ylabel("ele (m, GPS median)")
        axes[1][col].plot(xkm, n, lw=0.8, color="#4c956c")
        axes[1][col].set_ylabel("samples per bin")
        axes[1][col].set_xlabel("km from home")
        for a_ in (axes[0][col], axes[1][col]):
            a_.grid(alpha=0.3)
    fig.tight_layout()
    os.makedirs(PLOTS, exist_ok=True)
    fig.savefig(os.path.join(PLOTS, "route_profile.svg"))
    print(f"wrote {os.path.join(PLOTS, 'route_profile.svg')}")


if __name__ == "__main__":
    main()
