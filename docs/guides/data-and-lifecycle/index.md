# Data and its lifecycle

**Reader:** people who change the recorder or the analysis, or who need to know what a recording leaves on disk, where it lives and who deletes it. Reviewed 2026-11-16.

Español: [Datos y su ciclo de vida](../../es/guides/datos-y-su-ciclo-de-vida/index.md)

> **In short:** every recording leaves a small group of files in one folder. One small file holds the numbers an agent
> reads; the others are the data they came from. Only a shared name keeps the group together, and two cleanup settings
> decide what is deleted and when. This guide follows one recording from request to deletion; layers are in [How it works](../how-it-works.md).

## How to read the labels

| Label | Meaning |
|---|---|
| **confirmed** | Read with `rg` or `sed` on 2026-11-16 against the working tree (0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`), with `file:line` |
| **probable** | Read from the code, not run here |
| **speculation** | A guess about why |
| **not reproduced** | Could not be run here (the evidence page says why) |

Lines move when the code changes: search the name. Every number comes with its command in the evidence pages ([E1 to E7](./evidence-runs.md), [E8 to E12](./evidence-cache-and-flow.md)).

## One example first

An agent records a program for 20 seconds with the label `mygame`. The runs folder then holds files like these (a real folder from another run of the same kind, trimmed; command: [E1](./evidence-runs.md#e1-the-files-a-run-leaves)):

```text
baselines.json
v070-d3d12_20261018-021158.json
v070-d3d12_20261018-021158.rss.csv
v070-d3d12_20261018-021158.trace          <- a folder, 259 MiB
```

Files of one recording share a **stem** (the common start of the file name): the label, an underscore and the start time (`<label>_<YYYYMMDD-HHMMSS>`, `perf_record.sh:26`). There is no database and no index. The small `.json` is the **summary** (what an agent reads); the `.trace` is the raw Instruments recording and is almost the whole folder ([E2](./evidence-runs.md#e2-size): 259 MiB of 259 MiB).

## The pages

| Page | Answers |
|---|---|
| [Why the data is shaped this way](./why-this-shape.md) | Small JSON plus sibling files, no database, two cleanup settings |
| [Files on disk](./files-on-disk.md) | Where each folder lives, what a run leaves, tables and samplers (Figure 1) |
| [The summary, key by key](./json-keys.md) | Which keys exist, which always, which on a condition, the three generations |
| [The project file, `config.py` and `paths.py`](./project-and-config.md) | The project file, the mark, the baselines, the settings, the path guards |
| [Retention](./retention.md) | `KEEP_RUNS` against `METAL_TRACE_MAX_DISK_MB`, and what survives |
| [The cache and the lock](./cache-and-lock.md) | The test-program cache and the one-recording-at-a-time lock |
| [From a recording to disk](./recording-to-disk.md) | The eight steps of a macOS recording (Figure 2) |
| [When it fails](./when-it-fails.md) | What stays on disk after each failure, and who cleans it |
| [Known limits and touching it](./limits.md) | The 11 known limits and how to change this area safely |
| Evidence: [E1 to E7](./evidence-runs.md), [E8 to E12](./evidence-cache-and-flow.md) | Files, sizes, keys, columns, the stem glob, baselines; the cache, pins, the eight steps, variables, what was not reproduced |

## See also

- [How it works](../how-it-works.md): layers and the path of one request.
- [ADR-0004](../../adr/0004-project-file.md): the project file and the runs folder mark.
- [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md): compressed tables and the disk limit.
- [Proof of 0.27.0](../../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit): the size limit measured.
