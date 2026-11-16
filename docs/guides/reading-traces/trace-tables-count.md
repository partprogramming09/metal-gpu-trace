# `trace_tables` and `trace_count`

**Reader:** people who explore a kept `.trace`, or who change these two tools. Reviewed 2026-11-16.

Español: [`trace_tables` y `trace_count`](../../es/guides/leer-trazas/tablas-y-conteo.md)

> **In short:** a recording holds many tables, like the sheets of a spreadsheet, and some are empty. `trace_tables` lists
> their names. `trace_count` says which ones actually have rows, so nobody reads a page of nothing. Start with the first,
> then the second, then read a table with [`trace_query`](./trace-query.md).

## `trace_tables`: what is in this trace

`tool_trace_tables` (`traces.py:33-36`) asks for the table of contents, collects every `table` element that has a `schema`
attribute and returns `{"tables": [<sorted names>]}`. Nothing else: no row counts, no sizes. It is the cheapest of the three
calls; the next two need a name from it.

## `trace_count`: which tables have rows

A table can exist and be empty. The recording of E8 has 26 empty ones, among them the shader *spill* table (empty unless a
program spills registers). `tool_trace_count` (`traces.py:124-148`) exports each table named and counts its rows, in all and
per process:

```text
{"trace": "<name>", "tables": {"<schema>": {"rows": 3, "by_process": {"<name> (42)": 2, "<name> (7)": 1}}, ...}}
```

(the shape is what `tests/test_report.py:207-208` asserts, with synthetic process names; not run).

| Rule | Behaviour | Line |
|---|---|---|
| No `tables` argument | counts the ten of `COUNTED_TABLES`: GPU intervals, encoder list, command-buffer completion, the shader compiler's spill and activity tables, the shader profiler's list and samples, resource allocations, GPU counter intervals, `time-profile` | `traces.py:117-121` |
| A name not in the table of contents | not an error: `{"rows": None, "note": "not in this trace"}`. **`rows: 0` and "not there" are different answers** | `:133-135` |
| A name with other characters than letters, digits, `-` | `a table name holds only letters, digits and '-'; trace_tables lists them`; the check protects the xpath, built by inserting the name into a string | `:131-132`, `:136` |
| `by_process` | the ten processes with the most rows, named as the table names them (`name (pid)`), or by the pid when the cell has no text | `:142`, `:147` |
| One export fails | the others go on: a `RuntimeError` or a timeout is caught and that table gets `{"rows": None, "note": <the error text>}` | `:144-146` |

The tool's own note says it plainly: "a table with 0 rows needs another instrument or Xcode, not a bigger page"
(`:125-126`).

**Privacy.** The names in `by_process` are those of **whatever ran on the machine** while it was recorded, not only the
program under test (the same measurement shows a browser helper among the busiest processes of the GPU table, E8). They
travel to the client in the result. They are not written to a summary (`perf_report.py:584-590` keeps no name there), but
anyone who pastes a `trace_count` result into a shared place carries them along (finding F10, [limits](./limits.md)).

Next: [`trace_query`](./trace-query.md). Back to the [index](./index.md).
