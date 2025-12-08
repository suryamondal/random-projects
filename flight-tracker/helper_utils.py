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
def compute_arrival(date, std, sta, atd, flight_time):
    """
    New logic:
    - Requires flight_time to be present.
    - Computes arrival solely as ATD + flight_time (with rollover handling).
    """

    ft = clean_time_str(flight_time)
    if not ft:
        return None  # redundant but safe

    # Parse STD and ATD
    dep = parse_time(date, atd) or parse_time(date, std)
    if not dep:
        return None

    std_dt = parse_time(date, std)
    if not std_dt:
        return None

    # If actual takeoff time is earlier than STD → next day rollover
    if dep < std_dt:
        dep = dep + timedelta(days=1)

    # Parse duration HH:MM
    try:
        hh, mm = map(int, ft.split(":"))
        duration = timedelta(hours=hh, minutes=mm)
    except:
        return None

    # Compute arrival
    arr = dep + duration
    return arr
