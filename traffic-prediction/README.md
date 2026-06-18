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

### End-trimming

Idle time before you pull away, a late stop, and the walk to/from the car all
inflate the numbers, so each trace is clipped to just the driving part: keep
only from the first to the last point moving at >= `drive_speed_kmh`
(config.json, default 10), and re-zero distance to that start. The **interior is
never trimmed**, so mid-route traffic crawls are preserved. How much got clipped
is recorded per trace as `trim_head_s` / `trim_tail_s` — audit those; if a big
tail trim was actually slow traffic (not idle/walk), tune `drive_speed_kmh`.

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
