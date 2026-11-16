#!/bin/zsh
# Keeps the newest <keep> recordings in <folder>: removes every file of each older recording except its .trace, which
# only the disk quota frees (ADR-0006).
# baselines.json (the baselines) and panel.json (left by the removed panel of 0.24.0) are not recordings and are never removed.
# Usage: prune_runs.sh <folder> <keep>
set -euo pipefail
setopt extendedglob
out=$1 keep=$2
[[ $keep == <1-> ]] || { echo "keep must be a whole number of 1 or more: $keep" >&2; exit 2; }
for old in $out/(^(baselines|panel)).json(N.om[$((keep + 1)),-1]); do rm -rf ${old:r}.*~*.trace(N); done
