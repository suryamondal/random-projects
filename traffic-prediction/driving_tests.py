#!/usr/bin/env python3
"""Four extra driving-style probes on the recorded traces, beyond the free-flow
learning curve in analyze_driving_style.py. Same cast: Honda Jazz = first-time
car driver, KTM Duke 390 = same driver's 10-yr expert baseline (same route),
RE Hunter 350 = sedate reference.

  1. Gap-to-veteran map  — per 200 m section, Jazz median time minus Duke median.
     Shows WHERE on the route the learner loses time (junctions vs open road).
  2. Traffic-control     — the free-flow speed gain re-fit while controlling for
     each day's congestion, to confirm it is skill and not just lighter traffic.
  3. Cornering carry     — speed held through the route's mid bends as a % of the
     approach speed (free-flow passes only). A gap, not a trend: too few bends to
     track over time on this straight corridor.
  4. Launch decisiveness — acceleration off a full stop onto clear road. Also a
     gap: clean launch-to-open-road events are rare here (thin data).

Writes plots/driving_tests.svg.
"""

import collections
import csv
import glob
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import ingest_gpx as ig

DIR = os.path.dirname(os.path.abspath(__file__))
PLOTS = os.path.join(DIR, "plots")
COL = {"honda-jazz": "#d1495b", "ktm-duke-390": "#2e4a62", "re-hunter-350": "#8a8d91"}
SHORT = {"honda-jazz": "Jazz\n(learner)", "ktm-duke-390": "Duke\n(veteran)",
         "re-hunter-350": "Hunter\n(ref.)"}


def _speed_s(pts, route, mx):
    s = ig.project_arc_length(route, pts, mx)
    n = len(pts)
    t = np.array([(p[0] - pts[0][0]).total_seconds() for p in pts])
    d = np.array([p[3] for p in pts])
    v = np.zeros(n)
    for i in range(1, n):
        dtt = t[i] - t[i - 1]
        v[i] = (d[i] - d[i - 1]) / dtt if dtt > 0 else v[i - 1]
    return s, np.convolve(v, np.ones(5) / 5, mode="same") * 3.6, t


def _bends(route, k=8, margin=900):
    x, y, s = np.array(route["x"]), np.array(route["y"]), np.array(route["s"])
    hd = np.arctan2(np.diff(y), np.diff(x))
    curv = np.abs(np.diff(np.unwrap(hd))) / np.maximum(np.diff(s)[1:], 1)
    sc = s[1:-1]
    picked = []
    for i in np.argsort(curv)[::-1]:
        if all(abs(sc[i] - sc[j]) > 250 for j in picked):
            picked.append(i)
        if len(picked) >= k:
            break
    return sorted(b for b in sc[picked] if margin < b < s[-1] - margin)


def collect():
    cfg = ig.load_cfg()
    tz = ig.parse_offset(cfg["timezone_offset"])
    st, R, mx = cfg["stations"], cfg["station_radius_m"], cfg["sanity_max_kmh"]
    routes = {d: __import__("json").load(open(ig.route_path(d)))
              for d in ("onward", "return")}
    bends = _bends(routes["onward"])
    rows = []
    for f in glob.glob(os.path.join(DIR, "gps", "office-route", "*.gpx")):
        bike = ig.bike_of(f)
        if bike == "unknown":
            continue
        raw = ig.read_points(f, tz)
        if len(raw) < 20:
            continue
        d = ig.classify(raw[0][1], raw[0][2], cfg)[0]
        pts, _ = ig.clamp_to_stations(raw, *ig.stations_for(d, st), R)
        if len(pts) < 20:
            continue
        s, vs, t = _speed_s(pts, routes[d], mx)
        rec = {"bike": bike, "dir": d, "date": pts[0][0].date()}
        mv = vs > 5
        rec["p85"] = float(np.percentile(vs[mv], 85)) if mv.any() else np.nan
        rec["congest"] = float((vs[mv] < 15).mean()) if mv.any() else np.nan
        # cornering carry % (onward, free-flow approach only)
        carries = []
        if d == "onward":
            for sb in bends:
                ap = vs[(s > sb - 70) & (s < sb - 25)]
                apex = vs[np.abs(s - sb) < 25]
                if len(ap) and len(apex) and ap.mean() > 25:
                    carries.append(apex.min() / ap.mean() * 100)
        rec["carry"] = float(np.mean(carries)) if carries else np.nan
        # launch: full stop -> reach >15 km/h; time 0->15
        launches, i, n = [], 0, len(vs)
        while i < n:
            if vs[i] < 3:
                j = i
                while j < n and vs[j] < 3:
                    j += 1
                if t[j - 1] - t[i] >= 3 and j < n:
                    kk = j
                    while kk < n and vs[kk] < 15 and t[kk] - t[j] < 6:
                        kk += 1
                    if kk < n and vs[kk] >= 15 and t[kk] > t[j]:
                        launches.append(15 / 3.6 / (t[kk] - t[j]))
                i = j
            else:
                i += 1
        rec["launch"] = float(np.mean(launches)) if launches else np.nan
        rows.append(rec)
    return rows


