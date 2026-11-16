# Reading traces

**Reader:** people who ask the server what is inside a recording (a `.trace`, a `.gputrace` or the frames of a run), or who change `traces.py` or `gputrace_read.py`. Reviewed 2026-11-16.

Español: [Leer trazas](../es/guides/leer-trazas.md)

This page covers the tools that **read a recording itself** instead of its summary: `trace_tables`, `trace_count` and
`trace_query` (they open an Instruments `.trace` through `xctrace`), `perf_export_trace` (turns a run's per-frame table into
a file that Perfetto opens), and `capture_summary`, `capture_diff` and `capture_records` (they read a Metal `.gputrace`
capture with no Xcode at all). It explains how each one finds its file, what it returns, what the format of a `.gputrace`
is as far as the code knows it, where each tool stops and what the caller sees when it fails. It does not repeat
[Summarizing and analyzing](./summarizing.md) (how `perf_report.py` reads the same `.trace` to write the `<run>.json`
summary and every number in it), [Data and its lifecycle](./data-and-lifecycle.md) (which file is deleted when, including the
`.trace` and the `.chrome-trace`) or [Recording](./recording.md) (how the `.trace` is made); it links to them where the story
continues.

How to read the labels: every technical claim is **confirmed** (with `file:line`, checked with `rg` or `sed` on
2026-11-16 against the working tree, which is 0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`), **probable**
(read from the code but not run here) or **speculation** (a guess about why). **Not verified** marks an outside fact that was
not checked against its source. Lines move when the code changes: search the name, not only the number. Every number comes
with the command that produced it, in [Evidence](#evidence-the-commands-and-their-real-output). **Not reproduced** means the
behaviour could not be run for this page. Three limits apply. First, the repository holds **no `.trace`, no `.chrome-trace`
and no `.gputrace`** (E3), and reading a `.trace` needs `xctrace`, so none of the `trace_*` tools was run. Second, the session
that wrote this page could run read-only shell commands (`rg`, `sed`, `awk`, `jq`, `wc`) and could not run Python, so no tool
of `traces.py` or `gputrace_read.py` was run either: what they return is read from the code, evaluated by hand on the two real
runs of the clone where a run is needed, and pinned by tests that are named, not run. Third, no real `.gputrace` has been
examined for this page or for the project's published proof (see [the format](#what-is-inside-a-gputrace)), so every claim
about the format is the code's own claim.

## One example first

Three questions a person asks an agent, and what each tool does. The first is evaluated on a real run of this clone; the
other two are read from the code and its tests.

**1. "Show me this run in Perfetto."** The run `a2-proof-first_20261115-085621` has a per-frame table of 2045 frames (E4).
`perf_export_trace` with that run name reads that table, not the `.trace`, and writes `a2-proof-first_20261115-085621.chrome-trace`
into the runs folder; it answers `{"file": "a2-proof-first_20261115-085621.chrome-trace", "frames": 2045}`. The first frame of
the table is `6,1267.79,0.0243,1.7417,11.7952,13.5612`, and the code turns it into one slice (E5):

```text
{"name":"GPU frame","ph":"X","pid":1,"tid":1,"ts":1267790,"dur":13561.2,"args":{"frame":6,"compute":0.0243,"fragment":1.7417,"vertex":11.7952}}
```

`ts` and `dur` are in microseconds (what the Chrome trace format counts in), so 1267.79 ms becomes 1 267 790 and 13.5612 ms
becomes 13 561.2. The slice starts 1.27 s into the recording and lasts as long as the frame's GPU time. The tool was **not
run**: E5 is the arithmetic of `traces.py:22-25` done by `awk` on the real row, and the test that pins the same arithmetic on
a two-row table is `tests/test_analysis.py:329-332`.

**2. "Which parts of this table are busy?"** `trace_query` with `window_ms=10` on `metal-gpu-intervals` returns one entry per 10 ms
window instead of one entry per row. For three rows that start at 1 ms (2 ms long), 9 ms (1 ms) and 12 ms (4 ms), the answer
is two windows: `{"start_ms": 0, "count": 2, "duration_ms": 3.0}` and `{"start_ms": 10, "count": 1, "duration_ms": 4.0}`.
That is the example of `tests/test_traces.py:42-48` (not run), and E6 evaluates it by hand from the formula.

**3. "What did my change add to the draw calls?"** `capture_diff` on two `.gputrace` captures counts the confirmed Metal calls
in each and says what changed. The published proof of 0.26.0 shows the pair: `drawPrimitives` 3 against 5 (delta 2), and the
debug group `main` going from 2 draws to 4 while `shadow` is not listed because it did not change
([proof of 0.26.0](../evidence/v0.26.0.md#capture_diff-compares-two-captures)). That pair is **synthetic** (a byte stream built by
a test), not a capture made by Xcode: no real capture has been read by this project's published evidence.

What a reader asks, and where this page answers:

1. *Why do I need `KEEP_TRACE=1` for `trace_query` and not for `perf_export_trace`?* Because the first reads the `.trace`
   (deleted by default after the summary is written) and the second reads the per-frame table that stays
   ([the three ways to read](#the-pieces-and-where-they-live)).
2. *Why does paging through a big table feel slow?* Every page runs `xctrace export` again ([trace_query](#trace-query-rows-pages-and-windows)).
3. *Can the tool tell me how long a draw call took in a `.gputrace`?* No: the reader exposes names, counts and labels, no time
   ([what it cannot read](#what-the-reader-cannot-tell-you)).

## Why this part is shaped this way

| Choice | Why | Alternatives that were left out |
|---|---|---|
| A `.trace` is read **one table per call**, through `xctrace export` | A recording holds 85 tables in the one measured (E8); each export keeps a temporary store that can reach gigabytes on a big trace (`perf_report.py:39`), so asking for the one table wanted is what keeps disk and time bounded | Exporting the whole trace once and answering from it: gigabytes of XML on disk for a question about one table |
| `trace_query` caches nothing: every page runs the export again | `trace_query` builds its rows from a fresh export on each call and deletes the file when it finishes (`traces.py:101`, `:113-114`); the code has no cache. **Speculation:** the reason is the disk cost of keeping an XML file of the table | Keeping the exported XML between pages: a stale file could be read after the trace is gone, and it would hold the table twice |
| `window_ms` sums a table by time window | A table of hundreds of thousands of rows cannot be read row by row; the docstring says it is "a summary of a table too long to read row by row" (`traces.py:93-96`) | Returning more rows per page: the page is capped at 500 rows and 40 000 characters ([limits](#known-limits)) |
| `perf_export_trace` reads the per-frame table, not the `.trace` | The `.trace` is deleted by default ([ADR-0006](../adr/0006-compressed-tables-and-disk-quota.md), `perf_record.sh:162-163`) and the per-frame table stays, so the export works on a run whose trace is long gone (`traces.py:15`) | Reading the `.trace`: it would only work with `KEEP_TRACE=1`, and it would need `xctrace` again |
| The `.gputrace` reader is written by hand with `struct` | No Xcode is needed on the machine that reads, and the server is standard library only (`CLAUDE.md`, [ADR-0003](../adr/0003-python-3-9-floor.md)); `struct` and `re` are enough for a stream of records (`gputrace_read.py:9-14`) | Calling Xcode or a private framework: it would tie the tool to a machine with Xcode, and the format of the call list is not public |
| Every Metal call carries a **certainty**, and `capture_diff` counts only the confirmed ones | The call ids were worked out by hand: 17 of the 24 named ids are `"confirmado"` and 7 are `"probable"` (E2). A diff that counted a guess would report a change that may not exist (`gputrace_read.py:117`) | Counting every id: a wrong name would show up as a change |
| `capture_diff` aligns by **debug group label**, not by position | Two captures of the same scene often draw in a different order; a group is matched by its label, so a reordered group is not a difference (`gputrace_read.py:124-128`, E1 of the 0.26.0 proof) | Comparing record by record: a single added call shifts everything after it |
| Paths are checked before anything opens | A `.gputrace` path must lie inside `METAL_TRACE_OUT` or `METAL_TRACE_READ` (`paths.py:17-22`); a `.trace` name resolves inside the runs folder and a link is refused (`paths.py:83-91`) | Reading any path: a client could ask the server to open a file anywhere the user can |

## The pieces and where they live

| Piece | File | What it does |
|---|---|---|
| The tools of this page | `traces.py` | `tool_perf_export_trace` `:9`, `tool_trace_tables` `:33`, `tool_trace_query` `:92`, `tool_trace_count` `:124`, `tool_capture_summary` `:151`, `tool_capture_diff` `:160`, `tool_capture_records` `:169` |
| The registry entries | `registry.py` | name, input schema and hints of each tool (`:129`, `:159`, `:160`, `:165`, `:172`, `:173`, `:177`) |
| Window grouping | `traces.py` | `check_window` `:42`, `windows_of` `:54` |
| The `xctrace` layer | `perf_report.py` | `export` `:49`, `toc_of` `:81`, `table_xpath` `:90`, `rows` `:143`, `pid_of` `:182` (the same code the summary uses) |
| The `.gputrace` reader | `gputrace_read.py` | `CALLS` `:20`, `records` `:48`, `stream_of` `:64`, `summarize` `:72`, `counts` `:100`, `diff` `:124`; also a script (`main` `:144`) |
| Paths and paging | `paths.py` | `allowed` `:17`, `trace_path` `:83`, `page` `:94` |
| Per-frame tables | `tables.py` | `find` and `open_text`: both the `.csv.gz` and the older `.csv` ([data guide](./data-and-lifecycle.md)) |
| What happens to an error | `worker.py` | `call` turns a failure into an `isError` result (`:165-168`) |

One more tool lives in `traces.py` for a different reason: `gpu_family`, with the two kinds of resource
`metal-trace://gpu-families` and `metal-trace://gpu-families/<family>`, gives Apple's published facts about a GPU family
([below](#the-gpu-family-facts)). They read no recording.

![Three rows of three boxes, each row a flow from left to right. Row one, a .trace read by trace_tables, trace_count and trace_query: find the trace, export one table with xctrace, filter and return rows or time windows. Row two, a .gputrace read by capture_summary, capture_diff and capture_records: resolve the bundle inside the readable folders, split its capture file into records, count, compare or list them. Row three, perf_export_trace: find the per-frame table of a run, make one slice per frame, write the Chrome trace file. The text in red marks where each step stops.](/diagrams/reading-traces.png)
*Figure 1. The three ways to read a recording. HTML source: `docs/diagrams/reading-traces.html`.*

Which one to use, by what you have in hand:

| You have | Ask with | Needs `xctrace` | Needs the `.trace` kept |
|---|---|---|---|
| A run name and want the list of tables | `trace_tables` | yes | yes |
| A run name and want to know which tables have rows | `trace_count` | yes | yes |
| A run name and want the rows (or time windows) of one table | `trace_query` | yes | yes |
| A run name and want to see its frames in Perfetto | `perf_export_trace` | no | no (needs the per-frame table) |
| A `.gputrace` saved from Xcode | `capture_summary`, `capture_diff`, `capture_records` | no | not a `.trace` at all |

`perf_runs` has a `trace_kept` flag per run (`analysis.py:79`): it is true when the `<run>.trace` folder exists and is not a
link. It is the quickest way to know whether the first three rows can work for a run (**confirmed**; see the
[data guide](./data-and-lifecycle.md) for when a trace is kept: `KEEP_TRACE=1`, or the `deep` tier).

## Reading a `.trace` through `xctrace`

### How a `trace` argument is understood

The `trace` argument of all three tools is described as "a run name from perf_runs whose trace_kept is true, or the path of a
.trace" (`registry.py:20`). `paths.trace_path` (`:83-91`) decides which:

- If the text is a valid **name** (`name_ok`: letters, digits, `.`, `_` and `-`, at most 120 bytes; `paths.py:25-30`), it is
  `<runs folder>/<name>.trace`, with a trailing `.trace` on the name accepted. A link at that place is refused with
  `<name>.trace cannot be read` (`:88-89`).
- Otherwise it is a path and goes through `allowed` (`:91`): resolved, and it must lie inside the runs folder or one of the
  folders in `METAL_TRACE_READ`; if not, `<name> is outside the readable directories; add its directory to METAL_TRACE_READ`
  (`paths.py:20-21`).

A consequence worth knowing (**confirmed** from the code, **not run**): `foo.trace` has no `/`, so it counts as a run name
and is looked up in the runs folder; a `.trace` that lives elsewhere needs a path with a directory in it (for example
`./foo.trace`, or an absolute path inside `METAL_TRACE_READ`).

The folder must exist as a directory: `export` checks it first and raises `no recording at <name>: perf_record.sh deletes the
.trace once its summary is written, unless KEEP_TRACE=1` (`perf_report.py:52-54`). That sentence is what a client sees for a
trace that was already deleted, and it is the most likely error of this whole page.

### What a `.trace` looks like from here

A `.trace` is a **bundle**: a folder Instruments writes and `xctrace` reads. This project never opens its insides; it asks
`xctrace` for two things (**confirmed**, `perf_report.py:49-66`):

1. The **table of contents**: `xcrun xctrace export --input <trace> --output <temporary.xml> --toc`. It is an XML document
   whose root is `trace-toc`, with `run` elements (the code always reads `run number="1"`, `perf_report.py:92`), each with a
   `data` element holding one `table` element per **table** and the table's `schema` attribute as its name
   (`traces.py:36`, `:100`).
2. One **table**: the same command with `--xpath '/trace-toc/run[@number="1"]/data/table[@schema="<name>"]'` instead of
   `--toc`. The result is XML with a `schema` that lists the columns (each `col` has a `mnemonic`, the column's name) and one
   `row` element per row, whose cells are children named after the columns (`perf_report.py:143-179`; the shape is the fixture
   of `tests/test_traces.py:11-16`). Cells carry the value as text and often a `fmt` attribute with the formatted version
   (`traces.py:111`). To keep a big table small, `xctrace` writes a repeated value once with an `id` and later cells refer to
   it with `ref`; `rows` resolves those references while it reads (`perf_report.py:131-170`, see the
   [summarizing guide](./summarizing.md#step-1-export)).

The names of the tables are Instruments' own and are not listed by this project (they are whatever `trace_tables` returns).
One measurement of what a real recording holds: an 8-second recording of a test program at the `deep` tier, made on
2026-11-15 on an Apple M1 Pro with `xctrace` 27.2, exported **85 tables**, 59 with rows and 26 empty (E8; the project's own
research note of that date, not published; **not reproduced here**). The summary reads the handful that matter
([the table of tables in the summarizing guide](./summarizing.md#step-2-the-table-of-contents-and-missing-tables)); the rest are
there for `trace_query`.

### `trace_tables`: what is in this trace

`tool_trace_tables` (`traces.py:33-36`) asks for the table of contents, collects every `table` element that has a `schema`
attribute and returns `{"tables": [<sorted names>]}`. Nothing else: no row counts, no sizes. It is the cheapest of the three
calls and the one to start from: the next two need a name from it.

### `trace_count`: which tables have rows

A table can exist and be empty. The recording of E8 has 26 empty ones, among them the shader *spill* table, which is empty
unless a program spills registers. `tool_trace_count` (`traces.py:124-148`) answers exactly that, before anybody reads a
page of nothing: for each table named it exports the table and counts the rows, in all and per process:

```text
{"trace": "<name>", "tables": {"<schema>": {"rows": 3, "by_process": {"<name> (42)": 2, "<name> (7)": 1}}, ...}}
```

(the shape is what `tests/test_report.py:207-208` asserts, with synthetic process names; not run).

- With no `tables` argument it counts the ten in `COUNTED_TABLES` (`traces.py:117-121`): the GPU intervals, the encoder list,
  command-buffer completion, the shader compiler's spill and activity tables, the shader profiler's list and samples, resource
  allocations, GPU counter intervals and `time-profile`.
- A name that is not in the trace's table of contents is not an error: it comes back as `{"rows": None, "note": "not in this
  trace"}` (`:133-135`). **A table with `rows: 0` and a table that is not there are different answers.**
- A name must hold only letters, digits and `-`, else `a table name holds only letters, digits and '-'; trace_tables lists them`
  (`:131-132`). The check protects the xpath, which is built by inserting the name into a string (`:136`).
- `by_process` keeps the ten processes with the most rows, named as the table names them (`name (pid)`) or by the pid when
  the cell has no text (`:142`, `:147`). The tool's note says it plainly: "a table with 0 rows needs another instrument or
  Xcode, not a bigger page" (`:125-126`).
- One table's export failing does not stop the others: a `RuntimeError` or a timeout is caught and that table gets
  `{"rows": None, "note": <the error text>}` (`:144-146`).

The names in `by_process` are the names of **whatever ran on the machine** while it was recorded, not only the program under
test (the same measurement shows a browser helper among the busiest processes of the GPU table, E8). They travel to the
client in the result. They are not written to a summary (`perf_report.py:584-590` keeps no name there), but anyone who pastes
a `trace_count` result into a shared place carries them along.

### `trace_query`: rows, pages and windows

`tool_trace_query(trace, schema, offset=0, limit=50, pid=None, window_ms=None)` (`traces.py:92-114`) returns one page of one
table. In order:

1. `check_window` (`:42-51`) validates `window_ms`: `None` stays `None`; a whole float such as `10.0` counts as `10`; a bool, a
   fraction, `0`, a negative or more than `3 600 000` is `window_ms is a whole number of milliseconds from 1 to 3600000`.
2. The schema name must hold only letters, digits and `-` (`:98-99`).
3. The table is exported with the xpath of `:100` and read by `perf_report.rows` (`:101`).
4. With `pid`, rows of other processes are dropped. The filter is
   `pid is None or "process" not in row or perf_report.pid_of(row["process"]) == int(pid)` (`:102-103`): a table **without** a
   `process` column is returned whole whatever `pid` says. The tool's description says "keep only this process's rows", so a
   reader may expect an empty answer for such a table ([finding F6](#new-findings-in-the-code-not-fixed)).
5. Without `window_ms`, every row becomes `{column: value}` where the value is the cell's `fmt` text when it has one, else its
   text (`:111`). That is the value as Instruments shows it. **Probable:** for a time column it may read like `1.5 ms` where
   the raw text is nanoseconds, which is why the windows below read `.text` and not `fmt` (`:68`, `:79`). It is then
   cut into one page by `paths.page` (`:111-112`).
6. The file `rows` read is deleted in a `finally` (`:113-114`), also when the windows code raised; a test checks that
   (`tests/test_traces.py:118-124`, not run).

**Paging.** `paths.page(items, offset, limit)` (`paths.py:94-99`) clamps `offset` to 0 or more and `limit` to 1..500
(`config.MAX_LIMIT`, `config.py:43`; the schema says "default 50, at most 500", `registry.py:19`) and returns:

```text
{"total": <all rows>, "offset": <n>, "rows": [...], "next_offset": <n + len(rows), or null at the end>}
```

`next_offset: null` is how a client knows it reached the end. Everything is computed from a **list of all the rows**
(`:111-112` builds it, `:94-99` slices it), and each call exports the table again, so reading a table of a million rows in
pages of 500 runs the export 2000 times. The code has no cache (**confirmed**); the cost of one export of a large table was
**not measured here**. If one export is slower than 600 seconds, the call ends with `subprocess.TimeoutExpired`, which the
worker turns into an error result (`worker.py:165-168`; the timeout is `perf_report.py:49`).

**Windows.** With `window_ms`, `windows_of(selected, window_ms)` (`traces.py:54-89`) replaces the rows:

- The **first row decides the shape**: its time column is `start` if it has one, else `time` (`TIME_COLUMNS`, `:39`, `:62`),
  and the table has a duration column when the first row has `duration` (`:63`). A table with neither time column fails
  with `window_ms needs a table with a time column (start or time); trace_tables lists the tables and trace_query without
  window_ms shows the columns` (`:64-66`).
- Each row's time is `int(cell.text)` in nanoseconds; a window is `ns // (window_ms × 1 000 000)` (`:68`, `:74`). A row
  whose time is not a number, is negative or is missing is counted in `skipped_rows` (`:69-73`); the answer carries
  `skipped_rows` only when it is not 0 (`:108-109`).
- A window is `{"start_ms": index × window_ms, "count": N}` and, when the table has a duration, `"duration_ms"`: the **sum**
  of its rows' durations in ms, rounded to 3 decimals (`:75-87`). A row whose duration cannot be read still counts but adds
  nothing (`:77-81`). Only windows that hold a row are listed, in time order (`:83-84`), and they are paged like rows
  (`:107`), the answer also carrying `window_ms`.
- Because durations are summed, the sum of parallel work in one window can be larger than the window: the same caveat as
  the [per-frame GPU sum](./summarizing.md#gpu-time-per-frame-is-a-sum-over-channels).

The twelve tests of `tests/test_traces.py` pin all of this: windows by 10 ms, a `time` column without duration, rejection of
zero, negatives and non-numbers, a table without a time column, an empty table, rows without a usable time, a whole float,
paging, the pid filter and the deletion of the file. They were **not run** for this page.

## Exporting a `.chrome-trace`

`tool_perf_export_trace(run)` (`traces.py:9-30`) answers "show me the frames of this run in a timeline". The file it writes is
JSON in the Chrome trace event format, which `ui.perfetto.dev` and `chrome://tracing` open (the docstring says so,
`traces.py:10-13`; the viewers were **not opened** for this page).

How it works, in order:

1. `paths.run_path(run)` checks the name and that `<run>.json` exists, is not a link and is not `baselines.json`
   (`traces.py:14`, `paths.py:33-41`). An unknown run is `no run <name>; perf_runs lists them`.
2. `table_files.find(config.OUT, f"{run}.frames")` looks for `<run>.frames.csv.gz` first and `<run>.frames.csv` second, and
   not for a link (`traces.py:15`, `tables.py:13-20`). None: `<run> has no per-frame file; record it again` (`:16-17`).
3. For every row of the table it builds one **complete event** (`"ph": "X"`, a slice with a start and a length) named
   `GPU frame`, on process 1 and thread 1: `ts = start_ms × 1000`, `dur = gpu_ms_total × 1000` (microseconds), and in `args`
   the frame number plus each `gpu_ms_<channel>` column except the total, with the `gpu_ms_` prefix cut (`compute`,
   `fragment`, `vertex`) (`:22-25`).
4. A table that cannot be read, has a missing column or holds a value that is not a number is
   `<file name> cannot be read; record it again` (`:26-27`); no partial file is written.
5. It writes `{"traceEvents": [...], "displayTimeUnit": "ms"}` to `<runs folder>/<run>.chrome-trace` and returns
   `{"file": "<run>.chrome-trace", "frames": <events>}` (`:28-30`). `paths.write_file` replaces an older file of that name
   and refuses to write through a link (`paths.py:69-80`). The tool's hints say it is idempotent and not destructive
   (`registry.py:129-131`): running it twice writes the same file.

What the file shows and what it does not:

- **One track, one slice per frame.** Everything is on process 1 and thread 1, so a frame whose slice is longer than the gap to
  the next one overlaps it; Perfetto will stack them. The frame's length is its GPU time, the **sum** over the three channels
  (`gpu_ms_total`), not the time between its first and last interval. The docstring says a frame with parallel encoders "can show
  shorter than it took", but a sum of parallel work is longer than the elapsed time, not shorter ([finding F8](#new-findings-in-the-code-not-fixed)).
- **Only the frames the summary kept.** A stretch of the recording where the program rendered but did not present is left out
  of `frames.csv` (see [Work that was never presented](./summarizing.md#work-that-was-never-presented)), so it is also left out
  of the timeline. On the second real run of the clone the table has 153 frames (E4) for 20 seconds of recording.
- **No encoders, no command buffers, no memory.** It is one coarse track; the finer view is `trace_query` on the GPU intervals
  of a kept `.trace`.
- **The file is a retention kind of its own.** A `.chrome-trace` is the second thing the disk quota deletes, after a `.trace`
  and before the tables, except that the **current** run's export stays (`retention.py:5-8`, `:30-43`, the
  [data guide](./data-and-lifecycle.md) has the full order). It does not make a new run: `perf_runs` does not list it
  (`tests/test_analysis.py:333`, not run).

## Reading a `.gputrace` without Xcode

### What is inside a `.gputrace`

**Read this paragraph first: the project has not examined a real capture.** The module's docstring says the 8-byte header, the
call ids and their names "were worked out here against a capture whose command list Xcode showed (macOS 27.0.1)"
(`gputrace_read.py:7-8`). But the research of 2026-11-15 that was meant to study the format records that it was **not done**,
because it "needs two real captures made in Xcode" and there was none on that Mac; and the proof of `capture_diff` (0.26.0)
lists as **not tested** "two real captures made by Xcode (none was on this Mac)". The two statements are not reconciled
anywhere in the repository ([finding F5](#new-findings-in-the-code-not-fixed)). What this page can say is therefore limited to
what the code does and what its tests construct. The record layout follows the public project
[tmc/gputrace](https://github.com/tmc/gputrace) (MIT; the module says so at `gputrace_read.py:6`, and no code is copied,
README "Credits"); **not verified here** against that project's source.

What the code assumes (**confirmed** as assumptions, `gputrace_read.py:1-8`, `:48-69`):

- A `.gputrace` is a **folder** (a bundle) saved from Xcode. The reader opens **one file** in it, called `capture`
  (`stream_of`, `:64-69`); any other file in the bundle is not read, and what else a real bundle holds was not examined.
- `capture` is a stream called **MTSP**: the first 4 bytes are the ASCII `MTSP`, the next 4 are a word the reader skips
  (`off = 8`, `:51`). If the magic is not there the reader starts at 0 instead of failing.
- After that come **records**, one after the other. Each starts with `[u32 size][i32 call id]`, little-endian
  (`struct.unpack_from("<Ii", ...)`, `:53`), and `size` is the length of the **whole** record, those 8 bytes included, so the
  next record starts `size` bytes later (`:56`, `:61`).
- Inside a record, at offset `0x24` (36), there is a **signature**: a short ASCII string ended by a zero byte. The synthetic
  records of the tests use `Cuu` (`tests/test_capture.py:20`). **Speculation:** it names the types of the call's arguments.
  After the signature come the arguments (`:57-58`).
- The reader does not decode arguments. It extracts the **printable ASCII runs of 3 or more characters** after the signature
  (`re.findall(rb"[ -~]{3,}", tail)`, `:59`) and calls them `strings`. For a `pushDebugGroup` the first one is the **label**
  the program gave the group; that is the only argument anything depends on.
- The docstring also lists a `u32` at `+0x20` (`:5`); the code never reads it.

```text
 the file:   [MTSP][word][record 1][record 2] ... to the end of the file
             bytes 0-3  4-7   from byte 8, one after the other

 one record: [u32 size][i32 call id][ ... ][signature, NUL][arguments ...]
             the signature starts at offset 0x24 of the record
             size counts the whole record, these 8 bytes included
```

A record that cannot be parsed stops the whole read. If `size` is under 8, or the record would run past the end of the file,
the reader raises `ValueError`: `<bundle name>: record at 0x<offset> has size <n>; the stream is not MTSP as expected`
(`:54-55`, with only the bundle's folder name, never its path; pinned by `tests/test_capture.py:86-97`, not run). Fewer than
8 bytes left at the end of the file are ignored without a word (`while off + 8 <= len(data)`, `:52`).

**The call ids.** `CALLS` (`gputrace_read.py:20-45`) maps 24 call ids to a Metal call name and a certainty. Ids are negative
numbers; the code gives no reason for the numbering (**not verified**). The names are Metal's API names:

| Group | Calls | Certainty |
|---|---|---|
| Debug markers (3) | `pushDebugGroup` -16244, `insertDebugSignpost` -16245, `popDebugGroup` -16243 | `confirmado` |
| Drawing (1) | `drawPrimitives` -16218 (one overload only, `:88`) | `confirmado` |
| State a draw depends on (13) | `setRenderPipelineState`, `setDepthStencilState`, `setStencilReferenceValue`, `setTriangleFillMode`, `setCullMode`, `setDepthClipMode`, `setDepthBias`, `setFrontFacingWinding`, `setBlendColor`, `setViewports`, `setScissorRects`, `setVertexBufferOffset`, `useResource` | `confirmado` |
| Structure (3) | `renderCommandEncoder` -16353, `endEncoding` -16246, `commandBuffer` -16343 | `probable` |
| Other (4) | `buffer contents` -10240, `drawMeshThreadgroups` -15416, `drawMeshThreadgroupsWithIndirectBuffer` -15415, `dispatchThreadgroups` -16327 | `probable` |

The two words are Spanish in the code (`"confirmado"`, `"probable"`) and are returned as written in the `certainty` field of
`capture_summary`. `confirmado` means "matched one by one against Xcode's command list" (`:19`); `probable` is a name that
fits but was not matched. A record whose id is not in the table has `name: None`: it is counted, shown by id and
signature, and never named. Whether a real capture uses ids that are not here (indexed, instanced, indirect and mesh draws
have their own, per the comment at `:88`) is **unknown**.

### `capture_summary`

`tool_capture_summary(capture)` (`traces.py:151-157`) resolves the path with `paths.allowed` (readable folders only) and
calls `gputrace_read.summarize` (`:72-97`), which reads every record once and returns:

| Key | What it is |
|---|---|
| `capture` | the bundle's name, never its path |
| `records` | how many records the stream has |
| `command_buffers` | how many records have id -16343 (`commandBuffer`) |
| `render_encoders` | how many have id -16353 (`renderCommandEncoder`) |
| `draw_primitives` | how many have id -16218; indexed, mesh and indirect draws have other ids and are **not** counted (`:88-89`) |
| `debug_groups` | the labels of the `pushDebugGroup` records, in order (the first printable string of each; no cut here) |
| `signposts` | the same for `insertDebugSignpost` |
| `pops` | how many `popDebugGroup` records |
| `calls` | every distinct `(id, signature)` with its `count`, `name` and `certainty`, most frequent first |

The tool then adds `calls_total` (how many distinct `(id, signature)` pairs there are) and keeps only the first 100 of
`calls` (`traces.py:155-156`). `calls_total` is not the number of records: that is `records`.

Notice that `command_buffers` and `render_encoders` are counted from ids that the table calls `probable`, and the answer
does not say so next to those two numbers (only the entries of `calls` carry `certainty`). Read them as probable
([finding F3](#new-findings-in-the-code-not-fixed)).

### `capture_diff`

`tool_capture_diff(a, b)` (`traces.py:160-166`) calls `gputrace_read.diff` (`:124-141`), which calls `counts` (`:100-121`)
for each capture. `counts` walks the records with a stack of open debug groups:

- On `pushDebugGroup` it opens a group named by its label: the first printable string, **cut at 200 characters**; a push with
  no string of 3 or more characters is named `(unnamed)`, so all such groups merge (`:110-113`).
- On `popDebugGroup` it closes the innermost one; a pop with nothing open is ignored (`:114-116`).
- Any other record whose name is **confirmed** and is not a signpost adds 1 to the capture's total for that name and to the
  innermost open group, if there is one (`:117-120`). Records with `probable` ids, unknown ids, signposts and the three debug
  markers are **not counted**.
- Groups with the same label add up, and a group that is never popped runs to the end of the stream (`:100-105`, pinned by
  `tests/test_capture.py:156-161`, not run).

`diff` then returns:

```text
{"captures": {"a": <name>, "b": <name>},
 "aligned_by": "debug_group" | "whole_capture",
 "totals": {<call>: {"a": n, "b": n, "delta": b - a}, ...},
 "groups": [{"name": <label>, "a": {<call>: n, ...}, "b": {<call>: n, ...}}, ...]}
```

- `totals` has one entry per confirmed call that **either** capture makes, including the ones with delta 0 (`:130`, `:141`).
- `groups` lists only the groups where **some call differs**, with the counts of only the calls that differ (`:132-137`). A
  group that exists in one capture only is listed with `{}` on the other side. They are sorted by the size of the total
  change, largest first, then by name (`:138`); the tool keeps 100 and adds `groups_total` (`traces.py:164-165`).
- `aligned_by` is `"whole_capture"` when neither capture has a debug group; then `groups` is empty and only `totals` says
  anything (`:140`).

The published example (synthetic streams, [proof of 0.26.0](../evidence/v0.26.0.md#capture_diff-compares-two-captures)):

```text
aligned_by: debug_group
totals: drawPrimitives {a: 3, b: 5, delta: 2}, setRenderPipelineState {a: 1, b: 1, delta: 0}
groups: [{name: main, a: {drawPrimitives: 2}, b: {drawPrimitives: 4}}]
```

`shadow` is not listed because it did not change, and it does not matter that it came first in one capture and second in the
other. The test that builds this exact pair is `tests/test_capture.py:146-153` (not run).

### `capture_records`

`tool_capture_records(capture, offset=0, limit=100)` (`traces.py:169-174`) returns one page of the raw records, each as
`{"offset", "size", "id", "signature", "name", "strings"}` with at most the first 3 strings, and `name` is `None` when the id
is not in `CALLS`. It is for looking at what the reader sees when a summary looks wrong. The page is built from **all** the
records and then sliced (`:171-174`), so each page reads the whole stream again, and the default limit here is 100 against 50
for `trace_query` (the schema's own text says "default 50", `registry.py:19`, which is wrong for this tool; limit 8 below).

The same reader is also a script: `python3 -I src/metal_gpu_trace/gputrace_read.py <capture.gputrace> [--records]` prints
the summary as JSON, or with `--records` one line per record (`gputrace_read.py:3`, `:144-155`). It was **not run**.

### What the reader cannot tell you

All of these follow from what the code returns (**confirmed**), not from a test of a real capture:

- **No time.** The output has names, ids, counts and labels. A capture shows what was drawn, not how long it took; GPU time
  comes from a `.trace` and its summary.
- **No resources and no shaders.** Arguments are not decoded: buffers, textures and shader code are not in the output, only
  the printable strings of a record.
- **Only the draws that use the one overload.** A scene drawn with indexed, instanced, indirect or mesh draws can show
  `draw_primitives: 0` and still have draw calls (the ids of those are listed as `probable` or absent).
- **Structure counts are probable.** `command_buffers`, `render_encoders` come from the `probable` ids.
- **`diff` ignores everything unconfirmed.** A change that only touches `probable` or unknown calls shows no difference.
- **Memory is the file's size.** `records` reads the whole `capture` file into memory (`read_bytes`, `gputrace_read.py:50`), and
  `diff` reads two. The size of a real `capture` file was never seen here; **not measured**.

## The GPU family facts

`gpu_family(name)` and the `metal-trace://gpu-families` resources are not about a recording. They return Apple's published
facts for a GPU family or a chip: `traces.family_of` (`:177-185`) accepts a family key (`Apple7`) or a chip name
(`M1 Pro`, `A15`) after lowering the case and removing spaces, and for a chip with the suffix `ultra`, `max` or `pro` also
tries the name without it (`:182`). The data is `src/metal_gpu_trace/data/apple-gpu-families.json`, read once at import
(`config.py:35`), which has four families: `Apple7`, `Apple8`, `Apple9` and `Apple10` (E7). An unknown name is
`unknown family or chip '<name>'; try one of Apple7, ... or a chip such as M1 Pro, M2, M3 Max, A17 Pro`
(`traces.py:192-194`). The facts carry their source URLs (`:195-196`). They answer "what can this GPU do", to read a trace
against; this project restates Apple's pages and does not quote them (README "Credits"). **Not run.**

## When it fails

Every tool of this page runs inside `worker.call`, which turns `ToolError`, `FileNotFoundError`, `ValueError`,
`RuntimeError` and `subprocess.TimeoutExpired` into a result with `isError: true` whose text is the error's message
(`worker.py:165-166`); any other exception becomes `internal error: <ExceptionType>` (`:167-168`). A result over 40 000
characters is refused with `the result has N characters; ask for a smaller page with limit` (`worker.py:162-163`,
`config.py:45`). So a failure never stops the server, and the person gets one sentence.

| What goes wrong | What the reader gets | Line |
|---|---|---|
| The `.trace` is not there (deleted after the summary) | `no recording at <name>: perf_record.sh deletes the .trace once its summary is written, unless KEEP_TRACE=1` | `perf_report.py:52-54` |
| A `trace` name with other characters, as a path outside the readable folders | `<name> is outside the readable directories; add its directory to METAL_TRACE_READ` | `paths.py:20-21` |
| The `.trace` of a name is a link | `<name>.trace cannot be read` | `paths.py:88-89` |
| `xctrace` fails on an export | `xctrace export of <name> failed (exit N): <last line of its error>`; a table cut by the known `SIGTRAP` crash at a row boundary is accepted | `perf_report.py:62-65`, `:60-61` |
| An export takes more than 600 s | the worker reports the `TimeoutExpired`; for `trace_count` the table gets `rows: None` and the others continue | `perf_report.py:49`, `traces.py:144-146`, `worker.py:165` |
| `schema` or a counted table name has an odd character | `schema holds only letters, digits and '-'; trace_tables lists them` / `a table name holds only letters, digits and '-'; ...` | `traces.py:98-99`, `:131-132` |
| The table does not exist in the trace (`trace_query`) | the export of an absent table fails: **probable** `xctrace export ... failed`; `trace_count` says `not in this trace` instead | `traces.py:100-101`, `:133-135` |
| `window_ms` is not a whole number from 1 to 3 600 000 | `window_ms is a whole number of milliseconds from 1 to 3600000` | `traces.py:50` |
| `window_ms` on a table without `start` or `time` | `window_ms needs a table with a time column (start or time); trace_tables lists the tables and trace_query without window_ms shows the columns` | `traces.py:64-66` |
| Some rows have no usable time (windows) | not an error: the rows are counted in `skipped_rows` | `traces.py:69-73`, `:108-109` |
| `perf_export_trace` of an unknown run | `no run <name>; perf_runs lists them` | `paths.py:33-41` |
| `perf_export_trace` of a run without a per-frame table | `<run> has no per-frame file; record it again` | `traces.py:16-17` |
| The per-frame table is damaged (a cell is not a number, a column is missing, a bad gzip) | `<file name> cannot be read; record it again`; nothing is written | `traces.py:26-27` |
| The capture path is outside the readable folders | `<name> is outside the readable directories; add its directory to METAL_TRACE_READ` | `paths.py:20-21` |
| The bundle has no `capture` file (summary, diff) | `FileNotFoundError: <bundle name> has no capture file`, with no folder | `gputrace_read.py:67-68` |
| A record has size under 8 or runs past the end | `ValueError: <bundle name>: record at 0x<off> has size <n>; the stream is not MTSP as expected` | `gputrace_read.py:54-55` |
| `capture_records` on a bundle with no `capture` file, or on a path that is a file | **probable:** the raw `OSError` of `read_bytes` (see finding F1) | `traces.py:173`, `gputrace_read.py:50` |
| A result is too big (a capture with very many debug groups, a page of wide rows) | `the result has N characters; ask for a smaller page with limit` | `worker.py:162-163` |

None of these was **reproduced**: the error texts are read from the code, and the capture ones are pinned by
`tests/test_capture.py:86-97`, `:103-112`, `:115-132` and `:170-178` (not run).

## Known limits

Each item is a limit of today's behaviour, written down, not fixed here.

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | The repository has no real `.trace` or `.gputrace`: no tool of this page was run, and the only published proof of `capture_diff` is on synthetic streams | E3, `docs/evidence/v0.26.0.md` | Not reproduced |
| 2 | The call ids and the layout of a `.gputrace` are the code's claim; the research of 2026-11-15 says no real capture was available, and the code says its ids come from one | `gputrace_read.py:7-8`, `:19` | Contradiction, see F5 |
| 3 | `capture_diff` counts only 17 confirmed ids; a change in indexed, indirect or mesh draws, or in encoders, is invisible to it | `gputrace_read.py:20-45`, `:117` | Confirmed |
| 4 | Every page of `trace_query` and `trace_count` runs `xctrace export` again, and a page is cut from a list of all the rows held in memory | `traces.py:101`, `:111-112` | Confirmed; cost not measured |
| 5 | A table is read from the **first run** of the trace only (`run[@number="1"]`) | `traces.py:100`, `perf_report.py:92` | Confirmed |
| 6 | A `.trace` is readable only while it exists: after a normal recording it is deleted, and `trace_query` then says so | `perf_report.py:52-54` | Confirmed |
| 7 | `perf_export_trace` has one slice per frame on one track, and leaves out frames the summary left out | `traces.py:19-25` | Confirmed |
| 8 | The page size has two defaults: `registry.py:19` says "default 50" for every paged tool, but `capture_records` has `limit=100` | `traces.py:169`, `registry.py:19`, `:177` | Confirmed |
| 9 | A summary of a capture with many debug groups has no `limit`, so it can exceed the 40 000-character cap with no way to ask for less | `traces.py:151-157`, `worker.py:162-163` | Probable (F2) |
| 10 | The unit of a time cell in the pages of `trace_query` (the text Instruments shows) can differ from the nanoseconds the windows use | `traces.py:68`, `:111` | Probable |
| 11 | The sizes of a real `capture` file, and the duration of one export of a real table, were not measured | | Not reproduced |

## New findings in the code (not fixed)

Found while writing this page. Each is something the code does today; none is a decision. They are for the owner to
decide on.

| # | Finding | Where | Status |
|---|---|---|---|
| F1 | `capture_records` opens `<capture>/capture` itself and does not go through `stream_of`, so a bundle with no `capture` file raises the `OSError` of `read_bytes`, whose text holds the **full path**, and a path that is a file raises `NotADirectoryError`, an `OSError` that is not a `FileNotFoundError` and so is reported as `internal error: NotADirectoryError`. The changelog says the errors of `capture_records` no longer include the folder, and the tests cover only `summarize` and `diff` | `traces.py:173`, `gputrace_read.py:50` and `:64-69`, `CHANGELOG.md` (the 0.26.0 `capture_diff` entry) | Probable (code read, not run) |
| F2 | `capture_summary` has no `limit` and `debug_groups` and `signposts` are not capped, so a capture with thousands of labelled groups can produce a result over 40 000 characters, and the error tells the caller to ask for a smaller page with `limit`, which this tool does not have | `gputrace_read.py:90-91`, `traces.py:151-157`, `registry.py:172`, `worker.py:162-163` | Probable |
| F3 | `command_buffers` and `render_encoders` of the summary come from `probable` ids and are not marked as such in the answer | `gputrace_read.py:86-87`, `:38-40` | Confirmed |
| F4 | `capture_summary` cuts nothing and `counts` cuts a label at 200 characters, so the same label can look different in the summary (`debug_groups`) and in the diff (`groups[].name`) | `gputrace_read.py:81`, `:111` | Confirmed |
| F5 | The module says its ids were matched against a capture whose command list Xcode showed on macOS 27.0.1; the 0.26.0 proof and the research of 2026-11-15 say no real capture was available. Which is true decides what "confirmado" means | `gputrace_read.py:7-8`, `:19`; `docs/evidence/v0.26.0.md`; the research note of 2026-11-15 | Contradiction, needs the owner |
| F6 | `trace_query` with `pid` returns every row of a table that has no `process` column, while the tool says "keep only this process's rows" | `traces.py:102-103`, `registry.py:167` | Confirmed |
| F7 | `trace_query` builds the full list of rows before slicing a page, so a table of millions of rows is held in memory on each call | `traces.py:111-112` | Confirmed; size not measured |
| F8 | The docstring of `perf_export_trace` says a frame with parallel encoders "can show shorter than it took"; the length is a sum (`gpu_ms_total`), which for parallel work is longer than the elapsed time, as the [summarizing guide](./summarizing.md#gpu-time-per-frame-is-a-sum-over-channels) says | `traces.py:10-13` | Probable (wording) |
| F9 | `records` ignores fewer than 8 trailing bytes silently, and a file that does not start with `MTSP` is parsed from byte 0 instead of refused | `gputrace_read.py:51-52` | Confirmed |
| F10 | `trace_count` returns the names of every process in the trace (`by_process`), not only the program's | `traces.py:142` | Confirmed |

## Touching it without breaking it

- A new Metal call: add its id to `CALLS` as `"probable"` first. Only change it to `"confirmado"` after matching it against a
  real capture, because `capture_diff` starts counting it the moment it is confirmed, and every older diff changes. Add a
  record with it to a test in `tests/test_capture.py` (the helpers `record` and `capture` build a stream).
- A new tool that reads a capture: go through `paths.allowed` and `stream_of`, never `read_bytes` on a path of your own
  (finding F1), and keep the bundle's name, not its folder, in every message.
- A new tool that reads a `.trace`: take `trace` through `paths.trace_path`, put the table name through the same
  letters-digits-dash check, read through `perf_report.rows` (it deletes the exported file), and keep the `finally` that
  closes it (`traces.py:113-114`).
- A new field of a window: `windows_of` keeps its sums in nanoseconds and converts once at the end (`:85-87`); keep it
  that way so rounding does not add up.
- `traces.py` must not read a `<run>.json`: summaries are `analysis.py`'s. The only summary-like file it touches is the
  per-frame table, through `tables.py`.
- Add the tool to `registry.py` (name, schema, hints) and to `PAGED_TOOLS` (`:9`) if it returns `page()`; the golden file
  `tests/golden/protocol.json` is the contract with clients and has to be updated.

## Evidence: the commands and their real output

Collected on 2026-11-16 on an Apple silicon Mac. All commands only read. The runs folder is `perf-runs/` of the clone (a local,
ignored folder that is not published; it holds two finished runs and their tables). The session that collected them could run
`rg`, `sed`, `awk`, `jq`, `wc` and `find` and could not run Python, `xctrace` or `xxd`: no tool of this page was run, and E5 and E6
are the formulas of the code evaluated by hand.

### E1 Where each tool is registered

```text
$ rg -n '"(perf_export_trace|trace_tables|trace_count|trace_query|capture_summary|capture_diff|capture_records)":' src/metal_gpu_trace/registry.py | cut -c1-90
129:    "perf_export_trace": (traces.tool_perf_export_trace, schema(
159:    "trace_tables": (traces.tool_trace_tables, schema({"trace": TRACE}, ["trace"]), hi
160:    "trace_count": (traces.tool_trace_count, schema(
165:    "trace_query": (traces.tool_trace_query, schema(
172:    "capture_summary": (traces.tool_capture_summary, schema({"capture": CAPTURE}, ["ca
173:    "capture_diff": (traces.tool_capture_diff, schema(
177:    "capture_records": (traces.tool_capture_records, schema({"capture": CAPTURE, **PAG
```

### E2 How many call ids are confirmed and how many probable

```text
$ rg -c '"confirmado"\)' src/metal_gpu_trace/gputrace_read.py
17
$ rg -c '"probable"\)' src/metal_gpu_trace/gputrace_read.py
7
$ rg -n 'probable' src/metal_gpu_trace/gputrace_read.py | cut -c1-110
38:    -16353: ("renderCommandEncoder", "probable"),
39:    -16246: ("endEncoding", "probable"),
40:    -16343: ("commandBuffer", "probable"),
41:    -10240: ("buffer contents", "probable"),
42:    -15416: ("drawMeshThreadgroups", "probable"),
43:    -15415: ("drawMeshThreadgroupsWithIndirectBuffer", "probable"),
44:    -16327: ("dispatchThreadgroups", "probable"),
```

17 + 7 = 24 ids, the number the page uses. The 17 are the three debug markers, `drawPrimitives` and the thirteen state calls.

### E3 The repository has no trace and no capture to read

```text
$ find . -name '*.gputrace' -not -path './node_modules/*' -not -path './.git/*' | wc -l
       0
$ find . \( -name '*.trace' -o -name '*.chrome-trace' \) -not -path './node_modules/*' -not -path './.git/*' | wc -l
       0
```

The tests build their own: `tests/test_capture.py:18-27` writes a `.gputrace` folder with a `capture` file of `MTSP`, 4 zero
bytes and records, and `tests/test_traces.py:11-16` writes an XML table. Neither is a file of the repository.

### E4 The per-frame tables of the two real runs

```text
$ head -2 perf-runs/a2-proof-first_20261115-085621.frames.csv
frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total
6,1267.79,0.0243,1.7417,11.7952,13.5612
$ wc -l perf-runs/a2-proof-first_20261115-085621.frames.csv perf-runs/a2-proof-second_20261115-085735.frames.csv
    2046 perf-runs/a2-proof-first_20261115-085621.frames.csv
     154 perf-runs/a2-proof-second_20261115-085735.frames.csv
    2200 total
```

Header included, the first run has 2045 frames and the second 153: the same numbers as in the
[summarizing guide](./summarizing.md#one-example-first) (the second run stopped presenting at 3.6 s). Both tables are plain
`.csv`, from before the compression of 0.27.0; `tables.find` reads either format.

### E5 `perf_export_trace` on the first row, by hand

```text
$ sed -n 2p perf-runs/a2-proof-first_20261115-085621.frames.csv | awk -F, '{printf "{\"name\":\"GPU frame\",\"ph\":\"X\",\"pid\":1,\"tid\":1,\"ts\":%s,\"dur\":%s,\"args\":{\"frame\":%d,\"compute\":%s,\"fragment\":%s,\"vertex\":%s}}\n",$2*1000,$6*1000,$1,$3,$4,$5}'
{"name":"GPU frame","ph":"X","pid":1,"tid":1,"ts":1267790,"dur":13561.2,"args":{"frame":6,"compute":0.0243,"fragment":1.7417,"vertex":11.7952}}
```

This is `awk` doing the arithmetic of `traces.py:22-25` (`start_ms × 1000`, `gpu_ms_total × 1000`, the `gpu_ms_` prefix cut), not the
tool. Python's own floating-point result may differ in the last digits (for example `13561.2` against `13561.199999999999`);
**not reproduced** with the tool. The same arithmetic is asserted for a two-row table by `tests/test_analysis.py:329-332`
(`ts == 10500.0`, `dur == 600.0`), not run. The sum 0.0243 + 1.7417 + 11.7952 is 13.5612, the `gpu_ms_total` of the row.

### E6 `trace_query` windows, by hand

Three rows with `start` and `duration` in ns: (1 000 000, 2 000 000), (9 000 000, 1 000 000), (12 000 000, 4 000 000), and
`window_ms=10`. A window is `start // 10 000 000`:

```text
1 000 000 // 10 000 000 = 0     9 000 000 // 10 000 000 = 0     12 000 000 // 10 000 000 = 1
window 0: start_ms 0 x 10 = 0,   count 2, duration (2 000 000 + 1 000 000) / 1 000 000 = 3.0 ms
window 1: start_ms 1 x 10 = 10,  count 1, duration 4 000 000 / 1 000 000 = 4.0 ms
```

These are the rows and answer asserted by `tests/test_traces.py:42-48`
(`[{"start_ms": 0, "count": 2, "duration_ms": 3.0}, {"start_ms": 10, "count": 1, "duration_ms": 4.0}]`), not run; the sums
above are the formulas of `traces.py:74-87` evaluated by hand.

### E7 The limits and the GPU family data the code enforces

```text
$ rg -n 'MAX_LIMIT|MAX_TEXT' src/metal_gpu_trace/config.py src/metal_gpu_trace/worker.py src/metal_gpu_trace/registry.py | cut -c1-140
src/metal_gpu_trace/registry.py:19:        "limit": {**I, "description": f"rows per page, default 50, at most {config.MAX_LIMIT}"}}
src/metal_gpu_trace/config.py:43:MAX_LIMIT = 500
src/metal_gpu_trace/config.py:45:MAX_TEXT = 40_000
src/metal_gpu_trace/worker.py:162:        if len(text) > config.MAX_TEXT:
$ jq -r '.families|keys|join(",")' src/metal_gpu_trace/data/apple-gpu-families.json
Apple10,Apple7,Apple8,Apple9
```

### E8 What a real recording held (a measurement of 2026-11-15, not repeated)

The project's research note of 2026-11-15 (internal, not published) records, for one 8-second recording of the `drawstress`
test program at the `deep` tier, made with `xctrace` 27.2 on an Apple M1 Pro under macOS 27.0.1 and 170 MB on disk: **85
tables exported, 59 with rows and 26 empty**, and, for the GPU intervals table, the share of its summed duration by process.
The busiest processes were the program under test and, behind it, other programs of the machine (a browser helper and the window
server): the reason for [the names in `by_process`](#trace-count-which-tables-have-rows). Those numbers were **not re-measured**
for this page; the recording is not in the clone.

### What was not reproduced

- Any `xctrace` call, and so `trace_tables`, `trace_count` and `trace_query` on a real `.trace` (no `.trace` at hand, E3).
- Any tool of `traces.py` or `gputrace_read.py`: Python could not be run by the session that wrote this page.
- A hex dump of a record of a real `.gputrace`, or of a synthetic one (`xxd` could not be run): the layout above is the code's.
- Opening a `.chrome-trace` in Perfetto or `chrome://tracing`.
- The tests named in this page (they were read, not run).
- The cost of one `xctrace export` of a large table, and the size of a real `capture` file.

## See also

- [Summarizing and analyzing](./summarizing.md): how `perf_report.py` reads the same `.trace` for the summary, and the `unpresented`
  rule that also shapes the per-frame table.
- [Data and its lifecycle](./data-and-lifecycle.md): when a `.trace` and a `.chrome-trace` exist and what deletes them.
- [Recording](./recording.md): how the `.trace` is made and why it is deleted.
- [How it works](./how-it-works.md): which layer calls which.
- [Proof of 0.26.0](../evidence/v0.26.0.md#capture_diff-compares-two-captures): the published example of `capture_diff`, on synthetic
  streams.
