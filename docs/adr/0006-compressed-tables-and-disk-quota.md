# ADR-0006: Compressed tables and a disk limit for the runs folder

**Reader:** people

- **Status:** accepted
- **Date:** 2026-11-15
- **Decided by:** the maintainer (plan approved the same day)

## Context
Each recording leaves `<run>.frames.csv` (one line per GPU frame) and `<run>.metal_memory.csv` (one per memory sample) as
plain text, and a `.trace` when `KEEP_TRACE=1`. `KEEP_RUNS` counts runs, not bytes, and never prunes a kept `.trace`, so
the runs folder grew without a bound.

## Decision
- Write the two tables as `.csv.gz` (gzip, same bytes for the same rows) through one module, `tables`, which reads either
  format: recordings made before keep working with no conversion.
- Add `METAL_TRACE_MAX_DISK_MB`. After a recording, remove the oldest `.trace`, then `.chrome-trace`, then tables, until the
  folder fits. Summaries, `baselines.json` and the current run's tables are never removed; its `.trace` goes last.

## Alternatives considered
| Option | For | Against | Why yes / no |
|---|---|---|---|
| gzip tables, plain read fallback (chosen) | smaller; old runs untouched | two formats to read | Yes: one module hides it |
| Keep plain CSV | nothing changes | the heavy part stays heavy | No |
| Raw `zlib` | a few bytes less | no standard tool opens it | No |
| Prune whole runs, like `KEEP_RUNS` | simple | loses the summary that is the run | No |

## Consequences
- **Positive:** a smaller runs folder; a byte limit that a CI machine can set.
- **Negative / cost:** a run whose tables were pruned keeps its `.json`, but `perf_compare` with `skip_s` on it then says
  to record it again. A `.csv.gz` cut short is an error, not a short table.
- **Windows:** the engine writes the same `.csv.gz`, so a runs folder never mixes formats for new recordings.

## Revisit when
A real trace shows the limit removing runs people still compare, or a reader appears that cannot open gzip.
