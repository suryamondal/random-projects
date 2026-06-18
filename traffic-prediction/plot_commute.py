#!/usr/bin/env python3
"""Visualise your own recorded commute history into plots/, one set per
direction (evening = office->home, morning = home->office):

  <dir>_travel_history.svg  actual travel time vs departure clock time, one dot
                            per drive, coloured by weekday -> your home-grown
                            "when to leave" model, sharpens as you log more.
                            Partial traces are excluded (their time undercounts).
  <dir>_pocket_map.svg      every recorded pocket, plotted by location and sized
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

DIRECTIONS = {"evening": "office → home", "morning": "home → office"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def read_csv(name: str) -> list[dict]:
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def _clock_to_min(hms: str) -> int:
    """'HH:MM:SS' -> minutes since midnight (local)."""
    h, m, *_ = hms.split(":")
    return int(h) * 60 + int(m)


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def plot_travel_history(direction: str, label: str) -> None:
    rows = read_csv(f"{direction}_summary.csv")
    full = [r for r in rows if r.get("partial") != "True"]
    dropped = len(rows) - len(full)
    if not full:
        print(f"no {direction} travel data; skipping {direction}_travel_history")
        return

    by_wd: dict = defaultdict(list)
    for r in full:
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
    ax.set_title(f"{label}: your recorded travel time by departure time")
    ax.grid(True, alpha=0.3)
    ax.legend(title="weekday")
    note = f"{len(full)} trace{'' if len(full) == 1 else 's'} logged"
    if dropped:
        note += f" ({dropped} partial excluded)"
    note += " — sharpens as you add more"
    ax.annotate(note, xy=(0.02, 0.96), xycoords="axes fraction", fontsize=9,
                bbox=dict(boxstyle="round", fc="#e8f5e9"))
    out = os.path.join(PLOTS, f"{direction}_travel_history.svg")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def plot_pocket_map(direction: str, label: str) -> None:
    gps = read_csv(f"{direction}_pockets.csv")
    if not gps:
        print(f"no {direction} pocket data; skipping {direction}_pocket_map")
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
    ax.set_title(f"Where the pockets are: {label}")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.2)
    out = os.path.join(PLOTS, f"{direction}_pocket_map.svg")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def main() -> int:
    os.makedirs(PLOTS, exist_ok=True)
    for direction, label in DIRECTIONS.items():
        plot_travel_history(direction, label)
        plot_pocket_map(direction, label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
