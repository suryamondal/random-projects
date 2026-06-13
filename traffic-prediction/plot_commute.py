#!/usr/bin/env python3
"""Visualise the logged commute data into plots/:

  eta_curve.png    predicted travel time vs departure clock time (TomTom),
                   averaged per weekday -> shows the best window to leave.
  pocket_map.png   every recorded pocket (predicted + GPS), plotted by
                   location and sized/coloured by severity -> shows *where*
                   the jams are. GPS pockets are drawn as rings on top.

Reads whatever exists under data/; missing files are skipped.

Usage:
    python3 plot_commute.py
"""

import csv
import os
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, "data")
PLOTS = os.path.join(DIR, "plots")


def read_csv(name: str) -> list[dict]:
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def plot_eta_curve() -> None:
    rows = read_csv("eta_log.csv")
    rows = [r for r in rows if r.get("clock") and r["clock"] != "now"]
    if not rows:
        print("no eta_log.csv data; skipping eta_curve")
        return

    # mean travel time per (weekday, clock)
    agg: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        agg[r["weekday"]][r["clock"]].append(float(r["travel_min"]))

    fig, ax = plt.subplots(figsize=(10, 6))
    best_overall = None
    for wd in sorted(agg, key=lambda d: ["Mon", "Tue", "Wed", "Thu", "Fri",
                                         "Sat", "Sun"].index(d)):
        clocks = sorted(agg[wd])
        means = [sum(agg[wd][c]) / len(agg[wd][c]) for c in clocks]
        ax.plot(clocks, means, marker="o", label=wd)
        lo = min(zip(means, clocks))
        if best_overall is None or lo[0] < best_overall[0]:
            best_overall = (lo[0], lo[1], wd)

    ax.set_xlabel("departure time")
    ax.set_ylabel("predicted travel time (min)")
    ax.set_title("Office → home: predicted travel time by departure time")
    ax.grid(True, alpha=0.3)
    ax.legend(title="weekday")
    if best_overall:
        ax.annotate(f"fastest: {best_overall[1]} ({best_overall[0]:.0f} min)",
                    xy=(0.02, 0.95), xycoords="axes fraction", fontsize=9,
                    bbox=dict(boxstyle="round", fc="#e8f5e9"))
    out = os.path.join(PLOTS, "eta_curve.png")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"wrote {out}")


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def plot_pocket_map() -> None:
    pred = read_csv("pockets_log.csv")
    gps = read_csv("gpx_pockets.csv")
    if not pred and not gps:
        print("no pocket data; skipping pocket_map")
        return

    fig, ax = plt.subplots(figsize=(8, 9))

    if pred:
        lons = [_fnum(r["start_lon"]) for r in pred]
        lats = [_fnum(r["start_lat"]) for r in pred]
        sev = [(_fnum(r["delay_s"]) or 0) for r in pred]
        sc = ax.scatter(lons, lats, c=sev, cmap="YlOrRd", s=40, alpha=0.7,
                        edgecolors="none", label="predicted (TomTom)")
        fig.colorbar(sc, ax=ax, label="predicted delay (s)", shrink=0.6)

    if gps:
        glon = [_fnum(r["lon"]) for r in gps]
        glat = [_fnum(r["lat"]) for r in gps]
        gdur = [(_fnum(r["duration_s"]) or 0) for r in gps]
        ax.scatter(glon, glat, s=[max(40, d) for d in gdur],
                   facecolors="none", edgecolors="navy", linewidths=1.5,
                   label="actual (GPS), size=time stuck")

    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title("Where the pockets are")
    ax.legend(loc="best", fontsize=8)
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.2)
    out = os.path.join(PLOTS, "pocket_map.png")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"wrote {out}")


def main() -> int:
    os.makedirs(PLOTS, exist_ok=True)
    plot_eta_curve()
    plot_pocket_map()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
