#!/bin/zsh
# Records a Wine or macOS program with Metal System Trace into $PERF_OUT, keeping the newest KEEP_RUNS runs.
# Usage: [PERF_OUT=dir] [KEEP_TRACE=1] [KEEP_RUNS=N] perf_record.sh <label> <seconds> <wine dir|native> <prefix> <working dir> <program> [args...]
#    or: perf_record.sh <label> <seconds> attach - - <pid|name>   (records a running program, left running afterwards)
set -euo pipefail

here=${0:A:h}
label=$1 seconds=$2 wine=$3 prefix=$4 workdir=$5
shift 5
[[ $label =~ '^[A-Za-z0-9._-]+$' ]] || { echo "label may hold only letters, digits, '.', '_' and '-'" >&2; exit 2; }
[[ $seconds == <1-3600> ]] || { echo "seconds must be 1 to 3600" >&2; exit 2; }
[[ $wine == (native|attach) || -x $wine/bin/wine ]] || { echo "no Wine at $wine/bin/wine (or pass native or attach)" >&2; exit 2; }
if [[ $wine == attach ]]; then
  pid=$1
  # a name matches the newest process whose command line holds it, such as Game.exe under Wine
  [[ $pid == <-> ]] || pid=$(ps -axo pid=,command= | awk -v name="$1" 'index($0, name) && !/xctrace|awk|zsh|perf_record|ps -axo/ {p = $1} END {print p}')
  [[ -n $pid ]] && kill -0 $pid 2>/dev/null || { echo "no running process matches $1" >&2; exit 2; }
fi
name=${label}_$(date +%Y%m%d-%H%M%S)
# default: logs/perf beside the script's directory when it exists, else ./perf-runs
out=${PERF_OUT:-${here:h}/logs/perf}
[[ -n ${PERF_OUT:-} || -d $out ]] || out=$PWD/perf-runs
mkdir -p $out

# one recording at a time: two programs sharing the GPU spoil both measurements
lock=$out/.recording
mkdir $lock 2>/dev/null || { echo "another recording is running ($lock); remove it if none is" >&2; exit 3; }
trap 'rmdir $lock 2>/dev/null' EXIT

[[ $wine == attach ]] || cd $workdir
# the resident memory of the program's Wine process, once a second, while Instruments records
exe=${1:t}
(
  echo "time_s,rss_kib" > $out/$name.rss.csv
  for ((t = 0; t <= seconds + 5; t++)); do
    if [[ $wine == attach ]]; then
      rss=$(ps -o rss= -p $pid | awk '{print $1 + 0}')
    else
      rss=$(ps -axo rss=,command= | awk -v exe="$exe" 'index($0, exe) && !/xctrace|awk|zsh|perf_record|ps -axo/ {sum += $1} END {print sum + 0}')
    fi
    echo "$t,$rss" >> $out/$name.rss.csv
    sleep 1
  done
) &
sampler=$!
# PERF_ENV="NAME=VALUE ..." sets the program's variables (MULLION_DIAG=profile labels Mullion's encoders)
extra=()
for pair in ${=PERF_ENV:-}; do extra+=(--env $pair); done
# PERF_INSTRUMENTS="Time Profiler;Metal GPU Counters" adds Instruments to the Metal System Trace template
for instrument in ${(s:;:)PERF_INSTRUMENTS:-}; do extra+=(--instrument $instrument); done
if [[ $wine == attach ]]; then
  xcrun xctrace record --template "Metal System Trace" --time-limit ${seconds}s --output $out/$name.trace \
    --attach $pid || true
elif [[ $wine == native ]]; then
  xcrun xctrace record --template "Metal System Trace" --time-limit ${seconds}s --output $out/$name.trace \
    $extra --launch -- "$@" || true
  pkill -x $exe || true
else
  # the caller's overrides (a Mullion built for system32 needs d3d12,...=n) come before Wine's own
  overrides="${WINEDLLOVERRIDES:+$WINEDLLOVERRIDES;}mscoree=;mshtml="
  xcrun xctrace record --template "Metal System Trace" --time-limit ${seconds}s --output $out/$name.trace \
    --env WINEPREFIX=$prefix --env WINEDEBUG=-all --env "WINEDLLOVERRIDES=$overrides" $extra \
    --launch -- $wine/bin/wine "$@" || true
  # the program outlives the recording; stop what is left of its Wine
  WINEPREFIX=$prefix $wine/bin/wineserver -k || true
fi
kill $sampler 2>/dev/null || true
[ -d $out/$name.trace ] || { echo "no recording at $out/$name.trace" >&2; exit 1; }

python3 -I $here/perf_report.py $out/$name.trace --label $name --out $out
# the .trace goes once its numbers are in the .json; KEEP_TRACE=1 keeps it for trace_tables, trace_query or Instruments
[[ ${KEEP_TRACE:-0} == 1 ]] || rm -rf $out/$name.trace
if [[ ${KEEP_RUNS:-} == <1-> ]]; then
  for old in $out/*.json(N.om[$((KEEP_RUNS + 1)),-1]); do rm -rf ${old:r}.*(N); done
fi
