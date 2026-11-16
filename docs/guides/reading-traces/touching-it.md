# Touching it without breaking it

**Reader:** people who add or change a tool in `traces.py` or `gputrace_read.py`. Reviewed 2026-11-16.

Español: [Tocarlo sin romperlo](../../es/guides/leer-trazas/tocarlo.md)

> **In short:** a short list of rules, one per kind of change. The idea behind most of them: never trust a name or a path from
> a client, never count a guess as a fact, and keep the tests and the contract with clients in step with the code.

| If you add or change... | Do this | Because |
|---|---|---|
| A new Metal call | Add its id to `CALLS` as `"probable"` first. Change it to `"confirmado"` only after matching it against a real capture. Add a record with it to a test in `tests/test_capture.py` (the helpers `record` and `capture` build a stream) | `capture_diff` starts counting it the moment it is confirmed, and every older diff changes |
| A new tool that reads a capture | Go through `paths.allowed` and `stream_of`, never `read_bytes` on a path of your own; keep the bundle's name, not its folder, in every message | finding F1 |
| A new tool that reads a `.trace` | Take `trace` through `paths.trace_path`; put the table name through the same letters-digits-dash check; read through `perf_report.rows` (it deletes the exported file); keep the `finally` that closes it (`traces.py:113-114`) | the name goes into an xpath, and the exported file can be gigabytes |
| A new field of a window | `windows_of` keeps its sums in nanoseconds and converts once at the end (`:85-87`); keep it that way | rounding does not add up |
| Anything in `traces.py` | It must not read a `<run>.json`: summaries are `analysis.py`'s. The only summary-like file it touches is the per-frame table, through `tables.py` | one owner per file |
| A new tool, any kind | Add it to `registry.py` (name, schema, hints) and to `PAGED_TOOLS` (`:9`) if it returns `page()`; update the golden file `tests/golden/protocol.json` | it is the contract with clients |

Back to the [index](./index.md).
