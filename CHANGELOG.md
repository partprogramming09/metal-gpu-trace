# Changelog

Versions follow [Semantic Versioning](https://semver.org); each one is a `vX.Y.Z` tag. `metal-gpu-trace --version`
and the MCP `initialize` answer (`serverInfo.version`) print the installed one.

## 0.7.1 — 2026-10-18

- `trace_count` and `trace_query` read an empty table whose export xctrace 27.1 cuts right after the schema
  (`time-profile` under Wine with `PERF_INSTRUMENTS="Time Profiler"`) as 0 rows instead of failing with
  `exit -5: no message`.

## 0.7.0 — 2026-10-18

- `PERF_INSTRUMENTS="Time Profiler;Metal GPU Counters"` adds Instruments to the Metal System Trace recording; their
  tables live in the `.trace`, so it pairs with `KEEP_TRACE=1`.
- `trace_count`: rows of several tables of a kept `.trace`, in all and per process; by default the tables that
  matter for a translation layer. Measured on drawstress d3d12 under Mullion (M1 Pro, 30 s): 2559
  `graphics-compiler-spill-events` and 115 compiled shaders for the Wine process, 0 rows in the GPU counter and
  shader profiler tables.
- `perf_baseline_record`: records the same program `count` times and saves the runs as a reference in one call.
- xctrace 27.1 writes `metal-resource-allocations` and `time-profile` whole and then dies with SIGTRAP (exit 133):
  an export cut at a row boundary is read to its last row instead of failing.

## 0.6.0 — 2026-10-18

- `perf_baseline` and `perf_check`: a regression reference. `perf_baseline` saves copies of several equal recordings
  (ideally 3 or more) as a named reference in `baselines.json` beside the runs, so it outlives `KEEP_RUNS`, and
  returns the range each number spans across them. `perf_check` judges a recording against that range: `regressed`
  when FPS falls under it by more than `margin_pct` (default 3), GPU ms per frame rises over it, or encoders or
  command buffers per frame exceed it; `improved` when a number leaves the range the other way; `same` otherwise.
  The range, not one run, is the reference because 5 equal runs of drawstress d3d12 on an M1 Pro differed by 4.4 %
  in FPS and 6.1 % in GPU ms per frame. Frame pacing, short encoders and GPU idle time are reported but do not
  decide: they varied 13 % and 7 points between equal runs.
- `perf_compare` says what changed in the GPU work and where: encoders and command buffers per frame, the share of
  encoders under `short_us`, the GPU's idle share and idle ms per frame, and `labels`, each encoder label's count and
  GPU ms per frame in both runs, largest change in ms per frame first. Labels compare per frame because two
  recordings of different lengths do not compare by total time; a label missing from a run that holds the full 20
  labels is `outside_top_20`, not `gone`. A run summarized before 0.4.0 is named in `encoders.missing_in`, and the
  headline numbers still compare. Shares (short encoders, GPU idle) give their change in points, without a %.
- The `compare-layer` prompt reports `perf_compare`'s table and labels instead of rebuilding them from two
  `perf_diagnose` calls.
- Each recording names its translation layer in `layer`: the Wine version, the overrides in force (environment and
  the prefix's registry), the size and SHA-256 of `d3d12`, `d3d12core`, `d3d11`, `d3d10core` and `dxgi` in Wine and
  in the prefix, a 12-character `fingerprint` of all of it, and the program's variables (`MULLION_DIAG=profile`) with
  paths cut to file names. Native runs say they have no layer. `perf_runs` shows the fingerprint and Wine;
  `perf_compare` says whether both runs share a layer, which DLLs differ, and that different layers compare layers,
  not one change. Which copy of a DLL Wine loads is not recorded: Instruments does not keep Wine's own log.
- `perf_record.sh` keeps the caller's `WINEDLLOVERRIDES` (a Mullion built for `system32` needs `d3d12,...=n`) and
  adds `mscoree=;mshtml=` after it; before, it replaced them.
- A prefix copy of a Direct3D DLL identical to Wine's own (Wine's first boot makes one) leaves the layer
  fingerprint unchanged: the fingerprint and `differs` look at the copy Wine loads, the prefix's when it exists.
  Measured on an M1 Pro: the first drawstress run on a new prefix got a different fingerprint from the next
  three, with identical DLLs.
- Downloads are hashed in 1 MiB blocks.

## 0.5.0 — 2026-10-17

- `workload_list` and `workload_fetch`: download a test program once from this project's releases, check the
  SHA-256 this package pins and keep it in `~/Library/Caches/metal-gpu-trace`. Claude Code asks before every
  download (`anthropic/requiresUserInteraction`).
- `perf_record` records a fetched test program with `workload`, `api` and `dim`.
- First test program: bgfx 17-drawstress for macOS arm64 and Windows x64, built from source by
  `.github/workflows/workloads.yml` (release `workloads-1`). Recorded on an M1 Pro, it gives the same encoders per
  frame as a local build (2 in native Metal, 7 in D3D12 under Mullion) and FPS within 4 %.
- `compare-layer` prompt: records a test program in native Metal and under a translation layer, then diagnoses and
  compares both runs.

## 0.4.0 — 2026-10-17

- `perf_diagnose`: says whether a recording splits its GPU work into too many short encoders, as translation layers
  do, with encoders and command buffers per frame, the labels with the most GPU time and the GPU's idle time.
  Defaults (4 encoders per frame, 25 µs, 25 % short) come from bgfx 17-drawstress on an M1 Pro: 7 encoders per frame
  and 50 % under 25 µs under Mullion, 2 and 2 % in native Metal.
- Summaries gain `encoders` and `gpu_idle`, from `metal-gpu-intervals` and `metal-application-encoders-list`.
  Summaries written by older versions have neither: record again to diagnose them.
- Every tool parameter has a description; `metal-gpu-trace --version`.
- Registry files: `server.json` (MCP Registry), `glama.json`; `CHANGELOG.md`.
- `trace_tables` and `trace_query` take a run name; `perf_runs` says whether each run kept its `.trace`
  (`trace_kept`).
- A trace without `metal-gpu-intervals` fails with a hint; summaries list other missing tables in `missing_tables`.
- `capture_summary` returns `calls_total`.
- Tools carry `title`, `readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint`; `initialize`
  returns usage `instructions`.
- A recording's deadline grows with its length (10 s per recorded second plus 120 s), and one that overruns leaves
  no files behind.
- `perf-runs/` is created only when a recording needs it. Tests run under pytest; CI on macOS with Python 3.9 and
  3.13.

## 0.2.0

- First release on GitHub: `perf_record`, `perf_attach`, `perf_runs`, `perf_compare`, `trace_tables`,
  `trace_query`, `capture_summary`, `capture_records`, `gpu_family`, and the GPU family resources.
