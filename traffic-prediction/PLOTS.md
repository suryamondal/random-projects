# Plot menu

Pick a heading, name your traces, and say "do this". Every command below is
copy-pasteable as-is; substitute the file names.

Vehicle tag is taken from the filename suffix (`-honda-jazz.gpx`,
`-honda-brio.gpx`, `-ktm-duke-390.gpx`, `-re-hunter-350.gpx`).

---

## 1. Two or more traces, synced at a speed breaker  ← the canonical pace plot

**Answers:** who lost time where, against a fixed benchmark that is the same in
every plot ever made this way.

```bash
python3 breaker_overlay.py \
  gps/office-route/20260824-180634-honda-jazz.gpx \
  gps/office-route/20260821-181637-honda-brio.gpx \
  --labels "Jazz — you 08-24,Brio — him 08-21"
```

Top panel: time relative to the breaker crossing. Bottom panel: **each trace
against a constant-pace line**, not against each other — that keeps the zero
fixed so this plot can be laid beside any other one.

| option | default | note |
|---|---|---|
| `--breaker-index` | `2` | sorted breakers `[0.90, 3.20, 4.39, 4.54, 4.82]`, so 2 = **4.39 km**. This is the one the earlier return overlays used. |
| `--breaker-km` | – | explicit km, overrides the index |
| `--pace` | `24` | km/h of the reference line |
| `--top-ylim` / `--delta-ylim` | `-13,16` / `-4,5` | fixed so plots stay comparable |

Traces must span the breaker and reach the destination (`dest_gap <= 400 m`).
A trace whose *origin* half is incomplete is drawn **dashed** and its
origin→breaker time reported `n/a`. Prints an origin→breaker / breaker→dest
table.

Also works for a whole fleet: `python3 breaker_overlay.py gps/office-route/*-honda-brio.gpx`

---

## 2. Every trace of one vehicle, overlaid

**Answers:** is this driver getting faster over weeks, and where on the route.

```bash
python3 overlay_traces.py --bike honda-jazz --direction onward \
  --align arrival --ref best --ref-bikes honda-jazz,honda-brio \
  --top-ylim=-25,2 --delta-ylim=-6,1
```

`--align start|arrival` · `--ref first|best` · `--min-cover 0.8`
Few traces get a legend; many get a light→dark date colormap.

---

## 3. Exactly two traces, gate to gate

```bash
python3 compare_traces.py A.gpx B.gpx --label-a "..." --label-b "..." \
  [--sync breaker --breaker-km 4.39]
```

Bottom panel is **A − B**, which has no fixed zero — fine for a one-off
pairwise question, not comparable across plots. For anything you want to line
up against other plots, use §1 instead.

---

## 4. Driving style over time

```bash
python3 analyze_driving_style.py     # free-flow speed + assertiveness vs date
python3 driving_tests.py             # gap-to-veteran map, traffic control, cornering, launch
```

No arguments. Both filter to full gate-to-gate traces (both ends within 1 km).

---

## 5. Whole-drive IMU residual, one page

**Answers:** how hard the road worked each car, over the whole commute.

```bash
python3 imu_resid_full.py \
  --a sensors/284CL-2026-08-24_12-39-06.zip --a-gpx gps/office-route/20260824-180634-honda-jazz.gpx --a-label "Jazz — you" \
  --b sensors/2026-08-21_12-49-54.zip       --b-gpx gps/office-route/20260821-181637-honda-brio.gpx --b-label "Brio — him"
```

16:9, four stacked panels: A's vertical residual (raw − 25-sample MA), its
per-second std, then the same two for B.

**Speed is drawn full-scale behind each residual panel** as a plain line (no
fill) with its own right-hand km/h axis — the residual can't be read without it, since speed is what puts the
energy into the suspension in the first place.

| option | default | note |
|---|---|---|
| `--x` | `position` | `position` is the only x that puts both cars over the same tarmac; `time` gives each drive its own clock |
| `--vmax` | `50` | full scale of the speed background |
| `--nbin` | `2600` | envelope columns |

Residual is drawn as a per-pixel min/max envelope, not decimated — decimation
would alias the amplitude downward. Residual and std y-scales are shared between
the two cars, so the panels can be compared by eye.

---

## 6. IMU flipbook, two drives, one page per 20 s

```bash
python3 imu_frame.py sensors/<rec>.zip          # once per recording, first
python3 imu_compare_time_pdf.py \
  --a sensors/A.zip --a-gpx gps/office-route/A.gpx --a-label "Jazz — you" \
  --b sensors/B.zip --b-gpx gps/office-route/B.gpx --b-label "Brio — him"
```

