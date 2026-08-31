#!/usr/bin/env python3
"""Per-section time, several traces on one canvas — the section profile read as
curves instead of a heatmap.

The heatmap in plot_commute.py shows every trace at once but compresses each
into a colour. This draws the same quantity — seconds to cross each 200 m
section — as a line per trace through the section midpoints, so a handful of
drives can be compared section by section and the shape of a delay (one tall
spike vs a broad rise) is visible.

Colour carries both identities, as in breaker_overlay.py: hue = vehicle,
lightness = date within that vehicle (washed-out oldest -> full-strength
newest), so the two fleets stay apart while the order within each stays legible.

x is distance from HOME in both directions (the return's office-origin axis is
flipped), matching combined_section_profile.svg — the same physical place lands
at the same x in every plot in this repo.

y is capped (--ymax, default 60 s). A crawl section can run to several minutes
and would flatten every other trace into the floor; the cap keeps the driving
readable. Clipped sections are marked with a caret at the top of the axis and
counted in the legend, so a hidden spike is never silently dropped.

y starts at --ymin (default 10 s) rather than 0: 200 m in under 10 s is ~72 km/h,
which this corridor never sees, so the bottom of the axis was empty in every
trace recorded so far. Unlike the cap, this floor is NOT expected to clip — if a
trace ever dips below it the line will leave the axis unmarked, so lower it
rather than reading a gap as missing data.

Traces are picked from the ingested summary: the first (or --last) N full
gate-to-gate traces per vehicle, partial recordings excluded.

--median collapses each vehicle to a single line instead: the per-section MEDIAN
over every day it drove. Median, not mean, so one 900 s crawl cannot drag a
section the way it would an average. A section is drawn only where at least
--min-days days recorded it, since the ends of the route are covered by fewer
traces than the middle.

Usage:
    python3 section_compare.py                        # first 5, jazz vs brio
    python3 section_compare.py --last --n 5
    python3 section_compare.py --median               # one line per car
    python3 section_compare.py --median --median-n 8  # median of the first 8 days
    python3 section_compare.py --median --median-n 6 --last --full
    python3 section_compare.py --bikes honda-jazz,ktm-duke-390 --ymax 90
"""

import argparse
import csv
import json
import os
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors

DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, "data")
PLOTS = os.path.join(DIR, "plots")

COL = {"honda-jazz": "#d1495b", "ktm-duke-390": "#2e4a62",
       "re-hunter-350": "#8a8d91", "honda-brio": "#2a9d8f"}
SHORT = {"honda-jazz": "Jazz", "honda-brio": "Brio",
         "ktm-duke-390": "Duke", "re-hunter-350": "Hunter"}


