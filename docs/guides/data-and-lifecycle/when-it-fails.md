# When it fails

**Reader:** people who debug a recording that stopped half-way or a folder with odd leftovers. Reviewed 2026-11-16.

> **In short:** most failures clean up after themselves. The exceptions are a script killed with no chance to clean up, a
> table cut short and a run that did no GPU work. For each failure: what stays on disk and who removes it.

Back to the [index](./index.md). Example: cancel a 60 s recording at second 10 and nothing of that run is left, not even the lock; kill the script with `SIGKILL` and a stale `recording.lock` and partial files stay.

| What goes wrong | What is left on disk | Who cleans it | Line |
|---|---|---|---|
| The client cancels or the recording overruns its deadline | Nothing: the server kills the process group and the program, frees the lock, deletes the run's new files and new `.ktrace` temporaries | the server | `recording.py::record_run` |
| The script exits with an error, or gets `TERM` | Nothing of that run: the `EXIT` trap removes `$out/$name.*` if the code is not 0 | the script | `perf_record.sh:71`, `:74` |
| The server dies mid-recording | The recording and its program are stopped by a watcher loop in the script | the script | `perf_record.sh:82-92` |
| The script is killed with `SIGKILL` (no trap runs) | A stale `recording.lock`, partial files | The next script takes over a lock whose owner is dead (`preflight` does not refuse for it); partial files stay until `KEEP_RUNS` or the quota reaches them | `perf_record.sh:47-61`, `preflight.py:74-98` (probable: not reproduced) |
| The program did no GPU work | Summary and every file deleted; the `.trace` stays if asked to be kept, and the error says so | the server | `recording.py::run_recording` |
| A table write is interrupted | `<table>.csv.gz.<hex>.tmp`; its name starts with the run's stem, so `KEEP_RUNS` removes it with the run; the quota does not (its suffix is not a table suffix) | `KEEP_RUNS` | `tables.py::write`, `retention.py::TABLE_SUFFIXES` |
| A `.csv.gz` is cut short or empty | An error saying to record again, not a short table | nobody: the file stays | `tables.py::open_text`, [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md) |
| A pruned table is needed (`perf_compare` with `skip_s`) | "has no per-frame file; record it again" | nobody | `analysis.py::read_frames` |
| The disk is nearly full | Refused before starting: `2 + (seconds × 8 + 9) / 10` GB (integer division) free is needed in the temporary and runs folders; `PERF_MIN_FREE_GB` overrides | nobody | `perf_record.sh:34-38`, `preflight.py::check` |

The comment at `perf_record.sh:33` explains the disk figure: Instruments' temporaries peak around 0.8 GB per recorded second, and 48 GB was measured for 60 s of Wine D3D12. It is a code comment, not measured for this page (**probable**).
