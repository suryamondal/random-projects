# traffic-prediction

Time the daily commute (south Bengaluru, ~9 km up the Hosur Road / Electronic
City corridor) to dodge the jam pockets — built from **your own recorded GPS
traces**, no online prediction service.

Both legs are tracked as separate pipelines, auto-classified by where each
trace starts:

- **onward** — home → office
- **return** — office → home

The idea: record each drive, and let the history slowly become its own model.
Per direction you get:

- **When to leave** — `<dir>_travel_history.svg` plots actual travel time
  against departure time across every recorded day. The pattern sharpens as
  days accumulate. (Partial traces are excluded — their time undercounts.)
- **Where the pockets are** — `<dir>_pocket_map.svg` plots every spot you
  actually crawled, sized/coloured by how long you were stuck.
- **Where *and* when** — `<dir>_section_profile.svg` is a 2D heatmap:
  x = distance along the route (200 m bins), y = departure time (10 min bins),
  colour = seconds to cross that section, moving-window smoothed. A vertical red
  band is a fixed bottleneck; a band that reddens at certain departure times is
  a rush-hour pocket.

### Reference route axis

The section profile's distance axis is **not** raw path length (which would
drift between trips with GPS noise). The first full trace per direction becomes
a fixed reference route (`data/<dir>_route.json`); every trace's GPS points are
projected onto it, so the same physical place always lands at the same x. The
axis is built once and reused; pass `--rebuild-route` to rebuild it from the
longest trace in the batch.

## Setup

```bash
pip install -r requirements.txt        # or: sudo apt install python3-gpxpy python3-matplotlib
```

Route and pocket threshold live in `config.json` (origin/dest are already your
office and stay; `timezone_offset` localises the UTC GPS timestamps).

## Daily workflow

Drop traces into `gps/` (git-ignored) and ingest — direction is detected
automatically, so you can pass both legs (or the whole folder) at once:

```bash
python3 ingest_gpx.py gps/*.gpx
#    -> appends data/{onward,return}_summary.csv + _pockets.csv + _sections.csv

# redraw the plots whenever you want to look
python3 plot_commute.py
#    -> plots/<dir>_travel_history.svg + <dir>_pocket_map.svg + <dir>_section_profile.svg
```

Record **from the start point** (home for the onward leg, office for the return
leg) so each trace covers the full route. A drive that starts more than
`partial_gap_m` (config.json, default 400 m) from its origin is flagged
`partial=True` — still logged, but excluded from the travel-time and section
plots.

### Station clamping

Each route runs between two fixed **terminating stations** (`config.json →
stations`, one near the office, one near home). There is no fixed head/tail
trim — the ends are defined purely by **movement near the stations**:

- **Start** = the *first* real movement leaving the origin station.
- **End** = the *last* real movement near the destination station.

"Real movement" is a sustained window (`pullaway_min_pts`) averaging
>= `drive_speed_kmh`; "near" is within `station_radius_m` of the station. So the
walk to the bike, **helmet-up, idling, and the final creep-to-stop / parking**
are all excluded, while the moving ride — including a jam just *outside* the
station — is kept. The **interior is never trimmed**. How much got clipped is
recorded per trace as `trim_head_s` / `trim_tail_s`.

If no `stations` are configured it falls back to a plain speed-based trim.

### Partial traces are recovered

A trace that never gets within `partial_gap_m` of a station (you forgot to
record from the start, or stopped short) is flagged `partial=True`. Its *total*
travel time is an undercount, so it stays out of the travel-time plot — but
because every section is projected onto the shared route axis, the stretch it
*did* drive still contributes valid section times to the 2D profile. A trace
that joins at 2 km still informs everything from 2 km onward.

Let it accumulate for a couple of weeks before reading too much into the
pattern; a single day is weather/incident noise.

## Data files (git-ignored)

One set per direction (`onward_*`, `return_*`):

| file | written by | meaning |
|------|-----------|---------|
| `data/<dir>_summary.csv` | ingest_gpx | actual travel time per trace (with direction, partial flag, trim) |
| `data/<dir>_pockets.csv` | ingest_gpx | actual slow stretches |
| `data/<dir>_sections.csv` | ingest_gpx | time to cross each 200 m route section (full traces) |
| `data/<dir>_route.json` | ingest_gpx | reference route axis the sections project onto |

## GPS recorder

Any app that exports timestamped GPX works (e.g. BasicAirData GPS Logger or
GPSLogger for Android). A 1 s logging interval gives the cleanest speed profile.

## Optional: online prediction (parked)

`log_commute.py` can query TomTom's traffic-aware API across a sweep of
departure times to estimate a typical-traffic curve without waiting for your
own data to build up. It needs a free `TOMTOM_API_KEY` (in `.env`) and is run
via `run_daily.sh`. Not part of the core, GPS-first workflow above — kept around
in case it's useful as a sanity check.
