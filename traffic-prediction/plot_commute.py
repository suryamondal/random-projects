#!/usr/bin/env python3
"""Visualise your own recorded commute history into plots/:

  travel_history.png  actual travel time vs departure clock time, one dot per
                      recorded drive, coloured by weekday -> your home-grown
                      "when to leave" model, which sharpens as you log more.
  pocket_map.png      every recorded GPS pocket, plotted by location and sized
                      by time stuck -> shows *where* the jams are.

Built entirely from your GPS traces (no online prediction).
Reads whatever exists under data/; missing files are skipped.

Usage:
    python3 plot_commute.py
"""

import csv
import datetime as dt
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


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _clock_to_min(hms: str) -> int:
    """'HH:MM:SS' -> minutes since midnight (local)."""
    h, m, *_ = hms.split(":")
    return int(h) * 60 + int(m)


def plot_travel_history() -> None:
    rows = read_csv("gpx_summary.csv")
    if not rows:
        print("no gpx_summary.csv data; skipping travel_history")
        return

    by_wd: dict = defaultdict(list)
    for r in rows:
        wd = dt.date.fromisoformat(r["date"]).strftime("%a")
        by_wd[wd].append((_clock_to_min(r["start_time"]), float(r["duration_min"])))

    fig, ax = plt.subplots(figsize=(10, 6))
    for wd in sorted(by_wd, key=WEEKDAYS.index):
        xs = [p[0] for p in by_wd[wd]]
        ys = [p[1] for p in by_wd[wd]]
        ax.scatter(xs, ys, s=55, label=wd)

    ax.xaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{int(v) // 60:02d}:{int(v) % 60:02d}"))
    ax.set_xlabel("departure time")
    ax.set_ylabel("actual travel time (min)")
    ax.set_title("Office → home: your recorded travel time by departure time")
    ax.grid(True, alpha=0.3)
    ax.legend(title="weekday")
    n = len(rows)
    ax.annotate(f"{n} trace{'' if n == 1 else 's'} logged — sharpens as you add more",
                xy=(0.02, 0.96), xycoords="axes fraction", fontsize=9,
                bbox=dict(boxstyle="round", fc="#e8f5e9"))
    out = os.path.join(PLOTS, "travel_history.png")
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
    gps = read_csv("gpx_pockets.csv")
    if not gps:
        print("no pocket data; skipping pocket_map")
        return

    lon = [_fnum(r["lon"]) for r in gps]
    lat = [_fnum(r["lat"]) for r in gps]
    dur = [(_fnum(r["duration_s"]) or 0) for r in gps]

    fig, ax = plt.subplots(figsize=(8, 9))
    sc = ax.scatter(lon, lat, c=dur, cmap="YlOrRd", s=[max(50, d) for d in dur],
                    edgecolors="navy", linewidths=0.8)
    fig.colorbar(sc, ax=ax, label="time stuck (s)", shrink=0.6)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title("Where the pockets are (from your GPS traces)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.2)
    out = os.path.join(PLOTS, "pocket_map.png")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"wrote {out}")


def main() -> int:
    os.makedirs(PLOTS, exist_ok=True)
    plot_travel_history()
    plot_pocket_map()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
