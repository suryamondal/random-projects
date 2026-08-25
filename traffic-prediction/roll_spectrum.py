#!/usr/bin/env python3
"""Roll-rate SPECTRUM for two drives — where each body wants to oscillate.

Roll amplitude does not separate these cars: at commute pace the roll is driven
by the road, one wheel at a time, so the same tarmac tips both bodies by the
same couple of degrees (roll_profile.py measures 1.00x at p75). The suspension
difference is in the RESPONSE, not the amplitude — a soft, softly-damped body
has a LOW roll natural frequency and rings; a stiff one sits higher and snaps
back. That frequency is a property of mass and spring rate, so unlike amplitude
it does not care how fast you were going, which is what makes it comparable
across two drives at different speeds.

Layout follows plot 5: one panel per car with speed drawn behind it, shared
scales so they read against each other, and the comparison overlaid at the
bottom. Here the per-car panels are spectrograms in POSITION, so a resonance
can be told apart from one rough patch of road.

The top of the band is 15 Hz on purpose. The phone is wedged, not bolted, and
above ~15 Hz it stops tracking the body (see deroll in imu_resid_full: coherence
falls to ~0.11 and the fitted lever arm collapses). Nothing above that line is
the car.

Usage:
    python3 roll_spectrum.py --a <rec.zip> --a-gpx <a.gpx> --a-label "Jazz" \
                             --b <rec.zip> --b-gpx <b.gpx> --b-label "Brio"
"""

import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import spectrogram, welch

import imu_frame
import ingest_gpx as ig
from imu_compare_pdf import load_drive
from roll_profile import onroute_slice

DIR = os.path.dirname(os.path.abspath(__file__))
COL = {"a": "#d1495b", "b": "#2a9d8f"}


