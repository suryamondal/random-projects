#!/usr/bin/env python3
"""Query TomTom's traffic-aware routing API for the office->home route across a
sweep of evening departure times, and append the results to two CSVs:

  data/eta_log.csv     one row per (query, departure) with predicted travel time
  data/pockets_log.csv one row per congested road section (a "pocket")

Predictive traffic only works for *future* departure times, so each clock time
in the sweep is resolved to its next upcoming occurrence (weekends optionally
skipped). Run this daily (e.g. from cron) to build a per-weekday picture of when
the route is fastest. Needs a free TomTom key in the TOMTOM_API_KEY env var
(https://developer.tomtom.com, 2,500 requests/day free, no card required).

Usage:
    export TOMTOM_API_KEY=...
    python3 log_commute.py                # sweep from config.json
    python3 log_commute.py --now          # single live query for "leave now"
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys

import requests

DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, "data")
CFG_PATH = os.path.join(DIR, "config.json")
BASE = "https://api.tomtom.com/routing/1/calculateRoute"

ETA_FIELDS = [
    "query_time", "depart_at", "weekday", "clock",
    "travel_min", "no_traffic_min", "traffic_delay_min",
    "length_km", "n_pockets",
]
POCKET_FIELDS = [
    "query_time", "depart_at", "clock",
    "start_lat", "start_lon", "end_lat", "end_lon",
    "effective_speed_kmh", "delay_s", "magnitude",
]


def load_config() -> dict:
    with open(CFG_PATH) as f:
        return json.load(f)


def parse_offset(off: str) -> dt.timezone:
    """'+05:30' -> tzinfo."""
    sign = 1 if off[0] == "+" else -1
    h, m = int(off[1:3]), int(off[4:6])
    return dt.timezone(sign * dt.timedelta(hours=h, minutes=m))


def sweep_times(cfg: dict, tz: dt.timezone) -> list[dt.datetime]:
    """Resolve each clock time in the sweep to its next upcoming occurrence."""
    s = cfg["sweep"]
    sh, sm = map(int, s["start"].split(":"))
    eh, em = map(int, s["end"].split(":"))
    step = dt.timedelta(minutes=s["step_min"])
    now = dt.datetime.now(tz)

    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)

    out: list[dt.datetime] = []
    t = start
    while t <= end:
        when = t
        # roll forward to a future day; optionally skip Sat/Sun
        while when <= now or (cfg.get("skip_weekends") and when.weekday() >= 5):
            when += dt.timedelta(days=1)
        out.append(when)
        t += step
    return out


def query(cfg: dict, key: str, depart_at: dt.datetime | None) -> dict:
    o, d = cfg["origin"], cfg["destination"]
    loc = f"{o['lat']},{o['lon']}:{d['lat']},{d['lon']}"
    params = {
        "key": key,
        "traffic": "true",
        "routeType": "fastest",
        "travelMode": "car",
        "computeTravelTimeFor": "all",
        "sectionType": "traffic",
    }
    if depart_at is not None:
        params["departAt"] = depart_at.isoformat()
    r = requests.get(f"{BASE}/{loc}/json", params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"TomTom {r.status_code}: {r.text[:200]}")
    return r.json()


def extract(route: dict) -> tuple[dict, list[dict]]:
    """Pull the summary row and the list of congested sections from a route."""
    s = route["summary"]
    points: list[dict] = []
    for leg in route.get("legs", []):
        points.extend(leg.get("points", []))

    pockets: list[dict] = []
    for sec in route.get("sections", []):
        if sec.get("sectionType") != "TRAFFIC":
            continue
        i, j = sec.get("startPointIndex", 0), sec.get("endPointIndex", 0)
        a = points[i] if i < len(points) else {}
        b = points[j] if j < len(points) else {}
        pockets.append({
            "start_lat": a.get("latitude"), "start_lon": a.get("longitude"),
            "end_lat": b.get("latitude"), "end_lon": b.get("longitude"),
            "effective_speed_kmh": sec.get("effectiveSpeedInKmh"),
            "delay_s": sec.get("delayInSeconds"),
            "magnitude": sec.get("magnitudeOfDelay"),
        })

    summary = {
        "travel_min": round(s["travelTimeInSeconds"] / 60, 1),
        "no_traffic_min": round(s.get("noTrafficTravelTimeInSeconds", 0) / 60, 1),
        "traffic_delay_min": round(s.get("trafficDelayInSeconds", 0) / 60, 1),
        "length_km": round(s["lengthInMeters"] / 1000, 2),
        "n_pockets": len(pockets),
    }
    return summary, pockets


def append(path: str, fields: list[str], rows: list[dict]) -> None:
    os.makedirs(DATA, exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--now", action="store_true",
                    help="single live query for leaving now (no departAt sweep)")
    args = ap.parse_args()

    key = os.environ.get("TOMTOM_API_KEY")
    if not key:
        print("error: set TOMTOM_API_KEY (https://developer.tomtom.com)", file=sys.stderr)
        return 1

    cfg = load_config()
    tz = parse_offset(cfg["timezone_offset"])
    now = dt.datetime.now(tz)
    departures = [None] if args.now else sweep_times(cfg, tz)

    eta_rows, pocket_rows = [], []
    for when in departures:
        data = query(cfg, key, when)
        if not data.get("routes"):
            print(f"warn: no route for {when}", file=sys.stderr)
            continue
        summary, pockets = extract(data["routes"][0])
        label = "now" if when is None else when.strftime("%H:%M")
        depart_iso = now.isoformat() if when is None else when.isoformat()
        eta_rows.append({
            "query_time": now.isoformat(), "depart_at": depart_iso,
            "weekday": (now if when is None else when).strftime("%a"),
            "clock": label, **summary,
        })
        for p in pockets:
            pocket_rows.append({
                "query_time": now.isoformat(), "depart_at": depart_iso,
                "clock": label, **p,
            })
        print(f"{label}: {summary['travel_min']} min "
              f"(+{summary['traffic_delay_min']} delay, {summary['n_pockets']} pockets)")

    append(os.path.join(DATA, "eta_log.csv"), ETA_FIELDS, eta_rows)
    append(os.path.join(DATA, "pockets_log.csv"), POCKET_FIELDS, pocket_rows)
    print(f"logged {len(eta_rows)} departures, {len(pocket_rows)} pockets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
