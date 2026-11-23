# Known limits and touching it without breaking it

**Reader:** people who plan a fix in this area or change it. Reviewed 2026-11-16.

> **In short:** eleven surprising behaviours of today's code. Eight are still open and written down; three (rows 1, 6 and
> 9) were fixed on 2026-11-16 and 2026-11-22 and stay listed with their commits. Then come the rules for changing the
> data area without breaking older recordings, the cleanup or the privacy of shared summaries.

Back to the [index](./index.md). Example: row 6 was `KEEP_RUNS=2` deleting the big `.trace` of an old run, although [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md) says it never prunes a kept `.trace`; the fix (24490ec) makes the code match the ADR.

## Known limits

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | A `profile` key in a project file is still refused, the contract since 0.26.0 (listed as removed in `CHANGELOG.md`). The error now says it was removed and to delete it, but only when `profile` is among the first five unknown keys it lists (9b66165) | `project.py::load` | Fixed 2026-11-16 (commits 2720b23, 9b66165); whether to accept the key again is open |
| 2 | `.presentmon.csv` files never count toward the quota and are never removed by it | `retention.py::kind_of` | Confirmed |
| 3 | The cache has no cleanup; 5 of its 8 folders are older pinned versions (308 MiB) | `workloads.py::workload_entry`, E8-E10 | Confirmed |
| 4 | A summary whose `.trace` is gone is normal: `trace` is only the name and the file is deleted by default; `perf_runs` reports `trace_kept` | `perf_report.py::summarize`, `perf_record.sh:163`, `analysis.py::tool_perf_compare`, E5 | Confirmed |
| 5 | `panel.json` is still skipped everywhere though the panel is gone | `paths.py:10`, `retention.py:7`, `prune_runs.sh:3` and `:9`, `perf_record_windows.py::record_windows`, `analysis.py:52` | Confirmed; the comment says "drop this in a later version" |
| 6 | `KEEP_RUNS` used to delete the `.trace` of an older run, because `${old:r}.*` matched `<run>.trace`, against [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md) ("never prunes a kept `.trace`"). The glob now excludes `*.trace`, and the Windows `clean_runs` skips it; only `METAL_TRACE_MAX_DISK_MB` frees a `.trace` | `prune_runs.sh:10`, `perf_record_windows.py::record_windows` | Fixed 2026-11-16 (commit 24490ec). E6 measured the old glob, before 24490ec |
| 7 | A `.trace` with no `.json` is never counted by `KEEP_RUNS`, so it is never removed by it: a recording with no GPU work, `deep` or `KEEP_TRACE=1`, and an older run whose `.json` `KEEP_RUNS` has already removed. `perf_runs` does not list it. Only `METAL_TRACE_MAX_DISK_MB` removes it; with that variable unset (the default) it stays on disk | `recording.py::run_recording`, `prune_runs.sh:10` | Confirmed by the code |
| 8 | The disk limit can be unreachable and says nothing | `retention.py::prune_to_quota`, `recording.py::free_lock` | Confirmed by the code |
| 9 | The summary was rewritten with a non-atomic write, so a crash could leave half a `.json`. It now goes through a unique temporary file in the same folder, flushed to disk and renamed (`paths.write_file`); `fsync` before the rename is by design and a power cut was not simulated. A SIGKILL between creating the temporary file and the rename leaves a hidden `.<name>.<16 hex>.tmp` that nothing cleans. On Windows `os.replace` can fail with `ToolError` (permission denied) when another process has the destination open at that instant | `paths.py::_write_error`, `perf_report.py::summarize`, `recording.py::finish`, `perf_record_windows.py::record_windows` | Fixed 2026-11-22 (commit 0610c99) |
| 10 | A hand recording and a server recording default to different folders | `config.py::reload`, `perf_record.sh:28-29` | Confirmed |
| 11 | No real generation 2 or 3 summary here to compare the key lists against | E3 | Not reproduced |

E3, E5, E6 are in [Evidence E1 to E7](./evidence-runs.md); E8 to E10 in [Evidence E8 to E12](./evidence-cache-and-flow.md).

## Touching it without breaking it

- **A new summary key:** write it with the other keys of its group, say in the [key tables](./json-keys.md) whether it is always present or conditional, and if it belongs to both platforms put it in `common` through `metrics.common_block` with the key-list test updated (`test_common_block_has_the_same_keys_on_both_platforms`, `tests/test_analysis.py::test_old_csv_and_new_csv_gz_read_the_same_in_every_tool`). A reader must never assume a conditional key.
- **A new file kind in the runs folder:** give it the run's stem so `KEEP_RUNS` removes it with the run, and decide whether `retention.kind_of` lists it; if not, the quota can never free its space (limit 2).
- **A new retention rule:** keep the two mechanisms apart; if a change needs both, update both columns of the table in [Retention](./retention.md).
- **A table:** write with `tables.write`, read with `tables.find` and `tables.open_text`; never open a `.csv` directly, or runs from before or after 0.27.0 will break.
- **Reading a file of the runs folder:** through `paths.read_object` or `paths.read_text`, so a link is never followed.
- **Writing a file of the runs folder:** through `paths.write_file`, which writes a unique temporary file beside it and
  renames it, so a crash or a full disk leaves the previous file or none, never half a file. The lock's `pid` file is
  the exception: it lives in the lock folder and no tool reads it as a result.
- **A shared summary** must not carry a machine name, a UUID or an absolute path.