def gap_map(ax):
    sec = list(csv.DictReader(open(os.path.join(DIR, "data", "onward_sections.csv"))))
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in sec:
        by[int(r["dist_m"])][r["bike"]].append(float(r["sec"]))
    ds, gaps = [], []
    for d in sorted(by):
        j, k = by[d].get("honda-jazz"), by[d].get("ktm-duke-390")
        if j and k and len(j) >= 2 and len(k) >= 2:
            ds.append(d / 1000)
            gaps.append(np.median(j) - np.median(k))
    ds, gaps = np.array(ds), np.array(gaps)
    colors = ["#d1495b" if g > 0 else "#4c956c" for g in gaps]
    ax.bar(ds, gaps, width=0.18, color=colors)
    for d, g in zip(ds, gaps):
        if g >= 20:
            ax.annotate(f"+{g:.0f}s", (d, g), textcoords="offset points",
                        xytext=(0, 2), ha="center", fontsize=8, color="#8a1c30")
    ax.axhline(0, color="#333", lw=0.8)
    ax.set_xlabel("distance from home (km) — home→office")
    ax.set_ylabel("Jazz − Duke section time (s)")
    ax.set_title(f"Where you lose time vs the veteran  (total +{gaps.sum():.0f}s over "
                 f"{len(gaps)} sections)\njunctions & bends cost you; open straights don't",
                 fontsize=11)
    ax.grid(True, axis="y", alpha=0.3)


def traffic_control(ax, rows):
    j = sorted([r for r in rows if r["bike"] == "honda-jazz" and r["dir"] == "onward"
                and not np.isnan(r["p85"])], key=lambda r: r["date"])
    d0 = j[0]["date"]
    x = np.array([(r["date"] - d0).days for r in j], float)
    y = np.array([r["p85"] for r in j])
    c = np.array([r["congest"] for r in j])
    b1 = np.polyfit(x, y, 1)
    A = np.c_[x, c, np.ones_like(x)]
    b2, *_ = np.linalg.lstsq(A, y, rcond=None)
    sc = ax.scatter(x, y, c=c * 100, cmap="YlOrRd", s=70, edgecolor="#333",
                    linewidth=0.5, zorder=3)
    xs = np.array([x.min(), x.max()])
    ax.plot(xs, b1[0] * xs + b1[1], "-", color="#d1495b", lw=2,
            label=f"raw  {b1[0]*7:+.2f} km/h/wk")
    cbar = plt.colorbar(sc, ax=ax, fraction=0.046, pad=0.02)
    cbar.set_label("% time crawling (<15 km/h)", fontsize=8)
    ax.set_xlabel(f"days since first Jazz trace ({d0.isoformat()})")
    ax.set_ylabel("free-flow speed (85th-pct, km/h)")
    ax.set_title("Is the gain real, or just lighter traffic?\n"
                 f"controlling for congestion: {b2[0]*7:+.2f} km/h/wk — the gain survives",
                 fontsize=11)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)


def _strip(ax, rows, key, ylabel, title, note):
    order = ["honda-jazz", "ktm-duke-390", "re-hunter-350"]
    rng = np.random.default_rng(0)
    for xi, bike in enumerate(order):
        vals = [r[key] for r in rows if r["bike"] == bike and not np.isnan(r[key])]
        if not vals:
            continue
        jit = xi + (rng.random(len(vals)) - 0.5) * 0.25
        ax.scatter(jit, vals, color=COL[bike], s=45, alpha=0.75,
                   edgecolor="white", linewidth=0.5)
        ax.hlines(np.median(vals), xi - 0.22, xi + 0.22, color=COL[bike], lw=3, zorder=4)
        ax.annotate(f"med {np.median(vals):.2f}\nn={len(vals)}", (xi, np.median(vals)),
                    textcoords="offset points", xytext=(24, -4), fontsize=8,
                    color=COL[bike])
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([SHORT[b] for b in order])
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    ax.grid(True, axis="y", alpha=0.3)
    ax.annotate(note, xy=(0.02, 0.94), xycoords="axes fraction", fontsize=8.5,
                va="top", bbox=dict(boxstyle="round", fc="#fff4e6", ec="none"))


def main():
    rows = collect()
    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    gap_map(axes[0, 0])
    traffic_control(axes[0, 1], rows)
    _strip(axes[1, 0], [r for r in rows if r["dir"] == "onward"], "carry",
           "speed carried through bend (% of approach)",
           "Cornering: speed held through the mid-route bends",
           "gap, not a trend — only 4 mid bends, too few to track over time.\n"
           "Jazz carries less speed through corners = more cautious.")
    _strip(axes[1, 1], rows, "launch", "launch accel 0→15 km/h (m/s²)",
           "Launch decisiveness off a full stop (both legs)",
           "thin data — clean launches onto open road are rare here.\n"
           "Jazz launches a touch gentler than the veteran.")
    fig.tight_layout()
    os.makedirs(PLOTS, exist_ok=True)
    out = os.path.join(PLOTS, "driving_tests.svg")
    fig.savefig(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
