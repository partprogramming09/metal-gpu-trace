# When it fails

**Reader:** people who see an error from one of these tools and want to know what it means, or who change an error text. Reviewed 2026-11-16.

Español: [Cuando falla](../../es/guides/leer-trazas/cuando-falla.md)

> **In short:** when something goes wrong the server does not stop: you get one sentence saying what happened and, most of the
> time, what to do. The most common one is "no recording at ...": the recording was deleted after its summary was written,
> and recording again with `KEEP_TRACE=1` keeps it.

Every tool of this guide runs inside `worker.call`, which turns `ToolError`, `FileNotFoundError`, `ValueError`,
`RuntimeError` and `subprocess.TimeoutExpired` into a result with `isError: true` whose text is the error's message
(`worker.py:165-166`); any other exception becomes `internal error: <ExceptionType>` (`:167-168`). A result over 40 000
characters is refused with `the result has N characters; ask for a smaller page with limit` (`worker.py:162-163`,
`config.py:45`).

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
| `capture_records` on a bundle with no `capture` file, or on a path that is a file | **probable:** the raw `OSError` of `read_bytes` (finding F1) | `traces.py:173`, `gputrace_read.py:50` |
| A result is too big (a capture with very many debug groups, a page of wide rows) | `the result has N characters; ask for a smaller page with limit` | `worker.py:162-163` |

None of these was **reproduced**: the error texts are read from the code, and the capture ones are pinned by
`tests/test_capture.py:86-97`, `:103-112`, `:115-132` and `:170-178` (not run).

Back to the [index](./index.md).
