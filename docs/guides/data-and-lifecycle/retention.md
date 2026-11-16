# Retention: two mechanisms that do not mix

**Reader:** people who change or tune how the runs folder is kept small. Reviewed 2026-11-16.

Español: [Retención: dos mecanismos que no se mezclan](../../es/guides/datos-y-su-ciclo-de-vida/retencion.md)

> **In short:** two settings stop the runs folder from growing forever. They look alike and they are not. One keeps
> the newest N recordings and deletes the older ones whole. The other keeps the folder under a size and deletes only the
> heavy files, oldest first, so the small numbers survive. If the size cannot be reached it says nothing.

Back to the [index](./index.md). Example: three recordings of 259 MiB each; `KEEP_RUNS=2` removes the oldest one
entirely, while `METAL_TRACE_MAX_DISK_MB=600` only removes its big `.trace` and leaves its summary (worked table below).

They are written by different code, read from different places, count different things and delete different files:

| | `KEEP_RUNS=N` | `METAL_TRACE_MAX_DISK_MB=M` |
|---|---|---|
| Counts | Runs (by the modification time of their `.json`) | Bytes (MiB) of the whole top level of the folder |
| Runs in | `perf_record.sh:164` calls `prune_runs.sh`; the deletion is `prune_runs.sh:9` | `recording.finish` (`recording.py:346`) calls `retention.prune_to_quota` (`retention.py:46`) |
| Read from | The process environment, by the script and by the Windows engine (`perf_record_windows.py:922`); the server passes its own environment on (`recording.py:360`) | `config.py:22`, at server start and at every `config.reload` |
| Deletes | Every file of each run older than the newest N: `${old:r}.*` (`prune_runs.sh:9`): its `.json`, tables, samplers, `.chrome-trace` and `.trace` | Only heavy files: `.trace`, then `.chrome-trace`, then tables (`retention.py:8-10`, `:37-42`) |
| Never deletes | `baselines.json`, `panel.json` (`prune_runs.sh:9`) and the mark (it is not a `.json` stem) | A `.json`, samplers, `baselines.json`, the mark, `.presentmon.csv` (`retention.py:43`) |
| Order | Newest N survive | Oldest first inside each kind; kinds in the order above; the current run's `.trace` last |
| Skipped when | `KEEP_RUNS` is not a whole number of 1 or more (`perf_record.sh:164`); `prune_runs.sh` itself exits with 2 on a bad value (`prune_runs.sh:8`) | The limit is unset or invalid; another recording is running (`recording.py:346`) |
| Tells you | Nothing | `retention` in the summary of the recording that triggered it, when at least one file went |

Figure 1 on [Files on disk](./files-on-disk.md#what-a-recording-leaves-on-disk) shows the same split per file kind.

## How `KEEP_RUNS` decides

`prune_runs.sh:9` lists the `.json` files of the folder except `baselines.json` and `panel.json`, ordered by
modification time with the newest first (zsh qualifier `om`), takes from position `keep + 1` to the end, and removes
every file that has the same stem. A run is therefore a `.json`: a `.trace` with no `.json` beside it is never looked at
by `KEEP_RUNS` ([When it fails](./when-it-fails.md), known limit 7). The test `test_keep_runs_still_removes_old_tables`
(`tests/test_recording.py:1101`) pins the removal of compressed tables. On Windows `clean_runs`
(`perf_record_windows.py:503-518`) does the same in Python with `unlink`, a second implementation (confirmed: the two
share no code).

## How the quota decides

`prune_to_quota` (`retention.py:46-82`):

1. Lists the top level of the folder with each entry's modification time and size (a folder is counted recursively, a
   link as a file of its own size, `retention.py:13-27`).
2. If the total is at most `M` MiB, returns and touches nothing (`retention.py:60-61`).
3. Otherwise sorts the removable entries by kind, then by age, and removes them one at a time until the total fits
   (`retention.py:62-81`). `kind_of` (`retention.py:30-43`) says what an entry is: the current run's `.trace` is
   `CURRENT_TRACE` and goes last; the current run's `.chrome-trace` and tables are `None`, so they stay always;
   any other `.trace`, `.chrome-trace` or table is a candidate; everything else is `None`.
4. Returns `{freed_mb, removed, trace_dropped}`; `trace_dropped` is true only if the current run's own `.trace` went.

## Predicting what survives (a worked example, not a measured run)

Three `deep` runs A (oldest), B and C (the one just recorded), each with a 259 MiB `.trace`, 0.5 MiB of tables and a
5 KiB summary, about 778 MiB in all:

| `METAL_TRACE_MAX_DISK_MB` | What goes, in order | What is left |
|---|---|---|
| 1000 | Nothing: it already fits | A, B, C complete |
| 600 | A's `.trace` (total 519 MiB, fits) | A without trace; B, C complete |
| 300 | A's `.trace`, then B's (total 260 MiB) | Only C has a `.trace` |
| 200 | A's and B's `.trace`, then A's and B's tables, then C's `.trace` (`trace_dropped: true`) | The three summaries, C's tables and the samplers, about 1 MiB |

The same three runs with `KEEP_RUNS=2` lose **all** the files of A (summary included) and keep B and C complete; with
both settings, the script prunes first (`KEEP_RUNS`, at the end of `perf_record.sh`) and the quota runs after, on what is
left. This table is read from the code and from `kind_of`'s rules; it was **not reproduced**: no real folder here was
ever over a limit, and deleting files is not something a read-only check does. `tests/test_retention.py` exists for it
(not run for this page).

## Where the limit cannot be met

The total counts everything at the top level, including files that are never candidates. A folder whose summaries,
samplers and current run's tables already exceed `M` simply stays over `M`: the loop ends when it runs out of
candidates (`retention.py:65-80`), with no error, and `retention` appears in the summary only if something was removed
(`recording.py:348`). Nothing tells you the limit was not reached (confirmed by the code, not reproduced; known limit 8).
