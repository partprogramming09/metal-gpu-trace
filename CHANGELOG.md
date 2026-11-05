# Changelog

Versions follow [Semantic Versioning](https://semver.org); each one is a `vX.Y.Z` tag. `metal-gpu-trace --version`
and the MCP `initialize` answer (`serverInfo.version`) print the installed one.

## Unreleased

- `perf_record` takes `example` for a workload that lists `examples` in `data/workloads.json` (`workload_list` shows
  them): its argument goes after the api's. No workload ships examples yet; the first is the bgfx examples archive.
- A macOS summary has `machine`: chip, P and E CPU cores, GPU cores and class, RAM in GiB and macOS version, with no
  host name or UUID, so numbers say where they were measured. It is `null` when the Mac that summarizes the trace has
  other RAM or macOS than the trace's device (a trace recorded elsewhere), or a fact cannot be read.

## 0.16.0 — 2026-11-02

- GPU counters: `perf_record` takes `counters=true` (or `PERF_INSTRUMENTS="Metal GPU Counters"`), and the summary gets
  `gpu_counters`: mean, p95 and max of the 31 counters (ALU, texture, buffer, last level cache and MMU limiters and
  utilization, occupancy, read and write bandwidth in GB/s) and the `top_limiter`. On a 12 s drawstress run it read
  5 382 127 samples, exactly the table's rows, in 8 s and 87 MB, line by line without building the XML tree; what is slow
  is `xctrace` exporting the table, about 10 s and 64 MB of XML per recorded second (the recording's time limit grows to
  match). The panel has a GPU counters tab. They are whole-run, also with `skip_s`. `perf_report.py --counters` reads them
  from an existing trace.
- Power: the `Power Profiler` instrument is not supported on macOS (xctrace says so), so there is no power data to read.
- `panel.json`: `perf_panel(layout=[...])` saves the tab order in the runs directory, and every panel, the live one too,
  starts from it; the viewer's own changes in the browser still win. The browser's Layout JSON is the same format.
- `perf_baseline` and `perf_baseline_record` take `skip_s`: the reference keeps each run without its start-up and
  `perf_check` applies the same cut to the run it judges (`skipped_s` says so): a steady-state check.

## 0.15.0 — 2026-11-02

- `skip_s` also on `perf_history` and `perf_ab` (which draws its verdicts without the start-up; the recordings stay
  whole). `perf_check` has none: a reference keeps whole-run summaries, so a run without its start-up would not be
  judged against like with like.
- Fix: `skip_s` with a recording that has no Metal memory (a Windows run, or `memory=false`) made `perf_compare` fail with
  `AttributeError`; found comparing a real Windows recording with a Metal one.
- The panel's help for the process memory says it is `ps`'s RSS on macOS and the working set on Windows (the same kind of
  number, counted differently), and the cards and tables show the run name without its long layer label (the header and
  the legends keep it).
- The panel warns when B has worse FPS but better GPU ms per frame than A: the limit is not the GPU. Seen on a real
  drawstress run, native Metal against Wine with Mullion (DXMT) in D3D11: 104 against 50.8 FPS, 5.9 against 4.05 GPU ms,
  and the GPU idle 80% of the time against 39%.

## 0.14.0 — 2026-11-02

- `skip_s` on `perf_compare`, `perf_gate` and `perf_panel` (and `skip_s` in the live panel's URL fragment) leaves out the
  first seconds of each recording, where shaders compile and resources load. FPS and its lows, GPU and interval ms,
  stutter, jitter, hitches and Metal memory are recomputed from the per-frame files; the CPU use is dropped; thermal
  state, process memory, encoders and GPU idle stay whole-run (`steady.whole_run` and the panel say so). Causes are kept
  for the 20 longest hitches the summary lists (`causes_partial` otherwise). On two real drawstress recordings, 2 s
  moved the hitch counts from 9 and 2 to 2 and 0, and the 1% low from 92.5 and 96.7 to 96.3 and 97.6.

## 0.13.0 — 2026-11-02

- `perf_history`: lists the runs whose name starts with a prefix, oldest first, with FPS, 1% low, GPU ms, stutter,
  hitches and peak Metal MiB, and the change from the first to the last. It flags a series that mixes Windows and
  Metal runs, or has under 3 runs.
- A summary now has `cpu` (count, mean, p50, p95 and max of the program's CPU use, from the trace's `ProcessCPUUsage`
  table; 100% is one core, so several threads add up) and each hitch has `cpu_pct`, the mean CPU over the interval before
  it: below the run's mean the program was waiting, above it was busy. `hitches.worst` lists the 20 longest hitches, not
  5. The panel shows the CPU beside each hitch's cause, the mean CPU in its data tab and the hover.

## 0.12.0 — 2026-11-02

- `perf_compare` and the panel say when a Windows run is compared with a Metal run: the result has `measure` (which side
  is which and `not_comparable`: `gpu_ms_mean`, `gpu_ms_p95` and `metal_mib_peak`, since PresentMon and Instruments
  measure GPU time differently and only Metal records memory) and no encoder numbers. The Markdown names the same
  metrics; the panel warns, shows those rows as not comparable and marks a Windows run.
- `perf_gate`: checks a run against budgets you give (`fps_min`, `fps_1pct_low_min`, `stutter_rate_pct_max`,
  `gpu_ms_p95_max`, `hitches_max`, `metal_mib_max`) and returns pass or fail with each limit and value; a number the run
  lacks fails its budget.
- `perf_baseline` also returns `spread_pct`, each range's width as a % of its midpoint: the noise equal runs show, which
  a change has to exceed.
- The panel has an Encoders tab: the encoders with the most GPU time per run and, for two runs, what changed between
  them (not for Windows runs, which have none). Its layout key is now `v3`.
- `perf_check` judges a Windows run against a Metal reference (or the reverse) on FPS alone: GPU ms and the encoder
  numbers go to `unchecked` and `hint_measure` says why. `perf_ab` records both sides on one machine, so it needs no change.
- `perf_panel`: writes `<name>.panel.html`, one file with the data inside, for one or two runs (`preset` `fps` or
  `compare`). It has no server and no network use, carries no path and shows at most 5000 points per series (every
  hitch kept). It has five tabs: a summary with a verdict and the key numbers, the frames with a table of hitches and
  their causes, memory and thermal state, A against B, and the full data. A `?` beside each metric says what it
  measures and a warning says when a comparison is not reliable (under 100 frames, one recording per side, different
  layers). Spanish and English; the viewer hides and reorders tabs and exports the layout as JSON.
- `--http` also serves the panel live: `GET /panel` is the page (no data) and `GET /panel/data?runs=a,b&preset=fps` its
  data, with the same token, Host and Origin checks as `/mcp`. Open `/panel#token=...&runs=a,b`; the token stays in the
  URL fragment, which the browser never sends and the page removes. Without `runs` it shows the newest run, and the
  page asks again every 10 s, so a finished recording appears by itself.

## 0.11.0 — 2026-11-02

- `perf_ab`: records a program with two environments (`env_a`, `env_b`) in the order A B B A and says per metric whether
  B is better, worse or the same, only when every B value is outside A's range. `perf_record` and the tools built on it
  take `env` (`NAME=VALUE` pairs). It works on Windows too, where the pairs reach the program through `PERF_ENV`.

- A Metal summary now carries `fps_1pct_low`, `fps_01pct_low`, `stutter_rate_pct`, `frame_jitter_ms` and
  `throttling_analysis` in `gpu` (the fields `perf_diagnose` reads, which only Windows summaries filled, so its stutter
  verdict was always UNKNOWN), plus `graphics_compiler`, `thermal_state_share` and `hitches`: each frame over 1.5 median
  intervals and over 8 ms (so a 500 FPS program's 3 ms frames are not stutter) named `shader_compile`, `thermal`, `memory_growth`, `gpu_heavy` or `cpu_or_wait` from the trace. `perf_diagnose`
  returns `hitches`, adds a recommendation for the top cause and no longer suggests `FlipQueueSize` for a Metal run.

- `windows/winbridge-run-tests.ps1`: a script that updates a checkout on a real Windows machine and runs
  `test_perf_record_windows.py`, written as a WinBridge `RunTask` task. The README says how to register it.

## 0.10.2 — 2026-11-02

- Workload `drawstress` takes `api=vk`: the same program through Vulkan on MoltenVK (bgfx's Vulkan backend, already in
  the shipped binary). Set `METAL_TRACE_MOLTENVK` to a directory with an arm64 `libMoltenVK.dylib`; the run's `layer`
  names MoltenVK and the library's SHA-256, so `perf_compare` flags a comparison with native Metal as two layers.

- `perf_record.sh` also refuses a native program with the execute bit but no program inside (no Mach-O or `#!` header):
  `X is not a program the system can run`, exit 2, instead of an unclear `No such file ... .xml`.
- The CI runs the self-check on macOS too, but only when `perf_record.sh`, `perf_report.py` or the server change.

## 0.10.1 — 2026-11-02

- `perf_record.sh` refuses a native program that is not an executable file (`X is not an executable file`, exit 2)
  before it starts Instruments, and a failed recording deletes its partial files and frees its lock.
- Stability, from a sweep with real Instruments recordings and fuzzed requests:
  - A game that ignores SIGTERM no longer outlives a cancelled or overrun recording: it gets SIGTERM, then SIGKILL.
    One such game kept running for 40 minutes after its server was killed.
  - `perf_record.sh` stops its recording, program and lock, and deletes the partial files, when the server that started
    it dies (`PERF_PARENT_PID`, set by the server); the resident-memory sampler no longer outlives the script.
  - Tool calls wait in one queue of 64 served by one worker thread, instead of one thread per call; a call past the
    limit is refused at once. Cancelling a call still waiting in the queue answers it at once, not after the call ahead.
  - `--http` drops a client that stalls in the middle of its request after 15 s, so it cannot hold threads forever.
  - A `notifications/cancelled` with a malformed `params` or `requestId` is ignored instead of answered with an error.
- The Windows job of the CI runs only when a file it covers changes.

## 0.10.0 — 2026-11-02

- `metal-gpu-trace --http [--port N]` serves the tools over Streamable HTTP at `POST /mcp` on 127.0.0.1 only. It needs
  `METAL_TRACE_TOKEN` (16+ characters) and a matching bearer token on every request, refuses a foreign Host or Origin,
  and cancels a running call on `notifications/cancelled`. It does not stream progress.

## 0.9.1 — 2026-11-02

- On Windows, `perf_record` and `perf_attach` report progress every 5 s and stop on `notifications/cancelled`, deleting
  the partial files and killing the launched program, as on macOS.

## 0.9.0 — 2026-11-02

- Progress and cancellation. A client that sends a `progressToken` with `tools/call` gets `notifications/progress`
  every 5 s while `perf_record`, `perf_attach` or `perf_baseline_record` run (seconds elapsed of the deadline), instead
  of silence for up to 630 s. `notifications/cancelled` stops the recording, deletes its partial `.trace` and
  `instruments*.ktrace`, and answers the call with an error. Tool calls now run on a worker thread, one at a time, so
  `ping` and cancellation are read while a recording runs. On Windows the recording is not cancellable or reported yet.
- `tools/list` gives every tool an `outputSchema` (an object; `perf_runs`, `trace_query` and `capture_records` name
  their page fields), so clients can validate `structuredContent`. A tool that returns anything but an object is an
  error, not a malformed result.
- `metal-gpu-trace check RUN BASELINE [--margin-pct N]`: `perf_check` for CI, one JSON line and an exit code (0 same or
  improved, 1 regressed, 2 could not be judged). README shows a self-hosted macOS job.
- `perf_compare` takes `markdown=true` and adds the headline, encoder and label numbers as Markdown tables for a PR.
- `perf_export_trace` writes a run's GPU frames as `<run>.chrome-trace` (one slice per frame) for ui.perfetto.dev.
  Per-encoder slices are not available: the summary keeps encoder totals per label, not each encoder.
- Each saved run is an MCP resource: `metal-trace://runs/<run>` (listed as a resource template) reads its summary.

## 0.8.4 — 2026-11-01

- Recording no longer fills the disk. `xctrace record` leaves a temporary `instruments*.ktrace` (5 to 16 GB for a
  Wine D3D12 recording) in `$TMPDIR` that nothing deleted: 14 of them, 65 GB, filled a Mac in one afternoon.
  `perf_record.sh` now deletes the ones its own run created, even when the run fails, and the server does the same
  when it stops a recording that overran its deadline.
- `perf_record.sh` checks the free disk in `$TMPDIR` and beside the recording before it starts, and refuses (exit 4)
  below `2 + 0.8 GB per second` (26 GB for 30 s, 50 GB for 60 s; 48 GB peak measured for 60 s of Wine D3D12).
  `PERF_MIN_FREE_GB` overrides it. The server's instructions say so.
- `perf_report.py` runs at most 2 `xctrace export` at a time (`EXPORT_WORKERS`), not one per table: each keeps a
  temporary store of gigabytes, and running them in parallel saved only about 8 s out of 64.

## 0.8.3 — 2026-11-01

- `perf_record` and `perf_baseline_record` take `memory` (default true): `memory=false` sets `PERF_MEMORY=0` for that
  recording, so a client no longer needs the variable in the server's environment.

## 0.8.2 — 2026-11-01

- `PERF_MEMORY=0` (and `perf_report.py --no-memory`) skips the Metal memory table, the slowest to read: 41 % less time
  to summarize a 626 MB Wine D3D12 trace (about 70 s to 42 s, median of 3). The summary then has no `metal_memory_mib`
  and no `.metal_memory.csv`; everything else is identical. Memory stays on by default.

## 0.8.1 — 2026-11-01

- `perf_record` waits up to 15 s per recorded second plus 180 s (was 10 s plus 120 s) before stopping a recording.
  A 30 s Wine D3D12 recording (a 614 MB trace that `xctrace` takes minutes to close, then 93 s to read) overran the old
  420 s limit and saved nothing; it now has 630 s.

## 0.8.0 — 2026-11-01

- `perf_report.py` exports the table of contents and its tables at the same time instead of one after another, so a
  summary takes about as long as the slowest export; an optional table the trace lacks is skipped, and a failure
  leaves no temporary file behind.

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
