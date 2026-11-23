# When it fails

**Reader:** people who see an error from one of these tools and want to know what it means, or who change an error text. Reviewed 2026-11-16.

> **In short:** when something goes wrong the server does not stop: you get one sentence saying what happened and, mostly, what
> to do. The most common is "no recording at ...": the recording was deleted after its summary was written; recording again
> with `KEEP_TRACE=1` keeps it.

Every tool here runs inside `worker.call`, which turns `ToolError`, `FileNotFoundError`, `ValueError`, `RuntimeError` and
`subprocess.TimeoutExpired` into an `isError: true` result whose text is the message (`worker.py::_merge`); any other exception
becomes `internal error: <ExceptionType>` (`worker.py::call`). A result over 40 000 characters (a capture with very many debug groups,
a page of wide rows) is refused with `the result has N characters; ask for a smaller page with limit` (`worker.py::_merge`, `config.py::MAX_TEXT`).

| What goes wrong | What the reader gets | Line |
|---|---|---|
| The `.trace` is not there (deleted after the summary) | `trace_tables`, `trace_count` and `trace_query` read the run's `<name>.tables.sqlite` instead; with neither file: `no recording at <name>.trace and no <name>.tables.sqlite: ...` | `traces.py` (`source_of`, `missing`) |
| A `trace` or capture path outside the readable folders | `<name> is outside the readable directories; add its directory to METAL_TRACE_READ` | `paths.py::allowed` |
| The `.trace` of a name is a link | `<name>.trace cannot be read` | `paths.py::trace_path` |
| `xctrace` fails on an export | `xctrace export of <name> failed (exit N): <last line of its error>`; a table cut by the known `SIGTRAP` crash at a row boundary is accepted | `perf_report.py::export` |
| An export takes more than 600 s | the worker reports the `TimeoutExpired`; in `trace_count` the table gets `rows: None` and the others continue | `perf_report.py::export`, `traces.py::tool_trace_query`, `worker.py::_merge` |
| `schema` or a counted table name has an odd character | `schema holds only letters, digits and '-'; trace_tables lists them` / `a table name holds only letters, digits and '-'; ...` | `traces.py::tool_trace_query`, `traces.py::tool_trace_count` |
| The table is absent from the trace (`trace_query`) | the export fails: **probable** `xctrace export ... failed`; `trace_count` says `not in this trace` instead | `traces.py::windows_of`, `traces.py::tool_trace_count` |
| `window_ms` is not a whole number from 1 to 3 600 000 / the table has no `start` or `time` / some rows have no usable time | `window_ms is a whole number of milliseconds from 1 to 3600000` / `window_ms needs a table with a time column (start or time); trace_tables lists the tables and trace_query without window_ms shows the columns` / not an error: rows counted in `skipped_rows` | `traces.py::missing`, `traces.py::windows_of`, `traces.py::tool_trace_query` |
| `perf_export_trace`: unknown run / no per-frame table / damaged table (a cell not a number, a missing column, a bad gzip) | `no run <name>; perf_runs lists them` / `<run> has no per-frame file; record it again` / `<file name> cannot be read; record it again`, nothing written | `paths.py::run_path`, `traces.py::tool_perf_export_trace` |
| The bundle has no `capture` file (summary, diff) / a record has size under 8 or runs past the end | `FileNotFoundError: <bundle name> has no capture file`, no folder / `ValueError: <bundle name>: record at 0x<off> has size <n>; the stream is not MTSP as expected` | `gputrace_read.py::stream_of`, `gputrace_read.py::records` |
| `capture_records` on a bundle with no `capture` file, or on a path that is a file | **probable:** the raw `OSError` of `read_bytes` (F1) | `traces.py::tool_capture_records`, `gputrace_read.py::records` |

None was **reproduced**: texts are read from the code, and the capture ones are pinned by `tests/test_capture.py::test_malformed_record_raises_valueerror`,
`tests/test_capture.py::test_a_capture_without_its_stream_is_an_error`, `tests/test_capture.py::test_capture_diff_tool_rejects_a_path_outside_the_readable_directories` and `tests/test_capture.py::test_summarize_and_diff_errors_name_no_folder_when_the_stream_is_missing` (not run).

Back to the [index](./index.md).