def read_csv(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def route_total_m(direction):
    p = os.path.join(DATA, f"{direction}_route.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)["s"][-1]
    return None


def pick(direction, bike, n, last):
    """The first (or last) n full traces of one vehicle, as (date, start_time)."""
    rows = [r for r in read_csv(f"{direction}_summary.csv")
            if r["bike"] == bike and r["partial"] == "False"]
    rows.sort(key=lambda r: (r["date"], r["start_time"]))
    sel = rows[-n:] if last else rows[:n]
    return [(r["date"], r["start_time"]) for r in sel]


def pick_all(direction, bike):
    """Every full trace of one vehicle, as (date, start_time)."""
    rows = [r for r in read_csv(f"{direction}_summary.csv")
            if r["bike"] == bike and r["partial"] == "False"]
    rows.sort(key=lambda r: (r["date"], r["start_time"]))
    return [(r["date"], r["start_time"]) for r in rows]


def sections_by_trace(direction):
    """(date, start_time) -> {dist_m: sec} for every ingested trace."""
    out = defaultdict(dict)
    for r in read_csv(f"{direction}_sections.csv"):
        out[(r["date"], r["start_time"])][int(float(r["dist_m"]))] = float(r["sec"])
    return out


def complete_keys(by_trace):
    """Traces whose section coverage spans the whole route.

    The summary's `partial` flag only asks whether a trace STARTED near its
    origin gate; a trace can clear that and still be missing sections (a late
    first GPS fix drops the opening few hundred metres). For a median those
    absent sections are silently filled by the other days, which quietly makes
    the line a different mixture at one end of the route than the other.
    """
    full = max((len(v) for v in by_trace.values()), default=0)
    return {k for k, v in by_trace.items() if len(v) == full}


def shades(base, n):
    """n tints of base, washed-out first -> full strength last."""
    rgb = mcolors.to_rgb(base)
    d = max(1, n - 1)
    return [tuple(1.0 - (0.30 + 0.70 * i / d) * (1.0 - c) for c in rgb)
            for i in range(n)]


def plot_direction(direction, bikes, n, last, ymin, ymax, dbin,
                   median=False, min_n=3, median_n=None, full=False):
    by_trace = sections_by_trace(direction)
    if full:
        keep = complete_keys(by_trace)
        dropped = len(by_trace) - len(keep)
        by_trace = {k: v for k, v in by_trace.items() if k in keep}
        if dropped:
            print(f"  {direction}: --full dropped {dropped} trace(s) missing sections")
    rt = route_total_m(direction)
    fig, ax = plt.subplots(figsize=(15, 7))

    drawn = 0
    for bike in bikes:
        base = COL.get(bike, "#555555")
        if median:
            # median over every day, or over just the first/last median_n of them
            src = (pick_all(direction, bike) if median_n is None
                   else pick(direction, bike, median_n, last))
            keys = [k for k in src if k in by_trace]
            if not keys:
                print(f"  {direction}: no traces for {bike}, skipped")
                continue
            # median per section across every day this car drove, so a single
            # jam day cannot move the line the way a mean would
            pool = defaultdict(list)
            for k in keys:
                for dm, sec in by_trace[k].items():
                    pool[dm].append(sec)
            dm_ok = sorted(dm for dm in pool if len(pool[dm]) >= min_n)
            if not dm_ok:
                print(f"  {direction}: {bike} has no section with >={min_n} days")
                continue
            series = [(base, f"{SHORT.get(bike, bike)} — median of {len(keys)} days",
                       np.array(dm_ok, dtype=float),
                       np.array([np.median(pool[dm]) for dm in dm_ok]))]
        else:
            keys = [k for k in pick(direction, bike, n, last) if k in by_trace]
            if not keys:
                print(f"  {direction}: no traces for {bike}, skipped")
                continue
            series = []
            for col, key in zip(shades(base, len(keys)), keys):
                secs = by_trace[key]
                dd = np.array(sorted(secs), dtype=float)
                series.append((col, f"{SHORT.get(bike, bike)} {key[0][5:]} {key[1][:5]}",
                               dd, np.array([secs[k] for k in dd], dtype=float)))

        for col, lab, d, y in series:
            # section START in metres -> its midpoint, then to distance-from-home
            mid = d + dbin / 2.0
            x = (rt - mid) / 1000.0 if (direction == "return" and rt) else mid / 1000.0
            order = np.argsort(x)
            x, y = x[order], y[order]
            over = int((y > ymax).sum())
            if over:
                lab += f"  ({over} clipped)"
            ax.plot(x, np.minimum(y, ymax), color=col,
                    lw=2.4 if median else 1.5, label=lab, zorder=3)
            if over:
                ax.scatter(x[y > ymax], np.full(over, ymax * 0.985), marker="^",
                           s=26, color=col, zorder=4)
            drawn += 1

    if not drawn:
        plt.close(fig)
        print(f"  {direction}: nothing to plot")
        return

    ax.set_ylim(ymin, ymax)
    ax.set_xlabel("distance from home (km)   →   office")
    ax.set_ylabel(f"time in {dbin:.0f} m section (s)")
    which = "median" if median else ("last" if last else "first")
    arrow = "home → office" if direction == "onward" else "office → home"
    if median:
        what = ("median over every recorded day, per car" if median_n is None else
                f"median over the {'last' if last else 'first'} {median_n} days, per car")
    else:
        what = f"{which} {n} traces per car"
    ax.set_title(f"Per-section time — {direction} ({arrow}), {what}\n"
                 f"y {ymin:.0f}–{ymax:.0f} s; ^ marks a section clipped by the cap",
                 fontsize=12)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=2, loc="upper left")
    fig.tight_layout()
    os.makedirs(PLOTS, exist_ok=True)
    if median:
        stem = ("median" if median_n is None
                else f"median_{'last' if last else 'first'}{median_n}")
    else:
        stem = f"{which}{n}"
    if full:
        stem += "_full"
    out = os.path.join(PLOTS, f"section_compare_{stem}_{direction}.svg")
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=5, help="traces per vehicle")
    ap.add_argument("--last", action="store_true",
                    help="take the most recent n instead of the earliest")
    ap.add_argument("--bikes", default="honda-jazz,honda-brio")
    ap.add_argument("--ymax", type=float, default=60.0,
                    help="y cap in seconds (crawl sections clip to it)")
    ap.add_argument("--ymin", type=float, default=10.0,
                    help="y floor in seconds; 200 m under 10 s is ~72 km/h, "
                         "which this route never sees, so the space is dead")
    ap.add_argument("--directions", default="onward,return")
    ap.add_argument("--median", action="store_true",
                    help="one line per vehicle: the per-section median over "
                         "every day it drove, instead of n individual traces")
    ap.add_argument("--median-n", type=int, default=None,
                    help="with --median, take the median over only the first "
                         "(or --last) N days per car instead of all of them")
    ap.add_argument("--full", action="store_true",
                    help="keep only traces covering every section of the route; "
                         "the summary's partial flag checks the start gate only")
    ap.add_argument("--min-days", type=int, default=3,
                    help="a section needs this many days before its median is "
                         "drawn (--median only)")
    a = ap.parse_args()

    with open(os.path.join(DIR, "config.json")) as f:
        dbin = float(json.load(f).get("section_bin_m", 200))

    bikes = [b for b in a.bikes.split(",") if b]
    for direction in [d for d in a.directions.split(",") if d]:
        plot_direction(direction, bikes, a.n, a.last, a.ymin, a.ymax, dbin,
                       median=a.median, min_n=a.min_days, median_n=a.median_n,
                       full=a.full)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
