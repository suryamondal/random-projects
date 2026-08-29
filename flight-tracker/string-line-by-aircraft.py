#!/usr/bin/env python3
"""
String-line diagram: full data range, one aircraft per PDF page.

- Reuses helper_utils for all time/IATA parsing.
- Uses global airport list across all aircraft (same Y-axis everywhere).
- Skips flights with missing flight_time.
- Prints progress for each aircraft.
- Handles Ctrl+C so PDF is always left uncorrupted.
"""

import argparse
import sqlite3
import sys
import signal
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from helper_utils import (
    extract_iata, clean_time_str, parse_date,
    parse_time, compute_arrival
)

DB_FILE = "database/flights.db"

abort_flag = False

# ------------------------------------------------------------
# Graceful Ctrl+C
# ------------------------------------------------------------
def handle_sigint(signum, frame):
    global abort_flag
    abort_flag = True
    print("\n[INFO] Ctrl+C detected — finishing current page safely...")

signal.signal(signal.SIGINT, handle_sigint)


# ------------------------------------------------------------
# Load all flights for an airline, grouped by registration
# ------------------------------------------------------------
def load_flights_by_aircraft(conn, airline):
    print("[INFO] Loading flights from database...")

    cur = conn.cursor()
    cur.execute("""
        SELECT a.registration, f.date, f.flight,
               f.from_airport, f.to_airport,
               f.std, f.atd, f.sta, f.flight_time, f.status
        FROM flights f
        JOIN aircraft a ON a.registration = f.registration
        WHERE a.operator = ?
        ORDER BY a.registration, f.date, f.std
    """, (airline,))

    rows = cur.fetchall()
    print(f"[INFO] Total DB rows fetched: {len(rows)}")

    by_reg = {}
    valid_count = 0

    for (reg, date, flight, from_raw, to_raw,
         std, atd, sta, flight_time, status) in rows:

        if (status or "").strip().lower() == "unknown":
            continue

        # rule: skip flights without flight_time
        if not clean_time_str(flight_time):
            continue

        day = parse_date(date)
        if not day:
            continue

        from_iata = extract_iata(from_raw)
        to_iata   = extract_iata(to_raw)
        if not from_iata or not to_iata:
            continue

        dep = parse_time(date, atd) or parse_time(date, std)
        arr = compute_arrival(date, std, sta, atd, flight_time, status)
        if not dep or not arr:
            continue

        valid_count += 1

        by_reg.setdefault(reg, []).append({
            "date": day,
            "flight": flight,
            "from": from_iata,
            "to": to_iata,
            "dep": dep,
            "arr": arr,
        })

    print(f"[INFO] Valid flights retained: {valid_count}")
    print(f"[INFO] Aircraft with at least one valid flight: {len(by_reg)}")

    return by_reg


# ------------------------------------------------------------
# Build global airport list across ALL aircraft
# ------------------------------------------------------------
def build_global_airport_list(by_reg):
    airports = sorted({
        ap
        for flights in by_reg.values()
        for f in flights
        for ap in (f["from"], f["to"])
    })
    print(f"[INFO] Total unique airports across all aircraft: {len(airports)}")
    return airports


# ------------------------------------------------------------
# Build full timeline X-axis range (min to max date/time)
# ------------------------------------------------------------
def find_time_range(by_reg):
    all_times = []

    for flights in by_reg.values():
        for f in flights:
            all_times.append(f["dep"])
            all_times.append(f["arr"])

    if not all_times:
        raise RuntimeError("No time data available.")

    t_min = min(all_times)
    t_max = max(all_times)

    return t_min, t_max


# ------------------------------------------------------------
# Plot single aircraft's full timeline
# ------------------------------------------------------------
def plot_aircraft(ax, reg, flights, all_airports, t_min, t_max):
    # sort flights chronologically
    flights = sorted(flights, key=lambda f: f["dep"])

    # Y-axis map
    y_pos = {ap: i for i, ap in enumerate(all_airports)}
    ax.set_yticks([])

    # Draw dotted horizontal airport lines
    for ap in all_airports:
        ax.hlines(
            y_pos[ap], t_min, t_max,
            linestyles="dotted",
            linewidth=0.3,
            alpha=0.4
        )
        ax.text(
            t_min - timedelta(hours=4),
            y_pos[ap],
            ap,
            va="center",
            fontsize=3,
        )

    # Draw flights
    for f in flights:
        y1 = y_pos[f["from"]]
        y2 = y_pos[f["to"]]

        ax.plot(
            [f["dep"], f["arr"]],
            [y1, y2],
            linewidth=0.1,
            color="black"
        )
        ax.scatter(
            [f["dep"], f["arr"]],
            [y1, y2],
            s=1,
            marker='o',
            color="black"
        )

    ax.set_ylim(-1, len(all_airports))
    ax.set_xlim(t_min, t_max)
    ax.set_title(f"Aircraft: {reg}", fontsize=10)
    ax.tick_params(axis="x", labelsize=6)
    ax.set_xlabel("Date/Time", fontsize=6)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--airline", required=True)
    p.add_argument("--output", default="aircraft_stringlines.pdf")
    args = p.parse_args()

    print("[INFO] Starting full-range aircraft timeline generation...")

    conn = sqlite3.connect(DB_FILE)
    by_reg = load_flights_by_aircraft(conn, args.airline)
    all_airports = build_global_airport_list(by_reg)
    t_min, t_max = find_time_range(by_reg)
    conn.close()

    print(f"[INFO] Writing PDF: {args.output}")

    with PdfPages(args.output) as pdf:
        total_ac = len(by_reg)

        for idx, (reg, flights) in enumerate(sorted(by_reg.items()), start=1):
            print(f"[INFO] Page {idx}/{total_ac} — Aircraft {reg} — {len(flights)} flights")

            fig, ax = plt.subplots(figsize=(14, 8))
            plot_aircraft(ax, reg, flights, all_airports, t_min, t_max)

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
