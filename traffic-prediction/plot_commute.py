#!/usr/bin/env python3
"""Visualise your own recorded commute history into plots/, one set per
direction (onward = home->office, return = office->home):

  <dir>_travel_history.svg    actual travel time vs departure clock time, one
                              dot per drive, coloured by weekday -> your
                              home-grown "when to leave" model. Partial traces
                              excluded (their time undercounts).
  <dir>_pocket_map.svg        every recorded pocket, by location, sized by time
                              stuck -> shows *where* the jams are.
  combined_section_profile.svg  onward (top) over return (bottom, x reversed) on
                              a shared distance-from-home axis. 2D heatmap:
                              x = distance (200 m bins), y = departure time
                              (10 min bins, only the occupied ones, each row
                              tagged with its bin centre; a dashed rule marks a
                              jump), colour = seconds to cross that
                              section, the seconds printed in each cell, each
                              row's total time in the right margin -> *where and
                              when* the route is slow, both directions aligned.

  combined_section_profile_by_day.svg  the same panels with one row per calendar
                              day instead of per departure-time bin -> the
                              route's day-by-day history; row tag carries the
                              weekday and which car drove it.

Built entirely from your GPS traces (no online prediction).
Reads whatever exists under data/; missing files are skipped.

Usage:
    python3 plot_commute.py
"""

import csv
import datetime as dt
import json
import os
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, "data")
PLOTS = os.path.join(DIR, "plots")

