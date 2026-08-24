#!/usr/bin/env python3
"""Overlay traces synced at a speed breaker, against a constant-pace reference.

Syncing at a gate compares drives that met different traffic on the way out;
syncing at a breaker puts them all at the same point of road at t=0, so the two
halves of the drive can be read separately. The breaker is a physical feature
every trace must cross, which makes it a reliable zero.

The lower panel is deliberately NOT trace-minus-trace. Each drive is measured
against a fixed constant-pace line through the breaker (--pace km/h), so the
zero is the same in every plot ever made this way — drives from different days,
different vehicles and different plots stay comparable. A trace-minus-trace
panel has no fixed zero and cannot be compared with anything else.

Traces must span the breaker and reach the destination (dest_gap <= 400 m). A
trace whose ORIGIN half is incomplete is drawn dashed and its office->breaker
time reported as n/a, since that half is not measured.

Usage:
    python3 breaker_overlay.py gps/office-route/A.gpx gps/office-route/B.gpx \
        --labels "Jazz — you 08-24,Brio — him 08-21"
    python3 breaker_overlay.py gps/office-route/*-honda-brio.gpx --breaker-index 2
"""

import argparse
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors

import ingest_gpx as ig

DIR = os.path.dirname(os.path.abspath(__file__))
COL = {"honda-jazz": "#d1495b", "ktm-duke-390": "#2e4a62",
       "re-hunter-350": "#8a8d91", "honda-brio": "#2a9d8f"}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gpx", nargs="+")
    ap.add_argument("--labels", default=None, help="comma list, one per trace")
    ap.add_argument("--breaker-index", type=int, default=2,
                    help="which breaker, sorted by km-from-home (default 2 = the "
                         "3rd, 4.39 km — the one the earlier return overlays used)")
    ap.add_argument("--breaker-km", type=float, default=None,
                    help="override --breaker-index with an explicit km")
    ap.add_argument("--pace", type=float, default=24.0,
                    help="constant-pace reference, km/h (default 24)")
    ap.add_argument("--top-ylim", default="-13,16")
    ap.add_argument("--delta-ylim", default="-4,5")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = ig.load_cfg()
    tz = ig.parse_offset(cfg["timezone_offset"])
    st, R, mx = cfg["stations"], cfg["station_radius_m"], cfg["sanity_max_kmh"]
    brk = sorted(b["km_from_home"]
                 for b in json.load(open(os.path.join(DIR, "route_features.json")))
                 ["speed_breakers"])
    BRK = args.breaker_km if args.breaker_km is not None else brk[args.breaker_index]
    slope = 60.0 / args.pace                      # min per km

    labels = args.labels.split(",") if args.labels else [None] * len(args.gpx)
    rows = []
    for f, lab in zip(args.gpx, labels):
        raw = ig.read_points(f, tz)
        d = ig.classify(raw[0][1], raw[0][2], cfg, raw[-1][1], raw[-1][2])[0]
        rt = json.load(open(ig.route_path(d)))
        tot = rt["s"][-1]
        pts, tr = ig.clamp_to_stations(raw, *ig.stations_for(d, st), R)
        s = ig.project_arc_length(rt, pts, mx)
        km = s / 1000.0 if d == "onward" else (tot - s) / 1000.0
        if not (km.min() < BRK - 0.1 and km.max() > BRK + 0.1):
            print(f"skip {os.path.basename(f)}: does not span {BRK} km")
            continue
        if tr["dest_gap"] > 400:
            print(f"skip {os.path.basename(f)}: never reaches the destination")
            continue
        t = np.array([(p[0] - pts[0][0]).total_seconds() for p in pts]) / 60.0
        o = np.argsort(km)
        rows.append(dict(t0=pts[0][0], km=km[o], t=t[o], dirn=d,
                         full=tr["origin_gap"] <= 400,
                         bike=ig.bike_of(f), label=lab))
    if not rows:
        raise SystemExit("no qualifying traces")

    # One vehicle overlaid on itself needs a date gradient, not one flat colour
    # per vehicle — five identical reds are indistinguishable. Same convention
    # as overlay_traces.py: light (oldest) to dark (newest).
    rows.sort(key=lambda r: r["t0"])
    # Colour carries BOTH identities: hue = vehicle (so the fleets stay apart),
    # lightness = date within that vehicle (light oldest -> dark newest). A flat
    # colour per vehicle makes five traces of one car indistinguishable; a
    # single date ramp across everything loses which car is which.
    for bike in {r["bike"] for r in rows}:
        grp = [r for r in rows if r["bike"] == bike]
        base = COL.get(bike, "#555555")
        cmap = mcolors.LinearSegmentedColormap.from_list(
            bike, [mcolors.to_rgb(base) + (0.30,), mcolors.to_rgb(base)])
        n = max(1, len(grp) - 1)
        for i, r in enumerate(grp):
            rgb = mcolors.to_rgb(base)
            f = 0.30 + 0.70 * i / n          # 0.30 = washed out, 1.0 = full
            r["col"] = tuple(1.0 - f * (1.0 - c) for c in rgb)

    # Sign depends on travel direction: onward runs 0 -> 8.9 km so time grows
    # WITH position; return runs the other way. Using the return form for an
    # onward drive tilts the reference against the traces and turns the delta
    # panel into a diagonal.
    sgn = 1.0 if rows[0]["dirn"] == "onward" else -1.0
    def line(k):
        return sgn * slope * (k - BRK)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)
    for r in rows:
        k, t = r["km"], r["t"]
        g = np.arange(k.min() + 0.01, k.max() - 0.01, 0.01)
        tg = np.interp(g, k, t) - np.interp(BRK, k, t)
        c = r["col"]
        lab = r["label"] or f"{r['t0']:%m-%d} dep {r['t0']:%H:%M}"
        # tg[0] is the arrival end for a return (home), tg[-1] for an onward
        seg = tg[0] if r["dirn"] == "return" else tg[-1]
        r["seg_dest"] = abs(seg)
        r["seg_orig"] = abs(tg[-1] if r["dirn"] == "return" else tg[0])
        dest = "home" if r["dirn"] == "return" else "office"
        a1.plot(g, tg, color=c, lw=1.8, ls="-" if r["full"] else "--",
                label=f"{lab} — {abs(seg):.1f} min breaker→{dest}"
                      + ("" if r["full"] else "  (origin half partial)"))
        a2.plot(g, tg - line(g), color=c, lw=1.5,
                ls="-" if r["full"] else "--")
    gl = np.array([0.0, max(r["km"].max() for r in rows) + 0.1])
    a1.plot(gl, line(gl), color="#777777", lw=2.0, ls="--",
            label=f"reference: constant {args.pace:g} km/h")
    a2.axhline(0, color="#777777", lw=1.2, ls="--")
    for b in brk:
        w = 1.6 if abs(b - BRK) < 0.01 else 0.8
        for a in (a1, a2):
            a.axvline(b, color="#b2182b", lw=w, ls=":", alpha=.75)
    if args.top_ylim:
        a1.set_ylim(*sorted(float(v) for v in args.top_ylim.split(",")))
    if args.delta_ylim:
        a2.set_ylim(*sorted(float(v) for v in args.delta_ylim.split(",")))
    dirn = rows[0]["dirn"]
    a1.set_ylabel(f"time since the {BRK} km breaker (min)")
    a1.set_title(f"{dirn} — synced at the {BRK} km breaker"
                 + ("   (drive runs right→left)" if dirn == "return" else ""))
    a1.legend(loc="upper right", fontsize=8.5)
    a2.set_ylabel(f"Δ vs constant-{args.pace:g} km/h line (min)")
    a2.set_xlabel("position (km from home)")
    for a in (a1, a2):
        a.grid(alpha=.3)
    fig.tight_layout()
    out = args.out or os.path.join(DIR, "plots",
                                   f"breaker_overlay_{BRK:.2f}_{dirn}.svg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out)
    print(f"wrote {out}")

    dest = "home" if dirn == "return" else "office"
    print(f"\n{'trace':34}{'origin→brk':>12}{'brk→'+dest:>12}")
    for r in rows:
        lab = (r["label"] or f"{r['t0']:%m-%d %H:%M}")[:32]
        o = f"{r['seg_orig']:12.2f}" if r["full"] else f"{'n/a':>12}"
        print(f"{lab:34}{o}{r['seg_dest']:12.2f}")


if __name__ == "__main__":
    main()
