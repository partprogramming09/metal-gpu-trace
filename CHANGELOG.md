# Changelog

Versions follow [Semantic Versioning](https://semver.org); each one is a `vX.Y.Z` tag. `metal-gpu-trace --version`
and the MCP `initialize` answer (`serverInfo.version`) print the installed one.

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