DIRECTIONS = {"onward": "home → office", "return": "office → home"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

with open(os.path.join(DIR, "config.json")) as _f:
    CFG = json.load(_f)


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


def _route_total_m(direction: str):
    p = os.path.join(DATA, f"{direction}_route.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)["s"][-1]
    return None


def _bikes() -> list:
    """Distinct bikes present across the section data, in stable order."""
    seen = []
    for direction in DIRECTIONS:
        for r in read_csv(f"{direction}_sections.csv"):
            b = r.get("bike", "unknown")
            if b not in seen:
                seen.append(b)
    return seen


def _profile_grid(direction: str, bike=None):
    """Build the (departure-time x distance) grid of measured section seconds,
    optionally restricted to one bike."""
    rows = read_csv(f"{direction}_sections.csv")
    if bike is not None:
        rows = [r for r in rows if r.get("bike") == bike]
    if not rows:
        return None
    tbin = CFG.get("time_bin_min", 10)
    if bike is not None:            # a bike with many traces can afford finer bins
        tbin = CFG.get("time_bin_min_per_bike", {}).get(bike, tbin)
    dbin = CFG.get("section_bin_m", 200)
    cells = defaultdict(list)
    tset, dmax = set(), 0
    for r in rows:
        tb = (_clock_to_min(r["start_time"]) // tbin) * tbin
        db = int(float(r["dist_m"]))
        cells[(tb, db)].append(float(r["sec"]))
        tset.add(tb)
        dmax = max(dmax, db)
    # only bins that actually hold a trace: departures now span ~09:00-19:45,
    # and a contiguous range over that is mostly empty rows
    taxis = sorted(tset)
    daxis = list(range(0, dmax + dbin, dbin))
    raw = np.full((len(taxis), len(daxis)), np.nan)
    for i, tb in enumerate(taxis):
        for j, db in enumerate(daxis):
            v = cells.get((tb, db))
            if v:
                raw[i, j] = sum(v) / len(v)
    labels = [f"{int(round(tb + tbin / 2)) // 60:02d}:"
              f"{int(round(tb + tbin / 2)) % 60:02d}" for tb in taxis]
    return {"taxis": taxis, "daxis": daxis, "raw": raw, "tbin": tbin, "dbin": dbin,
            "labels": labels, "keys": taxis, "step": tbin,
            "ylabel": "departure time (bin centre)"}


BIKE_SHORT = {"honda-jazz": "jazz", "honda-brio": "brio",
              "ktm-duke-390": "duke", "re-hunter-350": "hunter"}


def _profile_grid_day(direction: str, bike=None):
    """Same grid as _profile_grid, but one row per calendar day instead of per
    departure-time bin: each row is that day's drive, so the stack reads as a
    day-by-day history of the route rather than a time-of-day pattern."""
    rows = read_csv(f"{direction}_sections.csv")
    if bike is not None:
        rows = [r for r in rows if r.get("bike") == bike]
    if not rows:
        return None
    dbin = CFG.get("section_bin_m", 200)
    cells = defaultdict(list)
    bikes_on = defaultdict(set)
    dmax = 0
    for r in rows:
        day = r["date"]
        db = int(float(r["dist_m"]))
        cells[(day, db)].append(float(r["sec"]))
        bikes_on[day].add(r.get("bike", ""))
        dmax = max(dmax, db)
    days = sorted(bikes_on)
    daxis = list(range(0, dmax + dbin, dbin))
    raw = np.full((len(days), len(daxis)), np.nan)
    for i, day in enumerate(days):
        for j, db in enumerate(daxis):
            v = cells.get((day, db))
            if v:
                raw[i, j] = sum(v) / len(v)
    labels, keys = [], []
    for day in days:
        d = dt.date.fromisoformat(day)
        tag = f"{d.strftime('%m-%d')} {WEEKDAYS[d.weekday()]}"
        if bike is None:        # which car it was is the point when all are mixed
            tag += "  " + "/".join(sorted(BIKE_SHORT.get(b, b)
                                          for b in bikes_on[day] if b))
        labels.append(tag)
        keys.append(d.toordinal())
    return {"taxis": days, "daxis": daxis, "raw": raw, "tbin": 1, "dbin": dbin,
            "labels": labels, "keys": keys, "step": 1, "ylabel": "day"}


def _render_profile(ax, grid: dict, title: str, x_tot: float, xlim_right: float,
                    reverse: bool, route_total_m, x_offset: float = 0.0,
                    vmin=None, vmax=None) -> None:
    """Draw one profile panel: colour = section seconds, the seconds printed in
    each bin, row totals at x_tot. If reverse, the office-origin distance axis is
    flipped to a home-origin one so both directions share a distance-from-home x.
    x_offset shifts the grid so both panels' bin edges line up; vmin/vmax fix a
    shared colour scale.
    """
    taxis, daxis, raw, tbin, dbin = (grid["taxis"], grid["daxis"], grid["raw"],
                                     grid["tbin"], grid["dbin"])
    labels, keys, step = grid["labels"], grid["keys"], grid["step"]
    edges_m = np.array(daxis + [daxis[-1] + dbin], dtype=float)
    if reverse and route_total_m:
        xedges = (route_total_m - edges_m)[::-1] / 1000.0
        rawc = raw[:, ::-1]
    else:
        xedges = edges_m / 1000.0 + x_offset
        rawc = raw
    xcent = (xedges[:-1] + xedges[1:]) / 2
    # rows are the occupied bins only, so y is a row index, not a time axis;
    # each row is tagged with its bin's central clock time instead
    yedges = np.arange(len(taxis) + 1, dtype=float)
    if vmax is None:
        vmax = np.nanpercentile(rawc, 97) if np.isfinite(rawc).any() else None
    ax.pcolormesh(xedges, yedges, rawc, cmap="YlOrRd", vmin=vmin, vmax=vmax,
                  shading="flat")

    for i, tb in enumerate(taxis):
        yc = i + 0.5
        for j in range(len(xcent)):
            v = rawc[i, j]
            if np.isnan(v):
                continue
            shade = "white" if vmax and v > 0.6 * vmax else "black"
            ax.text(xcent[j], yc, f"{v:.0f}", rotation=90, ha="center",
                    va="center", fontsize=8, color=shade)

    ax.text(x_tot, yedges[0] - 0.35, "Σ min", fontsize=11,
            ha="left", va="center", fontweight="bold")
    for i in range(len(taxis)):
        row = rawc[i][~np.isnan(rawc[i])]
        if row.size:
            ax.text(x_tot, i + 0.5, f"{row.sum() / 60:.1f}", fontsize=11,
                    ha="left", va="center")

    # a rule between rows whose bins are not adjacent in time, so dropped-out
    # stretches stay visible and the stack is not misread as continuous
    for i in range(1, len(keys)):
        if keys[i] - keys[i - 1] > step:
            ax.axhline(i, color="#666", lw=0.8, ls=(0, (4, 3)), zorder=5)

    ax.set_xlim(0, xlim_right)
    ax.set_ylabel(grid["ylabel"])
    ax.set_yticks([i + 0.5 for i in range(len(labels))])
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_ylim(0, len(taxis))
    ax.invert_yaxis()
    ax.set_title(title)


def plot_combined_profile(bike=None, vmin=None, vmax=None, by="time") -> None:
    """onward (top) over return (bottom, x reversed) on a shared distance-from-home
    axis, since they are the same road in opposite directions. Restricted to one
    bike if given; vmin/vmax let callers share a colour scale across bikes.

    by="time" rows are departure-time bins (the time-of-day pattern); by="day"
    rows are calendar days (the day-by-day history, one drive per row).
    """
    build = _profile_grid_day if by == "day" else _profile_grid
    go = build("onward", bike)
    gr = build("return", bike)
    tag = ("_by_day" if by == "day" else "") + (f"_{bike}" if bike else "")
    if not go and not gr:
        print(f"no section data for {bike or 'all'}; skipping combined_section_profile{tag}")
        return

    rt_r = _route_total_m("return")
    dbin = (go or gr)["dbin"]
    ext_o = (go["daxis"][-1] + go["dbin"]) / 1000.0 if go else 0
    ext_r = rt_r / 1000.0 if (gr and rt_r) else (
        (gr["daxis"][-1] + gr["dbin"]) / 1000.0 if gr else 0)
    pad = dbin / 1000.0
    # the reversed return grid sits at (route_total mod dbin); shift onward to match
    offset = (rt_r % dbin) / 1000.0 if rt_r else 0.0
    # totals in a shared right-side column, nudged right and the blank trimmed
    x_tot = max(ext_o + offset, ext_r) + 0.55
    xlim_right = x_tot + 0.6                       # room for the "Σ min" numbers

    if vmin is None or vmax is None:              # self-scale if not given one
        allvals = np.concatenate([g["raw"][np.isfinite(g["raw"])].ravel()
                                  for g in (go, gr) if g])
        vmin = float(allvals.min()) if allvals.size else None
        vmax = float(np.percentile(allvals, 97)) if allvals.size else None

    no = len(go["taxis"]) if go else 1
    nr = len(gr["taxis"]) if gr else 1
    fig, axes = plt.subplots(
        2, 1, figsize=(13.8 if by == "day" else 13,
                       max(2.5, 0.5 * no + 1.5) + max(2.5, 0.5 * nr + 1.5)),
        gridspec_kw={"height_ratios": [max(2, no), max(2, nr)]})

    who = f"  [{bike}]" if bike else ""
    if go:
        _render_profile(axes[0], go, f"onward: home → office{who}", x_tot, xlim_right,
                        False, None, x_offset=offset, vmin=vmin, vmax=vmax)
    if gr:
        _render_profile(axes[1], gr, f"return: home ← office{who}", x_tot,
                        xlim_right, True, rt_r, vmin=vmin, vmax=vmax)
    axes[1].set_xlabel("distance from home (km)   →   office")
    out = os.path.join(PLOTS, f"combined_section_profile{tag}.svg")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def _global_scale():
    """Shared (vmin, vmax) across all section data so per-bike plots compare."""
    vals = []
    for direction in DIRECTIONS:
        for r in read_csv(f"{direction}_sections.csv"):
            vals.append(float(r["sec"]))
    if not vals:
        return None, None
    a = np.array(vals)
    return float(a.min()), float(np.percentile(a, 97))


def main() -> int:
    os.makedirs(PLOTS, exist_ok=True)
    for direction, label in DIRECTIONS.items():
        plot_travel_history(direction, label)
        plot_pocket_map(direction, label)
    vmin, vmax = _global_scale()                       # shared so bikes compare
    for by in ("time", "day"):                         # time-of-day, then history
        plot_combined_profile(vmin=vmin, vmax=vmax, by=by)   # all bikes together
        for bike in _bikes():                          # one profile per bike
            plot_combined_profile(bike, vmin=vmin, vmax=vmax, by=by)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
