# Known limits and touching it without breaking it

**Reader:** people who plan a fix in this area or change it. Reviewed 2026-11-16.

Español: [Límites conocidos y tocarlo sin romperlo](../../es/guides/datos-y-su-ciclo-de-vida/limites.md)

> **In short:** this page lists eleven behaviours of today's code that are surprising but written down, not fixed. After
> it come the rules for changing the data area without breaking older recordings, the cleanup or the privacy of shared
> summaries.

Back to the [index](./index.md). Example: limit 6 means `KEEP_RUNS=2` can also delete the big `.trace` of an old run,
although [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md) says it never prunes a kept `.trace`.

## Known limits

Each item is a limit of today's behaviour, written down, not fixed here.

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | A `profile` key in a project file is refused. That is the contract since 0.26.0 (the key is listed as removed in `CHANGELOG.md`), so a file that still has it must drop it | `project.py:43-46` | Confirmed; whether to accept it again is open |
| 2 | `.presentmon.csv` files never count toward the quota and are never removed by it | `retention.py:43` | Confirmed |
| 3 | The cache has no cleanup; 5 of its 8 folders are older pinned versions (308 MiB) | `workloads.py:22`, E8-E10 | Confirmed |
| 4 | A summary whose `.trace` is gone is normal: `trace` is only the name, the file is deleted by default; `perf_runs` reports `trace_kept` for it | `perf_report.py:650`, `perf_record.sh:163`, `analysis.py:79`, E5 | Confirmed |
| 5 | `panel.json` is still skipped everywhere though the panel is gone | `paths.py:10`, `retention.py:7`, `prune_runs.sh:3` and `:9`, `perf_record_windows.py:508`, `analysis.py:52` | Confirmed; the comment says "drop this in a later version" |
| 6 | `KEEP_RUNS` deletes the `.trace` of an older run, because `${old:r}.*` matches `<run>.trace`. [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md) says `KEEP_RUNS` "never prunes a kept `.trace`", which is true only of a `.trace` with no `.json` | `prune_runs.sh:9`, E6 | The glob is confirmed (E6); the deletion itself was not reproduced |
| 7 | A `.trace` with no `.json` (a run that did no GPU work, `deep` or `KEEP_TRACE=1`) is never seen by `KEEP_RUNS`; only the quota removes it | `recording.py:427-433`, `prune_runs.sh:9` | Confirmed by the code |
| 8 | The disk limit can be unreachable and says nothing | `retention.py:65-80`, `recording.py:348` | Confirmed by the code |
| 9 | The summary is rewritten with a non-atomic write | `perf_report.py:836`, `recording.py:350` | Confirmed by the code |
| 10 | A recording by hand and one by the server default to different folders | `config.py:16`, `perf_record.sh:28-29` | Confirmed |
| 11 | There is no real generation 2 or 3 summary on this machine to compare the key lists against | E3 | Not reproduced |

Evidence: E3, E5, E6 are in [Evidence E1 to E7](./evidence-runs.md); E8 to E10 in
[Evidence E8 to E12](./evidence-cache-and-flow.md).

## Touching it without breaking it

- A new summary key: write it where the other keys of its group are written, say in the [key tables](./json-keys.md)
  whether it is always present or conditional, and if it belongs to both platforms put it in `common` through
  `metrics.common_block`, with the key-list test updated (`test_common_block_has_the_same_keys_on_both_platforms`,
  `tests/test_analysis.py:878`). A reader must never assume a conditional key.
- A new file kind in the runs folder: give it the run's stem so `KEEP_RUNS` removes it with the run, and decide
  whether `retention.kind_of` should list it. If it is not listed it is never counted as removable and the quota can
  not free its space (limit 2 is exactly that).
- A new retention rule: keep the two mechanisms apart. If a change needs to know about both, update both columns of the
  table in [Retention](./retention.md).
- A table: write it with `tables.write` and read it with `tables.find` and `tables.open_text`; do not open a `.csv`
  directly, or runs recorded before 0.27.0, or after it, will break one way or the other.
- Anything that reads a file of the runs folder goes through `paths.read_object` or `paths.read_text`, so a link is
  never followed.
- A shared summary must not carry a machine name, a UUID or an absolute path.
