#!/bin/bash
# ============================================================================
# >>> THIS setup.sh IS FOR A LOCAL basf2 INSTALLATION ONLY. <<<
# If you use a CVMFS release instead, this script MUST be changed: replace the
# _TOOLS_DIR / _BASF2_DIR paths below with `source /cvmfs/belle2.cern.ch/tools/b2setup`
# and `b2setup <release>` (drop the local `cd`/b2setup lines).
# ============================================================================
#
# Local analysis directory setup.
#
# Usage (from the basf2/ subdirectory of this project):
#   source setup.sh
#
# After sourcing:
#   scons        — compile local C++ modules
#   basf2 ...    — run steering scripts

prevdir="$(pwd)"

# ===== OPTION A: LOCAL basf2 install (active) ===============================
# Edit the two paths to point at your local tools/basf2, then source below.
_TOOLS_DIR="/media/surya/Surya_NVME_1/products/belle2-public/tools"
_BASF2_DIR="/media/surya/Surya_NVME_1/products/belle2-public/basf2"
source "${_TOOLS_DIR}/b2setup" 2>/dev/null
cd "${_BASF2_DIR}" && b2setup 2>/dev/null
cd "$prevdir"

# ===== OPTION B: CVMFS release ==============================================
# To use a CVMFS release instead, comment out OPTION A above and uncomment the
# two lines below (pick the release you need, e.g. release-09-00-11):
#
# source /cvmfs/belle2.cern.ch/tools/b2setup
# b2setup release-09-00-11
# ===========================================================================

b2dir="${BELLE2_RELEASE_DIR}"
[[ -n "$b2dir" ]] || b2dir="${BELLE2_LOCAL_DIR}"
[[ -n "$b2dir" ]] || b2dir="${_BASF2_DIR}"

[[ -e site_scons ]] || ln -s "${b2dir}/site_scons" site_scons
[[ -e SConstruct ]] || ln -s site_scons/SConstruct SConstruct

export BELLE2_ANALYSIS_DIR="$(pwd)"
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:$(pwd)/lib/Linux_x86_64/opt"
export PATH="${PATH}:$(pwd)/bin/Linux_x86_64/opt"
export PYTHONPATH="${PYTHONPATH}:$(pwd)/lib/Linux_x86_64/opt:$(pwd)/scripts"
export ROOT_INCLUDE_PATH="${ROOT_INCLUDE_PATH}:$(pwd)/include"
export BELLE2_RELEASE_DIR="${b2dir}"

echo "Local analysis dir: $(pwd)"
echo "basf2 release dir:  ${b2dir}"
echo "Run 'scons' to compile local modules."
