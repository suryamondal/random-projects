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
    Strategy:
    1) If ATD + flight_time available → use that.
    2) Otherwise fall back to STA, with next-day rollover logic.
    """
    atd_c = clean_time_str(atd)
    ft_c  = clean_time_str(flight_time)

    # --- Primary: ATD + flight_time ---
    if atd_c and ft_c:
        dep = parse_time(date, atd_c)
        if dep:
            try:
                hh, mm = map(int, ft_c.split(":"))
                return dep + timedelta(hours=hh, minutes=mm)
            except Exception:
                pass

    # --- Fallback: use STA ---
    arr = parse_time(date, sta)
    dep_std = parse_time(date, std)

    if arr and dep_std:
        # Rollover: arrival past midnight
        if arr.time() < dep_std.time():
            arr = arr + timedelta(days=1)
        return arr

    return None
