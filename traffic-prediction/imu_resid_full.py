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
from scipy.signal import butter, filtfilt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import ingest_gpx as ig
import imu_frame
from imu_compare_pdf import load_drive

DIR = os.path.dirname(os.path.abspath(__file__))
CHAN = {"lateral": 0, "forward": 1, "vertical": 2}   # rows of the vehicle frame
VERT = CHAN["vertical"]
RES_COL, STD_COL = "#4c956c", "#b2182b"
# speed gets its own colour: #2e4a62 is the KTM Duke 390 in this project's
# vehicle palette, so reusing it for a data channel is a clash waiting to
# confuse a plot that does include the Duke.
SPD_COL = "#1f6fbf"


def target(d, which, smooth, ci=VERT):
    """The signal being plotted: the residual, or the moving average itself."""
    if which == "resid":
        return d["Vf"][ci] - d["MA"][ci]
    return d["MA"][ci]


def deroll(d, rec, smooth, which="resid", ci=VERT):
    """Remove the roll-coupled part of the vertical residual.

    A phone offset laterally from the roll axis sees body ROLL as apparent
    VERTICAL acceleration, scaled by the offset — so two recordings with the
    phone wedged in different places are not comparable until this is taken out.
    Measured r(residual, roll-accel): 0.07 with the phone near the centreline,
    0.54 with it in a door pocket. Left in, that artifact alone made one car
    look 1.35x rougher than the other across the whole route.

    Returns (residual, r) with the least-squares roll term subtracted.
    """
    stem = os.path.splitext(os.path.basename(rec.rstrip("/")))[0]
    fp = os.path.join(DIR, "data", f"{stem}_frame.json")
    R = np.array((json.load(open(fp)) if os.path.exists(fp)
                  else imu_frame.derive(rec))["R"])
    # a = alpha x r, so each channel couples to only TWO of the three rotations:
    #   vertical = pitch*longitudinal - roll*lateral      (yaw cannot enter)
    #   forward  = yaw*lateral        - pitch*vertical    (roll cannot enter)
    #   lateral  = roll*vertical      - yaw*longitudinal  (pitch cannot enter)
    # Regressing on all three lets the forbidden one come out at zero as a check
    # — measured, it does: roll in the forward channel fits -0.005 / -0.008.
    gv = R @ imu_frame.gyro(rec, d["t"])
    alpha = np.vstack([np.gradient(gv[i], d["t"]) for i in range(3)])
    # BAND-LIMIT the regressor. a_z = -d x alpha is rigid-body kinematics, and
    # it holds here from 0.5 to 15 Hz: the fitted coefficient is flat at
    # 0.79-1.05 m with coherence up to 0.77. Above 15 Hz coherence falls to
    # ~0.11 and the coefficient collapses — the phone is wedged, not bolted, so
    # the rigid assumption fails. Correcting up there removes signal for nothing.
    fs = 1.0 / np.median(np.diff(d["t"]))
    bb, aa = butter(4, [0.5 / (fs / 2), 15.0 / (fs / 2)], btype="band")
    ker = np.ones(smooth) / smooth
    rows = []
    for i in range(3):
        a_ = filtfilt(bb, aa, alpha[i])
        # put the regressor in the SAME band as the target
        rows.append(a_ - np.convolve(a_, ker, mode="same") if which == "resid"
                    else np.convolve(a_, ker, mode="same"))
    rd = np.vstack(rows)
    r = target(d, which, smooth, ci)
    # FIT ON THE DRIVE ONLY. The recordings run several minutes past their GPX
    # at both ends (phone being placed and picked up); that handling noise is
    # uncorrelated with roll and swamps the regression — it drags the measured
    # correlation from +0.54 down to +0.03 and the correction then does nothing.
    # fit on MOVING on-route samples: crawling and stopped stretches carry no
    # roll excitation to fit against and only dilute the estimate (0.65 m / 46 %
    # with them in, 0.77 m / 62 % with them out).
    fit = (np.isfinite(d["ikm"]) & np.isfinite(r) & np.isfinite(rd).all(axis=0)
           & (d["v"] > 15))
    X = rd[:, fit].T
    c, *_ = np.linalg.lstsq(X, r[fit], rcond=None)
    # variance explained decides whether this is worth doing at all: a phone on
    # the roll axis gives ~0.5 %, one in a door pocket ~62 %. Below the
    # threshold the regressor is mostly noise and subtracting it ADDS variance,
    # so leave the signal alone and say so.
    ve = 1.0 - ((r[fit] - X @ c).var() / r[fit].var())
    if ve < 0.05:
        return r, c, ve, False
    return r - c @ rd, c, ve, True


