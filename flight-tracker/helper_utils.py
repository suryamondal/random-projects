"""
Original parsing utilities extracted from visualize-aircrafts-at-airports.py

Includes:
- extract_iata
- clean_time_str
- parse_date
- parse_time
- compute_arrival

This module is imported by string-line diagram generator and
kept separate so both scripts share *identical* parsing logic.
"""

import re
from datetime import datetime, timedelta


# ---------------------------------------------------------
# Robust IATA extraction
# ---------------------------------------------------------
def extract_iata(raw):
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)

    # Normalize unicode parentheses and whitespace
    raw_norm = raw.replace("（", "(").replace("）", ")") \
                  .replace("﹙", "(").replace("﹚", ")") \
                  .replace("\u00A0", " ")  # NBSP
    raw_norm = raw_norm.strip()

    # Find all occurrences like "(ABC)"
    matches = re.findall(r"\(([A-Za-z0-9]{3})\)", raw_norm)
    if matches:
        return matches[-1].upper()

    # Fallback: take last 3 alnum chars
    s = re.sub(r"[^A-Za-z0-9]", "", raw_norm)
    if len(s) >= 3:
        cand = s[-3:]
        if cand.isalnum():
            return cand.upper()

    return None


# ---------------------------------------------------------
# Clean time string
# ---------------------------------------------------------
def clean_time_str(t):
    if t is None:
        return None
    if not isinstance(t, str):
        t = str(t)

    # Normalize NBSP and hidden chars
    t = t.replace("\u00A0", " ").replace("\u200B", "").strip()

    if t == "" or t.lower() == "null":
        return None

    return t


# ---------------------------------------------------------
# Parse date with two formats
# ---------------------------------------------------------
def parse_date(date_str):
    # Try ISO
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except:
        pass

    # Try "DD Mon YYYY"
    try:
        return datetime.strptime(date_str, "%d %b %Y").date()
    except:
        return None


# ---------------------------------------------------------
# Parse time using parsed date
# ---------------------------------------------------------
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


# ---------------------------------------------------------
# Compute arrival time with rollover
# ---------------------------------------------------------
def compute_arrival(date, std, sta, atd, flight_time, status):
    """
    Compute actual arrival ONLY if flight has a valid 'Landed HH:MM' status.
    Otherwise return None.
    """

    # ---------------------------------------------------------
    # Extract landing time from status
    # ---------------------------------------------------------
    def extract_landing_time(status_str):
        if not status_str:
            return None
        s = status_str.strip().lower()
        if "landed" not in s:
            return None
        try:
            t = s.split("landed")[-1].strip()
            return clean_time_str(t)
        except:
            return None

    # Get landing time
    landing_t = extract_landing_time(status)
    if not landing_t:
        # REQUIRED: discard if no Landed HH:MM
        return None

    # ---------------------------------------------------------
    # Require flight_time
    # ---------------------------------------------------------
    ft = clean_time_str(flight_time)
    if not ft:
        return None

    # ---------------------------------------------------------
    # Parse times
    # ---------------------------------------------------------
    std_dt = parse_time(date, std)
    atd_dt = parse_time(date, atd) if atd else None
    if not std_dt:
        return None

    dep = atd_dt or std_dt

    # ---------------------------------------------------------
    # Rollover check
    # ---------------------------------------------------------
    if atd_dt and atd_dt < std_dt:
        delta = std_dt - atd_dt
        if delta > timedelta(hours=2):
            dep += timedelta(days=1)

    # ---------------------------------------------------------
    # Compute arrival
    # ---------------------------------------------------------
    hh, mm = map(int, ft.split(":"))
    duration = timedelta(hours=hh, minutes=mm)
    computed_arrival = dep + duration

    # ---------------------------------------------------------
    # Parse actual reported landing time
    # ---------------------------------------------------------
    reported_arr = parse_time(date, landing_t)
    if reported_arr and reported_arr < dep:
        reported_arr += timedelta(days=1)

    # Validate consistency
    if reported_arr:
        diff = abs((reported_arr - computed_arrival).total_seconds())
        # Allow small operational differences (20 min)
        if diff > 20 * 60:
            return None
        return reported_arr

    return None  # Should not reach here but safe


# ---------------------------------------------------------
# Aircraft path validation utilities
# ---------------------------------------------------------

def validate_and_segment_path(legs, min_turnaround_minutes=20):
    """
    Validate continuity of aircraft path.

    Returns:
        segments: list of lists of legs (continuous paths)
        breaks: list of dicts describing discontinuities
    """

    if not legs:
        return [], []

    # Sort by departure time
    legs = sorted(legs, key=lambda x: x["dep"])

    segments = []
    current_segment = [legs[0]]
    breaks = []

    for prev, curr in zip(legs, legs[1:]):
        ok = True
        reason = None

        # continuity check
        if prev["to"] != curr["from"]:
            ok = False
            reason = "airport_mismatch"

        # time order check
        elif curr["dep"] < prev["arr"]:
            ok = False
            reason = "time_overlap"

        # turnaround check
        elif (curr["dep"] - prev["arr"]).total_seconds() < min_turnaround_minutes * 60:
            ok = False
            reason = "insufficient_turnaround"

        if ok:
            current_segment.append(curr)
        else:
            breaks.append({
                "reason": reason,
                "prev": prev,
                "curr": curr,
            })
            segments.append(current_segment)
            current_segment = [curr]

    segments.append(current_segment)

    return segments, breaks


def build_airline_paths(conn, airline):
    cur = conn.cursor()
    cur.execute("""
        SELECT a.registration, f.date, f.from_airport, f.to_airport,
               f.std, f.atd, f.sta, f.flight_time, f.status
        FROM flights f
        JOIN aircraft a ON a.registration = f.registration
        WHERE a.operator = ?
        ORDER BY a.registration, f.date, f.std
    """, (airline,))

    paths = {}

    for (reg, date, from_raw, to_raw, std, atd, sta, flight_time, status) in cur.fetchall():

        if "landed" not in (status or "").lower():
            continue

        from_iata = extract_iata(from_raw)
        to_iata = extract_iata(to_raw)
        if not from_iata or not to_iata:
            continue

        dep = parse_time(date, atd) or parse_time(date, std)
        arr = compute_arrival(date, std, sta, atd, flight_time, status)
        if not dep or not arr:
            continue

        paths.setdefault(reg, []).append({
            "from": from_iata,
            "to": to_iata,
            "dep": dep,
            "arr": arr,
        })

    return paths
