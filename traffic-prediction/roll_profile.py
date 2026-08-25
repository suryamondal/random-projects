#!/usr/bin/env python3
"""Body ROLL along the route: rotation in the plane perpendicular to forward.

Roll is what the body does about its longitudinal axis -- the lateral/vertical
plane tips, and a phone lying in the centre console sees it directly on the
gyroscope. This is deliberately NOT a cornering-gain measurement: city commutes
never reach the lateral g where "roll gain per g" means anything. What is
plotted is the motion itself -- how far the body tips and how quickly it comes
back -- which is where soft and stiff suspensions actually differ at this pace.

Roll angle comes from the GYRO, not the accelerometer. A rolled body tips the
measured lateral acceleration by g*sin(phi), so the accelerometer confounds the
roll with the cornering that caused it; the gyro measures the rotation directly.
The rate is integrated and DC-blocked at --hp (0.1 Hz, the project convention)
to shed integrator drift, which costs the true DC tilt (camber, a long
constant-radius bend) but keeps every transient -- and the transients are the
suspension's signature. 0.1 Hz is far below the 1.2-1.5 Hz body roll being
measured, so it takes the drift and leaves the signal.

Both phones must sit near the centreline for this to compare. A phone offset
laterally also sees roll as apparent vertical acceleration (see deroll in
imu_resid_full), but the ROLL RATE itself is a body rate: it does not depend on
where in the body the gyro sits. Placement changes only the axes, and the frame
already handles that.

Usage:
    python3 roll_profile.py --a <rec.zip> --a-gpx <a.gpx> --a-label "Jazz" \
                            --b <rec.zip> --b-gpx <b.gpx> --b-label "Brio"
"""

import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import butter, filtfilt

import analyze_imu as ai
import imu_frame
import ingest_gpx as ig
from imu_compare_pdf import load_drive

DIR = os.path.dirname(os.path.abspath(__file__))
COL = {"a": "#d1495b", "b": "#2a9d8f"}
STD_COL = "#b2182b"


def onroute_slice(d, pad_s=5.0):
    """Index range covering the on-route drive, excluding phone handling.

    The recording starts before the phone is set down and ends after it is
    picked up: peak roll rates of 329 deg/s appear at the edges, which is the
    phone being handled, not the car. Integrating across that leaves an 85 deg
    excursion bleeding in through the filter edges -- trimmed, the same drive
    peaks at a physical 4.2 deg.
    """
    ok = np.flatnonzero(np.isfinite(d["ikm"]))
    if len(ok) == 0:
        return slice(None)
    pad = int(pad_s * d["fs"])
    return slice(max(0, ok[0] + pad), min(len(d["ikm"]), ok[-1] - pad))


def roll_series(rec, d, hp, sl):
    """Roll angle (deg) and roll rate (deg/s) over the on-route slice."""
    stem = os.path.splitext(os.path.basename(rec.rstrip("/")))[0]
    fp = os.path.join(DIR, "data", f"{stem}_frame.json")
    R = np.array((json.load(open(fp)) if os.path.exists(fp)
                  else imu_frame.derive(rec))["R"])
    # frame rows are x lateral, y forward, z up -> rotation about FORWARD is roll
    w = R @ imu_frame.gyro(rec, d["t"])
    rate = np.degrees(w[1])[sl]
    fs = d["fs"]
    b, a = butter(2, hp / (fs / 2), btype="high")
    rate_f = filtfilt(b, a, rate)
    ang = filtfilt(b, a, np.cumsum(rate_f) / fs)   # integrate, re-filter for drift
    return ang, rate_f




