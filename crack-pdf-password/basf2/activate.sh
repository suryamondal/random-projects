#!/bin/bash

prevdir="$(pwd)"

cd /home/surya/products/belle2-public/basf2
source /home/surya/products/belle2-public/tools/b2setup

cd "$prevdir"

b2dir="$BELLE2_RELEASE_DIR"
[[ -n "$b2dir" ]] || b2dir="$BELLE2_LOCAL_DIR"

[[ -e site_scons ]] || ln -s "$b2dir/site_scons"
[[ -e SConstruct ]] || ln -s site_scons/SConstruct

export BELLE2_ANALYSIS_DIR="$(pwd)"
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$(pwd)/lib/Linux_x86_64/opt"
export PATH="$PATH:$(pwd)/bin/Linux_x86_64/opt"
export PYTHONPATH="$PYTHONPATH:$(pwd)/lib/Linux_x86_64/opt"
export ROOT_INCLUDE_PATH="$ROOT_INCLUDE_PATH:$(pwd)/include"
export BELLE2_RELEASE_DIR="$b2dir"
