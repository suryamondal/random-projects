#!/usr/bin/env python3
"""Driving-style learning curve from the recorded GPS traces.

The Honda Jazz traces are a first-time car driver's first weeks; the KTM Duke 390
traces are the same driver after ~10 years on the bike (an expert baseline), and
the RE Hunter 350 is a sedate, experienced reference rider. Same road, so the
Duke's flat trend is the control: if the route/season were shifting, it would
drift too. It doesn't — so a Jazz trend is skill, not scenery.

Two traffic-robust signals per trace (clamped to the gate-to-gate route):

  free-flow speed  = 85th-percentile of the smoothed moving speed. "When the road
                     opened up, how fast did you dare go" — a confidence proxy.
                     Read on the ONWARD (morning) leg, which flows; the evening
                     return is traffic-capped and carries little skill signal.
  assertiveness    = std of acceleration. A timid new driver feathers throttle and
                     brake (low); confidence and the Duke's sportier riding raise
                     it. Not "smoothness is better" — it reads caution vs commitment.

Writes plots/driving_style.svg.
"""

import glob
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import ingest_gpx as ig

DIR = os.path.dirname(os.path.abspath(__file__))
PLOTS = os.path.join(DIR, "plots")

COL = {"honda-jazz": "#d1495b",      # learner — warm
       "ktm-duke-390": "#2e4a62",    # veteran — deep blue
       "re-hunter-350": "#8a8d91",   # reference — grey
       "honda-brio": "#2a9d8f"}      # colleague — teal
LABEL = {"honda-jazz": "Honda Jazz (1st car, learning)",
         "ktm-duke-390": "KTM Duke 390 (10-yr veteran)",
         "re-hunter-350": "RE Hunter 350 (sedate ref.)",
         "honda-brio": "Honda Brio (colleague, lapsed-trained)"}


def trace_metrics(pts):
    n = len(pts)
    t = np.array([(p[0] - pts[0][0]).total_seconds() for p in pts])
    d = np.array([p[3] for p in pts])
    v = np.zeros(n)
    for i in range(1, n):
        dtt = t[i] - t[i - 1]
        v[i] = (d[i] - d[i - 1]) / dtt if dtt > 0 else v[i - 1]
    vs = np.convolve(v, np.ones(5) / 5, mode="same")      # ~5 s smoothing
    a = np.gradient(vs, t)
    a = a[np.isfinite(a)]
    mv = vs * 3.6 > 5
    if not mv.any():
        return None
    return {"p85": float(np.percentile(vs[mv] * 3.6, 85)),
            "accel_std": float(np.std(a))}


def collect():
    cfg = ig.load_cfg()
    tz = ig.parse_offset(cfg["timezone_offset"])
    st = cfg["stations"]
    R = cfg["station_radius_m"]
    rows = []
    for f in glob.glob(os.path.join(DIR, "gps", "office-route", "*.gpx")):
        bike = ig.bike_of(f)
        if bike == "unknown":
            continue
        raw = ig.read_points(f, tz)
        if len(raw) < 20:
            continue
        direction = ig.classify(raw[0][1], raw[0][2], cfg)[0]
        pts, tr = ig.clamp_to_stations(raw, *ig.stations_for(direction, st), R)
        # full gate-to-gate office traces only: fragments and partial pieces
        # aren't style samples (ends must be within 1 km of the gates)
        if len(pts) < 20 or max(tr["origin_gap"], tr["dest_gap"]) > 1000:
            continue
        m = trace_metrics(pts)
        if m:
            m.update(date=pts[0][0].date(), direction=direction, bike=bike)
            rows.append(m)
    return rows


def _days(rows, d0):
    return np.array([(r["date"] - d0).days for r in rows], dtype=float)


def main():
    rows = collect()
    d0 = min(r["date"] for r in rows)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9), sharex=True)

    # ---- panel 1: free-flow confidence on the onward (flowing) leg ----
    for bike in ("ktm-duke-390", "re-hunter-350", "honda-jazz", "honda-brio"):
        pts = [r for r in rows if r["bike"] == bike and r["direction"] == "onward"]
        if not pts:
            continue
        x, y = _days(pts, d0), np.array([r["p85"] for r in pts])
        ax1.scatter(x, y, s=60, color=COL[bike], label=LABEL[bike], zorder=3,
                    edgecolor="white", linewidth=0.6)
        if len(x) >= 3:
            m, b = np.polyfit(x, y, 1)
            xs = np.array([x.min(), x.max()])
            r2 = 1 - ((y - (m * x + b)) ** 2).sum() / (((y - y.mean()) ** 2).sum() + 1e-9)
            style = "-" if bike == "honda-jazz" else "--"
            ax1.plot(xs, m * xs + b, style, color=COL[bike], linewidth=2, zorder=2)
            if bike in ("honda-jazz", "ktm-duke-390"):
                ax1.annotate(f"{m*7:+.1f} km/h/wk (R²={r2:.2f})",
                             xy=(xs[-1], m * xs[-1] + b),
                             xytext=(6, 0), textcoords="offset points",
                             va="center", fontsize=9, color=COL[bike], fontweight="bold")
    ax1.set_ylabel("free-flow speed  (85th-pct, km/h)")
    ax1.set_title("Learning to drive: free-flow confidence on the morning leg\n"
                  "veteran bike is flat (mastered) — the car is climbing (still improving)",
                  fontsize=12)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper right", fontsize=9)
    ax1.margins(x=0.08)

    # ---- panel 2: assertiveness (accel std), all legs ----
    for bike in ("ktm-duke-390", "re-hunter-350", "honda-jazz", "honda-brio"):
        pts = [r for r in rows if r["bike"] == bike]
        if not pts:
            continue
        x, y = _days(pts, d0), np.array([r["accel_std"] for r in pts])
        ax2.scatter(x, y, s=45, color=COL[bike], alpha=0.8, zorder=3,
                    edgecolor="white", linewidth=0.5)
        if len(x) >= 3:
            m, b = np.polyfit(x, y, 1)
            xs = np.array([x.min(), x.max()])
            style = "-" if bike == "honda-jazz" else "--"
            ax2.plot(xs, m * xs + b, style, color=COL[bike], linewidth=2, zorder=2)
    ax2.set_ylabel("assertiveness  (accel std, m/s²)")
    ax2.set_xlabel(f"days since first recorded trace ({d0.isoformat()})")
    ax2.set_title("Throttle/brake commitment — timid (low) vs decisive (high)",
                  fontsize=12)
    ax2.grid(True, alpha=0.3)
    ax2.annotate("cautious new-driver zone: smooth but timid",
                 xy=(0.02, 0.06), xycoords="axes fraction", fontsize=9,
                 bbox=dict(boxstyle="round", fc="#fbeaec", ec="none"))

    fig.tight_layout()
    out = os.path.join(PLOTS, "driving_style.svg")
    os.makedirs(PLOTS, exist_ok=True)
    fig.savefig(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
