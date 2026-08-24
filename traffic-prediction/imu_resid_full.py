#!/usr/bin/env python3
"""One 16:9 page: two drives' vertical residual and its per-second std, whole drive.

Four panels, top to bottom:
    1  drive A, vertical channel, raw minus its 25-sample moving average
    2  drive A, standard deviation of that residual in each 1 s slice
    3  drive B, same as 1
    4  drive B, same as 2

The residual is what the moving average discards. At 100 Hz a 25-sample average
turns over around 4 Hz, and nobody moves a pedal that fast, so panels 1 and 3
are suspension and tyre response to the road rather than driver input. Panel 2
and 4 are that same thing as one number per second, which is what makes the two
cars readable side by side.

x is ALONG-ROUTE POSITION, not time: the drives take different times over the
same road, so only position puts panel 1 and panel 3 over the same tarmac. Use
--x time to plot each drive against its own clock instead.

The residual is drawn as a per-pixel min/max envelope rather than decimated —
200k points cannot be honestly thinned to a few thousand, and decimation would
alias the amplitude. Both drives share y scales, and the std scale is shared
too, so the panels can be compared by eye.

Usage:
    python3 imu_frame.py sensors/<recA>.zip          # frames first, both drives
    python3 imu_resid_full.py \
        --a sensors/<recA>.zip --a-gpx gps/office-route/<A>.gpx --a-label Jazz \
        --b sensors/<recB>.zip --b-gpx gps/office-route/<B>.gpx --b-label Brio
"""

import argparse
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import ingest_gpx as ig
from imu_compare_pdf import load_drive

DIR = os.path.dirname(os.path.abspath(__file__))
VERT = 2
RES_COL, STD_COL = "#4c956c", "#b2182b"
# speed gets its own colour: #2e4a62 is the KTM Duke 390 in this project's
# vehicle palette, so reusing it for a data channel is a clash waiting to
# confuse a plot that does include the Duke.
SPD_COL = "#1f6fbf"


def series(d, xmode):
    """(x, residual, speed, per-second std x, per-second std) for the whole drive."""
    ok = np.isfinite(d["ikm"]) if xmode == "position" else np.ones(len(d["t"]), bool)
    r = (d["Vf"][VERT] - d["MA"][VERT])[ok]
    v = d["v"][ok]
    t = d["t"][ok]
    x = d["ikm"][ok] if xmode == "position" else t
    # per-second std: bin by TIME (a second is a second), place at its own x
    edges = np.arange(t[0], t[-1] + 1.0, 1.0)
    idx = np.digitize(t, edges) - 1
    sx, sd = [], []
    for i in range(len(edges) - 1):
        m = idx == i
        if m.sum() > 5:
            sx.append(x[m].mean())
            sd.append(r[m].std())
    return x, r, v, np.array(sx), np.array(sd)


def bin_mean(x, y, nbin, lo, hi):
    """y averaged into nbin columns over [lo, hi] — for the speed background."""
    e = np.linspace(lo, hi, nbin + 1)
    idx = np.clip(np.digitize(x, e) - 1, 0, nbin - 1)
    out = np.full(nbin, np.nan)
    order = np.argsort(idx)
    xi, yi = idx[order], y[order]
    bounds = np.searchsorted(xi, np.arange(nbin + 1))
    for i in range(nbin):
        a, b = bounds[i], bounds[i + 1]
        if b > a:
            out[i] = yi[a:b].mean()
    return (e[:-1] + e[1:]) / 2, out


def speed_bg(ax, x, v, nbin, lo, hi, ylim, vmax):
    """Speed drawn full-scale behind the residual, with its own right axis.

    Same treatment as the flipbook pages: the residual is unreadable without
    knowing how fast the car was going, since speed is what puts energy into
    the suspension in the first place.
    """
    c, vb = bin_mean(x, v, nbin, lo, hi)
    sv = np.clip(vb, 0, vmax) / vmax * (2 * ylim) - ylim
    ax.fill_between(c, -ylim, sv, color=SPD_COL, alpha=0.12, zorder=0)
    ax.plot(c, sv, color=SPD_COL, lw=1.0, alpha=0.75, zorder=1)
    axs = ax.twinx()
    axs.set_ylim(0, vmax)
    axs.set_ylabel("km/h", color=SPD_COL, fontsize=8)
    axs.tick_params(colors=SPD_COL, labelsize=7)
    ax.set_zorder(axs.get_zorder() + 1)
    ax.patch.set_visible(False)
    return axs


