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
from scipy.signal import coherence, welch
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


def panel(ax, d, t0, win, args, label, resid=False):
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
        if resid:
            # what the moving average discards: actual minus the MA already
            # drawn on the main page
            r = d["Vf"][idx][m] - d["MA"][idx][m]
            ax.plot(tt, np.clip(r, -L, L) + off, lw=0.5, color=col,
                    label=lab, zorder=4)
        else:
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
    kf = k[np.isfinite(k)]          # a window may start before GPX coverage;
    k0, k1 = ((float(kf[0]), float(kf[-1]))   # one NaN must not void the range
              if len(kf) else (np.nan, np.nan))
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


def resample_window(d, t0, win, s_all, ok, s_c, step=0.10):
    """The window's three channels re-indexed by POSITION, on a uniform grid.

    Each sample is placed at its own along-route position (metres from the
    synced centre) — not stretched by a single factor, because speed varies
    inside the window too. DC-blocked channels only; no band-pass, since a
    time-domain filter admits different SPATIAL wavelengths from each car.
    """
    m = (d["t"] >= t0) & (d["t"] < t0 + win) & ok
    if m.sum() < 50:
        return None
    x = s_all[m] - s_c
    o = np.argsort(x)
    x = x[o]
    xu, iu = np.unique(x, return_index=True)
    if xu[-1] - xu[0] < 10:
        return None
    g = np.arange(xu[0], xu[-1], step)          # uniform metres grid
    ch = [np.interp(g, xu, d["Vf"][idx][m][o][iu]) for idx, _, _, _ in CH]
    return g, ch


