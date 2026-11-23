# Reading traces

**Reader:** people who ask the server what is inside a recording (a `.trace`, a `.gputrace` or the frames of a run), or who change `traces.py` or `gputrace_read.py`. Reviewed 2026-11-16.

> **In short:** a recording is the raw file a measurement leaves behind; a summary is the few numbers taken from it. These
> seven tools open the raw file, so you can ask "what is in it?" without Instruments or Xcode: three read an Instruments
> `.trace`, one turns a run's frames into a timeline Perfetto shows, three read a Metal `.gputrace`. One example of each below.

## The pages of this guide

| Page | One topic |
|---|---|
| [Why it is shaped this way](./why-this-shape.md) | the design choices and the alternatives left out |
| [The `trace` argument](./trace-argument.md) | how a name or path is understood; what a `.trace` is from here |
| [`trace_tables` and `trace_count`](./trace-tables-count.md) | which tables exist and which have rows |
| [`trace_query`](./trace-query.md) | rows, pages and time windows |
| [The tables file](./tables-file.md) | `<run>.tables.sqlite`: query a recording after its `.trace` is gone |
| [Exporting a `.chrome-trace`](./chrome-trace.md) | `perf_export_trace`, what the file shows and omits |
| [The `.gputrace` format](./gputrace-format.md) | what the code assumes; the call ids |
| [The capture tools](./capture-tools.md) | `capture_summary`, `capture_diff`, `capture_records`, what they cannot say |
| [The GPU family facts](./gpu-families.md) | `gpu_family`, no recording involved |
| [When it fails](./when-it-fails.md) | every error and its text |
| [Known limits and findings](./limits.md) | limits 1-11 and findings F1-F10, not fixed |
| [Touching it without breaking it](./touching-it.md) | rules for changing the code |
| [Evidence](./evidence.md) | E1-E8, commands and real output; what was not reproduced |

## How to read the labels

| Label | Means |
|---|---|
| **confirmed** | with `file:line`, checked with `rg` or `sed` on 2026-11-16 against the working tree (0.27.3) |
| **probable** | read from the code, not run here |
| **speculation** | a guess about why |
| **not verified** | an outside fact not checked against its source |
| **not reproduced** | the behaviour could not be run for this guide |

Lines move when the code changes: search the name. Every number comes with its command in [Evidence](./evidence.md), whose top
states the three limits of method: **no tool of this guide was run** (no real trace or capture, no Python, no real `.gputrace`).

## One example first

Three questions asked of an agent. The first is evaluated on a real run of this clone; the other two come from code and tests.

**1. "Show me this run in Perfetto."** The run `a2-proof-first_20261115-085621` has a per-frame table of 2045 frames (E4).
`perf_export_trace` reads that table, not the `.trace`, writes `a2-proof-first_20261115-085621.chrome-trace` into the runs
folder and answers `{"file": "a2-proof-first_20261115-085621.chrome-trace", "frames": 2045}`. The first row,
`6,1267.79,0.0243,1.7417,11.7952,13.5612`, becomes one slice (E5):

```text
{"name":"GPU frame","ph":"X","pid":1,"tid":1,"ts":1267790,"dur":13561.2,"args":{"frame":6,"compute":0.0243,"fragment":1.7417,"vertex":11.7952}}
```

