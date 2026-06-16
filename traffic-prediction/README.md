# traffic-prediction

Time the evening **office → home** commute (south Bengaluru, ~9 km up the
Hosur Road / Electronic City corridor) to dodge the jam pockets — built from
**your own recorded GPS traces**, no online prediction service.

The idea: record the drive home each day, and let the history slowly become its
own model:

- **When to leave** — `travel_history.svg` plots actual travel time against
  departure time across every recorded day. The pattern sharpens as days
  accumulate.
- **Where the pockets are** — `pocket_map.svg` plots every spot you actually
  crawled, sized/coloured by how long you were stuck.

## Setup

```bash
pip install -r requirements.txt        # or: sudo apt install python3-gpxpy python3-matplotlib
```

Route and pocket threshold live in `config.json` (origin/dest are already your
office and stay; `timezone_offset` localises the UTC GPS timestamps).

## Daily workflow

```bash
# after the drive home, feed the day's GPS trace (GPX from your recorder)
python3 ingest_gpx.py gps/20260616-190353.gpx
#    -> appends data/gpx_summary.csv + data/gpx_pockets.csv

# redraw the plots whenever you want to look
python3 plot_commute.py
#    -> plots/travel_history.svg  (travel time vs departure time, per weekday)
#    -> plots/pocket_map.svg      (where you got stuck)
```

Drop traces into `gps/` (git-ignored) and ingest them in a batch any time:

```bash
python3 ingest_gpx.py gps/*.gpx
```

Record **from the office** so each trace covers the full route — a drive that
starts mid-route undercounts distance, time and the early pockets.

Let it accumulate for a couple of weeks before reading too much into the
pattern; a single day is weather/incident noise.

## Data files (git-ignored)

| file | written by | meaning |
|------|-----------|---------|
| `data/gpx_summary.csv` | ingest_gpx | actual travel time per trace |
| `data/gpx_pockets.csv` | ingest_gpx | actual slow stretches |

## GPS recorder

Any app that exports timestamped GPX works (e.g. BasicAirData GPS Logger or
GPSLogger for Android). A 1 s logging interval gives the cleanest speed profile.

## Optional: online prediction (parked)

`log_commute.py` can query TomTom's traffic-aware API across a sweep of
departure times to estimate a typical-traffic curve without waiting for your
own data to build up. It needs a free `TOMTOM_API_KEY` (in `.env`) and is run
via `run_daily.sh`. Not part of the core, GPS-first workflow above — kept around
in case it's useful as a sanity check.
