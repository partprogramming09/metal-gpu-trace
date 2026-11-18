# From a recording to disk

**Reader:** people who change the order in which a recording writes, locks and cleans up. Reviewed 2026-11-16.

> **In short:** a recording goes through eight steps: check the lock, take it, write the data, build the numbers, clean
> up, free the lock, and let the server finish. The summary is written twice. A recording started by hand skips the last step, so it has no size limit.

Back to the [index](./index.md). Example: for a 20 s recording, steps 3 and 4 make the `.trace` and `.rss.csv` appear; step 6 makes the `.trace` disappear.

![Sequence of five actors, the server, the lock, the script, the report and the runs folder, in eight numbered steps. The lock is held from step 2 to step 7. The summary is written twice, in steps 5 and 8.](./img/data-recording-to-disk.png)
*Figure 2. A macOS recording from the first check to the files on disk. HTML source: `docs/guides/data-and-lifecycle/img/data-recording-to-disk.html`.*

Numbers are those of the figure; proof in [E11](./evidence-cache-and-flow.md#e11-the-eight-steps-of-figure-2).

| # | Step | Detail |
|---|---|---|
| 1 | **The server checks the lock** | `recording.record` calls `preflight.check` (`recording.py:315`): refuses if a live process owns the lock; never takes it |
| 2 | **The script takes the lock** | Writes its pid; the folder now belongs to this recording |
| 3 | **Samplers and Instruments write** | Two background loops write `.rss.csv` and `.agx.csv` once a second while `xctrace` writes the `.trace` |
| 4 | **The script starts the report** | `python3 -I perf_report.py <trace> --label <stem> --out <folder>` |
| 5 | **The report writes the tables, then a first summary** | Memory table (`perf_report.py:745`), frames table (`:831`), then the `.json` (`:836`) |
| 6 | **The script deletes the `.trace`** | Unless `KEEP_TRACE=1`; then applies `KEEP_RUNS` if set (it removes the older runs' other files, never their `.trace`; see [Retention](./retention.md)) |
| 7 | **The script frees the lock** | When it exits |
| 8 | **The server finishes** | `recording.finish` adds `layer`, `context`, `tier`, applies the disk limit if no other recording runs, and **rewrites** the `.json` |

## Consequences worth knowing

- **The summary is written twice** (steps 5 and 8), so briefly the first version has no `layer` or `context`. Both writes are plain `write_text` (`perf_report.py:836`, `recording.py:350`), not the temporary-name-and-rename of tables, so a reader can in principle catch a half-written file. `perf_runs` skips a summary that does not parse (`analysis.py:80-81`: "a summary still being written"). Confirmed by the code; a half-read was **not reproduced** (known limit 9).
- **The disk limit only exists on the server's path.** A hand-run `perf_record.sh` stops at step 7: it has `KEEP_RUNS` and `KEEP_TRACE` but no `METAL_TRACE_MAX_DISK_MB`, applied in Python (`recording.py:346`) (confirmed).
- **`KEEP_RUNS` runs while the lock is held** (step 6 before 7), so no other recording starts mid-deletion.
