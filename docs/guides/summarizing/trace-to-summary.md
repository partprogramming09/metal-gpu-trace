# From a trace to the summary

**Reader:** people who change `perf_report.py` or want to know which tables of a recording feed which number. Reviewed 2026-11-16.

Español: [Del trace al resumen](../../es/guides/resumir-y-analizar/del-trace-al-resumen.md)

**In short:** a `.trace` is a very large recording made by Apple's Instruments. One script asks Instruments for the tables it
needs, keeps the program's own GPU work, and writes a small summary file. If the program stopped drawing to the screen part
way through, the script notices and sets that stretch aside instead of letting it ruin the frame-rate figures.

Back to the [guide index](./index.md).

![Eight boxes in two rows joined by arrows. Top row: export the contents and tables with xctrace; check the table of contents (a decision: no metal-gpu-intervals is an error, other absent tables go to missing_tables); read the launched program's GPU work; decide whether some work was never presented. Bottom row: the frame numbers, the optional tables, pacing and hitches, and writing the files.](./img/trace-to-summary.png)
*Figure 1. What `perf_report.py` does with a `.trace`. HTML source: `docs/guides/summarizing/img/trace-to-summary.html`.*

The command is `python3 -I src/metal_gpu_trace/perf_report.py <recording.trace> [--label NAME] [--out DIR] [--no-memory] [--counters]` (`perf_report.py:1-5`, `:840-847`; the trace is **positional**, `:842`). It prints the `gpu`, `metal_memory_mib` and `process_rss_mib` blocks (`:852`) and writes the files. Everything below is **confirmed** by the lines named; running it was **not reproduced** (no `.trace` at hand).

## Step 1: export

`toc_and_tables` (`:95-123`) asks `xctrace` for the table of contents and each table, at most two `xctrace export` calls at a time (`EXPORT_WORKERS = 2`, `:40`): each export keeps a temporary store of gigabytes on a big trace, so two bound the disk needed (`:39`). Each call writes a temporary XML file (`export`, `:49-66`) that `rows` deletes after reading (`:170`).

| Case | What happens | Line |
|---|---|---|
| The `.trace` folder is missing | `FileNotFoundError: no recording at <name>: perf_record.sh deletes the .trace once its summary is written, unless KEEP_TRACE=1`; the likely cause is that the trace was already deleted | `:52-54` |
| `xctrace` 27.1 writes a table whole, then dies with `SIGTRAP` | `export` accepts the file if it ends at a row boundary or right after an empty table's schema (`complete_xml`); a file cut elsewhere is `xctrace export of <name> failed (exit N): <last line of stderr>`. A test pins the three cases (`tests/test_report.py:105-125`, inside `test_report`; not run) | `:69-78`, `:60-61`, `:62-65` |

Only the **first run** of the trace is read (xpath `run[@number="1"]`, `:90-92`). A table of millions of rows is read without building a tree: `rows` makes a first pass to find which `id`s a later `ref` names and keeps only those cells (`:131-170`). If a later step fails, the temporary files are removed anyway (`finally`, `:825-829`).

## Step 2: the table of contents and `missing_tables`

The tables the summary can read:

| Table (xctrace schema) | Needed? | What it feeds | If it is absent from the trace |
|---|---|---|---|
| `metal-gpu-intervals` | **required** (`:34`, `:194`) | every `gpu` number, `encoders`, `gpu_idle`, `frames.csv`, the hitches | `ValueError: the trace has no metal-gpu-intervals table; this Xcode may name it differently: trace_tables lists the tables it has` (`:194-196`), but see [limit 2](./limits.md) |
| `metal-current-allocated-size` | requested unless `--no-memory` (`:34`, `:639`) | `metal_memory_mib`, `metal_memory.csv`, the `memory_growth` hitch cause | with `--no-memory` it is not exported and is named in `missing_tables`; otherwise the export of an absent table fails (probable, [limit 3](./limits.md)) |
| `gpu-performance-state-intervals` | requested always (`:34`) | `gpu_performance_state_share` | the export of an absent table fails (probable, [limit 3](./limits.md)) |
| `metal-application-encoders-list` | optional (`:36`) | the labels of the encoders | no labels: encoders grouped under `?` (`:724-727`, `metrics.label_name` `:89-91`) |
| `graphics-compiler-activity-intervals` | optional | `graphics_compiler`; the `shader_compile` cause | no `graphics_compiler` key; no hitch is ever named `shader_compile` (`:774-781`) |
| `device-thermal-state-intervals` | optional | `thermal_state_share`; the `thermal` cause | neither exists; the throttling flag stays the FPS-based one (`:782-790`, `:819-820`) |
| `ProcessCPUUsage` | optional | `cpu`; each hitch's `cpu_pct` | no `cpu`, no `cpu_pct` (`:791-798`) |
| `metal-resource-allocations`, `graphics-compiler-spill-events`, `metal-command-buffer-error` | optional | `resource_allocations`, `shader_spills`, `command_buffer_errors` | no key (`:799-806`); **absent is not zero** (and no `resource_allocations` when the program has no allocation) |
| `gpu-counter-info`, `gpu-counter-value` | only with `--counters` or `PERF_INSTRUMENTS` naming Metal GPU Counters (`:42`, `:632-633`, `:640`) | `gpu_counters`; each hitch's `top_limiter` | no `gpu_counters` (`:812-824`) |

`missing_tables(toc)` (`:190-197`) is the sorted list of the tables above (memory and performance state included, though only `OPTIONAL` is optional) that the table of contents lacks. It is written to the summary (`:664`) so that "their numbers come out empty" is not mistaken for zero (`:663`); a test pins the full list for a trace with only the GPU intervals, and the error for an empty one (`tests/test_report.py:128-135`, not run; [E7](./evidence.md#e7)). **Nothing in `src/` reads the key** (`rg`; see [the data guide](../data-and-lifecycle/json-keys.md#the-summary-key-by-key)): it is for the person reading, and a gate fails on the missing value itself ([When a number is missing](./reading-and-comparing.md#when-a-number-is-missing)). It is `[]` in both real runs ([E4](./evidence.md#e4)); the three names the Windows engine always writes are a fixed list, not a reading of a trace (`perf_record_windows.py:900`, [recording guide](../recording/windows-engine.md#why-a-separate-engine-and-what-it-measures)).

## Step 3: the program's GPU work

`summarize` picks the first process whose type is `launched` or `attached` (`:643`); without one it stops with `the trace has no launched or attached process; record it with xctrace --launch or --attach` (`:644-645`). Then it reads every row of `metal-gpu-intervals` (`:674-693`). A row of **another** process adds only its duration to `by_process` (no name kept, so nothing a person runs reaches a shared summary; used only for `noisy_basis`, `other_processes`, `:584-590`). A row of **this** process keeps the duration (ms) in `frames[frame][channel]` (`vertex`, `fragment` or `compute`), the first start time of each frame, the start latency when the row has a sane one, and a span `(frame, start, duration, encoder id, command buffer id)` (`:681-693`).

## Work that was never presented

Example first: the second run of the [guide's example](./index.md#one-example-first). `unpresented(spans)` (`:206-230`) exists because Instruments numbers frames by *presents*: a program that renders without presenting (window hidden, minimized or off screen, or a long load) leaves **every later command buffer under its last frame number**. A frame number counts as stalled when it has at least `max(32, 8 × the median number of command buffers per frame)` command buffers (`UNPRESENTED_MIN_BUFFERS = 32`, `UNPRESENTED_FACTOR = 8`, `:201-202`, `:220-221`) **and** its work spans at least one second (`UNPRESENTED_MIN_S`, `:203`, `:222`).

Those frames are **left out of everything per frame**: not in `frames`, `frame_gpu_ms`, the gaps or `frames.csv` (`:696-701`, `:233-245`), and reported once in `gpu.unpresented` (when it began, how long, command buffers, GPU time; `:227-230`). The GPU time is not lost: `gpu_idle` still counts it (`idle_gaps(spans, left_out)`, `:245`).

[E5](./evidence.md#e5) shows the second run: frame 160 holds 1776 command buffers over 17.236 s and 92 % of the GPU time (`share_of_gpu_time` 0.92), from 3.637 s; the other 153 frames are the first 3.6 s. Downstream, `perf_compare` and `perf_check` add an `unpresented` entry with a note (`analysis.py:13-16`, `:30-34`, `:189-191`, `:374-376`), `perf_gate` **fails** the run (`:493`) and `suggested_actions` says to record again with the window visible (`:660-662`). Tests: `test_unpresented_tail`, `test_unpresented_spares_heavy_frames`, `test_summary_leaves_out_unpresented`, `test_unpresented_mid_run` (`tests/test_report.py:690`, `:701`, `:715`, `:765`; not run).

## Steps 4 and 5: the frame numbers, then the other tables

After the filter `summarize` builds the `gpu` block (`:703-721`), the encoder block (`:723-729`) and each optional table in turn (`:731-817`, skipping with `if "<schema>" in tables` those the trace lacks). Pacing and hitches come last (`:818-822`) because they need the compiler, thermal and memory lists. Then `frames.csv.gz` is written (`:831-834`), the `common` block is added (`:835`) and the summary is written (`:836`). `recording.finish` adds `layer`, `context`, `tier` and `retention` (`recording.py:337-351`; [recording guide](../recording/macos-journey.md#step-5-when-the-script-returns)).
