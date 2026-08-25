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
The rate is integrated and high-passed at --hp to shed integrator drift, which
costs the true DC tilt (camber, a long constant-radius bend) but keeps every
transient -- and the transients are the suspension's signature.

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
    m = (V > vmin) & np.isfinite(K)
    return S[m], V[m], K[m]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True)
    p.add_argument("--a-gpx", required=True)
    p.add_argument("--a-label", default="A")
    p.add_argument("--b", required=True)
    p.add_argument("--b-gpx", required=True)
    p.add_argument("--b-label", default="B")
    p.add_argument("--hp", type=float, default=0.05,
                   help="high-pass for the roll integration (Hz)")
    p.add_argument("--vmin", type=float, default=4.0, help="km/h floor")
    p.add_argument("--smooth", type=float, default=0.25,
                   help="trace smoothing window (s)")
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
        D[tag] = dict(d=d, lab=lab, ang=ang, rate=rate,
                      ang_s=np.convolve(ang, ker, mode="same"))

    fig, (a1, a2, a3) = plt.subplots(
        3, 1, figsize=(13, 11),
        gridspec_kw={"height_ratios": [2.0, 1.6, 1.4]})

    # ---- 1. the roll motion itself, along the route
    for tag in ("a", "b"):
        e = D[tag]; d = e["d"]
        m = np.isfinite(d["ikm"]) & (d["v"] > args.vmin)
        a1.plot(d["ikm"][m], e["ang_s"][m], lw=0.5, color=COL[tag],
                alpha=0.85, label=f'{e["lab"]}')
    a1.axhline(0, color="#888", lw=0.8, ls="--")
    a1.set_ylabel("roll angle (deg)")
    a1.set_title("body roll along the route — rotation about the forward axis "
                 f"(gyro, high-passed {args.hp} Hz)")
    a1.legend(loc="upper right", fontsize=9)
    a1.grid(alpha=0.3)

    # ---- 2. rolling amplitude, so the two are comparable at a glance
    for tag in ("a", "b"):
        e = D[tag]; d = e["d"]
        S, V, K = bucket(e["ang"], d["t"], d["v"], d["ikm"], d["fs"], args.vmin)
        o = np.argsort(K)
        w = max(1, len(S) // 60)
        ker = np.ones(w) / w
        a2.plot(K[o], np.convolve(S[o], ker, mode="same"), lw=1.6,
                color=COL[tag], label=f'{e["lab"]}  median {np.median(S):.3f} deg')
        e["S"], e["V"] = S, V
    a2.set_ylabel("roll amplitude\n(per-second std, deg)")
    a2.set_xlabel("position (km from home)")
    a2.legend(loc="upper right", fontsize=9)
    a2.grid(alpha=0.3)

    # ---- 3. distribution over DISTANCE (speed-weighted, as elsewhere)
    pool = np.r_[D["a"]["S"], D["b"]["S"]]
    hi = np.percentile(pool, 99.0)
    core = pool[pool <= hi]
    nb = max(8, len(core) // 45)
    bins = np.unique(np.percentile(core, np.linspace(0, 100, nb + 1)))
    bins[-1] = hi
    wdt = np.diff(bins)
    for tag in ("a", "b"):
        e = D[tag]
        cnt, _ = np.histogram(np.clip(e["S"], bins[0], np.nextafter(hi, 0)),
                              bins=bins, weights=e["V"])
        dens = 100 * cnt / e["V"].sum() / wdt
        a3.step(bins[:-1], dens, where="post", lw=1.6, color=COL[tag],
                label=e["lab"])
    a3.set_xlabel("per-second roll amplitude (deg)")
    a3.set_ylabel("% of distance\nper deg")
    a3.legend(loc="upper right", fontsize=9)
    a3.grid(alpha=0.3)

    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out)
    print(f"wrote {args.out}")

    def wq(x, w, q):
        o = np.argsort(x); x, w = x[o], w[o]
        c = np.cumsum(w) / w.sum()
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