def roll_rate(rec, d, sl):
    """Roll rate (deg/s) over the on-route slice, in vehicle axes."""
    stem = os.path.splitext(os.path.basename(rec.rstrip("/")))[0]
    fp = os.path.join(DIR, "data", f"{stem}_frame.json")
    R = np.array((json.load(open(fp)) if os.path.exists(fp)
                  else imu_frame.derive(rec))["R"])
    w = R @ imu_frame.gyro(rec, d["t"])     # rows: pitch, roll, yaw
    return np.degrees(w[1])[sl]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True)
    p.add_argument("--a-gpx", required=True)
    p.add_argument("--a-label", default="A")
    p.add_argument("--b", required=True)
    p.add_argument("--b-gpx", required=True)
    p.add_argument("--b-label", default="B")
    p.add_argument("--fmin", type=float, default=0.3)
    p.add_argument("--fmax", type=float, default=15.0,
                   help="above ~15 Hz a wedged phone stops tracking the body")
    p.add_argument("--vmin", type=float, default=8.0,
                   help="km/h floor — crawling puts no energy into the springs")
    p.add_argument("--nperseg", type=int, default=2048)
    p.add_argument("--out", default="plots/roll_spectrum.svg")
    args = p.parse_args()

    cfg = ig.load_cfg()
    D = {}
    for tag, rec, gpx, lab in (("a", args.a, args.a_gpx, args.a_label),
                               ("b", args.b, args.b_gpx, args.b_label)):
        d = load_drive(rec, gpx, 0.1, 25, cfg)
        sl = onroute_slice(d)
        r = roll_rate(rec, d, sl)
        for k in ("t", "v", "ikm"):
            d[k] = d[k][sl]
        D[tag] = dict(d=d, lab=lab, r=r, fs=d["fs"])

    fig = plt.figure(figsize=(13, 12))
    gs = fig.add_gridspec(4, 1, height_ratios=[1.5, 1.5, 1.7, 1.7], hspace=0.42)
    axes = [fig.add_subplot(gs[i]) for i in range(4)]

    # ---- 1 & 2: spectrogram in position, so a resonance is distinguishable
    #             from one rough patch of road. Shared colour scale.
    SG = {}
    for tag in ("a", "b"):
        e = D[tag]; d = e["d"]
        f, ts, Sxx = spectrogram(e["r"], e["fs"], nperseg=args.nperseg,
                                 noverlap=args.nperseg // 2)
        band = (f >= args.fmin) & (f <= args.fmax)
        km = np.interp(ts, d["t"] - d["t"][0], d["ikm"])
        SG[tag] = (f[band], km, 10 * np.log10(Sxx[band] + 1e-12))
    vmax = max(s[2].max() for s in SG.values())
    vmin_db = vmax - 45
    for i, tag in enumerate(("a", "b")):
        ax = axes[i]; e = D[tag]; d = e["d"]
        f, km, S = SG[tag]
        ax.pcolormesh(km, f, S, shading="nearest", cmap="magma",
                      vmin=vmin_db, vmax=vmax)
        ax.set_ylabel("freq (Hz)")
        ax.set_title(f'{e["lab"]} — roll-rate spectrogram', fontsize=10)
        ax.set_ylim(args.fmin, args.fmax)
        sp = ax.twinx()
        sp.plot(d["ikm"], d["v"], lw=0.6, color="#9fd8ff", alpha=0.75)
        sp.set_ylim(0, 60); sp.set_ylabel("km/h", fontsize=8)
        sp.tick_params(labelsize=7)
    axes[1].set_xlabel("position (km from home)")

    # ---- 3: absolute PSD, moving only
    for tag in ("a", "b"):
        e = D[tag]; d = e["d"]
        m = d["v"] > args.vmin
        f, P = welch(e["r"][m], e["fs"], nperseg=args.nperseg)
        band = (f >= args.fmin) & (f <= args.fmax)
        e["f"], e["P"] = f[band], P[band]
        axes[2].semilogy(e["f"], e["P"], lw=1.5, color=COL[tag],
                         label=f'{e["lab"]}  ({m.sum()/e["fs"]:.0f} s moving, '
                               f'mean {d["v"][m].mean():.1f} km/h)')
    axes[2].set_ylabel("roll-rate PSD\n(deg²/s²/Hz)")
    axes[2].set_title("absolute — but the faster drive puts more energy in at "
                      "every frequency, so read the shape below", fontsize=10)
    axes[2].legend(fontsize=8); axes[2].grid(alpha=0.3, which="both")
    axes[2].set_xlim(args.fmin, args.fmax)

    # ---- 4: shape — each PSD normalised to unit power in band, which removes
    #         the speed difference and leaves only WHERE the body resonates
    print(f"\n{'':22}{'peak Hz':>10}{'centroid Hz':>13}{'rms deg/s':>12}")
    for tag in ("a", "b"):
        e = D[tag]
        N = e["P"] / np.trapz(e["P"], e["f"])
        e["N"] = N
        k = int(np.argmax(N))
        cen = np.trapz(e["f"] * N, e["f"])
        e["peak"], e["cen"] = e["f"][k], cen
        axes[3].plot(e["f"], N, lw=1.6, color=COL[tag],
                     label=f'{e["lab"]}   peak {e["f"][k]:.2f} Hz')
        axes[3].axvline(e["f"][k], color=COL[tag], ls=":", lw=1.0, alpha=0.8)
        print(f'{e["lab"]:22}{e["f"][k]:10.2f}{cen:13.2f}{e["r"].std():12.3f}')
    axes[3].set_xlabel("frequency (Hz)")
    axes[3].set_ylabel("normalised PSD\n(unit power in band)")
    axes[3].set_title("shape — speed removed; a lower peak means a softer, "
                      "slower-ringing body", fontsize=10)
    axes[3].legend(fontsize=9); axes[3].grid(alpha=0.3)
    axes[3].set_xlim(args.fmin, min(args.fmax, 8.0))

    fig.suptitle("roll-rate spectrum — where each body wants to oscillate",
                 fontsize=12)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight")
    print(f"\nwrote {args.out}")

    a, b = D["a"], D["b"]
    print(f"\nband share of roll power (normalised):")
    print(f"{'band':>12}{a['lab'][:14]:>16}{b['lab'][:14]:>16}   ratio")
    for lo, hi in ((0.3, 0.8), (0.8, 1.5), (1.5, 3.0), (3.0, 6.0), (6.0, 15.0)):
        vals = []
        for e in (a, b):
            m = (e["f"] >= lo) & (e["f"] < hi)
            vals.append(100 * np.trapz(e["N"][m], e["f"][m]))
        print(f"{lo:5.1f}-{hi:<4.1f} Hz{vals[0]:16.1f}{vals[1]:16.1f}"
              f"   {vals[1]/max(vals[0], 1e-9):6.2f}")


if __name__ == "__main__":
    main()
