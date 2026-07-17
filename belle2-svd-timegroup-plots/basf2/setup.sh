#!/bin/bash
# Local analysis directory setup for svd-time-groupwise-tracking.
#
# Usage (from the basf2/ subdirectory of this project):
#   source setup.sh
#
# After sourcing:
#   scons        — compile local C++ modules
#   basf2 ...    — run steering scripts

prevdir="$(pwd)"

_TOOLS_DIR="/media/surya/Surya_NVME_1/products/belle2-public/tools"
_BASF2_DIR="/media/surya/Surya_NVME_1/products/belle2-public/basf2"

source "${_TOOLS_DIR}/b2setup" 2>/dev/null
cd "${_BASF2_DIR}" && b2setup 2>/dev/null
cd "$prevdir"

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
