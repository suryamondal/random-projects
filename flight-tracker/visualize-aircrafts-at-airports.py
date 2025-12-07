#!/usr/bin/env python3
import argparse
import sqlite3
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import geopandas as gpd

# -----------------------------
# Airport coordinates (extend as needed)
# -----------------------------
AIRPORTS = {
    "DEL": (28.5562, 77.1000),
    "BOM": (19.0896, 72.8656),
    "BLR": (13.1986, 77.7066),
    "MAA": (12.9941, 80.1709),
    "HYD": (17.24, 78.43),
    "CCU": (22.6547, 88.4467),
}

DB_FILE = "database/flights.db"


# ---------------------------------------
# Parse time for "YYYY-MM-DD HH:MM"
# ---------------------------------------
def parse_time(date, t):
    if not t or t.strip() == "":
        return None
    try:
        return datetime.strptime(date + " " + t, "%Y-%m-%d %H:%M")
    except:
        return None


# -----------------------------------------------------
# Option A: Determine arrival using ATD + flight_time
# Fallback to STA + day rollover
# -----------------------------------------------------
def compute_arrival(date, std, sta, atd, flight_time):
    # 1) Try using ATD + flight_time
    if atd and flight_time:
        dep = parse_time(date, atd)
        if dep:
            try:
                h, m = map(int, flight_time.split(":"))
                arr = dep + timedelta(hours=h, minutes=m)
                return arr
            except:
                pass

    # 2) STA fallback with rollover
    arr = parse_time(date, sta)
    dep_std = parse_time(date, std)

    if arr and dep_std:
        # If STA < STD, it's next day
        if arr.time() < dep_std.time():
            arr += timedelta(days=1)
        return arr

    return None


# -----------------------------------------------------
# Build presence windows for aircraft at airports
# -----------------------------------------------------
def compute_presence_windows(conn, airline):
    cur = conn.cursor()

    cur.execute("""
        SELECT a.registration, f.date, f.from_airport, f.to_airport,
               f.std, f.atd, f.sta, f.flight_time, f.status
        FROM flights f
        JOIN aircraft a ON a.registration = f.registration
        WHERE a.operator = ?
        ORDER BY a.registration, f.date, f.std
    """, (airline,))

    rows = cur.fetchall()

    presence = []      # (start_time, end_time, airport)
    last_loc = {}      # reg -> (arrival_time, airport)

    for reg, date, from_ap, to_ap, std, atd, sta, flight_time, status in rows:

        # Skip flights with unknown status
        if status and status.lower() == "unknown":
            continue

        # Departure time (ATD preferred)
        dep = parse_time(date, atd) or parse_time(date, std)

        arr = compute_arrival(date, std, sta, atd, flight_time)

        # If both times exist, create "presence at origin airport before dep"
        if dep and from_ap:
            presence.append((
                dep - timedelta(minutes=30),  # assume 30 min ground before ATD
                dep,
                from_ap
            ))

        # After arrival → presence at destination until next departure
        if arr and to_ap:
            last_loc[reg] = (arr, to_ap)

    return presence, last_loc


# -----------------------------------------------------
# Build timeline for frames
# -----------------------------------------------------
def build_time_range(presence, last_loc, interval_min):
    all_times = [t for win in presence for t in win[:2]]

    # Add last known arrival times
    for t, _ap in last_loc.values():
        all_times.append(t)

    if not all_times:
        raise RuntimeError("No timestamp data available after filtering.")

    t_min = min(all_times)
    t_max = max(all_times)

    # Extend plot window slightly
    t_max += timedelta(hours=6)

    times = []
    step = timedelta(minutes=interval_min)
    t = t_min
    while t <= t_max:
        times.append(t)
        t += step

    return times


# -----------------------------------------------------
# Count aircraft at a timestamp
# -----------------------------------------------------
def count_aircraft_at_time(t, presence, last_loc):
    counts = {}

    # From presence windows
    for start, end, ap in presence:
        if start <= t <= end:
            counts[ap] = counts.get(ap, 0) + 1

    # From last known location (aircraft stays after arrival)
    for arr, ap in last_loc.values():
        if t >= arr:
            counts[ap] = counts.get(ap, 0) + 1

    return counts


# -----------------------------------------------------
# Plot one page
# -----------------------------------------------------
def plot_frame(ax, india_map, t, counts):
    india_map.plot(ax=ax, color="white", edgecolor="black")

    ax.set_title(f"Aircraft at airports — {t}", fontsize=14)

    for ap, count in counts.items():
        if ap not in AIRPORTS:
            continue
        lat, lon = AIRPORTS[ap]
        ax.scatter(lon, lat, s=40 + 20 * count)
        ax.text(lon, lat, f"{ap}\n{count}", fontsize=8)

    ax.set_xlim(68, 98)
    ax.set_ylim(6, 38)


# -----------------------------------------------------
# MAIN
# -----------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--airline", required=True)
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--output", default="airline_map.pdf")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_FILE)

    presence, last_loc = compute_presence_windows(conn, args.airline)
    conn.close()

    times = build_time_range(presence, last_loc, args.interval)

    india_map = gpd.read_file(gpd.datasets.get_path("naturalearth_lowres"))
    india_map = india_map[india_map["name"] == "India"]

    with PdfPages(args.output) as pdf:
        for t in times:
            fig, ax = plt.subplots(figsize=(8, 10))
            counts = count_aircraft_at_time(t, presence, last_loc)
            plot_frame(ax, india_map, t, counts)
            pdf.savefig(fig)
            plt.close(fig)

    print(f"[DONE] Saved {args.output}")


if __name__ == "__main__":
    main()