def series(d, xmode, resid=None, which="resid", smooth=25, ci=VERT):
    """(x, residual, speed, per-second std x, per-second std) for the whole drive."""
    ok = np.isfinite(d["ikm"]) if xmode == "position" else np.ones(len(d["t"]), bool)
    r = target(d, which, smooth, ci)[ok] if resid is None else resid[ok]
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
    ax.plot(c, sv, color=SPD_COL, lw=1.0, alpha=0.75, zorder=1)
    axs = ax.twinx()
    axs.set_ylim(0, vmax)
    axs.set_ylabel("km/h", color=SPD_COL, fontsize=8)
    axs.tick_params(colors=SPD_COL, labelsize=7)
    ax.set_zorder(axs.get_zorder() + 1)
    ax.patch.set_visible(False)
    return axs


def envelope(ax, x, y, nbin, color, with_mean=False):
    """Per-pixel min/max band — honest at 200k points, unlike decimation.

    with_mean also draws the per-column mean as a line. The residual is
    zero-mean by construction so that line carries nothing, but the moving
    average is a 0.1-2 Hz BAND, not a slow trend: as a bare min/max envelope it
    renders as a hairball that looks nothing like a moving average, and the
    structure only becomes legible with the mean drawn through it.
    """
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
    ax.fill_between(c, mn, mx, color=color, lw=0, alpha=.40 if with_mean else .85)
    if with_mean:
        mu = np.full(nbin, np.nan)
        for i in range(nbin):
            a, b = bounds[i], bounds[i + 1]
            if b > a:
                mu[i] = yi[a:b].mean()
        ax.plot(c, mu, color="#1f5c3a", lw=0.8)


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
    ap.add_argument("--channel", choices=tuple(CHAN), default="vertical",
                    help="which vehicle-frame axis to plot")
    ap.add_argument("--signal", choices=("resid", "ma"), default="resid",
                    help="'resid' (default): raw minus the 25-sample moving "
                         "average — above ~4 Hz, suspension and tyre response. "
                         "'ma': the moving average itself — below ~4 Hz, body "
                         "motion and primary ride.")
    ap.add_argument("--no-deroll", action="store_true",
                    help="keep the roll-coupled component. Off by default: with "
                         "it in, a phone wedged off the roll axis reads as a "
                         "rougher car and the two panels are not comparable.")
    ap.add_argument("--binning", choices=("width", "count"), default="count",
                    help="'count': equal-OCCUPANCY bins — edges at quantiles of "
                         "the pooled data, so bins are narrow where the data is "
                         "dense and wide in the tail, and every bin carries the "
                         "same Poisson error. Heights are density (%% per unit), "
                         "since equal-count bins would otherwise be flat by "
                         "construction. 'width': fixed-width bins.")
    ap.add_argument("--hist-pct", type=float, default=95.0,
                    help="percentile setting the distribution panel's x limit "
                         "(default 95). The bulk of this signal sits below ~20%% "
                         "of its range, so plotting to p99.5 squeezes every mode "
                         "into the left edge. Bins are unchanged; only the view.")
    ap.add_argument("--per-bin", type=int, default=45,
                    help="target entries per bin for --binning count")
    ap.add_argument("--bins", type=int, default=60,
                    help="bins in the distribution panel (default 60). One entry "
                         "per second of drive, so n is only ~1700 for a single "
                         "commute: 60 bins puts ~149 in the peak (+/-8%%), 300 "
                         "bins puts 36 (+/-17%%) and empties a quarter of them. "
                         "Pool more drives before going much finer.")
    ap.add_argument("--vmax", type=float, default=50.0,
                    help="full scale of the speed background (km/h)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = ig.load_cfg()
    A = load_drive(args.a, args.a_gpx, args.hp, args.smooth, cfg)
    B = load_drive(args.b, args.b_gpx, args.hp, args.smooth, cfg)
    if A["dirn"] != B["dirn"]:
        raise SystemExit(f"different directions: {A['dirn']} vs {B['dirn']}")
    didA = didB = False
    if args.no_deroll:
        resA = resB = None
        rA = rB = float("nan")
    else:
        ci = CHAN[args.channel]
        resA, cA, veA, didA = deroll(A, args.a, args.smooth, args.signal, ci)
        resB, cB, veB, didB = deroll(B, args.b, args.smooth, args.signal, ci)
        for lab, c_, ve_, did in ((args.a_label, cA, veA, didA),
                                  (args.b_label, cB, veB, didB)):
            print(f"  rotation: pitch {c_[0]:+.3f} roll {c_[1]:+.3f} "
                  f"yaw {c_[2]:+.3f} m, explains {100*ve_:4.1f}% -> "
                  f"{'removed' if did else 'LEFT ALONE (below 5%)'}   [{lab}]")
    ci = CHAN[args.channel]
    xa, ra, va, sxa, sda = series(A, args.x, resA, args.signal, args.smooth, ci)
    xb, rb, vb_, sxb, sdb = series(B, args.x, resB, args.signal, args.smooth, ci)

    rlim = float(np.percentile(np.abs(np.r_[ra, rb]), 99.9))
    slim = float(np.percentile(np.r_[sda, sdb], 99.5))
    xlo = min(xa.min(), xb.min())
    xhi = max(xa.max(), xb.max())

    feat_p = os.path.join(DIR, "route_features.json")
    feat = json.load(open(feat_p)) if os.path.exists(feat_p) else {}

    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(5, 1, hspace=0.42, left=0.06, right=0.985,
                          top=0.905, bottom=0.055,
                          height_ratios=[1, 1, 1, 1, 0.85])
    axes = [fig.add_subplot(gs[i]) for i in range(4)]
    axh = fig.add_subplot(gs[4])
    panels = ((axes[0], xa, ra, va, args.a_label, "resid"),
              (axes[1], sxa, sda, None, args.a_label, "std"),
              (axes[2], xb, rb, vb_, args.b_label, "resid"),
              (axes[3], sxb, sdb, None, args.b_label, "std"))
    for ax, X, Y, V, lab, kind in panels:
        if kind == "resid":
            speed_bg(ax, X, V, args.nbin, xlo, xhi, rlim, args.vmax)
            envelope(ax, X, Y, args.nbin, RES_COL,
                     with_mean=(args.signal == "ma"))
            ax.set_ylim(-rlim, rlim)
            ax.set_ylabel((f"raw − {args.smooth}-sample MA" if args.signal == "resid"
                           else f"{args.smooth}-sample MA") + "\n(m/s²)", fontsize=8)
            ax.set_title(f"{lab} — {args.channel} "
                         + ("residual" if args.signal == "resid"
                            else "moving average"), fontsize=10, loc="left")
        else:
            ax.fill_between(X, 0, Y, color=STD_COL, lw=0, alpha=.30, step="mid")
            ax.plot(X, Y, color=STD_COL, lw=0.6, drawstyle="steps-mid")
            ax.set_ylim(0, slim)
            ax.set_ylabel("std per second\n(m/s²)", fontsize=8)
            ax.set_title(f"{lab} — per-second std of that "
                         + ("residual" if args.signal == "resid"
                            else "moving average"), fontsize=10, loc="left")
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
    # ---- panel 5: distribution of the per-second std, both drives, shared bins
    pool = np.r_[sda, sdb]
    hi_ = float(np.percentile(pool, 99.5))
    if args.binning == "count":
        # edges at quantiles of the POOLED data so both drives share them
        core = pool[pool <= hi_]
        nb = max(8, len(core) // args.per_bin)
        bins = np.unique(np.percentile(core, np.linspace(0.0, 100.0, nb + 1)))
        # do NOT drag the first edge down to 0: the first quantile edge IS the
        # data minimum, and widening that bin divides its count by a bigger
        # width, scaling its density by 0.80x — a 20 % suppression landing
        # exactly on the quiet pedestal, which is the feature of interest.
        # The axis is set to start at 0 separately.
        bins[-1] = hi_
    else:
        bins = np.linspace(0.0, hi_, args.bins + 1)
    w = np.diff(bins)
    # OVERFLOW: the axis stops at p99.5, and matplotlib silently discards
    # anything past the last edge. Clip into the final bin instead, so the plot
    # accounts for every second rather than quietly losing the tail — which on
    # this signal is exactly the hard braking worth seeing.
    for X, lab, col in ((sda, args.a_label, "#d1495b"),
                        (sdb, args.b_label, "#2a9d8f")):
        n_ovf = int((X > bins[-1]).sum())
        cnt, _ = np.histogram(np.clip(X, bins[0], np.nextafter(bins[-1], 0.0)),
                              bins=bins)
        # density: % of seconds PER UNIT, so unequal bin widths stay comparable
        h = 100.0 * cnt / len(X) / w
        axh.step(np.r_[bins[0], bins], np.r_[0.0, h, 0.0], where="post",
                 lw=1.6, color=col,
                 label=f"{lab}   n={len(X)}   overflow {100.0*n_ovf/len(X):.1f}%")
    axh.axvline(bins[-1], color="#555555", lw=1.0, ls=":")
    # bins run to p99.5; the VIEW stops earlier so the modes are legible
    xmax = float(np.percentile(pool, args.hist_pct))
    axh.set_xlim(0, xmax)
    trunc = (f"   — view stops at p{args.hist_pct:g}, bins continue to {hi_:.2f}"
             if xmax < hi_ * 0.99 else "")
    axh.set_xlabel("per-second std (m/s²)   — last bin includes overflow" + trunc)
    axh.set_ylabel("% of seconds\nper m/s²", fontsize=8)
    axh.set_title(f"distribution of the per-second std — "
                  + (f"{len(bins)-1} equal-occupancy bins (~{args.per_bin}/bin)"
                     if args.binning == "count" else f"{args.bins} fixed-width bins")
                  + ", last = overflow", fontsize=10, loc="left")
    axh.legend(fontsize=8)
    axh.grid(alpha=.25)
    axh.tick_params(labelsize=7)

    for ax in axes[:3]:
        ax.tick_params(labelbottom=False)
    axes[3].set_xlabel("position (km from home)" if args.x == "position"
                       else "time since recording start (s)")
    if args.x == "position":
        for bd in feat.get("speed_breakers", []):
            axes[0].text(bd["km_from_home"], rlim * 0.98,
                         f" {bd['km_from_home']:.2f}", fontsize=6.5,
                         rotation=90, va="top")
    # say what actually happened, not what was requested
    if args.no_deroll:
        tag = "raw — rotation NOT removed, not comparable between cars"
    elif didA and didB:
        tag = "rotation-coupled component removed from both"
    elif didA or didB:
        tag = f"rotation removed from {args.a_label if didA else args.b_label} only"
    else:
        tag = "rotation coupling <5% in both, nothing removed"
    what = ("residual" if args.signal == "resid" else "moving average")
    # two lines: the long-form caveats overflowed the canvas on one
    fig.suptitle(f"{args.channel.capitalize()} {what} and its per-second spread"
                 f" — {args.a_label} vs {args.b_label}\n"
                 f"dotted = speed breakers · shaded = broken stretches · {tag}",
                 fontsize=11, y=0.985, linespacing=1.4)
    out = args.out or os.path.join(
        DIR, "plots",
        f"imu_{args.channel}_{'resid' if args.signal == 'resid' else 'movavg'}_full.svg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out)
    print(f"wrote {out}")
    print(f"  residual y +/-{rlim:.2f} m/s2 (p99.9, shared)   "
          f"std y 0-{slim:.2f} (p99.5, shared)")
    print(f"  {args.a_label}: median per-second std {np.median(sda):.3f}   "
          f"{args.b_label}: {np.median(sdb):.3f}   "
          f"ratio {np.median(sdb)/np.median(sda):.2f}")


if __name__ == "__main__":
    main()
