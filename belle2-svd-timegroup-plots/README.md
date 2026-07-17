# SVD Time-Grouping Event Plots

A small Belle II project that produces, **one PDF page per event**, the SVD
time-grouping histogram overlaid with the fitted per-group Gaussians (all groups,
or a selected subset of signal groups). Simulation only for now.

## What it does

The production `SVDTimeGrouping` module builds a cluster-time histogram (each
cluster smeared by its time resolution), fits Gaussian peaks, and stamps every
`SVDCluster` with its group id and the group's Gaussian parameters
`(integral, center, sigma)`.

This project adds a local module, **`SVDTimeGroupingPlotter`**, that runs *after*
grouping. For each event it:

1. rebuilds the same cluster-time histogram (reusing the grouping module's
   shaping helpers, so it matches bin-for-bin);
2. reads back the per-group Gaussian parameters from the clusters;
3. draws the histogram (black) with each selected group's Gaussian overlaid in a
   distinct colour, plus a legend (group id, peak time, cluster count);
4. appends the canvas as a page to a multi-page PDF.

## Layout

```
basf2/                                    local basf2 analysis directory
  setup.sh                                sources b2setup, links site_scons, sets paths
  svd/modules/SVDTimeGroupingPlotter/     the local C++ module
    include/  src/  SConscript
scripts/
  plot_timegroups.py                      simulate -> cluster -> group -> plot steering
plots/                                    output PDFs land here
```

## Build & run

```bash
cd basf2
source setup.sh          # sets up basf2; needs the belle2 environment
scons                    # compiles the local SVDTimeGroupingPlotter module
cd ..
basf2 scripts/plot_timegroups.py -- --numEvents 10
# -> plots/svd_timegroups.pdf, one page per event
```

Useful options:

- `--groups 0 1 2` — overlay only these group ids (default: all). Group `0` is
  the most signal-like after the grouping module's sort.
- `--bkgDir <dir>` — overlay beam-background `BGOverlay` ROOT files; this is what
  creates the out-of-time groups the algorithm is built to separate.
- `--process mumu` — use `e+e- -> mu+mu-` instead of `Y(4S) -> BB`.
- `--numEvents`, `--seed`, `--output`.

The module also takes `useFullRange` (default `True`): it draws the full
`[tRangeLow, tRangeHigh]` window (±160 ns) so out-of-time background groups are
seen in context. Set it `False` to shrink the x-axis to the populated span, as
the grouping module does internally for its fit.

## Notes

- The plotter runs grouping with `useParamFromDB=False` so both grouping and
  plotting use the compiled default resolutions — that is what makes the redrawn
  histogram exact. If you run grouping from DB payloads instead, the overlay is
  still close but not guaranteed bin-identical.
- Grouping is skipped by the production module for events with `< 10` clusters;
  those pages are drawn with a "no time groups" note.
