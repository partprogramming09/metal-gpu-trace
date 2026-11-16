# Summarizing and analyzing

**Reader:** people who read a summary or a comparison and want to know where each number comes from and when not to trust it, or who change `perf_report.py`, `analysis.py`, `metrics.py` or `experiments.py`. Reviewed 2026-11-16.

Español: [Resumir y analizar](../es/guides/resumir-y-analizar.md)

This page follows a recording after it is made: how `perf_report.py` turns an Instruments `.trace` into the `<run>.json`
summary, how every headline number in it is computed (with the formula and the line), what `analysis.py` does when it reads
summaries back and compares them, what the experiments in `experiments.py` add, how "better", "worse" and "same" are decided
and how noise is handled, and what happens when something fails. It does not repeat [Data and its
lifecycle](./data-and-lifecycle.md) (the summary's keys one by one, the generations of the format, which file is deleted
when) or [Recording](./recording.md) (how the `.trace` is made, the lock, the Windows engine); it links to them where the
story continues.

How to read the labels: every technical claim is **confirmed** (with `file:line`, checked with `rg` or `sed` on
2026-11-16 against the working tree, which is 0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`), **probable**
(read from the code but not run here) or **speculation** (a guess about why). **Not verified** marks an outside fact that
was not checked against its source. Lines move when the code changes: search the name, not only the number. Every number
comes with the command that produced it, in [Evidence](#evidence-the-commands-and-their-real-output). **Not reproduced**
means the behaviour could not be run for this page. Two limits apply. First, the repository has no `.trace` to read (the
`perf-runs/` folder of the clone holds two finished summaries and their tables, and nothing else), and running `xctrace`
needs a recording, so **`perf_report.py` was not run at all**: what it does with a trace is read from its code, and the
tests that pin it are named instead. Second, the session that wrote this page could run read-only shell commands (`rg`,
`sed`, `jq`, `awk`) and could not run Python, so **no tool of `analysis.py` was run either**: the numbers it would
produce are evaluated by hand from the formulas of the code, on the two real summaries, and the page says so each time.
The tests named were **not run** for this page.

## One example first

Two recordings of the same program sit in a runs folder, 20 seconds each (they are `a2-proof-first_20261115-085621` and
`a2-proof-second_20261115-085735`; the names are the labels plus a time stamp). Their summaries say, side by side
(the commands are E2 and E3):

| | first | second |
|---|---|---|
| `gpu.frames` | 2045 | 153 |
| `gpu.fps_estimate` | 105.4 | 102.1 |
| `gpu.fps_1pct_low` | 96.2 | 40.8 |
| `gpu.stutter_rate_pct` | 0.29 | 2.63 |
| `gpu.unpresented` | absent | present: 1776 command buffers after 3.637 s |

What a reader asks, and where this page answers:

1. *Where does 105.4 come from?* From the **median gap between frame starts**, 9.4845 ms: `1000 / 9.4845 = 105.4`
   ([fps_estimate](#fps-estimate)). The page recomputes it from `frames.csv` and gets the same number (E3).
2. *Why does the second run have 153 frames in 20 seconds?* The program **stopped presenting** at 3.6 s (a hidden
   window is the usual cause), so Instruments stopped numbering frames and the remaining 17 s of GPU work were left out
   of the frame numbers (`unpresented`, [below](#work-that-was-never-presented)). FPS 102.1 is the speed of the first
   3.6 s only.
3. *Is 102.1 against 105.4 a regression?* `perf_compare` reports the change (-3.3, -3.1 %) and nothing else. `perf_check`
   judges against a **range** with a 3 % margin; against a one-run reference, 102.1 is under `105.4 × 0.97 = 102.238`, so it
   would say `regressed`, on a run whose own summary says it stopped presenting (E6). That is why the page spends a section
   on [noise](#better-worse-same-and-noise).

## Why this part is shaped this way

| Choice | Why | Alternatives that were left out |
|---|---|---|
| The summary is a short JSON read from the trace once, and the `.trace` is deleted | A `.trace` is hundreds of MB and is read by `xctrace` in minutes; everything the tools need fits in a file of a few KB plus two tables (see the [data guide](./data-and-lifecycle.md)). The recording script deletes the trace right after the report unless `KEEP_TRACE=1` (`perf_record.sh:160-163`) | Re-reading the trace on every question: **speculation** that it was left out because of the time and disk each read costs (`perf_report.py:39-41`, `:126-165`); no ADR records the choice (ADR-0006 is about keeping the trace, not about this) |
| `perf_report.py` is also a script run by path | `perf_record.sh` calls `python3 -I perf_report.py <trace>` (`perf_record.sh:160`) and the file adds the package to the path itself (`perf_report.py:24-26`) | A module only: the script must work with `-I`, which ignores the environment |
| The numbers both platforms share live in `metrics.py` | Windows has no `.trace`, but its summary has the same shape: `frame_pacing`, `stats` and `common_block` are one copy (`metrics.py:1-2`, `perf_record_windows.py:489`, `:917`) | Two copies of each formula: the Windows ones would drift |
| The reader never recomputes from the trace, only from `frames.csv` | `skip_s` recomputes FPS, lows, stutter and hitches from the per-frame table (`analysis.py:552-599`); the other keys stay whole-run and say so (`steady.whole_run`) | Keeping the whole trace to recompute anything: it is the trace the project deletes |
| "Better" means outside a **range**, not a different number | Equal runs differ by themselves: 5 runs of one program differed by 4.4 % in FPS and 6.1 % in GPU ms (`CHANGELOG.md`, the `perf_baseline` entry; not re-measured for this page), so a single run is no reference (`analysis.py:259-268`) | A fixed percentage on one run: it would call noise a regression, as the [example](#one-example-first) shows |
| The decision uses few numbers | Frame pacing, short encoders and GPU idle time "vary too much between equal runs": 13 % and 7 points in the same changelog entry (`analysis.py:338-340`) | Judging on everything: more false alarms |
| The 100-frame rule is a flag, not a refusal | `too_short` and a `hint` are added, the answer is still computed (`analysis.py:187`, `:377-378`, `:498-499`) | Refusing short runs: the person would get nothing instead of a number with a warning |

## The pieces and where they live

| Piece | File | What it does |
|---|---|---|
| The summarizer | `perf_report.py` (`summarize` `:627`, `main` `:840`) | Reads a `.trace` through `xctrace`, writes `<label>.json`, `.frames.csv.gz`, `.metal_memory.csv.gz` |
| The export and parsing | `perf_report.py` (`export` `:49`, `toc_and_tables` `:95`, `rows` `:143`) | One `xctrace export` per table, two at a time; rows resolved from xctrace's `id`/`ref` cells |
| The statistics | `perf_report.py` (`frame_pacing` `:253`, `attribute_hitches` `:283`, `unpresented` `:206`, `noisy_environment` `:565`) | The numbers of the [next section](#how-each-number-is-computed) |
| What both platforms share | `metrics.py` (`stats` `:75`, `encoder_stats` `:94`, `idle_gaps` `:122`, `common_block` `:49`) | The same formulas for macOS and Windows |
| Reading and comparing | `analysis.py` | `perf_runs`, `perf_compare`, `perf_baseline`, `perf_check`, `perf_history`, `perf_gate`, `perf_diagnose`, `perf_memory_breakdown` |
| Experiments | `experiments.py` | `perf_baseline_record`, `perf_ab`, `perf_cold_warm`, `perf_sweep` (they record, then call `analysis`) |

## From a `.trace` to the summary

![Eight boxes in two rows joined by arrows. Top row: export the contents and tables with xctrace; check the table of contents (a decision: no metal-gpu-intervals is an error, other absent tables go to missing_tables); read the launched program's GPU work; decide whether some work was never presented. Bottom row: the frame numbers, the optional tables, pacing and hitches, and writing the files.](/diagrams/analysis-trace-to-summary.png)
*Figure 1. What `perf_report.py` does with a `.trace`. HTML source: `docs/diagrams/analysis-trace-to-summary.html`.*

The command is `python3 -I src/metal_gpu_trace/perf_report.py <recording.trace> [--label NAME] [--out DIR] [--no-memory]
[--counters]` (`perf_report.py:1-5`, `:840-847`); the trace is a **positional** argument (`:842`). It prints the `gpu`,
`metal_memory_mib` and `process_rss_mib` blocks (`:852`) and writes the files. Everything below is **confirmed** by the lines
named; running it was **not reproduced** (no `.trace` at hand).

### Step 1: export

`toc_and_tables` (`:95-123`) asks `xctrace` for the table of contents and for each table, with at most two
`xctrace export` calls at a time (`EXPORT_WORKERS = 2`, `:40`): each export keeps a temporary store of gigabytes on a big
trace, so two bound the disk it needs (`:39`). Each call writes a temporary XML file (`export`, `:49-66`) that `rows`
deletes after reading (`:170`).

- A missing `.trace` folder is `FileNotFoundError: no recording at <name>: perf_record.sh deletes the .trace once its summary
  is written, unless KEEP_TRACE=1` (`:52-54`): the likely cause is simply that the trace was already deleted.
- `xctrace` 27.1 sometimes writes a table whole and then dies with `SIGTRAP`. `export` accepts that file when it ends at a
  row boundary or right after an empty table's schema (`complete_xml`, `:69-78`, `:60-61`); a file cut anywhere else is
  `xctrace export of <name> failed (exit N): <last line of stderr>` (`:62-65`). A test pins the three cases
  (`tests/test_report.py:105-125`, inside `test_report`; not run).
- The tables come from the **first run** of the trace only: the xpath says `run[@number="1"]` (`:90-92`).
- A table with millions of rows is read without building a tree: `rows` makes a first pass over the file to find which
  `id`s a later `ref` names, and keeps only those cells (`:131-170`).
- The temporary files are removed even when a later step fails (`finally`, `:825-829`).

### Step 2: the table of contents and `missing_tables`

The tables the summary can read:

| Table (xctrace schema) | Needed? | What it feeds | If it is absent from the trace |
|---|---|---|---|
| `metal-gpu-intervals` | **required** (`:34`, `:194`) | every `gpu` number, `encoders`, `gpu_idle`, `frames.csv`, the hitches | `ValueError: the trace has no metal-gpu-intervals table; this Xcode may name it differently: trace_tables lists the tables it has` (`:194-196`), but see [limit 2](#known-limits) |
| `metal-current-allocated-size` | requested unless `--no-memory` (`:34`, `:639`) | `metal_memory_mib`, `metal_memory.csv`, the `memory_growth` hitch cause | with `--no-memory` it is not exported and is named in `missing_tables`; otherwise the export of an absent table fails (probable, [limit 3](#known-limits)) |
| `gpu-performance-state-intervals` | requested always (`:34`) | `gpu_performance_state_share` | the export of an absent table fails (probable, [limit 3](#known-limits)) |
| `metal-application-encoders-list` | optional (`:36`) | the labels of the encoders | no labels: encoders are grouped under `?` (`:724-727`, `metrics.label_name` `:89-91`) |
| `graphics-compiler-activity-intervals` | optional | `graphics_compiler`; the `shader_compile` cause | no `graphics_compiler` key; no hitch is ever named `shader_compile` (`:774-781`) |
| `device-thermal-state-intervals` | optional | `thermal_state_share`; the `thermal` cause | no `thermal_state_share`; no `thermal` cause; the throttling flag stays the FPS-based one (`:782-790`, `:819-820`) |
| `ProcessCPUUsage` | optional | `cpu`; each hitch's `cpu_pct` | no `cpu`; hitches have no `cpu_pct` (`:791-798`) |
| `metal-resource-allocations` | optional | `resource_allocations` | no key (also none when the program has no allocation) (`:799-802`) |
| `graphics-compiler-spill-events` | optional | `shader_spills` | no key (`:803-804`) |
| `metal-command-buffer-error` | optional | `command_buffer_errors` | no key: **absent is not zero** (`:805-806`) |
| `gpu-counter-info`, `gpu-counter-value` | only with `--counters` or `PERF_INSTRUMENTS` naming Metal GPU Counters (`:42`, `:632-633`, `:640`) | `gpu_counters`; each hitch's `top_limiter` | no `gpu_counters` (`:812-824`) |

`missing_tables(toc)` (`:190-197`) is the list, sorted, of the tables above (memory and performance state included, though
only `OPTIONAL` is optional) that the table of contents does not have, and it is written to the summary as `missing_tables`
(`:664`). It is there so that "their numbers come out empty" is not mistaken for zero (`:663`). A test pins the full list for a
trace that has only the GPU intervals, and the error for an empty one (`tests/test_report.py:128-135`, not run; E7).
**Nothing in `src/` reads the key** (`rg`; see [the data guide](./data-and-lifecycle.md#the-summary-key-by-key)): it is for the
person reading the summary, and a gate does not look at it; it fails on the missing value itself ([When a number is
missing](#when-a-number-is-missing)).

On a real summary of this repository the list is `[]` for both runs (E4): every table was there. The three names that the
Windows engine always writes are a fixed list, not a reading of a trace (`perf_record_windows.py:900`,
[recording guide](./recording.md#why-a-separate-engine-and-what-it-measures)).

### Step 3: the program's GPU work

`summarize` picks the first process whose type is `launched` or `attached` (`:643`); without one it stops with `the trace has
no launched or attached process; record it with xctrace --launch or --attach` (`:644-645`). Then it reads every row of
`metal-gpu-intervals` (`:674-693`):

- A row of **another** process adds its duration to `by_process`: no name is kept, so nothing a person runs reaches a shared
  summary (`other_processes`, `:584-590`). It is used only for `noisy_basis`.
- A row of this process adds its duration (ms) to `frames[frame][channel]`, where the channel is `vertex`, `fragment` or
  `compute` (`:681-685`), keeps the first start time of each frame (`:690`), the start latency when the row has a sane one
  (`:686-689`) and a span `(frame, start, duration, encoder id, command buffer id)` (`:692-693`).

### Work that was never presented

`unpresented(spans)` (`:206-230`) exists because of how Instruments numbers frames: by *presents*. A program that renders
without presenting (its window hidden, minimized or off screen, or a long load that presents nothing) leaves **every later
command buffer under its last frame number**. A frame number counts as stalled when both hold: it has at least
`max(32, 8 × the median number of command buffers per frame)` command buffers (`UNPRESENTED_MIN_BUFFERS = 32`,
`UNPRESENTED_FACTOR = 8`, `:201-202`, `:220-221`) and its work spans at least one second (`UNPRESENTED_MIN_S`, `:203`, `:222`).

Those frames are then **left out of everything per frame**: not in `frames`, not in `frame_gpu_ms`, not in the gaps, not in
`frames.csv` (`:696-701`, `:233-245`), and reported once in `gpu.unpresented` with when it began, how long it lasted, how
many command buffers and how much GPU time it held (`:227-230`). The GPU time is not lost: `gpu_idle` still counts it
(`idle_gaps(spans, left_out)`, `:245`).

The second run of the [example](#one-example-first) is this case, and E5 shows the block: frame 160 holds 1776 command
buffers over 17.236 s and 92 % of the run's GPU time (`share_of_gpu_time` 0.92), starting at 3.637 s. The other 153 frames
are the first 3.6 s. The downstream tools see it: `perf_compare` and `perf_check` add an `unpresented` entry with a note
(`analysis.py:13-16`, `:30-34`, `:189-191`, `:374-376`), `perf_gate` **fails** the run (`:493`), and `suggested_actions` says to record
again with the window visible (`:660-662`). Tests: `test_unpresented_tail`, `test_unpresented_spares_heavy_frames`,
`test_summary_leaves_out_unpresented`, `test_unpresented_mid_run` (`tests/test_report.py:690`, `:701`, `:715`, `:765`; not run).

### Steps 4 and 5: the frame numbers, then the other tables

After the filter `summarize` builds the `gpu` block (`:703-721`), the encoder block (`:723-729`) and then each optional table
in turn (`:731-817`), skipping with `if "<schema>" in tables` the ones the trace lacks. The pacing block and the hitches come
last (`:818-822`) because they need the compiler, thermal and memory lists read before them. Finally `frames.csv.gz` is written
(`:831-834`), the `common` block is added (`:835`) and the summary is written (`:836`). `recording.finish` adds `layer`,
`context`, `tier` and `retention` afterwards (`recording.py:337-351`; [recording guide](./recording.md#step-5-when-the-script-returns)).

## How each number is computed

Everything here is **confirmed** by the line given. "The gaps" means the intervals between the first start of consecutive
**presented** frames, in ms; "the totals" means the GPU ms of each frame, summed over its channels.

| Key | Formula | Line |
|---|---|---|
| the gaps | for each pair of consecutive frame numbers `a < b` in order: `first_start[b] - first_start[a]`, kept only if positive and if no unpresented frame lies between them | `perf_report.py:233-245` |
| the totals | for each frame: the sum of `duration / 1e6` of its intervals | `:685`, `:705` |
| `gpu.frames` | the number of frames kept | `:711` |
| `gpu.frame_gpu_ms`, `frame_interval_ms` | `stats(totals)`, `stats(gaps)` | `:712`, `:714` |
| `stats` | `count`, `mean` (3 decimals), `p50 = ordered[n // 2]`, `p95 = ordered[min(n-1, int(n × 0.95))]`, `max` | `metrics.py:75-86` |
| `gpu.fps_estimate` | `round(1000 / median(gaps), 1)`, `None` without gaps | `perf_report.py:718` |
| `gpu.fps_1pct_low` | `1000 / ordered_gaps[min(n-1, int(n × 0.99))]`, only with at least 100 gaps | `:262-266` |
| `gpu.fps_01pct_low` | the same with `0.999` and at least 1000 gaps | `:266` |
| `gpu.stutter_rate_pct` | `100 × (number of gaps > max(1.5 × median, 8.0 ms)) / n`, two decimals; needs at least 2 gaps | `:250`, `:267-268` |
| `gpu.frame_jitter_ms` | `pstdev(gaps)`, three decimals (population standard deviation) | `:269` |
| `gpu.throttling_analysis` | with at least 5 gaps: `k = max(1, int(n × 0.2))`; `fps_initial` and `fps_final` are `1000 / median` of the first and last `k` gaps; `drift = (initial - final) / initial × 100`; detected when the drop is over 10 % **and** the mean GPU ms of the last `k` frames is above the first `k` | `:270-279` |
| `hitches` | the same limit as stutter; each gap above it is one hitch, with a cause | `:283-320` |
| `gpu.start_latency_ms` | `stats` of the start latency of every row of the program that has one, without the unpresented frames | `:716-717` |
| `gpu_idle` | the GPU's idle time between the program's own intervals: per frame, gaps over 1 ms, and `idle_share = sum(gaps) / whole span` | `metrics.py:122-138` |
| `encoders` | encoders and command buffers per frame, each encoder's GPU time, the share shorter than 10, 25, 50, 100, 250, 500 and 1000 µs, the 20 labels with the most GPU time | `metrics.py:94-119` |
| `metal_memory_mib` | `peak`, `final`, `mean` of the program's samples; `trend_mib_per_min` is the least-squares slope over the second half of the time, with at least 5 samples and 5 s | `perf_report.py:731-746`, `:438-450` |
| `gpu_performance_state_share`, `thermal_state_share` | time in each state over the total, 3 decimals | `:765-771`, `:782-790` |
| `noisy_environment` | `external = device_pct_mean - 100 × (1 - idle_share)`; flagged when `external >= 20` points | `:560-581` |

The sections below explain the ones that need a reason.

### fps_estimate

The **median** gap, not the mean: one long gap (a load, a hidden window) moves the mean and not the median. `1000 / median`
turns ms per frame into frames per second. Note two medians in the same summary: `fps_estimate` uses
`statistics.median` (the mean of the two middle values when the count is even), and `frame_interval_ms.p50` uses
`ordered[n // 2]` (the upper one). They differ in the third decimal at most: in the first run 9.4845 against 9.485 (E2, E3).
It is cosmetic.

### The 1 % and 0.1 % lows

`low(share, frames)` (`:262-264`) sorts the gaps, takes the one at position `int(n × share)` (capped at the last) and
converts it to FPS. So the 1 % low is **the interval that 99 % of the frames beat**, turned into FPS (a percentile), and it
is `None` until the run has 100 gaps behind it (1000 for the 0.1 % low): with fewer, one frame *is* the 1 %. The README's
words, "the FPS of the slowest 1 % of frames", describe the idea. Whether other tools define the 1 % low as this percentile
or as the average of the slowest 1 % was **not verified**; compare numbers across tools only after checking.

At 100 FPS 100 gaps are a second of recording, so the rule is not what makes a recording long: the 30 s under Wine are about
the start-up, as the [recording guide](./recording.md#why-30-seconds-or-more-under-wine) says.

### Stutter, jitter and hitches

A gap is a stutter **and** a hitch when it is longer than `max(1.5 × median gap, 8 ms)` (`STUTTER_FLOOR_MS`, `:250`). The
8 ms floor exists "because at 500 FPS a 3 ms frame is scheduler noise, not a stutter" (`:248-249`; test
`test_pacing_and_hitches`, `tests/test_report.py:154`, not run). Both keys use that limit; the stutter rate counts the gaps over
`n` and the hitch list names a cause. In the two real runs the numbers agree: 6 gaps over the limit 14.227 ms are 0.29 % of
2044 and `hitches.count` is 6; 4 gaps over 14.690 ms are 2.63 % of 152 and `hitches.count` is 4 (E3, E4).

`frame_jitter_ms` is the standard deviation of the gaps, so a single 799 ms gap (the second run) gives 63.799 ms
(E3): jitter is read together with `stutter_rate_pct`, not alone.

Each hitch is named by the **first** of these that fits what the trace shows in the interval before the slow frame
(`attribute_hitches`, `:294-310`):

| Order | Cause | Rule |
|---|---|---|
| 1 | `shader_compile` | the graphics compiler ran for the program during the interval |
| 2 | `thermal` | the device's thermal state was anything but `Nominal` during it |
| 3 | `memory_growth` | the program's Metal memory grew by 8 MiB or more between the interval's two ends |
| 4 | `gpu_heavy` | the frame that opens the interval used the GPU for at least 80 % of the gap |
| 5 | `cpu_or_wait` | none of the above: the program was busy on the CPU or waiting |

The list keeps the 20 longest, each with its `frame` (the frame that ended the gap), `interval_ms`, `window_ms` and, when the
CPU table is there, `cpu_pct` (`:312-320`). `per_minute` is `count / ((last start - first start) / 60 000 ms)`, so it counts
over the presented span and not over `duration_s`: the second run says 103.3 hitches a minute because its presented span is
2.3 s long (E4). That makes `per_minute` a number to read with `frames`, not alone. Causes are labels, not proofs: five of the
first run's six hitches are `cpu_or_wait`, which means "no table explains it".

### GPU time per frame is a sum over channels

`frame_gpu_ms` adds the vertex, fragment and compute intervals of a frame (`:685`, `:705`). The channels run in parallel, so a
frame's total can be larger than the time between frames; that is why `gpu_idle` and `gpu_heavy` are defined on the
program's own intervals and not on the sum. `other_processes` says it too (`:587-588`). On Windows this number is not
the same thing (it comes from PresentMon), and the comparison refuses to subtract the two (`NOT_COMPARABLE`,
`analysis.py:132`).

### The noisy-environment flag

Two things load the GPU: the program and everything else. `device_pct` (from the driver's counters, the whole GPU) minus the
program's own busy share (`100 × (1 - idle_share)`) is what "everything else" used; 20 points or more is `noisy_environment:
true` and adds `noisy_basis` with the other processes' count and share (`:565-581`, `:757-762`). The 20 is "provisional, not a
measurement: re-fit it on at least 3 quiet runs of the same Mac" (`:560-561`) and there is a test that the limit is inclusive
(`test_noisy_boundary_is_inclusive`, `tests/test_report.py:905`, not run). Evaluated by hand on the two real runs (E7),
the difference is -6.4 and 0.6 points: neither would be flagged. The two real summaries do not have the key at all: they were
written by a version before it existed (generation 1: no `schema_version`, `tier` or `common`), so the page cannot say
what that version wrote for it.

### Windows

`perf_record_windows.py` calls the same `frame_pacing` (`:489`) and `common_block` (`:917`), so a Windows summary's FPS, lows,
stutter and jitter follow the formulas above, over PresentMon's frame intervals or the drawstress log's means. What it
cannot measure is `null`, not zero, and which source it used is `gpu.source` (see the [recording
guide](./recording.md#the-three-sources-of-frames-and-which-one-wins)).

## Reading summaries back: `analysis.py`

### Finding and reading a run

- `perf_runs` lists `*.json` in the runs folder, newest first, skipping `baselines.json` and the old `panel.json`
  (`analysis.py:51-62`), and a file still being written or not a summary (`:80-81`). A name must be letters, digits, `.`, `_`, `-`;
  a link is never followed (`paths.run_path` `paths.py:33-41`, `paths.read_object` `:54-66`).
- Every tool that reads a summary is wrapped by `reads_recordings` (`:37-48`): a summary whose sections have the wrong
  type (a hand edit, another version) becomes a `ToolError` that names the kind of error and never a path, not an internal error.
- Older summaries have fewer keys. `metrics.schema_of` says which generation a summary is (`metrics.py:13-16`); the
  comparison says "summaries written before version 0.4.0 have no encoder numbers" instead of failing (`:223-227`).

### `skip_s`: the steady state

The first seconds of a run are not the program at rest: shaders compile, resources load. `steady_summary(run, skip_s)`
(`:552-599`) with `skip_s > 0` reads `frames.csv` and keeps the frames that start at least `skip_s` seconds after the first,
then recomputes **from those frames**: `frames`, `frame_gpu_ms`, `frame_interval_ms`, `fps_estimate`, the lows, stutter and
jitter (through the same `perf_report.frame_pacing`, `:573`), the hitch count (gaps over the stored `threshold_ms`, with a
tolerance of 0.002 ms because `frames.csv` rounds start times to 0.001 ms, `:503`, `:577`), and the Metal memory's `peak`.
What it cannot recompute stays whole-run, and the summary says which: `steady.whole_run` lists
`gpu.start_latency_ms`, `thermal_state_share`, `process_rss_mib`, `encoders`, `gpu_idle` and `gpu_counters` (`:598`). The `cpu`
block and `throttling_analysis` are dropped (`:569`, `:592`). Hitch **causes** are kept only for the 20 the summary lists, and
`causes_partial` says when there were more hitches than that (`:579-586`). With fewer than 2 frames left it refuses:
`<run> has under 2 frames after the first N s; use a smaller skip_s` (`:565-566`). `skip_s` is 0 to 600 (`paths.py:118-126`).

`suggested_actions` proposes a `skip_s` itself: when every `shader_compile` hitch among the 20 longest ends within the first
quarter of the run, it suggests the whole seconds that cover them (`_startup_skip_s`, `:670-690`; tests at
`tests/test_analysis.py:1162-1180`, not run).

### `perf_compare`

`compare_summaries` (`:166-242`) is the heart. It computes, for 11 numbers, `change(a, b)`: `b - a` rounded to 3 decimals and
`100 × change / a` rounded to 1 (`:392-396`); either is `None` when a value is missing. The numbers are FPS, the two lows,
stutter, jitter, mean and p95 GPU ms, p95 frame interval, p50 start latency, peak Metal MiB and peak RSS (`:168-180`).
**It decides nothing.** It does not say "faster" or "slower"; it says what moved and adds everything that could make the
move meaningless:

| Key | Appears when | Line |
|---|---|---|
| `too_short` | a run has under 100 frames | `:187` |
| `layer`, `context` | the two runs differ in translation layer, commit or Instruments version (the [recording guide](./recording.md#what-identifies-a-run)) | `:188` |
| `unpresented` | one run stopped presenting | `:189-191` |
| `noisy_environment` | one run was flagged noisy | `:192-194` |
| `screen` | one run was recorded with the screen locked and the other not | `:195-200` |
| `tier` | the tiers differ (a `light` run has no memory) | `:201-205` |
| `gpu_state` | the time-weighted performance level differs by 0.25 or more (0 all Minimum, 1 all Medium, 2 all Maximum): the same work takes more GPU ms in a lower state | `:206-211`, `:141-146` |
| `memory_pressure` | both measured memory the same way (its change), or a note that they did not | `:212-214`, `:149-163` |
| `measure` | a Windows run against a Metal run: GPU ms and Metal memory are not subtracted, the encoders are "not comparable" and the function returns early | `:215-222` |
| `encoders` and `labels` | both are Metal summaries with encoders: encoders and command buffers per frame, short-encoder share, idle share (shares change in points, never in %, because 1.9 % to 49.7 % would read +2516 %, `:239-240`), and each label's count and GPU ms per frame, largest change first, at most 20 | `:223-242`, `:399-421` |

`short_us` must be one of 10, 25, 50, 100, 250, 500, 1000 (`:228-230`). With `markdown` true the result also has a table
for a pull request (`:85-102`), and `suggested_actions` lists what to call next for each run (`:125-126`).

A label missing from one summary may only have fallen out of that summary's top 20, so it is `outside_top_20` and has no
change, not `new` or `gone` (`:399-421`).

### Baselines: a range, not a run

`perf_baseline name runs` (`:259-293`) stores **copies of the summaries** of the runs (so the reference outlives `KEEP_RUNS`)
in `baselines.json` with the date, replacing a reference of the same name, and returns two things per checked metric:

- the `range`: the lowest and highest value across the runs (`ranges`, `:296-307`), `None` for a metric a run lacks;
- the `spread_pct`: `200 × (max - min) / (max + min)`, the width as a percentage of the midpoint (`spreads`, `:310-314`),
  "the noise of this program on this machine, which a change must exceed" (`:264-265`).

The checked metrics are four: `fps`, `gpu_ms_mean` and the p50 of encoders and of command buffers per frame (`CHECKED`, `:246-251`).
The code accepts a single run (the range is then one point and the spread 0); `CHANGELOG.md` says "ideally 3 or more". The file
itself is described in the [data guide](./data-and-lifecycle.md#the-project-file-the-mark-and-the-baselines). The baseline reports
`unpresented` and `noisy_environment` for the runs it was built from (`:288-292`), so a bad reference is visible.

### `perf_check`: the verdict

`judge(metric, value, span, margin_pct)` (`:317-330`) is the rule. For a metric where higher is worse (GPU ms, the counts):
`worse` if `value > span.max × (1 + margin)`, `better` if `value < span.min × (1 - margin)`, else `same`; for FPS the sides swap.
The margin is `margin_pct / 100` (default **3**, `:334`) for FPS and GPU ms, and **0** for the two `_p50` counts (`:325`): an
encoder count is exact, and one more encoder per frame is a change. Then (`:351-368`):

1. A metric the run or the reference lacks is `unchecked`, not judged.
2. If one side is Windows and the other Metal, only FPS is judged (`cross`, `:350-354`).
3. Verdict: **`regressed` if any metric is worse; `improved` if any is better and none worse; `same` otherwise** (`:368`).

The answer carries `regressed` and `improved` with the metric, value and range of each, `unchecked`, the `range` and the full
`perf_compare` of the reference's *first* run against this run (`:369-371`). Frame pacing, short encoders and idle time are in
the comparison but **never decide** (`:338-340`). The 3 % is a default the project chose (**not verified** as measured: the
changelog's 4.4 % and 6.1 % spreads are why the reference is a range); `perf_baseline`'s `spread_pct` is reported but `perf_check`
**does not read it** ([limit 8](#known-limits)).

Test: `test_judge_matches_perf_check` (`tests/test_analysis.py:342`, not run) pins that `judge` says `worse` for exactly the metrics
`perf_check` lists as regressed and `better` for those it lists as improved.

### `perf_gate`: a bar, not a reference

`perf_gate` (`:471-500`) checks fixed budgets: `fps_min`, `fps_1pct_low_min`, `stutter_rate_pct_max`, `gpu_ms_p95_max`,
`hitches_max`, `metal_mib_max` (`GATES`, `:466-468`); at least one is required. Each budget is `ok` only if the value exists
and is on the right side: `ok = value is not None and (value >= limit if min else value <= limit)` (`:490`). The answer is
`pass` only if all hold **and** the run has no `unpresented` (`:493`). A gate is the right tool for a bar a change must clear;
`perf_check` is for "did this change move it beyond what equal runs do".

### `perf_history` and `perf_diagnose`

- `perf_history prefix` lists the runs whose name starts with the prefix, oldest first, with six numbers and the change from
  the first to the last (`:437-462`). It flags a series that mixes Windows and Metal, and says "under 3 runs: not a trend yet"
  (`:458-461`). Its own advice: read a trend as real only when it exceeds the `spread_pct` of equal runs (`:440-441`).
- `perf_diagnose` (`:693-820`) is a rule-based reading of one summary. It is **a heuristic, and its text is not English**: the
  recommendations are Spanish sentences (`:756-807`), the only Spanish in the tool output. Its rules:

  | Output | Rule (thresholds are in the code) | Line |
  |---|---|---|
  | `stutter_analysis.verdict` | `UNKNOWN` without the stutter number; `SEVERE_STUTTER` above 7 %; `MICRO_STUTTER` from 2 %; else `SMOOTH` | `:720-727` |
  | `bottleneck` | `MEMORY_PRESSURE_SUSPECTED` when variance is high (jitter at least 3 ms, or p95 minus p50 of the interval at least 5 ms) and the working set is at least 1500 MiB; `UNKNOWN` without `idle_share`; `CPU_SUBMISSION_BOUND` when `idle_share >= 0.25` (or `>= 0.20` with too many short encoders); `GPU_BOUND` when `idle_share <= 0.15` and the GPU ms is at least 80 % of the interval; else `BALANCED` | `:737-752` |
  | `too_many_short_encoders` | encoders per frame p50 at least `min_encoders` (4) **and** the share under `short_us` at least `short_share` (0.25) | `:711` |

  The defaults "come from bgfx 17-drawstress on an M1 Pro: 7 encoders per frame and 50 % under 25 µs under Mullion, 2 and 2 % in
  native Metal" (`:698-699`). The memory verdict is an inference ("memory bandwidth itself is not measured", `:742`). Evaluated
  by hand on the two real runs (E7): the first is `SMOOTH` (stutter 0.29 %) and the second `MICRO_STUTTER` (2.63 %), both with
  `idle_share` above 0.25, which by the rule is `CPU_SUBMISSION_BOUND`; the page did not run the tool, so that line is **probable**.

`perf_memory_breakdown` (`:823-870`) only rearranges the `resource_allocations` block; it computes no new quantity beyond ratios
(`live_share_pct`, `allocated_mib_per_live_mib`) and is not detailed here.

### When a number is missing

Everything above is built to carry `None` and not zero:

| Reader | A missing number becomes |
|---|---|
| `compare_summaries` | `change(None, None)`: both `a` and `b` `None` when the key is absent (`:182-186`) |
| `perf_check` | the metric is `unchecked`; `hint_unchecked` says a pre-0.4.0 summary has no encoder numbers (`:359-361`, `:382-383`) |
| `perf_gate` | the budget **fails** (`value` null, `ok` false): "a gate must not pass on missing data" (`:476-477`, `:490`) |
| `perf_history` | `null` in the row (`dig`, `:424-428`) |
| `perf_diagnose` | `UNKNOWN` bottleneck without `idle_share` or `UNKNOWN` stutter verdict without the stutter number (`:720-721`, `:744-745`) |
| a short run | `fps_1pct_low` and `fps_01pct_low` are `None` (a number needs its frames, `perf_report.py:264`) |

## The experiments

`experiments.py` records several runs and calls the readers above. Each recording goes through `record_new_summary`
(`recording.py:440-449`), which calls `perf_record` and reads back the one summary it wrote, so each run is a normal run with a
normal label. All four share `cooldown_s` (0 to 600 s, rests between two recordings and never before the first or after the
last; a cancelled call ends the rest, `recording.py:240-249`, `paths.py:102-115`) and take `perf_record`'s arguments. Each
recording takes its seconds plus about a minute to read back (docstrings), and the recording lock lets only one run at a time
(see the [recording guide](./recording.md#one-recording-at-a-time)).

| Tool | What it records | What it returns | Limits | Line |
|---|---|---|---|---|
| `perf_baseline_record` | the same program `count` times in a row, runs named `<name>-1`, `-2`, ... | the baseline: the range and `spread_pct` (it ends in `perf_baseline`) | `count` 1 to 10 | `experiments.py:9-27`, `:20` |
| `perf_ab` | two environments in the order **A B B A**, repeated `rounds` times; runs `<name>-a1`, `-b1`, `-b2`, `-a2`, ... | per metric (FPS, 1 % low, GPU ms, stutter) the values of each side and a verdict | `rounds` 1 to 5 (4 to 20 recordings) | `:48-69`, `:202-222` |
| `perf_cold_warm` | the same program twice: `<name>-first` and `<name>-second` (macOS only) | hitches and causes of each run and `first_seen_hitches` | none | `:72-102` |
| `perf_sweep` | once per value of one variable (`dim`, `example`, `api`, `size` or `env:NAME`), values forward in one round and backward in the next | per value the median of the four metrics, and a straight-line fit | 2 to 8 values, `rounds` 1 to 5, at most 24 recordings | `:141-199`, `:117-138` |

### Why A B B A

A laptop warms up as it records. Running A, B, A, B would put every B on a warmer machine than the A before it; A B B A puts one
of each at the start and one at the end, so slow drift hits both sides alike, and `rounds` repeats the pattern (`:49-51`).
The sweep does the same by reversing the order of the values every other round (`:161`). That the drift matters is the
project's own claim (the cooldown exists for it: "so a laptop does not throttle", `:13-14`); the size of the drift was
**not measured** for this page.

### How `perf_ab` decides

`ab_verdict(a, b, higher_better)` (`:36-45`):

- `unknown` if either side has no values;
- **better** if every `b` value is above every `a` value (`min(b) > max(a)`) for a metric where higher is better (FPS, 1 % low),
  and below for one where lower is better (GPU ms, stutter);
- **worse** in the mirrored case;
- `same` otherwise, including every overlap.

There is no margin and no percentage: the **spread of the A runs is the ruler**, "so a run's own spread never passes for an
effect" (`:37-38`). With `rounds=1` each side has two values (A B B A), so the ruler is two runs wide. A value a run does not have
(a 1 % low of a short run, `None`) is left out of the list, so a side can have fewer values than runs (`:213-215`). `too_short` is
true if any run has under 100 frames (`:217-219`). By hand on the two real runs, taking the first as side A and the second as side B:
FPS `a = [105.4]` and `b = [102.1]`, so `max(b) < min(a)` and a higher-is-better metric gives `worse` for a 3 % drop, because a
single value has no spread. That is the arithmetic of the rule, not a run of the tool; it is why `perf_ab` records four runs and
why one run per side is not an experiment (E6).

### How `perf_cold_warm` decides

`cold_warm_report` (`:72-87`): `first_seen_hitches = max(0, shader_compile hitches of the first - those of the second)` and
`extra_hitches_in_first = max(0, hitches of the first - hitches of the second)`. The hint says the Metal shader cache is **not
cleared** between the runs, so the first run is "cold" only if the program's pipelines were not built before. By hand on the two
real runs, which are named like a `perf_cold_warm` pair (the labels end in `-first` and `-second`; that they came from the tool is
**probable**): both have 0 `shader_compile` hitches, so `first_seen_hitches` is 0; the hitch counts are 6 and 4, so
`extra_hitches_in_first` is 2 (E7). The second run's 4 are not comparable with the first's 6: its presented span is 2.3 s.

### How `perf_sweep` fits a line

With at least 3 values that are numbers (`dim` is; `size` is not, and `example` and `api` are names), it fits `GPU ms per frame`
against the value by least squares (`line_fit`, `:105-114`): `slope = Σ(x - mx)(y - my) / Σ(x - mx)²`, `intercept = my - slope × mx`,
`r² = 1 - residual / total`. For `dim` the x is `dim³`, because drawstress draws `dim³` cubes per frame (64 000 at `dim` 40,
[recording guide](./recording.md#what-is-in-the-list-e4)), so the slope is **ms per draw** and the intercept the fixed cost
(`:189-196`). A variable whose values are not numbers gives no fit (`ValueError` is caught, `:188-191`), and `line_fit` returns
`None` when x never changes (`:109-110`). The tests that pin the experiments are `test_baseline_record`, `test_perf_sweep`,
`test_cold_warm` (`tests/test_analysis.py:170`, `:198`, `:269`) and the cooldown ones in `tests/test_recording.py:1398-1443` (not
run). A real sweep was **not reproduced**: it needs 4 to 24 recordings.

## Better, worse, same, and noise

One table, because the four deciders look alike and are not:

| Tool | Reference | Margin | A single run? | Says |
|---|---|---|---|---|
| `perf_compare` | one run | none | yes | the change, and what could make it meaningless; **no verdict** |
| `perf_check` | the range of N runs | 3 % for FPS and GPU ms (`margin_pct`), 0 for the counts | yes, against N | `regressed`, `improved` or `same` |
| `perf_ab` | the range of the A runs of this experiment | none | needs 2 per side at least to mean something | `better`, `worse`, `same` or `unknown` per metric |
| `perf_gate` | a number you set | none | yes | `pass` or fail per budget |

![Eight boxes in two rows joined by arrows. Top row: read the summaries, perf_compare (changes, no verdict), perf_baseline (the range and spread of equal runs) and perf_check's decision of each metric against that range with a margin. Bottom row: the verdict regressed, improved or same; perf_ab; perf_gate; and the warnings that never change a verdict.](/diagrams/analysis-compare-flow.png)
*Figure 2. How a run is compared and judged. HTML source: `docs/diagrams/analysis-compare-flow.html`.*

What the project does about noise, in the order you meet it:

1. **Repeat.** "Repeat a run before calling a change real" (the project's `CLAUDE.md`; the [guide index](./index.md) says the
   same). `perf_baseline_record` and A B B A are the tools that repeat for you.
2. **Measure the noise.** `spread_pct` of a baseline is how far equal runs differ.
3. **Judge outside the noise.** The range replaces the single run, and the margin adds a small buffer past it.
4. **Say when the run is suspect.** The flags of `perf_compare`: `unpresented`, `noisy_environment`, `screen`, `gpu_state`, `tier`,
   `too_short`. They are visible and they **do not change the verdict** of `perf_check`; only `perf_gate` fails on `unpresented`.
5. **Rest.** `cooldown_s`, and a `suggested_actions` entry proposing a 60 s rest when the Mac throttled ("60 s is a starting
   value, not a measurement", `analysis.py:665-666`).

The [example](#one-example-first) is why step 1 matters: a single reference run gives a range one point wide, and 3 % is small
against the 4.4 % that five equal runs once differed by (`CHANGELOG.md`, not re-measured). Against `a2-proof-first` alone the
second run is `regressed`; against three equal runs of the first kind it would very probably be `same`. The first claim is
by-hand arithmetic (E6); the second is **speculation**.

## When it fails

| What goes wrong | What the reader gets | What is left | Line |
|---|---|---|---|
| The `.trace` is already deleted | `no recording at <name>: perf_record.sh deletes the .trace once its summary is written, unless KEEP_TRACE=1` | nothing new | `perf_report.py:52-54` |
| `xctrace export` fails | `xctrace export of <name> failed (exit N): <last stderr line>` | temporary files of the other exports are deleted | `:62-65`, `:106-110`, `:121-123` |
| The trace has no `metal-gpu-intervals` | the message in [Step 2](#step-2-the-table-of-contents-and-missing-tables) | nothing | `:194-196` |
| The trace has no launched or attached process | `the trace has no launched or attached process; record it with xctrace --launch or --attach` | nothing | `:644-645` |
| The program did no GPU work | a summary with `frames` 0 and no FPS is built; when it comes from a recording, `recording.py` turns it into `the program did no GPU work ...` and deletes the run | the `.trace` only if asked | `recording.py:427-436` |
| `perf_report` exits non-zero in a recording | `recording failed (exit N): <last line>` | the script's trap deletes the run's files | `perf_record.sh:5`, `:71`, [recording guide](./recording.md#what-happens-if-instruments-dies-part-way) |
| An export times out, or a table is cut mid-row | a Python traceback, not a sentence ([limit 4](#known-limits)) | a temporary XML file may stay ([limit 4](#known-limits)) | `:59`, `:166-168`, `:850` |
| A summary is not valid JSON, is a link or has a wrong-typed section | `<run> is not valid JSON; record it again` / `<run> cannot be read` / `... not in the form the recorder writes (<ErrorType>)` | nothing | `paths.py:54-66`, `analysis.py:37-48` |
| `perf_compare` names a run that does not exist | `no run <name>; perf_runs lists them` | | `paths.py:33-41` |
| `skip_s` leaves under 2 frames, or no `frames.csv` | `<run> has under 2 frames after the first N s; use a smaller skip_s`, `<run> has no per-frame file; record it again` | | `analysis.py:510`, `:565-566` |
| `perf_check` or `perf_baseline` names a missing reference | `no reference <name>; perf_baseline with no arguments lists them` | | `:285`, `:345` |
| An experiment fails mid-way | the `ToolError` of the failing recording; **runs already recorded stay**, and no baseline, verdict or fit is written | the earlier runs, as normal runs | `experiments.py:23-27`, `:64-69`, `:160-172` (no `try`) |
| An experiment is cancelled while resting | `cancelled while cooling down` and no further recording starts | the runs already made | `recording.py:240-249` |

The last two rows are confirmed by the code (there is no `try` around the loops); a failing experiment was **not reproduced**.

## Known limits

Each item is a limit of today's behaviour, written down, not fixed here.

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | The two real summaries of this repository are generation 1: they have no `schema_version`, `tier`, `common` or `noisy_environment`, so the page recomputed with today's formulas and the match (E3) is a check of those formulas on old data, not of what the version that wrote them did | `perf-runs/` (a local folder, not published) | Confirmed |
| 2 | The friendly message for a trace without `metal-gpu-intervals` may be unreachable: `toc_and_tables` takes the export of a required table with `future.result()`, and the code's own comment says "xctrace fails on a table that is not there", so the failure would be the generic `xctrace export ... failed` first; the `ValueError` is only reached if the export succeeds on an absent table. `tests/test_report.py:128-135` tests `missing_tables` directly | `perf_report.py:98-99`, `:116-117`, `:194-196` | Probable: not reproduced (no trace) |
| 3 | `missing_tables` lists `metal-current-allocated-size` and `gpu-performance-state-intervals` as if they were optional, but only the first can be absent without failing (when memory is skipped with `--no-memory`); a trace without the second most likely fails the export, so the name would never reach the summary | `perf_report.py:190-197` against `:95-123` | Probable |
| 4 | `export` does not catch a `subprocess.TimeoutExpired` (600 s per table, 3600 for the counter values), and `main` catches only `ValueError`, `FileNotFoundError` and `RuntimeError`: a slow export ends in a traceback, which carries the command line, and the temporary XML file that `export` created is not deleted on that path (the `finally` of `summarize` removes only files already returned). A table cut mid-row (an `ET.ParseError` that `complete_xml` does not forgive) ends the same way | `perf_report.py:55-59`, `:166-168`, `:850` | Confirmed by the code; not reproduced |
| 5 | `command_buffer_errors` counts every row of its table, not only the program's; the allocations and spills tables are filtered by the program's pid | `perf_report.py:805-806` against `:457-522` | Confirmed by the code |
| 6 | `stutter_rate_pct` skips gaps that span an unpresented frame; `hitches` and `steady_summary` build their gaps from the frame starts that are left, so a gap that spans an unpresented frame is counted by them and not by the stutter rate, and `hitches.count` can then exceed the stutter count | `perf_report.py:243-244`, `:706`, `:822` against `analysis.py:568` | Probable: the real second run's stall is at its end, so it does not show this |
| 7 | `perf_ab`, `perf_sweep` and `perf_cold_warm` do not report `unpresented` or `noisy_environment` of the runs they record (only `too_short`); `perf_baseline` does | `experiments.py:202-222`, `:187`, `:72-87` against `analysis.py:288-292` | Confirmed |
| 8 | `perf_check` uses a fixed `margin_pct` (3) and does not read the baseline's `spread_pct`; a one-run reference has spread 0, and a 3.1 % FPS dip reads `regressed` | `analysis.py:317-330`, `:310-314` | Confirmed (E6) |
| 9 | The 1 % low is the percentile of the interval, not the average of the slowest 1 %; whether that matches other tools is not verified | `perf_report.py:262-266` | Not verified |
| 10 | A throttling flag is overwritten by "any non-Nominal thermal interval" whenever the thermal table exists, whether or not FPS fell | `perf_report.py:819-820` | Confirmed |
| 11 | `perf_diagnose` writes its recommendations in Spanish while everything else is English | `analysis.py:756-807` | Confirmed (cosmetic) |
| 12 | The 3 % margin, the 20-point noise threshold, the 8 ms floor and the 25 %, 20 %, 15 % idle thresholds are the project's choices, some marked "provisional" in the code; none is re-measured here | `analysis.py:325`, `:746-748`; `perf_report.py:250`, `:562` | Not verified |
| 13 | Two real runs prove the formulas on summaries of one program on one Mac; a Windows summary's numbers (PresentMon, the log) were not recomputed | | Not reproduced |

## Touching it without breaking it

- A new number: compute it in `metrics.py` if Windows can also produce it, in `perf_report.py` otherwise; add the key to the
  summary and to the [data guide](./data-and-lifecycle.md#the-summary-key-by-key). Make a missing input give `None` or no key,
  never `0`: every reader above treats `None` as "unknown".
- A new table in `perf_report.py`: add its schema to `OPTIONAL`, read it only `if "<schema>" in tables`, and add a test beside
  `test_toc_and_tables`. Do not put a table in `TABLES` (required) unless every summary needs it: an absent required table
  fails the whole report ([limit 3](#known-limits)).
- A new thing to compare: add it to `numbers` in `compare_summaries` (`:168`); to decide on it, add it to `CHECKED` (`:246`) and
  decide its margin in `judge` (`:325`); to require it, add it to `GATES` (`:466`).
- A change to a threshold (`STUTTER_FLOOR_MS`, `NOISY_EXTERNAL_PCT`, the 1.5, the 3 %): the numbers of every older summary stay
  as written, and `skip_s` recomputes with the **current** `frame_pacing` but the **stored** `threshold_ms`
  (`analysis.py:573-577`); change them knowing the two will disagree on old runs, and update
  `tests/golden/metrics.json`.
- `analysis.py` must not call `xctrace`: it reads summaries and `frames.csv` only, which is why it works after the trace is
  gone. Reading the trace is `perf_report.py`'s and the `traces.py` tools' job.
- Keep `reads_recordings` on any new tool that reads a summary (`:37-48`), and keep paths out of its messages.

## Evidence: the commands and their real output

Collected on 2026-11-16 on an Apple silicon Mac. All commands only read. The runs folder is `perf-runs/` of the clone (a local,
ignored folder that is not published; it holds the two runs below). The session that collected them could run `rg`, `sed`,
`jq` and `awk` and could not run Python or `xctrace`: no tool of this page was run, and E3, E6 and E7 are the formulas of the
code evaluated by hand.

### E1 The tables, workers, thresholds and error messages

```text
$ rg -n '^MEMORY =|^TABLES =|^OPTIONAL =|^COUNTER_TABLES =|^EXPORT_WORKERS =|^STUTTER_FLOOR_MS =|^UNPRESENTED_' src/metal_gpu_trace/perf_report.py | cut -c1-120
33:MEMORY = "metal-current-allocated-size"
34:TABLES = ("metal-gpu-intervals", MEMORY, "gpu-performance-state-intervals")
36:OPTIONAL = ("metal-application-encoders-list", "graphics-compiler-activity-intervals", "device-thermal-state-interval
40:EXPORT_WORKERS = 2
42:COUNTER_TABLES = ("gpu-counter-info", "gpu-counter-value")
201:UNPRESENTED_MIN_BUFFERS = 32
202:UNPRESENTED_FACTOR = 8
203:UNPRESENTED_MIN_S = 1.0
250:STUTTER_FLOOR_MS = 8.0

$ rg -n 'raise ValueError|sys.exit|raise RuntimeError|raise FileNotFoundError' src/metal_gpu_trace/perf_report.py | cut -c1-170
53:        raise FileNotFoundError(f"no recording at {pathlib.Path(trace).name}: perf_record.sh deletes the .trace once "
65:        raise RuntimeError(f"xctrace export of {pathlib.Path(trace).name} failed (exit {proc.returncode}): {reason}")
195:        raise ValueError("the trace has no metal-gpu-intervals table; this Xcode may name it differently: "
645:        raise ValueError("the trace has no launched or attached process; record it with xctrace --launch or --attach")
851:        sys.exit(str(error))
```

Only these four conditions have a sentence; the `except` at line 850 catches exactly those three kinds. Anything else
escapes `main` as a traceback ([limit 4](#known-limits)).

### E2 The `gpu` block of the two real summaries

```text
$ jq -c '.gpu | del(.per_channel_ms)' a2-proof-first_20261115-085621.json
{"intervals":6269,"frames":2045,"frame_gpu_ms":{"count":2045,"mean":5.937,"p50":6.008,"p95":6.213,"max":13.561},"frame_interval_ms":{"count":2044,"mean":9.587,"p50":9.485,"p95":10.098,"max":36.335},"fps_estimate":105.4,"fps_1pct_low":96.2,"fps_01pct_low":48.2,"stutter_rate_pct":0.29,"frame_jitter_ms":0.817,"throttling_analysis":{"thermal_throttling_detected":false,"fps_initial":103.0,"fps_final":105.8,"fps_drift_pct":-2.7}}

$ jq -c '.gpu | del(.per_channel_ms)' a2-proof-second_20261115-085735.json
{"intervals":548,"frames":153,"frame_gpu_ms":{"count":153,"mean":5.86,"p50":6.058,"p95":6.798,"max":13.704},"frame_interval_ms":{"count":152,"mean":15.286,"p50":9.795,"p95":11.982,"max":798.956},"fps_estimate":102.1,"unpresented":{"frames":[160],"from_s":3.637,"span_s":17.236,"command_buffers":1776,"gpu_ms":10358.288,"share_of_gpu_time":0.92},"fps_1pct_low":40.8,"fps_01pct_low":null,"stutter_rate_pct":2.63,"frame_jitter_ms":63.799,"throttling_analysis":{"thermal_throttling_detected":false,"fps_initial":100.6,"fps_final":100.8,"fps_drift_pct":-0.2}}
```

### E3 Recomputing the numbers from `frames.csv`

The table has one row per frame: `frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total` (the [data
guide](./data-and-lifecycle.md#the-tables-and-the-samplers)). The gaps are the differences of `start_ms` (positive only), the
formulas are those of the table above.

```text
$ cd perf-runs
$ tail -n +2 a2-proof-first_20261115-085621.frames.csv | awk -F, 'NR>1{g=$2-p; if(g>0) print g} {p=$2}' | sort -n | awk '{a[NR]=$1; s+=$1; q+=$1*$1} END{n=NR; med=(n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2; lim=1.5*med; if(lim<8)lim=8; for(k=1;k<=n;k++) if(a[k]>lim) c++; i=int(n*0.99); if(i>n-1)i=n-1; j=int(n*0.999); if(j>n-1)j=n-1; m=s/n; sd=sqrt(q/n-m*m); printf "n=%d median=%.4f fps=%.1f low1=%.1f low01=%.1f limit=%.3f over=%d stutter=%.2f jitter=%.3f max=%.3f\n", n, med, 1000/med, 1000/a[i+1], 1000/a[j+1], lim, c, c/n*100, sd, a[n]}'
n=2044 median=9.4845 fps=105.4 low1=96.2 low01=48.2 limit=14.227 over=6 stutter=0.29 jitter=0.817 max=36.335
$ tail -n +2 a2-proof-first_20261115-085621.frames.csv | awk -F, '{s+=$6; n++} END{printf "frames=%d gpu_ms_mean=%.3f\n", n, s/n}'
frames=2045 gpu_ms_mean=5.937

$ tail -n +2 a2-proof-second_20261115-085735.frames.csv | awk -F, 'NR>1{g=$2-p; if(g>0) print g} {p=$2}' | sort -n | awk '{a[NR]=$1; s+=$1; q+=$1*$1} END{n=NR; med=(n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2; lim=1.5*med; if(lim<8)lim=8; for(k=1;k<=n;k++) if(a[k]>lim) c++; i=int(n*0.99); if(i>n-1)i=n-1; j=int(n*0.999); if(j>n-1)j=n-1; m=s/n; sd=sqrt(q/n-m*m); printf "n=%d median=%.4f fps=%.1f low1=%.1f low01(n<1000: null)=%.1f limit=%.3f over=%d stutter=%.2f jitter=%.3f max=%.3f\n", n, med, 1000/med, 1000/a[i+1], 1000/a[j+1], lim, c, c/n*100, sd, a[n]}'
n=152 median=9.7935 fps=102.1 low1=40.8 low01(n<1000: null)=1.3 limit=14.690 over=4 stutter=2.63 jitter=63.799 max=798.956
$ tail -n +2 a2-proof-second_20261115-085735.frames.csv | awk -F, '{s+=$6; n++} END{printf "frames=%d gpu_ms_mean=%.3f\n", n, s/n}'
frames=153 gpu_ms_mean=5.860
```

Against E2: `fps_estimate` 105.4 and 102.1, `fps_1pct_low` 96.2 and 40.8, `fps_01pct_low` 48.2 (first) and `null` (second: 152 gaps are under
1000, so the `1.3` the script prints is what the rule throws away, and the summary correctly has `null`), `stutter_rate_pct` 0.29
and 2.63, `frame_jitter_ms` 0.817 and 63.799, frames 2045 and 153, mean GPU ms 5.937 and 5.860 (5.86 in the summary). Every
published number matches. The hitch threshold is 14.227 for the first run and 14.690 here (14.691 in the summary: the summary
computed it from nanosecond starts, the table keeps them to 0.001 ms). One more difference is by design: `frame_interval_ms.p50` is
9.485 and 9.795 against the true medians 9.4845 and 9.7935 (see [fps_estimate](#fps-estimate)). The summaries were written by an
older version of the code than the formulas used here, so this checks the formulas on old data ([limit 1](#known-limits)).

### E4 The hitch blocks

```text
$ jq -c '{missing_tables, hitches: (.hitches | del(.worst))}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"missing_tables":[],"hitches":{"count":6,"per_minute":18.37,"threshold_ms":14.227,"causes":{"cpu_or_wait":5,"memory_growth":1}}}
{"missing_tables":[],"hitches":{"count":4,"per_minute":103.3,"threshold_ms":14.691,"causes":{"cpu_or_wait":3,"memory_growth":1}}}

$ jq -c '.hitches.worst[0:2]' a2-proof-second_20261115-085735.json
[{"frame":159,"interval_ms":798.956,"cause":"cpu_or_wait","window_ms":[2825.46,3624.416],"cpu_pct":4.8},{"frame":23,"interval_ms":24.502,"cause":"cpu_or_wait","window_ms":[1465.036,1489.538],"cpu_pct":95.0}]
```

`count` is 6 and 4, equal to the "over" counts of E3 (so hitches and stutter share their limit). `per_minute` 103.3 for 4
hitches means a 2.32 s span, the presented part of a 20.9 s run (the summary's `duration_s` is 20.87). The worst hitch of the
second run is the 799 ms gap that ends the presented part, with the program at 4.8 % CPU: it was waiting, which fits a hidden
window (**speculation**: why the window was hidden is not in the data).

### E5 The `unpresented` block, from E2

`gpu.unpresented` of the second run: `frames` `[160]`, `from_s` 3.637, `span_s` 17.236, `command_buffers` 1776, `gpu_ms` 10358.288,
`share_of_gpu_time` 0.92. The code's own rule needs at least `max(32, 8 × median)` command buffers and at least 1 s
(`perf_report.py:220-222`); 1776 and 17.236 s satisfy it by a wide margin. The run's `intervals` is 548 and its
`frames` 153: the work left out is not in them. The reading "the window was hidden at 3.6 s" is **speculation**.

### E6 `perf_compare` and `perf_check`, evaluated by hand

The two functions were **not run**. These are their formulas (`change`, `analysis.py:392-396`; `judge`, `:317-330`) applied with
`jq` to the two summaries, `a` the first run and `b` the second:

```text
$ jq -n --slurpfile a a2-proof-first_20261115-085621.json --slurpfile b a2-proof-second_20261115-085735.json 'def ch(x;y): {a:x,b:y,change:((y-x)*1000|round/1000),change_pct:(if x==0 then null else ((100*(y-x)/x)*10|round/10) end)}; ($a[0]) as $A | ($b[0]) as $B | {fps:ch($A.gpu.fps_estimate;$B.gpu.fps_estimate), fps_1pct_low:ch($A.gpu.fps_1pct_low;$B.gpu.fps_1pct_low), stutter_rate_pct:ch($A.gpu.stutter_rate_pct;$B.gpu.stutter_rate_pct), frame_jitter_ms:ch($A.gpu.frame_jitter_ms;$B.gpu.frame_jitter_ms), gpu_ms_mean:ch($A.gpu.frame_gpu_ms.mean;$B.gpu.frame_gpu_ms.mean), metal_mib_peak:ch($A.metal_memory_mib.peak;$B.metal_memory_mib.peak), too_short:[], unpresented_runs:["b"]}' -c
{"fps":{"a":105.4,"b":102.1,"change":-3.3,"change_pct":-3.1},"fps_1pct_low":{"a":96.2,"b":40.8,"change":-55.4,"change_pct":-57.6},"stutter_rate_pct":{"a":0.29,"b":2.63,"change":2.34,"change_pct":806.9},"frame_jitter_ms":{"a":0.817,"b":63.799,"change":62.982,"change_pct":7708.9},"gpu_ms_mean":{"a":5.937,"b":5.86,"change":-0.077,"change_pct":-1.3},"metal_mib_peak":{"a":83.17,"b":94.38,"change":11.21,"change_pct":13.5},"too_short":[],"unpresented_runs":["b"]}

$ jq -n --slurpfile a a2-proof-first_20261115-085621.json --slurpfile b a2-proof-second_20261115-085735.json '($a[0].gpu.fps_estimate) as $lo | ($b[0].gpu.fps_estimate) as $v | {fps_floor_with_3pct_margin:($lo*0.97), run_fps:$v, verdict:(if $v < $lo*0.97 then "worse" else "same" end), gpu_ms_ceiling:($a[0].gpu.frame_gpu_ms.mean*1.03), run_gpu_ms:$b[0].gpu.frame_gpu_ms.mean}' -c
{"fps_floor_with_3pct_margin":102.238,"run_fps":102.1,"verdict":"worse","gpu_ms_ceiling":6.1151100000000005,"run_gpu_ms":5.86}
```

Reading: `perf_compare` would give the first block (plus an `unpresented` entry naming `b`, and no `too_short` because 153 is not under 100).
For `perf_check` against a reference made only of the first run, FPS is under the floor (102.1 < 102.238), so the verdict
would be `regressed`; GPU ms per frame (5.86 under 6.115) and the encoder counts (both runs have p50 2 and 1, from the
summaries' `encoders`) are `same`. The first-run reference has `spread_pct` 0. This is [limit 8](#known-limits) and the reason
`perf_baseline` wants several runs. The results are **probable** (the code was read, not run).

### E7 `missing_tables`, noise and diagnosis by hand

```text
$ sed -n 128,132p tests/test_report.py
    assert perf_report.missing_tables(toc) == ["ProcessCPUUsage", "device-thermal-state-intervals", "gpu-performance-state-intervals",
                                               "graphics-compiler-activity-intervals", "graphics-compiler-spill-events",
                                               "metal-application-encoders-list",
                                               "metal-command-buffer-error", "metal-current-allocated-size",
                                               "metal-resource-allocations"]

$ jq -c '{label, stutter:.gpu.stutter_rate_pct, stutter_verdict:(if .gpu.stutter_rate_pct==null then "UNKNOWN" elif .gpu.stutter_rate_pct>7 then "SEVERE_STUTTER" elif .gpu.stutter_rate_pct>=2 then "MICRO_STUTTER" else "SMOOTH" end), idle_share:.gpu_idle.idle_share, high_variance:((.gpu.frame_jitter_ms>=3) or ((.gpu.frame_interval_ms.p95-.gpu.frame_interval_ms.p50)>=5)), working_set_mib:([.process_rss_mib.max,.metal_memory_mib.peak]|max), noisy_external_pct:((.gpu_activity.device_pct.mean - 100*(1-.gpu_idle.idle_share))*10|round/10)}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"label":"a2-proof-first_20261115-085621","stutter":0.29,"stutter_verdict":"SMOOTH","idle_share":0.381,"high_variance":false,"working_set_mib":237.312,"noisy_external_pct":-6.4}
{"label":"a2-proof-second_20261115-085735","stutter":2.63,"stutter_verdict":"MICRO_STUTTER","idle_share":0.425,"high_variance":true,"working_set_mib":238.672,"noisy_external_pct":0.6}

$ jq -c '{label,hitches:.hitches.count,shader_compile:(.hitches.causes.shader_compile // 0),compiler_busy_ms:.graphics_compiler.busy_ms}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"label":"a2-proof-first_20261115-085621","hitches":6,"shader_compile":0,"compiler_busy_ms":0.227}
{"label":"a2-proof-second_20261115-085735","hitches":4,"shader_compile":0,"compiler_busy_ms":0.292}
```

The first block is the whole assertion of `missing_tables` for a trace holding only the GPU intervals: nine names, sorted. The
second applies the thresholds of `perf_diagnose` and `noisy_environment` by hand: stutter verdicts `SMOOTH` and `MICRO_STUTTER`,
variance high only in the second, a working set far under 1500 MiB, and 0.381 and 0.425 idle shares (both over 0.25: a
`CPU_SUBMISSION_BOUND` bottleneck by the rule, **probable**, the tool not run); and the difference between the GPU's use and the
program's own, -6.4 and 0.6 points, far from the 20 that flags noise. The third block is the input to
`cold_warm_report`: no `shader_compile` hitch in either run, so `first_seen_hitches` would be 0, and `extra_hitches_in_first`
would be `max(0, 6 - 4)` = 2.

### E8 The limits the code enforces

```text
$ rg -n "1 <= count|1 <= rounds|2 <= len\(values\)|> 24|<= seconds <= 600|<= skip <= 600|ok = value|margin = 0 if" src/metal_gpu_trace/experiments.py src/metal_gpu_trace/analysis.py src/metal_gpu_trace/paths.py | cut -c1-190
src/metal_gpu_trace/experiments.py:20:    if not 1 <= count <= 10:
src/metal_gpu_trace/experiments.py:60:    if not 1 <= rounds <= 5:
src/metal_gpu_trace/experiments.py:124:    if not isinstance(values, list) or not 2 <= len(values) <= 8:
src/metal_gpu_trace/experiments.py:153:    if not 1 <= rounds <= 5:
src/metal_gpu_trace/experiments.py:156:    if len(values) * rounds > 24:
src/metal_gpu_trace/paths.py:113:    if not 0 <= seconds <= 600:  # a NaN is false here too
src/metal_gpu_trace/paths.py:124:    if not 0 <= skip <= 600:
src/metal_gpu_trace/analysis.py:325:    margin = 0 if metric.endswith("_p50") else margin_pct / 100
src/metal_gpu_trace/analysis.py:490:        ok = value is not None and (value >= limit if kind == "min" else value <= limit)
```

### What was not reproduced

- **`perf_report.py` on a `.trace`**: no trace exists in the repository (`perf-runs/` has only summaries and tables) and `xctrace`
  was not run. The export, the contents check, `missing_tables`, the crash-tolerant read and the error messages are read from
  the code and pinned by `tests/test_report.py` (not run).
- **Any tool of `analysis.py` and `experiments.py`**: Python was not available to the session; `perf_compare`, `perf_check`, `perf_gate`,
  `perf_diagnose`, `perf_ab`, `perf_cold_warm`, `perf_sweep` and `perf_baseline_record` were evaluated by hand or not at all. A real
  baseline, A B B A and sweep need 4 to 24 recordings.
- **A summary with a non-empty `missing_tables`**, a trace without `metal-gpu-intervals`, a table cut mid-row and an export that times out.
- **A Windows summary's recomputation.**
- **The numbers of 0.27.2**: the two real summaries are generation 1 and older than the code described.

## See also

- [Data and its lifecycle](./data-and-lifecycle.md): the summary's keys one by one, the generations, the tables, the baselines file
  and what deletes what.
- [Recording](./recording.md): how the `.trace` and the `rss.csv` and `agx.csv` samplers are made, the lock, the Windows engine.
- [How it works](./how-it-works.md): which layer calls which.
- [Run from a clone](./run-from-a-clone.md): how to run the code and the tests.
