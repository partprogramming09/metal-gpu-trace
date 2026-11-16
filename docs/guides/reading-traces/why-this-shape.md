# Why it is shaped this way

**Reader:** people who change `traces.py` or `gputrace_read.py` and want to know why it is built as it is. Reviewed 2026-11-16.

Español: [Por qué tiene esta forma](../../es/guides/leer-trazas/por-que-asi.md)

> **In short:** each choice below answers one worry: do not fill the disk, do not need Xcode, do not report a change that
> may not exist, do not let a client open any file on the machine. Each row also names the simpler option that was left out
> and what would have gone wrong with it.

| Choice | Why | Alternatives left out |
|---|---|---|
| A `.trace` is read **one table per call**, through `xctrace export` | A recording holds 85 tables in the one measured (E8); each export keeps a temporary store that can reach gigabytes on a big trace (`perf_report.py:39`), so asking for the one table wanted keeps disk and time bounded | Exporting the whole trace once and answering from it: gigabytes of XML on disk for a question about one table |
| `trace_query` caches nothing: every page runs the export again | It builds its rows from a fresh export on each call and deletes the file when it finishes (`traces.py:101`, `:113-114`); the code has no cache. **Speculation:** the reason is the disk cost of keeping an XML file of the table | Keeping the exported XML between pages: a stale file could be read after the trace is gone, and it would hold the table twice |
| `window_ms` sums a table by time window | A table of hundreds of thousands of rows cannot be read row by row; the docstring calls it "a summary of a table too long to read row by row" (`traces.py:93-96`) | Returning more rows per page: a page is capped at 500 rows and 40 000 characters ([limits](./limits.md)) |
| `perf_export_trace` reads the per-frame table, not the `.trace` | The `.trace` is deleted by default ([ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md), `perf_record.sh:162-163`) and the per-frame table stays, so the export works on a run whose trace is long gone (`traces.py:15`) | Reading the `.trace`: only works with `KEEP_TRACE=1` and needs `xctrace` again |
| The `.gputrace` reader is written by hand with `struct` | No Xcode is needed on the machine that reads, and the server is standard library only (`CLAUDE.md`, [ADR-0003](../../adr/0003-python-3-9-floor.md)); `struct` and `re` are enough for a stream of records (`gputrace_read.py:9-14`) | Calling Xcode or a private framework: ties the tool to a machine with Xcode, and the format of the call list is not public |
| Every Metal call carries a **certainty**; `capture_diff` counts only the confirmed ones | The call ids were worked out by hand: 17 of the 24 named ids are `"confirmado"`, 7 are `"probable"` (E2). A diff that counted a guess would report a change that may not exist (`gputrace_read.py:117`) | Counting every id: a wrong name would show up as a change |
| `capture_diff` aligns by **debug group label**, not by position | Two captures of the same scene often draw in a different order; a group is matched by its label, so a reordered group is not a difference (`gputrace_read.py:124-128`; E1 of the 0.26.0 proof) | Comparing record by record: one added call shifts everything after it |
| Paths are checked before anything opens | A `.gputrace` path must lie inside `METAL_TRACE_OUT` or `METAL_TRACE_READ` (`paths.py:17-22`); a `.trace` name resolves inside the runs folder and a link is refused (`paths.py:83-91`) | Reading any path: a client could make the server open a file anywhere the user can |

Back to the [index](./index.md).
