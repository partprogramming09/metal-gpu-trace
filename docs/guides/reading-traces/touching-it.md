# Touching it without breaking it

**Reader:** people who add or change a tool in `traces.py` or `gputrace_read.py`. Reviewed 2026-11-16.

> **In short:** one rule per kind of change. The idea behind most: never trust a name or a path from a client, never count a
> guess as a fact, and keep tests and the client contract in step with the code.

| If you add or change... | Do this | Because |
|---|---|---|
| A new Metal call | Add its id to `CALLS` as `"probable"`; make it `"confirmado"` only after matching a real capture; add a record with it to a test in `tests/test_capture.py` (helpers `record` and `capture` build a stream) | `capture_diff` counts it the moment it is confirmed, and every older diff changes |
| A tool that reads a capture | Go through `paths.allowed` and `stream_of`, never `read_bytes` on your own path; keep the bundle's name, not its folder, in every message | F1 |
| A tool that reads a `.trace` | Take `trace` through `paths.trace_path`; put the table name through the same letters-digits-dash check; read through `perf_report.rows` (it deletes the exported file); keep the `finally` that closes it (`traces.py:113-114`) | the name goes into an xpath, and the exported file can be gigabytes |
| A new field of a window | `windows_of` keeps sums in nanoseconds and converts once at the end (`:85-87`) | rounding does not add up |
| Anything in `traces.py` | It must not read a `<run>.json` (summaries are `analysis.py`'s); the only summary-like file it touches is the per-frame table, through `tables.py` | one owner per file |
| Any new tool | Add it to `registry.py` (name, schema, hints) and to `PAGED_TOOLS` (`:9`) if it returns `page()`; update `tests/golden/protocol.json` | it is the contract with clients |

Back to the [index](./index.md).
