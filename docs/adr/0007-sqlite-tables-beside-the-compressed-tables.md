# ADR-0007: SQLite tables beside the compressed tables

**Reader:** people

- **Status:** accepted (amends [ADR-0006](0006-compressed-tables-and-disk-quota.md))
- **Date:** 2026-11-16
- **Decided by:** the maintainer (plan approved the same day)

## Context
`trace_tables`, `trace_count` and `trace_query` read the `.trace` through `xctrace export`, one table per call, and the
`.trace` is deleted after the summary unless `KEEP_TRACE=1`. A recording without its `.trace` could not be questioned
again ("which frames took more than 16.6 ms?") except through the two compressed per-frame and memory tables, which hold
a few columns and no filter.

## Decision
- While `perf_report` reads each table for the summary it also stores the rows in `<run>.tables.sqlite`, in one
  transaction, in a temporary file moved into place at the end. It stores the tables the summary already reads (plus
  `gpu-counter-info` with counters; the samples of `gpu-counter-value` are not stored: 2 955 137 rows made 229 MB of a
  233 MB file in a 6 s recording), so no extra `xctrace` call is made. Columns are the export's own, with the cell's text
  (a number when it is exactly one), its formatted value where that differs, and the pid of a `process` cell.
- Before storing, a command-line column gets the summary's `public_arguments` and any `/Users/<name>` becomes `~`.
- The three tools read the file when the `.trace` is not there; when it is, nothing changes. `trace_query` gains
  declarative filters (`where`, `columns`, `order_by`, `descending`, `group_by`, `aggregates`), never SQL: names are taken
  from the file and quoted, operators and functions come from fixed lists, values are bound parameters. The file opens
  read-only, with an authorizer that allows only SELECT, and a link is refused.
- `.frames.csv.gz` and `.metal_memory.csv.gz` stay as they are; the readers of summary generations 1 to 3 do not change.
- Disk: the quota removes, oldest first, `.trace`, then `.chrome-trace`, then `.tables.sqlite`, then the compressed tables.
  The Chrome trace is rebuilt from the per-frame table at no cost; the SQLite file is only for ad hoc questions; the
  compressed tables feed `perf_compare` with `skip_s` and `perf_export_trace`. `KEEP_RUNS` removes an older run's file
  with the rest of it. The current run's file is never removed.
- `PERF_TABLES=0` (or `--no-tables`) skips the file.

## Alternatives considered
| Option | For | Against | Why yes / no |
|---|---|---|---|
| SQLite beside the `csv.gz` (chosen) | filters and grouping without a `.trace`; standard library | about 7 times the size of a `csv.gz` of the same rows (synthetic data) | Yes |
| Keep every `.trace` | exact | hundreds of MB each, slow exports | No |
| Free SQL in `trace_query` | flexible | an agent's text reaches the database | No: declarative filters |
| Replace the `csv.gz` | one format | breaks readers of old runs and `perf_compare` | No |

## Consequences
- **Positive:** a run stays questionable at the price of a few MB instead of its `.trace`.
- **Negative / cost:** the summary takes longer (the rows are written as they are read; on 200 000 synthetic rows (45 MB of XML) the read goes from 1.8 s to 3.1 s, before the `xctrace` export, which
  is the larger part). The real columns of an Instruments recording were not seen when this was written, so the design stores whatever
  columns come. Only the tables the summary reads are stored: `trace_count` says so for the others.
- **Privacy:** the file is local and holds process names and labels; it is not part of the shared summary.

## Revisit when
A real recording shows the ingest slowing the summary noticeably, or the file outweighing the `.trace` it replaces.
