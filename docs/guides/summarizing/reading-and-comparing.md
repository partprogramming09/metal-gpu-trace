# Reading and comparing

**Reader:** people who use `perf_compare`, `perf_check`, `perf_gate` and friends and want to know what each really does, or who change `analysis.py`. Reviewed 2026-11-17.

**In short:** once summaries exist, `analysis.py` lists them, compares two, builds a "normal range" from several equal runs,
and checks a new run against it. Comparing only says what moved; checking says better, worse or same; a gate is a fixed bar.
Missing data stays "unknown" and is never turned into zero.

Back to the [guide index](./index.md). Lines are in `analysis.py` unless another file is named. No tool here was run ([index](./index.md#how-to-read-the-labels)); the numbers are evaluated by hand in [E6 and E7](./evidence.md#e6).

## Finding and reading a run

`perf_runs` lists `*.json` in the runs folder, newest first, skipping `baselines.json`, the old `panel.json` (`analysis.py::_recordings`) and a file still being written or not a summary (`analysis.py::tool_perf_runs`). A name must be letters, digits, `.`, `_`, `-`; a link is never followed (`paths.run_path` `paths.py::run_path`, `paths.read_object` `paths.py::read_object`). Every tool that reads a summary is wrapped by `reads_recordings` (`analysis.py::reads_recordings`): a summary whose sections have the wrong type (a hand edit, another version) becomes a `ToolError` naming the kind of error, never a path. Older summaries have fewer keys: `metrics.schema_of` says which generation (`metrics.py::schema_of`) and the comparison says "summaries written before version 0.4.0 have no encoder numbers" instead of failing (`:223-227`).

## `skip_s`: the steady state

Example: a program that compiles shaders in its first 3 seconds looks slow if those seconds count. `steady_summary(run, skip_s)` (`analysis.py::steady_summary`) with `skip_s > 0` reads `frames.csv`, keeps the frames starting at least `skip_s` seconds after the first, and recomputes **from those frames**:

| Recomputed or not | How |
|---|---|
| `frames`, `frame_gpu_ms`, `frame_interval_ms`, `fps_estimate`, the lows, stutter, jitter | recomputed through the same `perf_report.frame_pacing` (`analysis.py::steady_summary`) |
| the hitch count | gaps over the stored `threshold_ms`, with a tolerance of 0.002 ms because `frames.csv` rounds starts to 0.001 ms (`analysis.py::CSV_TOL_MS`, `analysis.py::steady_summary`) |
| Metal memory `peak` | recomputed from the kept frames |
| `gpu.start_latency_ms`, `thermal_state_share`, `process_rss_mib`, `encoders`, `gpu_idle`, `gpu_counters` | stay whole-run; `steady.whole_run` lists them (`analysis.py::steady_summary`) |
| `cpu` block, `throttling_analysis` | dropped (`analysis.py::steady_summary`) |
| hitch **causes** | kept only for the 20 the summary lists; `causes_partial` says when there were more (`analysis.py::steady_summary`) |

With fewer than 2 frames left it refuses: `<run> has under 2 frames after the first N s; use a smaller skip_s` (`analysis.py::steady_summary`). `skip_s` is 0 to 600 (`paths.py::check_skip`). `suggested_actions` proposes one itself: when every `shader_compile` hitch among the 20 longest ends within the first quarter of the run, it suggests the whole seconds that cover them (`_startup_skip_s`, `analysis_advice.py::_startup_skip_s`; tests `tests/test_analysis.py::test_memory_breakdown_says_why_it_cannot`, not run).

## `perf_compare`

`compare_summaries` (`analysis_compare.py::compare_summaries`) computes, for 11 numbers, `change(a, b)`: `b - a` rounded to 3 decimals and `100 × change / a` rounded to 1 (`analysis_compare.py::change`), `None` when a value is missing. The 11: FPS, the two lows, stutter, jitter, mean and p95 GPU ms, p95 frame interval, p50 start latency, peak Metal MiB, peak RSS (`analysis_compare.py::compare_summaries`). **It decides nothing**: it says what moved and adds everything that could make the move meaningless:

| Key | Appears when | Line |
|---|---|---|
| `too_short` | a run has under 100 frames | `analysis_compare.py::compare_summaries` |
| `layer`, `context` | the runs differ in translation layer, commit or Instruments version ([recording guide](../recording/macos-journey.md#what-identifies-a-run)) | `analysis_compare.py::compare_summaries` |
| `unpresented`, `noisy_environment` | one run stopped presenting; one run was flagged noisy | `analysis_compare.py::compare_summaries` |
| `screen` | one run was recorded with the screen locked and the other not | `analysis_compare.py::compare_summaries` |
| `power` | at the start, the runs differ in low power mode or in thermal warning (both known), or one run changed while it was recorded; the note says which, and `changed_in` names the run. A summary with no `machine.power` gets none ([power and heat](./power-and-heat.md)) | `analysis_compare.py::compare_summaries` |
| `tier` | the tiers differ (a `light` run has no memory) | `analysis_compare.py::compare_summaries` |
| `gpu_state` | the time-weighted performance level differs by 0.25 or more (0 all Minimum, 1 all Medium, 2 all Maximum): the same work takes more GPU ms in a lower state | `analysis_compare.py::compare_summaries`, `analysis_compare.py::gpu_state_level` |
| `memory_pressure` | both measured memory the same way (its change), or a note that they did not | `analysis_compare.py::compare_summaries`, `analysis_compare.py::memory_pressure_change` |
| `measure` | a Windows run against a Metal run: GPU ms and Metal memory are not subtracted, the encoders are "not comparable" and the function returns early | `analysis_compare.py::compare_summaries` |
| `encoders` and `labels` | both are Metal summaries with encoders: encoders and command buffers per frame, short-encoder share, idle share (shares change in points, never in %, because 1.9 % to 49.7 % would read +2516 %, `analysis_compare.py::compare_summaries`), and each label's count and GPU ms per frame, largest change first, at most 20 | `analysis_compare.py::compare_summaries`, `analysis.py::label_changes` |

Keys the tool description no longer spells out: `skipped_s` appears when `skip_s` cut the runs (thermal state, process memory and encoders stay whole-run). `context` says whether both runs share the project's commit and Instruments' version: `same` is true or false, null when a run's commit is unknown (named in `unknown_in`; runs from before 0.26.0 are named in `missing_in`). `perf_memory_breakdown` also returns `allocated_mib_per_live_mib` (how many times over the live memory was allocated) and `events_per_s_after_3s` (the allocation rate once start-up is over). To read only some of these, pass `fields` to the tool ([the worker](../server-and-transport/worker.md)).

`short_us` must be one of 10, 25, 50, 100, 250, 500, 1000 (`analysis_compare.py::compare_summaries`). With `markdown` true the result also has a table for a pull request (`analysis_compare.py::markdown_report`), and `suggested_actions` lists what to call next for each run (`analysis.py::tool_perf_compare`). A label missing from one summary may only have fallen out of that summary's top 20, so it is `outside_top_20` with no change, not `new` or `gone` (`analysis.py::label_changes`).

## Baselines: a range, not a run

`perf_baseline name runs` (`analysis.py::tool_perf_baseline`) stores **copies of the summaries** (so the reference outlives `KEEP_RUNS`) in `baselines.json` with the date, replacing a reference of the same name, and returns per checked metric the `range` (lowest and highest value across the runs, `None` for a metric a run lacks; `ranges`, `analysis_compare.py::ranges`) and the `spread_pct`: `200 × (max - min) / (max + min)`, the width as a percentage of the midpoint (`spreads`, `analysis_compare.py::spreads`), "the noise of this program on this machine, which a change must exceed" (`analysis.py::tool_perf_baseline`). Four metrics are checked: `fps`, `gpu_ms_mean` and the p50 of encoders and of command buffers per frame (`CHECKED`, `analysis_compare.py::CHECKED`). The code accepts a single run (range one point, spread 0); `CHANGELOG.md` says "ideally 3 or more". The file is described in the [data guide](../data-and-lifecycle/project-and-config.md#the-project-file-the-mark-and-the-baselines). It reports `unpresented` and `noisy_environment` of its runs (`analysis.py::tool_perf_baseline`), so a bad reference is visible.

## `perf_check`: the verdict

`judge(metric, value, span, margin_pct)` (`analysis_compare.py::judge`): where higher is worse (GPU ms, the counts), `worse` if `value > span.max × (1 + margin)`, `better` if `value < span.min × (1 - margin)`, else `same`; for FPS the sides swap. The margin is `margin_pct / 100` (default **3**, `analysis.py::tool_perf_check`) for FPS and GPU ms, and **0** for the two `_p50` counts (`analysis_compare.py::judge`): an encoder count is exact and one more encoder per frame is a change. Then (`analysis.py::tool_perf_check`): a metric the run or the reference lacks is `unchecked`; if one side is Windows and the other Metal, only FPS is judged (`cross`, `analysis.py::tool_perf_check`); the verdict is **`regressed` if any metric is worse, `improved` if any is better and none worse, `same` otherwise** (`analysis.py::tool_perf_check`).

The answer carries `regressed` and `improved` (metric, value, range of each), `unchecked`, the `range` and the full `perf_compare` of the reference's *first* run against this run (`analysis.py::tool_perf_check`). A reference of one run whose verdict is not `same` also carries a `note` saying its noise is not measured (`analysis.py::tool_perf_check`). Frame pacing, short encoders and idle time are in the comparison but **never decide**: they "vary too much between equal runs" (13 % and 7 points in the changelog, `analysis.py::tool_perf_check`). The 3 % is a default the project chose (**not verified** as measured; the 4.4 % and 6.1 % spreads of the [index](./index.md#why-this-part-is-shaped-this-way) are why the reference is a range); `perf_check` **does not read** the baseline's `spread_pct` ([limit 8](./limits.md)). Test: `test_judge_matches_perf_check` (`tests/test_analysis.py::test_judge_matches_perf_check`, not run) pins that `judge` says `worse` for exactly the metrics `perf_check` lists as regressed, and `better` for those it lists as improved.

## `perf_gate`: a bar, not a reference

`perf_gate` (`analysis.py::tool_perf_gate`) checks fixed budgets: `fps_min`, `fps_1pct_low_min`, `stutter_rate_pct_max`, `gpu_ms_p95_max`, `hitches_max`, `metal_mib_max` (`GATES`, `analysis.py::GATES`); at least one is required. A budget is `ok` only if the value exists and is on the right side: `ok = value is not None and (value >= limit if min else value <= limit)` (`analysis.py::tool_perf_gate`). The answer is `pass` only if all hold **and** the run has no `unpresented` (`analysis.py::tool_perf_gate`). Use a gate for a bar a change must clear; `perf_check` for "did this change move it beyond what equal runs do".

## `perf_history` and `perf_diagnose`

`perf_history prefix` lists the runs whose name starts with the prefix, oldest first, with six numbers and the change from first to last (`analysis.py::tool_perf_history`). It flags a series that mixes Windows and Metal and says "under 3 runs: not a trend yet" (`analysis.py::tool_perf_history`); read a trend as real only when it exceeds the `spread_pct` of equal runs (`analysis.py::tool_perf_history`).

`perf_diagnose` (`:693-820`) is a rule-based reading of one summary: **a heuristic**: its recommendations are English sentences (they were Spanish before this change; see [limit 11](./limits.md)).

| Output | Rule (thresholds are in the code) | Line |
|---|---|---|
| `stutter_analysis.verdict` | `UNKNOWN` without the stutter number; `SEVERE_STUTTER` above 7 %; `MICRO_STUTTER` from 2 %; else `SMOOTH` | `analysis.py::tool_perf_diagnose` |
| `bottleneck` | `MEMORY_PRESSURE_SUSPECTED` when variance is high (jitter at least 3 ms, or p95 minus p50 of the interval at least 5 ms) and the working set is at least 1500 MiB; `UNKNOWN` without `idle_share`; `CPU_SUBMISSION_BOUND` when `idle_share >= 0.25` (or `>= 0.20` with too many short encoders), or `DISPLAY_SYNCED` instead when the run is locked to the display (`display_synced_hz` is set: the idle time is the wait for the display); `GPU_BOUND` when `idle_share <= 0.15` and the GPU ms is at least 80 % of the interval; else `BALANCED` | `analysis.py::tool_perf_diagnose` |
| `too_many_short_encoders` | encoders per frame p50 at least `min_encoders` (4) **and** the share under `short_us` at least `short_share` (0.25) | `analysis.py::tool_perf_diagnose` |

The defaults "come from bgfx 17-drawstress on an M1 Pro: 7 encoders per frame and 50 % under 25 µs under Mullion, 2 and 2 % in native Metal" (`analysis.py::tool_perf_diagnose`). The memory verdict is an inference ("memory bandwidth itself is not measured", `analysis.py::tool_perf_diagnose`). By hand on the two real runs ([E7](./evidence.md#e7)): `SMOOTH` (0.29 %) and `MICRO_STUTTER` (2.63 %), both `CPU_SUBMISSION_BOUND` by the rule (**probable**, tool not run). `perf_memory_breakdown` (`analysis.py::tool_perf_memory_breakdown`) only rearranges the `resource_allocations` block and computes ratios (`live_share_pct`, `allocated_mib_per_live_mib`).

## When a number is missing

| Reader | A missing number becomes |
|---|---|
| `compare_summaries` | `change(None, None)`: both `a` and `b` `None` when the key is absent (`analysis_compare.py::compare_summaries`) |
| `perf_check` | `unchecked`; `hint_unchecked` says a pre-0.4.0 summary has no encoder numbers (`analysis.py::tool_perf_check`) |
| `perf_gate` | the budget **fails** (`value` null, `ok` false): "a gate must not pass on missing data" (`analysis.py::tool_perf_gate`) |
| `perf_history` | `null` in the row (`dig`, `analysis.py::dig`) |
| `perf_diagnose`, a short run | `UNKNOWN` verdicts (`analysis.py::tool_perf_diagnose`); `fps_1pct_low` and `fps_01pct_low` are `None` (`perf_report.py::counter_stats`) |