`ts` and `dur` are microseconds (the Chrome trace format's unit): 1267.79 ms becomes 1 267 790 and 13.5612 ms becomes 13 561.2.
The slice starts 1.27 s in and lasts the frame's GPU time. The tool was **not run**: E5 is the arithmetic of `traces.py::tool_perf_export_trace`
by `awk`; the test pinning it is `tests/test_analysis.py::test_cold_warm`.

**2. "Which parts of this table are busy?"** `trace_query` with `window_ms=10` on `metal-gpu-intervals` returns one entry per
10 ms window. Rows starting at 1 ms (2 ms long), 9 ms (1 ms) and 12 ms (4 ms) give `{"start_ms": 0, "count": 2, "duration_ms": 3.0}`
and `{"start_ms": 10, "count": 1, "duration_ms": 4.0}` (`tests/test_traces.py::test_window_ms_groups_rows_by_window`, not run; E6 by hand).

**3. "What did my change add to the draw calls?"** `capture_diff` on two `.gputrace` captures counts the confirmed Metal calls in
each. The [proof of 0.26.0](../../evidence/v0.26.0.md#capture_diff-compares-two-captures) shows `drawPrimitives` 3 against 5
(delta 2) and the debug group `main` going from 2 draws to 4; `shadow` is not listed because it did not change. That pair is
**synthetic** (a byte stream built by a test): no real capture has been read by the project's published evidence.

## The three ways to read, and where they live

![Three rows of three boxes, each row a flow from left to right. Row one, a .trace read by trace_tables, trace_count and trace_query: find the trace, export one table with xctrace, filter and return rows or time windows. Row two, a .gputrace read by capture_summary, capture_diff and capture_records: resolve the bundle inside the readable folders, split its capture file into records, count, compare or list them. Row three, perf_export_trace: find the per-frame table of a run, make one slice per frame, write the Chrome trace file. The text in red marks where each step stops.](./img/three-ways.png)
*Figure 1. The three ways to read a recording. HTML source: `docs/guides/reading-traces/img/three-ways.html`.*

| You have | Ask with | Needs `xctrace` | Needs the `.trace` kept |
|---|---|---|---|
| A run name: the list of tables, which have rows, or the rows (or time windows) of one | `trace_tables`, `trace_count`, `trace_query` | yes, if it reads the `.trace`; not with the tables file | no: the tables file (`<run>.tables.sqlite`) is enough. With a kept `.trace` (`KEEP_TRACE=1`) it reads that; every page re-exports, so big tables are slow: [trace_query](./trace-query.md) |
| A run name: its frames in Perfetto | `perf_export_trace` | no | no (reads the per-frame table, which stays) |
| A `.gputrace` saved from Xcode | `capture_summary`, `capture_diff`, `capture_records` | no | not a `.trace`; names, counts, labels, no time ([capture tools](./capture-tools.md)) |

`perf_runs` also has `tables_kept` (`analysis.py::tool_perf_runs`): true when `<run>.tables.sqlite` exists and is not a link; [the tables file](./tables-file.md) says what it holds.

`perf_runs` has a `trace_kept` flag per run (`analysis.py::tool_perf_runs`): true when the `<run>.trace` folder exists and is not a link, so
it tells whether the first three rows can work (**confirmed**; a trace is kept with `KEEP_TRACE=1` or the `deep` tier, see the
[data guide](../data-and-lifecycle/index.md)).

| Piece | File | What it does |
|---|---|---|
| The seven tools | `traces.py` | `tool_perf_export_trace` `traces.py::tool_perf_export_trace`, `tool_trace_tables` `traces.py::tool_trace_tables`, `tool_trace_query` `traces.py::tool_trace_query`, `tool_trace_count` `traces.py::tool_trace_count`, `tool_capture_summary` `traces.py::tool_trace_query`, `tool_capture_diff` `traces.py::tool_trace_query`, `tool_capture_records` `traces.py::tool_trace_query` |
| Registry entries | `registry.py` | name, schema and hints (`registry.py::TOOLS`); window grouping lives in `traces.py`: `check_window` `traces.py::check_window`, `windows_of` `traces.py::windows_of` |
| The `xctrace` layer | `perf_report.py` | `export` `perf_report.py::export`, `toc_of` `perf_report.py::toc_of`, `table_xpath` `perf_report.py::toc_of`, `rows` `perf_report.py::rows`, `pid_of` `perf_report.py::rows` (same code as the summary) |
| The `.gputrace` reader | `gputrace_read.py` | `CALLS` `gputrace_read.py::CALLS`, `records` `gputrace_read.py::records`, `stream_of` `gputrace_read.py::stream_of`, `summarize` `gputrace_read.py::summarize`, `counts` `gputrace_read.py::counts`, `diff` `gputrace_read.py::diff`; also a script (`main` `gputrace_read.py::main`) |
| Paths and paging | `paths.py` | `allowed` `paths.py::allowed`, `trace_path` `paths.py::trace_path`, `page` `paths.py::page` |
| Per-frame tables | `tables.py` | `find` and `open_text`: both `.csv.gz` and the older `.csv` ([data guide](../data-and-lifecycle/index.md)) |
| What happens to an error | `worker.py` | `call` turns a failure into an `isError` result (`worker.py::call`) |

`gpu_family` also lives in `traces.py` but reads no recording: [the GPU family facts](./gpu-families.md).

## See also

[Summarizing and analyzing](../summarizing/index.md) (how `perf_report.py` reads the same `.trace` for the `<run>.json` summary; the `unpresented` rule that also shapes the per-frame table) · [Data and its lifecycle](../data-and-lifecycle/index.md) (when a `.trace` and a `.chrome-trace` exist, what deletes them) · [Recording](../recording/index.md) (how the `.trace` is made, why it is deleted) · [How it works](../how-it-works.md) (which layer calls which) · [Proof of 0.26.0](../../evidence/v0.26.0.md#capture_diff-compares-two-captures) (the published `capture_diff` example, on synthetic streams).
