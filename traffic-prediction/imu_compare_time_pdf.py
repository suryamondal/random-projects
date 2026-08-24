#!/usr/bin/env python3
"""Two IMU drives of the same road, paged as TIME windows synced by position.

imu_journey_pdf.py pages one drive in 20 s windows against the clock. Two drives
cannot share that axis directly: they are not paced alike, so the same clock
offset lands on different tarmac.

This keeps the time axis — the plot is the familiar one, 20 s per page, each
channel in its own lane with speed full-scale behind — and fixes the sync by
choosing WHERE each window sits:

  1. the reference drive (A) is cut into 20 s windows, 50% overlap;
  2. each window's CENTRE time is converted to an along-route position;
  3. drive B's window is centred on the time B first reached that same position.

So both panels show a true 20 s window centred on the same point of road. The
speeds differ, so the windows do NOT cover the same LENGTH of road — they agree
at the centre and diverge toward the edges. Each panel prints the span it
actually covers, and the map draws both spans so the divergence is visible.

Road features are placed per panel by position, so a breaker appears at each
drive's own crossing time rather than at a shared x.

Position uses the sub-vertex refinement in imu_compare_pdf: ingest's projection
snaps to the nearest route vertex (~6 m apart here), and matching window centres
on a 6 m grid would put +/-3 m of slop into every sync.

Usage:
    python3 imu_frame.py sensors/<recA>.zip        # frames first, both drives
    python3 imu_frame.py sensors/<recB>.zip
    python3 imu_compare_time_pdf.py \
        --a sensors/<recA>.zip --a-gpx gps/office-route/<A>.gpx --a-label Jazz \
        --b sensors/<recB>.zip --b-gpx gps/office-route/<B>.gpx --b-label Brio
"""

import argparse
import datetime as dt
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

import ingest_gpx as ig
from imu_compare_pdf import load_drive, CH

DIR = os.path.dirname(os.path.abspath(__file__))


def arc(d):
    """Monotonic along-route arc-length (m) per sample, and its finite mask."""
    ok = np.isfinite(d["ikm"])
    s = (d["ikm"] * 1000.0 if d["dirn"] == "onward"
         else d["tot"] - d["ikm"] * 1000.0)
    return s, ok


def first_time_at(d, s_target):
    """Time at which the drive FIRST reaches along-route position s_target.

    Position stalls whenever the car is stopped, so the inverse mapping is
    many-to-one; first arrival is taken, which centres the window on reaching
    the spot rather than in the middle of a wait.
    """
    s, ok = arc(d)
    t, s = d["t"][ok], s[ok]
    su, idx = np.unique(s, return_index=True)      # return_index -> first hit
    return float(np.interp(s_target, su, t[idx]))


def panel(ax, d, t0, win, args, label):
    L = args.lane
    OFFS, YL = 2 * L, 3.2 * L
    m = (d["t"] >= t0) & (d["t"] < t0 + win)
    axs = ax.twinx()
    axs.set_ylim(0, args.vmax)
    axs.set_ylabel("km/h", color="#2e4a62", fontsize=8)
    axs.tick_params(colors="#2e4a62", labelsize=7)
    if m.sum() < 10:
        ax.text(.5, .5, "no data", ha="center", va="center",
                transform=ax.transAxes, color="#999")
        ax.set_ylim(-YL, YL); ax.set_xlim(0, win)
        return YL, (np.nan, np.nan)
    tt = d["t"][m] - t0
    sv = np.clip(d["v"][m], 0, args.vmax) / args.vmax * (2 * YL) - YL
    ax.fill_between(tt, -YL, sv, color="#2e4a62", alpha=0.10, zorder=0)
    ax.plot(tt, sv, color="#2e4a62", lw=1.2, alpha=0.55, zorder=1)
    st = d["v"][m] < 2
    if st.any():
        ax.fill_between(tt, -YL, YL, where=st, color="#b2182b", alpha=0.06,
                        step="mid", zorder=0)
    for idx, lab, col, lane in CH:
        off = lane * OFFS
        ax.axhline(off, color=col, lw=0.6, ls="--", alpha=.5, zorder=2)
        for gl in (-1, 1):
            ax.axhline(off + gl, color=col, lw=0.4, ls=":", alpha=.25, zorder=2)
        ax.plot(tt, np.clip(d["Vf"][idx][m], -L, L) + off, lw=0.4, color=col,
                alpha=0.30, zorder=3)
        ax.plot(tt, np.clip(d["MA"][idx][m], -L, L) + off, lw=1.7, color=col,
                label=lab, zorder=4)
    ax.set_ylim(-YL, YL)
    ax.set_xlim(0, win)
    ax.set_yticks([lane * OFFS + g for _, _, _, lane in CH for g in (-1, 0, 1)])
    ax.set_yticklabels(["-1", "0", "+1"] * 3, fontsize=7)
    ax.grid(alpha=.2, axis="x")
    ax.set_zorder(axs.get_zorder() + 1)
    ax.patch.set_visible(False)
    k = d["ikm"][m]
    k0, k1 = (float(k[0]), float(k[-1])) if np.isfinite(k).all() else (np.nan, np.nan)
    ax.set_title(f"{label}    {k0:.3f} → {k1:.3f} km-from-home "
                 f"({abs(k1-k0)*1000:.0f} m covered)", fontsize=10, loc="left")
    return YL, (k0, k1)


