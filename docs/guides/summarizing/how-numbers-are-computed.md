# How each number is computed

**Reader:** people who see a number in a summary and ask where it comes from, or who change `perf_report.py` or `metrics.py`. Reviewed 2026-11-17.

**In short:** most numbers come from one list: how many milliseconds pass between the start of one frame and the start of
the next. The "FPS" is the typical gap turned upside down, a "stutter" is a gap much longer than usual, and a "hitch" is
the same slow gap with a guess at its cause. This page gives each formula and the line of code that holds it.

Back to the [guide index](./index.md).

Example first: in the first run of the guide's example, the median gap is 9.4845 ms, so `1000 / 9.4845 = 105.4` FPS; 6 of 2044 gaps are over 14.227 ms, so the stutter rate is 0.29 % ([E3](./evidence.md#e3)). Everything here is **confirmed** by the line given. "The gaps" are the intervals between the first start of consecutive **presented** frames, in ms; "the totals" are the GPU ms of each frame, summed over its channels.

| Key | Formula | Line |
|---|---|---|
| the gaps | for each pair of consecutive frame numbers `a < b`: `first_start[b] - first_start[a]`, kept only if positive and if no unpresented frame lies between them | `perf_report_frames.py::presented` |
| the totals | per frame: the sum of `duration / 1e6` of its intervals | `perf_report.py::summarize` |
| `gpu.frames`, `frame_gpu_ms`, `frame_interval_ms` | the number of frames kept; `stats(totals)`, `stats(gaps)` | `perf_report.py::summarize` |
| `stats` | `count`, `mean` (3 decimals), `p50 = ordered[n // 2]`, `p95 = ordered[min(n-1, int(n × 0.95))]`, `max` | `metrics.py::common_block` |
| `gpu.fps_estimate` | `round(1000 / median(gaps), 1)`, `None` without gaps | `perf_report.py::summarize` |
| `gpu.fps_1pct_low`, `fps_01pct_low` | `1000 / ordered_gaps[min(n-1, int(n × 0.99))]` with at least 100 gaps; the same with `0.999` and at least 1000 gaps | `perf_report_frames.py::frame_pacing` |
| `gpu.stutter_rate_pct` | `100 × (gaps > max(1.5 × median, 8.0 ms)) / n`, two decimals; needs at least 2 gaps | `perf_report_frames.py::STUTTER_FLOOR_MS`, `perf_report_frames.py::frame_pacing` |
| `gpu.frame_jitter_ms` | `pstdev(gaps)`, three decimals (population standard deviation) | `perf_report_frames.py::frame_pacing` |
| `gpu.throttling_analysis` | with at least 5 gaps: `k = max(1, int(n × 0.2))`; `fps_initial` and `fps_final` are `1000 / median` of the first and last `k` gaps; `drift = (initial - final) / initial × 100`; detected when the drop is over 10 % **and** the mean GPU ms of the last `k` frames is above the first `k` | `perf_report_frames.py::frame_pacing` |
| `hitches` | the same limit as stutter; each gap above it is one hitch, with a cause | `perf_report_frames.py::attribute_hitches` |
| `gpu.start_latency_ms` | `stats` of the start latency of every row of the program that has one, without the unpresented frames | `perf_report.py::summarize` |
| `gpu_idle` | the GPU's idle time between the program's own intervals: per frame, gaps over 1 ms, and `idle_share = sum(gaps) / whole span` | `metrics.py::encoder_stats` |
| `encoders` | encoders and command buffers per frame, each encoder's GPU time, the share shorter than 10, 25, 50, 100, 250, 500 and 1000 µs, the 20 labels with the most GPU time | `metrics.py::stats` |
| `metal_memory_mib` | `peak`, `final`, `mean` of the program's samples; `trend_mib_per_min` is the least-squares slope over the second half of the time, with at least 5 samples and 5 s | `perf_report.py::summarize`, `perf_report_frames.py::memory_trend` |
| `gpu_performance_state_share`, `thermal_state_share` | time in each state over the total, 3 decimals | `perf_report.py::summarize` |
| `noisy_environment` | `external = device_pct_mean - 100 × (1 - idle_share)`; flagged when `external >= 20` points | `perf_report_host.py::noisy_environment` |
| `graphics_compiler.duration_ms` | `stats` (count, mean, p50, p95, max) of `end - start` for each compile in the program's graphics-compiler intervals: the same rows as `busy_ms` | `perf_report.py::compiler_summary` (`compiler_summary`) |
| `graphics_compiler.startup`, `.in_flight` | the compiles split by their start against the start of the 10th frame (`frame_starts[9]`): `startup` those that begin before it, `in_flight` the rest; each with `intervals` and `busy_ms`. Absent with fewer than 10 frames | `perf_report.py::compiler_summary`, `perf_report.py::summarize` |
| `command_buffer_errors`, `command_buffer_errors_scope`, `command_buffer_error_codes` | errors whose `cmdbuffer-id` the encoders table names under the program's pid; `scope` is `program`, or `all_processes` when there is no encoders table; codes are counted by `error-code` (`unknown` when a row has none), and the key appears only with at least one error | `perf_report.py::command_buffer_errors`, `perf_report.py::summarize` |
| `gpu_activity.split_scenes_per_min`, `recoveries_per_min` | growth of `split_scenes` or `recoveries` over the samples' time span, per minute: `growth × 60 / span_s`; `null` when the span is zero | `perf_report.py::agx_summary` (`agx_summary`) |
| `machine.power` | low power mode and thermal warning, read before and after the recording; `changed` is true when a fact known at both ends differs. Explained in [power and heat](./power-and-heat.md) | `perf_report_host.py::power_state`, `perf_report_host.py::power_block`; `recording.py::record_run` |

