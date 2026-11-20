# `trace_tables` and `trace_count`

**Reader:** people who explore a recording's tables (its kept `.trace`, or its tables file), or who change these two tools. Reviewed 2026-11-16.

> **Since the tables file:** when the `.trace` is gone, both tools read `<run>.tables.sqlite`, which holds the tables the summary
> read (`trace_count` says "not in this trace's tables file" for the others). See [the tables file](tables-file.md).

> **In short:** a recording holds many tables, like the sheets of a spreadsheet, and some are empty. `trace_tables` lists
> their names; `trace_count` says which have rows, so nobody reads a page of nothing. Then read one with [`trace_query`](./trace-query.md).

## `trace_tables`: what is in this trace

`tool_trace_tables` (`traces.py:33-36`) asks for the table of contents, collects every `table` with a `schema` attribute and
returns `{"tables": [<sorted names>]}`: no row counts, no sizes. The cheapest of the three; the other two need a name from it.

## `trace_count`: which tables have rows

A table can exist and be empty: the recording of E8 has 26, among them the shader *spill* table (empty unless a program spills
registers). `tool_trace_count` (`traces.py:124-148`) exports each table named and counts its rows, in all and per process
(shape asserted by `tests/test_report.py:207-208`, synthetic names; not run):

```text
{"trace": "<name>", "tables": {"<schema>": {"rows": 3, "by_process": {"<name> (42)": 2, "<name> (7)": 1}}, ...}}
```

| Rule | Behaviour | Line |
|---|---|---|
| No `tables` argument | counts the ten of `COUNTED_TABLES`: GPU intervals, encoder list, command-buffer completion, the shader compiler's spill and activity tables, the shader profiler's list and samples, resource allocations, GPU counter intervals, `time-profile` | `traces.py:117-121` |
| A name not in the table of contents | not an error: `{"rows": None, "note": "not in this trace"}`. **`rows: 0` and "not there" are different answers** | `:133-135` |
| A name with other characters than letters, digits, `-` | `a table name holds only letters, digits and '-'; trace_tables lists them`; the check protects the xpath, built by inserting the name into a string | `:131-132`, `:136` |
| `by_process` | the ten processes with most rows, named as the table names them (`name (pid)`), or by pid when the cell has no text | `:142`, `:147` |
| One export fails | the others go on: a `RuntimeError` or timeout is caught and that table gets `{"rows": None, "note": <the error text>}` | `:144-146` |

The tool's own note: "a table with 0 rows needs another instrument or Xcode, not a bigger page" (`:125-126`).

**Privacy.** `by_process` names **whatever ran on the machine** while recording, not only the program under test (a browser
helper is among the busiest in the GPU table, E8). They travel to the client in the result; no summary keeps a name
(`perf_report.py:584-590`), but whoever pastes a `trace_count` result in a shared place carries them (F10, [limits](./limits.md)).

Next: [`trace_query`](./trace-query.md). Back to the [index](./index.md).
