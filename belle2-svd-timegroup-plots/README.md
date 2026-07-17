# SVD Time-Grouping Event Plots

One PDF page per event: the SVD time-grouping histogram with every group's fitted
Gaussian drawn on top. That's it.

## Get only this directory

This lives inside the `random-projects` monorepo. To pull **only** this folder
(sparse checkout, no other projects):

```bash
git clone --filter=blob:none --sparse https://github.com/suryamondal/random-projects.git
cd random-projects
git sparse-checkout set belle2-svd-timegroup-plots
cd belle2-svd-timegroup-plots
```

If it lives on a branch rather than the default one, add `--branch <branch>` to
the `git clone`. Already cloned the repo? Just run the `git sparse-checkout set`
line from its root.

## Run it

```bash
cd basf2 && source setup.sh && scons && cd ..     # once
basf2 scripts/plot_timegroups.py -- --numEvents 10
open plots/svd_timegroups.pdf                      # one page per event
```

Already set up the shell? Skip straight to the `basf2 ...` line.

> **`setup.sh` is for a LOCAL basf2 install only.** On a CVMFS release you must
> edit it (swap the local paths for `source /cvmfs/belle2.cern.ch/tools/b2setup`
> + `b2setup <release>`). See the banner at the top of `basf2/setup.sh`.

## Knobs you'll actually use

```bash
--groups 0 1 2      # only these groups (default: all). group ids, not the signal tag
--bkgDir <dir>      # overlay beam background -> lots of groups to look at
--numEvents 10      # how many events/pages
--output plots/x.pdf
```

## What you're looking at

Two pads per page, same event:

- **Left** raw cluster-time histogram (0.5 ns bins, one count per cluster).
- **Right** the Gaussian-weighted distribution the grouping algorithm fits.
- **Coloured curves** = each group's fitted Gaussian, id tagged over its peak.
- **`(signal)` group + dotted line** = the group that wins the true (MC-truth)
  signal clusters, and those clusters' mean time. Everything else is beam
  background. (Signal isn't always group 0 — it's decided from truth.)
- Full ±160 ns range so out-of-time groups stay in frame.

## If something's off

- **Blank / "no time groups" page** — event had < 10 clusters; grouping is skipped
  by design.
- **Only one group** — you ran without `--bkgDir`; that's expected, signal only.
- **Nothing plots** — the plotter runs *after* `SVDTimeGrouping`; the steering
  already wires that up. Don't reorder it.

---

<details>
<summary>The rest (only if you care)</summary>

The module `SVDTimeGroupingPlotter` runs after `SVDTimeGrouping`. Each event it
rebuilds the exact histogram the algorithm fitted — reusing that module's own
shaping helpers and the per-group `(integral, center, sigma)` stamped onto every
`SVDCluster` — then overlays each group's Gaussian and appends a PDF page.

Layout:

```
basf2/                                    local basf2 analysis dir
  setup.sh
  svd/modules/SVDTimeGroupingPlotter/     the C++ module (include/ src/ SConscript)
scripts/plot_timegroups.py                simulate -> cluster -> group -> plot
plots/                                    output PDFs
```

Extra module params: `useFullRange` (default `True`; set `False` to crop the
x-axis to the populated span), `maxPages`, and histogram-shape knobs
(`tRangeLow/High`, `rebinningFactor`, `fillSigmaN`) kept identical to
`SVDTimeGrouping`.

The steering runs grouping with `useParamFromDB=False` so grouping and plotting
share the same compiled resolutions — that's what makes the overlay exact. Run
grouping from DB payloads instead and it's close but not bin-identical.
</details>