def gcc(a, b, step, mode="phat"):
    """Cross-correlation vs spatial lag. mode='phat' whitens the cross-spectrum."""
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    X, Y = np.fft.rfft(a, n), np.fft.rfft(b, n)
    R = X * np.conj(Y)
    if mode == "phat":
        R = R / (np.abs(R) + 1e-12)
    c = np.fft.irfft(R, n)
    c = np.concatenate((c[-(n // 2):], c[:n // 2]))
    c = c / (np.max(np.abs(c)) + 1e-12)
    return c, np.arange(-(n // 2), n // 2) * step


def dist_panel(ax, w, args, label, other=None):
    """One drive's three channels on the distance axis; `other` drawn faint behind."""
    L = args.lane
    OFFS, YL = 2 * L, 3.2 * L
    k = 25                                   # ~2.5 m moving average at 0.10 m
    ker = np.ones(k) / k
    if other is not None:
        x, ch = other
        for (idx, lab, col, lane), y in zip(CH, ch):
            ma = np.convolve(y, ker, mode="same") if len(y) > k else y
            ax.plot(x, np.clip(ma, -L, L) + lane * OFFS, "--", color="#999999",
                    lw=1.0, alpha=.8, zorder=2)
    if w is None:
        ax.text(.5, .5, "stationary in this window — no distance span to "
                        "resample onto", ha="center", va="center",
                transform=ax.transAxes, color="#b2182b", fontsize=9)
    else:
        x, ch = w
        for (idx, lab, col, lane), y in zip(CH, ch):
            off = lane * OFFS
            ax.plot(x[::3], np.clip(y, -L, L)[::3] + off, color=col,
                    lw=0.35, alpha=0.25, zorder=3)
            ma = np.convolve(y, ker, mode="same") if len(y) > k else y
            ax.plot(x, np.clip(ma, -L, L) + off, color=col, lw=1.6,
                    label=lab, zorder=4)
    for idx, lab, col, lane in CH:
        ax.axhline(lane * OFFS, color=col, lw=0.5, ls=":", alpha=.45)
    ax.axvline(0, color="#e07b39", lw=1.4, alpha=.85, zorder=5)
    ax.set_ylim(-YL, YL)
    ax.set_yticks([lane * OFFS + g for _, _, _, lane in CH for g in (-1, 0, 1)])
    ax.set_yticklabels(["-1", "0", "+1"] * 3, fontsize=7)
    ax.set_ylabel(f"accel >0.1 Hz, 2.5 m MA\n(m/s², ±{L:g}/lane)", fontsize=8)
    ax.set_title(f"{label} — resampled onto distance"
                 + ("   (other drive dashed grey)" if other is not None else ""),
                 fontsize=10, loc="left")
    ax.grid(alpha=.25)


def coh_panel(ax, wa, wb, step=0.10):
    """Magnitude-squared coherence of the vertical channels vs SPATIAL frequency."""
    if wa is None or wb is None:
        ax.text(.5, .5, "no overlap", ha="center", va="center",
                transform=ax.transAxes, color="#999", fontsize=8)
        ax.set_xticks([]); ax.set_yticks([]); return
    lo, hi = max(wa[0][0], wb[0][0]), min(wa[0][-1], wb[0][-1])
    if hi - lo < 20:
        ax.text(.5, .5, "overlap too short", ha="center", va="center",
                transform=ax.transAxes, color="#999", fontsize=8)
        ax.set_xticks([]); ax.set_yticks([]); return
    g = np.arange(lo, hi, step)
    a = np.interp(g, wa[0], wa[1][0]); b = np.interp(g, wb[0], wb[1][0])
    nper = max(64, min(512, len(g) // 6))
    f, Cxy = coherence(a - a.mean(), b - b.mean(), fs=1.0 / step,
                       nperseg=nper, noverlap=nper // 2)
    ax.semilogx(f[1:], Cxy[1:], color="#4c956c", lw=1.3)
    ax.axhline(np.mean(Cxy[1:]), color="#b2182b", lw=1.0, ls="--")
    ax.set_ylim(0, 1)
    ax.set_xlabel("spatial frequency (cycles/m)", fontsize=8)
    ax.set_ylabel("coherence", fontsize=8)
    ax.set_title(f"vertical coherence   mean {np.mean(Cxy[1:]):.2f}",
                 fontsize=8, loc="left")
    ax.set_ylabel("coherence  (1 = identical)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(alpha=.25, which="both")


def gcc_panel(ax, wa, wb, step=0.10):
    """GCC-PHAT of the VERTICAL channels, with its own reliability number."""
    if wa is None or wb is None:
        ax.text(.5, .5, "no overlap", ha="center", va="center",
                transform=ax.transAxes, color="#999", fontsize=8)
        ax.set_xticks([]); ax.set_yticks([])
        return
    lo, hi = max(wa[0][0], wb[0][0]), min(wa[0][-1], wb[0][-1])
    if hi - lo < 15:
        ax.text(.5, .5, f"overlap only {hi-lo:.0f} m", ha="center", va="center",
                transform=ax.transAxes, color="#999", fontsize=8)
        ax.set_xticks([]); ax.set_yticks([])
        return
    g = np.arange(lo, hi, step)
    a = np.interp(g, wa[0], wa[1][0]); b = np.interp(g, wb[0], wb[1][0])
    a = a - a.mean(); b = b - b.mean()
    cp, lg = gcc(a, b, step, "phat")
    cx, _ = gcc(a, b, step, "plain")
    span = min(40.0, (hi - lo) / 2)
    sel = np.abs(lg) <= span
    ax.plot(lg[sel], cp[sel], color="#8fa8c8", lw=0.7, alpha=.8, label="PHAT")
    ax.plot(lg[sel], cx[sel], color="#1d3557", lw=1.5, label="plain")
    k = int(np.argmax(cp[sel]))
    lag = lg[sel][k]
    srt = np.sort(cp[sel])[::-1]
    ratio = srt[1] / srt[0] if srt[0] > 0 else 1.0
    ax.axvline(lag, color="#b2182b", lw=1.2, ls="--")
    ok = ratio < 0.80
    ax.set_title(f"GCC-PHAT (vertical)   lag {lag:+.1f} m\n"
                 f"2nd/1st = {ratio:.2f}  "
                 + ("(usable peak)" if ok else "NO DISTINCT PEAK"),
                 fontsize=8, loc="left",
                 color=("#2e6b47" if ok else "#b2182b"))
    ax.set_xlabel("spatial lag (m)", fontsize=8)
    ax.set_xlim(-span, span)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=6, loc="lower right")
    ax.grid(alpha=.25)



NPER = 512          # ~0.2 Hz bins at 100 Hz; ~7 averages inside a 20 s window


def window_psds(d, t0s, win):
    """PSD of every window, per channel. Returns (freqs, [[P_ch0, P_ch1, P_ch2], ...])."""
    fs = 1.0 / np.median(np.diff(d["t"]))
    f = None
    out = []
    for t0 in t0s:
        m = (d["t"] >= t0) & (d["t"] < t0 + win)
        row = []
        for idx, _, _, _ in CH:
            if m.sum() < NPER * 2:
                row.append(None)
                continue
            f, P = welch(d["Vf"][idx][m], fs=fs, nperseg=NPER)
            row.append(P)
        out.append(row)
    return f, out


def moving_avg(psds, k):
    """Running mean of the per-window spectra over +/-k//2 neighbouring windows.

    The baseline is LOCAL, so a page shows what is unusual about this stretch
    against the road either side of it — not against the whole drive. Windows
    overlap by half, so k=9 spans roughly the surrounding 60 s of driving.
    """
    n = len(psds)
    out = []
    for i in range(n):
        lo, hi = max(0, i - k // 2), min(n, i + k // 2 + 1)
        row = []
        for c in range(len(CH)):
            vals = [psds[j][c] for j in range(lo, hi) if psds[j][c] is not None]
            row.append(np.mean(vals, axis=0) if vals else None)
        out.append(row)
    return out


def spec_dev_panel(ax, f, Pact, Pbase, label, k, fmax=49.0):
    """Actual spectrum minus its local moving average, in dB.

    0 dB = this window matches the road/driving either side of it. A peak means
    that band is louder here than the surrounding stretch; a trough means
    quieter. Baseline is per-drive and local, so each panel is measured against
    its own recent history and the two panels stay comparable across cars.
    """
    any_drawn = False
    for (idx, lab, col, _), Pa, Pb in zip(CH, Pact, Pbase):
        if Pa is None or Pb is None:
            continue
        sel = (f > 0.3) & (f <= fmax)
        dev = 10.0 * np.log10((Pa[sel] + 1e-18) / (Pb[sel] + 1e-18))
        ax.semilogx(f[sel], dev, color=col, lw=1.4, label=lab)
        any_drawn = True
    if not any_drawn:
        ax.text(.5, .5, "window too short for a spectrum", ha="center",
                va="center", transform=ax.transAxes, color="#999", fontsize=9)
    ax.axhline(0, color="#333", lw=1.0, ls="--", alpha=.7)
    ax.set_ylim(-15, 15)
    ax.set_xlim(0.3, fmax)
    ax.set_ylabel("actual − moving avg (dB)", fontsize=8)
    ax.set_title(f"{label} — spectrum vs its local {k}-window moving average",
                 fontsize=10, loc="left")
    ax.grid(alpha=.25, which="both")
    ax.tick_params(labelsize=7)



def draw_map(mp, rt, rkm, feat, cfg, asp, ka, kb, kc, a_lab, b_lab):
    mp.plot(rt["lon"], rt["lat"], color="#dddddd", lw=2.5, zorder=1)
    for kk, col, lw in ((ka, "#d1495b", 5.0), (kb, "#2a9d8f", 2.5)):
        if kk is not None and np.isfinite(kk).all():
            seg = (rkm >= min(kk)) & (rkm <= max(kk))
            if seg.any():
                mp.plot(np.array(rt["lon"])[seg], np.array(rt["lat"])[seg],
                        color=col, lw=lw, zorder=3, solid_capstyle="butt")
    j = int(np.argmin(np.abs(rkm - kc)))
    mp.plot(rt["lon"][j], rt["lat"][j], "o", ms=9, color="#e07b39",
            mec="#333", mew=0.8, zorder=6)
    for bd in feat.get("speed_breakers", []):
        mp.plot(bd["lon"], bd["lat"], "^", ms=5, color="#b2182b", zorder=4)
    for pt, mk, nm in ((cfg["stations"]["home"], "s", "home"),
                       (cfg["stations"]["office"], "o", "office")):
        mp.plot(pt["lon"], pt["lat"], mk, ms=7, color="k")
        mp.annotate(nm, (pt["lon"], pt["lat"]), xytext=(6, -2),
                    textcoords="offset points", fontsize=8, fontweight="bold")
    mp.set_aspect(asp)
    mp.set_xticks([]); mp.set_yticks([])
    mp.set_title(f"position\n{a_lab} thick / {b_lab} thin", fontsize=8)
    for sp in mp.spines.values():
        sp.set_color("#bbbbbb")


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
    ap.add_argument("--alt-page", choices=("none", "diff", "spec", "gcc"),
                    default="none",
                    help="content of an extra page inserted after each main page. "
                         "'diff': actual minus the moving average already drawn "
                         "on the main page — what the smoothing discards. "
                         "'spec': each window's spectrum as a dB deviation "
                         "from its own local --spec-ma window moving average. "
                         "'gcc': distance-resampled channels with GCC-PHAT and "
                         "coherence — note measured coherence over a 20 s window "
                         "is ~0.11, so its lag has no shared signal to come from.")
    ap.add_argument("--spec-ma", type=int, default=9,
                    help="windows in the moving-average baseline (default 9)")
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
    rkm = (np.array(rt["s"]) / 1000 if dirn == "onward"
           else (A["tot"] - np.array(rt["s"])) / 1000)

    # every window first: a moving-average baseline cannot be formed one page
    # at a time, it needs the neighbours on both sides
    wins = []
    for pi, t0a in enumerate(starts, 1):
        s_c = float(np.interp(t0a + win / 2, tA, sA[okA]))
        if not (sB_lo <= s_c <= sB_hi):
            continue                         # centre outside B's coverage
        wins.append((pi, t0a, first_time_at(B, s_c) - win / 2, s_c))

    if args.alt_page == "spec":
        fA, SPA = window_psds(A, [w[1] for w in wins], win)
        fB, SPB = window_psds(B, [w[2] for w in wins], win)
        MAA, MAB = moving_avg(SPA, args.spec_ma), moving_avg(SPB, args.spec_ma)

    pages = 0
    with PdfPages(out) as pdf:
        for wi, (pi, t0a, t0b, s_c) in enumerate(wins):
            kc = (s_c / 1000 if dirn == "onward" else (A["tot"] - s_c) / 1000)
            inb = any(a_ <= kc <= b_ for a_, b_ in
                      [(x["from_km"], x["to_km"])
                       for x in feat.get("broken_stretches", [])])
            hdr = (f"centre {kc:.3f} km-from-home   "
                   f"{args.a_label} t={t0a:.0f}s / {args.b_label} t={t0b:.0f}s"
                   + ("   [BROKEN STRETCH]" if inb else ""))

            # ---------------- page A: the original time-axis comparison -------
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
                ax.set_ylabel(f"accel >{args.hp} Hz, {args.smooth}-sample MA\n"
                              f"(m/s², ±{args.lane:g}/lane)", fontsize=8)
            ax1.legend(fontsize=7, loc="upper right", ncol=3)
            ax1.tick_params(labelbottom=False)
            ax2.set_xlabel(f"s within the {win:g} s window "
                           f"(orange = synced centre)")
            draw_map(mp, rt, rkm, feat, cfg, asp, ka, kb, kc,
                     args.a_label, args.b_label)
            fig.suptitle(f"page {pi}{'a' if args.alt_page != 'none' else ''}"
                         f"   {hdr}", fontsize=12, y=0.975)
            pdf.savefig(fig); plt.close(fig); pages += 1

            # ---------------- page B --------------------------------------
            if args.alt_page == "none":
                continue
            if args.alt_page == "diff":
                fig = plt.figure(figsize=(13.5, 8.6))
                gs = fig.add_gridspec(2, 2, width_ratios=[3.1, 1],
                                      hspace=0.28, wspace=0.10)
                dx1 = fig.add_subplot(gs[0, 0])
                dx2 = fig.add_subplot(gs[1, 0], sharex=dx1)
                mp2 = fig.add_subplot(gs[:, 1])
                Z1, _ = panel(dx1, A, t0a, win, args, args.a_label, resid=True)
                Z2, _ = panel(dx2, B, t0b, win, args, args.b_label, resid=True)
                features(dx1, A, feat, t0a, win, Z1, label=True)
                features(dx2, B, feat, t0b, win, Z2, label=False)
                for ax in (dx1, dx2):
                    ax.axvline(win / 2, color="#e07b39", lw=1.4, alpha=.85,
                               zorder=7)
                    ax.set_ylabel(f"actual − {args.smooth}-sample MA\n"
                                  f"(m/s², ±{args.lane:g}/lane)", fontsize=8)
                dx1.legend(fontsize=7, loc="upper right", ncol=3)
                dx1.tick_params(labelbottom=False)
                dx2.set_xlabel(f"s within the {win:g} s window "
                               f"(orange = synced centre)")
                draw_map(mp2, rt, rkm, feat, cfg, asp, ka, kb, kc,
                         args.a_label, args.b_label)
                fig.suptitle(f"page {pi}b   {hdr}   [residual]",
                             fontsize=12, y=0.975)
                pdf.savefig(fig); plt.close(fig); pages += 1
                continue
            if args.alt_page == "spec":
                fig = plt.figure(figsize=(13.5, 8.6))
                gs = fig.add_gridspec(2, 2, width_ratios=[3.1, 1],
                                      hspace=0.30, wspace=0.10)
                cx1 = fig.add_subplot(gs[0, 0])
                cx2 = fig.add_subplot(gs[1, 0], sharex=cx1)
                mp2 = fig.add_subplot(gs[:, 1])
                spec_dev_panel(cx1, fA, SPA[wi], MAA[wi], args.a_label,
                               args.spec_ma)
                spec_dev_panel(cx2, fB, SPB[wi], MAB[wi], args.b_label,
                               args.spec_ma)
                cx1.legend(fontsize=7, loc="upper right", ncol=3)
                cx1.tick_params(labelbottom=False)
                cx2.set_xlabel("frequency (Hz)")
                draw_map(mp2, rt, rkm, feat, cfg, asp, ka, kb, kc,
                         args.a_label, args.b_label)
                fig.suptitle(f"page {pi}b   {hdr}", fontsize=12, y=0.975)
                pdf.savefig(fig); plt.close(fig); pages += 1
                continue
            wa = resample_window(A, t0a, win, sA, okA, s_c)
            wb = resample_window(B, t0b, win, sB, okB, s_c)
            fig = plt.figure(figsize=(13.5, 10.0))
            gs = fig.add_gridspec(3, 3, width_ratios=[2.35, 0.85, 1.0],
                                  height_ratios=[1, 1, 0.72],
                                  hspace=0.40, wspace=0.20)
            bx1 = fig.add_subplot(gs[0, 0:2])
            bx2 = fig.add_subplot(gs[1, 0:2], sharex=bx1)
            bx3 = fig.add_subplot(gs[2, 0])
            bx4 = fig.add_subplot(gs[2, 1])
            mp2 = fig.add_subplot(gs[:, 2])
            dist_panel(bx1, wa, args, args.a_label)
            dist_panel(bx2, wb, args, args.b_label)
            bx1.legend(fontsize=7, loc="upper right", ncol=3)
            bx1.tick_params(labelbottom=False)
            bx2.set_xlabel("metres from synced centre  (position-resampled; "
                           "orange = centre)")
            gcc_panel(bx3, wa, wb)
            coh_panel(bx4, wa, wb)
            draw_map(mp2, rt, rkm, feat, cfg, asp, ka, kb, kc,
                     args.a_label, args.b_label)
            fig.suptitle(f"page {pi}b   {hdr}", fontsize=12, y=0.978)
            pdf.savefig(fig); plt.close(fig); pages += 1

        pdf.infodict()["Title"] = (f"{args.a_label} vs {args.b_label} — "
                                   f"position-synced {win:g}s windows")
    print(f"wrote {out}  ({pages} pages, {os.path.getsize(out)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
