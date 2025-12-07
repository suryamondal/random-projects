#!/usr/bin/env python3
import argparse
import os
import time
import random
import json
import re
import requests
from bs4 import BeautifulSoup

# ---------------------------
# Global user-agent
# ---------------------------
HEADERS = {
    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
}

# ---------------------------
# Read registrations
# ---------------------------
def load_registrations(path):
    regs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            regs.append(line)
    return regs

# ---------------------------
# Extract label/value for OPERATOR / AIRCRAFT
# ---------------------------
def get_label_value(soup, label):
    """
    FR24 renders "AIRCRAFT", "AIRLINE", "OPERATOR" in many layouts.
    This function searches for text 'AIRLINE', then pulls the value next to it.
    """
    # Try exact match first
    node = soup.find(string=re.compile(rf"^{label}\s*$", re.I))
    if not node:
        # Try partial (sometimes extra whitespace)
        node = soup.find(string=re.compile(label, re.I))

    if not node:
        return None

    # Value often appears in the sibling element
    parent = node.parent
    if not parent:
        return None

    # Try next sibling first
    nxt = parent.find_next_sibling()
    if nxt and nxt.get_text(strip=True):
        txt = nxt.get_text(strip=True)
        if txt and txt.lower() != label.lower():
            return txt

    # Try searching nearby nodes
    count = 0
    cur = parent
    while count < 5 and cur:
        cur = cur.find_next()
        count += 1
        if not cur:
            break
        txt = cur.get_text(strip=True)
        if txt and txt.lower() != label.lower():
            return txt

    return None

# ---------------------------
# Parse a single flight row
# ---------------------------
def parse_flight_row(row):
    cols = row.find_all("td")

    # Desktop rows have >= 10 columns
    if len(cols) < 10:
        return None

    def t(i):
        return cols[i].get_text(" ", strip=True)

    # Column meaning:
    # 0 DATE
    # 1 FROM
    # 2 TO
    # 3 FLIGHT
    # 4 FLIGHT TIME
    # 5 STD
    # 6 ATD
    # 7 STA
    # 8 ICON (ignore)
    # 9 STATUS

    return {
        "date": t(0),
        "from": t(1),
        "to": t(2),
        "flight": t(3),
        "flight_time": t(4),
        "std": t(5),
        "atd": t(6),
        "sta": t(7),
        "status": t(9)
    }

# ---------------------------
# Parse the full aircraft page HTML
# ---------------------------
def parse_aircraft_page(html, registration):
    soup = BeautifulSoup(html, "html.parser")

    # Operator / Aircraft Type
    operator = get_label_value(soup, "OPERATOR")
    if not operator:
        operator = get_label_value(soup, "AIRLINE")

    aircraft_type = get_label_value(soup, "AIRCRAFT")

    # Flight history table
    flights = []
    table = soup.find("table", id="tbl-datatable")

    if table:
        rows = table.find_all("tr")
        for r in rows:
            cls = r.get("class") or []
            # Skip upgrade rows
            if any("row-upgrade" in c for c in cls):
                continue

            parsed = parse_flight_row(r)
            if parsed:
                flights.append(parsed)

    # FR24 lists most recent first → reverse to earliest first
    flights.reverse()

    return {
        "registration": registration.upper(),
        "operator": operator,
        "type": aircraft_type,
        "flight_history": flights
    }

# ---------------------------
# Fetch the aircraft HTML
# ---------------------------
def fetch_html(url):
    res = requests.get(url, headers=HEADERS, timeout=20)
    res.raise_for_status()
    return res.text

# ---------------------------
# Handle one aircraft scrape
# ---------------------------
def scrape_aircraft(reg):
    url = f"https://www.flightradar24.com/data/aircraft/{reg.lower()}"
    try:
        html = fetch_html(url)
    except Exception as e:
        print(f"[ERROR] Could not fetch {reg}: {e}")
        return None

    return parse_aircraft_page(html, reg)

# ---------------------------
# Main
# ---------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", required=True, help="File with registration numbers")
    parser.add_argument("-o", "--output", required=True, help="Directory to save JSON files")
    parser.add_argument("--min-sleep", type=float, default=2.0)
    parser.add_argument("--max-sleep", type=float, default=6.0)
    args = parser.parse_args()

    regs = load_registrations(args.file)
    if not regs:
        print("No valid registrations found.")
        return

    os.makedirs(args.output, exist_ok=True)

    for reg in regs:
        print(f"Scraping {reg} ...")

        data = scrape_aircraft(reg)
        if not data:
            print(f"Skipping {reg} due to read/parse error.")
            continue

        out_path = os.path.join(args.output, f"{reg.upper()}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Saved → {out_path}")

        # Random polite delay
        delay = random.uniform(args.min_sleep, args.max_sleep)
        print(f"Sleeping {delay:.2f}s ...")
        time.sleep(delay)

if __name__ == "__main__":
    main()
