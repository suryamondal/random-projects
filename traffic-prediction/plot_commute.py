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
                              (10 min bins), colour = seconds to cross that
                              section, the seconds printed in each cell, each
                              row's total time in the right margin -> *where and
                              when* the route is slow, both directions aligned.

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


def _profile_grid(direction: str):
    """Build the (departure-time x distance) grid of measured section seconds."""
    rows = read_csv(f"{direction}_sections.csv")
    if not rows:
        return None
    tbin = CFG.get("time_bin_min", 10)
    dbin = CFG.get("section_bin_m", 200)
    cells = defaultdict(list)
    tset, dmax = set(), 0
    for r in rows:
        tb = (_clock_to_min(r["start_time"]) // tbin) * tbin
        db = int(float(r["dist_m"]))
        cells[(tb, db)].append(float(r["sec"]))
        tset.add(tb)
        dmax = max(dmax, db)
    taxis = list(range(min(tset), max(tset) + tbin, tbin))
    daxis = list(range(0, dmax + dbin, dbin))
    raw = np.full((len(taxis), len(daxis)), np.nan)
    for i, tb in enumerate(taxis):
        for j, db in enumerate(daxis):
            v = cells.get((tb, db))
            if v:
                raw[i, j] = sum(v) / len(v)
    return {"taxis": taxis, "daxis": daxis, "raw": raw, "tbin": tbin, "dbin": dbin}


def _render_profile(ax, grid: dict, title: str, x_tot: float,
                    reverse: bool, route_total_m) -> None:
    """Draw one profile panel: colour = section seconds, the seconds printed in
    each bin, row totals at x_tot. If reverse, the office-origin distance axis is
    flipped to a home-origin one so both directions share a distance-from-home x.
    """
    taxis, daxis, raw, tbin, dbin = (grid["taxis"], grid["daxis"], grid["raw"],
                                     grid["tbin"], grid["dbin"])
    edges_m = np.array(daxis + [daxis[-1] + dbin], dtype=float)
    if reverse and route_total_m:
        xedges = (route_total_m - edges_m)[::-1] / 1000.0
        rawc = raw[:, ::-1]
    else:
        xedges = edges_m / 1000.0
        rawc = raw
    xcent = (xedges[:-1] + xedges[1:]) / 2
    yedges = np.array(taxis + [taxis[-1] + tbin], dtype=float)
    vmax = np.nanpercentile(rawc, 97) if np.isfinite(rawc).any() else None
    ax.pcolormesh(xedges, yedges, rawc, cmap="YlOrRd", vmax=vmax, shading="flat")

    for i, tb in enumerate(taxis):
        yc = tb + tbin / 2
        for j in range(len(xcent)):
            v = rawc[i, j]
            if np.isnan(v):
                continue
            shade = "white" if vmax and v > 0.6 * vmax else "black"
            ax.text(xcent[j], yc, f"{v:.0f}", rotation=90, ha="center",
                    va="center", fontsize=8, color=shade)

    ax.text(x_tot, yedges[0] - tbin * 0.35, "Σ min", fontsize=11,
            ha="left", va="center", fontweight="bold")
    for i, tb in enumerate(taxis):
        row = rawc[i][~np.isnan(rawc[i])]
        if row.size:
            ax.text(x_tot, tb + tbin / 2, f"{row.sum() / 60:.1f}", fontsize=11,
                    ha="left", va="center")
    ax.set_xlim(0, x_tot + 6 * (dbin / 1000.0))
    ax.set_ylabel("departure time")
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{int(v) // 60:02d}:{int(v) % 60:02d}"))
    ax.invert_yaxis()
    ax.set_title(title)


def plot_combined_profile() -> None:
    """onward (top) over return (bottom, x reversed) on a shared distance-from-home
    axis, since they are the same road in opposite directions."""
    go = _profile_grid("onward")
    gr = _profile_grid("return")
    if not go and not gr:
        print("no section data; skipping combined_section_profile")
        return

    rt_r = _route_total_m("return")
    ext_o = (go["daxis"][-1] + go["dbin"]) / 1000.0 if go else 0
    ext_r = rt_r / 1000.0 if (gr and rt_r) else (
        (gr["daxis"][-1] + gr["dbin"]) / 1000.0 if gr else 0)
    pad = (go or gr)["dbin"] / 1000.0
    x_tot = max(ext_o, ext_r) + pad

    no = len(go["taxis"]) if go else 1
    nr = len(gr["taxis"]) if gr else 1
    fig, axes = plt.subplots(
        2, 1, figsize=(13, max(2.5, 0.5 * no + 1.5) + max(2.5, 0.5 * nr + 1.5)),
        gridspec_kw={"height_ratios": [max(2, no), max(2, nr)]})

    if go:
        _render_profile(axes[0], go, "onward: home → office", x_tot, False, None)
    if gr:
        _render_profile(axes[1], gr, "return: office → home (reversed)", x_tot,
                        True, rt_r)
    axes[1].set_xlabel("distance from home (km)   →   office")
    fig.suptitle("section travel time (s): onward over return, shared distance axis",
                 fontsize=13)
    out = os.path.join(PLOTS, "combined_section_profile.svg")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def main() -> int:
    os.makedirs(PLOTS, exist_ok=True)
    for direction, label in DIRECTIONS.items():
        plot_travel_history(direction, label)
        plot_pocket_map(direction, label)
    plot_combined_profile()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
