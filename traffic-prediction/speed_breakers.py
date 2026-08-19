#!/usr/bin/env python3
"""Guess speed-breaker locations from the pooled speed profiles, mark on a map.

Signature of a breaker vs a signal/jam: at a signal some drives pass fast
(green light, empty day), so the pooled HIGH-percentile speed stays high; at a
breaker even the fastest-ever crossing slows. So a candidate is a NARROW dip in
the per-bin p90 of per-trace mean speeds, on a straight stretch (route turn
< 20 deg within +/-40 m, so corners don't masquerade), away from the gates.

Candidates found independently in both directions within --match-m of the same
physical spot are upgraded to "confirmed" — opposite-direction traffic agreeing
on a coordinate is strong evidence of a physical bump.

Output: printed table + plots/speed_breakers_map.svg (route path with markers).
"""

import argparse
import glob
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import ingest_gpx as ig

DIR = os.path.dirname(os.path.abspath(__file__))


def detect(dirn, cfg, tz, bin_m=10.0, min_depth=10.0, ratio=0.72):
    st, R = cfg["stations"], cfg.get("station_radius_m", 50)
    mx = cfg.get("sanity_max_kmh", 150)
    rt = json.load(open(ig.route_path(dirn)))
    tot = rt["s"][-1]
    nb = int(tot // bin_m)
    per = [[] for _ in range(nb)]
    for f in sorted(glob.glob(os.path.join(DIR, "gps", "office-route", "*.gpx"))):
        raw = ig.read_points(f, tz)
        d = ig.classify(raw[0][1], raw[0][2], cfg, raw[-1][1], raw[-1][2])[0]
        if d != dirn:
            continue
        pts, _ = ig.clamp_to_stations(raw, *ig.stations_for(d, st), R)
        if len(pts) < 20:
            continue
        s = ig.project_arc_length(rt, pts, mx)
        t = np.array([(p[0] - pts[0][0]).total_seconds() for p in pts])
        v = np.convolve(np.gradient(s, t) * 3.6, np.ones(3) / 3, mode="same")
        acc = {}
        for si, vi in zip(s, v):
            b = int(si // bin_m)
            if 0 <= b < nb:
                acc.setdefault(b, []).append(vi)
        for b, vals in acc.items():
            per[b].append(np.mean(vals))
    sg = np.arange(nb) * bin_m + bin_m / 2
    P = np.array([np.percentile(x, 90) if len(x) >= 8 else np.nan for x in per])

    srt = np.array(rt["s"])
    x, y = np.array(rt["x"]), np.array(rt["y"])
    g2 = np.arange(0, tot, 5)
    hd = np.unwrap(np.arctan2(np.diff(np.interp(g2, srt, y)),
                              np.diff(np.interp(g2, srt, x))))

    def turn_at(sm, win=40):
        i0 = max(0, int((sm - win) // 5))
        i1 = min(len(hd) - 1, int((sm + win) // 5))
        return abs(np.degrees(hd[i1] - hd[i0]))

    cands = []
    for i in range(3, nb - 3):
        if not np.isfinite(P[i]):
            continue
        lo, hi = max(0, i - 12), min(nb, i + 13)
        neigh = np.concatenate([P[lo:i - 3], P[i + 4:hi]])
        neigh = neigh[np.isfinite(neigh)]
        if len(neigh) < 6:
            continue
        base = np.percentile(neigh, 75)
        if (base - P[i] > min_depth and P[i] < base * ratio
                and turn_at(sg[i]) < 20 and 150 < sg[i] < tot - 150):
            cands.append((sg[i], P[i], base))
    merged = []
    for c in sorted(cands, key=lambda c: c[1] - c[2]):     # deepest first
        if all(abs(c[0] - m[0]) > 60 for m in merged):
            merged.append(c)
    lat, lon = np.array(rt["lat"]), np.array(rt["lon"])
    out = []
    for sm, p, base in sorted(merged):
        km = sm / 1000 if dirn == "onward" else (tot - sm) / 1000
        out.append({"dir": dirn, "km_from_home": km,
                    "lat": float(np.interp(sm, srt, lat)),
                    "lon": float(np.interp(sm, srt, lon)),
                    "p90": p, "base": base})
    return out, rt


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--match-m", type=float, default=50.0)
    args = ap.parse_args()
    cfg = ig.load_cfg()
    tz = ig.parse_offset(cfg["timezone_offset"])
    on, rt_on = detect("onward", cfg, tz)
    re_, rt_re = detect("return", cfg, tz)

    for a in on:
        a["match"] = any(ig.haversine(a["lat"], a["lon"], b["lat"], b["lon"])
                         < args.match_m for b in re_)
    for b in re_:
        b["match"] = any(ig.haversine(a["lat"], a["lon"], b["lat"], b["lon"])
                         < args.match_m for a in on)

    print(f"{'dir':<8}{'km-from-home':>13}{'p90':>6}{'vs base':>9}  confirmed(both dirs)")
    for r in on + re_:
        print(f"{r['dir']:<8}{r['km_from_home']:>10.2f} km {r['p90']:>5.0f}"
              f"{r['base']:>8.0f}   {'YES' if r['match'] else 'one-direction'}")

    fig, ax = plt.subplots(figsize=(11, 9))
    ax.plot(rt_on["lon"], rt_on["lat"], color="#bbbbbb", lw=3, zorder=1,
            label="route")
    seen = []
    for r in on + re_:
        dup = any(ig.haversine(r["lat"], r["lon"], la, lo) < 40 for la, lo in seen)
        if r["match"] and dup:
            continue
        seen.append((r["lat"], r["lon"]))
        if r["match"]:
            ax.plot(r["lon"], r["lat"], "^", ms=11, color="#b2182b", zorder=3)
        else:
            ax.plot(r["lon"], r["lat"], "^", ms=9, mfc="none", mec="#e08e45",
                    zorder=3)
        ax.annotate(f"{r['km_from_home']:.1f}", (r["lon"], r["lat"]),
                    xytext=(6, 4), textcoords="offset points", fontsize=8)
    ax.plot(cfg["stations"]["home"]["lon"], cfg["stations"]["home"]["lat"],
            "ks", ms=8)
    ax.annotate("home", (cfg["stations"]["home"]["lon"],
                         cfg["stations"]["home"]["lat"]),
                xytext=(6, -10), textcoords="offset points", fontweight="bold")
    ax.plot(cfg["stations"]["office"]["lon"], cfg["stations"]["office"]["lat"],
            "ko", ms=8)
    ax.annotate("office", (cfg["stations"]["office"]["lon"],
                           cfg["stations"]["office"]["lat"]),
                xytext=(6, 4), textcoords="offset points", fontweight="bold")
    ax.set_aspect(1 / np.cos(np.radians(12.81)))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title("Guessed speed breakers — filled red = confirmed by both "
                 "directions, hollow = one direction\nlabels = km from home")
    ax.grid(alpha=0.25)
    out = os.path.join(DIR, "plots", "speed_breakers_map.svg")
    fig.tight_layout()
    fig.savefig(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
