#!/usr/bin/env python3
import argparse
import subprocess
import json
import os
import time
import random
import re

# ------------------------------
# Run lynx and get plain text
# ------------------------------
def lynx_dump(url):
    try:
        out = subprocess.check_output(
            ["lynx", "-dump", "-nolist", url],
            stderr=subprocess.STDOUT
        ).decode("utf-8", errors="ignore")
        return out
    except Exception as e:
        print("ERROR running lynx:", e)
        return ""

# ------------------------------
# Parse flight history from text
# ------------------------------
def parse_flights(text):
    lines = text.splitlines()
    flights = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Flight numbers look like: 6E1234 / IGO123 / etc.
        if re.match(r"^[A-Z0-9]{2,3}\d{2,4}$", line):
            try:
                flight = line
                date = lines[i+1].strip()
                flight_time = lines[i+2].strip()
                status = lines[i+3].strip()
                # Expect STD block
                std = lines[i+5].strip()
                atd = lines[i+7].strip()
                sta = lines[i+9].strip()

                # FROM/TO
                from_city = lines[i+11].strip()
                to_city = lines[i+13].strip()

                flights.append({
                    "date": date,
                    "from": clean_field(from_city, "FROM "),
                    "to": clean_field(to_city, "TO "),
                    "flight": flight,
                    "flight_time": flight_time if flight_time != "-" else None,
                    "std": clean_field(std, "STD "),
                    "atd": clean_field(atd, "ATD "),
                    "sta": clean_field(sta, "STA "),
                    "status": status
                })

                # advance by pattern size
                i += 14
                continue

            except IndexError:
                break

        i += 1

    # Reverse chronology (earliest first)
    flights.reverse()
    return flights

# ------------------------------
# Extract operator and aircraft type
# ------------------------------
def clean_field(value, prefix):
    """
    Removes prefixes like 'FROM ', 'TO ', 'STD ', 'ATD ', 'STA '.
    """
    value = value.replace("\u2014", "-")  # normalize long-dash
    if value.startswith(prefix):
        return value[len(prefix):].strip()
    return value.strip()

def extract_meta(text):
    operator = None
    aircraft_type = None

    lines = [l.strip() for l in text.splitlines()]

    for idx, line in enumerate(lines):
        if line == "AIRCRAFT":
            aircraft_type = lines[idx+1].strip()
        if line == "AIRLINE":
            # AIRLINE may appear as: AIRLINE [4]IndiGo
            operator = re.sub(r"\[\d+\]", "", lines[idx+1]).strip()
        if line == "OPERATOR":
            operator = lines[idx+1].strip()

    return operator, aircraft_type

    return operator, aircraft

def next_nonempty(current_line, full_text):
    lines = full_text.splitlines()
    idx = lines.index(current_line)
    for j in range(idx+1, len(lines)):
        if lines[j].strip():
            return lines[j].strip()
    return None

# ------------------------------
# Main single-aircraft scrape
# ------------------------------
def scrape(reg):
    url = f"https://www.flightradar24.com/data/aircraft/{reg.lower()}"
    text = lynx_dump(url)

    operator, aircraft_type = extract_meta(text)
    flights = parse_flights(text)

    return {
        "registration": reg.upper(),
        "operator": operator,
        "type": aircraft_type,
        "flight_history": flights
    }

# ------------------------------
# CLI main
# ------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", required=True)
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    with open(args.file, "r") as f:
        regs = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    os.makedirs(args.output, exist_ok=True)

    for reg in regs:
        print(f"Scraping {reg} ...")
        data = scrape(reg)

        out = os.path.join(args.output, f"{reg.upper()}.json")
        with open(out, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2)

        print(f"Saved → {out}")

        time.sleep(random.uniform(2, 6))

if __name__ == "__main__":
    main()
