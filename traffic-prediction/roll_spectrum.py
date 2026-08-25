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

Layout is plot 5's: 16:9, A's signal, A's per-second summary, then the same two
for B, and the comparison overlaid in a fifth panel. Speed is drawn behind each
signal panel on its own km/h axis, scales are shared between the two cars, and
speed breakers are marked. Here the signal panel is a spectrogram in POSITION,
so a resonance can be told apart from one rough patch of road, and the summary
panel is the spectral centroid — where that second's roll energy sat.

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
CEN_COL = "#b2182b"


def roll_rate(rec, d, sl):
    """Roll rate (deg/s) over the on-route slice, in vehicle axes."""
    stem = os.path.splitext(os.path.basename(rec.rstrip("/")))[0]
    fp = os.path.join(DIR, "data", f"{stem}_frame.json")
    R = np.array((json.load(open(fp)) if os.path.exists(fp)
                  else imu_frame.derive(rec))["R"])
    w = R @ imu_frame.gyro(rec, d["t"])     # rows: pitch, roll, yaw
    return np.degrees(w[1])[sl]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--a-gpx", required=True)
    ap.add_argument("--a-label", default="A")
    ap.add_argument("--b", required=True)
    ap.add_argument("--b-gpx", required=True)
    ap.add_argument("--b-label", default="B")
    ap.add_argument("--fmin", type=float, default=0.3)
    ap.add_argument("--fmax", type=float, default=15.0,
                    help="above ~15 Hz a wedged phone stops tracking the body")
    ap.add_argument("--vmin", type=float, default=8.0,
                    help="km/h floor — crawling puts no energy into the springs")
    ap.add_argument("--vmax", type=float, default=50.0,
                    help="full scale of the speed background")
    ap.add_argument("--nperseg", type=int, default=2048)
    ap.add_argument("--hist-fmax", type=float, default=8.0,
                    help="x limit of the comparison panel; bins run to --fmax")
    ap.add_argument("--out", default="plots/roll_spectrum.svg")
    args = ap.parse_args()

    cfg = ig.load_cfg()
    feat_p = os.path.join(DIR, "route_features.json")
    feat = json.load(open(feat_p)) if os.path.exists(feat_p) else {}

    D = {}
    for tag, rec, gpx, lab in (("a", args.a, args.a_gpx, args.a_label),
                               ("b", args.b, args.b_gpx, args.b_label)):
        d = load_drive(rec, gpx, 0.1, 25, cfg)
        sl = onroute_slice(d)
        r = roll_rate(rec, d, sl)
        for k in ("t", "v", "ikm"):
            d[k] = d[k][sl]
        f, ts, Sxx = spectrogram(r, d["fs"], nperseg=args.nperseg,
                                 noverlap=args.nperseg // 2)
        band = (f >= args.fmin) & (f <= args.fmax)
        fb, S = f[band], Sxx[band]
        km = np.interp(ts, d["t"] - d["t"][0], d["ikm"])
        vw = np.interp(ts, d["t"] - d["t"][0], d["v"])
        cen = (fb[:, None] * S).sum(axis=0) / np.maximum(S.sum(axis=0), 1e-30)
        m = d["v"] > args.vmin
        fw, P = welch(r[m], d["fs"], nperseg=args.nperseg)
        pb = (fw >= args.fmin) & (fw <= args.fmax)
        D[tag] = dict(d=d, lab=lab, r=r, f=fb, km=km, vw=vw, S=S, cen=cen,
                      pf=fw[pb], P=P[pb], nmov=m.sum(), vmean=d["v"][m].mean())

    xlo = min(D[t]["km"].min() for t in "ab")
    xhi = max(D[t]["km"].max() for t in "ab")
    SdB = {t: 10 * np.log10(D[t]["S"] + 1e-12) for t in "ab"}
    vmax_db = max(s.max() for s in SdB.values())
    vmin_db = vmax_db - 45
    clim = (0.0, max(np.percentile(D[t]["cen"], 99) for t in "ab") * 1.05)

    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(5, 1, hspace=0.52, left=0.06, right=0.985,
                          top=0.905, bottom=0.055,
                          height_ratios=[1, 1, 1, 1, 0.85])
    axes = [fig.add_subplot(gs[i]) for i in range(4)]
    axh = fig.add_subplot(gs[4])

    panels = ((axes[0], "a", "spec"), (axes[1], "a", "cen"),
              (axes[2], "b", "spec"), (axes[3], "b", "cen"))
    for ax, tag, kind in panels:
        e = D[tag]
        if kind == "spec":
            ax.pcolormesh(e["km"], e["f"], SdB[tag], shading="nearest",
                          cmap="magma", vmin=vmin_db, vmax=vmax_db)
            ax.set_ylim(args.fmin, args.fmax)
            ax.set_ylabel("roll-rate\nspectrogram (Hz)", fontsize=8)
            ax.set_title(f'{e["lab"]} — roll-rate spectrogram '
                         f"(shared dB scale)", fontsize=10, loc="left")
            axs = ax.twinx()
            axs.plot(e["km"], e["vw"], lw=0.7, color="#9fd8ff", alpha=0.8)
            axs.set_ylim(0, args.vmax)
            axs.set_ylabel("km/h", fontsize=7)
            axs.tick_params(labelsize=6)
        else:
            ax.fill_between(e["km"], 0, e["cen"], color=CEN_COL, lw=0,
                            alpha=.30, step="mid")
            ax.plot(e["km"], e["cen"], color=CEN_COL, lw=0.7,
                    drawstyle="steps-mid")
            ax.set_ylim(*clim)
            ax.set_ylabel("spectral centroid\n(Hz)", fontsize=8)
            ax.set_title(f'{e["lab"]} — where that second\'s roll energy sat',
                         fontsize=10, loc="left")
        ax.set_xlim(xlo, xhi)
        ax.grid(alpha=.25)
        ax.tick_params(labelsize=7)
        for bd in feat.get("speed_breakers", []):
            ax.axvline(bd["km_from_home"], color="#333", lw=0.8, ls=":",
                       alpha=.7)
    axes[3].set_xlabel("position (km from home)", fontsize=8, labelpad=1)

    # ---- 5. the comparison: each PSD normalised to unit power in band, which
    # removes the speed difference and leaves only WHERE the body resonates.
    # Absolute PSD would put the faster drive above the other at every
    # frequency and say nothing about the suspension.
    print(f"\n{'':24}{'peak Hz':>10}{'centroid Hz':>13}{'rms deg/s':>12}"
          f"{'moving':>9}")
    for tag in ("a", "b"):
        e = D[tag]
        N = e["P"] / np.trapz(e["P"], e["pf"])
        e["N"] = N
        k = int(np.argmax(N))
        e["peak"] = e["pf"][k]
        e["cenP"] = np.trapz(e["pf"] * N, e["pf"])
        axh.plot(e["pf"], N, lw=1.6, color=COL[tag],
                 label=f'{e["lab"]}   peak {e["peak"]:.2f} Hz   '
                       f'centroid {e["cenP"]:.2f} Hz   '
                       f'{e["nmov"]/e["d"]["fs"]:.0f} s @ {e["vmean"]:.1f} km/h')
        axh.axvline(e["peak"], color=COL[tag], ls=":", lw=1.0, alpha=0.8)
        print(f'{e["lab"]:24}{e["peak"]:10.2f}{e["cenP"]:13.2f}'
              f'{e["r"].std():12.3f}{e["nmov"]/e["d"]["fs"]:8.0f}s')
    axh.set_xlim(args.fmin, args.hist_fmax)
    axh.set_xlabel(f"frequency (Hz)   — view stops at {args.hist_fmax:g} Hz, "
                   f"band runs to {args.fmax:g} Hz")
    axh.set_ylabel("normalised PSD\n(unit power in band)", fontsize=8)
    axh.set_title("normalised to unit in-band power — a LOWER peak is a "
                  "softer, slower-ringing body", fontsize=10, loc="left", pad=6)
    axh.legend(fontsize=8)
    axh.grid(alpha=.25)
    axh.tick_params(labelsize=7)

    fig.suptitle("roll-rate spectrum — where each body wants to oscillate "
                 f"({args.fmin:g}–{args.fmax:g} Hz; above that a wedged phone "
                 "is not tracking the car)", fontsize=11)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out)
    print(f"\nwrote {args.out}")

    a, b = D["a"], D["b"]
    print(f"\nband share of roll power (normalised):")
    print(f"{'band':>12}{a['lab'][:16]:>18}{b['lab'][:16]:>18}   ratio")
    for lo, hi in ((0.3, 0.8), (0.8, 1.5), (1.5, 3.0), (3.0, 6.0), (6.0, 15.0)):
        vals = []
        for e in (a, b):
            m = (e["pf"] >= lo) & (e["pf"] < hi)
            vals.append(100 * np.trapz(e["N"][m], e["pf"][m]))
        print(f"{lo:5.1f}-{hi:<4.1f} Hz{vals[0]:18.1f}{vals[1]:18.1f}"
              f"   {vals[1]/max(vals[0], 1e-9):6.2f}")


if __name__ == "__main__":
    main()
