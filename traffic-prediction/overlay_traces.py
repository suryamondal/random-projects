#!/usr/bin/env python3
"""Overlay every commute trace of one vehicle+direction on the shared route axis.

Each trace is gate-clamped and projected onto the direction's reference route;
only traces covering >=80% of the route qualify (fragments would collapse the
common stretch). All clocks are re-zeroed at the start of the common stretch, so
the curves compare the identical piece of road even when some traces begin
mid-route (e.g. dashcam cold starts). Two panels: position-time for every drive,
and each drive's time delta against a reference.

Alignment (--align):
  start    clocks re-zeroed at the start of the COMMON stretch (default)
  arrival  clocks re-zeroed at arrival; each trace drawn over its OWN coverage,
           so a late-starting trace no longer truncates the others

Reference for the delta panel (--ref):
  first    the earliest drive of this vehicle (default)
  best     the fastest full track (>=95% route coverage) from the --ref-bikes
           pool, drawn dashed on both panels

Few drives get a legend; many get a light->dark date colormap with a colorbar.

Usage:
    python3 overlay_traces.py --bike honda-brio --direction onward
    python3 overlay_traces.py --bike honda-jazz --direction onward \
        --align arrival --ref best --ref-bikes honda-jazz,honda-brio \
        --top-ylim=-25,2 --delta-ylim=-6,1
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
    ap.add_argument("--align", choices=("start", "arrival"), default="start")
    ap.add_argument("--ref", choices=("first", "best"), default="first")
    ap.add_argument("--ref-bikes", default=None,
                    help="comma list of vehicles for the --ref best pool "
                         "(default: just --bike)")
    ap.add_argument("--top-ylim", default=None, help="y range top panel, 'lo,hi'")
    ap.add_argument("--delta-ylim", default=None, help="y range delta panel, 'lo,hi'")
    args = ap.parse_args()

    cfg = ig.load_cfg()
    tz = ig.parse_offset(cfg["timezone_offset"])
    st, R = cfg["stations"], cfg.get("station_radius_m", 50)
    mx = cfg.get("sanity_max_kmh", 150)
    dirn = args.direction
    rt = json.load(open(ig.route_path(dirn)))
    tot = rt["s"][-1]

    def load(bike):
        out = []
        for f in sorted(glob.glob(os.path.join(DIR, "gps", "office-route",
                                               f"*-{bike}.gpx"))):
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
            out.append((pts[0][0], x, t))
        return out

    tr = load(args.bike)
    if len(tr) < 2:
        raise SystemExit(f"only {len(tr)} qualifying {args.bike} {dirn} traces")

    x_lo = max(x.min() for _, x, _ in tr) + 0.02
    x_hi = min(x.max() for _, x, _ in tr) - 0.02
    xg_common = np.arange(x_lo, x_hi, 0.01)

    def rez(x, t):
        """(grid, arrival/start-zeroed time) — common grid for start alignment,
        the trace's own coverage for arrival alignment."""
        o = np.argsort(x)
        if args.align == "start":
            tg = np.interp(xg_common, x[o], t[o])
            return xg_common, tg - (tg[0] if dirn == "onward" else tg[-1])
        g = np.arange(x[o].min() + 0.01, x[o].max() - 0.01, 0.01)
        tg = np.interp(g, x[o], t[o])
        # zero at the arrival side (office for onward, home for return)
        return g, tg - (tg[-1] if dirn == "onward" else tg[0])

    # reference curve for the delta panel
    if args.ref == "best":
        pool_bikes = (args.ref_bikes.split(",") if args.ref_bikes else [args.bike])
        pool = [r for b in pool_bikes for r in load(b)
                if (r[1].max() - r[1].min()) >= 0.95 * tot / 1000]
        if not pool:
            raise SystemExit("no >=95%-coverage track in the reference pool")
        ref_trace = min(pool, key=lambda r: r[2][-1] - r[2][0])
    else:
        ref_trace = tr[0]
    xr, tref = rez(ref_trace[1], ref_trace[2])

    d0 = tr[0][0].date()
    dN = max(1, (tr[-1][0].date() - d0).days)
    norm = mcolors.Normalize(0, dN)
    cmap = cm.get_cmap("Blues" if dirn == "onward" else "Reds")
    few = len(tr) <= 6

    fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    a1, a2 = axes
    for t0, x, t in tr:
        g, tg = rez(x, t)
        c = cmap(0.25 + 0.75 * norm((t0.date() - d0).days))
        total = max(abs(tg[0]), abs(tg[-1]))
        lab = f"{t0:%m-%d} dep {t0:%H:%M} — {total:.1f} min" if few else None
        a1.plot(g, tg, color=c, lw=1.5 if few else 1.0, label=lab)
        lo, hi = max(g.min(), xr.min()), min(g.max(), xr.max())
        m = (g >= lo) & (g <= hi)
        dref = np.interp(g[m], xr, tref)
        if not (args.ref == "first" and t0 is tr[0][0]):
            a2.plot(g[m], tg[m] - dref, color=c, lw=1.3 if few else 0.9,
                    label=(f"{t0:%m-%d}" if few else None))
    if args.ref == "best":
        a1.plot(xr, tref, color="#e07b39", lw=2.0, ls="--",
                label=f"ref (best full): {ref_trace[0]:%m-%d} — "
                      f"{max(abs(tref[0]), abs(tref[-1])):.1f} min")
    a2.axhline(0, color="#e07b39" if args.ref == "best" else "#333",
               lw=1.0, ls="--" if args.ref == "best" else "-")
    if few:
        a1.legend(fontsize=9)
        a2.legend(fontsize=9)
    else:
        sm = cm.ScalarMappable(norm=norm, cmap=cmap)
        cb = fig.colorbar(sm, ax=list(axes), fraction=0.03, pad=0.02)
        cb.set_label(f"days since first trace ({d0})")
        if args.ref == "best":
            a1.legend(loc="upper left", fontsize=9)
    if args.top_ylim:
        a1.set_ylim(*sorted(float(v) for v in args.top_ylim.split(",")))
    if args.delta_ylim:
        a2.set_ylim(*sorted(float(v) for v in args.delta_ylim.split(",")))
    a1.set_ylabel("time before arrival (min)" if args.align == "arrival"
                  else "time over common stretch (min)")
    a1.set_title(f"{args.bike} {'mornings' if dirn == 'onward' else 'returns'} "
                 f"overlaid ({len(tr)} drives)"
                 + ("  (drive runs right→left)" if dirn == "return" else ""))
    a2.set_ylabel("Δ time vs reference (min)" if args.ref == "best"
                  else "Δ time vs first drive (min)")
    a2.set_xlabel("position (km from home)")
    for a in axes:
        a.grid(alpha=0.3)
    os.makedirs(args.out, exist_ok=True)
    leg = "mornings" if dirn == "onward" else "returns"
    suffix = "_arrival" if args.align == "arrival" else ""
    out = os.path.join(args.out, f"{args.bike}_{leg}_overlay{suffix}.svg")
    fig.savefig(out)
    print(f"wrote {out} ({len(tr)} drives, common {x_lo:.2f}-{x_hi:.2f} km)")


if __name__ == "__main__":
    main()