def features(ax, d, feat, t0, win, YL, label=True):
    """Draw route features at each drive's OWN crossing time inside the window."""
    s, ok = arc(d)
    t, s = d["t"][ok], s[ok]
    for bd in feat.get("speed_breakers", []):
        st = (bd["km_from_home"] * 1000 if d["dirn"] == "onward"
              else d["tot"] - bd["km_from_home"] * 1000)
        if not (s.min() <= st <= s.max()):
            continue
        su, idx = np.unique(s, return_index=True)
        tc = float(np.interp(st, su, t[idx]))
        if t0 <= tc < t0 + win:
            ax.axvline(tc - t0, color="#333", lw=1.0, ls=":", zorder=6)
            if label:
                ax.text(tc - t0, YL * 0.97, f" breaker {bd['km_from_home']:.2f}",
                        fontsize=7, rotation=90, va="top")
    for c in feat.get("hard_corners_km", []):
        sc = (c * 1000 if d["dirn"] == "onward" else d["tot"] - c * 1000)
        if not (s.min() <= sc <= s.max()):
            continue
        su, idx = np.unique(s, return_index=True)
        tc = float(np.interp(sc, su, t[idx]))
        if t0 <= tc < t0 + win:
            ax.axvline(tc - t0, color="#7b5aa6", lw=0.9, ls="--", alpha=.55, zorder=5)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--a-gpx", required=True)
    ap.add_argument("--a-label", default="A")
    ap.add_argument("--b", required=True)
    ap.add_argument("--b-gpx", required=True)
    ap.add_argument("--b-label", default="B")
    ap.add_argument("--window", type=float, default=20.0)
    ap.add_argument("--overlap", type=float, default=0.5)
    ap.add_argument("--hp", type=float, default=0.1)
    ap.add_argument("--smooth", type=int, default=25)
    ap.add_argument("--lane", type=float, default=2.0)
    ap.add_argument("--vmax", type=float, default=50.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = ig.load_cfg()
    A = load_drive(args.a, args.a_gpx, args.hp, args.smooth, cfg)
    B = load_drive(args.b, args.b_gpx, args.hp, args.smooth, cfg)
    if A["dirn"] != B["dirn"]:
        raise SystemExit(f"different directions: {A['dirn']} vs {B['dirn']}")

    feat_p = os.path.join(DIR, "route_features.json")
    feat = json.load(open(feat_p)) if os.path.exists(feat_p) else {}
    rt, dirn = A["rt"], A["dirn"]
    sA, okA = arc(A)
    sB, okB = arc(B)
    sB_lo, sB_hi = sB[okB].min(), sB[okB].max()

    win, step = args.window, args.window * (1 - args.overlap)
    tA = A["t"][okA]
    starts = np.arange(tA[0], tA[-1] - win + step, step)

    out = args.out or os.path.join(
        DIR, "plots", f"imu_sync_{A['stem']}_vs_{B['stem']}.pdf")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    asp = 1 / np.cos(np.radians(float(np.nanmean(rt["lat"]))))
    HOME, OFF = cfg["stations"]["home"], cfg["stations"]["office"]
    rkm = (np.array(rt["s"]) / 1000 if dirn == "onward"
           else (A["tot"] - np.array(rt["s"])) / 1000)

    pages = 0
    with PdfPages(out) as pdf:
        for pi, t0a in enumerate(starts, 1):
            tc = t0a + win / 2
            s_c = float(np.interp(tc, tA, sA[okA]))
            if not (sB_lo <= s_c <= sB_hi):
                continue                     # centre outside B's coverage
            t0b = first_time_at(B, s_c) - win / 2
            fig = plt.figure(figsize=(13.5, 8.6))
            gs = fig.add_gridspec(2, 2, width_ratios=[3.1, 1],
                                  hspace=0.28, wspace=0.10)
            ax1 = fig.add_subplot(gs[0, 0])
            ax2 = fig.add_subplot(gs[1, 0], sharex=ax1)
            mp = fig.add_subplot(gs[:, 1])
            Y1, ka = panel(ax1, A, t0a, win, args, args.a_label)
            Y2, kb = panel(ax2, B, t0b, win, args, args.b_label)
            features(ax1, A, feat, t0a, win, Y1, label=True)
            features(ax2, B, feat, t0b, win, Y2, label=False)
            for ax in (ax1, ax2):
                ax.axvline(win / 2, color="#e07b39", lw=1.4, alpha=.85, zorder=7)
            ax1.legend(fontsize=7, loc="upper right", ncol=3)
            ax1.tick_params(labelbottom=False)
            ax2.set_xlabel(f"s within the {win:g} s window "
                           f"(orange = synced centre)")
            for ax in (ax1, ax2):
                ax.set_ylabel(f"accel >{args.hp} Hz, {args.smooth}-sample MA\n"
                              f"(m/s², ±{args.lane:g}/lane)", fontsize=8)

            mp.plot(rt["lon"], rt["lat"], color="#dddddd", lw=2.5, zorder=1)
            for d, kk, col, lw in ((A, ka, "#d1495b", 5.0), (B, kb, "#2a9d8f", 2.5)):
                if np.isfinite(kk).all():
                    seg = (rkm >= min(kk)) & (rkm <= max(kk))
                    if seg.any():
                        mp.plot(np.array(rt["lon"])[seg], np.array(rt["lat"])[seg],
                                color=col, lw=lw, zorder=3, solid_capstyle="butt")
            kc = (s_c / 1000 if dirn == "onward" else (A["tot"] - s_c) / 1000)
            j = int(np.argmin(np.abs(rkm - kc)))
            mp.plot(rt["lon"][j], rt["lat"][j], "o", ms=9, color="#e07b39",
                    mec="#333", mew=0.8, zorder=6)
            for bd in feat.get("speed_breakers", []):
                mp.plot(bd["lon"], bd["lat"], "^", ms=5, color="#b2182b", zorder=4)
            for pt, mk, nm in ((HOME, "s", "home"), (OFF, "o", "office")):
                mp.plot(pt["lon"], pt["lat"], mk, ms=7, color="k")
                mp.annotate(nm, (pt["lon"], pt["lat"]), xytext=(6, -2),
                            textcoords="offset points", fontsize=8, fontweight="bold")
            mp.set_aspect(asp)
            mp.set_xticks([]); mp.set_yticks([])
            mp.set_title(f"position\n{args.a_label} thick / {args.b_label} thin",
                         fontsize=8)
            for sp in mp.spines.values():
                sp.set_color("#bbbbbb")

            inb = any(a_ <= kc <= b_ for a_, b_ in
                      [(x["from_km"], x["to_km"])
                       for x in feat.get("broken_stretches", [])])
            fig.suptitle(f"page {pi}   centre {kc:.3f} km-from-home   "
                         f"{args.a_label} t={t0a:.0f}s / {args.b_label} t={t0b:.0f}s"
                         + ("   [BROKEN STRETCH]" if inb else ""),
                         fontsize=12, y=0.975)
            pdf.savefig(fig)
            plt.close(fig)
            pages += 1
        pdf.infodict()["Title"] = (f"{args.a_label} vs {args.b_label} — "
                                   f"position-synced {win:g}s windows")
    print(f"wrote {out}  ({pages} pages, {os.path.getsize(out)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
