# Changelog

Versions follow [Semantic Versioning](https://semver.org); each one is a `vX.Y.Z` tag. `metal-gpu-trace --version`
and the MCP `initialize` answer (`serverInfo.version`) print the installed one.

## Unreleased

- New workload `godot`: a lit 3D scene Godot 4.7.2 builds from code (400 meshes, 8 omni lights, a shadowed sun, Forward+, no
  imported assets), with `api` mtl (Godot's Metal driver) and d3d12 (under Wine). A workload entry can now list `downloads`:
  `workload_fetch` downloads each zip from its publisher (here godotengine/godot-builds, 171 MB for macOS and 86 MB for
  Windows), checks the SHA-512 `data/workloads.json` pins, refuses links and paths outside the folder, unzips it with its
  file modes, and `args` may use `{dir}` for the workload's folder. The project archive (1.5 KB, release `workloads-9`) is packed
  by the workloads workflow with `only_godot`. Run through the tools: the fetch took 9 s for 257 MB, native Metal 121 FPS and
  Wine D3D12 120 FPS, 14 encoders per frame in both. With `perf_cold_warm` (30 s runs) `first_seen_hitches` was 0 in both
  because Godot's shader-compile hitches (3 in Metal, 7 in Wine) recur identically in the second run.

- `example_traits` also gives `d3d12_encoders_per_frame`, the median under Wine with Mullion's D3D12 layer: 7 to 23 for most
  examples (2 to 14 in native Metal), 16 for 22-windows, 38-bloom, 41-tess and 46-fsr, and 312 for 26-occlusion (106 render, 99 compute and 104 blit
  encoders per frame against 4 in native Metal, at 80 FPS instead of 120). The 21 examples added after the first nine were
  recorded for 30 s each under Wine D3D12 (116 to 124 FPS except 26-occlusion); the first nine's counts are the earlier
  measurements. D3D11 has not been run for the new ones. Encoder labels are the generic "Render Command", "Blit Command" and
  "Compute Command" in both native and Wine runs, with no view names. 30-picking, the read-back example: 4 blit encoders per
  frame under Wine against 1 native, with the same GPU time (1.49 ms Wine, 1.51 native) and a hitch rate in the range of two
  native 10 s runs (48.6 a minute under Wine for 30 s; 17 and 42 native): no read-back stall seen.

## 0.21.0 — 2026-11-05

- `metal_memory_mib.trend_mib_per_min`: the slope of the Metal memory samples of the second half of the recorded time, in MiB
  per minute, to tell a program that keeps growing after start-up from one that settles; `null` with under 5 samples there or
  under 5 s between them. It is in a recording's own summary only: `skip_s` rebuilds `metal_memory_mib` without it, and
  `perf_compare`, the panel and the history do not show it.
  Real 40 s recordings, native: 41-tess (peak 3265 MiB, final 1738) -0.01 and 21-deferred (55 MiB) 0.0, both flat; a growing
  program has only been seen in the unit test, not in a real recording. A first 21-deferred recording of 40 s overran the 780 s
  limit and was stopped; the repeat took 240 s.

- `bgfx-examples` (release `workloads-8`, 55 MiB) holds eleven more examples: 05-instancing, 22-windows, 26-occlusion, 27-terrain,
  33-pom, 37-gpudrivenrendering, 39-assao, 41-tess, 45-bokeh, 50-headless and 51-gpufont, with classes geometry, multi_surface,
  occlusion and offscreen besides the earlier ones. Each ran in native Metal for 15 s and loaded all its files. Six ran paced at
  120 FPS (2 to 4 encoders, 0.17 to 0.74 GPU ms), and 39-assao too but heavier (below); 26-occlusion, 37-gpudrivenrendering, 41-tess and 45-bokeh ran unpaced at 3600,
  3900, 2600 and 700 FPS; 39-assao took a median 6 ms of GPU and 4 encoders per frame (its first 15 s recording had one start-up
  frame of 15 s with 22 475 encoders, which made the mean 31 ms and 41: read medians, or use `skip_s`), and 41-tess peaked at
  3.2 GiB of Metal memory. None has run under Wine yet.

- `perf_cold_warm` records a program twice in a row and returns each run's hitches, hitches per minute and graphics compiler
  time, `first_seen_hitches` (shader_compile hitches only the first run has) and `extra_hitches_in_first` (any cause). It does
  not clear Metal's shader cache, and runs on macOS only. `first_seen_hitches` is the first run's shader_compile hitch count
  minus the second's, never below 0. On 21-deferred, native, 10 s each: the first run 16 hitches (100 a minute), the second 3,
  and `first_seen_hitches` 0 because neither run had a shader_compile hitch (the graphics compiler was busy 0.3 ms in both), so
  that run's first-run cost was not a shader compile. One pair of runs only.
- `hitches.per_minute` in every summary of a recording and in the summaries `skip_s` recomputes: the hitch count over the
  recorded minutes, `null` with under two frames.

## 0.20.0 — 2026-11-05

- `bgfx-examples` (release `workloads-7`, 38 MB) holds ten more examples: 08-update, 10-font, 16-shadowmaps, 19-oit, 20-nanovg,
  30-picking, 32-particles, 40-svt, 46-fsr and 47-pixelformats, with classes ui_text, shadows, overdraw, readback, upscale and
  format_coverage. Each ran in native Metal at about 120 FPS for 10 s (20 s for 20-nanovg): 08-update 14 encoders per frame and
  0.98 GPU ms, 46-fsr 5 and 2.4 ms with 42 hitches in 973 frames, the others 2 to 5 encoders and 0.15 to 1.5 ms; none has run
  under Wine yet. 20-nanovg's first 10 s run, with its images read from disk for the first time, gave 287 frames and 12 ms of
  GPU time per frame, and the 20 s run after it 2344 frames and 0.51 ms: skip the start-up with `skip_s`. 40-svt writes a 370 MB
  tile cache to `temp/` in the workload's folder on its first run (about 1.5 s) and crashes without that folder, which the
  archive now holds; 20-nanovg stops loading at the first missing `images/imageN.jpg`, so the archive holds all twelve.

- `workload_list` gives each bgfx example in `bgfx-examples` an `example_traits` entry: its `class` (cpu_submit, textured,
  postprocess, gpu_bandwidth, compute, gpu_alu, streaming, indirect) and `native_encoders_per_frame`, the count measured in native
  Metal on an M1 Pro, so a recording can be checked against a known answer.

- With `MTL_SHADER_VALIDATION=1` or `MTL_DEBUG_LAYER=1` in `env`, a native or Wine recording keeps the program's output and the
  summary gets `validation`: `messages`, `by_kind` and up to five `examples` of Metal's validation messages. Shader validation
  does report a store outside a buffer (offset 4 000 000 in a 4096-byte buffer, a compute kernel), which the command buffer
  itself finishes without error; `perf_record` turns on `MTL_SHADER_VALIDATION_REPORT_TO_STDERR`, without which the message
  does not reach the program's output. Checked on a real native recording of that kernel (`messages` 2: the layer printed the
  store twice); not checked under Wine. Messages are grouped by kind (20 kinds at most, the rest under `other`) with paths
  replaced by `<path>`. A `DYLD_*` variable in `env` turns the capture off with a warning: the shell that collects the output
  drops it. Validation slows the GPU: do not compare its ms with a normal run.

## 0.19.0 — 2026-11-05

- With `counters=true`, each hitch in `hitches.worst` has `window_ms` (the interval before the late frame) and `top_limiter`:
  the Limiter counter with the highest mean in that window, from the GPU counters kept as means per 10 ms. On a 3 s drawstress
  recording with 61 start-up hitches, the 20 listed ones named Texture Write, GPU Last Level Cache and ALU Limiter depending
  on the window, while the whole run's main limiter was the last level cache. Every hitch has `window_ms`, with or without
  counters.
  The window is read in whole 10 ms bins (the one that starts at its end left out), and `top_limiter` is `null` when no sample
  falls in it.
  Cost, measured on a 20 s drawstress recording with counters (10.4 million samples): 259 s to summarize it, 3.7 GB peak resident
  memory for the process tree (xctrace's export dominates); the extra reading adds about 20 % to the counter parsing itself.

## 0.18.0 — 2026-11-05

- `perf_compare` returns `gpu_state` when two runs spent their time in different GPU performance states (the shares of
  `gpu_performance_state_share` weighted Minimum 0, Medium 1, Maximum 2, a gap of 0.25 or more). Measured with an unlocked
  Mac: a native Metal run paced at 120 FPS sits 100 % in Minimum with the GPU idle 82 to 98 % of the time, and the same
  work takes more GPU ms: 21-deferred 1.75 ms against 0.27 ms unpaced, 01-cubes 0.20 against 0.11. So the 0.17.0 advice
  to compare GPU ms when FPS is paced was incomplete: GPU ms follow the performance state too. The `screen` note and
  the `perf_diagnose` vsync recommendation say so now. Two paced runs, such as native Metal and D3D12 under Wine with
  Mullion (1.75 and 2.11 ms for 21-deferred), do compare.
- Both READMEs document what 0.17.0 added (the `mtl-x64` api, `size` and `example`, the `bgfx-examples` workload, the two
  macOS levers, and a section on reading numbers across runs: screen lock, vsync, GPU performance state), `perf_sweep`
  lists `size`, and `es/README.md` gains the seven tool rows it lacked (`perf_ab`, `perf_sweep`, `perf_gate`,
  `perf_history`, `perf_panel`, `perf_export_trace`, `presentmon_install`). A test now requires a table row for every tool
  in both READMEs.
- The screen lock is confirmed as what left native Metal unpaced: on the same Mac and the same examples the runs went from
  3 000 to 4 000 FPS with the session locked to 120 FPS (vsync) once it was unlocked.

## 0.17.0 — 2026-11-05

- Workloads. `bgfx-examples` (release `workloads-4`, 25.2 MiB) holds nine bgfx examples (01-cubes, 06-bump, 09-hdr,
  21-deferred, 24-nbody, 31-rsm, 35-dynamic, 38-bloom, 48-drawindirect) for native Metal, D3D11 and D3D12:
  `perf_record(workload="bgfx-examples", api=..., example="21-deferred")`; `workload_list` shows the examples. All nine
  ran under Wine with Mullion in D3D11 and D3D12 at about 120 FPS (vsync), for example in D3D12 01-cubes 0.58 GPU ms and
  7 encoders per frame, 21-deferred 2.08 ms and 10, 31-rsm 6.36 ms and 10. drawstress moves to `workloads-3` (9.3 MB):
  it takes `size` and has the api `mtl-x64`, native Metal built for x86_64 and run under Rosetta like Wine's programs
  (its layer is named `rosetta`, so `perf_compare` against `mtl` says it compares two layers: 438 against 735 FPS at
  dim 20). `workloads.yml` builds both archives into the release tag in its `default:` line; run it with a new tag each
  time, because a rebuilt archive has another SHA-256 and would break the installs that pin the old one. `dim` on a
  workload without `dim_variable` is refused instead of failing with `KeyError`.
- `perf_record` and the tools that pass its arguments on take `size` (`"1920x1080"`, for a workload that lists
  `size_variables`: drawstress reads `DRAWSTRESS_WIDTH` and `DRAWSTRESS_HEIGHT`), and two macOS levers.
  `memory_free_pct` (20 to 60) holds the whole Mac at that percentage of RAM free while recording
  (`memory_pressure -p N -y S`) and stops it when the recording ends or fails. `background` runs the program under
  `taskpolicy -b`: at dim 20 FPS fell from 723 to about 108, so it is a throttle, not a switch to the efficiency cores.
  `memory_free_pct=30` left drawstress at 728 FPS and cut its resident memory (p95 165 to 118 MiB). Lower power mode needs
  `sudo pmset` and is not offered. At dim 10, GPU time went from 0.15 ms at 1280x720 to 0.34 ms at 2560x1440.
- `perf_sweep` records one run per value of `dim`, `size`, `example`, `api` or an environment variable (`env:NAME`),
  2 to 8 values and up to 24 recordings, and returns the median FPS, 1 % low, GPU ms and stutter per value; with 3 or
  more numeric values it fits GPU ms per frame on the value (fixed ms and ms per draw for `dim`) with its r2.
- A macOS summary has `machine`: chip, P and E CPU cores, GPU cores and class, RAM in GiB, macOS version and
  `screen_locked`, with no host name or UUID. It is `null` when the Mac that summarizes the trace has other RAM or macOS
  than the trace's device, or a fact cannot be read. `perf_compare` returns `screen` when one run was recorded with the
  screen locked and the other not: a locked session may leave frames unpaced by the display (native Metal ran at 735 to
  4 000 FPS on a locked session, against 120 in vsynced runs), so compare GPU ms per frame, not FPS.
- A macOS summary has `gpu_activity`, from the GPU driver's counters (`ioreg`, no sudo) sampled once a second into
  `<run>.agx.csv`: device, renderer and tiler utilization, the growth of `SplitSceneCount` (`split_scenes`) and of
  `recoveryCount` (`recoveries`, `gpu_recovered`), and the driver's memory in use. The counters cover the whole GPU, not
  only the recorded program.
- A macOS summary has `resource_allocations`, from the `metal-resource-allocations` table every recording already holds
  (the `Metal Resource Events` instrument is not needed): the program's allocation `events`, `mib` allocated (a running
  total, not memory in use), `per_frame`, `by_type`, `after_3s` (past the start-up) and `per_second`; and
  `command_buffer_errors`, the rows of `metal-command-buffer-error`. Reading them adds about 5 s per 8 s of recording.
  Real runs: drawstress native 3.0 allocations per frame (about one a drawable's texture), 48-drawindirect in D3D12 under
  Wine with Mullion 8.0, nearly all buffers (different programs: not a comparison of layers); no command buffer errors.
- `perf_diagnose` returns `display_synced_hz` and `gpu_activity`, and recommends: comparing GPU ms, not FPS, when the FPS
  sits within 1 % of a common display rate (24 to 240 Hz) with a 95th percentile frame interval no more than 30 % above
  the median (D3D11 under Wine at 118.9 FPS gives 120, native Metal at 735 gives none); and a look at the run when the
  GPU recovered during it (a hang or a command that timed out) or split scenes.

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
