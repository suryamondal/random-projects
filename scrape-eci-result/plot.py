#!/usr/bin/env python3
"""Plot TMC vs BJP seats and vote% from results.csv."""

import csv
import os
from datetime import datetime

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(DIR, "results.csv")
OUT_PATH = os.path.join(DIR, "results.png")

TODAY = datetime(2026, 5, 4)
TMC_COLOR = "#1f77b4"
BJP_COLOR = "#ff7f0e"


def load():
    rows = []
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            t = datetime.combine(TODAY.date(), datetime.strptime(r["time"], "%H:%M").time())
            def i(k):
                v = r.get(k, "")
                return int(v) if v else None
            rows.append({
                "time": t,
                "tmc_won": i("tmc_won"),
                "tmc_lead": i("tmc_lead"),
                "bjp_won": i("bjp_won"),
                "bjp_lead": i("bjp_lead"),
                "tmc_vp": float(r["tmc_vote_pct"]) if r["tmc_vote_pct"] else None,
                "bjp_vp": float(r["bjp_vote_pct"]) if r["bjp_vote_pct"] else None,
            })
    return rows


def main():
    rows = load()
    times = [r["time"] for r in rows]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    def total(r, p):
        w, l = r[f"{p}_won"], r[f"{p}_lead"]
        return w + l if w is not None and l is not None else None

    tmc_total = [total(r, "tmc") for r in rows]
    bjp_total = [total(r, "bjp") for r in rows]
    tmc_won = [r["tmc_won"] for r in rows]
    bjp_won = [r["bjp_won"] for r in rows]

    ax1.plot(times, tmc_total, "o-", color=TMC_COLOR, label="TMC total (won + leading)")
    ax1.plot(times, bjp_total, "o-", color=BJP_COLOR, label="BJP total (won + leading)")
    ax1.plot(times, tmc_won, "--", color=TMC_COLOR, alpha=0.7, label="TMC declared (won)")
    ax1.plot(times, bjp_won, "--", color=BJP_COLOR, alpha=0.7, label="BJP declared (won)")
    ax1.set_ylabel("Seats")
    ax1.set_title("West Bengal 2026 — Seats over time")
    ax1.legend(loc="center right")
    ax1.grid(True, alpha=0.3)

    vp_times = [r["time"] for r in rows if r["tmc_vp"] is not None]
    ax2.plot(vp_times, [r["tmc_vp"] for r in rows if r["tmc_vp"] is not None],
             "o-", color=TMC_COLOR, label="TMC vote %")
    ax2.plot(vp_times, [r["bjp_vp"] for r in rows if r["bjp_vp"] is not None],
             "o-", color=BJP_COLOR, label="BJP vote %")
    ax2.set_ylabel("Vote share (%)")
    ax2.set_xlabel("Time (04 May 2026)")
    ax2.set_title("Vote share over time")
    ax2.legend(loc="center right")
    ax2.grid(True, alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax2.xaxis.set_major_locator(mdates.MinuteLocator(interval=15))
    fig.autofmt_xdate()

    fig.tight_layout()
    fig.savefig(OUT_PATH, dpi=120)
    print("wrote", OUT_PATH)


if __name__ == "__main__":
    main()
