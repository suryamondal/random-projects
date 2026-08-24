#!/usr/bin/env python3
"""Two IMU-recorded drives of the SAME road, paged side by side against position.

imu_journey_pdf.py pages one drive against the clock. That cannot compare two
drives: the same pothole arrives at a different second in each recording, so a
time axis puts different pieces of road on the same page. Here the x axis is
POSITION along the reference route, so every page is a fixed stretch of road and
the two panels show what each car did over the identical tarmac.

  top     drive A (three vehicle-frame channels, speed as full-scale background)
  bottom  drive B, same lanes, same scales
  right   the route, this page's stretch highlighted

Two alignments are applied, and the second is the point of the script:

  GPS       each sample is placed by projecting its GPS fix onto the shared
            reference route (arc-length), the same projection ingest uses.
  ROAD      GPS alone leaves 10-20 m of residual offset between two drives, which
            is larger than the features being compared. The road itself fixes
            that: a rough patch is a property of the tarmac, so the ENVELOPE of
            each drive's band-passed vertical channel is (unlike the raw
            waveform, whose phase depends on speed) approximately a function of
            position. Cross-correlating the two envelopes in the position domain
            over sliding windows recovers the residual shift; it is smoothed and
            applied to B. --no-road-align disables this.

Stops are excluded from the traces — at a standstill the vertical channel is
idle vibration, not road, and it would pile onto a single x. Stopped stretches
are drawn as red bands annotated with their duration instead.

Usage:
    python3 imu_frame.py sensors/<recA>.zip          # frames first, both drives
    python3 imu_frame.py sensors/<recB>.zip
    python3 imu_compare_pdf.py \
        --a sensors/<recA>.zip --a-gpx gps/office-route/<A>.gpx --a-label "Jazz" \
        --b sensors/<recB>.zip --b-gpx gps/office-route/<B>.gpx --b-label "Brio"
"""

import argparse
import csv
import datetime as dt
import io
import json
import os
import zipfile

import numpy as np
from scipy.signal import butter, filtfilt, hilbert
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

import analyze_imu as ai
import ingest_gpx as ig
import imu_frame

DIR = os.path.dirname(os.path.abspath(__file__))

CH = [(2, "vertical (up +)", "#4c956c", +1),
      (1, "forward (accel +)", "#b2182b", 0),
      (0, "lateral (+x)", "#7b5aa6", -1)]


def refine_arc_length(route, pts, s_coarse):
    """Sub-vertex arc-length.

    ingest's project_arc_length returns the arc-length OF THE NEAREST VERTEX, so
    position advances in steps of the route's vertex spacing (median ~6 m here).
    That is invisible in section times but it dominates a position axis: at 1 Hz
    a fix moves less than one vertex spacing, so position stalls and then jumps,
    which shows up as a staircase in anything plotted against it.

    This keeps ingest's vertex choice — and with it the forward-window and
    U-turn protection — and only refines WITHIN the two segments adjoining that
    vertex, by dropping a perpendicular onto each and taking the nearer foot.
    Monotonicity is re-imposed, as ingest does.
    """
    rx, ry, rs = np.array(route["x"]), np.array(route["y"]), np.array(route["s"])
    px, py = ig._local_xy([p[1] for p in pts], [p[2] for p in pts],
                          route["lat0"], route["lon0"])
    k = np.clip(np.searchsorted(rs, s_coarse), 0, len(rs) - 1)
    out = np.array(s_coarse, dtype=float)
    for i, ki in enumerate(k):
        best_d, best_s = np.inf, out[i]
        for a in (ki - 1, ki):
            b = a + 1
            if a < 0 or b >= len(rs):
                continue
            ax, ay, bx, by = rx[a], ry[a], rx[b], ry[b]
            dx, dy = bx - ax, by - ay
            den = dx * dx + dy * dy
            if den <= 0:
                continue
            t = np.clip(((px[i] - ax) * dx + (py[i] - ay) * dy) / den, 0.0, 1.0)
            fx, fy = ax + t * dx, ay + t * dy
            d = (px[i] - fx) ** 2 + (py[i] - fy) ** 2
            if d < best_d:
                best_d, best_s = d, rs[a] + t * (rs[b] - rs[a])
        out[i] = best_s
    return np.maximum.accumulate(out)


