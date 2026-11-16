# The summary, key by key

**Reader:** people who add, read or change a key of the summary JSON. Reviewed 2026-11-16.

Español: [El resumen, clave por clave](../../es/guides/datos-y-su-ciclo-de-vida/claves-del-resumen.md)

> **In short:** the summary is the small file with the numbers of one recording. Three different pieces of code add
> keys to it one after another, and not every key is always there: some depend on what the recording captured. A tool
> that reads it must treat the conditional keys as optional. This page lists every key, when it appears and who reads it.

Back to the [index](./index.md). Example: a real summary from this machine has `label`, `trace`, `process`, `device`,
`gpu`, `encoders` and a few more, but no `machine` or `context`; see
[E3](./evidence-runs.md#e3-keys-of-real-summaries).

The keys are written by three pieces of code in sequence:

1. `perf_report.summarize` builds it from the `.trace` (`perf_report.py:648-835`) and writes the first `.json`.
2. `recording.finish` adds `layer`, `context`, `tier` and `retention`, rebuilds `common`, and rewrites the file
   (`recording.py:337-351`).
3. On Windows, `perf_record_windows.py` builds a different, smaller object (`perf_record_windows.py:887-917`), then `finish`
   does step 2 on it.

## The generations

`schema_version` says which generation a summary is (`metrics.py:10`, read by `metrics.schema_of`, `metrics.py:13`). A
summary without it is generation 1, and every tool still reads generation 1, 2 and 3 (`CHANGELOG.md`, 0.27.0, Changed: a summary without it is version 1 and every tool still reads it).

| Generation | What it added | Shipped in |
|---|---|---|
| 1 | The original keys | before 0.27.0 |
| 2 | Compressed tables, `tier`, `retention` (`metrics.py:9`) | 0.27.0 (`CHANGELOG.md`) |
| 3 | The `common` block (`metrics.py:9`) | `[Unreleased]` in `CHANGELOG.md`; the code already writes it |

**Every real summary on the machine this page was checked on is generation 1** (E3: no `schema_version`, no `common`,
no `tier`, no `retention`), because they were recorded before 0.27.0. So the key lists below come from the code, not from
a real generation 3 file. A generation 3 summary was **not reproduced** (it needs a macOS recording with Instruments).
Even so, the generation 1 files are what the tables below were compared with: every key in a real file is in them
(E3, known limit 11).

## Keys of a macOS summary: always present

| Key | What it holds | Written at | Read by |
|---|---|---|---|
| `schema_version` | The generation (first key) | `perf_report.py:648` | `analysis.py:74` through `metrics.schema_of` |
| `label` | The recording's label | `perf_report.py:649` | `analysis.py:643` |
| `trace` | The name of the `.trace`, kept even after the file is deleted | `perf_report.py:650` | nothing in `src/` reads the key (`rg`); `perf_runs` tests the file instead (`analysis.py:79`) |
| `process` | `name`, `pid`, `termination-reason`, `arguments` (made shareable by `public_arguments`) | `perf_report.py:651-652` | `analysis.py:74` (`arguments`), `recording.py:432` (`termination-reason`) |
| `device` | `platform`, `model`, `memory-size`, `os-version`; the machine's name and UUID are left out on purpose | `perf_report.py:654` | `analysis.py:138`, `metrics.py:55` |
| `template` | The Instruments template name | `perf_report.py:659` | `analysis.py:759` |
| `duration_s` | Seconds recorded | `perf_report.py:660` | `analysis.py:673` |
| `machine` | Chip, cores, RAM, macOS, `screen_locked` | `perf_report.py:661` | `analysis.py:195` (a locked screen) |
| `missing_tables` | Instruments tables the trace did not have | `perf_report.py:664` | no reader in `src/` (`rg`); it is for whoever reads the summary |
| `gpu` | `intervals`, `frames`, `frame_gpu_ms`, `per_channel_ms`, `frame_interval_ms`, `start_latency_ms`, `fps_estimate`, and the pacing keys below | `perf_report.py:709` | `perf_runs`, compare, diagnose, gates (`analysis.py` throughout) |
| `encoders` | Encoders and command buffers per frame, the shortest encoders, the top 20 labels | `perf_report.py:728` | `analysis.py:223`, `:702` |
| `gpu_idle` | When the GPU waited | `perf_report.py:729` | `analysis.py:231`, `:715` |
| `gpu_performance_state_share` | Share of time per GPU clock state; `{}` if there is none | `perf_report.py:771` | `analysis.py:144` |
| `hitches` | `count`, `per_minute`, `threshold_ms`, `causes`, the 20 `worst` | `perf_report.py:822` | `analysis.py:574`, `:773` |
| `common` | `frame_pacing`, `memory_pressure`, `boundness`, `submission_overhead`, `api`, built by `metrics.common_block` | `perf_report.py:835`, rebuilt at `recording.py:343` | `analysis.py:153` |
| `layer` | The translation layer: Wine and its overrides and DLL hashes, or `none` (native), `unknown` (attached), MoltenVK, Rosetta | `recording.py:341` | `recording.py:208`, `metrics.layer_label` |
| `context` | `git` (short commit and `dirty`, or null) and `instruments` (the version, or null) | `recording.py:341`, `run_context` at `recording.py:168` | `recording.py:195` |

A summary written by `perf_report.py` run by hand has no `layer` and no `context`: those two come from `recording.finish`
(confirmed: the assignments are only at `recording.py:341`).

The pacing keys inside `gpu` come from `frame_pacing` (`perf_report.py:253`) and are present only when there are frame
gaps: `fps_1pct_low` and `fps_01pct_low` (a null unless there are 100 and 1000 frames), `stutter_rate_pct` and
`frame_jitter_ms` (more than one gap), `throttling_analysis` (five gaps or more).

## Keys of a macOS summary: present only on a condition

| Key | Condition (read from the `if` around the assignment) | Written at |
|---|---|---|
| `tier` | `recording.finish` got a tier: `perf_record` passes one, `perf_attach` does not | `recording.py:344-345` |
| `retention` | `METAL_TRACE_MAX_DISK_MB` is set, no other recording is running and at least one file was removed: `{freed_mb, removed, trace_dropped}` | `recording.py:346-349` |
| `gpu.unpresented` | The program stopped presenting; the work after that is left out of the frames | `perf_report.py:721` |
| `metal_memory_mib` | The Metal memory table was read (`memory` true: not the `light` tier, not `PERF_MEMORY=0`); `{"samples": 0}` when it had no sample | `perf_report.py:740` |
| `process_rss_mib` | `<run>.rss.csv` exists beside the trace | `perf_report.py:753` |
| `gpu_activity` | `<run>.agx.csv` gave rows | `perf_report.py:756` |
| `noisy_environment` | `noisy_environment()` returned something; `true` or `false` | `perf_report.py:759` |
| `noisy_basis` | `noisy_environment` is `true`; carries `other_processes` | `perf_report.py:761-762` |
| `graphics_compiler` | The `graphics-compiler-activity-intervals` table exists | `perf_report.py:780` |
| `thermal_state_share` | The `device-thermal-state-intervals` table exists | `perf_report.py:790` |
| `cpu` | `ProcessCPUUsage` had rows for the program | `perf_report.py:798` |
| `resource_allocations` | The allocations table exists and has events | `perf_report.py:802` |
| `shader_spills` | The `graphics-compiler-spill-events` table exists | `perf_report.py:804` |
| `command_buffer_errors` | The `metal-command-buffer-error` table exists (a count) | `perf_report.py:806` |
| `validation` | `<run>.validation.log` exists (Metal validation was on) | `perf_report.py:811` |
| `gpu_counters` | The two counter tables exist and gave samples (`counters=true`, the `deep` tier) | `perf_report.py:817` |

## A Windows summary

`perf_record_windows.py:887-917` writes a smaller object:

| Part | Content |
|---|---|
| Keys written by the engine | `schema_version`, `label`, `trace` (the name `<run>.trace`, a file that never exists on Windows), `process`, `device`, `template` (`Windows Native Trace`), `duration_s`, `missing_tables` (three fixed names), `gpu`, `encoders`, `gpu_idle`, `metal_memory_mib` (`{"samples": 0}`), `process_rss_mib`, `layer`, `common` |
| `gpu` | Has `source` (one of `drawstress-log`, `presentmon` or `dwm-composition`), the pacing keys and `throttling_analysis` |
| Added by `finish` | `context`, and `tier` and `retention` under the same conditions |
| Absent | `machine`, `hitches`, `gpu_performance_state_share` and every conditional Metal key: a tool must treat each as optional (confirmed: not in the dict at those lines) |

`finish` also replaces `layer` with the one `record_run` computed (`recording.py:341`, `:370`, `:385`), which for a
native Windows run reads `native Metal, no translation layer` (`recording.py:134-135`) where the engine had written
`native Windows` (`perf_record_windows.py`, same dict); `layer_label` calls both `native`, so no reader notices
(confirmed by the code, not reproduced).
