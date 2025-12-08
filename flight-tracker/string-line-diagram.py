#!/usr/bin/env python3
"""
String-line diagram generator for a single airline operator.
Improved with:
- Progress summaries
- Ctrl+C handling to avoid corrupting PDF
- Clear reporting of steps
"""

import argparse
import sqlite3
import signal
import sys
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from helper_utils import (
    extract_iata, clean_time_str, parse_date,
    parse_time, compute_arrival
)

DB_FILE = "database/flights.db"


# ------------------------------------------------------------
# Graceful Ctrl+C handling
# ------------------------------------------------------------
abort_flag = False

def handle_sigint(signum, frame):
    global abort_flag
    abort_flag = True
    print("\n[INFO] Ctrl+C detected — finishing current page and closing PDF safely...")


signal.signal(signal.SIGINT, handle_sigint)


# ------------------------------------------------------------
# Read DB flights grouped by day
# ------------------------------------------------------------
def load_flights(conn, airline):
    print("[INFO] Loading flights from database...")

    cur = conn.cursor()
    cur.execute("""
        SELECT a.registration, f.date, f.from_airport, f.to_airport,
               f.std, f.atd, f.sta, f.flight_time, f.status
        FROM flights f
        JOIN aircraft a ON a.registration = f.registration
        WHERE a.operator = ?
        ORDER BY f.date, f.std
    """, (airline,))

    rows = cur.fetchall()
    print(f"[INFO] Total DB rows fetched: {len(rows)}")

    flights_by_day = {}
    valid_count = 0

    for (reg, date, from_raw, to_raw, std, atd, sta, flight_time, status) in rows:

        if (status or "").strip().lower() == "unknown":
            continue

        day = parse_date(date)
        if not day:
            continue

        from_iata = extract_iata(from_raw)
        to_iata   = extract_iata(to_raw)
        if not from_iata or not to_iata:
            continue

        dep = parse_time(date, atd) or parse_time(date, std)
        arr = compute_arrival(date, std, sta, atd, flight_time)
        if not dep or not arr:
            continue

        valid_count += 1

        flights_by_day.setdefault(day, []).append({
            "reg": reg,
            "from": from_iata,
            "to": to_iata,
            "dep": dep,
            "arr": arr,
        })

    print(f"[INFO] Valid flights after filtering: {valid_count}")
    print(f"[INFO] Days with at least one flight: {len(flights_by_day)}")

    return flights_by_day


# ------------------------------------------------------------
# Plot a string-line diagram for a given day
# ------------------------------------------------------------
def plot_day(ax, day, flights, all_airports):
    airports = all_airports
    y_pos = {ap: i for i, ap in enumerate(airports)}

    ax.set_yticks([])

    # dotted horizontal lines
    for ap in airports:
        ax.hlines(
            y_pos[ap], 0, 24*60,
            linestyles="dotted",
            linewidth=0.3,
            alpha=0.4
        )
        ax.text(
            -25,
            y_pos[ap],
            ap,
            va="center",
            fontsize=3,
        )

    # plot flights
    for f in flights:
        y1 = y_pos[f["from"]]
        y2 = y_pos[f["to"]]
        t1 = f["dep"].hour*60 + f["dep"].minute
        t2 = f["arr"].hour*60 + f["arr"].minute

        ax.plot([t1, t2], [y1, y2], linewidth=0.1)
        ax.scatter([t1, t2], [y1, y2], s=1, marker='o')

    ax.set_ylim(-1, len(airports))
    ax.set_xlim(0, 24*60)
    ax.set_xticks(range(0, 24*60 + 1, 60))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(25)], fontsize=5)

    ax.set_title(f"String Line Diagram — {day}", fontsize=8)
    ax.set_ylabel("")
    ax.set_xlabel("Time of day", fontsize=6)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--airline", required=True)
    p.add_argument("--output", default="stringline.pdf")
    args = p.parse_args()

    print("[INFO] Starting string-line diagram generation...")

    conn = sqlite3.connect(DB_FILE)
    flights_by_day = load_flights(conn, args.airline)
    # ---- Build a global airport list shared across all days ----
    all_airports = sorted({
        ap
        for flights in flights_by_day.values()
        for f in flights
        for ap in (f["from"], f["to"])
    })
    print(f"[INFO] Total unique airports across all days: {len(all_airports)}")
    conn.close()

    print(f"[INFO] Writing PDF: {args.output}")

    with PdfPages(args.output) as pdf:

        total_days = len(flights_by_day)
        for idx, (day, flights) in enumerate(sorted(flights_by_day.items()), start=1):

            print(f"[INFO] Page {idx}/{total_days} — {day} — {len(flights)} flights")

            fig, ax = plt.subplots(figsize=(11, 8))

            plot_day(ax, day, flights, all_airports)

            pdf.savefig(fig)
            plt.close(fig)

            if abort_flag:
                break

    if abort_flag:
        print("[INFO] PDF closed safely. Partial output preserved.")
    else:
        print(f"[INFO] PDF generation complete: {args.output}")


if __name__ == "__main__":
    main()