def envelope(ax, x, y, nbin, color):
    """Per-pixel min/max band — honest at 200k points, unlike decimation."""
    lo, hi = np.nanmin(x), np.nanmax(x)
    e = np.linspace(lo, hi, nbin + 1)
    idx = np.clip(np.digitize(x, e) - 1, 0, nbin - 1)
    mn = np.full(nbin, np.nan)
    mx = np.full(nbin, np.nan)
    order = np.argsort(idx)
    xi, yi = idx[order], y[order]
    bounds = np.searchsorted(xi, np.arange(nbin + 1))
    for i in range(nbin):
        a, b = bounds[i], bounds[i + 1]
        if b > a:
            mn[i], mx[i] = yi[a:b].min(), yi[a:b].max()
    c = (e[:-1] + e[1:]) / 2
    ax.fill_between(c, mn, mx, color=color, lw=0, alpha=.85)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--a-gpx", required=True)
    ap.add_argument("--a-label", default="A")
    ap.add_argument("--b", required=True)
    ap.add_argument("--b-gpx", required=True)
    ap.add_argument("--b-label", default="B")
    ap.add_argument("--x", choices=("position", "time"), default="position")
    ap.add_argument("--hp", type=float, default=0.1)
    ap.add_argument("--smooth", type=int, default=25)
    ap.add_argument("--nbin", type=int, default=2600, help="envelope columns")
    ap.add_argument("--vmax", type=float, default=50.0,
                    help="full scale of the speed background (km/h)")
    ap.add_argument("--out", default=os.path.join(DIR, "plots",
                                                  "imu_resid_full.svg"))
    args = ap.parse_args()

    cfg = ig.load_cfg()
    A = load_drive(args.a, args.a_gpx, args.hp, args.smooth, cfg)
    B = load_drive(args.b, args.b_gpx, args.hp, args.smooth, cfg)
    if A["dirn"] != B["dirn"]:
        raise SystemExit(f"different directions: {A['dirn']} vs {B['dirn']}")
    xa, ra, va, sxa, sda = series(A, args.x)
    xb, rb, vb_, sxb, sdb = series(B, args.x)

    rlim = float(np.percentile(np.abs(np.r_[ra, rb]), 99.9))
    slim = float(np.percentile(np.r_[sda, sdb], 99.5))
    xlo = min(xa.min(), xb.min())
    xhi = max(xa.max(), xb.max())

    feat_p = os.path.join(DIR, "route_features.json")
    feat = json.load(open(feat_p)) if os.path.exists(feat_p) else {}

    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(4, 1, hspace=0.30, left=0.06, right=0.985,
                          top=0.925, bottom=0.065)
    axes = [fig.add_subplot(gs[i]) for i in range(4)]
    panels = ((axes[0], xa, ra, va, args.a_label, "resid"),
              (axes[1], sxa, sda, None, args.a_label, "std"),
              (axes[2], xb, rb, vb_, args.b_label, "resid"),
              (axes[3], sxb, sdb, None, args.b_label, "std"))
    for ax, X, Y, V, lab, kind in panels:
        if kind == "resid":
            speed_bg(ax, X, V, args.nbin, xlo, xhi, rlim, args.vmax)
            envelope(ax, X, Y, args.nbin, RES_COL)
            ax.set_ylim(-rlim, rlim)
            ax.set_ylabel(f"raw − {args.smooth}-sample MA\n(m/s²)", fontsize=8)
            ax.set_title(f"{lab} — vertical residual", fontsize=10, loc="left")
        else:
            ax.fill_between(X, 0, Y, color=STD_COL, lw=0, alpha=.30, step="mid")
            ax.plot(X, Y, color=STD_COL, lw=0.6, drawstyle="steps-mid")
            ax.set_ylim(0, slim)
            ax.set_ylabel("std per second\n(m/s²)", fontsize=8)
            ax.set_title(f"{lab} — per-second std of that residual",
                         fontsize=10, loc="left")
        ax.set_xlim(xlo, xhi)
        ax.grid(alpha=.25)
        ax.tick_params(labelsize=7)
        if args.x == "position":
            for bd in feat.get("speed_breakers", []):
                ax.axvline(bd["km_from_home"], color="#333", lw=0.8, ls=":",
                           alpha=.7)
            for bs in feat.get("broken_stretches", []):
                ax.axvspan(bs["from_km"], bs["to_km"], color="#a6761d",
                           alpha=.10, lw=0)
    for ax in axes[:3]:
        ax.tick_params(labelbottom=False)
    axes[3].set_xlabel("position (km from home)" if args.x == "position"
                       else "time since recording start (s)")
    if args.x == "position":
        for bd in feat.get("speed_breakers", []):
            axes[0].text(bd["km_from_home"], rlim * 0.98,
                         f" {bd['km_from_home']:.2f}", fontsize=6.5,
                         rotation=90, va="top")
    fig.suptitle(f"Vertical residual and its per-second spread — "
                 f"{args.a_label} vs {args.b_label}    "
                 f"(dotted = speed breakers, shaded = broken stretches)",
                 fontsize=13, y=0.975)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out)
    print(f"wrote {args.out}")
    print(f"  residual y +/-{rlim:.2f} m/s2 (p99.9, shared)   "
          f"std y 0-{slim:.2f} (p99.5, shared)")
    print(f"  {args.a_label}: median per-second std {np.median(sda):.3f}   "
          f"{args.b_label}: {np.median(sdb):.3f}   "
          f"ratio {np.median(sdb)/np.median(sda):.2f}")


if __name__ == "__main__":
    main()
