#!/usr/bin/env python3
"""Page through an IMU-recorded drive: overlapping windows, one page each.

A 30-minute 100 Hz recording is unreadable as one figure, and a single |a|
magnitude trace hides what the driver actually did. This renders the drive as a
PDF flipbook so events can be found by eye and placed on the route:

  main panel  the three VEHICLE-frame channels (vertical / forward / lateral,
              from imu_frame.py) stacked in separate lanes, faint raw behind a
              bold moving average, with GPS SPEED drawn full-scale in the
              background so every input is read against what the car was doing
  right       the route, the window's path highlighted, a marker at its
              midpoint, curated speed breakers as triangles

Windows overlap by half, so nothing hides at a page boundary.

Scaling matters more than it sounds: ordinary driving inputs are a few tenths of
m/s^2 while an impact is several, so a shared axis flattens real manoeuvres into
apparent silence. Each channel gets its own lane clipped at --lane; impacts clip
instead of compressing everything else.

Filtering is a zero-phase (filtfilt) high-pass above --hp Hz: slow drift and the
gravity residual go, event timing is not shifted.

Usage:
    python3 imu_frame.py sensors/<rec>.zip          # first, derive the frame
    python3 imu_journey_pdf.py sensors/<rec>.zip --gpx gps/office-route/<t>.gpx
"""

import argparse
import csv
import datetime as dt
import io
import json
import os
import zipfile

import numpy as np
from scipy.signal import butter, filtfilt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

import analyze_imu as ai
import ingest_gpx as ig
import imu_frame

DIR = os.path.dirname(os.path.abspath(__file__))


