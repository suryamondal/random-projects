#!/usr/bin/env python3
"""Salvage and analyse a Sensor Logger recording (100 Hz IMU + 1 Hz GPS).

Phone recordings made without a rigid mount are bracketed by two large
handling shocks — placing the phone at the start and picking it up at the
end — and anything outside those is hand-carry noise, not driving. This tool:

  1. finds the two largest handling events (vertical shocks above
     --handling-g), trims to the data between them (+/- a margin);
  2. within that window: speed profile & stops (GPS), road bump inventory
     (vertical shocks while moving), and an engine-rpm track from the
     2nd-order (2 x rpm/60) firing vibration, readable when the mount noise
     allows (clean at idle; needs a rigid mount while moving);
  3. writes a three-panel dashboard SVG (speed / rpm / vertical shock).

Vertical is recovered without knowing the phone's mounting angle: gravity is
low-pass tracked and acceleration projected onto it, so a leaning, slowly
shifting phone (door bottle-holder) still yields usable vertical dynamics.

Usage:
    python3 analyze_imu.py <recording.zip | extracted-dir> [--out plots/]
"""

import argparse
import csv
import os
import sys
import tempfile
import zipfile

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DIR = os.path.dirname(os.path.abspath(__file__))


def load(path):
    """Return (loc, imu) dicts from a Sensor Logger export (zip or dir)."""
    if path.endswith(".zip"):
        tmp = tempfile.mkdtemp(prefix="imu_")
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        path = tmp
    loc_rows = list(csv.DictReader(open(os.path.join(path, "Location.csv"))))
    loc = {
        "t": np.array([float(r["seconds_elapsed"]) for r in loc_rows]),
        "kmh": np.array([float(r["speed"]) for r in loc_rows]) * 3.6,
        "lat": np.array([float(r["latitude"]) for r in loc_rows]),
        "lon": np.array([float(r["longitude"]) for r in loc_rows]),
    }
    tot = np.genfromtxt(os.path.join(path, "TotalAcceleration.csv"),
                        delimiter=",", names=True)
    imu = {"t": tot["seconds_elapsed"],
           "A": np.vstack([tot["x"], tot["y"], tot["z"]])}
    return loc, imu


def vertical(imu, mask=None):
    """Vertical dynamic acceleration under a FIXED gravity assumption: the
    phone is jammed in place, so gravity is one constant vector — the median
    of the raw signal (over mask, if given). Subtracting a constant leaves the
    true dynamics unsmeared (a low-pass tracker would leak real accelerations
    into its gravity estimate). Returns the signed component along gravity."""
    A = imu["A"]
    sel = A if mask is None else A[:, mask]
    g0 = np.median(sel, axis=1)
    gn = g0 / np.linalg.norm(g0)
    return (A * gn[:, None]).sum(0) - np.linalg.norm(g0)


def handling_window(t, vert, thresh, margin):
    """(t_start, t_end) between the TWO LARGEST shocks — placing the phone and
    picking it back up. Falls back to the full span if the two largest are
    close together or too weak to be handling."""
    av = np.abs(vert)
    order = np.argsort(av)[::-1]
    i1 = order[0]
    i2 = next((i for i in order[1:] if abs(t[i] - t[i1]) > 60), None)
    if i2 is None or min(av[i1], av[i2]) < thresh:
        return t[0], t[-1]                # no clear bracket; keep everything
    a, b = sorted((t[i1], t[i2]))
    return a + margin, b - margin


