#!/usr/bin/env python3
"""
Per-event SVD time-grouping plots (simulation)
==============================================
Simulates a few events, runs SVD clustering + the production SVDTimeGrouping
module, then the local SVDTimeGroupingPlotter, which writes ONE PDF page per
event: the cluster-time histogram the grouping algorithm fitted, overlaid with
the fitted per-group Gaussians.

The grouping module is run with forceGroupingFromDB=False / useParamFromDB=False
so it uses its compiled default parameters -- the exact same values the plotter
uses to rebuild the histogram, so the overlay is faithful.

Usage (from the project root, after `source basf2/setup.sh` and `scons`):
  basf2 scripts/plot_timegroups.py -- [--numEvents 10] [--seed 42] \
        [--bkgDir <dir-with-BGOverlay-root>] [--groups 0 1 2] \
        [--output plots/svd_timegroups.pdf]

Output:
  plots/svd_timegroups.pdf   (one page per event)
"""

import os
import glob
import argparse

import basf2 as b2
import generators as ge
import simulation as sim

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--numEvents', type=int, default=10,
                    help='Number of events to simulate/plot (default 10).')
parser.add_argument('--seed', default='42', help='Random seed (default 42).')
parser.add_argument('--runNum', type=int, default=1, help='Run number (default 1).')
parser.add_argument('--process', choices=['mixed', 'mumu'], default='mixed',
                    help="Generator: 'mixed' = Y(4S)->BB (default), 'mumu' = e+e- -> mu+mu-.")
parser.add_argument('--bkgDir', default=None,
                    help='Directory of BGOverlay ROOT files. If given, beam background is '
                         'overlaid -- this is what produces the out-of-time groups the '
                         'algorithm is designed to separate. Default: no overlay.')
parser.add_argument('--groups', type=int, nargs='*', default=None,
                    help='Group ids to overlay (e.g. --groups 0 1 2). Default: all groups. '
                         'Group 0 is the most signal-like after the grouping sort.')
parser.add_argument('--output', default='plots/svd_timegroups.pdf',
                    help='Output PDF path (default plots/svd_timegroups.pdf).')
args = parser.parse_args()

b2.set_random_seed(args.seed)
b2.set_log_level(b2.LogLevel.INFO)

os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

main = b2.create_path()

# ---------------------------------------------------------------------------
# Event source + generator
# ---------------------------------------------------------------------------
main.add_module('EventInfoSetter',
                evtNumList=[args.numEvents], runList=[args.runNum], expList=[0])
main.add_module('Gearbox')
main.add_module('Geometry')
if args.process == 'mumu':
    ge.add_kkmc_generator(main, finalstate='mu-mu+')
else:
    ge.add_evtgen_generator(main, finalstate='mixed')

# ---------------------------------------------------------------------------
# Beam-background overlay (optional)
# ---------------------------------------------------------------------------
bg = None
if args.bkgDir:
    bg = sorted(glob.glob(os.path.join(args.bkgDir, '*.root')))
    if not bg:
        b2.B2FATAL(f'No BGOverlay files found in {args.bkgDir}/')
    b2.B2INFO(f'BGOverlay files ({len(bg)}): {bg}')

# ---------------------------------------------------------------------------
# Simulation + digitisation
# ---------------------------------------------------------------------------
sim.add_simulation(main, bkgfiles=bg)

# ---------------------------------------------------------------------------
# SVD clustering + time grouping (compiled defaults, so the plot is faithful)
# ---------------------------------------------------------------------------
main.add_module('SVDClusterizer')
main.add_module('SVDTimeGrouping',
                forceGroupingFromDB=False,
                useParamFromDB=False,
                isEnabledIn6Samples=True,
                isEnabledIn3Samples=True)

# ---------------------------------------------------------------------------
# The plotter: one PDF page per event
# ---------------------------------------------------------------------------
plotter = {
    'outputFileName': args.output,
}
if args.groups is not None:
    plotter['groupsToPlot'] = args.groups
main.add_module('SVDTimeGroupingPlotter', **plotter)

main.add_module('Progress')
b2.print_path(main)
b2.process(main)
print(b2.statistics)
