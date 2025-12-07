#!/usr/bin/env python3
"""
Polished FR24 scraper that uses lynx -dump output as source of truth.

Usage:
  python3 scrape_fr24_lynx_polished.py -f regs.txt -o outdir

Requires: lynx installed and on PATH.
"""
import argparse
import subprocess
import json
import os
import time
import random
import re

# --------------------------
# Run lynx and return text
# --------------------------
def lynx_dump(url):
    try:
        out = subprocess.check_output(
            ["lynx", "-dump", "-nolist", url],
            stderr=subprocess.STDOUT
        ).decode("utf-8", errors="ignore")
        return out
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] lynx failed: {e}")
        return ""
    except FileNotFoundError:
        print("[ERROR] lynx not found. Install lynx or use another method.")
        return ""

# --------------------------
# Cleaning helpers
# --------------------------
DASH_CHARS = {"-", "—", "\u2014", "\u2013", "\u2012"}  # common dash variants

def normalize_dash(s):
    """Normalize dash-like strings to a single em-dash or None as required."""
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    # replace non-breaking spaces and weird whitespace
    s = s.replace("\u00A0", " ").strip()
    # if the value is just a dash (any variant) treat as None
    if all(ch in DASH_CHARS or ch.isspace() for ch in s) and len(s) <= 3:
        return None
    return s

def remove_prefix(value, prefix):
    """Remove prefix (case sensitive) if present and strip; then normalize dashes."""
    if value is None:
        return None
    v = value.strip()
    if v.startswith(prefix):
        v = v[len(prefix):].strip()
    return normalize_dash(v)

# --------------------------
# Meta extraction
# --------------------------
def extract_aircraft_type(text):
    lines = [ln.strip() for ln in text.splitlines()]
    for idx, ln in enumerate(lines):

        # CASE A: AIRCRAFT and type on SAME line
        if ln.startswith("AIRCRAFT "):
            parts = ln.split()
            # parts[0] = AIRCRAFT, remaining = type words
            type_words = parts[1:3]  # first two words only
            return " ".join(type_words).strip()

        # CASE B: AIRCRAFT on its own line → next non-empty line is type
        if ln == "AIRCRAFT":
            # find next non-empty line
            for nxt in lines[idx+1:]:
                if nxt:
                    parts = nxt.split()
                    type_words = parts[:2]  # first two words only
                    return " ".join(type_words).strip()

    return None  # if not found

def extract_meta(text):
    operator = None
    aircraft_type = None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # AIRLINE and OPERATOR extraction (keep your existing logic)
    for idx, ln in enumerate(lines):
        if ln.upper() == "AIRLINE":
            operator = re.sub(r"\[\d+\]", "", lines[idx+1]).strip()
        elif ln.upper().startswith("AIRLINE "):
            operator = re.sub(r"\[\d+\]", "", ln[len("AIRLINE "):]).strip()

        if ln.upper() == "OPERATOR":
            operator = lines[idx+1].strip()
        elif ln.upper().startswith("OPERATOR "):
            operator = ln[len("OPERATOR "):].strip()

    aircraft_type = extract_aircraft_type(text)

    return operator, aircraft_type

# --------------------------
# Flight parsing
# --------------------------
# Pattern to detect flight codes such as '6E7246', 'IGO92HY', etc.
FLIGHT_RE = re.compile(r"^[A-Z0-9/]{1,6}\d{1,5}$", re.I)

