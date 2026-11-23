# Known limits and new findings

**Reader:** the owner and anyone deciding what to fix in `traces.py` or `gputrace_read.py`. Reviewed 2026-11-16.

> **In short:** what these tools cannot do today (limits) and what looked wrong while the guide was written (findings). Nothing
> was fixed: each item is what the code does now, written down for the owner to decide. The biggest: no real capture was ever
> read, so the capture format is the code's own claim.

## Known limits

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | The repository has no real `.trace` or `.gputrace`: no tool of this guide was run, and the only published proof of `capture_diff` is on synthetic streams | E3, `docs/evidence/v0.26.0.md` | Not reproduced |
| 2 | The call ids and layout of a `.gputrace` are the code's claim; the research of 2026-11-15 says no real capture was available, the code says its ids come from one | `gputrace_read.py:7-8`, `gputrace_read.py::CALLS` | Contradiction, see F5 |
| 3 | `capture_diff` counts only 17 confirmed ids; a change in indexed, indirect or mesh draws, or in encoders, is invisible to it | `gputrace_read.py::CALLS`, `gputrace_read.py::counts` | Confirmed |
| 4 | Every page of `trace_query` and `trace_count` runs `xctrace export` again, and a page is cut from a list of all rows in memory | `traces.py::windows_of`, `traces.py::tool_trace_query` | Confirmed; cost not measured |
| 5 | A table is read from the **first run** of the trace only (`run[@number="1"]`) | `traces.py::windows_of`, `perf_report.py::table_xpath` | Confirmed |
| 6 | A `.trace` is readable only while it exists: after a normal recording it is deleted, and `trace_query` says so | `perf_report.py::export` | Confirmed |
| 7 | `perf_export_trace` has one slice per frame on one track, and leaves out frames the summary left out | `traces.py::tool_perf_export_trace` | Confirmed |
| 8 | Two page-size defaults: `registry.py::PAGE` says "default 50" for every paged tool, but `capture_records` has `limit=100` | `traces.py::tool_trace_query`, `registry.py::PAGE`, `registry.py::TOOLS` | Confirmed |
| 9 | A summary of a capture with many debug groups has no `limit`, so it can exceed the 40 000-character cap with no way to ask for less | `traces.py::tool_trace_query`, `worker.py::_merge` | Probable (F2) |
| 10 | The unit of a time cell in `trace_query` pages (Instruments' text) can differ from the nanoseconds the windows use | `traces.py::tables_file`, `traces.py::tool_trace_query` | Probable |
| 11 | The size of a real `capture` file and the duration of one export of a real table were not measured | | Not reproduced |

## New findings in the code (not fixed)

Each is something the code does today; none is a decision.

| # | Finding | Where | Status |
|---|---|---|---|
| F1 | `capture_records` opens `<capture>/capture` itself, not through `stream_of`: a bundle with no `capture` file raises the `OSError` of `read_bytes`, whose text holds the **full path**, and a path that is a file raises `NotADirectoryError`, an `OSError` that is not a `FileNotFoundError`, reported as `internal error: NotADirectoryError`. The changelog says `capture_records` errors no longer include the folder; tests cover only `summarize` and `diff` | `traces.py::tool_capture_records`, `gputrace_read.py::records`, `gputrace_read.py::stream_of`, `CHANGELOG.md` (0.26.0 `capture_diff` entry) | Probable (read, not run) |
| F2 | `capture_summary` has no `limit` and `debug_groups` and `signposts` are uncapped: thousands of labelled groups can exceed 40 000 characters, and the error tells the caller to use `limit`, which this tool lacks | `gputrace_read.py::summarize`, `traces.py::tool_trace_query`, `registry.py::TOOLS`, `worker.py::_merge` | Probable |
| F3 | `command_buffers` and `render_encoders` of the summary come from `probable` ids and are not marked as such | `gputrace_read.py::summarize`, `gputrace_read.py::CALLS` | Confirmed |
| F4 | `capture_summary` cuts nothing and `counts` cuts a label at 200 characters, so a label can differ between `debug_groups` and `groups[].name` | `gputrace_read.py::summarize`, `gputrace_read.py::counts` | Confirmed |
| F5 | The module says its ids were matched against a capture whose command list Xcode showed on macOS 27.0.1; the 0.26.0 proof and the research note of 2026-11-15 say no real capture was available. Which is true decides what "confirmado" means | `gputrace_read.py:7-8`, `gputrace_read.py::CALLS`; `docs/evidence/v0.26.0.md`; the research note | Contradiction, needs the owner |
| F6 | `trace_query` with `pid` returns every row of a table with no `process` column, while the tool says "keep only this process's rows" | `traces.py::windows_of`, `registry.py::TOOLS` | Confirmed |
| F7 | `trace_query` builds the full list of rows before slicing a page: a table of millions of rows is held in memory on each call | `traces.py::windows_of` | Confirmed; size not measured |
| F8 | The docstring of `perf_export_trace` says a frame with parallel encoders "can show shorter than it took"; the length is a sum (`gpu_ms_total`), longer for parallel work, as the [summarizing guide](../summarizing/how-numbers-are-computed.md#gpu-time-per-frame-is-a-sum-over-channels) says | `traces.py::tool_perf_export_trace` | Probable (wording) |
| F9 | `records` silently ignores fewer than 8 trailing bytes, and a file not starting with `MTSP` is parsed from byte 0 instead of refused | `gputrace_read.py::records` | Confirmed |
| F10 | `trace_count` returns the names of every process in the trace (`by_process`), not only the program's | `traces.py::tool_trace_query` | Confirmed |

Back to the [index](./index.md).
