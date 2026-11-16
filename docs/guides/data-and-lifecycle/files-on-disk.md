# Files on disk

**Reader:** people who need to know what a recording leaves on disk and where. Reviewed 2026-11-16.

Español: [Archivos en disco](../../es/guides/datos-y-su-ciclo-de-vida/archivos-en-disco.md)

> **In short:** a run is a handful of files sharing one name start, in one folder. This page says where that folder
> is, what each file holds, who writes it and who reads it, then the two table formats and the two once-a-second samplers.

Back to the [index](./index.md). Example: for the run `v070-d3d12_20261018-021158`, the `.rss.csv` is 367 bytes and the `.trace` folder 259 MiB ([E1](./evidence-runs.md#e1-the-files-a-run-leaves), [E2](./evidence-runs.md#e2-size)).

## Where things live

| What | Where | Set by |
|---|---|---|
| Runs folder, MCP server | `./perf-runs` of the server's working directory | `METAL_TRACE_OUT` (`config.py:16`); a project file overrides it (`project.py:188`) |
| Runs folder, `perf_record.sh` by hand | `PERF_OUT`, else `<clone>/logs/perf` if it exists, else `./perf-runs` | `perf_record.sh:28-29` |
| Other readable folders | `METAL_TRACE_READ`, separated by `:` | `config.py:17` |
| Cache of test programs | `~/Library/Caches/metal-gpu-trace` (Windows: `%LOCALAPPDATA%\metal-gpu-trace`) | `config.py:37-40` |
| Recording lock | `<cache>/recording.lock/` | `METAL_TRACE_LOCK` or `PERF_LOCK` (`config.py:42`, `perf_record.sh:42`) |
| Instruments `.ktrace` temporaries | `$TMPDIR/instruments*.ktrace`, removed when the script ends | `perf_record.sh:63-69` |

The two defaults for the runs folder differ: a server recording and a hand recording from a clone land in different places (confirmed; known limit 10).

## What a recording leaves on disk

| File | Holds | Written by | Size (E1, E2) | Read by |
|---|---|---|---|---|
| `<run>.json` | The summary ([keys](./json-keys.md)) | `perf_report.py:836`, rewritten by `recording.py:350` | 4.9 KiB | Every analysis tool (`analysis.py`), `perf_runs` |
| `<run>.frames.csv.gz` | One row per presented GPU frame; plain `.csv` before 0.27.0 | `perf_report.py:831` (macOS), `perf_record_windows.py:847` (Windows) | 56 KiB plain, 20 s | `analysis.read_frames` (`analysis.py:508`), Chrome trace export (`traces.py:15`) |
| `<run>.metal_memory.csv.gz` | Metal memory over time | `perf_report.py:745` | 418 KiB plain | `analysis.py:527` |
| `<run>.rss.csv` | Resident memory, once a second | sampler `perf_record.sh:105-113`; `perf_record_windows.py:669` (Windows) | 367 bytes | `perf_report.py:749-753` folds it into `process_rss_mib` |
| `<run>.agx.csv` | The GPU driver's counters for the whole GPU, once a second | sampler `perf_record.sh:106-114` | 575 bytes | `perf_report.py:754-756` folds it into `gpu_activity` |
| `<run>.trace/` | The Instruments bundle (a folder) | `xctrace`, `perf_record.sh:140-151` | 259 MiB | `trace_query`, `trace_tables`, Instruments |
| `<run>.chrome-trace` | Frames as a Chrome trace, only when the export tool is called | `traces.py:28` | not measured here | a browser's trace viewer |
| `<run>.presentmon.csv` | PresentMon rows (Windows only) | `perf_record_windows.py:650` | not measured here | `perf_record_windows.py` |
| `<run>.drawstress.log` | The test program's log, one line per batch of frames (Windows only, `drawstress-log` source) | `perf_record_windows.py:632-633`, kept after a good run (`:937-941`) | not measured here | `perf_record_windows.py:762-764`; the quota ignores it, like `.presentmon.csv` (`retention.py:30-43`) |
| `baselines.json` | Named references: copies of several summaries | `analysis.py:282` | 10 KiB, 1 baseline of 3 runs ([E7](./evidence-runs.md#e7-the-baselines-file)) | `load_baselines`, `analysis.py:254` |
| `.metal-gpu-trace-runs` | The folder's mark: a plain file with the project's name | `project.py:198` | 8 bytes | `project.mark_owner`, `project.py:109` |
| `panel.json` | Left by 0.24.0, whose panel was removed ([ADR-0005](../../adr/0005-remove-the-panel.md)) | nobody now | none here | only skipped: `paths.py:10`, `analysis.py:52` |

Files that exist only while recording: `<run>.validation.log` (Metal validation on; removed at `perf_record.sh:161`) and leftovers of an interrupted table write (`<table>.csv.gz.<hex>.tmp`, see [When it fails](./when-it-fails.md)).

![A table with one row per kind of file in a run and four columns: who writes it, what happens at the end of a run, what KEEP_RUNS does and what METAL_TRACE_MAX_DISK_MB does. Only KEEP_RUNS ever removes a summary; baselines.json and the folder mark are never removed.](./img/data-files-per-run.png)
*Figure 1. The files of one run and what each pruning removes. HTML source: `docs/guides/data-and-lifecycle/img/data-files-per-run.html`.*

## The tables and the samplers

| File | Header | Notes |
|---|---|---|
| `frames.csv(.gz)` | `frame,start_ms,gpu_ms_<channel>...,gpu_ms_total` | One lower-cased `gpu_ms_<channel>` column per channel in the trace (`perf_report.py:831-834`); the real example ([E4](./evidence-runs.md#e4-the-columns-of-the-tables)) has `compute`, `fragment`, `vertex`. On Windows the only channel is `draw` (`perf_record_windows.py:847`). Unpresented frames are not in it but in `gpu.unpresented` (`perf_report.py:695-721`) |
| `metal_memory.csv(.gz)` | `time_ms,metal_allocated_bytes` | One row per sample of the program's Metal allocations (`perf_report.py:745-746`) |
| `rss.csv` | `time_s,rss_kib` | Background shell loops (`perf_record.sh:104-118`), `seconds + 5` one-second ticks; plain text, never compressed |
| `agx.csv` | `time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib` | Same loops (`perf_record.sh:105-106`) |

**How a table is written and read** (`tables.py`):

- Written as `<stem>.csv.gz` under a temporary name `<target>.<8 hex>.tmp` in the same folder, then `os.replace`d over the target (`tables.py:43-52`): a reader never sees half a table, and an exception removes the temporary file (`tables.py:53-58`).
- Same rows, same bytes: the gzip header has no name and `mtime=0` (`tables.py:48`).
- Read by `tables.find` (`tables.py:13`): `.csv.gz` first, then `.csv`, so runs before 0.27.0 keep working. A link is never a table (`tables.py:18`, `:26`); a zero-byte `.gz` is an error, not an empty table (`tables.py:29-30`).

The real folders here have no `.csv.gz` at all (E1), so the compressed path and its saving were **not reproduced** on a real recording. The ratio comes from [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md) and [the 0.27.0 proof](../../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit).
