# Known limits and new findings

**Reader:** the owner and anyone deciding what to fix in `traces.py` or `gputrace_read.py`. Reviewed 2026-11-16.

Español: [Límites conocidos y hallazgos](../../es/guides/leer-trazas/limites.md)

> **In short:** this page lists what these tools cannot do today (limits) and what looked wrong while the guide was
> written (findings). Nothing here was fixed: each item is something the code does now, written down so the owner can
> decide. The biggest one: no real capture was ever read, so the capture format is the code's own claim.

## Known limits

Each item is a limit of today's behaviour, written down, not fixed here.

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | The repository has no real `.trace` or `.gputrace`: no tool of this guide was run, and the only published proof of `capture_diff` is on synthetic streams | E3, `docs/evidence/v0.26.0.md` | Not reproduced |
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

Found while writing this guide. Each is something the code does today; none is a decision.

| # | Finding | Where | Status |
|---|---|---|---|
| F1 | `capture_records` opens `<capture>/capture` itself and does not go through `stream_of`, so a bundle with no `capture` file raises the `OSError` of `read_bytes`, whose text holds the **full path**, and a path that is a file raises `NotADirectoryError`, an `OSError` that is not a `FileNotFoundError` and so is reported as `internal error: NotADirectoryError`. The changelog says the errors of `capture_records` no longer include the folder, and the tests cover only `summarize` and `diff` | `traces.py:173`, `gputrace_read.py:50` and `:64-69`, `CHANGELOG.md` (the 0.26.0 `capture_diff` entry) | Probable (code read, not run) |
| F2 | `capture_summary` has no `limit` and `debug_groups` and `signposts` are not capped, so a capture with thousands of labelled groups can produce a result over 40 000 characters, and the error tells the caller to ask for a smaller page with `limit`, which this tool does not have | `gputrace_read.py:90-91`, `traces.py:151-157`, `registry.py:172`, `worker.py:162-163` | Probable |
| F3 | `command_buffers` and `render_encoders` of the summary come from `probable` ids and are not marked as such in the answer | `gputrace_read.py:86-87`, `:38-40` | Confirmed |
| F4 | `capture_summary` cuts nothing and `counts` cuts a label at 200 characters, so the same label can look different in the summary (`debug_groups`) and in the diff (`groups[].name`) | `gputrace_read.py:81`, `:111` | Confirmed |
| F5 | The module says its ids were matched against a capture whose command list Xcode showed on macOS 27.0.1; the 0.26.0 proof and the research of 2026-11-15 say no real capture was available. Which is true decides what "confirmado" means | `gputrace_read.py:7-8`, `:19`; `docs/evidence/v0.26.0.md`; the research note of 2026-11-15 | Contradiction, needs the owner |
| F6 | `trace_query` with `pid` returns every row of a table that has no `process` column, while the tool says "keep only this process's rows" | `traces.py:102-103`, `registry.py:167` | Confirmed |
| F7 | `trace_query` builds the full list of rows before slicing a page, so a table of millions of rows is held in memory on each call | `traces.py:111-112` | Confirmed; size not measured |
| F8 | The docstring of `perf_export_trace` says a frame with parallel encoders "can show shorter than it took"; the length is a sum (`gpu_ms_total`), which for parallel work is longer than the elapsed time, as the [summarizing guide](../summarizing/how-numbers-are-computed.md#gpu-time-per-frame-is-a-sum-over-channels) says | `traces.py:10-13` | Probable (wording) |
| F9 | `records` ignores fewer than 8 trailing bytes silently, and a file that does not start with `MTSP` is parsed from byte 0 instead of refused | `gputrace_read.py:51-52` | Confirmed |
| F10 | `trace_count` returns the names of every process in the trace (`by_process`), not only the program's | `traces.py:142` | Confirmed |

Back to the [index](./index.md).
