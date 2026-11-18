# Evidence: the commands and their real output

**Reader:** people who want to check a number of this guide or repeat a command. Reviewed 2026-11-17.

Back to the [guide index](./index.md).

**In short:** every number in this guide comes from a command that was run on two real recordings, or from a formula of the
code evaluated by hand with `jq`. This page keeps each command with its literal output so you can repeat it. Where a tool
could not be run, the page says so.

Collected on 2026-11-16 on an Apple silicon Mac. All commands only read. The runs folder is `perf-runs/` of the clone (local, ignored, not published; it holds the two runs below, and E3 runs from inside it). The session could run `rg`, `sed`, `jq` and `awk`, not Python or `xctrace`: no tool of this guide was run, and E3, E6 and E7 are the code's formulas evaluated by hand. What was not reproduced is in [Known limits](./limits.md#what-was-not-reproduced).

## E1 The tables, workers, thresholds and error messages {#e1}

```text
$ rg -n '^MEMORY =|^TABLES =|^OPTIONAL =|^COUNTER_TABLES =|^EXPORT_WORKERS =|^STUTTER_FLOOR_MS =|^UNPRESENTED_' src/metal_gpu_trace/perf_report.py | cut -c1-120
34:TABLES = ("metal-gpu-intervals", MEMORY, "gpu-performance-state-intervals")
36:OPTIONAL = ("metal-application-encoders-list", "graphics-compiler-activity-intervals", "device-thermal-state-interval
40:EXPORT_WORKERS = 2
42:COUNTER_TABLES = ("gpu-counter-info", "gpu-counter-value")
201:UNPRESENTED_MIN_BUFFERS = 32
202:UNPRESENTED_FACTOR = 8
203:UNPRESENTED_MIN_S = 1.0
250:STUTTER_FLOOR_MS = 8.0
$ rg -n 'raise ValueError|sys.exit|raise RuntimeError|raise FileNotFoundError' src/metal_gpu_trace/perf_report.py | cut -c1-170
53:        raise FileNotFoundError(f"no recording at {pathlib.Path(trace).name}: perf_record.sh deletes the .trace once "
65:        raise RuntimeError(f"xctrace export of {pathlib.Path(trace).name} failed (exit {proc.returncode}): {reason}")
195:        raise ValueError("the trace has no metal-gpu-intervals table; this Xcode may name it differently: "
645:        raise ValueError("the trace has no launched or attached process; record it with xctrace --launch or --attach")
851:        sys.exit(str(error))
```

Only these four conditions have a sentence; the `except` at line 850 catches exactly those three kinds. Anything else escapes `main` as a traceback ([limit 4](./limits.md)). The first output is trimmed (… line 33, `MEMORY = "metal-current-allocated-size"`, omitted).

## E2 The `gpu` block of the two real summaries {#e2}

```text
$ jq -c '.gpu | del(.per_channel_ms)' a2-proof-first_20261115-085621.json
{"intervals":6269,"frames":2045,"frame_gpu_ms":{"count":2045,"mean":5.937,"p50":6.008,"p95":6.213,"max":13.561},"frame_interval_ms":{"count":2044,"mean":9.587,"p50":9.485,"p95":10.098,"max":36.335},"fps_estimate":105.4,"fps_1pct_low":96.2,"fps_01pct_low":48.2,"stutter_rate_pct":0.29,"frame_jitter_ms":0.817,"throttling_analysis":{"thermal_throttling_detected":false,"fps_initial":103.0,"fps_final":105.8,"fps_drift_pct":-2.7}}
$ jq -c '.gpu | del(.per_channel_ms)' a2-proof-second_20261115-085735.json
{"intervals":548,"frames":153,"frame_gpu_ms":{"count":153,"mean":5.86,"p50":6.058,"p95":6.798,"max":13.704},"frame_interval_ms":{"count":152,"mean":15.286,"p50":9.795,"p95":11.982,"max":798.956},"fps_estimate":102.1,"unpresented":{"frames":[160],"from_s":3.637,"span_s":17.236,"command_buffers":1776,"gpu_ms":10358.288,"share_of_gpu_time":0.92},"fps_1pct_low":40.8,"fps_01pct_low":null,"stutter_rate_pct":2.63,"frame_jitter_ms":63.799,"throttling_analysis":{"thermal_throttling_detected":false,"fps_initial":100.6,"fps_final":100.8,"fps_drift_pct":-0.2}}
```

## E3 Recomputing the numbers from `frames.csv` {#e3}