def bucket(x, t, v, ikm, fs, vmin):
    """Std of x within each whole second, plus that second's speed and km."""
    n = int(round(fs))
    k = len(x) // n
    X = x[:k * n].reshape(k, n)
    V = v[:k * n].reshape(k, n).mean(axis=1)
    K = ikm[:k * n].reshape(k, n).mean(axis=1)
    S = X.std(axis=1)
    T = np.arange(k) + 0.5
    m = (V > vmin) & np.isfinite(K)
    return S[m], V[m], K[m], T[m]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--a", required=True)
    p.add_argument("--a-gpx", required=True)
    p.add_argument("--a-label", default="A")
    p.add_argument("--b", required=True)
    p.add_argument("--b-gpx", required=True)
    p.add_argument("--b-label", default="B")
    p.add_argument("--hp", type=float, default=0.1,
                   help="DC block for the roll integration (Hz) — 0.1 is the "
                        "project convention, same as load_drive uses")
    p.add_argument("--vmin", type=float, default=4.0, help="km/h floor")
    p.add_argument("--x", choices=["position", "time"], default="position")
    p.add_argument("--smooth", type=float, default=0.25,
                   help="trace smoothing window (s)")
    p.add_argument("--per-bin", type=int, default=45)
    p.add_argument("--hist-pct", type=float, default=95.0)
    p.add_argument("--weight", choices=["speed", "none"], default="speed")
    p.add_argument("--out", default="plots/roll_profile.svg")
    args = p.parse_args()

    cfg = ig.load_cfg()
    D = {}
    for tag, rec, gpx, lab in (("a", args.a, args.a_gpx, args.a_label),
                               ("b", args.b, args.b_gpx, args.b_label)):
        d = load_drive(rec, gpx, 0.1, 25, cfg)
        sl = onroute_slice(d)
        ang, rate = roll_series(rec, d, args.hp, sl)   # needs the FULL timebase
        for k in ("t", "v", "ikm"):
            d[k] = d[k][sl]
        ker = np.ones(max(1, int(args.smooth * d["fs"])))
        ker = ker / ker.sum()
        S, V, K, T = bucket(ang, d["t"], d["v"], d["ikm"], d["fs"], args.vmin)
        D[tag] = dict(d=d, lab=lab, ang=ang, rate=rate,
                      ang_s=np.convolve(ang, ker, mode="same"),
                      S=S, V=V, K=K, T=T)

    for tag in ("a", "b"):
        e = D[tag]; d = e["d"]
        e["x"] = (d["t"] - d["t"][0]) if args.x == "time" else d["ikm"]
        e["sx"] = e["T"] if args.x == "time" else e["K"]
        e["ok"] = np.isfinite(e["x"]) & (d["v"] > args.vmin)

    ylim = 1.05 * max(np.percentile(np.abs(D[t]["ang"]), 99.8) for t in "ab")
    slim = 1.05 * max(np.percentile(D[t]["S"], 99.5) for t in "ab")
    xlo = min(D[t]["x"][D[t]["ok"]].min() for t in "ab")
    xhi = max(D[t]["x"][D[t]["ok"]].max() for t in "ab")
    xlab = ("time since the drive started (s)" if args.x == "time"
            else "position (km from home)")

    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(5, 1, hspace=0.42, left=0.06, right=0.985,
                          top=0.905, bottom=0.055,
                          height_ratios=[1, 1, 1, 1, 0.85])
    axes = [fig.add_subplot(gs[i]) for i in range(4)]
    axh = fig.add_subplot(gs[4])

    for ax, tag, kind in ((axes[0], "a", "roll"), (axes[1], "a", "std"),
                          (axes[2], "b", "roll"), (axes[3], "b", "std")):
        e = D[tag]
        if kind == "roll":
            ax.axhline(0, color="#444", lw=0.9)
            ax.fill_between(e["x"][e["ok"]], 0, e["ang_s"][e["ok"]],
                            color=COL[tag], lw=0, alpha=.35)
            ax.plot(e["x"][e["ok"]], e["ang_s"][e["ok"]], lw=0.4, color=COL[tag])
            ax.set_ylim(-ylim, ylim)
            ax.set_ylabel("roll angle (deg)\n−left     +right", fontsize=8)
            ax.set_title(f'{e["lab"]} — body roll, rotation about the forward '
                         f"axis (DC blocked at {args.hp:g} Hz)",
                         fontsize=10, loc="left")
        else:
            ax.fill_between(e["sx"], 0, e["S"], color=STD_COL, lw=0,
                            alpha=.30, step="mid")
            ax.plot(e["sx"], e["S"], color=STD_COL, lw=0.6, drawstyle="steps-mid")
            ax.set_ylim(0, slim)
            ax.set_ylabel("std per second\n(deg)", fontsize=8)
            ax.set_title(f'{e["lab"]} — per-second std of that roll',
                         fontsize=10, loc="left")
        ax.set_xlim(xlo, xhi)
        ax.grid(alpha=.25)
        ax.tick_params(labelsize=7)
    axes[3].set_xlabel(xlab, fontsize=8, labelpad=0)

    # ---- 5. distribution of the per-second std, same recipe as plot 5:
    # equal-occupancy bins on the POOLED data, density so unequal widths and
    # drive lengths stay comparable, last bin carries the overflow.
    pool = np.r_[D["a"]["S"], D["b"]["S"]]
    hi_ = float(np.percentile(pool, 99.5))
    core = pool[pool <= hi_]
    nb = max(8, len(core) // args.per_bin)
    bins = np.unique(np.percentile(core, np.linspace(0.0, 100.0, nb + 1)))
    bins[-1] = hi_
    w = np.diff(bins)
    for tag in ("a", "b"):
        e = D[tag]
        wt = e["V"].copy() if args.weight == "speed" else np.ones_like(e["S"])
        ovf_w = 100.0 * wt[e["S"] > bins[-1]].sum() / wt.sum()
        cnt, _ = np.histogram(np.clip(e["S"], bins[0], np.nextafter(bins[-1], 0.0)),
                              bins=bins, weights=wt)
        h = 100.0 * cnt / wt.sum() / w
        axh.step(np.r_[bins[0], bins], np.r_[0.0, h, 0.0], where="post",
                 lw=1.6, color=COL[tag],
                 label=f'{e["lab"]}   n={len(e["S"])}   overflow {ovf_w:.1f}%')
    axh.axvline(bins[-1], color="#555555", lw=1.0, ls=":")
    xmax = float(np.percentile(pool, args.hist_pct))
    axh.set_xlim(0, xmax)
    trunc = (f"   — view stops at p{args.hist_pct:g}, bins continue to {hi_:.2f}"
             if xmax < hi_ * 0.99 else "")
    axh.set_xlabel("per-second std of roll (deg)   — last bin includes overflow"
                   + trunc)
    axh.set_ylabel(("% of distance" if args.weight == "speed" else "% of seconds")
                   + "\nper deg", fontsize=8)
    axh.set_title(("speed-weighted " if args.weight == "speed" else "")
                  + f"distribution of the per-second std — {len(bins)-1} "
                  f"equal-occupancy bins (~{args.per_bin}/bin), last = overflow",
                  fontsize=10, loc="left", pad=12)
    axh.legend(fontsize=8)
    axh.grid(alpha=.25)
    axh.tick_params(labelsize=7)

    fig.suptitle("body roll — rotation about the forward axis", fontsize=11)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out)
    print(f"wrote {args.out}")

    def wq(x, wt, q):
        o = np.argsort(x); x, wt = x[o], wt[o]
        c = np.cumsum(wt) / wt.sum()
        return float(np.interp(q / 100, c, x))

    print(f"\n{'':22}{'p25':>9}{'p50':>9}{'p75':>9}{'p90':>9}   (deg, "
          f"speed-weighted)")
    for tag in ("a", "b"):
        e = D[tag]
        print(f'{e["lab"]:22}' + "".join(
            f"{wq(e['S'], e['V'], q):9.4f}" for q in (25, 50, 75, 90)))
    ra, rb = D["a"], D["b"]
    print(f'{"ratio b/a":22}' + "".join(
        f"{wq(rb['S'],rb['V'],q)/wq(ra['S'],ra['V'],q):9.2f}"
        for q in (25, 50, 75, 90)))
    for tag in ("a", "b"):
        e = D[tag]
        print(f'  {e["lab"]}: roll p99 {np.percentile(np.abs(e["ang"]), 99):.2f} deg, '
              f'max {np.abs(e["ang"]).max():.2f} deg, rate rms {np.std(e["rate"]):.3f} deg/s')


if __name__ == "__main__":
    main()
