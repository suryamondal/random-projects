#!/usr/bin/env python3
"""
Debugging + final visualization script.
- Robust iata & time parsing
- Detailed debug prints (counts & samples) to diagnose why presence/last_loc may be empty
- Option B: track aircraft through foreign airports but plot only Indian coords
"""

import signal
import sys
import argparse
import sqlite3
import re
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import geopandas as gpd
# FAST India outline (hard-coded bounding box polygon)
import shapely.geometry as geom
from airport_coords import AIRPORT_COORDS

india_poly = geom.Polygon([
    (68, 6), (98, 6), (98, 38), (68, 38)
])
india_map = gpd.GeoDataFrame({'geometry':[india_poly]}, crs="EPSG:4326")


DB_FILE = "database/flights.db"

INDIAN_IATA = set(AIRPORT_COORDS.keys())

# -------------------------
# Graceful Ctrl+C handling
# -------------------------
def handle_sigint(signum, frame):
    print("\n[INFO] Caught Ctrl+C — exiting cleanly.")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_sigint)


# -------------------------
# Robust IATA extraction
# -------------------------
def extract_iata(raw):
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)

    # normalize common unicode parentheses and whitespace characters
    raw_norm = raw.replace("（", "(").replace("）", ")") \
                  .replace("﹙", "(").replace("﹚", ")") \
                  .replace("\u00A0", " ")  # NBSP
    raw_norm = raw_norm.strip()

    # find all occurrences like "(ABC)" case-insensitive
    matches = re.findall(r"\(([A-Za-z0-9]{3})\)", raw_norm)
    if matches:
        return matches[-1].upper()

    # fallback: find last 3 alnum chars (useful for "CITY ABC" or "CITY (ABC" broken)
    s = re.sub(r"[^A-Za-z0-9]", "", raw_norm)  # remove punctuation
    if len(s) >= 3:
        cand = s[-3:]
        if cand.isalnum():
            return cand.upper()

    return None

# -------------------------
# Robust time parser
# -------------------------
def clean_time_str(t):
    if t is None:
        return None
    if not isinstance(t, str):
        t = str(t)
    # normalize NBSP and non-printables, strip
    t = t.replace("\u00A0", " ").replace("\u200B", "").strip()
    # sometimes values like '05:57 ' or '\n05:57' exist
    if t == "" or t.lower() == "null":
        return None
    return t

def parse_date(date_str):
    # Try ISO format first
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        pass

    # Try "DD Mon YYYY"
    try:
        return datetime.strptime(date_str, "%d %b %Y").date()
    except:
        return None

def parse_time(date, t):
    t = clean_time_str(t)
    if not t:
        return None

    d = parse_date(date)
    if not d:
        return None

    try:
        hh, mm = map(int, t.split(":"))
        return datetime(d.year, d.month, d.day, hh, mm)
    except:
        return None

# -------------------------
# Arrival logic (Option A)
# -------------------------
def compute_arrival(date, std, sta, atd, flight_time):
    # Try ATD + flight_time first
    atd_c = clean_time_str(atd)
    ft_c = clean_time_str(flight_time)
    if atd_c and ft_c:
        dep = parse_time(date, atd_c)
        if dep:
            try:
                hh, mm = map(int, ft_c.split(":"))
                return dep + timedelta(hours=hh, minutes=mm)
            except Exception:
                pass

    # Fallback to STA with rollover
    arr = parse_time(date, sta)
    dep_std = parse_time(date, std)
    if arr and dep_std:
        if arr.time() < dep_std.time():
            arr = arr + timedelta(days=1)
        return arr
    return None

# -------------------------
# Read DB + build presence & last_loc with debug logging
# -------------------------
def compute_presence_windows(conn, airline, debug_samples=20):
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
    total_rows = len(rows)

    presence = []
    last_loc = {}

    # debug counters
    skipped_unknown = 0
    skipped_no_airport = 0
    skipped_no_time = 0
    added_presence = 0
    added_lastloc = 0

    skip_examples = []

    for idx, (reg, date, from_raw, to_raw, std, atd, sta, flight_time, status) in enumerate(rows):
        reason = None

        # normalize status
        status_s = (status or "").strip().lower()
        if status_s == "unknown":
            skipped_unknown += 1
            reason = "unknown-status"
            if len(skip_examples) < debug_samples:
                skip_examples.append((reg, date, from_raw, to_raw, std, atd, sta, flight_time, status, reason))
            continue

        # extract iata
        from_iata = extract_iata(from_raw)
        to_iata = extract_iata(to_raw)

        # compute times
        dep = parse_time(date, atd) or parse_time(date, std)
        arr = compute_arrival(date, std, sta, atd, flight_time)

        # If neither airport present, skip for presence/lastloc but record reason
        if (from_iata is None) and (to_iata is None):
            skipped_no_airport += 1
            reason = "no-airport"
            if len(skip_examples) < debug_samples:
                skip_examples.append((reg, date, from_raw, to_raw, std, atd, sta, flight_time, status, reason))
            continue

        # If no times can be parsed, skip but keep examples
        if dep is None and arr is None:
            skipped_no_time += 1
            reason = "no-times"
            if len(skip_examples) < debug_samples:
                skip_examples.append((reg, date, from_raw, to_raw, std, atd, sta, flight_time, status, reason))
            continue

        # add presence window for origin if dep exists and origin IATA extracted
        if dep and from_iata:
            presence.append((dep - timedelta(minutes=30), dep, from_iata))
            added_presence += 1

        # record destination as last known location if arr exists and to_iata exists
        if arr and to_iata:
            last_loc[reg] = (arr, to_iata)
            added_lastloc += 1

    # debug summary
    debug = {
        "total_rows": total_rows,
        "skipped_unknown": skipped_unknown,
        "skipped_no_airport": skipped_no_airport,
        "skipped_no_time": skipped_no_time,
        "presence_count": len(presence),
        "lastloc_count": len(last_loc),
        "added_presence": added_presence,
        "added_lastloc": added_lastloc,
        "skip_examples": skip_examples[:debug_samples],
        "rows_sample": rows[:debug_samples],
    }

    return presence, last_loc, debug