def epoch0(path):
    """Absolute time of seconds_elapsed = 0, from the first Location row."""
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            r = next(csv.DictReader(io.TextIOWrapper(z.open("Location.csv"))))
    else:
        r = next(csv.DictReader(open(os.path.join(path, "Location.csv"))))
    return (dt.datetime.fromtimestamp(int(r["time"]) / 1e9, dt.timezone.utc)
            - dt.timedelta(seconds=float(r["seconds_elapsed"])))


def load_drive(rec, gpx, hp, smooth, cfg):
    """Vehicle-frame channels, speed and km-from-home for one recording."""
    stem = os.path.splitext(os.path.basename(rec.rstrip("/")))[0]
    fp = os.path.join(DIR, "data", f"{stem}_frame.json")
    R = np.array((json.load(open(fp)) if os.path.exists(fp)
                  else imu_frame.derive(rec))["R"])

    loc, imu = ai.load(rec)
    t, A = imu["t"], imu["A"]
    fs = 1 / np.median(np.diff(t))
    V = R @ A
    b, a = butter(2, hp / (fs / 2), btype="high")
    Vf = np.vstack([filtfilt(b, a, c) for c in V])
    ker = np.ones(smooth) / smooth
    MA = np.vstack([np.convolve(c, ker, mode="same") for c in Vf])
    v = np.interp(t, loc["t"], np.convolve(loc["kmh"], np.ones(3) / 3, mode="same"))

    tz = ig.parse_offset(cfg["timezone_offset"])
    raw = ig.read_points(gpx, tz)
    dirn = ig.classify(raw[0][1], raw[0][2], cfg, raw[-1][1], raw[-1][2])[0]
    rt = json.load(open(ig.route_path(dirn)))
    tot = rt["s"][-1]
    pts, _ = ig.clamp_to_stations(raw, *ig.stations_for(dirn, cfg["stations"]),
                                  cfg.get("station_radius_m", 50))
    s = ig.project_arc_length(rt, pts, cfg.get("sanity_max_kmh", 150))
    s = refine_arc_length(rt, pts, s)
    km = s / 1000 if dirn == "onward" else (tot - s) / 1000
    gt = np.array([p[0].timestamp() for p in pts])
    t0 = epoch0(rec)
    abst = np.array([(t0 + dt.timedelta(seconds=float(x))).timestamp() for x in t])
    ikm = np.interp(abst, gt, km, left=np.nan, right=np.nan)

    # road-signature envelope: band-passed vertical, rectified, in position space
    bb, aa = butter(4, [2 / (fs / 2), min(25, fs / 2 - 1) / (fs / 2)], btype="band")
    env = np.abs(hilbert(filtfilt(bb, aa, V[2])))
    return dict(stem=stem, t=t, fs=fs, Vf=Vf, MA=MA, v=v, ikm=ikm, env=env,
                dirn=dirn, rt=rt, tot=tot, t0=t0, label=None)


def env_on_grid(d, grid, vmin=3.0):
    """Road-response envelope resampled onto a position grid (moving samples)."""
    ok = np.isfinite(d["ikm"]) & (d["v"] > vmin)
    if ok.sum() < 10:
        return np.full(len(grid), np.nan)
    o = np.argsort(d["ikm"][ok])
    x, y = d["ikm"][ok][o], d["env"][ok][o]
    x, idx = np.unique(x, return_index=True)
    return np.interp(grid, x, y[idx], left=np.nan, right=np.nan)


