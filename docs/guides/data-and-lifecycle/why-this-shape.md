# Why the data is shaped this way

**Reader:** people who change the recorder or the analysis. Reviewed 2026-11-16.

> **In short:** a recording is one small file with the numbers plus big files with the raw data. Delete the big ones and
> the numbers stay readable. There is no database on purpose: a folder can be copied, committed or deleted by hand.

Back to the [index](./index.md). Example: the index folder has a 4.9 KiB summary beside a 259 MiB `.trace`, which explains most rows.

| Choice | Why | Left out |
|---|---|---|
| One small JSON summary per run | It is compared, shared and pasted into an issue, so it stays small and free of machine names, UUIDs and absolute paths ([What this is about](../index.md#what-to-know-before-touching-it)) | Numbers only in the `.trace`: 259 MiB and needs Instruments |
| Heavy data in sibling files named by the stem | A tool needing frames reads `<stem>.frames.csv.gz`; one needing the summary never touches them; pruning the heavy part leaves the summary readable | One file per run: pruning would rewrite it |
| No database, no index | The server is standard library only on Python 3.9 ([ADR-0003](../../adr/0003-python-3-9-floor.md)); a folder can be copied, committed or deleted by hand | A database file (SQLite): **speculation** it was left out for the same reason; no ADR records it |
| `.trace` deleted by default | Tens to hundreds of MB, and the summary holds its numbers (`perf_record.sh:162-163`); keep it with `KEEP_TRACE=1` or the `deep` tier for `trace_query` or Instruments | Keeping every trace: the folder grew without bound ([ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md)) |
| Tables as `.csv.gz` | Same rows, a fraction of the size; `tables.py` reads both formats so older runs work ([ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md)) | Plain CSV (heavy), raw `zlib` (no standard tool), pruning whole runs (loses the summary) |
| Two retention mechanisms | One counts runs (`KEEP_RUNS`), one counts bytes (`METAL_TRACE_MAX_DISK_MB`); see [Retention](./retention.md) | A single rule: the ADR rejected pruning whole runs by size |