def rpm_track(t, vert, fs, win_s=2.0, hop_s=0.5, band=(15, 49)):
    """Dominant vibration frequency x30 (4-cyl 2nd order) per window."""
    win, hop = int(fs * win_s), int(fs * hop_s)
    times, rpm = [], []
    for s0 in range(0, len(vert) - win, hop):
        seg = vert[s0:s0 + win] * np.hanning(win)
        f = np.fft.rfftfreq(win, 1 / fs)
        P = np.abs(np.fft.rfft(seg)) ** 2
        b = (f > band[0]) & (f < band[1])
        times.append(t[s0 + win // 2])
        rpm.append(f[b][np.argmax(P[b])] * 30)
    return np.array(times), np.array(rpm)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rec", help="Sensor Logger zip or extracted directory")
    ap.add_argument("--out", default=os.path.join(DIR, "plots"),
                    help="output directory for the dashboard SVG")
    ap.add_argument("--handling-g", type=float, default=15.0,
                    help="vertical shock (m/s^2) treated as phone handling "
                         "(default 15)")
    ap.add_argument("--margin", type=float, default=3.0,
                    help="seconds trimmed inside each handling event (default 3)")
    ap.add_argument("--bump-g", type=float, default=4.0,
                    help="vertical shock (m/s^2) counted as a road bump "
                         "(default 4)")
    args = ap.parse_args()

    loc, imu = load(args.rec)
    fs = 1 / np.median(np.diff(imu["t"]))
    vert = vertical(imu)                       # pass 1: gravity from full span

    t0, t1 = handling_window(imu["t"], vert, args.handling_g, args.margin)
    print(f"handling window: keeping {t0:.0f}s .. {t1:.0f}s "
          f"(dropped {t0 - imu['t'][0]:.0f}s head, {imu['t'][-1] - t1:.0f}s tail)")

    mi = (imu["t"] >= t0) & (imu["t"] <= t1)
    ml = (loc["t"] >= t0) & (loc["t"] <= t1)
    vert = vertical(imu, mask=mi)              # pass 2: gravity from the drive only
    ti, vi = imu["t"][mi], vert[mi]
    tg, vg = loc["t"][ml], loc["kmh"][ml]

    # stops (>=5 s under 2 km/h)
    stops, i = [], 0
    while i < len(vg):
        if vg[i] < 2:
            j = i
            while j < len(vg) and vg[j] < 2:
                j += 1
            if tg[j - 1] - tg[i] >= 5:
                stops.append((tg[i], tg[j - 1] - tg[i]))
            i = j
        else:
            i += 1
    stopped = sum(d for _, d in stops)
    print(f"drive: {t1 - t0:.0f}s, stops>=5s: {len(stops)} ({stopped:.0f}s), "
          f"moving {(t1 - t0 - stopped) / 60:.1f} min, vmax {vg.max():.0f} km/h")

    # road bumps: vertical shocks while moving
    kmh_i = np.interp(ti, tg, vg)
    bumps, i = [], 0
    while i < len(vi):
        if abs(vi[i]) > args.bump_g and kmh_i[i] > 5:
            j = i
            while j < len(vi) and abs(vi[j]) > args.bump_g / 2:
                j += 1
            bumps.append((ti[i], np.abs(vi[i:j]).max(), kmh_i[i]))
            i = j + int(fs)
        else:
            i += 1
    print(f"road bumps (> {args.bump_g} m/s^2 while moving): {len(bumps)}")
    for tb, pk, v0 in bumps:
        print(f"   t={tb:.0f}s  {pk:.1f} m/s^2 at {v0:.0f} km/h")

    tr, rpm = rpm_track(ti, vi, fs)

    stem = os.path.splitext(os.path.basename(args.rec.rstrip("/")))[0]
    fig, axes = plt.subplots(4, 1, figsize=(13, 10.5),
                             gridspec_kw={"height_ratios": [1, 1, 1, 1]})
    axes[0].plot(tg, vg, color="#2e4a62")
    axes[0].set_ylabel("km/h")
    axes[0].set_title(f"{stem} — trimmed to the drive ({t0:.0f}–{t1:.0f}s): "
                      "speed / engine / road / spectrum")
    axes[1].scatter(tr, rpm, s=4, color="#d1495b")
    axes[1].set_ylabel("rpm (2nd-order vib)")
    axes[1].set_ylim(400, 1500)
    axes[2].plot(ti, vi, lw=0.3, color="#4c956c")
    axes[2].set_ylabel("accel − g, fixed frame (m/s²)")
    axes[2].set_xlabel("seconds")
    for ax in axes[:3]:
        ax.set_xlim(t0, t1)
        ax.grid(alpha=0.3)
    # panel 4: single full-length FFT of the gravity-subtracted signal (no
    # segmenting/averaging): mean removed, rectangular window, normalised to a
    # one-sided PSD in (m/s^2)^2/Hz. Frequency resolution = 1/T_drive.
    # The axis runs to min(100 Hz, Nyquist): content above fs/2 does not exist,
    # so seeing 100 Hz needs the app set to sample at >= 200 Hz.
    seg = vi - vi.mean()
    f = np.fft.rfftfreq(len(seg), 1 / fs)
    P = np.abs(np.fft.rfft(seg)) ** 2 * 2 / (fs * len(seg))
    axes[3].loglog(f, P, lw=0.3, color="#7b5aa6", alpha=0.8)
    axes[3].set_ylim(max(P.max() * 1e-7, P[P > 0].min()), P.max() * 3)
    top = f[(f > 2)][np.argsort(P[f > 2])[::-1][:3]]
    for i, pk in enumerate(sorted(top)):
        axes[3].axvline(pk, ls=":", lw=0.7, color="grey")
        axes[3].annotate(f"{pk:.2f} Hz", (pk, P.max()),
                         xytext=(4, -10 * (i + 1)), textcoords="offset points",
                         fontsize=8)
    axes[3].set_xlabel(f"frequency (Hz)   [Nyquist = {fs/2:.0f} Hz at this "
                       "sampling rate]")
    axes[3].set_ylabel("PSD ((m/s²)²/Hz)")
    axes[3].set_xlim(max(1 / (t1 - t0), 0.01), min(100, fs / 2))
    axes[3].grid(alpha=0.3)
    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, f"imu_{stem}.svg")
    fig.tight_layout()
    fig.savefig(out)
    print(f"wrote {out}")

    # second figure: the longitudinal channel. The phone's long (y) axis rides
    # horizontal and ~forward in this mounting, so gravity-free y IS the
    # throttle/brake axis: speed, y acceleration, and its full-length FFT.
    g0 = np.median(imu["A"][:, mi], axis=1)
    ylong = (imu["A"][1] - g0[1])[mi]
    fig2, ax2 = plt.subplots(3, 1, figsize=(13, 8))
    ax2[0].plot(tg, vg, color="#2e4a62")
    ax2[0].set_ylabel("km/h")
    ax2[0].set_title(f"{stem} — longitudinal (phone y) channel")
    ax2[1].plot(ti, ylong, lw=0.3, color="#b5651d")
    ax2[1].set_ylabel("y accel (m/s²)")
    ax2[1].set_xlabel("seconds")
    for ax in ax2[:2]:
        ax.set_xlim(t0, t1)
        ax.grid(alpha=0.3)
    # low-passed longitudinal: 4th-order zero-phase Butterworth at 5 Hz.
    # 5 Hz (not 10) keeps every pedal/vehicle transient — car longitudinal
    # dynamics live below ~3 Hz — while cutting the 12–30 Hz engine/driveline
    # buzz that a 10 Hz corner would let through.
    from scipy.signal import butter, filtfilt
    b, a = butter(4, 5 / (fs / 2))
    ylp = filtfilt(b, a, ylong)
    ax2[2].plot(ti, ylp, lw=0.7, color="#8a1c30")
    ax2[2].axhline(0, color="#333", lw=0.5)
    ax2[2].set_xlim(t0, t1)
    ax2[2].set_ylabel("y accel, 5 Hz low-pass (m/s²)")
    ax2[2].set_xlabel("seconds")
    ax2[2].grid(alpha=0.3)
    out2 = os.path.join(args.out, f"imu_{stem}_long.svg")
    fig2.tight_layout()
    fig2.savefig(out2)
    print(f"wrote {out2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
