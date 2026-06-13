# traffic-prediction

Time the evening **office → home** commute (south Bengaluru, ~9 km up the
Hosur Road / Electronic City corridor) to dodge the jam pockets.

Two data sources that reinforce each other:

- **TomTom predictive sweep** (`log_commute.py`) — asks "if I leave at 17:00,
  17:15, … 19:30, how long does it take?" You can't answer that from your own
  driving because you only commute once a day. This tells you **when to leave**.
- **Your GPS traces** (`ingest_gpx.py`) — your actual recorded drive is
  ground truth: real travel time and the exact spots where you crawled. This
  tells you **where the pockets are** and validates the predictions.

`plot_commute.py` merges both into `plots/`.

## Setup

```bash
pip install -r requirements.txt
# free key, 2,500 req/day, no credit card: https://developer.tomtom.com
export TOMTOM_API_KEY=...
```

Route, sweep window and pocket threshold live in `config.json` (origin/dest are
already your office and stay).

## Daily workflow

```bash
# 1. predictive sweep — run any time, ideally once a day (e.g. cron at 09:00)
python3 log_commute.py
#    -> appends data/eta_log.csv + data/pockets_log.csv

# 2. after the drive home, feed the day's GPS trace (GPX from your recorder)
python3 ingest_gpx.py ~/gps/20260613-173000.gpx
#    -> appends data/gpx_summary.csv + data/gpx_pockets.csv

# 3. redraw the plots whenever you want to look
python3 plot_commute.py
#    -> plots/eta_curve.png  (best departure window, per weekday)
#    -> plots/pocket_map.png (where jams happen: predicted vs actual)
```

A one-off "should I leave right now?" check:

```bash
python3 log_commute.py --now
```

Let it accumulate for ~1–2 weeks before trusting the weekday curves — a single
day is weather/incident noise.

## Automate the daily sweep

`run_daily.sh` loads the key from `.env`, runs the sweep, and logs to
`run_daily.log` so cron failures are visible.

```bash
cp .env.example .env        # then put your TOMTOM_API_KEY in .env
chmod +x run_daily.sh
./run_daily.sh              # test it once by hand

# install: weekdays at 09:00
( crontab -l 2>/dev/null; echo "0 9 * * 1-5 $(pwd)/run_daily.sh" ) | crontab -
```

## Data files (git-ignored)

| file | written by | meaning |
|------|-----------|---------|
| `data/eta_log.csv`     | log_commute | predicted travel time per departure time |
| `data/pockets_log.csv` | log_commute | predicted congested sections |
| `data/gpx_summary.csv` | ingest_gpx  | actual travel time per trace |
| `data/gpx_pockets.csv` | ingest_gpx  | actual slow stretches |

## GPS recorder

Any app that exports timestamped GPX works (e.g. BasicAirData GPS Logger or
GPSLogger for Android). A 1 s logging interval gives the cleanest speed
profile.
