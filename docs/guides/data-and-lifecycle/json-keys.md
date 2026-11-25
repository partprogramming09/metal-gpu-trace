# The summary, key by key

**Reader:** people who add, read or change a key of the summary JSON. Reviewed 2026-11-18.

> **In short:** the summary is the small file with the numbers of one recording. Three pieces of code add keys one after
> another, and some keys depend on what the recording captured, so a reader must treat conditional keys as optional.

Back to the [index](./index.md). Example: a real summary here has `label`, `trace`, `process`, `device`, `gpu`, `encoders` and a few more, but no `machine` or `context` ([E3](./evidence-runs.md#e3-keys-of-real-summaries)).

Keys are written in sequence by:

1. `perf_report.summarize` builds it from the `.trace` (`perf_report.py::summarize`) and writes the first `.json`.
2. `recording.finish` adds `layer`, `context`, `tier`, `retention`, `app_metrics` (when the program wrote its file), rebuilds `common` and rewrites the file (`recording.py::finish`).
3. On Windows, `perf_record_windows.py` builds a smaller object (`perf_record_windows.py::record_windows`), then `finish` does step 2 on it.

## The generations

`schema_version` says the generation (`metrics.py::SCHEMA_VERSION`, read by `metrics.schema_of`, `metrics.py::schema_of`). Without it a summary is generation 1, and every tool still reads 1, 2 and 3 (`CHANGELOG.md`, 0.27.0, Changed).

| Generation | What it added | Shipped in |
|---|---|---|
| 1 | The original keys | before 0.27.0 |
| 2 | Compressed tables, `tier`, `retention` (`metrics.py::SCHEMA_VERSION`) | 0.27.0 (`CHANGELOG.md`) |
| 3 | The `common` block (`metrics.py::SCHEMA_VERSION`) | 0.27.3; the code writes it |

**Every real summary here is generation 1** (E3: no `schema_version`, `common`, `tier` or `retention`), recorded before 0.27.0. The key lists below come from the code; a generation 3 summary was recorded on macOS and on Windows for 0.27.3 (see [its proof](../../evidence/v0.27.3.md)); the real files in this repository's runs folder are still older. Every key in a real file is in these tables (E3, known limit 11).

## Keys of a macOS summary: always present

| Key | Holds | Written at; read by |
|---|---|---|
| `schema_version` | The generation (first key) | `perf_report.py::summarize`; `analysis.py::tool_perf_runs` via `metrics.schema_of` |
| `label`, `template`, `duration_s` | Recording label, Instruments template name, seconds recorded | `perf_report.py::summarize`; `analysis_advice.py::suggested_actions`, `analysis.py::tool_perf_diagnose`, `analysis_advice.py::_startup_skip_s` |
| `trace` | Name of the `.trace`, kept after the file is deleted | `perf_report.py::summarize`; nothing in `src/` reads it (`rg`); `perf_runs` tests the file (`analysis.py::tool_perf_runs`) |
| `process` | `name`, `pid`, `termination-reason`, `arguments` (shareable via `public_arguments`) | `perf_report.py::summarize`; `analysis.py::tool_perf_runs` (`arguments`), `recording.py::run_recording` (`termination-reason`) |
| `device` | `platform`, `model`, `memory-size`, `os-version`; machine name and UUID left out on purpose | `perf_report.py::summarize`; `analysis_compare.py::measurement`, `metrics.py::common_block` |
| `machine` | Chip, cores, RAM, macOS, `screen_locked`, and `power` (low power mode and heat at the start and the end, see [power and heat](../summarizing/power-and-heat.md)). **It can be `null`**: when this Mac is not the one that recorded the trace, or a fact cannot be read; then there is no `power` either | `perf_report.py::summarize` (`perf_report_host.py::machine_info`); `recording.py::run_recording` (`power`); `analysis_compare.py::compare_summaries` (locked screen), `analysis_compare.py::compare_summaries` (`power`) |
| `missing_tables` | Instruments tables the trace did not have | `perf_report.py::summarize`; no reader in `src/` (`rg`) |
| `gpu` | `intervals`, `frames`, `frame_gpu_ms`, `per_channel_ms`, `frame_interval_ms`, `start_latency_ms`, `fps_estimate`, pacing keys below | `perf_report.py::summarize`; `perf_runs`, compare, diagnose, gates (`analysis.py`) |
| `encoders` | Encoders and command buffers per frame, shortest encoders, top 20 labels | `perf_report.py::summarize`; `analysis_compare.py::compare_summaries`, `analysis.py::tool_perf_diagnose` |
| `gpu_idle` | When the GPU waited | `perf_report.py::summarize`; `analysis_compare.py::compare_summaries`, `analysis.py::tool_perf_diagnose` |
| `gpu_performance_state_share` | Time share per GPU clock state; `{}` if none | `perf_report.py::summarize`; `analysis_compare.py::gpu_state_level` |
| `hitches` | `count`, `per_minute`, `threshold_ms`, `causes`, 20 `worst` | `perf_report.py::summarize`; `analysis.py::steady_summary`, `analysis.py::tool_perf_diagnose` |
| `common` | `frame_pacing`, `memory_pressure`, `boundness`, `submission_overhead`, `api` (its `runtime` is `metal` on macOS and `unknown` on Windows, which does not read it from PresentMon yet), from `metrics.common_block` | `perf_report.py::summarize`, rebuilt `recording.py::finish`; `analysis_compare.py::memory_pressure_change` |
| `layer` | Translation layer: Wine with overrides and DLL hashes, `none` (native), `unknown` (attached), MoltenVK, Rosetta | `recording.py::finish`; `recording.py::identity`, `metrics.layer_label` |
| `context` | `git` (short commit and `dirty`, or null) and `instruments` (version, or null); since 0.33 also `env_keys` (the sorted names, never the values, of the variables the run was given) and, when `fingerprint_paths` was passed, `fingerprint` (per file: base name, first 16 hex digits of its SHA-256, size) | `recording.py::finish`, `recording.py::run_context`; `recording.py::context_change` |

A summary from a hand-run `perf_report.py` has no `layer` or `context`: they come from `recording.finish` (confirmed: assigned only at `recording.py::finish`).

The pacing keys in `gpu` come from `frame_pacing` (`perf_report_frames.py::frame_pacing`), only when there are frame gaps: `fps_1pct_low` and `fps_01pct_low` (null unless 100 and 1000 frames), `stutter_rate_pct` and `frame_jitter_ms` (more than one gap), `throttling_analysis` (five gaps or more).

## Keys of a macOS summary: present only on a condition

| Key | Condition (from the `if` around the assignment) | Written at |
|---|---|---|
| `tier` | `recording.finish` got a tier: `perf_record` passes one, `perf_attach` does not | `recording.py::finish` |
| `retention` | `METAL_TRACE_MAX_DISK_MB` set, no other recording running, at least one file removed: `{freed_mb, removed, trace_dropped}` | `recording.py::finish` |
| `app_metrics` | The program wrote a file at the path in `METAL_TRACE_APP_METRICS`. The recording sets that variable only when some temporary folder has a path without spaces; the file must be a plain file (not a link or a folder); an empty file gives `samples: 0`. See [Program telemetry](../recording/macos-journey.md#program-telemetry) | `recording.py::finish` (`app_metrics.safe_read`); `app_metrics.py::read` |
| `gpu.unpresented` | The program stopped presenting; later work is left out of the frames | `perf_report.py::summarize` |
| `metal_memory_mib` | Metal memory table read (`memory` true: not `light` tier, not `PERF_MEMORY=0`); `{"samples": 0}` if no sample | `perf_report.py::summarize` |
| `process_rss_mib` | `<run>.rss.csv` exists beside the trace | `perf_report.py::summarize` |
| `gpu_activity` | `<run>.agx.csv` gave rows. Its `split_scenes_per_min` and `recoveries_per_min` are the growth of `split_scenes` and `recoveries` per minute of the samples' time span (null when the span is zero or the counter is missing) | `perf_report.py::summarize`; `perf_report.py::agx_summary` |
| `noisy_environment`, `noisy_basis` | `noisy_environment()` returned something (`true` or `false`); the basis (with `other_processes`) only when `true` | `perf_report.py::summarize` |
| `graphics_compiler` | The `graphics-compiler-activity-intervals` table exists. `intervals`, `busy_ms`, and `duration_ms` (count, mean, p50, p95, max of one compile). `startup` and `in_flight` (each with `intervals` and `busy_ms`) split the compiles by whether they began before the 10th frame; they are absent when the program has fewer than 10 frames | `perf_report.py::summarize`; `perf_report.py::compiler_summary` |
| `thermal_state_share` | The `device-thermal-state-intervals` table exists | `perf_report.py::summarize` |
| `cpu` | `ProcessCPUUsage` had rows for the program | `perf_report.py::summarize` |
| `resource_allocations` | The allocations table exists and has events | `perf_report.py::summarize` |
| `shader_spills` | The `graphics-compiler-spill-events` table exists (a count) | `perf_report.py::summarize` |
| `command_buffer_errors`, `command_buffer_errors_scope`, `command_buffer_error_codes` | The `metal-command-buffer-error` table exists. `command_buffer_errors` counts the errors of the program's command buffers (matched by `cmdbuffer-id` to the encoders table of the program's pid) and `command_buffer_errors_scope` is `program`; with no encoders table it counts every process's errors and the scope is `all_processes`. `command_buffer_error_codes` maps each `error-code` to its count, only when there is at least one error | `perf_report.py::summarize` (scope), `perf_report.py::command_buffer_errors` (count), `perf_report.py::summarize` (buffers) |
| `validation` | `<run>.validation.log` exists (Metal validation was on) | `perf_report.py::summarize` |
| `gpu_counters` | Both counter tables exist and gave samples (`counters=true`, the `deep` tier) | `perf_report.py::summarize` |

`app_metrics` sits at the top level of the summary, not in `common`: each program decides what its columns mean, so the block carries `comparable: false` and is not compared across programs. It does not raise `schema_version`; readers of generations 1 to 3 do not change.

## A Windows summary

`perf_record_windows.py::record_windows` writes a smaller object:

| Part | Content |
|---|---|
| Written by the engine | `schema_version`, `label`, `trace` (the name `<run>.trace`, a file that never exists on Windows), `process`, `device`, `template` (`Windows Native Trace`), `duration_s`, `missing_tables` (three fixed names), `gpu`, `encoders`, `gpu_idle`, `metal_memory_mib` (`{"samples": 0}`), `process_rss_mib`, `layer`, `common` |
| `gpu` | Has `source` (`drawstress-log`, `presentmon`, `dwm-composition` or `vegaflow-bench-json`), the pacing keys and `throttling_analysis` |
| Added by `finish` | `context`, and `tier`, `retention`, `app_metrics` under the same conditions |
| Absent | `machine`, `hitches`, `gpu_performance_state_share` and every conditional Metal key: treat each as optional (confirmed: not in the dict at those lines) |

`finish` replaces `layer` with the one `record_run` computed (`recording.py::finish`, `recording.py::record_run`): for a native Windows run `native Metal, no translation layer` (`recording.py::layer_of`) instead of the engine's `native Windows`; `layer_label` calls both `native`, so no reader notices (confirmed by the code, not reproduced).

## Results imported from VegaFlow (`import-bench`)

`metal-gpu-trace import-bench FILE.json...` (`bench_import.py::from_json`) writes a summary from a `bench.ps1` result. Only `gpu.frame_jitter_ms` is filled (`gpu.source` is `vegaflow-bench-json`); the other pacing keys are `null` because VegaFlow's FPS, 1 % low and hitches use other formulas. Its own numbers sit in `vegaflow_bench` under their original names (`avg_fps`, `fps_1pct_low`, `present_mode`, `clean`, `errors`, ...). `clean` says whether the present mode held; it is not `noisy_environment`. `skip_s` does not work on these runs: there is no per-frame file.
