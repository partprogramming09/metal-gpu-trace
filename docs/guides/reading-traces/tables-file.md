# The tables file: question a recording after its `.trace` is gone

**Reader:** people who call `trace_tables`, `trace_count` or `trace_query`, or who change `tabledb.py`. Reviewed 2026-11-16.

Español: [El archivo de tablas](../../es/guides/leer-trazas/archivo-de-tablas.md)

> **In short:** every recording leaves `<run>.tables.sqlite` beside its summary. It holds the tables the summary read, so
> the three table tools keep answering after the `.trace` (hundreds of MB) is deleted, and `trace_query` can filter, sort
> and group them without you writing SQL. `perf_runs` says `tables_kept: true` for the runs that have it.

## What is stored

The tables `perf_report` already reads for the summary: the GPU intervals, Metal memory, performance state, and the optional
ones the trace has (encoders, shader compiler, thermal, CPU, resource allocations, command buffer errors, shader spills),
plus the two counter tables when the recording used GPU counters. Tables only `trace_count` names by default (such as
`time-profile`) are not stored; `trace_count` says "not in this trace's tables file" for them.

Each table has the columns the export names, nothing assumed. A column `c` is kept as the cell's text (an integer or decimal
when it is exactly one, so `duration > 1000000` compares numbers; times are nanoseconds), and the formatted value Instruments
shows is what `trace_query` returns. A `process` column also keeps the process id, which is what `pid` filters on.

Command-line columns get the same cleaning as the summary's `process.arguments`, and any `/Users/<name>` becomes `~`, so the
file holds no home folder. It still holds process names, so keep it local like the `.trace`.

## Which source answers

| The run has | `trace_tables`, `trace_count`, `trace_query` read |
|---|---|
| its `.trace` (`KEEP_TRACE=1`) | the `.trace`, as before |
| only the tables file | the tables file |
| neither | an error naming both files |

`where`, `columns`, `order_by`, `descending`, `group_by` and `aggregates` always read the tables file; without it the error says so. A run
recorded before this existed keeps working through its summary and its compressed tables, as before.

## Filtering

```json
{"trace": "run1", "schema": "metal-gpu-intervals",
 "where": [{"column": "duration", "op": ">", "value": 16600000}],
 "columns": ["start", "duration", "channel-name"], "order_by": "duration", "descending": true, "limit": 20}
```

```json
{"trace": "run1", "schema": "metal-gpu-intervals", "group_by": ["channel-name"],
 "aggregates": [{"fn": "count"}, {"fn": "avg", "column": "duration"}], "order_by": "avg_duration", "descending": true}
```

- `where` filters are joined by AND; `op` is one of `=`, `!=`, `<`, `<=`, `>`, `>=`; `value` is a string or a number (`null`
  only with `=` and `!=`). A column is compared as stored, so a cell that only has a formatted value (a `process`) is found
  with `pid`, not with `where`.
- `group_by` groups by the formatted value; each aggregate is named `fn_column` (`avg_duration`), `count` for a plain count.
  `order_by` then takes a group column or an aggregate name.
- `window_ms` combines with `where` and `pid` only. Paging (`total`, `offset`, `rows`, `next_offset`) is the same in every mode.

There is no SQL: column names must be ones the table has, operators and functions come from the lists above, values are bound
parameters. The file opens read-only, a link is refused, and anything but a SELECT is denied.

## Disk

When `METAL_TRACE_MAX_DISK_MB` is set the quota removes, in this order and the oldest first within each kind: `.trace`,
`.chrome-trace`, `.tables.sqlite`, then the compressed tables. The Chrome trace comes back from the per-frame table; the tables file only serves ad hoc questions; the
compressed tables feed `perf_compare` with `skip_s` and `perf_export_trace`. `KEEP_RUNS=N` removes an older run's tables file
with the rest of its files. The current run's file is never removed. `PERF_TABLES=0` skips writing it.

See [ADR-0007](../../adr/0007-sqlite-tables-beside-the-compressed-tables.md).

Back to the [index](./index.md).
