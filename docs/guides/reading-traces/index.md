# Reading traces

**Reader:** people who ask the server what is inside a recording (a `.trace`, a `.gputrace` or the frames of a run), or who change `traces.py` or `gputrace_read.py`. Reviewed 2026-11-16.

Español: [Leer trazas](../../es/guides/leer-trazas/index.md)

> **In short:** a recording is the raw file a measurement leaves behind; a summary is the few numbers taken from it. These
> seven tools open the raw file itself, so you can ask "what is in it?" without opening Instruments or Xcode. Three read
> an Instruments `.trace`, one turns a run's frames into a timeline Perfetto can show, and three read a Metal `.gputrace`
> capture. This page shows one example of each and says which tool to use; the other pages go deeper, one topic each.

The tools: `trace_tables`, `trace_count`, `trace_query` (open a `.trace` through `xctrace`), `perf_export_trace` (a run's
per-frame table into a file Perfetto opens) and `capture_summary`, `capture_diff`, `capture_records` (read a `.gputrace`
with no Xcode). Not repeated here: [Summarizing and analyzing](../summarizing/index.md) (how `perf_report.py` reads the same
`.trace` for the `<run>.json` summary), [Data and its lifecycle](../data-and-lifecycle/index.md) (which file is deleted when) and
[Recording](../recording/index.md) (how the `.trace` is made).

## The pages of this guide