Top A, bottom B, map right. Windows are 20 s but **centred by position**: A's
window centre is converted to an along-route arc-length and B's window is
centred where B first reached that same point. Windows therefore cover
different *lengths* of road; each panel prints its own span.

`--alt-page` inserts a second page after each one:

| value | content |
|---|---|
| `none` *(default)* | – |
| `diff` | actual − the 25-sample MA already on the main page: what the smoothing discards |
| `spec` | window spectrum in dB vs its own local `--spec-ma` moving average |
| `gcc` | distance-resampled channels + GCC-PHAT + coherence — **see gotcha 3** |

`--layout resid4` replaces the page with four stacked 16:9 panels (A residual,
A per-second std, B residual, B per-second std).

---

## 7. IMU flipbook, one drive

```bash
python3 imu_journey_pdf.py sensors/<rec>.zip --gpx gps/office-route/<t>.gpx
```

---

## 8. Route geometry and features

```bash
python3 route_profile.py       # pooled lat/lon/elevation, 3 m bins
python3 speed_breakers.py      # breaker detection + map
python3 plot_commute.py        # commute history plot set
```

---

## Data intake

```bash
# 1. unzip into gps/raw/ and sensors/, delete the zip
# 2. tag and cut any off-route detour
python3 filter_offroute.py --bike honda-jazz --out gps/office-route gps/raw/<t>.gpx
# 3. re-ingest everything
python3 ingest_gpx.py gps/office-route/*.gpx
```

`filter_offroute` copies a clean trace **byte-for-byte**; it only cuts at a real
detour (`--corridor 60 --min-detour 300 --min-depth 200`).

---

## Conventions

- **Plots are `.svg`.** PDFs only for multi-page flipbooks.
- Colours, vehicles: Jazz `#d1495b` · Brio `#2a9d8f` · Duke 390 `#2e4a62` · Hunter 350 `#8a8d91`. Do not change these between plots.
- Colours, data channels: vertical `#4c956c` · forward `#b2182b` · lateral `#7b5aa6` · **speed `#1f6fbf`**.
  Speed must not reuse `#2e4a62` — that is the Duke 390. The IMU flipbooks
  (§6, §7) still draw speed in `#2e4a62` and have not been migrated.
- Per-100 m section-time step plots: cap y at **12 s/100 m**.
- Breaker sync defaults to **4.39 km**; constant-pace reference **24 km/h**.
- Style metrics use full gate-to-gate traces only (both ends within 1 km).
- `gps/`, `sensors/`, `data/`, `plots/` are gitignored — scripts are committed, data is not.

## Gotchas

1. **Position is quantised to ~6.23 m.** `ingest_gpx.project_arc_length` returns
   the arc-length of the *nearest route vertex*, so position stalls for ~35 % of
   samples. Harmless at 200 m section resolution; it dominates anything plotted
   against position. `imu_compare_pdf.refine_arc_length()` fixes it (35 % → 1 %)
   and the IMU scripts use it. The GPS plot scripts still use the raw
   projection — worth applying if a plot depends on fine position.
2. **IMU recordings run past their GPX coverage** at both ends, so the first and
   last windows contain samples with no position. Use the finite subset; one
   NaN must not void a whole range.
3. **GCC-PHAT does not work at 20 s.** Measured coherence between the two cars'
   vertical channels over a 20 s window is **0.11**, and the correlation peak's
   2nd/1st ratio runs 0.89–0.98 — no distinct peak. Road matching only converges
   above ~**300 m** (median lag error 18 m at a 20 m window, 5 m at 640 m).
   Short windows report *high* correlation at a *random* lag, which is
   overfitting, not signal.
4. **Following distance is not recoverable** from a single vehicle's trace at any
   sampling rate. Speed-vs-position correlation does not separate a tailgater
   (Jazz 0.855 vs Brio 0.854). It needs both cars instrumented in convoy, or
   forward dashcam video.
5. **PDF delivery caps at 30 MiB.** Compress with
   `gs -sDEVICE=pdfwrite -dPDFSETTINGS=/printer`, split with
   `qpdf in.pdf --pages in.pdf 1-172 -- part1.pdf`. Do **not** rasterize
   matplotlib artists to shrink — it produces white seams through the traces.
6. **`Annotation.csv` in the Sensor Logger export is empty.** Tapping the
   annotation button at each speed breaker would timestamp crossings exactly and
   make per-breaker impact measurable — currently it is not, because breaker
   coordinates carry 10–20 m of their own error and the axle-pair signature
   fires 150–265 times on a road this broken.
