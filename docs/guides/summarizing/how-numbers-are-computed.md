# How each number is computed

**Reader:** people who see a number in a summary and ask where it comes from, or who change `perf_report.py` or `metrics.py`. Reviewed 2026-11-16.

Español: [Cómo se calcula cada número](../../es/guides/resumir-y-analizar/como-se-calculan-los-numeros.md)

**In short:** most numbers come from one list: how many milliseconds pass between the start of one frame and the start of
the next. The "FPS" is the typical gap turned upside down, a "stutter" is a gap much longer than usual, and a "hitch" is
the same slow gap with a guess at its cause. This page gives each formula and the line of code that holds it.

Back to the [guide index](./index.md).

Example first: in the first run of the guide's example, the median gap is 9.4845 ms, so `1000 / 9.4845 = 105.4` FPS; 6 of 2044 gaps are over 14.227 ms, so the stutter rate is 0.29 % ([E3](./evidence.md#e3)). Everything here is **confirmed** by the line given. "The gaps" are the intervals between the first start of consecutive **presented** frames, in ms; "the totals" are the GPU ms of each frame, summed over its channels.

| Key | Formula | Line |
|---|---|---|
| the gaps | for each pair of consecutive frame numbers `a < b`: `first_start[b] - first_start[a]`, kept only if positive and if no unpresented frame lies between them | `perf_report.py:233-245` |
| the totals | per frame: the sum of `duration / 1e6` of its intervals | `:685`, `:705` |
| `gpu.frames`, `frame_gpu_ms`, `frame_interval_ms` | the number of frames kept; `stats(totals)`, `stats(gaps)` | `:711`, `:712`, `:714` |
| `stats` | `count`, `mean` (3 decimals), `p50 = ordered[n // 2]`, `p95 = ordered[min(n-1, int(n × 0.95))]`, `max` | `metrics.py:75-86` |
| `gpu.fps_estimate` | `round(1000 / median(gaps), 1)`, `None` without gaps | `perf_report.py:718` |
| `gpu.fps_1pct_low`, `fps_01pct_low` | `1000 / ordered_gaps[min(n-1, int(n × 0.99))]` with at least 100 gaps; the same with `0.999` and at least 1000 gaps | `:262-266` |
| `gpu.stutter_rate_pct` | `100 × (gaps > max(1.5 × median, 8.0 ms)) / n`, two decimals; needs at least 2 gaps | `:250`, `:267-268` |
| `gpu.frame_jitter_ms` | `pstdev(gaps)`, three decimals (population standard deviation) | `:269` |
| `gpu.throttling_analysis` | with at least 5 gaps: `k = max(1, int(n × 0.2))`; `fps_initial` and `fps_final` are `1000 / median` of the first and last `k` gaps; `drift = (initial - final) / initial × 100`; detected when the drop is over 10 % **and** the mean GPU ms of the last `k` frames is above the first `k` | `:270-279` |
| `hitches` | the same limit as stutter; each gap above it is one hitch, with a cause | `:283-320` |
| `gpu.start_latency_ms` | `stats` of the start latency of every row of the program that has one, without the unpresented frames | `:716-717` |
| `gpu_idle` | the GPU's idle time between the program's own intervals: per frame, gaps over 1 ms, and `idle_share = sum(gaps) / whole span` | `metrics.py:122-138` |
| `encoders` | encoders and command buffers per frame, each encoder's GPU time, the share shorter than 10, 25, 50, 100, 250, 500 and 1000 µs, the 20 labels with the most GPU time | `metrics.py:94-119` |
| `metal_memory_mib` | `peak`, `final`, `mean` of the program's samples; `trend_mib_per_min` is the least-squares slope over the second half of the time, with at least 5 samples and 5 s | `perf_report.py:731-746`, `:438-450` |
| `gpu_performance_state_share`, `thermal_state_share` | time in each state over the total, 3 decimals | `:765-771`, `:782-790` |
| `noisy_environment` | `external = device_pct_mean - 100 × (1 - idle_share)`; flagged when `external >= 20` points | `:560-581` |

## fps_estimate

