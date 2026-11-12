#!/bin/zsh
# Records a Wine or macOS program with Metal System Trace into $PERF_OUT, keeping the newest KEEP_RUNS runs.
# Usage: [PERF_OUT=dir] [KEEP_TRACE=1] [KEEP_RUNS=N] [PERF_MEMORY=0 skips the Metal memory table] perf_record.sh <label> <seconds> <wine dir|native> <prefix> <working dir> <program> [args...]
#    or: perf_record.sh <label> <seconds> attach - - <pid|name>   (records a running program, left running afterwards)
set -euo pipefail

here=${0:A:h}
label=$1 seconds=$2 wine=$3 prefix=$4 workdir=$5
shift 5
[[ $label =~ '^[A-Za-z0-9._-]+$' ]] || { echo "label may hold only letters, digits, '.', '_' and '-'" >&2; exit 2; }
[[ $seconds == <1-3600> ]] || { echo "seconds must be 1 to 3600" >&2; exit 2; }
[[ $wine == (native|attach) || -x $wine/bin/wine ]] || { echo "no Wine at $wine/bin/wine (or pass native or attach)" >&2; exit 2; }
[[ $wine != native || ( -f $1 && -x $1 ) ]] || { echo "${1:t} is not an executable file" >&2; exit 2; }
if [[ $wine == native ]]; then
  # a program starts with a Mach-O magic number (also ELF, for the Linux CI) or a #! line
  magic=$(head -c 4 $1 | od -An -tx1 | tr -d ' \n')
  [[ $magic == (cffaedfe|cefaedfe|feedface|feedfacf|cafebabe|bebafeca|7f454c46|2321*) ]] ||
    { echo "${1:t} is not a program the system can run (no Mach-O or #! header)" >&2; exit 2; }
fi
if [[ $wine == attach ]]; then
  pid=$1
  # a name matches the newest process whose command line holds it, such as Game.exe under Wine
  [[ $pid == <-> ]] || pid=$(ps -axo pid=,command= | awk -v name="$1" 'index($0, name) && !/xctrace|awk|zsh|perf_record|ps -axo/ {p = $1} END {print p}')
  [[ -n $pid ]] && kill -0 $pid 2>/dev/null || { echo "no running process matches $1" >&2; exit 2; }
fi
name=${label}_$(date +%Y%m%d-%H%M%S)
# default: logs/perf beside the clone (the script is in <clone>/src/metal_gpu_trace) when it exists, else ./perf-runs
out=${PERF_OUT:-${here:h:h:h}/logs/perf}
[[ -n ${PERF_OUT:-} || -d $out ]] || out=$PWD/perf-runs
mkdir -p $out
tmp=${TMPDIR:-/tmp}

# Instruments' temporary files peak at about 0.8 GB per recorded second (48 GB measured for 60 s of Wine D3D12)
need=$(( ${PERF_MIN_FREE_GB:-2 + (seconds * 8 + 9) / 10} ))
for dir in $tmp $out; do
  free=$(( $(df -k $dir | awk 'NR == 2 {print $4}') / 1048576 ))
  (( free >= need )) || { echo "not enough free disk on $dir: $free GB free, $need GB needed (PERF_MIN_FREE_GB overrides)" >&2; exit 4; }
done

# one recording at a time: two programs sharing the GPU spoil both measurements
lock=$out/.recording
mkdir $lock 2>/dev/null || { echo "another recording is running ($lock); remove it if none is" >&2; exit 3; }
before=(${tmp%/}/instruments*.ktrace(N))
# Frees the lock and the temporary .ktrace files that xctrace left in $TMPDIR during this run.
cleanup() {
  local rc=$?
  kill ${watchdog:-} ${sampler:-} 2>/dev/null || true
  rmdir $lock 2>/dev/null
  for k in ${tmp%/}/instruments*.ktrace(N); do (( ${before[(Ie)$k]} )) || rm -rf $k; done
  # a failed recording leaves no partial files behind
  if (( rc )); then rm -rf $out/$name.*(N); fi
}
trap cleanup EXIT
trap 'rm -rf $out/$name.*(N); exit 143' TERM

[[ $wine == attach ]] || cd $workdir
# the resident memory of the program's Wine process, once a second, while Instruments records
exe=${1:t}
# stops the program by name: SIGTERM, then SIGKILL for one that ignores it
stop_program() { pkill -x $exe && { sleep 1; pgrep -x $exe >/dev/null && pkill -KILL -x $exe; }; return 0 }
# PERF_PARENT_PID is the server that started this recording: when it dies the recording and its program are stopped
if [[ -n ${PERF_PARENT_PID:-} ]]; then
  (
    while kill -0 $PERF_PARENT_PID 2>/dev/null; do sleep 1; done
    if [[ $wine == native ]]; then stop_program
    elif [[ $wine != attach ]]; then WINEPREFIX=$prefix $wine/bin/wineserver -k
    fi
    pkill -TERM -P $$ -f 'xctrace|perf_report'
    kill -TERM $$
  ) &
  watchdog=$!