## fps_estimate

The **median** gap, not the mean: one long gap (a load, a hidden window) moves the mean and not the median. Two medians live in one summary: `fps_estimate` uses `statistics.median` (the mean of the two middle values when the count is even) and `frame_interval_ms.p50` uses `ordered[n // 2]` (the upper one). They differ in the third decimal at most (9.4845 against 9.485 in the first run, [E2, E3](./evidence.md#e3)): cosmetic.

## The 1 % and 0.1 % lows

`low(share, frames)` (`perf_report_frames.py::frame_pacing`) sorts the gaps, takes the one at position `int(n × share)` (capped at the last) and converts it to FPS. So the 1 % low is **the interval that 99 % of the frames beat**, turned into FPS (a percentile), and is `None` until 100 gaps stand behind it (1000 for the 0.1 % low): with fewer, one frame *is* the 1 %. The README says "the FPS of the slowest 1 % of frames", which describes the idea; whether other tools use this percentile or the average of the slowest 1 % was **not verified**, so check before comparing across tools. At 100 FPS, 100 gaps are a second of recording, so the rule is not what makes a recording long: the 30 s under Wine are about the start-up ([recording guide](../recording/rules.md#why-30-seconds-or-more-under-wine)).

## Stutter, jitter and hitches

A gap is a stutter **and** a hitch when it is longer than `max(1.5 × median gap, 8 ms)` (`STUTTER_FLOOR_MS`, `perf_report_frames.py::STUTTER_FLOOR_MS`). The floor exists "because at 500 FPS a 3 ms frame is scheduler noise, not a stutter" (`perf_report_frames.py::STUTTER_FLOOR_MS`; test `test_pacing_and_hitches`, `tests/test_report.py::test_pacing_and_hitches`, not run). The stutter rate counts the gaps over `n`; the hitch list names a cause; in both real runs the counts agree ([E3, E4](./evidence.md#e4)). `frame_jitter_ms` is the standard deviation of the gaps, so one 799 ms gap (second run) gives 63.799 ms ([E3](./evidence.md#e3)): read it together with `stutter_rate_pct`, not alone.

Each hitch is named by the **first** rule that fits the interval before the slow frame (`attribute_hitches`, `perf_report_frames.py::attribute_hitches`): 1 `shader_compile` (the graphics compiler ran for the program during the interval); 2 `thermal` (the device's thermal state was anything but `Nominal`); 3 `memory_growth` (the program's Metal memory grew by 8 MiB or more between the interval's two ends); 4 `gpu_heavy` (the frame that opens the interval used the GPU for at least 80 % of the gap); 5 `cpu_or_wait` (none of the above: busy on the CPU or waiting). Causes are labels, not proofs: five of the first run's six hitches are `cpu_or_wait`, meaning "no table explains it".

The list keeps the 20 longest, each with `frame` (the frame that ended the gap), `interval_ms`, `window_ms` and, when the CPU table is there, `cpu_pct` (`perf_report_frames.py::attribute_hitches`). `per_minute` is `count / ((last start - first start) / 60 000 ms)`: it counts over the presented span, not over `duration_s` (the second run says 103.3, [E4](./evidence.md#e4)), so read it with `frames`, not alone.

## GPU time per frame is a sum over channels

`frame_gpu_ms` adds the vertex, fragment and compute intervals of a frame (`perf_report.py::summarize`). The channels run in parallel, so a frame's total can exceed the time between frames; that is why `gpu_idle` and `gpu_heavy` are defined on the program's own intervals and not on the sum (`other_processes` says it too, `perf_report_host.py::other_processes`). On Windows this number comes from PresentMon and is not the same thing: the comparison refuses to subtract the two (`NOT_COMPARABLE`, `analysis_compare.py::NOT_COMPARABLE`).

## The noisy-environment flag

Two things load the GPU: the program and everything else. `device_pct` (driver counters, the whole GPU) minus the program's own busy share (`100 × (1 - idle_share)`) is what "everything else" used; 20 points or more is `noisy_environment: true` and adds `noisy_basis` with the other processes' count and share (`perf_report_host.py::noisy_environment`, `perf_report.py::summarize`). The 20 is "provisional, not a measurement: re-fit it on at least 3 quiet runs of the same Mac" (`metrics.py::NOISY_EXTERNAL_PCT`); a test says the limit is inclusive (`test_noisy_boundary_is_inclusive`, `tests/test_report.py::test_rows_deletes_file_on_early_close_and_on_failure`, not run). By hand, neither real run would be flagged ([E7](./evidence.md#e7)); both summaries lack the key because an older version wrote them ([limit 1](./limits.md)).

## Windows

`perf_record_windows.py` calls the same `frame_pacing` (`perf_record_windows.py::compute_precision_telemetry`) and `common_block` (`perf_record_windows.py::record_windows`), so a Windows summary's FPS, lows, stutter and jitter follow these formulas, over PresentMon's frame intervals or the drawstress log's means. What it cannot measure is `null`, not zero, and the source used is `gpu.source` ([recording guide](../recording/windows-engine.md#the-three-sources-of-frames-and-which-one-wins)).
