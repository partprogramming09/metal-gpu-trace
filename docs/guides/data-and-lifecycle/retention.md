# Retention: two mechanisms that do not mix

**Reader:** people who change or tune how the runs folder is kept small. Reviewed 2026-11-16.

> **In short:** two look-alike settings stop the runs folder from growing forever. One keeps the newest N recordings and
> deletes the summaries and tables of older ones, never their big `.trace`. The other keeps the folder under a size and
> deletes only heavy files, oldest first, so the small numbers survive. If the size cannot be reached it says nothing.

Back to the [index](./index.md). Example: three recordings of 259 MiB; `KEEP_RUNS=2` removes the oldest one's summary and tables but keeps its 259 MiB `.trace`, while `METAL_TRACE_MAX_DISK_MB=600` removes only that `.trace` and leaves its summary (worked table below).

| | `KEEP_RUNS=N` | `METAL_TRACE_MAX_DISK_MB=M` |
|---|---|---|
| Counts | Runs (by modification time of their `.json`) | Bytes (MiB) of the whole top level of the folder |
| Runs in | `perf_record.sh:164` calls `prune_runs.sh`; the deletion is `prune_runs.sh:10` | `recording.finish` (`recording.py:346`) calls `retention.prune_to_quota` (`retention.py:46`) |
| Read from | The process environment, by the script and the Windows engine (`perf_record_windows.py:924`); the server passes its own on (`recording.py:360`) | `config.py:22`, at server start and every `config.reload` |
| Deletes | Every file of each run older than the newest N except its `.trace`: `${old:r}.*~*.trace` (`prune_runs.sh:10`): `.json`, tables, samplers, `.chrome-trace` | Only heavy files: `.trace`, then `.chrome-trace`, then tables (`retention.py:8-10`, `:37-42`) |
| Never deletes | `baselines.json`, `panel.json` (`prune_runs.sh:10`), the mark (not a `.json` stem), a `.trace` (`prune_runs.sh:10`, `perf_record_windows.py:515`) | A `.json`, samplers, `baselines.json`, the mark, `.presentmon.csv` (`retention.py:43`) |
| Order | Newest N survive | Oldest first inside each kind; kinds in the order above; the current run's `.trace` last |
| Skipped when | `KEEP_RUNS` is not a whole number of 1 or more (`perf_record.sh:164`); `prune_runs.sh` exits with 2 on a bad value (`prune_runs.sh:9`) | Limit unset or invalid; another recording running (`recording.py:346`) |
| Tells you | Nothing | `retention` in the summary of the recording that triggered it, if a file went |

Figure 1 on [Files on disk](./files-on-disk.md#what-a-recording-leaves-on-disk) shows the same split per file kind.

## How `KEEP_RUNS` decides

`prune_runs.sh:10` lists the folder's `.json` files except `baselines.json` and `panel.json`, newest first (zsh qualifier `om`), takes from position `keep + 1` on, and removes every file with the same stem **except a `.trace`**, which only the disk quota frees ([ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md)). A run is found by its `.json`, so a `.trace` left with no `.json` is never counted again and stays on disk ([When it fails](./when-it-fails.md), known limit 7). `test_keep_runs_still_removes_old_tables` (`tests/test_recording.py:1108`) pins the removal of compressed tables, and `test_keep_runs_never_removes_a_trace` (`:1120`) pins the `.trace`. On Windows `clean_runs` (`perf_record_windows.py:503-521`) does the same in Python with `unlink`, skipping `.trace` (`:515`), a second implementation (confirmed: no shared code).

## How the quota decides

`prune_to_quota` (`retention.py:46-82`):

1. Lists the top level with each entry's modification time and size (a folder counted recursively, a link as a file of its own size, `retention.py:13-27`).
2. If the total is at most `M` MiB, touches nothing (`retention.py:60-61`).
3. Otherwise sorts removable entries by kind, then age, and removes one at a time until it fits (`retention.py:62-81`). `kind_of` (`retention.py:30-43`): the current run's `.trace` is `CURRENT_TRACE` and goes last; the current run's `.chrome-trace` and tables are `None` (always stay); any other `.trace`, `.chrome-trace` or table is a candidate; everything else is `None`.
4. Returns `{freed_mb, removed, trace_dropped}`; `trace_dropped` is true only if the current run's own `.trace` went.

## Predicting what survives (a worked example, not a measured run)

Three `deep` runs A (oldest), B and C (just recorded), each with a 259 MiB `.trace`, 0.5 MiB of tables and a 5 KiB summary, about 778 MiB in all:

| `METAL_TRACE_MAX_DISK_MB` | What goes, in order | What is left |
|---|---|---|
| 1000 | Nothing: it fits | A, B, C complete |
| 600 | A's `.trace` (total 519 MiB, fits) | A without trace; B, C complete |
| 300 | A's `.trace`, then B's (total 260 MiB) | Only C has a `.trace` |
| 200 | A's and B's `.trace`, then A's and B's tables, then C's `.trace` (`trace_dropped: true`) | The three summaries, C's tables and the samplers, about 1 MiB |

With `KEEP_RUNS=2` A loses its summary and tables but keeps its 259 MiB `.trace`, which `perf_runs` no longer lists because it has no `.json`; B and C keep everything. With both settings the script prunes first (`KEEP_RUNS`, end of `perf_record.sh`) and the quota runs after, on what is left: A's `.trace` is then the oldest candidate, so the rows above apply to it. Read from the code and `kind_of`'s rules; **not reproduced**: no real folder here was ever over a limit, and deleting is not a read-only check. `tests/test_retention.py` exists for it (not run for this page).

## Where the limit cannot be met

The total counts everything at the top level, including files that are never candidates. If summaries, samplers and the current run's tables already exceed `M`, the folder stays over `M`: the loop ends when candidates run out (`retention.py:65-80`), with no error, and `retention` appears only if something was removed (`recording.py:348`). Nothing says the limit was not reached (confirmed by the code, not reproduced; known limit 8).
