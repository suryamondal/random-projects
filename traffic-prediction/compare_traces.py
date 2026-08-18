#!/usr/bin/env python3
"""Overlap two commute traces on the shared route axis.

Both traces are clamped to the gates and projected onto the direction's
reference route, so x is *position* (projected arc-length, localized GPS error
only — not cumulative path length). Two panels: position-time for both drives
(each zeroed at its own gate exit), and the pointwise time delta A - B.

Usage:
    python3 compare_traces.py <traceA.gpx> <traceB.gpx> [--label-a ME --label-b HIM]
"""

import argparse
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import ingest_gpx as ig

DIR = os.path.dirname(os.path.abspath(__file__))
COLORS = ("#d1495b", "#2a9d8f")


def series(path, cfg, tz):
    raw = ig.read_points(path, tz)
    d = ig.classify(raw[0][1], raw[0][2], cfg, raw[-1][1], raw[-1][2])[0]
    rt = json.load(open(ig.route_path(d)))
    pts, _ = ig.clamp_to_stations(raw, *ig.stations_for(d, cfg["stations"]),
                                  cfg.get("station_radius_m", 50))
    s = ig.project_arc_length(rt, pts, cfg.get("sanity_max_kmh", 150))
    x = s / 1000.0 if d == "onward" else (rt["s"][-1] - s) / 1000.0
    t = np.array([(p[0] - pts[0][0]).total_seconds() for p in pts]) / 60.0
    return d, x, t, pts[0][0]


def interp_sorted(xg, x, y):
    o = np.argsort(x)
    return np.interp(xg, x[o], y[o])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--label-a", default=None)
    ap.add_argument("--label-b", default=None)
    ap.add_argument("--out", default=os.path.join(DIR, "plots"))
    args = ap.parse_args()

    cfg = ig.load_cfg()
    tz = ig.parse_offset(cfg["timezone_offset"])
    da, xa, ta, t0a = series(args.a, cfg, tz)
    db, xb, tb, t0b = series(args.b, cfg, tz)
    if da != db:
        raise SystemExit(f"traces are different directions ({da} vs {db})")
    la = args.label_a or os.path.basename(args.a).replace(".gpx", "")
    lb = args.label_b or os.path.basename(args.b).replace(".gpx", "")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    ax1.plot(xa, ta, color=COLORS[0], lw=1.4,
             label=f"{la} ({t0a:%m-%d %H:%M}) {ta[-1]:.1f} min")
    ax1.plot(xb, tb, color=COLORS[1], lw=1.4,
             label=f"{lb} ({t0b:%m-%d %H:%M}) {tb[-1]:.1f} min")
    ax1.set_ylabel("time since gate exit (min)")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.set_title(f"{da}: position = projected route arc-length"
                  + ("  (drive runs right→left)" if da == "return" else ""))

    lo = max(xa.min(), xb.min()) + 0.05
    hi = min(xa.max(), xb.max()) - 0.05
    xg = np.arange(lo, hi, 0.01)
    dt_ = interp_sorted(xg, xa, ta) - interp_sorted(xg, xb, tb)
    ax2.plot(xg, dt_, color="#b5651d", lw=1.2)
    ax2.axhline(0, color="#333", lw=0.7)
    end = dt_[-1] if da == "onward" else dt_[0]
    ax2.text(0.02, 0.9, f"end gap {end:+.1f} min", transform=ax2.transAxes, fontsize=9)
    ax2.set_ylabel(f"Δ time = {la} − {lb} (min)")
    ax2.set_xlabel("position (km from home)")
    for ax in (ax1, ax2):
        ax.grid(alpha=0.3)
    os.makedirs(args.out, exist_ok=True)
    sa = os.path.basename(args.a)[:15]
    sb = os.path.basename(args.b)[:15]
    out = os.path.join(args.out, f"compare_{sa}_vs_{sb}.svg")
    fig.tight_layout()
    fig.savefig(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
