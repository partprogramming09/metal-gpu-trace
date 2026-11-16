# When it fails

**Reader:** people who debug a recording that stopped half-way or a folder with odd leftovers. Reviewed 2026-11-16.

Español: [Cuando falla](../../es/guides/datos-y-su-ciclo-de-vida/cuando-falla.md)

> **In short:** most failures clean up after themselves: the script or the server deletes the files of the failed run.
> The exceptions are a script killed with no chance to clean up, a table cut short and a run that did no GPU work. This
> page lists, for each failure, what stays on disk and who removes it.

Back to the [index](./index.md). Example: cancel a 60 s recording at second 10 and nothing of that run is left, not
even the lock; kill the script with `SIGKILL` and a stale `recording.lock` and partial files stay.

| What goes wrong | What is left on disk | Who cleans it | Line |
|---|---|---|---|
| The client cancels or the recording overruns its deadline | Nothing: the server kills the process group, the program, frees the lock and deletes the run's new files and the new `.ktrace` temporaries | the server | `recording.py:396-413` |
| The script exits with an error | Nothing of that run: the `EXIT` trap removes `$out/$name.*` if the code is not 0 | the script | `perf_record.sh:71` |
| The script gets `TERM` | The same | the script | `perf_record.sh:74` |
| The server dies mid-recording | The recording and its program are stopped by a watcher loop inside the script | the script | `perf_record.sh:82-92` |
| The script is killed with `SIGKILL` (no trap runs) | A stale `recording.lock`, partial files of the run | The next script takes over a lock whose owner is dead; `preflight` does not refuse for a dead owner. The partial files stay until `KEEP_RUNS` or the quota reaches them | `perf_record.sh:47-61`, `preflight.py:74-98` (probable: not reproduced) |
| The program did no GPU work | The summary and every file of the run are deleted; the `.trace` stays if it was asked to be kept, and the error says so | the server | `recording.py:427-436` |
| A table write is interrupted | `<table>.csv.gz.<hex>.tmp`. Its name starts with the run's stem, so `KEEP_RUNS` removes it with the run; the quota does not (its suffix is not a table suffix) | `KEEP_RUNS` | `tables.py:40-43`, `retention.py:10` |
| A `.csv.gz` is cut short or empty | An error that says to record again, not a short table | nobody: the file stays | `tables.py:29-30`, [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md) |
| A pruned table is needed (`perf_compare` with `skip_s`) | A message "has no per-frame file; record it again" | nobody | `analysis.py:510` |
| The disk is nearly full | The recording is refused before it starts: `2 + (seconds × 8 + 9) / 10` GB (integer division) free is needed in the temporary folder and the runs folder, `PERF_MIN_FREE_GB` overrides it | nobody | `perf_record.sh:34-38`, `preflight.py:128-131` |

The comment in `perf_record.sh:33` explains the disk figure: Instruments' temporary files peak around 0.8 GB per
recorded second, and 48 GB was measured for 60 s of Wine D3D12. It is a code comment, not a measurement made for this
page (**probable**).