# -------------------------
# timeline builder, counter, plotting (same ideas as before)
# -------------------------
def build_time_range(presence, last_loc, interval_min):
    all_times = []
    for s, e, _ in presence:
        all_times.append(s)
        all_times.append(e)
    for arr, _ in last_loc.values():
        all_times.append(arr)

    if not all_times:
        raise RuntimeError("No timestamp data after filtering (presence and last_loc empty).")

    t_min = min(all_times)
    t_max = max(all_times) + timedelta(hours=6)

    times = []
    t = t_min
    step = timedelta(minutes=interval_min)
    while t <= t_max:
        times.append(t)
        t += step
    return times

def count_aircraft_at_time(t, presence, last_loc):
    counts = {}
    for s, e, ap in presence:
        if s <= t <= e:
            counts[ap] = counts.get(ap, 0) + 1
    for arr, ap in last_loc.values():
        if t >= arr:
            counts[ap] = counts.get(ap, 0) + 1
    return counts

def plot_frame(ax, india_map, t, counts):
    india_map.plot(ax=ax, color="white", edgecolor="black")
    ax.set_title(f"Aircraft at Indian Airports — {t.strftime('%Y-%m-%d %H:%M')}", fontsize=14)

    # plot only airports with coords
    for ap, (lat, lon) in AIRPORT_COORDS.items():
        cnt = counts.get(ap, 0)
        if cnt > 0:
            ax.scatter(lon, lat, s=40 + 20*cnt)
            ax.text(lon, lat, f"{ap}\n{cnt}", fontsize=8, ha='center', va='bottom')
        else:
            ax.scatter(lon, lat, s=8, alpha=0.2)

    ax.set_xlim(68, 98)
    ax.set_ylim(6, 38)

# -------------------------
# Main
# -------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--airline", required=True)
    p.add_argument("--interval", type=int, default=30)
    p.add_argument("--output", default="output.pdf")
    args = p.parse_args()

    conn = sqlite3.connect(DB_FILE)
    presence, last_loc, debug = compute_presence_windows(conn, args.airline)
    conn.close()

    # Print full debug summary — paste this if it still fails
    print("=== DEBUG SUMMARY ===")
    print(f"Total rows read for operator '{args.airline}': {debug['total_rows']}")
    print(f"Skipped (status=='unknown'): {debug['skipped_unknown']}")
    print(f"Skipped (no airport extracted both ends): {debug['skipped_no_airport']}")
    print(f"Skipped (no parsable times both ends): {debug['skipped_no_time']}")
    print(f"Presence windows created: {debug['presence_count']} (added_presence={debug['added_presence']})")
    print(f"Last-known locations recorded: {debug['lastloc_count']} (added_lastloc={debug['added_lastloc']})")
    print("\nSample rows (first 10):")
    for r in debug["rows_sample"][:10]:
        print(r)
    print("\nSample skipped examples and reasons (up to 20):")
    for ex in debug["skip_examples"]:
        print(ex)
    print("======================\n")

    # If nothing to plot, stop with informative message
    if debug["presence_count"] == 0 and debug["lastloc_count"] == 0:
        raise RuntimeError("No usable presence or last-locations found — see debug summary above.")

    times = build_time_range(presence, last_loc, args.interval)

    # india_map = gpd.read_file(gpd.datasets.get_path("naturalearth_lowres"))
    # india_map = india_map[india_map["name"] == "India"]

    with PdfPages(args.output) as pdf:

        total = len(times)
        bar_width = 30  # characters

        for i, t in enumerate(times, start=1):
            try:
                # ----- Build progress bar -----
                filled = int(bar_width * i / total)
                bar = "#" * filled + "-" * (bar_width - filled)
                percent = (i / total) * 100

                sys.stdout.write(
                    f"\r[{bar}] {percent:5.1f}%  ({t.strftime('%Y-%m-%d %H:%M')})"
                )
                sys.stdout.flush()

                # ----- Generate frame -----
                fig, ax = plt.subplots(figsize=(8, 10))
                counts = count_aircraft_at_time(t, presence, last_loc)
                plot_frame(ax, india_map, t, counts)
                pdf.savefig(fig)
                plt.close(fig)

            except KeyboardInterrupt:
                print("\n[INFO] Stopping early — PDF written so far is valid.")
                break

        print("\n[INFO] PDF generation complete.")

if __name__ == "__main__":
    main()