def parse_flights(text):
    """
    Parse the lynx-dumped text into flight records.
    The lynx dump tends to present blocks:
      <flight>
      <date>
      <flight_time>
      <status or 'Landed ...'>
      STD
      <std>
      ATD
      <atd>
      STA
      <sta>
      FROM
      <FROM ...>
      TO
      <TO ...>
    We'll scan lines and extract blocks following that pattern.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    # compact lines by removing empty lines but keep index positions flexible
    idx = 0
    flights = []

    while idx < len(lines):
        ln = lines[idx].strip()
        # detect a flight code line
        if FLIGHT_RE.match(ln):
            # attempt to harvest fields safely with bounds checks
            try:
                flight = ln
                date = lines[idx + 1].strip()
                flight_time = normalize_dash(lines[idx + 2].strip())
                status = normalize_dash(lines[idx + 3].strip())

                # The labels STD/ATD/STA appear on lines; values usually 2 lines after label in lynx dump
                # Find the next occurrences of STD, ATD, STA and their values robustly
                # We'll search forward a limited amount to find STD/ATD/STA lines.
                std = atd = sta = None
                from_field = to_field = None

                # scan up to next 20 lines for the labels and values
                for j in range(idx + 4, min(idx + 40, len(lines))):
                    s = lines[j].strip()
                    # STD label may be present alone on line 'STD' then value on next; or 'STD 03:00'
                    if s == "STD" and j + 1 < len(lines):
                        std = normalize_dash(lines[j + 1].strip())
                    elif s.startswith("STD "):
                        std = normalize_dash(s[len("STD "):].strip())
                    elif s == "ATD" and j + 1 < len(lines):
                        atd = normalize_dash(lines[j + 1].strip())
                    elif s.startswith("ATD "):
                        atd = normalize_dash(s[len("ATD "):].strip())
                    elif s == "STA" and j + 1 < len(lines):
                        sta = normalize_dash(lines[j + 1].strip())
                    elif s.startswith("STA "):
                        sta = normalize_dash(s[len("STA "):].strip())
                    elif s == "FROM" and j + 1 < len(lines):
                        from_field = lines[j + 1].strip()
                    elif s.startswith("FROM "):
                        from_field = s[len("FROM "):].strip()
                    elif s == "TO" and j + 1 < len(lines):
                        to_field = lines[j + 1].strip()
                    elif s.startswith("TO "):
                        to_field = s[len("TO "):].strip()

                    # break early if we've found FROM and TO (typical end of block)
                    if from_field and to_field:
                        break

                # If any of std/atd/sta still None, allow them to be None (normalize_dash already did)
                # Clean the FROM/TO fields to remove any "FROM"/"TO" prefixes (if present)
                if from_field:
                    from_field = remove_prefix(from_field, "FROM ")
                if to_field:
                    to_field = remove_prefix(to_field, "TO ")

                # flight_time: if '-' or None -> make None
                flight_time = normalize_dash(flight_time)

                flights.append({
                    "date": date if date else None,
                    "from": from_field if from_field else None,
                    "to": to_field if to_field else None,
                    "flight": flight,
                    "flight_time": flight_time,
                    "std": std,
                    "atd": atd,
                    "sta": sta,
                    "status": status if status else None
                })

                # advance index past this block. We jump to after the 'TO' value line if possible,
                # otherwise move +1 to avoid infinite loop.
                if to_field:
                    # find the index of that 'TO' value and continue from next line
                    # simple scan to find first occurrence of that exact to_field after idx
                    found = False
                    for k in range(idx + 4, min(len(lines), idx + 80)):
                        if lines[k].strip() == to_field:
                            idx = k + 1
                            found = True
                            break
                    if not found:
                        idx += 6
                else:
                    idx += 6

                continue

            except IndexError:
                # not enough remaining lines to parse a full block; break out
                break

        idx += 1

    # FR24 shows most recent first in dump; user requested earliest first
    flights.reverse()
    return flights

# --------------------------
# Scrape single registration
# --------------------------
def scrape(reg):
    url = f"https://www.flightradar24.com/data/aircraft/{reg.lower()}"
    txt = lynx_dump(url)
    if not txt:
        return {
            "registration": reg.upper(),
            "operator": None,
            "type": None,
            "flight_history": []
        }

    operator, aircraft_type = extract_meta(txt)
    flights = parse_flights(txt)

    return {
        "registration": reg.upper(),
        "operator": operator,
        "type": aircraft_type,
        "flight_history": flights
    }

# --------------------------
# CLI
# --------------------------
def load_registrations(path):
    with open(path, "r", encoding="utf-8") as fh:
        return [l.strip() for l in fh if l.strip() and not l.strip().startswith("#")]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", required=True, help="File with registration numbers")
    parser.add_argument("-o", "--output", required=True, help="Output directory")
    parser.add_argument("--min-sleep", type=float, default=2.0)
    parser.add_argument("--max-sleep", type=float, default=6.0)
    args = parser.parse_args()

    regs = load_registrations(args.file)
    os.makedirs(args.output, exist_ok=True)

    for reg in regs:
        print(f"Scraping {reg} ...")
        data = scrape(reg)

        out_path = os.path.join(args.output, f"{reg.upper()}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Saved → {out_path}  (flights: {len(data['flight_history'])})")
        time.sleep(random.uniform(args.min_sleep, args.max_sleep))

if __name__ == "__main__":
    main()