def road_shift(a, b, win_km=0.40, max_shift_km=0.040, step_m=2.0):
    """Residual position offset of B relative to A, from road-envelope matching.

    Returns a callable km -> shift_km (already smoothed). Windows whose best
    correlation is weak contribute nothing and are interpolated across.
    """
    lo = max(np.nanmin(a["ikm"]), np.nanmin(b["ikm"]))
    hi = min(np.nanmax(a["ikm"]), np.nanmax(b["ikm"]))
    grid = np.arange(lo, hi, step_m / 1000.0)
    ea, eb = env_on_grid(a, grid), env_on_grid(b, grid)
    # smooth to ~5 m so the match is on the road's texture, not single jolts
    k = max(3, int(5.0 / step_m))
    ker = np.ones(k) / k
    ea = np.convolve(ea, ker, mode="same")
    eb = np.convolve(eb, ker, mode="same")
    nlag = int(max_shift_km * 1000 / step_m)
    half = int(win_km * 1000 / step_m / 2)
    cs, ss = [], []
    for c in range(half, len(grid) - half, half):
        A_ = ea[c - half:c + half]
        best, bl = -2.0, 0
        for lag in range(-nlag, nlag + 1):
            B_ = eb[c - half + lag:c + half + lag]
            if len(B_) != len(A_):
                continue
            m = np.isfinite(A_) & np.isfinite(B_)
            if m.sum() < half:
                continue
            x, y = A_[m] - A_[m].mean(), B_[m] - B_[m].mean()
            den = np.sqrt((x * x).sum() * (y * y).sum())
            if den <= 0:
                continue
            r = float((x * y).sum() / den)
            if r > best:
                best, bl = r, lag
        if best > 0.35:
            cs.append(grid[c])
            ss.append(bl * step_m / 1000.0)
    if len(cs) < 2:
        return (lambda km: 0.0), 0, np.nan
    cs, ss = np.array(cs), np.array(ss)
    # median-smooth the shift so one bad window cannot bend the alignment
    sm = np.array([np.median(ss[max(0, i - 1):i + 2]) for i in range(len(ss))])
    return ((lambda km: float(np.interp(km, cs, sm))), len(cs),
            float(np.median(np.abs(sm)) * 1000))


def stops(d, kmlo, kmhi, vmin=2.0):
    """[(km, seconds)] for stationary stretches inside the window."""
    m = np.isfinite(d["ikm"]) & (d["ikm"] >= kmlo) & (d["ikm"] <= kmhi)
    if not m.any():
        return []
    st = m & (d["v"] < vmin)
    if not st.any():
        return []
    idx = np.where(st)[0]
    out = []
    for g in np.split(idx, np.where(np.diff(idx) > d["fs"])[0] + 1):
        secs = len(g) / d["fs"]
        if secs >= 2.0:
            out.append((float(np.nanmedian(d["ikm"][g])), secs))
    return out


def panel(ax, d, kmlo, kmhi, args, shift=0.0, title=""):
    L = args.lane
    OFFS, YL = 2 * L, 3.2 * L
    km = d["ikm"] - shift
    m = np.isfinite(km) & (km >= kmlo) & (km <= kmhi) & (d["v"] >= 2.0)
    axs = ax.twinx()
    axs.set_ylim(0, args.vmax)
    axs.set_ylabel("km/h", color="#2e4a62", fontsize=8)
    axs.tick_params(colors="#2e4a62", labelsize=7)
    if m.sum() >= 5:
        o = np.argsort(km[m])
        x = km[m][o]
        sv = np.clip(d["v"][m][o], 0, args.vmax) / args.vmax * (2 * YL) - YL
        ax.fill_between(x, -YL, sv, color="#2e4a62", alpha=0.10, zorder=0)
        ax.plot(x, sv, color="#2e4a62", lw=1.1, alpha=0.55, zorder=1)
        for idx, lab, col, lane in CH:
            off = lane * OFFS
            ax.axhline(off, color=col, lw=0.6, ls="--", alpha=.5, zorder=2)
            for gl in (-1, 1):
                ax.axhline(off + gl, color=col, lw=0.4, ls=":", alpha=.25, zorder=2)
            ax.plot(x, np.clip(d["Vf"][idx][m][o], -L, L) + off, lw=0.4,
                    color=col, alpha=0.30, zorder=3)
            ax.plot(x, np.clip(d["MA"][idx][m][o], -L, L) + off, lw=1.6,
                    color=col, label=lab, zorder=4)
    else:
        ax.text(0.5, 0.5, "no moving data on this stretch", ha="center",
                va="center", transform=ax.transAxes, color="#999", fontsize=10)
    for kmc, secs in stops(d, kmlo, kmhi):
        ax.axvspan(kmc - 0.004, kmc + 0.004, color="#b2182b", alpha=0.13, zorder=0)
        ax.text(kmc, -YL * 0.93, f"stop {secs:.0f}s", fontsize=6.5, rotation=90,
                ha="center", va="bottom", color="#b2182b")
    ax.set_ylim(-YL, YL)
    ax.set_xlim(kmlo, kmhi)
    ax.set_yticks([lane * OFFS + g for _, _, _, lane in CH for g in (-1, 0, 1)])
    ax.set_yticklabels(["-1", "0", "+1"] * 3, fontsize=7)
    ax.grid(alpha=.2, axis="x")
    ax.set_title(title, fontsize=10, loc="left")
    ax.set_zorder(axs.get_zorder() + 1)
    ax.patch.set_visible(False)
    return YL


