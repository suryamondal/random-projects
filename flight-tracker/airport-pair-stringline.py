#!/usr/bin/env python3
"""
Airport-pair string line diagram (path-validated).

For each airport pair (A, B):
- One PDF page
- X-axis: absolute time (shared across all plots)
- Y-axis: exactly two airports
- Red: A -> B
- Blue: B -> A

IMPORTANT:
Uses validated aircraft paths from helper_utils.
No teleporting aircraft allowed.
"""

import argparse
import sqlite3
import signal
import sys
from datetime import timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from helper_utils import (
    build_airline_paths,
    validate_and_segment_path,
)

DB_FILE = "database/flights.db"

abort_flag = False


# ------------------------------------------------------------
# Ctrl+C handling (safe PDF close)
# ------------------------------------------------------------
def handle_sigint(signum, frame):
    global abort_flag
    abort_flag = True
    print("\n[INFO] Ctrl+C detected — finishing current page safely...")


signal.signal(signal.SIGINT, handle_sigint)


# ------------------------------------------------------------
# Flatten validated segments into flight legs
# ------------------------------------------------------------
def collect_valid_legs(paths):
    """
    paths:
        {registration: [leg, leg, ...]}

    Returns:
        list of validated flight legs
    """
    valid_legs = []
    broken_aircraft = {}

    for reg, legs in paths.items():
        segments, breaks = validate_and_segment_path(legs)

        if breaks:
            broken_aircraft[reg] = breaks

        for seg in segments:
            valid_legs.extend(seg)

    return valid_legs, broken_aircraft


# ------------------------------------------------------------
# Group flights by airport pair
# ------------------------------------------------------------
def group_by_pairs(flights):
    pairs = {}
    for f in flights:
        key = tuple(sorted([f["from"], f["to"]]))
        pairs.setdefault(key, []).append(f)
    return pairs


# ------------------------------------------------------------
# Compute global time bounds
# ------------------------------------------------------------
def compute_time_bounds(flights):
    t_min = min(f["dep"] for f in flights)
    t_max = max(f["arr"] for f in flights)
    return t_min, t_max


# ------------------------------------------------------------
# Plot one airport-pair page
# ------------------------------------------------------------
def plot_pair(ax, pair, flights, t_min, t_max):
    a, b = pair
    y_pos = {a: 1, b: 0}

    ax.set_yticks([])
    ax.set_ylim(-0.5, 1.5)

    # airport labels
    ax.text(t_min - timedelta(hours=2), 1, a, va="center", fontsize=6)
    ax.text(t_min - timedelta(hours=2), 0, b, va="center", fontsize=6)

    for f in flights:
        y1 = y_pos[f["from"]]
        y2 = y_pos[f["to"]]

        color = "red" if (f["from"] == a and f["to"] == b) else "blue"

        ax.plot(
            [f["dep"], f["arr"]],
            [y1, y2],
            linewidth=0.3,
            color=color,
        )
        ax.scatter(
            [f["dep"], f["arr"]],
            [y1, y2],
            s=4,
            color=color,
        )

    ax.set_xlim(t_min, t_max)
    ax.set_title(f"{a} ⇄ {b}", fontsize=8)
    ax.set_xlabel("Time", fontsize=6)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--airline", required=True)
    p.add_argument("--output", default="airport-pairs.pdf")
    args = p.parse_args()

    print("[INFO] Loading and validating aircraft paths...")

    conn = sqlite3.connect(DB_FILE)
    airline_paths = build_airline_paths(conn, args.airline)
    conn.close()

    flights, broken = collect_valid_legs(airline_paths)

    if not flights:
        raise RuntimeError("No valid continuous flight paths found.")

    print(f"[INFO] Aircraft processed: {len(airline_paths)}")
    print(f"[INFO] Aircraft with breaks: {len(broken)}")
    print(f"[INFO] Valid flight legs used: {len(flights)}")

    pairs = group_by_pairs(flights)
    t_min, t_max = compute_time_bounds(flights)

    print(f"[INFO] Airport pairs: {len(pairs)}")
    print(f"[INFO] Time span: {t_min} → {t_max}")
    print(f"[INFO] Writing PDF: {args.output}")

    with PdfPages(args.output) as pdf:
        for idx, (pair, pair_flights) in enumerate(sorted(pairs.items()), start=1):

            print(
                f"[INFO] Page {idx}/{len(pairs)} — "
                f"{pair[0]}-{pair[1]} ({len(pair_flights)} flights)"
            )

            fig, ax = plt.subplots(figsize=(11, 3))
            plot_pair(ax, pair, pair_flights, t_min, t_max)
            pdf.savefig(fig)
            plt.close(fig)

            if abort_flag:
                break

    if abort_flag:
        print("[INFO] PDF closed safely (partial output preserved).")
    else:
        print("[INFO] PDF generation complete.")


if __name__ == "__main__":
    main()
