#!/usr/bin/env python3
"""Overlay every commute trace of one vehicle+direction on the shared route axis.

Each trace is gate-clamped and projected onto the direction's reference route;
only traces covering >=80% of the route qualify (fragments would collapse the
common stretch). All clocks are re-zeroed at the start of the common stretch, so
the curves compare the identical piece of road even when some traces begin
mid-route (e.g. dashcam cold starts). Two panels: position-time for every drive,
and each drive's time delta against the first (earliest) drive.

Few drives get a legend; many get a light->dark date colormap with a colorbar.

Usage:
    python3 overlay_traces.py --bike honda-brio --direction onward
    python3 overlay_traces.py --bike honda-jazz --direction return
"""

import argparse
import glob
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm, colors as mcolors

import ingest_gpx as ig

DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bike", required=True)
    ap.add_argument("--direction", required=True, choices=("onward", "return"))
    ap.add_argument("--out", default=os.path.join(DIR, "plots"))
    ap.add_argument("--min-cover", type=float, default=0.8,
                    help="fraction of the route a trace must span (default 0.8)")
    args = ap.parse_args()

    cfg = ig.load_cfg()
    tz = ig.parse_offset(cfg["timezone_offset"])
    st, R = cfg["stations"], cfg.get("station_radius_m", 50)
    mx = cfg.get("sanity_max_kmh", 150)
    dirn = args.direction
    rt = json.load(open(ig.route_path(dirn)))
    tot = rt["s"][-1]

    tr = []
    for f in sorted(glob.glob(os.path.join(DIR, "gps", "office-route",
                                           f"*-{args.bike}.gpx"))):
        raw = ig.read_points(f, tz)
        d = ig.classify(raw[0][1], raw[0][2], cfg, raw[-1][1], raw[-1][2])[0]
        if d != dirn:
            continue
        pts, _ = ig.clamp_to_stations(raw, *ig.stations_for(d, st), R)
        s = ig.project_arc_length(rt, pts, mx)
        if (s.max() - s.min()) < args.min_cover * tot:
            continue
        x = s / 1000.0 if dirn == "onward" else (tot - s) / 1000.0
        t = np.array([(p[0] - pts[0][0]).total_seconds() for p in pts]) / 60.0
        tr.append((pts[0][0], x, t))
    if len(tr) < 2:
        raise SystemExit(f"only {len(tr)} qualifying {args.bike} {dirn} traces")

    x_lo = max(x.min() for _, x, _ in tr) + 0.02
    x_hi = min(x.max() for _, x, _ in tr) - 0.02
    xg = np.arange(x_lo, x_hi, 0.01)

    def rez(x, t):
        o = np.argsort(x)
        tg = np.interp(xg, x[o], t[o])
        # zero at the drive-start side of the common stretch
        return tg - (tg[0] if dirn == "onward" else tg[-1])

    d0 = tr[0][0].date()
    dN = max(1, (tr[-1][0].date() - d0).days)
    norm = mcolors.Normalize(0, dN)
    cmap = cm.get_cmap("Blues" if dirn == "onward" else "Reds")
    few = len(tr) <= 6

    fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    a1, a2 = axes
    ref = None
    for t0, x, t in tr:
        tg = rez(x, t)
        c = cmap(0.25 + 0.75 * norm((t0.date() - d0).days))
        total = tg[0] if dirn == "return" else tg[-1]
        lab = f"{t0:%m-%d} dep {t0:%H:%M} — {total:.1f} min" if few else None
        a1.plot(xg, tg, color=c, lw=1.5 if few else 1.0, label=lab)
        if ref is None:
            ref = tg
        else:
            a2.plot(xg, tg - ref, color=c, lw=1.3 if few else 0.9,
                    label=(f"{t0:%m-%d} vs first" if few else None))
    a2.axhline(0, color="#333", lw=0.7)
    if few:
        a1.legend(fontsize=9)
        a2.legend(fontsize=9)
    else:
        sm = cm.ScalarMappable(norm=norm, cmap=cmap)
        cb = fig.colorbar(sm, ax=list(axes), fraction=0.03, pad=0.02)
        cb.set_label(f"days since first trace ({d0})")
    a1.set_ylabel("time over common stretch (min)")
    a1.set_title(f"{args.bike} {'mornings' if dirn == 'onward' else 'returns'} "
                 f"overlaid ({len(tr)} drives)"
                 + ("  (drive runs right→left)" if dirn == "return" else ""))
    a2.set_ylabel("Δ time vs first drive (min)")
    a2.set_xlabel("position (km from home)")
    for a in axes:
        a.grid(alpha=0.3)
    os.makedirs(args.out, exist_ok=True)
    leg = "mornings" if dirn == "onward" else "returns"
    out = os.path.join(args.out, f"{args.bike}_{leg}_overlay.svg")
    if not few:
        pass
    fig.savefig(out)
    print(f"wrote {out} ({len(tr)} drives, common {x_lo:.2f}-{x_hi:.2f} km)")


if __name__ == "__main__":
    main()