| Page | One topic |
|---|---|
| [Why it is shaped this way](./why-this-shape.md) | the design choices and the alternatives left out |
| [The `trace` argument](./trace-argument.md) | how a name or path is understood; what a `.trace` is from here |
| [`trace_tables` and `trace_count`](./trace-tables-count.md) | which tables exist and which have rows |
| [`trace_query`](./trace-query.md) | rows, pages and time windows |
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
| **confirmed** | with `file:line`, checked with `rg` or `sed` on 2026-11-16 against the working tree (0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`) |
| **probable** | read from the code, not run here |
| **speculation** | a guess about why |
| **not verified** | an outside fact not checked against its source |
| **not reproduced** | the behaviour could not be run for this guide |

Lines move when the code changes: search the name, not only the number. Every number comes with its command in
[Evidence](./evidence.md). Three limits of method (no real trace or capture in the repo, no Python run, no real `.gputrace`
examined) are written in full at the top of that page: **no tool of this guide was run**.

## One example first

Three questions a person asks an agent. The first is evaluated on a real run of this clone; the other two are read from the
code and its tests.

**1. "Show me this run in Perfetto."** The run `a2-proof-first_20261115-085621` has a per-frame table of 2045 frames (E4).
`perf_export_trace` with that name reads that table, not the `.trace`, writes `a2-proof-first_20261115-085621.chrome-trace`
into the runs folder and answers `{"file": "a2-proof-first_20261115-085621.chrome-trace", "frames": 2045}`. The first row of
the table is `6,1267.79,0.0243,1.7417,11.7952,13.5612`, and the code turns it into one slice (E5):

```text
{"name":"GPU frame","ph":"X","pid":1,"tid":1,"ts":1267790,"dur":13561.2,"args":{"frame":6,"compute":0.0243,"fragment":1.7417,"vertex":11.7952}}
```

`ts` and `dur` are in microseconds (what the Chrome trace format counts in): 1267.79 ms becomes 1 267 790 and 13.5612 ms
becomes 13 561.2. The slice starts 1.27 s into the recording and lasts as long as the frame's GPU time. The tool was **not
run**: E5 is the arithmetic of `traces.py:22-25` done by `awk` on the real row; the test that pins the same arithmetic on a
two-row table is `tests/test_analysis.py:329-332`.

**2. "Which parts of this table are busy?"** `trace_query` with `window_ms=10` on `metal-gpu-intervals` returns one entry per
10 ms window instead of one per row. Three rows that start at 1 ms (2 ms long), 9 ms (1 ms) and 12 ms (4 ms) give two windows:
`{"start_ms": 0, "count": 2, "duration_ms": 3.0}` and `{"start_ms": 10, "count": 1, "duration_ms": 4.0}`. That is the example
of `tests/test_traces.py:42-48` (not run); E6 evaluates it by hand.

**3. "What did my change add to the draw calls?"** `capture_diff` on two `.gputrace` captures counts the confirmed Metal calls
in each and says what changed. The published proof of 0.26.0 shows `drawPrimitives` 3 against 5 (delta 2) and the debug
group `main` going from 2 draws to 4, while `shadow` is not listed because it did not change
([proof of 0.26.0](../../evidence/v0.26.0.md#capture_diff-compares-two-captures)). That pair is **synthetic** (a byte stream
built by a test), not a capture made by Xcode: no real capture has been read by this project's published evidence.

| A reader asks | Short answer | Page |
|---|---|---|
| Why `KEEP_TRACE=1` for `trace_query` and not for `perf_export_trace`? | the first reads the `.trace` (deleted by default after the summary); the second reads the per-frame table that stays | [below](#the-three-ways-to-read-and-where-they-live) |
| Why is paging through a big table slow? | every page runs `xctrace export` again | [trace_query](./trace-query.md) |
| Can the tool say how long a draw call took in a `.gputrace`? | no: names, counts and labels, no time | [the capture tools](./capture-tools.md) |

## The three ways to read, and where they live

![Three rows of three boxes, each row a flow from left to right. Row one, a .trace read by trace_tables, trace_count and trace_query: find the trace, export one table with xctrace, filter and return rows or time windows. Row two, a .gputrace read by capture_summary, capture_diff and capture_records: resolve the bundle inside the readable folders, split its capture file into records, count, compare or list them. Row three, perf_export_trace: find the per-frame table of a run, make one slice per frame, write the Chrome trace file. The text in red marks where each step stops.](./img/three-ways.png)
*Figure 1. The three ways to read a recording. HTML source: `docs/guides/reading-traces/img/three-ways.html`.*

| You have | Ask with | Needs `xctrace` | Needs the `.trace` kept |
|---|---|---|---|
| A run name, want the list of tables | `trace_tables` | yes | yes |
| A run name, want to know which tables have rows | `trace_count` | yes | yes |
| A run name, want the rows (or time windows) of one table | `trace_query` | yes | yes |
| A run name, want its frames in Perfetto | `perf_export_trace` | no | no (needs the per-frame table) |
| A `.gputrace` saved from Xcode | `capture_summary`, `capture_diff`, `capture_records` | no | not a `.trace` at all |

`perf_runs` has a `trace_kept` flag per run (`analysis.py:79`): true when the `<run>.trace` folder exists and is not a link.
It is the quickest way to know whether the first three rows can work for a run (**confirmed**; when a trace is kept:
`KEEP_TRACE=1` or the `deep` tier, see the [data guide](../data-and-lifecycle/index.md)).

| Piece | File | What it does |
|---|---|---|
| The seven tools | `traces.py` | `tool_perf_export_trace` `:9`, `tool_trace_tables` `:33`, `tool_trace_query` `:92`, `tool_trace_count` `:124`, `tool_capture_summary` `:151`, `tool_capture_diff` `:160`, `tool_capture_records` `:169` |
| Registry entries | `registry.py` | name, schema and hints (`:129`, `:159`, `:160`, `:165`, `:172`, `:173`, `:177`) |
| Window grouping | `traces.py` | `check_window` `:42`, `windows_of` `:54` |
| The `xctrace` layer | `perf_report.py` | `export` `:49`, `toc_of` `:81`, `table_xpath` `:90`, `rows` `:143`, `pid_of` `:182` (same code as the summary) |
| The `.gputrace` reader | `gputrace_read.py` | `CALLS` `:20`, `records` `:48`, `stream_of` `:64`, `summarize` `:72`, `counts` `:100`, `diff` `:124`; also a script (`main` `:144`) |
| Paths and paging | `paths.py` | `allowed` `:17`, `trace_path` `:83`, `page` `:94` |
| Per-frame tables | `tables.py` | `find` and `open_text`: both `.csv.gz` and the older `.csv` ([data guide](../data-and-lifecycle/index.md)) |
| What happens to an error | `worker.py` | `call` turns a failure into an `isError` result (`:165-168`) |

`gpu_family` also lives in `traces.py` but reads no recording: [the GPU family facts](./gpu-families.md).

## See also

- [Summarizing and analyzing](../summarizing/index.md): how `perf_report.py` reads the same `.trace`, and the `unpresented` rule that also shapes the per-frame table.
- [Data and its lifecycle](../data-and-lifecycle/index.md): when a `.trace` and a `.chrome-trace` exist and what deletes them.
- [Recording](../recording/index.md): how the `.trace` is made and why it is deleted.
- [How it works](../how-it-works.md): which layer calls which.
- [Proof of 0.26.0](../../evidence/v0.26.0.md#capture_diff-compares-two-captures): the published `capture_diff` example, on synthetic streams.
