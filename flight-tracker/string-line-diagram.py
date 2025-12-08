#!/usr/bin/env python3
"""
String-line diagram generator for a single airline operator.
One PDF page per day.

Reuses the same DB-reading and time/IATA parsing logic as the visualization script.
"""

import argparse
import sqlite3
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# ============================================================
#  IMPORT / COPY THESE FROM YOUR ORIGINAL SCRIPT  (VERBATIM)
#  extract_iata
#  clean_time_str
#  parse_date
#  parse_time
#  compute_arrival
# ============================================================

from helper_utils import (
    extract_iata, clean_time_str, parse_date,
    parse_time, compute_arrival
)
# If you do not want a separate file, paste directly instead.


DB_FILE = "database/flights.db"


# ------------------------------------------------------------
# Read DB flights grouped by day
# ------------------------------------------------------------
def load_flights(conn, airline):
    cur = conn.cursor()
    cur.execute("""
        SELECT a.registration, f.date, f.from_airport, f.to_airport,
               f.std, f.atd, f.sta, f.flight_time, f.status
        FROM flights f
        JOIN aircraft a ON a.registration = f.registration
        WHERE a.operator = ?
        ORDER BY f.date, f.std
    """, (airline,))

    flights_by_day = {}

    for (reg, date, from_raw, to_raw, std, atd, sta, flight_time, status) in cur.fetchall():

        if (status or "").strip().lower() == "unknown":
            continue  # identical logic to your script

        day = parse_date(date)
        if not day:
            continue

        from_iata = extract_iata(from_raw)
        to_iata   = extract_iata(to_raw)

        if not from_iata or not to_iata:
            continue

        dep = parse_time(date, atd) or parse_time(date, std)
        arr = compute_arrival(date, std, sta, atd, flight_time)

        # Only flights that actually "exist"
        if not dep or not arr:
            continue

        flights_by_day.setdefault(day, []).append({
            "reg": reg,
            "from": from_iata,
            "to": to_iata,
            "dep": dep,
            "arr": arr,
        })

    return flights_by_day


# ------------------------------------------------------------
# Plot a string-line diagram for a given day
# ------------------------------------------------------------
def plot_day(ax, day, flights):
    # ---- Collect all airports touched ----
    airports = sorted({f["from"] for f in flights} | {f["to"] for f in flights})

    y_pos = {ap: i for i, ap in enumerate(airports)}

    # ---- Draw dotted horizontal lines ----
    for ap in airports:
        ax.hlines(y_pos[ap], 0, 24*60, linestyles="dotted", linewidth=0.8, alpha=0.4)
        ax.text(-40, y_pos[ap], ap, va="center", fontsize=9)

    # ---- Plot each flight ----
    for f in flights:
        y1 = y_pos[f["from"]]
        y2 = y_pos[f["to"]]

        t1 = f["dep"].hour*60 + f["dep"].minute
        t2 = f["arr"].hour*60 + f["arr"].minute

        ax.plot([t1, t2], [y1, y2], linewidth=1.2)
        ax.scatter([t1, t2], [y1, y2], s=16)

    ax.set_ylim(-1, len(airports))
    ax.set_xlim(0, 24*60)
    ax.set_xticks(range(0, 24*60 + 1, 60))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(25)])
    ax.set_title(f"String Line Diagram — {day}")
    ax.set_ylabel("Airports")
    ax.set_xlabel("Time of day")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--airline", required=True)
    p.add_argument("--output", default="stringline.pdf")
    args = p.parse_args()

    conn = sqlite3.connect(DB_FILE)
    flights_by_day = load_flights(conn, args.airline)
    conn.close()

    with PdfPages(args.output) as pdf:
        for day, flights in sorted(flights_by_day.items()):
            fig, ax = plt.subplots(figsize=(11, 8))  # landscape fits time better
            plot_day(ax, day, flights)
            pdf.savefig(fig)
            plt.close(fig)

    print(f"[INFO] String-line PDF written to {args.output}")


if __name__ == "__main__":
    main()
