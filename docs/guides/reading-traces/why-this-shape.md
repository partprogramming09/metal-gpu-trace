# Why it is shaped this way

**Reader:** people who change `traces.py` or `gputrace_read.py` and want to know why it is built as it is. Reviewed 2026-11-16.

> **In short:** each choice answers one worry: do not fill the disk, do not need Xcode, do not report a change that may not
> exist, do not let a client open any file on the machine. Each row names the simpler option left out and what would go wrong.

| Choice | Why | Alternatives left out |
|---|---|---|
| A `.trace` is read **one table per call** through `xctrace export`; `trace_query` caches nothing, every page re-exports | 85 tables in the one measured (E8); an export keeps a temporary store that can reach gigabytes (`perf_report.py::EXPORT_WORKERS`), so one table bounds disk and time. Rows come from a fresh export each call, file deleted at the end (`traces.py::windows_of`, `traces.py::tool_trace_query`). **Speculation:** the reason is the disk cost of keeping the XML | Exporting the whole trace once: gigabytes of XML for one table. Keeping the XML between pages: a stale file could be read after the trace is gone, and it holds the table twice |
| `window_ms` sums a table by time window | A table of hundreds of thousands of rows cannot be read row by row; the docstring calls it "a summary of a table too long to read row by row" (`traces.py::check_window`) | More rows per page: a page is capped at 500 rows and 40 000 characters ([limits](./limits.md)) |
| `perf_export_trace` reads the per-frame table, not the `.trace` | The `.trace` is deleted by default ([ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md), `perf_record.sh:162-163`); the table stays, so it works on a run whose trace is long gone (`traces.py::tool_perf_export_trace`) | Reading the `.trace`: needs `KEEP_TRACE=1` and `xctrace` again |
| The `.gputrace` reader is hand-written with `struct` | No Xcode needed where it reads, and the server is standard library only (`CLAUDE.md`, [ADR-0003](../../adr/0003-python-3-9-floor.md)); `struct` and `re` suffice (`gputrace_read.py:9-14`) | Calling Xcode or a private framework: ties it to a machine with Xcode, and the call-list format is not public |
| Every Metal call carries a **certainty**; `capture_diff` counts only the confirmed and **aligns by debug group label**, not position | Ids were worked out by hand: 17 of 24 are `"confirmado"`, 7 `"probable"` (E2); counting a guess could report a change that does not exist (`gputrace_read.py::counts`). Two captures of one scene often draw in another order, so a reordered group is no difference (`gputrace_read.py::diff`; E1 of the 0.26.0 proof) | Counting every id: a wrong name shows as a change. Comparing record by record: one added call shifts everything after it |
| Paths are checked before anything opens | A `.gputrace` path must lie inside `METAL_TRACE_OUT` or `METAL_TRACE_READ` (`paths.py::allowed`); a `.trace` name resolves inside the runs folder and a link is refused (`paths.py::trace_path`) | Reading any path: a client could make the server open a file anywhere the user can |

Back to the [index](./index.md).