The table has one row per frame: `frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total` (the [data guide](../data-and-lifecycle/files-on-disk.md#the-tables-and-the-samplers)). The gaps are the differences of `start_ms` (positive only); the formulas are those of [How each number is computed](./how-numbers-are-computed.md).

```text
$ tail -n +2 a2-proof-first_20261115-085621.frames.csv | awk -F, 'NR>1{g=$2-p; if(g>0) print g} {p=$2}' | sort -n | awk '{a[NR]=$1; s+=$1; q+=$1*$1} END{n=NR; med=(n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2; lim=1.5*med; if(lim<8)lim=8; for(k=1;k<=n;k++) if(a[k]>lim) c++; i=int(n*0.99); if(i>n-1)i=n-1; j=int(n*0.999); if(j>n-1)j=n-1; m=s/n; sd=sqrt(q/n-m*m); printf "n=%d median=%.4f fps=%.1f low1=%.1f low01=%.1f limit=%.3f over=%d stutter=%.2f jitter=%.3f max=%.3f\n", n, med, 1000/med, 1000/a[i+1], 1000/a[j+1], lim, c, c/n*100, sd, a[n]}'
n=2044 median=9.4845 fps=105.4 low1=96.2 low01=48.2 limit=14.227 over=6 stutter=0.29 jitter=0.817 max=36.335
$ tail -n +2 a2-proof-first_20261115-085621.frames.csv | awk -F, '{s+=$6; n++} END{printf "frames=%d gpu_ms_mean=%.3f\n", n, s/n}'
frames=2045 gpu_ms_mean=5.937
$ tail -n +2 a2-proof-second_20261115-085735.frames.csv | awk -F, 'NR>1{g=$2-p; if(g>0) print g} {p=$2}' | sort -n | awk '{a[NR]=$1; s+=$1; q+=$1*$1} END{n=NR; med=(n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2; lim=1.5*med; if(lim<8)lim=8; for(k=1;k<=n;k++) if(a[k]>lim) c++; i=int(n*0.99); if(i>n-1)i=n-1; j=int(n*0.999); if(j>n-1)j=n-1; m=s/n; sd=sqrt(q/n-m*m); printf "n=%d median=%.4f fps=%.1f low1=%.1f low01(n<1000: null)=%.1f limit=%.3f over=%d stutter=%.2f jitter=%.3f max=%.3f\n", n, med, 1000/med, 1000/a[i+1], 1000/a[j+1], lim, c, c/n*100, sd, a[n]}'
n=152 median=9.7935 fps=102.1 low1=40.8 low01(n<1000: null)=1.3 limit=14.690 over=4 stutter=2.63 jitter=63.799 max=798.956
$ tail -n +2 a2-proof-second_20261115-085735.frames.csv | awk -F, '{s+=$6; n++} END{printf "frames=%d gpu_ms_mean=%.3f\n", n, s/n}'
frames=153 gpu_ms_mean=5.860
```

Against E2, every published number matches: FPS 105.4 and 102.1, 1 % low 96.2 and 40.8, 0.1 % low 48.2 and `null` for the second (152 gaps are under 1000, so the `1.3` the script prints is what the rule throws away), stutter 0.29 and 2.63, jitter 0.817 and 63.799, frames 2045 and 153, mean GPU ms 5.937 and 5.860 (5.86 in the summary). The hitch threshold is 14.227 and 14.690 here (14.691 in the summary: it used nanosecond starts, the table keeps 0.001 ms). `frame_interval_ms.p50` is 9.485 and 9.795 against the true medians 9.4845 and 9.7935, by design ([fps_estimate](./how-numbers-are-computed.md#fps_estimate)). The summaries come from an older version than the formulas used, so this checks the formulas on old data ([limit 1](./limits.md)).

## E4 The hitch blocks {#e4}

```text
$ jq -c '{missing_tables, hitches: (.hitches | del(.worst))}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"missing_tables":[],"hitches":{"count":6,"per_minute":18.37,"threshold_ms":14.227,"causes":{"cpu_or_wait":5,"memory_growth":1}}}
{"missing_tables":[],"hitches":{"count":4,"per_minute":103.3,"threshold_ms":14.691,"causes":{"cpu_or_wait":3,"memory_growth":1}}}
$ jq -c '.hitches.worst[0:2]' a2-proof-second_20261115-085735.json
[{"frame":159,"interval_ms":798.956,"cause":"cpu_or_wait","window_ms":[2825.46,3624.416],"cpu_pct":4.8},{"frame":23,"interval_ms":24.502,"cause":"cpu_or_wait","window_ms":[1465.036,1489.538],"cpu_pct":95.0}]
```

`count` is 6 and 4, equal to the "over" counts of E3 (hitches and stutter share their limit), and `missing_tables` is `[]` in both: every table was there. `per_minute` 103.3 for 4 hitches means a 2.32 s span, the presented part of a 20.9 s run (`duration_s` is 20.87). The worst hitch of the second run is the 799 ms gap that ends the presented part, with the program at 4.8 % CPU: it was waiting, which fits a hidden window (**speculation**: why the window was hidden is not in the data).

## E5 The `unpresented` block, from E2 {#e5}

The second run's `gpu.unpresented` (E2) has 1776 command buffers over 17.236 s; the rule needs at least `max(32, 8 × median)` and 1 s (`perf_report.py:220-222`), so it is met by a wide margin. The run's `intervals` are 548 and its `frames` 153: the work left out is not in them. The reading "the window was hidden at 3.6 s" is **speculation**.

## E6 `perf_compare` and `perf_check`, evaluated by hand {#e6}

The two functions were **not run**: these are their formulas (`change`, `analysis.py:392-396`; `judge`, `:317-330`) applied with `jq`, `a` the first run and `b` the second:

```text
$ jq -n --slurpfile a a2-proof-first_20261115-085621.json --slurpfile b a2-proof-second_20261115-085735.json 'def ch(x;y): {a:x,b:y,change:((y-x)*1000|round/1000),change_pct:(if x==0 then null else ((100*(y-x)/x)*10|round/10) end)}; ($a[0]) as $A | ($b[0]) as $B | {fps:ch($A.gpu.fps_estimate;$B.gpu.fps_estimate), fps_1pct_low:ch($A.gpu.fps_1pct_low;$B.gpu.fps_1pct_low), stutter_rate_pct:ch($A.gpu.stutter_rate_pct;$B.gpu.stutter_rate_pct), frame_jitter_ms:ch($A.gpu.frame_jitter_ms;$B.gpu.frame_jitter_ms), gpu_ms_mean:ch($A.gpu.frame_gpu_ms.mean;$B.gpu.frame_gpu_ms.mean), metal_mib_peak:ch($A.metal_memory_mib.peak;$B.metal_memory_mib.peak), too_short:[], unpresented_runs:["b"]}' -c
{"fps":{"a":105.4,"b":102.1,"change":-3.3,"change_pct":-3.1},"fps_1pct_low":{"a":96.2,"b":40.8,"change":-55.4,"change_pct":-57.6},"stutter_rate_pct":{"a":0.29,"b":2.63,"change":2.34,"change_pct":806.9},"frame_jitter_ms":{"a":0.817,"b":63.799,"change":62.982,"change_pct":7708.9},"gpu_ms_mean":{"a":5.937,"b":5.86,"change":-0.077,"change_pct":-1.3},"metal_mib_peak":{"a":83.17,"b":94.38,"change":11.21,"change_pct":13.5},"too_short":[],"unpresented_runs":["b"]}
$ jq -n --slurpfile a a2-proof-first_20261115-085621.json --slurpfile b a2-proof-second_20261115-085735.json '($a[0].gpu.fps_estimate) as $lo | ($b[0].gpu.fps_estimate) as $v | {fps_floor_with_3pct_margin:($lo*0.97), run_fps:$v, verdict:(if $v < $lo*0.97 then "worse" else "same" end), gpu_ms_ceiling:($a[0].gpu.frame_gpu_ms.mean*1.03), run_gpu_ms:$b[0].gpu.frame_gpu_ms.mean}' -c
{"fps_floor_with_3pct_margin":102.238,"run_fps":102.1,"verdict":"worse","gpu_ms_ceiling":6.1151100000000005,"run_gpu_ms":5.86}
```

`perf_compare` would give the first block (plus an `unpresented` entry naming `b`, and no `too_short`: 153 is not under 100). For `perf_check` against a reference made only of the first run, FPS is under the floor (102.1 < 102.238), so the verdict would be `regressed`; GPU ms per frame (5.86 under 6.115) and the encoder counts (both runs have p50 2 and 1, from the summaries' `encoders`) are `same`. That reference has `spread_pct` 0: this is [limit 8](./limits.md) and why `perf_baseline` wants several runs. The results are **probable** (code read, not run). Measured before 53f742b, when `perf_check` had no `note`; since then this one-run case adds one (`analysis.py:378-380`), and the verdict does not change.

## E7 `missing_tables`, noise and diagnosis by hand {#e7}

```text
$ sed -n 128,132p tests/test_report.py
    assert perf_report.missing_tables(toc) == ["ProcessCPUUsage", "device-thermal-state-intervals", "gpu-performance-state-intervals",
                                               "graphics-compiler-activity-intervals", "graphics-compiler-spill-events",
                                               "metal-application-encoders-list",
                                               "metal-command-buffer-error", "metal-current-allocated-size",
                                               "metal-resource-allocations"]
$ jq -c '{label, stutter:.gpu.stutter_rate_pct, stutter_verdict:(if .gpu.stutter_rate_pct==null then "UNKNOWN" elif .gpu.stutter_rate_pct>7 then "SEVERE_STUTTER" elif .gpu.stutter_rate_pct>=2 then "MICRO_STUTTER" else "SMOOTH" end), idle_share:.gpu_idle.idle_share, high_variance:((.gpu.frame_jitter_ms>=3) or ((.gpu.frame_interval_ms.p95-.gpu.frame_interval_ms.p50)>=5)), working_set_mib:([.process_rss_mib.max,.metal_memory_mib.peak]|max), noisy_external_pct:((.gpu_activity.device_pct.mean - 100*(1-.gpu_idle.idle_share))*10|round/10)}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"label":"a2-proof-first_20261115-085621","stutter":0.29,"stutter_verdict":"SMOOTH","idle_share":0.381,"high_variance":false,"working_set_mib":237.312,"noisy_external_pct":-6.4}
{"label":"a2-proof-second_20261115-085735","stutter":2.63,"stutter_verdict":"MICRO_STUTTER","idle_share":0.425,"high_variance":true,"working_set_mib":238.672,"noisy_external_pct":0.6}
$ jq -c '{label,hitches:.hitches.count,shader_compile:(.hitches.causes.shader_compile // 0),compiler_busy_ms:.graphics_compiler.busy_ms}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"label":"a2-proof-first_20261115-085621","hitches":6,"shader_compile":0,"compiler_busy_ms":0.227}
{"label":"a2-proof-second_20261115-085735","hitches":4,"shader_compile":0,"compiler_busy_ms":0.292}
```

The first block is the whole assertion of `missing_tables` for a trace holding only the GPU intervals: nine names, sorted. The second applies the thresholds of `perf_diagnose` and `noisy_environment` by hand: `SMOOTH` and `MICRO_STUTTER`, variance high only in the second, a working set far under 1500 MiB, idle shares 0.381 and 0.425 (both over 0.25: `CPU_SUBMISSION_BOUND` by the rule, **probable**, tool not run), and a GPU-use difference of -6.4 and 0.6 points, far from the 20 that flags noise. The third is the input to `cold_warm_report`: no `shader_compile` hitch in either run, so `first_seen_hitches` would be 0 and `extra_hitches_in_first` `max(0, 6 - 4)` = 2.

## E8 The limits the code enforces {#e8}

```text
$ rg -n "1 <= count|1 <= rounds|2 <= len\(values\)|> 24|<= seconds <= 600|<= skip <= 600|ok = value|margin = 0 if" src/metal_gpu_trace/experiments.py src/metal_gpu_trace/analysis.py src/metal_gpu_trace/paths.py | cut -c1-190
src/metal_gpu_trace/experiments.py:20:    if not 1 <= count <= 10:
src/metal_gpu_trace/experiments.py:60:    if not 1 <= rounds <= 5:
src/metal_gpu_trace/experiments.py:124:    if not isinstance(values, list) or not 2 <= len(values) <= 8:
src/metal_gpu_trace/experiments.py:153:    if not 1 <= rounds <= 5:
src/metal_gpu_trace/experiments.py:156:    if len(values) * rounds > 24:
src/metal_gpu_trace/paths.py:113:    if not 0 <= seconds <= 600:  # a NaN is false here too
src/metal_gpu_trace/paths.py:124:    if not 0 <= skip <= 600:
src/metal_gpu_trace/analysis.py:325:    margin = 0 if metric.endswith("_p50") else margin_pct / 100
src/metal_gpu_trace/analysis.py:490:        ok = value is not None and (value >= limit if kind == "min" else value <= limit)
```

## E9 Power at both ends, a real 30-second recording {#e9}

The command that made the recording is **not given** for this page, so its evidence is pending. The output is what the session
gave, copied as it was. It is the `power` block of `machine` in the summary; see [Power and heat](./power-and-heat.md).

```text
evidence pending: the command that made the 30-second recording (not given)
"power": {"start": {"low_power_mode": false, "thermal_warning": false}, "end": {"low_power_mode": false, "thermal_warning": false}, "changed": false}
```

## E10 The graphics compiler's durations, a real 20-second recording {#e10}

Command: **not given**, evidence pending. The output shows the compiler block of the summary as the session gave it.
Not given: `duration_ms.count` and `duration_ms.mean` (so they are not shown here), and no run of `command_buffer_errors`
for this page.

```text
evidence pending: the command that made the 20-second recording (not given)
graphics_compiler: intervals 4, busy_ms 0.255, duration_ms p50 0.086, p95 0.088, max 0.088
```
