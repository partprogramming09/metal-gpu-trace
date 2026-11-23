# `trace_query`: rows, pages and windows

**Reader:** people who read the rows of a table in a kept `.trace`, or who change `traces.py::check_window`. Reviewed 2026-11-16.

> **In short:** `trace_query` hands you one page of one table, 50 rows by default. For a table too long to read, ask for time
> windows instead: "how many rows and how much time in each 10 ms". Three rows at 1 ms, 9 ms and 12 ms give two windows, with
> 2 rows and 1. Every page runs the export again, so big tables are slow.

`tool_trace_query(trace, schema, offset=0, limit=50, pid=None, window_ms=None)` (`traces.py::check_window`), in order:

| # | Step | Detail | Line |
|---|---|---|---|
| 1 | `check_window` validates `window_ms` | `None` stays `None`; a whole float such as `10.0` counts as `10`; a bool, a fraction, `0`, a negative or over `3 600 000` is `window_ms is a whole number of milliseconds from 1 to 3600000` | `:42-51` |
| 2 | Schema name | only letters, digits and `-` | `:98-99` |
| 3 | Export and read | exported with the xpath of `:100`, read by `perf_report.rows` | `:100-101` |
| 4 | `pid` filter | `pid is None or "process" not in row or perf_report.pid_of(row["process"]) == int(pid)`: a table **without** a `process` column is returned whole whatever `pid` says, although the tool says "keep only this process's rows" (F6) | `:102-103` |
| 5 | Rows (no `window_ms`) | each row becomes `{column: value}`, the value being the cell's `fmt` text if any, else its text: as Instruments shows it. **Probable:** a time column may read `1.5 ms` where the raw text is nanoseconds, which is why windows read `.text`, not `fmt` (`:68`, `:79`). Then `paths.page` cuts a page | `:111-112` |
| 6 | Cleanup | the file `rows` read is deleted in a `finally`, also if the windows code raised (`tests/test_traces.py:118-124`, not run) | `:113-114` |

> **Since the tables file:** the rows can also come from `<run>.tables.sqlite` when the `.trace` is gone, and `where`, `columns`,
> `order_by`, `group_by` and `aggregates` filter them: see [the tables file](tables-file.md). The line numbers below describe the
> export path.

## Paging

`paths.page(items, offset, limit)` (`paths.py:94-99`) clamps `offset` to 0 or more and `limit` to 1..500 (`config.MAX_LIMIT`,
`config.py:43`; schema "default 50, at most 500", `registry.py:19`) and returns:

```text
{"total": <all rows>, "offset": <n>, "rows": [...], "next_offset": <n + len(rows), or null at the end>}
```

`next_offset: null` tells a client it reached the end. Everything comes from a **list of all the rows** (`:111-112` builds it,
`:94-99` slices it) and each call exports again: a million rows in pages of 500 runs the export 2000 times. No cache
(**confirmed**); the cost of one export of a large table was **not measured**. If an export takes over 600 s the call ends with
`subprocess.TimeoutExpired`, which the worker turns into an error (`worker.py::_merge`; timeout at `perf_report.py:49`).

## Windows

With `window_ms`, `windows_of(selected, window_ms)` (`traces.py:54-89`) replaces the rows:

| Rule | Behaviour | Line |
|---|---|---|
| The **first row decides the shape** | its time column is `start` if present, else `time` (`TIME_COLUMNS`); there is a duration column when the first row has `duration` | `:39`, `:62`, `:63` |
| No time column | `window_ms needs a table with a time column (start or time); trace_tables lists the tables and trace_query without window_ms shows the columns` | `:64-66` |
| Which window | a row's time is `int(cell.text)` in nanoseconds; window = `ns // (window_ms × 1 000 000)` | `:68`, `:74` |
| Bad time (not a number, negative, missing) | counted in `skipped_rows`, which the answer carries only when not 0 | `:69-73`, `:108-109` |
| A window | `{"start_ms": index × window_ms, "count": N}` plus `"duration_ms"` when the table has a duration: the **sum** of its rows' durations in ms, rounded to 3 decimals; a row with an unreadable duration counts but adds nothing | `:75-87`, `:77-81` |
| Which are listed | only windows holding a row, in time order, paged like rows; the answer also carries `window_ms` | `:83-84`, `:107` |

Durations are summed, so parallel work in one window can exceed the window: the same caveat as the
[per-frame GPU sum](../summarizing/how-numbers-are-computed.md#gpu-time-per-frame-is-a-sum-over-channels).

The twelve tests of `tests/test_traces.py` pin all of this (windows by 10 ms, a `time` column without duration, rejection of
zero, negatives and non-numbers, no time column, an empty table, rows without usable time, a whole float, paging, the pid
filter, file deletion); **not run**. Hand evaluation of the example: E6 in [Evidence](./evidence.md).

Back to the [index](./index.md).