def epoch0(path):
    """Absolute time of seconds_elapsed = 0, from the first Location row."""
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            r = next(csv.DictReader(io.TextIOWrapper(z.open("Location.csv"))))
    else:
        r = next(csv.DictReader(open(os.path.join(path, "Location.csv"))))
    return (dt.datetime.fromtimestamp(int(r["time"]) / 1e9, dt.timezone.utc)
            - dt.timedelta(seconds=float(r["seconds_elapsed"])))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rec")
    ap.add_argument("--gpx", required=True, help="the paired commute trace")
    ap.add_argument("--window", type=float, default=20.0)
    ap.add_argument("--overlap", type=float, default=0.5)
    ap.add_argument("--hp", type=float, default=0.1, help="high-pass Hz")
    ap.add_argument("--smooth", type=int, default=25, help="moving-average samples")
    ap.add_argument("--lane", type=float, default=2.0, help="clip per lane (m/s^2)")
    ap.add_argument("--vmax", type=float, default=50.0, help="speed background full scale")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    stem = os.path.splitext(os.path.basename(args.rec.rstrip("/")))[0]
    fp = os.path.join(DIR, "data", f"{stem}_frame.json")
    R = np.array((json.load(open(fp)) if os.path.exists(fp)
                  else imu_frame.derive(args.rec))["R"])

    loc, imu = ai.load(args.rec)
    t, A = imu["t"], imu["A"]
    fs = 1 / np.median(np.diff(t))
    V = R @ A
    b, a = butter(2, args.hp / (fs / 2), btype="high")
    Vf = np.vstack([filtfilt(b, a, c) for c in V])
    ker = np.ones(args.smooth) / args.smooth
    MA = np.vstack([np.convolve(c, ker, mode="same") for c in Vf])
    v = np.interp(t, loc["t"], np.convolve(loc["kmh"], np.ones(3) / 3, mode="same"))

    cfg = ig.load_cfg()
    tz = ig.parse_offset(cfg["timezone_offset"])
    raw = ig.read_points(args.gpx, tz)
    dirn = ig.classify(raw[0][1], raw[0][2], cfg, raw[-1][1], raw[-1][2])[0]
    rt = json.load(open(ig.route_path(dirn)))
    tot = rt["s"][-1]
    pts, _ = ig.clamp_to_stations(raw, *ig.stations_for(dirn, cfg["stations"]),
                                  cfg.get("station_radius_m", 50))
    s = ig.project_arc_length(rt, pts, cfg.get("sanity_max_kmh", 150))
    km = s / 1000 if dirn == "onward" else (tot - s) / 1000
    gt = np.array([p[0].timestamp() for p in pts])
    t0 = epoch0(args.rec)
    abst = np.array([(t0 + dt.timedelta(seconds=float(x))).timestamp() for x in t])
    ikm = np.interp(abst, gt, km, left=np.nan, right=np.nan)
    ilat = np.interp(abst, gt, [p[1] for p in pts], left=np.nan, right=np.nan)
    ilon = np.interp(abst, gt, [p[2] for p in pts], left=np.nan, right=np.nan)

    feat_p = os.path.join(DIR, "route_features.json")
    feat = json.load(open(feat_p)) if os.path.exists(feat_p) else {}
    brk = feat.get("speed_breakers", [])
    brokn = [(x["from_km"], x["to_km"]) for x in feat.get("broken_stretches", [])]

    L = args.lane
    OFFS, YL = 2 * L, 3.2 * L          # lanes at +/-2L, axis +/-3.2L
    CH = [(2, "vertical (up +)", "#4c956c", +OFFS),
          (1, "forward (accel +)", "#b2182b", 0.0),
          (0, "lateral (+x)", "#7b5aa6", -OFFS)]
    step = args.window * (1 - args.overlap)
    starts = np.arange(t[0], t[-1] - args.window + step, step)
    out = args.out or os.path.join(DIR, "plots", f"imu_journey_{stem}.pdf")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    asp = 1 / np.cos(np.radians(float(np.nanmean(rt["lat"]))))
    HOME, OFF = cfg["stations"]["home"], cfg["stations"]["office"]

    with PdfPages(out) as pdf:
        for pi, ts in enumerate(starts, 1):
            m = (t >= ts) & (t < ts + args.window)
            if m.sum() < 50:
                continue
            fig = plt.figure(figsize=(13.5, 8.3))
            gs = fig.add_gridspec(1, 2, width_ratios=[3.1, 1], wspace=0.10)
            ax = fig.add_subplot(gs[0, 0])
            mp = fig.add_subplot(gs[0, 1])
            tt = t[m] - ts
            # --- speed as full-scale background ---
            sv = np.clip(v[m], 0, args.vmax) / args.vmax * (2 * YL) - YL
            ax.fill_between(tt, -YL, sv, color="#2e4a62", alpha=0.10, zorder=0)
            ax.plot(tt, sv, color="#2e4a62", lw=1.2, alpha=0.55, zorder=1)
            st = v[m] < 2
            if st.any():
                ax.fill_between(tt, -YL, YL, where=st, color="#b2182b",
                                alpha=0.06, step="mid", zorder=0)
            axs = ax.twinx()
            axs.set_ylim(0, args.vmax)
            axs.set_ylabel("speed (km/h) — background", color="#2e4a62", fontsize=9)
            axs.tick_params(colors="#2e4a62", labelsize=8)
            # --- three channel lanes ---
            for idx, lab, col, off in CH:
                ax.axhline(off, color=col, lw=0.6, ls="--", alpha=.5, zorder=2)
                for gl in (-1, 1):
                    ax.axhline(off + gl, color=col, lw=0.4, ls=":", alpha=.25, zorder=2)
                ax.plot(tt, np.clip(Vf[idx][m], -L, L) + off, lw=0.4,
                        color=col, alpha=0.30, zorder=3)
                ax.plot(tt, np.clip(MA[idx][m], -L, L) + off, lw=1.7,
                        color=col, label=lab, zorder=4)
            ax.set_ylim(-YL, YL)
            ax.set_xlim(0, args.window)
            ax.set_yticks([o + g for _, _, _, o in CH for g in (-1, 0, 1)])
            ax.set_yticklabels(["-1", "0", "+1"] * 3, fontsize=8)
            ax.set_ylabel(f"accel >{args.hp} Hz zero-phase, {args.smooth}-sample MA "
                          f"(m/s², clipped ±{L:g} per lane)")
            ax.set_xlabel(f"s from {ts:.0f} s")
            ax.grid(alpha=.2, axis="x")
            ax.legend(fontsize=8, loc="upper right", ncol=3)
            ax.set_zorder(axs.get_zorder() + 1)
            ax.patch.set_visible(False)
            for bd in brk:
                i2 = np.where(np.abs(ikm[m] - bd["km_from_home"]) < 0.02)[0]
                if len(i2):
                    x = tt[i2[len(i2) // 2]]
                    ax.axvline(x, color="#333", lw=0.9, ls=":", zorder=5)
                    ax.text(x, YL * 0.96, f"breaker {bd['km_from_home']:.2f}",
                            fontsize=7, rotation=90, va="top")
            # --- map ---
            mp.plot(rt["lon"], rt["lat"], color="#cccccc", lw=2.5, zorder=1)
            for bd in brk:
                mp.plot(bd["lon"], bd["lat"], "^", ms=5, color="#b2182b", zorder=3)
            seg = np.isfinite(ilat[m])
            if seg.any():
                mp.plot(ilon[m][seg], ilat[m][seg], color="#2e4a62", lw=3.5, zorder=4)
                c = seg.sum() // 2
                mp.plot(ilon[m][seg][c], ilat[m][seg][c], "o", ms=9,
                        color="#e07b39", mec="#333", mew=0.8, zorder=5)
            for pt, mk, nm in ((HOME, "s", "home"), (OFF, "o", "office")):
                mp.plot(pt["lon"], pt["lat"], mk, ms=7, color="k")
                mp.annotate(nm, (pt["lon"], pt["lat"]), xytext=(6, -2),
                            textcoords="offset points", fontsize=8, fontweight="bold")
            mp.set_aspect(asp)
            mp.set_xticks([]); mp.set_yticks([])
            mp.set_title("position", fontsize=9)
            for sp in mp.spines.values():
                sp.set_color("#bbbbbb")
            k0, k1 = ikm[m][0], ikm[m][-1]
            clock = t0 + dt.timedelta(seconds=float(ts)) + dt.timedelta(hours=5, minutes=30)
            rng = (f"{k0:.2f} → {k1:.2f} km-from-home"
                   if np.isfinite(k0) and np.isfinite(k1) else "off-route")
            kk = np.nanmean(ikm[m]) if np.isfinite(ikm[m]).any() else np.nan
            inb = np.isfinite(kk) and any(a_ <= kk <= b_ for a_, b_ in brokn)
            ax.set_title(f"page {pi}/{len(starts)}   t {ts:.0f}–{ts+args.window:.0f} s   "
                         f"{clock:%H:%M:%S} IST   {rng}"
                         + ("   [BROKEN STRETCH]" if inb else ""), fontsize=11)
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)
        pdf.infodict()["Title"] = f"{stem} — vehicle-frame journey scan"
    print(f"wrote {out}  ({len(starts)} pages, {os.path.getsize(out)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
