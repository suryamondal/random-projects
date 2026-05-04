#!/usr/bin/env python3
"""Scrape current TMC/BJP seat lead + vote% from the ECI WB 2026 partywise page
and append a row to results.csv (columns: time,tmc,bjp,tmc_vote_pct,bjp_vote_pct)."""

import csv
import datetime
import os
import re
import sys
import urllib.request

URL = "https://results.eci.gov.in/ResultAcGenMay2026/partywiseresult-S25.htm"
DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(DIR, "results.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def seat_total(html: str, party_name: str) -> int | None:
    """Return the 'Total' column value for a party row in the Party Wise Results table."""
    pat = re.compile(
        r'<tr class="tr">\s*<td[^>]*>\s*' + re.escape(party_name)
        + r'\s*</td>.*?<td[^>]*>\s*([0-9]+)\s*</td>\s*</tr>',
        re.S,
    )
    m = pat.search(html)
    return int(m.group(1)) if m else None


def vote_pct(html: str, label: str) -> float | None:
    """Pull '<label>{NN.NN%}' from the pie-chart JS array."""
    m = re.search(r"'" + re.escape(label) + r"\{([0-9.]+)%\}'", html)
    return float(m.group(1)) if m else None


def page_timestamp(html: str) -> str:
    m = re.search(r"Last Updated at\s*<span>\s*([0-9:]+)\s*([AP]M)\s*On\s*([0-9/]+)", html)
    if not m:
        return datetime.datetime.now().strftime("%H:%M")
    t12, ampm, _date = m.groups()
    h, mm = map(int, t12.split(":"))
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mm:02d}"


def main() -> int:
    html = fetch(URL)

    bjp = seat_total(html, "Bharatiya Janata Party - BJP")
    tmc = seat_total(html, "All India Trinamool Congress - AITC")
    tmc_vp = vote_pct(html, "AITC")
    bjp_vp = vote_pct(html, "BJP")
    time_str = page_timestamp(html)

    row = [
        time_str,
        tmc if tmc is not None else "",
        bjp if bjp is not None else "",
        f"{tmc_vp:.2f}" if tmc_vp is not None else "",
        f"{bjp_vp:.2f}" if bjp_vp is not None else "",
    ]

    new_file = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["time", "tmc", "bjp", "tmc_vote_pct", "bjp_vote_pct"])
        w.writerow(row)

    print("appended:", row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