The **median** gap, not the mean: one long gap (a load, a hidden window) moves the mean and not the median. Two medians live in one summary: `fps_estimate` uses `statistics.median` (the mean of the two middle values when the count is even) and `frame_interval_ms.p50` uses `ordered[n // 2]` (the upper one). They differ in the third decimal at most (9.4845 against 9.485 in the first run, [E2, E3](./evidence.md#e3)): cosmetic.

## The 1 % and 0.1 % lows

`low(share, frames)` (`:262-264`) sorts the gaps, takes the one at position `int(n × share)` (capped at the last) and converts it to FPS. So the 1 % low is **the interval that 99 % of the frames beat**, turned into FPS (a percentile), and is `None` until 100 gaps stand behind it (1000 for the 0.1 % low): with fewer, one frame *is* the 1 %. The README says "the FPS of the slowest 1 % of frames", which describes the idea; whether other tools use this percentile or the average of the slowest 1 % was **not verified**, so check before comparing across tools. At 100 FPS, 100 gaps are a second of recording, so the rule is not what makes a recording long: the 30 s under Wine are about the start-up ([recording guide](../recording/rules.md#why-30-seconds-or-more-under-wine)).

## Stutter, jitter and hitches

A gap is a stutter **and** a hitch when it is longer than `max(1.5 × median gap, 8 ms)` (`STUTTER_FLOOR_MS`, `:250`). The floor exists "because at 500 FPS a 3 ms frame is scheduler noise, not a stutter" (`:248-249`; test `test_pacing_and_hitches`, `tests/test_report.py:154`, not run). The stutter rate counts the gaps over `n`; the hitch list names a cause; in both real runs the counts agree ([E3, E4](./evidence.md#e4)). `frame_jitter_ms` is the standard deviation of the gaps, so one 799 ms gap (second run) gives 63.799 ms ([E3](./evidence.md#e3)): read it together with `stutter_rate_pct`, not alone.

Each hitch is named by the **first** rule that fits the interval before the slow frame (`attribute_hitches`, `:294-310`): 1 `shader_compile` (the graphics compiler ran for the program during the interval); 2 `thermal` (the device's thermal state was anything but `Nominal`); 3 `memory_growth` (the program's Metal memory grew by 8 MiB or more between the interval's two ends); 4 `gpu_heavy` (the frame that opens the interval used the GPU for at least 80 % of the gap); 5 `cpu_or_wait` (none of the above: busy on the CPU or waiting). Causes are labels, not proofs: five of the first run's six hitches are `cpu_or_wait`, meaning "no table explains it".

The list keeps the 20 longest, each with `frame` (the frame that ended the gap), `interval_ms`, `window_ms` and, when the CPU table is there, `cpu_pct` (`:312-320`). `per_minute` is `count / ((last start - first start) / 60 000 ms)`: it counts over the presented span, not over `duration_s` (the second run says 103.3, [E4](./evidence.md#e4)), so read it with `frames`, not alone.

## GPU time per frame is a sum over channels

`frame_gpu_ms` adds the vertex, fragment and compute intervals of a frame (`:685`, `:705`). The channels run in parallel, so a frame's total can exceed the time between frames; that is why `gpu_idle` and `gpu_heavy` are defined on the program's own intervals and not on the sum (`other_processes` says it too, `:587-588`). On Windows this number comes from PresentMon and is not the same thing: the comparison refuses to subtract the two (`NOT_COMPARABLE`, `analysis.py:132`).

## The noisy-environment flag

Two things load the GPU: the program and everything else. `device_pct` (driver counters, the whole GPU) minus the program's own busy share (`100 × (1 - idle_share)`) is what "everything else" used; 20 points or more is `noisy_environment: true` and adds `noisy_basis` with the other processes' count and share (`:565-581`, `:757-762`). The 20 is "provisional, not a measurement: re-fit it on at least 3 quiet runs of the same Mac" (`:560-561`); a test says the limit is inclusive (`test_noisy_boundary_is_inclusive`, `tests/test_report.py:905`, not run). By hand, neither real run would be flagged ([E7](./evidence.md#e7)); both summaries lack the key because an older version wrote them ([limit 1](./limits.md)).

## Windows

`perf_record_windows.py` calls the same `frame_pacing` (`:489`) and `common_block` (`:917`), so a Windows summary's FPS, lows, stutter and jitter follow these formulas, over PresentMon's frame intervals or the drawstress log's means. What it cannot measure is `null`, not zero, and the source used is `gpu.source` ([recording guide](../recording/windows-engine.md#the-three-sources-of-frames-and-which-one-wins)).