fi
# one line of the AGX driver's counters (whole GPU): device, renderer and tiler utilization, split scenes, recoveries, MiB in use
agx_sample() {
  local raw line key values=()
  raw=$(ioreg -c AGXAccelerator -r -d 1 2>/dev/null) || true
  line=${${(f)raw}[(r)*PerformanceStatistics*]}
  for key in 'Device Utilization %' 'Renderer Utilization %' 'Tiler Utilization %' SplitSceneCount recoveryCount 'In use system memory'; do
    if [[ $line =~ "\"$key\"=([0-9]+)" ]]; then values+=($match[1]); else values+=(""); fi
  done
  [[ -n $values[6] ]] && values[6]=$((values[6] / 1048576))
  print -r -- ${(j:,:)values}
}
(
  echo "time_s,rss_kib" > $out/$name.rss.csv
  echo "time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib" > $out/$name.agx.csv
  for ((t = 0; t <= seconds + 5; t++)); do
    if [[ $wine == attach ]]; then
      rss=$(ps -o rss= -p $pid | awk '{print $1 + 0}')
    else
      rss=$(ps -axo rss=,command= | awk -v exe="$exe" 'index($0, exe) && !/xctrace|awk|zsh|perf_record|ps -axo/ {sum += $1} END {print sum + 0}')
    fi
    echo "$t,$rss" >> $out/$name.rss.csv
    echo "$t,$(agx_sample)" >> $out/$name.agx.csv
    sleep 1
  done
) &
sampler=$!
# PERF_ENV="NAME=VALUE ..." sets the program's variables (MULLION_DIAG=profile labels Mullion's encoders)
extra=()
for pair in ${=PERF_ENV:-}; do extra+=(--env $pair); done
# PERF_PREFIX="/usr/sbin/taskpolicy -b" runs the program under that command (an absolute path: xctrace needs one)
launcher=(${=PERF_PREFIX:-})
# PERF_INSTRUMENTS="Time Profiler;Metal GPU Counters" adds Instruments to the Metal System Trace template
for instrument in ${(s:;:)PERF_INSTRUMENTS:-}; do extra+=(--instrument $instrument); done
# with Metal validation on, the program's output (where the layers report) is kept in $name.validation.log for the summary
validate=0 dyld=0
for pair in ${=PERF_ENV:-}; do
  [[ $pair == (MTL_SHADER_VALIDATION|MTL_DEBUG_LAYER)=[^0]* ]] && validate=1
  [[ $pair == DYLD_* ]] && dyld=1
done
if (( validate && ! dyld )) && [[ $wine != attach ]]; then
  extra+=(--env MTL_SHADER_VALIDATION_REPORT_TO_STDERR=1 --target-stdout $out/$name.validation.log)
  launcher=(/bin/sh -c 'exec "$@" 2>&1' sh $launcher)
elif (( validate && dyld )); then
  # /bin/sh is protected by SIP and drops DYLD_* variables before the program starts
  echo "validation messages are not kept: a DYLD_ variable would not reach the program through the shell that collects them" >&2
fi
if [[ $wine == attach ]]; then
  xcrun xctrace record --template "Metal System Trace" --time-limit ${seconds}s --output $out/$name.trace \
    --attach $pid || true
elif [[ $wine == native ]]; then
  xcrun xctrace record --template "Metal System Trace" --time-limit ${seconds}s --output $out/$name.trace \
    $extra --launch -- $launcher "$@" || true
  stop_program
else
  # the caller's overrides (a Mullion built for system32 needs d3d12,...=n) come before Wine's own
  overrides="${WINEDLLOVERRIDES:+$WINEDLLOVERRIDES;}mscoree=;mshtml="
  xcrun xctrace record --template "Metal System Trace" --time-limit ${seconds}s --output $out/$name.trace \
    --env WINEPREFIX=$prefix --env WINEDEBUG=-all --env "WINEDLLOVERRIDES=$overrides" $extra \
    --launch -- $launcher $wine/bin/wine "$@" || true
  # the program outlives the recording; stop what is left of its Wine
  WINEPREFIX=$prefix $wine/bin/wineserver -k || true
fi
kill $sampler 2>/dev/null || true
[ -d $out/$name.trace ] || { echo "no recording at $out/$name.trace" >&2; exit 1; }

report=(--label $name --out $out)
[[ ${PERF_MEMORY:-1} == 0 ]] && report+=(--no-memory)
python3 -I $here/perf_report.py $out/$name.trace $report
rm -f $out/$name.validation.log
# the .trace goes once its numbers are in the .json; KEEP_TRACE=1 keeps it for trace_tables, trace_query or Instruments
[[ ${KEEP_TRACE:-0} == 1 ]] || rm -rf $out/$name.trace
if [[ ${KEEP_RUNS:-} == <1-> ]]; then
  for old in $out/*.json(N.om[$((KEEP_RUNS + 1)),-1]); do rm -rf ${old:r}.*(N); done
fi
