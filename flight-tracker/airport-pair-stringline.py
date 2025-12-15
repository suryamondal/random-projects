#!/usr/bin/env python3
"""
Airport-pair string line diagram (path-validated).

Enhancements:
1. Airport pairs sorted by total flights (descending)
2. 4 plots per page
3. Single-column layout (4x1)
4. Per-page status summary restored
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
# Plot one airport-pair subplot
# ------------------------------------------------------------
def plot_pair(ax, pair, flights, t_min, t_max):
    a, b = pair
    y_pos = {a: 1, b: 0}

    ax.set_yticks([])
    ax.set_ylim(-0.5, 1.5)

    # airport labels
    ax.text(t_min - timedelta(hours=1), 1, a, va="center", fontsize=6)
    ax.text(t_min - timedelta(hours=1), 0, b, va="center", fontsize=6)

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
    ax.set_title(f"{a} ⇄ {b} ({len(flights)})", fontsize=7)
    ax.tick_params(axis="x", labelsize=6)


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

    pairs = group_by_pairs(flights)

    # ---- Sort by total flights (descending) ----
    sorted_pairs = sorted(
        pairs.items(),
        key=lambda x: len(x[1]),
        reverse=True,
    )

    t_min, t_max = compute_time_bounds(flights)

    print(f"[INFO] Aircraft processed: {len(airline_paths)}")
    print(f"[INFO] Aircraft with breaks: {len(broken)}")
    print(f"[INFO] Airport pairs: {len(sorted_pairs)}")
    print(f"[INFO] Writing PDF: {args.output}")

    with PdfPages(args.output) as pdf:
        page_pairs = []
        page_no = 0

        for idx, (pair, pair_flights) in enumerate(sorted_pairs, start=1):
            page_pairs.append((pair, pair_flights))

            # ---- Emit page when full or last ----
            if len(page_pairs) == 4 or idx == len(sorted_pairs):
                page_no += 1

                # ---- Page summary print ----
                summary = ", ".join(
                    f"{p[0]}-{p[1]}({len(f)})" for p, f in page_pairs
                )
                print(f"[INFO] Page {page_no}: {summary}")

                fig, axes = plt.subplots(4, 1, figsize=(18, 12))
                axes = list(axes)

                for ax, (p, flts) in zip(axes, page_pairs):
                    plot_pair(ax, p, flts, t_min, t_max)

                # turn off unused axes (last page)
                for ax in axes[len(page_pairs):]:
                    ax.axis("off")

                pdf.savefig(fig)
                plt.close(fig)

                page_pairs = []

                if abort_flag:
                    break

    if abort_flag:
        print("[INFO] PDF closed safely (partial output preserved).")
    else:
        print("[INFO] PDF generation complete.")


if __name__ == "__main__":
    main()