def features(ax, feat, YL, kmlo, kmhi, label=True):
    for bd in feat.get("speed_breakers", []):
        k = bd["km_from_home"]
        if kmlo <= k <= kmhi:
            ax.axvline(k, color="#333", lw=1.0, ls=":", zorder=6)
            if label:
                ax.text(k, YL * 0.97, f" breaker {k:.2f}", fontsize=7,
                        rotation=90, va="top")
    for bs in feat.get("broken_stretches", []):
        a_, b_ = max(bs["from_km"], kmlo), min(bs["to_km"], kmhi)
        if b_ > a_:
            ax.axvspan(a_, b_, color="#a6761d", alpha=0.07, zorder=0)
    for c in feat.get("hard_corners_km", []):
        if kmlo <= c <= kmhi:
            ax.axvline(c, color="#7b5aa6", lw=0.9, ls="--", alpha=0.55, zorder=5)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--a-gpx", required=True)
    ap.add_argument("--a-label", default="A")
    ap.add_argument("--b", required=True)
    ap.add_argument("--b-gpx", required=True)
    ap.add_argument("--b-label", default="B")
    ap.add_argument("--window", type=float, default=0.20, help="page width, km")
    ap.add_argument("--overlap", type=float, default=0.5)
    ap.add_argument("--hp", type=float, default=0.1)
    ap.add_argument("--smooth", type=int, default=25)
    ap.add_argument("--lane", type=float, default=2.0)
    ap.add_argument("--vmax", type=float, default=50.0)
    ap.add_argument("--no-road-align", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = ig.load_cfg()
    A = load_drive(args.a, args.a_gpx, args.hp, args.smooth, cfg)
    B = load_drive(args.b, args.b_gpx, args.hp, args.smooth, cfg)
    A["label"], B["label"] = args.a_label, args.b_label
    if A["dirn"] != B["dirn"]:
        raise SystemExit(f"different directions: {A['dirn']} vs {B['dirn']}")

    if args.no_road_align:
        shf, nwin, med = (lambda km: 0.0), 0, 0.0
    else:
        shf, nwin, med = road_shift(A, B)
        print(f"road alignment: {nwin} matched windows, "
              f"median |shift| {med:.1f} m applied to {args.b_label}")

    feat_p = os.path.join(DIR, "route_features.json")
    feat = json.load(open(feat_p)) if os.path.exists(feat_p) else {}

    rt, tot, dirn = A["rt"], A["tot"], A["dirn"]
    rkm = (np.array(rt["s"]) / 1000 if dirn == "onward"
           else (tot - np.array(rt["s"])) / 1000)
    lo = max(np.nanmin(A["ikm"]), np.nanmin(B["ikm"]))
    hi = min(np.nanmax(A["ikm"]), np.nanmax(B["ikm"]))
    step = args.window * (1 - args.overlap)
    edges = np.arange(lo, hi - args.window + step, step)

    out = args.out or os.path.join(
        DIR, "plots", f"imu_compare_{A['stem']}_vs_{B['stem']}.pdf")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    asp = 1 / np.cos(np.radians(float(np.nanmean(rt["lat"]))))
    HOME, OFF = cfg["stations"]["home"], cfg["stations"]["office"]

    with PdfPages(out) as pdf:
        for pi, k0 in enumerate(edges, 1):
            k1 = k0 + args.window
            fig = plt.figure(figsize=(13.5, 8.6))
            gs = fig.add_gridspec(2, 2, width_ratios=[3.1, 1],
                                  hspace=0.22, wspace=0.10)
            ax1 = fig.add_subplot(gs[0, 0])
            ax2 = fig.add_subplot(gs[1, 0], sharex=ax1)
            mp = fig.add_subplot(gs[:, 1])
            sh = shf((k0 + k1) / 2)
            Y1 = panel(ax1, A, k0, k1, args, 0.0, f"{args.a_label}")
            Y2 = panel(ax2, B, k0, k1, args, sh,
                       f"{args.b_label}" + (f"   (road-aligned {sh*1000:+.0f} m)"
                                            if sh else ""))
            for ax, Y in ((ax1, Y1), (ax2, Y2)):
                features(ax, feat, Y, k0, k1, label=(ax is ax1))
            ax1.legend(fontsize=7, loc="upper right", ncol=3)
            ax1.tick_params(labelbottom=False)
            ax2.set_xlabel("position (km from home)")
            ax1.set_ylabel(f"accel >{args.hp} Hz, {args.smooth}-sample MA "
                           f"(m/s², ±{args.lane:g}/lane)", fontsize=8)
            ax2.set_ylabel(f"accel >{args.hp} Hz, {args.smooth}-sample MA "
                           f"(m/s², ±{args.lane:g}/lane)", fontsize=8)

            mp.plot(rt["lon"], rt["lat"], color="#cccccc", lw=2.5, zorder=1)
            seg = (rkm >= k0) & (rkm <= k1)
            if seg.any():
                mp.plot(np.array(rt["lon"])[seg], np.array(rt["lat"])[seg],
                        color="#2e4a62", lw=3.5, zorder=4)
                c = np.where(seg)[0][seg.sum() // 2]
                mp.plot(rt["lon"][c], rt["lat"][c], "o", ms=9, color="#e07b39",
                        mec="#333", mew=0.8, zorder=5)
            for bd in feat.get("speed_breakers", []):
                mp.plot(bd["lon"], bd["lat"], "^", ms=5, color="#b2182b", zorder=3)
            for pt, mk, nm in ((HOME, "s", "home"), (OFF, "o", "office")):
                mp.plot(pt["lon"], pt["lat"], mk, ms=7, color="k")
                mp.annotate(nm, (pt["lon"], pt["lat"]), xytext=(6, -2),
                            textcoords="offset points", fontsize=8,
                            fontweight="bold")
            mp.set_aspect(asp)
            mp.set_xticks([]); mp.set_yticks([])
            mp.set_title("position", fontsize=9)
            for sp in mp.spines.values():
                sp.set_color("#bbbbbb")

            inb = any(a_ <= (k0 + k1) / 2 <= b_
                      for a_, b_ in [(x["from_km"], x["to_km"])
                                     for x in feat.get("broken_stretches", [])])
            fig.suptitle(f"page {pi}/{len(edges)}   {k0:.2f}–{k1:.2f} km-from-home"
                         f"   ({dirn})" + ("   [BROKEN STRETCH]" if inb else ""),
                         fontsize=12, y=0.98)
            pdf.savefig(fig)
            plt.close(fig)
        pdf.infodict()["Title"] = (f"{args.a_label} vs {args.b_label} — "
                                   f"road-referenced IMU comparison")
    print(f"wrote {out}  ({len(edges)} pages, {os.path.getsize(out)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
