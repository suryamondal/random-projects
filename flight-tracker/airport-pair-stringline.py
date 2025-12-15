#!/usr/bin/env python3
"""
Airport-pair string line diagram.

For each airport pair (A, B):
- One PDF page
- X-axis: absolute time (shared across all plots)
- Y-axis: two airports only
- Red: A -> B
- Blue: B -> A
"""

import argparse
import sqlite3
import signal
import sys
from datetime import timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from helper_utils import (
    extract_iata,
    parse_date,
    parse_time,
    compute_arrival,
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
# Load and validate flights
# ------------------------------------------------------------
def load_flights(conn, airline):
    cur = conn.cursor()
    cur.execute("""
        SELECT f.date, f.from_airport, f.to_airport,
               f.std, f.atd, f.sta, f.flight_time, f.status
        FROM flights f
        JOIN aircraft a ON a.registration = f.registration
        WHERE a.operator = ?
        ORDER BY f.date, f.std
    """, (airline,))

    rows = cur.fetchall()
    flights = []

    for (date, from_raw, to_raw, std, atd, sta, flight_time, status) in rows:

        if (status or "").strip().lower() == "unknown":
            continue

        from_iata = extract_iata(from_raw)
        to_iata   = extract_iata(to_raw)
        if not from_iata or not to_iata:
            continue

        dep = parse_time(date, atd) or parse_time(date, std)
        arr = compute_arrival(date, std, sta, atd, flight_time, status)
        if not dep or not arr:
            continue

        flights.append({
            "from": from_iata,
            "to": to_iata,
            "dep": dep,
            "arr": arr,
        })

    return flights


# ------------------------------------------------------------
# Group flights by airport-pair
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

        ax.plot([f["dep"], f["arr"]], [y1, y2],
                linewidth=0.3, color=color)
        ax.scatter([f["dep"], f["arr"]], [y1, y2],
                   s=4, color=color)

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

    conn = sqlite3.connect(DB_FILE)
    flights = load_flights(conn, args.airline)
    conn.close()

    if not flights:
        raise RuntimeError("No valid landed flights found.")

    pairs = group_by_pairs(flights)
    t_min, t_max = compute_time_bounds(flights)

    print(f"[INFO] Valid flights: {len(flights)}")
    print(f"[INFO] Airport pairs: {len(pairs)}")
    print(f"[INFO] Time span: {t_min} → {t_max}")
    print(f"[INFO] Writing PDF: {args.output}")

    with PdfPages(args.output) as pdf:
        for idx, (pair, pair_flights) in enumerate(sorted(pairs.items()), start=1):

            print(f"[INFO] Page {idx}/{len(pairs)} — {pair[0]}-{pair[1]} "
                  f"({len(pair_flights)} flights)")

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
