# Why the data is shaped this way

**Reader:** people who change the recorder or the analysis. Reviewed 2026-11-16.

Español: [Por qué los datos tienen esta forma](../../es/guides/datos-y-su-ciclo-de-vida/por-que-esta-forma.md)

> **In short:** a recording is split into one small file with the numbers and several big files with the raw data. You
> can delete the big ones and the numbers stay readable. There is no database on purpose: a folder can be copied,
> committed or deleted by hand. This page lists each choice, why it was made and what was rejected.

Back to the [index](./index.md). Example: the folder in the index shows one 4.9 KiB summary beside a 259 MiB `.trace`,
which is the reason for most rows below.

| Choice | Why | Alternatives that were left out |
|---|---|---|
| One small JSON summary per run | It is what gets compared, shared and pasted into an issue, so it must stay small and free of machine names, UUIDs and absolute paths ([What this is about](../index.md#what-to-know-before-touching-it)) | Putting the numbers in the `.trace` only: it is 259 MiB and needs Instruments to open |
| Heavy data in sibling files named by the stem | A tool that needs frames reads `<stem>.frames.csv.gz`; one that needs only the summary never touches them. Deleting the heavy part of an old run leaves the summary readable | A single file per run: pruning would mean rewriting it |
| No database, no index | The server is standard library only on Python 3.9 ([ADR-0003](../../adr/0003-python-3-9-floor.md)) and a folder can be copied, committed to a branch or deleted by hand | A database file (for example SQLite): **speculation** that it was left out for the same reason; no ADR records the choice |
| `.trace` deleted by default | It is tens to hundreds of MB and the summary already holds its numbers (`perf_record.sh:162-163`); keep it with `KEEP_TRACE=1` or the `deep` tier when you want `trace_query` or Instruments | Keeping every trace: the folder grew without a bound ([ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md)) |
| Tables as `.csv.gz` | Same rows, a fraction of the size, and `tables.py` reads both formats so older runs keep working ([ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md)) | Plain CSV (heavy), raw `zlib` (no standard tool opens it), pruning whole runs (loses the summary) |
| Two retention mechanisms | One counts runs (`KEEP_RUNS`), one counts bytes (`METAL_TRACE_MAX_DISK_MB`); they answer different questions and delete different things (see [Retention](./retention.md)) | A single rule: the ADR rejected pruning whole runs by size because it loses the summary |
