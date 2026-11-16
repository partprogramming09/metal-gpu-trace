# Data and its lifecycle

**Reader:** people who change the recorder or the analysis, or who need to know what a recording leaves on disk, where it lives and who deletes it. Reviewed 2026-11-16.

Español: [Datos y su ciclo de vida](../es/guides/datos-y-su-ciclo-de-vida.md)

This page follows the data of one recording from the moment it is requested to the moment it is deleted. It does not
repeat [How it works](./how-it-works.md) (which layer calls which); it widens the part of it that says where
recordings live.

How to read the labels: every technical claim is **confirmed** (with `file:line`, checked with `rg` or `sed` on
2026-11-16 against the working tree, which is 0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`), **probable**
(read from the code but not run here) or **speculation** (a guess about why). Lines move when the code changes: search
the name, not only the number. Every number comes with the command that produced it, in
[Evidence](#evidence-the-commands-and-their-real-output). Where a command could not be run it says **not reproduced**.

## One example first

Suppose an agent records a program for 20 seconds with the label `mygame`. A few minutes later the runs folder holds
files like these (a real folder from another run of the same kind, trimmed, with its owner removed and its name
replaced; the command is E1):

```text
baselines.json
probe-d3d12_20261018-003026.json
v070-d3d12_20261018-021158.frames.csv
v070-d3d12_20261018-021158.json
v070-d3d12_20261018-021158.metal_memory.csv
v070-d3d12_20261018-021158.rss.csv
v070-d3d12_20261018-021158.trace          <- a folder, 259 MiB
```

Everything that belongs to one recording shares a **stem**: the label, an underscore and the start time
(`<label>_<YYYYMMDD-HHMMSS>`, `perf_record.sh:26`). The stem is the only thing that ties the files together: there is no
database and no index. The small `.json` is the **summary** (the numbers an agent reads); the other files are the data
the summary was computed from, and the `.trace` is the raw recording from Instruments, which is almost the whole
size of the folder (E2: 259 MiB of 259 MiB).

## Why the data is shaped this way

| Choice | Why | Alternatives that were left out |
|---|---|---|
| One small JSON summary per run | It is what gets compared, shared and pasted into an issue, so it must stay small and free of machine names, UUIDs and absolute paths ([What this is about](./index.md#what-to-know-before-touching-it)) | Putting the numbers in the `.trace` only: it is 259 MiB and needs Instruments to open |
| Heavy data in sibling files named by the stem | A tool that needs frames reads `<stem>.frames.csv.gz`; one that needs only the summary never touches them. Deleting the heavy part of an old run leaves the summary readable | A single file per run: pruning would mean rewriting it |
| No database, no index | The server is standard library only on Python 3.9 ([ADR-0003](../adr/0003-python-3-9-floor.md)) and a folder can be copied, committed to a branch or deleted by hand | A database file (for example SQLite): **speculation** that it was left out for the same reason; no ADR records the choice |
| `.trace` deleted by default | It is tens to hundreds of MB and the summary already holds its numbers (`perf_record.sh:162-163`); keep it with `KEEP_TRACE=1` or the `deep` tier when you want `trace_query` or Instruments | Keeping every trace: the folder grew without a bound ([ADR-0006](../adr/0006-compressed-tables-and-disk-quota.md)) |
| Tables as `.csv.gz` | Same rows, a fraction of the size, and `tables.py` reads both formats so older runs keep working ([ADR-0006](../adr/0006-compressed-tables-and-disk-quota.md)) | Plain CSV (heavy), raw `zlib` (no standard tool opens it), pruning whole runs (loses the summary) |
| Two retention mechanisms | One counts runs (`KEEP_RUNS`), one counts bytes (`METAL_TRACE_MAX_DISK_MB`); they answer different questions and delete different things (see [Retention](#retention-two-mechanisms-that-do-not-mix)) | A single rule: the ADR rejected pruning whole runs by size because it loses the summary |

## Where things live

| What | Where | Set by |
|---|---|---|
| The runs folder, MCP server | `./perf-runs` of the server's working directory | `METAL_TRACE_OUT` (`config.py:16`); a project file overrides it (`project.py:188`) |
| The runs folder, `perf_record.sh` run by hand | `PERF_OUT`, else `<clone>/logs/perf` if that folder exists, else `./perf-runs` | `perf_record.sh:28-29` |
| Folders the tools may read besides it | `METAL_TRACE_READ`, separated by `:` | `config.py:17` |
| Cache of test programs | `~/Library/Caches/metal-gpu-trace` (Windows: `%LOCALAPPDATA%\metal-gpu-trace`) | `config.py:37-40` |
| The recording lock | `<cache>/recording.lock/` | `METAL_TRACE_LOCK` or `PERF_LOCK` (`config.py:42`, `perf_record.sh:42`) |
| `.ktrace` temporary files of Instruments | `$TMPDIR/instruments*.ktrace`, removed when the script ends | `perf_record.sh:63-69` |

The two defaults for the runs folder differ: a recording started by the server and one started by hand from a clone
do not land in the same place (confirmed, lines above).

## What a recording leaves on disk

| File | What it holds | Written by | Size (E1, E2) | Read by |
|---|---|---|---|---|
| `<run>.json` | The summary (next section) | `perf_report.py:836`, rewritten by `recording.py:350` | 4.9 KiB | Every analysis tool (`analysis.py`), `perf_runs` |
| `<run>.frames.csv.gz` | One row per presented GPU frame; plain `.csv` before 0.27.0 | `perf_report.py:831` (macOS), `perf_record_windows.py:847` (Windows) | 56 KiB plain, 20 s | `analysis.read_frames` (`analysis.py:508`), the Chrome trace export (`traces.py:15`) |
| `<run>.metal_memory.csv.gz` | Metal memory allocated over time | `perf_report.py:745` | 418 KiB plain | `analysis.py:527` |
| `<run>.rss.csv` | The program's resident memory, once a second | the sampler in `perf_record.sh:105-113`; `perf_record_windows.py:669` on Windows | 367 bytes | `perf_report.py:749-753` folds it into `process_rss_mib` |
| `<run>.agx.csv` | The GPU driver's counters for the whole GPU, once a second | the sampler in `perf_record.sh:106-114` | 575 bytes | `perf_report.py:754-756` folds it into `gpu_activity` |
| `<run>.trace/` | The Instruments bundle (a folder) | `xctrace`, `perf_record.sh:140-151` | 259 MiB | `trace_query`, `trace_tables`, Instruments |
| `<run>.chrome-trace` | The frames as a Chrome trace, only when the export tool is called | `traces.py:28` | not measured here | a browser's trace viewer |
| `<run>.presentmon.csv` | PresentMon's rows (Windows only) | `perf_record_windows.py:650` | not measured here | `perf_record_windows.py` |
| `<run>.drawstress.log` | The test program's own log, one line per batch of frames (Windows only, `drawstress-log` source) | `perf_record_windows.py:632-633`, kept after a good run (`:937-941`) | not measured here | `perf_record_windows.py:762-764`; the quota ignores it, like `.presentmon.csv` (`retention.py:30-43`) |
| `baselines.json` | Named references: copies of several summaries | `analysis.py:282` | 10 KiB, 1 baseline of 3 runs (E7) | `load_baselines`, `analysis.py:254` |
| `.metal-gpu-trace-runs` | The folder's mark: a plain file holding the project's name | `project.py:198` | 8 bytes | `project.mark_owner`, `project.py:109` |
| `panel.json` | Left by 0.24.0, whose panel was removed ([ADR-0005](../adr/0005-remove-the-panel.md)) | nobody now | none on this machine | it is only skipped: `paths.py:10`, `analysis.py:52` |

Files that exist only while a recording runs: `<run>.validation.log` (when Metal validation is on, removed at
`perf_record.sh:161`) and the leftovers of an interrupted table write (`<table>.csv.gz.<hex>.tmp`, see
[When it fails](#when-it-fails)).

Which of these a pruning removes is the first figure.

![A table with one row per kind of file in a run and four columns: who writes it, what happens at the end of a run, what KEEP_RUNS does and what METAL_TRACE_MAX_DISK_MB does. Only KEEP_RUNS ever removes a summary; baselines.json and the folder mark are never removed.](/diagrams/data-files-per-run.png)
*Figure 1. The files of one run and what each pruning removes. HTML source: `docs/diagrams/data-files-per-run.html`.*

## The summary, key by key

The summary is a JSON object whose keys are written by three different pieces of code in sequence:

1. `perf_report.summarize` builds it from the `.trace` (`perf_report.py:648-835`) and writes the first `.json`.
2. `recording.finish` adds `layer`, `context`, `tier` and `retention`, rebuilds `common`, and rewrites the file
   (`recording.py:337-351`).
3. On Windows, `perf_record_windows.py` builds a different, smaller object (`perf_record_windows.py:887-917`), then `finish`
   does step 2 on it.

### The generations

`schema_version` says which generation a summary is (`metrics.py:10`, read by `metrics.schema_of`, `metrics.py:13`). A
summary without it is generation 1, and every tool still reads generation 1, 2 and 3 (`CHANGELOG.md`, 0.27.0, Changed: a summary without it is version 1 and every tool still reads it).

| Generation | What it added | Shipped in |
|---|---|---|
| 1 | The original keys | before 0.27.0 |
| 2 | Compressed tables, `tier`, `retention` (`metrics.py:9`) | 0.27.0 (`CHANGELOG.md`) |
| 3 | The `common` block (`metrics.py:9`) | `[Unreleased]` in `CHANGELOG.md`; the code already writes it |

**Every real summary on the machine this page was checked on is generation 1** (E3: no `schema_version`, no `common`,
no `tier`, no `retention`), because they were recorded before 0.27.0. So the key lists below come from the code, not from
a real generation 3 file. A generation 3 summary was **not reproduced** (it needs a macOS recording with Instruments).
Even so, the generation 1 files are what the table in [Evidence E3](#e3-keys-of-real-summaries) was compared with: every key in a real
file is in the lists below.

### Keys of a macOS summary: always present

| Key | What it holds | Written at | Read by |
|---|---|---|---|
| `schema_version` | The generation (first key) | `perf_report.py:648` | `analysis.py:74` through `metrics.schema_of` |
| `label` | The recording's label | `perf_report.py:649` | `analysis.py:643` |
| `trace` | The name of the `.trace`, kept even after the file is deleted | `perf_report.py:650` | nothing in `src/` reads the key (`rg`); `perf_runs` tests the file instead (`analysis.py:79`) |
| `process` | `name`, `pid`, `termination-reason`, `arguments` (made shareable by `public_arguments`) | `perf_report.py:651-652` | `analysis.py:74` (`arguments`), `recording.py:432` (`termination-reason`) |
| `device` | `platform`, `model`, `memory-size`, `os-version`; the machine's name and UUID are left out on purpose | `perf_report.py:654` | `analysis.py:138`, `metrics.py:55` |
| `template` | The Instruments template name | `perf_report.py:659` | `analysis.py:759` |
| `duration_s` | Seconds recorded | `perf_report.py:660` | `analysis.py:673` |
| `machine` | Chip, cores, RAM, macOS, `screen_locked` | `perf_report.py:661` | `analysis.py:195` (a locked screen) |
| `missing_tables` | Instruments tables the trace did not have | `perf_report.py:664` | no reader in `src/` (`rg`); it is for whoever reads the summary |
| `gpu` | `intervals`, `frames`, `frame_gpu_ms`, `per_channel_ms`, `frame_interval_ms`, `start_latency_ms`, `fps_estimate`, and the pacing keys below | `perf_report.py:709` | `perf_runs`, compare, diagnose, gates (`analysis.py` throughout) |
| `encoders` | Encoders and command buffers per frame, the shortest encoders, the top 20 labels | `perf_report.py:728` | `analysis.py:223`, `:702` |
| `gpu_idle` | When the GPU waited | `perf_report.py:729` | `analysis.py:231`, `:715` |
| `gpu_performance_state_share` | Share of time per GPU clock state; `{}` if there is none | `perf_report.py:771` | `analysis.py:144` |
| `hitches` | `count`, `per_minute`, `threshold_ms`, `causes`, the 20 `worst` | `perf_report.py:822` | `analysis.py:574`, `:773` |
| `common` | `frame_pacing`, `memory_pressure`, `boundness`, `submission_overhead`, `api`, built by `metrics.common_block` | `perf_report.py:835`, rebuilt at `recording.py:343` | `analysis.py:153` |
| `layer` | The translation layer: Wine and its overrides and DLL hashes, or `none` (native), `unknown` (attached), MoltenVK, Rosetta | `recording.py:341` | `recording.py:208`, `metrics.layer_label` |
| `context` | `git` (short commit and `dirty`, or null) and `instruments` (the version, or null) | `recording.py:341`, `run_context` at `recording.py:168` | `recording.py:195` |

A summary written by `perf_report.py` run by hand has no `layer` and no `context`: those two come from `recording.finish`
(confirmed: the assignments are only at `recording.py:341`).

The pacing keys inside `gpu` come from `frame_pacing` (`perf_report.py:253`) and are present only when there are frame
gaps: `fps_1pct_low` and `fps_01pct_low` (a null unless there are 100 and 1000 frames), `stutter_rate_pct` and
`frame_jitter_ms` (more than one gap), `throttling_analysis` (five gaps or more).

### Keys of a macOS summary: present only on a condition

| Key | Condition (read from the `if` around the assignment) | Written at |
|---|---|---|
| `tier` | `recording.finish` got a tier: `perf_record` passes one, `perf_attach` does not | `recording.py:344-345` |
| `retention` | `METAL_TRACE_MAX_DISK_MB` is set, no other recording is running and at least one file was removed: `{freed_mb, removed, trace_dropped}` | `recording.py:346-349` |
| `gpu.unpresented` | The program stopped presenting; the work after that is left out of the frames | `perf_report.py:721` |
| `metal_memory_mib` | The Metal memory table was read (`memory` true: not the `light` tier, not `PERF_MEMORY=0`); `{"samples": 0}` when it had no sample | `perf_report.py:740` |
| `process_rss_mib` | `<run>.rss.csv` exists beside the trace | `perf_report.py:753` |
| `gpu_activity` | `<run>.agx.csv` gave rows | `perf_report.py:756` |
| `noisy_environment` | `noisy_environment()` returned something; `true` or `false` | `perf_report.py:759` |
| `noisy_basis` | `noisy_environment` is `true`; carries `other_processes` | `perf_report.py:761-762` |
| `graphics_compiler` | The `graphics-compiler-activity-intervals` table exists | `perf_report.py:780` |
| `thermal_state_share` | The `device-thermal-state-intervals` table exists | `perf_report.py:790` |
| `cpu` | `ProcessCPUUsage` had rows for the program | `perf_report.py:798` |
| `resource_allocations` | The allocations table exists and has events | `perf_report.py:802` |
| `shader_spills` | The `graphics-compiler-spill-events` table exists | `perf_report.py:804` |
| `command_buffer_errors` | The `metal-command-buffer-error` table exists (a count) | `perf_report.py:806` |
| `validation` | `<run>.validation.log` exists (Metal validation was on) | `perf_report.py:811` |
| `gpu_counters` | The two counter tables exist and gave samples (`counters=true`, the `deep` tier) | `perf_report.py:817` |

### A Windows summary

`perf_record_windows.py:887-917` writes a smaller object: `schema_version`, `label`, `trace` (the name `<run>.trace`,
a file that never exists on Windows), `process`, `device`, `template` (`Windows Native Trace`), `duration_s`,
`missing_tables` (three fixed names), `gpu` (with `source`, one of `drawstress-log`, `presentmon` or
`dwm-composition`, plus the pacing keys and `throttling_analysis`), `encoders`, `gpu_idle`, `metal_memory_mib`
(`{"samples": 0}`), `process_rss_mib`, `layer`, `common`; `finish` then adds `context`, and `tier` and `retention`
under the same conditions. `finish` also replaces `layer` with the one `record_run` computed (`recording.py:341`, `:370`,
`:385`), which for a native Windows run reads `native Metal, no translation layer` (`recording.py:134-135`) where the
engine had written `native Windows` (`perf_record_windows.py`, same dict); `layer_label` calls both `native`, so no
reader notices (confirmed by the code, not reproduced). There is no `machine`, `hitches`, `gpu_performance_state_share` or any of the conditional
Metal keys, so a tool must treat each of them as optional (confirmed: not in the dict at those lines).

## The tables and the samplers

**`frames.csv(.gz)`** has the header `frame,start_ms,gpu_ms_<channel>...,gpu_ms_total`: one `gpu_ms_<channel>` column per
channel the trace had, lower-cased (`perf_report.py:831-834`). The real example (E4) has `compute`, `fragment` and
`vertex`. On Windows the only channel is `draw` (`perf_record_windows.py:847`). Frames the program never presented are
not in it; they are in `gpu.unpresented` (`perf_report.py:695-721`).

**`metal_memory.csv(.gz)`** is `time_ms,metal_allocated_bytes`, one row per sample of the program's Metal allocations
(`perf_report.py:745-746`).

**`rss.csv`** is `time_s,rss_kib`, **`agx.csv`** is `time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib`
(`perf_record.sh:105-106`): both are written by shell loops that run in the background during the recording
(`perf_record.sh:104-118`), for `seconds + 5` ticks of one second, and are plain text, never compressed.

**How a table is written and read** (`tables.py`):

- Written as `<stem>.csv.gz` under a temporary name `<target>.<8 hex>.tmp` in the same folder, then renamed over the
  target with `os.replace` (`tables.py:43-52`): a reader never sees half a table, and an exception while writing removes
  the temporary file (`tables.py:53-58`).
- The same rows give the same bytes: the gzip header carries no name and `mtime=0` (`tables.py:48`).
- Read by `tables.find` (`tables.py:13`): `.csv.gz` first, then `.csv`, so a run recorded before 0.27.0 keeps working
  untouched. A link is never a table (`tables.py:18`, `:26`) and a zero-byte `.gz` is an error, not an empty table
  (`tables.py:29-30`).

The real folders on this machine have no `.csv.gz` file at all, all of their tables are plain `.csv` (E1). So the
compressed path, and the size it saves, was **not reproduced** on a real recording. The compression ratio of
[ADR-0006](../adr/0006-compressed-tables-and-disk-quota.md) and [the 0.27.0 proof](../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit)
are the published source.

## The project file, the mark and the baselines

`metal-gpu-trace.json` (`project.py`, [ADR-0004](../adr/0004-project-file.md)) lives in a repository and names the
project and where its recordings go. Its keys are `name` and `runs` (required), `baseline` and `format` (`project.py:15`);
any other key is refused with its name (`project.py:43-46`, confirmed; this is also what happens to a leftover `profile`
key, removed in 0.26.0 according to `CHANGELOG.md`). `runs` is checked hard because `KEEP_RUNS` deletes files there
(`project.py:3-5`): the folder must be new, empty (desktop litter such as `.DS_Store` does not count,
`project.py:17`) or carry the mark `.metal-gpu-trace-runs`, and a mark holding another project's name refuses it
(`project.py:94-105`). `project.apply` (`project.py:162-189`) points `config.OUT`, `config.READ[0]` and
`config.BASELINES` at that folder and writes the mark (`project.py:192-201`).

`baselines.json` is a JSON object whose keys are the baseline names; each value has `runs` (the run names), `set` (a
date), `summaries` (copies of those runs' summaries) and, if asked for, `skip_s` (`analysis.py:279-280`). In the real
file (E7) the single baseline holds three summaries. The copies are the point: `KEEP_RUNS` can delete the runs the
baseline was made from and `perf_check` still judges against the saved numbers (`config.py:18`).

## `config.py` and `paths.py`

`config.py` holds the settings, and every other module reads them as `config.NAME` at the moment it uses them, never
copied (`config.py:1-2`; the rule is explained in [How it works](./how-it-works.md#two-rules-that-keep-it-testable)).

| Name | Meaning | Line |
|---|---|---|
| `OUT` | The runs folder, resolved | `config.py:16` |
| `READ` | `OUT` plus the folders in `METAL_TRACE_READ`: what the tools may read | `config.py:17` |
| `BASELINES` | `OUT/baselines.json` | `config.py:19` |
| `MAX_DISK_MB` | The byte limit in MiB: a whole number of 1 or more in `METAL_TRACE_MAX_DISK_MB`, else `None` (no limit; no error for a bad value) | `config.py:22-23` |
| `PROJECT`, `PROJECT_ERROR` | The project file in use, or what is wrong with it | `config.py:33-34` |
| `FAMILIES`, `WORKLOADS` | The two files in `data/`, loaded once at import | `config.py:35-36` |
| `CACHE` | The cache folder | `config.py:37-40` |
| `LOCK` | The recording lock, shared by every runs folder | `config.py:42` |
| `MAX_LIMIT`, `MAX_TEXT` | Rows per page (500) and characters per result (40 000) | `config.py:43-45` |

`config.reload` (`config.py:11`) re-reads `METAL_TRACE_OUT`, `METAL_TRACE_READ` and `METAL_TRACE_MAX_DISK_MB`; it runs at
import and again from `project.apply`. Anything else in this file is read once at import.

`paths.py` is what keeps a caller from naming a file it should not touch:

| Function | What it guarantees | Line |
|---|---|---|
| `name_ok` | A name of letters, digits, `.`, `_`, `-` only and at most 120 bytes (a label is limited to 100 in `recording.record`, `recording.py:312`) | `paths.py:25` |
| `run_path` | The `.json` of a named run; refuses a name outside that alphabet, `baselines.json`, `panel.json`, a link and a missing run | `paths.py:33` |
| `allowed` | A path inside `config.READ`, else a `ToolError` that says to add the directory | `paths.py:17` |
| `read_text`, `read_object` | Read a file of the runs folder never through a link (`O_NOFOLLOW`), without blocking on a pipe; `read_object` returns a JSON object or a `ToolError` that names what failed, never the path | `paths.py:43`, `:54` |
| `write_file` | Replaces a file, refusing a link | `paths.py:69` |
| `trace_path` | The `.trace` of a run name, or a path inside the readable folders | `paths.py:83` |
| `page` | One page of a list with `total`, `offset` and `next_offset` | `paths.py:94` |
| `check_cooldown`, `check_skip` | Seconds from 0 to 600, else a `ToolError` | `paths.py:102`, `:118` |

The reason for the link checks is written in the code: a runs folder may come from a clone or a download, and a link
inside it could point at any file (`paths.py:55-57`).

## Retention: two mechanisms that do not mix

Two settings keep the runs folder from growing. They look alike and they are not: they are written by different code,
read from different places, count different things and delete different files.

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

### How `KEEP_RUNS` decides

`prune_runs.sh:9` lists the `.json` files of the folder except `baselines.json` and `panel.json`, ordered by
modification time with the newest first (zsh qualifier `om`), takes from position `keep + 1` to the end, and removes
every file that has the same stem. A run is therefore a `.json`: a `.trace` with no `.json` beside it is never looked at
by `KEEP_RUNS` (see [When it fails](#when-it-fails)). The test `test_keep_runs_still_removes_old_tables`
(`tests/test_recording.py:1101`) pins the removal of compressed tables. On Windows `clean_runs`
(`perf_record_windows.py:503-518`) does the same in Python with `unlink`, a second implementation (confirmed: the two
share no code).

### How the quota decides

`prune_to_quota` (`retention.py:46-82`):

1. Lists the top level of the folder with each entry's modification time and size (a folder is counted recursively, a
   link as a file of its own size, `retention.py:13-27`).
2. If the total is at most `M` MiB, returns and touches nothing (`retention.py:60-61`).
3. Otherwise sorts the removable entries by kind, then by age, and removes them one at a time until the total fits
   (`retention.py:62-81`). `kind_of` (`retention.py:30-43`) says what an entry is: the current run's `.trace` is
   `CURRENT_TRACE` and goes last; the current run's `.chrome-trace` and tables are `None`, so they stay always;
   any other `.trace`, `.chrome-trace` or table is a candidate; everything else is `None`.
4. Returns `{freed_mb, removed, trace_dropped}`; `trace_dropped` is true only if the current run's own `.trace` went.

### Predicting what survives (a worked example, not a measured run)

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

### Where the limit cannot be met

The total counts everything at the top level, including files that are never candidates. A folder whose summaries,
samplers and current run's tables already exceed `M` simply stays over `M`: the loop ends when it runs out of
candidates (`retention.py:65-80`), with no error, and `retention` appears in the summary only if something was removed
(`recording.py:348`). Nothing tells you the limit was not reached (confirmed by the code, not reproduced).

## The cache and the lock

### The cache is not the recordings

`~/Library/Caches/metal-gpu-trace` holds **the test programs that `workload_fetch` downloads**, not recordings. Each
folder is named `<workload>-<first 12 characters of the pinned SHA-256>` (`workloads.py:22`), is downloaded once into a
temporary folder inside the cache, verified, and renamed into place (`workloads.py:156-175`). Later calls reuse it
(`workloads.py:154-155`).

The cache here weighs 942 MiB in 8 folders (E8). `data/workloads.json` pins only 3 versions (E9), so 5 of those 8
folders are older pinned versions that nothing uses: 63 + 65 + 79 + 78 + 23 = 308 MiB. Nothing in `workloads.py` deletes
a cache folder (`rg` of `rmtree` and `unlink` finds only the unpacked `part.unlink()` at `workloads.py:173`, E10),
so the cache only grows when a new release changes a pin (confirmed, with the limit that the search covers
`workloads.py` and the other modules are not known to delete there). Nothing cleans it: delete a folder by hand, it is
downloaded again when needed.

### The lock

One recording at a time, whatever folder each goes to: two programs sharing the GPU spoil both measurements
(`perf_record.sh:40`). The lock is a **folder** (`mkdir` is atomic: it either creates it or fails) named
`recording.lock` in the cache, with a file `pid` inside that holds the owner's process id.

- **Taking it.** `perf_record.sh:52-62`: `mkdir $lock`; if that fails and the owner is dead (`ps -p`), it takes the lock
  over under a second lock (`$lock.takeover`) so two recordings that find the same dead lock cannot both take it
  (`perf_record.sh:44-61`); if the owner is alive it exits with code 3 and the message `another recording is running`
  (`perf_record.sh:47-50`). Then `echo $$ > $lock/pid` (`perf_record.sh:62`).
- **Checking it without taking it.** `preflight.check` refuses before anything starts when the lock names a live
  process (`preflight.py:135-137`); `lock_owner_alive` (`preflight.py:74-94`) reads at most 32 bytes of the `pid` file,
  never through a link, and treats a missing, odd or dead owner as not running. `recording.finish` uses the same
  check so it never prunes while another recording writes into the folder (`recording.py:346`).
- **Releasing it.** The script's `EXIT` trap removes it (`perf_record.sh:65-73`); the server removes it if it killed the
  script on cancel or timeout (`recording.free_lock`, `recording.py:326-335`, called at `:404`), and only if the `pid`
  file still holds the script's own pid, so it never removes another recording's lock.
- **Windows.** `perf_record_windows.py` has its own version of the same idea: `mkdir` the lock, write the `pid`, take over
  a stale one once, release in `finally` (`perf_record_windows.py:574-597`, `:942-946`).

Right now the cache holds no lock (E8: nothing named `recording.lock`), which is the expected state between recordings.
A held lock was **not reproduced**: holding it means recording.

## From a recording to disk

![Sequence of five actors, the server, the lock, the script, the report and the runs folder, in eight numbered steps. The lock is held from step 2 to step 7. The summary is written twice, in steps 5 and 8.](/diagrams/data-recording-to-disk.png)
*Figure 2. A macOS recording from the first check to the files on disk. HTML source: `docs/diagrams/data-recording-to-disk.html`.*

The numbers are those of the figure; the proof of each is in [E11](#e11-the-eight-steps-of-figure-2).

1. **The server checks the lock.** `recording.record` calls `preflight.check` (`recording.py:315`), which reads the lock
   and refuses if a live process owns it. It never takes it.
2. **The script takes the lock** and writes its pid. From here the folder belongs to this recording.
3. **The samplers and Instruments write.** Two background loops write `.rss.csv` and `.agx.csv` once a second while
   `xctrace` writes the `.trace`.
4. **The script starts the report**: `python3 -I perf_report.py <trace> --label <stem> --out <folder>`.
5. **The report writes the tables and a first summary**, in that order: the memory table (`perf_report.py:745`), the
   frames table (`:831`), then the `.json` (`:836`).
6. **The script deletes the `.trace`** unless `KEEP_TRACE=1`, then applies `KEEP_RUNS` if it is set.
7. **The script frees the lock** when it exits.
8. **The server finishes.** `recording.finish` adds `layer`, `context`, `tier`, applies the disk limit if no other
   recording is running, and **rewrites** the `.json`.

Consequences worth knowing:

- **The summary is written twice** (steps 5 and 8), so for a short time the first version has no `layer` or `context`.
  Both writes are plain `write_text` (`perf_report.py:836`, `recording.py:350`), not the temporary-name-and-rename
  that tables use, so a reader can in principle catch a half-written file. `perf_runs` skips a summary that does not
  parse (`analysis.py:80-81`; its comment reads "a summary still being written"). Confirmed by the code; a
  half-read was **not reproduced**.
- **The disk limit only exists on the server's path.** A recording started by hand with `perf_record.sh` stops at step 7:
  it has `KEEP_RUNS` and `KEEP_TRACE`, but no `METAL_TRACE_MAX_DISK_MB`, because that is applied in Python
  (`recording.py:346`) (confirmed).
- **`KEEP_RUNS` runs while the lock is still held** (step 6 is before step 7), so no other recording can start between
  the deletion and the end of this one.

## When it fails

| What goes wrong | What is left on disk | Who cleans it | Line |
|---|---|---|---|
| The client cancels or the recording overruns its deadline | Nothing: the server kills the process group, the program, frees the lock and deletes the run's new files and the new `.ktrace` temporaries | the server | `recording.py:396-413` |
| The script exits with an error | Nothing of that run: the `EXIT` trap removes `$out/$name.*` if the code is not 0 | the script | `perf_record.sh:71` |
| The script gets `TERM` | The same | the script | `perf_record.sh:74` |
| The server dies mid-recording | The recording and its program are stopped by a watcher loop inside the script | the script | `perf_record.sh:82-92` |
| The script is killed with `SIGKILL` (no trap runs) | A stale `recording.lock`, partial files of the run | The next script takes over a lock whose owner is dead; `preflight` does not refuse for a dead owner. The partial files stay until `KEEP_RUNS` or the quota reaches them | `perf_record.sh:47-61`, `preflight.py:74-98` (probable: not reproduced) |
| The program did no GPU work | The summary and every file of the run are deleted; the `.trace` stays if it was asked to be kept, and the error says so | the server | `recording.py:427-436` |
| A table write is interrupted | `<table>.csv.gz.<hex>.tmp`. Its name starts with the run's stem, so `KEEP_RUNS` removes it with the run; the quota does not (its suffix is not a table suffix) | `KEEP_RUNS` | `tables.py:40-43`, `retention.py:10` |
| A `.csv.gz` is cut short or empty | An error that says to record again, not a short table | nobody: the file stays | `tables.py:29-30`, [ADR-0006](../adr/0006-compressed-tables-and-disk-quota.md) |
| A pruned table is needed (`perf_compare` with `skip_s`) | A message "has no per-frame file; record it again" | nobody | `analysis.py:510` |
| The disk is nearly full | The recording is refused before it starts: `2 + (seconds × 8 + 9) / 10` GB (integer division) free is needed in the temporary folder and the runs folder, `PERF_MIN_FREE_GB` overrides it | nobody | `perf_record.sh:34-38`, `preflight.py:128-131` |

The comment in `perf_record.sh:33` explains the disk figure: Instruments' temporary files peak around 0.8 GB per
recorded second, and 48 GB was measured for 60 s of Wine D3D12. It is a code comment, not a measurement made for this
page (**probable**).

## Known limits

Each item is a limit of today's behaviour, written down, not fixed here.

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | A `profile` key in a project file is refused. That is the contract since 0.26.0 (the key is listed as removed in `CHANGELOG.md`), so a file that still has it must drop it | `project.py:43-46` | Confirmed; whether to accept it again is open |
| 2 | `.presentmon.csv` files never count toward the quota and are never removed by it | `retention.py:43` | Confirmed |
| 3 | The cache has no cleanup; 5 of its 8 folders are older pinned versions (308 MiB) | `workloads.py:22`, E8-E10 | Confirmed |
| 4 | A summary whose `.trace` is gone is normal: `trace` is only the name, the file is deleted by default; `perf_runs` reports `trace_kept` for it | `perf_report.py:650`, `perf_record.sh:163`, `analysis.py:79`, E5 | Confirmed |
| 5 | `panel.json` is still skipped everywhere though the panel is gone | `paths.py:10`, `retention.py:7`, `prune_runs.sh:3` and `:9`, `perf_record_windows.py:508`, `analysis.py:52` | Confirmed; the comment says "drop this in a later version" |
| 6 | `KEEP_RUNS` deletes the `.trace` of an older run, because `${old:r}.*` matches `<run>.trace`. [ADR-0006](../adr/0006-compressed-tables-and-disk-quota.md) says `KEEP_RUNS` "never prunes a kept `.trace`", which is true only of a `.trace` with no `.json` | `prune_runs.sh:9`, E6 | The glob is confirmed (E6); the deletion itself was not reproduced |
| 7 | A `.trace` with no `.json` (a run that did no GPU work, `deep` or `KEEP_TRACE=1`) is never seen by `KEEP_RUNS`; only the quota removes it | `recording.py:427-433`, `prune_runs.sh:9` | Confirmed by the code |
| 8 | The disk limit can be unreachable and says nothing | `retention.py:65-80`, `recording.py:348` | Confirmed by the code |
| 9 | The summary is rewritten with a non-atomic write | `perf_report.py:836`, `recording.py:350` | Confirmed by the code |
| 10 | A recording by hand and one by the server default to different folders | `config.py:16`, `perf_record.sh:28-29` | Confirmed |
| 11 | There is no real generation 2 or 3 summary on this machine to compare the key lists against | E3 | Not reproduced |

## Touching it without breaking it

- A new summary key: write it where the other keys of its group are written, say in the key tables above whether it is
  always present or conditional, and if it belongs to both platforms put it in `common` through
  `metrics.common_block`, with the key-list test updated (`test_common_block_has_the_same_keys_on_both_platforms`, `tests/test_analysis.py:878`). A reader must never assume a conditional key.
- A new file kind in the runs folder: give it the run's stem so `KEEP_RUNS` removes it with the run, and decide
  whether `retention.kind_of` should list it. If it is not listed it is never counted as removable and the quota can
  not free its space (limit 2 is exactly that).
- A new retention rule: keep the two mechanisms apart. If a change needs to know about both, update both columns of the
  table in [Retention](#retention-two-mechanisms-that-do-not-mix).
- A table: write it with `tables.write` and read it with `tables.find` and `tables.open_text`; do not open a `.csv`
  directly, or runs recorded before 0.27.0, or after it, will break one way or the other.
- Anything that reads a file of the runs folder goes through `paths.read_object` or `paths.read_text`, so a link is
  never followed.
- A shared summary must not carry a machine name, a UUID or an absolute path.

## Evidence: the commands and their real output

Collected on 2026-11-16 on an Apple silicon Mac. All commands only read. Paths are shortened: the home folder is `~`,
the folder of recordings is `~/perf-runs/<project>`, the file owner is left out. The runs folder checked is one
folder of recordings made in October 2026 with an older version, the repository's own `perf-runs/` has two more
recordings of November 15.

### E1 The files a run leaves

```text
$ ls -a -1 ~/perf-runs/<project> | head -4
.
..
.metal-gpu-trace-runs
baselines.json

$ cd ~/perf-runs/<project> && ls -l -g -o -h . | sed 's/ [0-9]* *$//'
total
-rw-r--r--@  1     10K Oct 18 02:02 baselines.json
-rw-r--r--@  1    4.9K Oct 18 02:02 probe-d3d12_20261018-003026.json
-rw-r--r--@  1    2.7K Oct 18 02:02 probe-mtl_20261018-003242.json
-rw-r--r--@  1    4.2K Oct 18 02:02 ref-d3d12-1_20261018-002332.json
-rw-r--r--@  1    4.7K Oct 18 02:02 ref-d3d12-2_20261018-002603.json
-rw-r--r--@  1    4.9K Oct 18 02:02 ref-d3d12-3_20261018-002816.json
-rw-r--r--@  1    2.9K Oct 18 02:02 tp-d3d12_20261018-011509.json
-rw-r--r--@  1     56K Oct 18 02:13 v070-d3d12_20261018-021158.frames.csv
-rw-r--r--@  1    4.9K Oct 18 02:13 v070-d3d12_20261018-021158.json
-rw-r--r--@  1    418K Oct 18 02:13 v070-d3d12_20261018-021158.metal_memory.csv
-rw-r--r--@  1    367B Oct 18 02:12 v070-d3d12_20261018-021158.rss.csv
drwxr-xr-x@ 10    320B Oct 18 02:13 v070-d3d12_20261018-021158.trace
```

Seven summaries, one run with its three tables and sampler, and one `.trace`. Every table is plain `.csv`: none is
`.csv.gz`, so the compressed format was **not reproduced** on a real run.

### E2 Size

```text
$ du -sh ~/perf-runs/<project> ~/perf-runs/<project>/v070-d3d12_20261018-021158.trace
259M	~/perf-runs/<project>
259M	~/perf-runs/<project>/v070-d3d12_20261018-021158.trace
```

`du -sh` prints binary units, so 259M is 259 MiB. The `.trace` is the whole folder, to the precision `du` gives.

### E3 Keys of real summaries

```text
$ jq -r 'keys_unsorted|join(" ")' perf-runs/a2-proof-first_20261115-085621.json
label trace process device template duration_s machine missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_activity gpu_performance_state_share graphics_compiler thermal_state_share cpu resource_allocations command_buffer_errors hitches layer context

$ jq -c '{trace,schema:(.schema_version),tier,retention}' ~/perf-runs/<project>/v070-d3d12_20261018-021158.json perf-runs/a2-proof-first_20261115-085621.json
{"trace":"v070-d3d12_20261018-021158.trace","schema":null,"tier":null,"retention":null}
{"trace":"a2-proof-first_20261115-085621.trace","schema":null,"tier":null,"retention":null}

$ jq -r '"\(input_filename|split("/")|last|.[0:26]): \(keys_unsorted|join(" "))"' <the October summaries, 3 of the 5 shown here>
probe-d3d12_20261018-00302: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_performance_state_share layer
tp-d3d12_20261018-011509.j: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib gpu_performance_state_share
v070-d3d12_20261018-021158: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_performance_state_share layer
```

Every key in these real files is in the always-present or conditional tables above, one by one (`label`, `trace`,
`process`, `device`, `template`, `duration_s`, `machine`, `missing_tables`, `gpu`, `encoders`, `gpu_idle`,
`metal_memory_mib`, `process_rss_mib`, `gpu_activity`, `gpu_performance_state_share`, `graphics_compiler`,
`thermal_state_share`, `cpu`, `resource_allocations`, `command_buffer_errors`, `hitches`, `layer`, `context`). The
reverse check (a real summary with every key the code can write) was **not reproduced**: there is none. The files also
show why a reader must treat keys as optional: the older ones have no `machine`, `hitches` or `context`, and
`tp-d3d12` has no `layer`. The `python3 -I -c` listing that the plan asked for was **not reproduced**: the tool that
collected this evidence ran only read-only tools without Python, so `jq` was used instead.

### E4 The columns of the tables

```text
$ head -3 ~/perf-runs/<project>/v070-d3d12_20261018-021158.frames.csv
frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total
1,8920.469,0.1068,0.0,0.0,0.1068
2,8939.648,0.1057,0.0,0.0,0.1057

$ head -3 ~/perf-runs/<project>/v070-d3d12_20261018-021158.metal_memory.csv
time_ms,metal_allocated_bytes
2267.019,131072
8887.183,147456

$ head -3 ~/perf-runs/<project>/v070-d3d12_20261018-021158.rss.csv
time_s,rss_kib
0,0
1,0

$ head -3 perf-runs/a2-proof-first_20261115-085621.agx.csv
time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib
0,0,0,0,0,0,361
1,3,3,3,0,0,362
```

### E5 A summary whose `.trace` is gone

```text
$ cd ~/perf-runs/<project>
$ ls -d probe-mtl_20261018-003242.*
probe-mtl_20261018-003242.json

$ jq -r '.trace' v070-d3d12_20261018-021158.json probe-mtl_20261018-003242.json
v070-d3d12_20261018-021158.trace
probe-mtl_20261018-003242.trace
```

The second summary names a `.trace`, and the `ls` shows there is none (the first one does have its folder, E1).

The key names a file that is not there: that is the normal case, since the `.trace` is deleted unless asked for.

### E6 What `${old:r}.*` matches

```text
$ cd ~/perf-runs/<project>
$ ls -d v070-d3d12_20261018-021158.*
v070-d3d12_20261018-021158.frames.csv
v070-d3d12_20261018-021158.json
v070-d3d12_20261018-021158.metal_memory.csv
v070-d3d12_20261018-021158.rss.csv
v070-d3d12_20261018-021158.trace
```

This is the glob `prune_runs.sh:9` expands for an old run's stem (`${old:r}` is the `.json` name without `.json`).
It includes the `.trace`. Limit 6 rests on this output; `rm -rf` itself was **not reproduced** (it is a deletion).

### E7 The baselines file

```text
$ jq -r 'to_entries[]|"\(.key): \(.value|keys|join(","))"' ~/perf-runs/<project>/baselines.json
<baseline>: runs,set,summaries

$ jq -r '.[].summaries|length' ~/perf-runs/<project>/baselines.json
3
```

(The baseline's own name was replaced by `<baseline>`.) One baseline, with `runs`, `set` and `summaries` (three copies of
summaries), as `analysis.py:279-280` writes it.

### E8 The cache and the lock

```text
$ ls -a ~/Library/Caches/metal-gpu-trace
.
..
bgfx-examples-1d120363981c
bgfx-examples-320a6b3bbc11
bgfx-examples-9c1bd6164b4a
bgfx-examples-bd41458ee01e
bgfx-examples-c5b25350c15e
drawstress-2b3b01fa2dd0
drawstress-f7e25cbb8c4a
godot-a85320f08e1a

$ du -sh ~/Library/Caches/metal-gpu-trace
942M	~/Library/Caches/metal-gpu-trace

$ du -sh ~/Library/Caches/metal-gpu-trace/*
 97M	~/Library/Caches/metal-gpu-trace/bgfx-examples-1d120363981c
 63M	~/Library/Caches/metal-gpu-trace/bgfx-examples-320a6b3bbc11
 65M	~/Library/Caches/metal-gpu-trace/bgfx-examples-9c1bd6164b4a
 79M	~/Library/Caches/metal-gpu-trace/bgfx-examples-bd41458ee01e
 78M	~/Library/Caches/metal-gpu-trace/bgfx-examples-c5b25350c15e
 27M	~/Library/Caches/metal-gpu-trace/drawstress-2b3b01fa2dd0
 23M	~/Library/Caches/metal-gpu-trace/drawstress-f7e25cbb8c4a
510M	~/Library/Caches/metal-gpu-trace/godot-a85320f08e1a
```

No `recording.lock` is listed: nothing is recording.

### E9 The versions the package pins

```text
$ jq -r '.workloads|to_entries[]|"\(.key) \(.value.sha256[0:12])"' src/metal_gpu_trace/data/workloads.json
drawstress 2b3b01fa2dd0
bgfx-examples 1d120363981c
godot a85320f08e1a
```

Three pinned versions against eight folders: `bgfx-examples-320a`, `-9c1b`, `-bd41`, `-c5b2` and `drawstress-f7e2` match no
pin.

### E10 Nothing deletes a cache folder

```text
$ rg -n "rmtree|unlink" src/metal_gpu_trace/workloads.py
173:            part.unlink()
```

### E11 The eight steps of Figure 2

Each step is read from the line that does it (`rg -n` in `src/metal_gpu_trace`), not from a recording. The layout below
is mine (step, `file:line`, the line without its indentation); the text of each line is as `rg` printed it, trimmed to
140 characters:

```text
1  preflight.py:135        if recording_running(alive):
2  perf_record.sh:52       if ! mkdir $lock 2>/dev/null; then
2  perf_record.sh:62       echo $$ > $lock/pid
3  perf_record.sh:105      echo "time_s,rss_kib" > $out/$name.rss.csv
3  perf_record.sh:140      xcrun xctrace record --template "Metal System Trace" --time-limit ${seconds}s --output $out/$name.trace \
4  perf_record.sh:160      python3 -I $here/perf_report.py $out/$name.trace $report
5  perf_report.py:745      table_files.write(out, f"{label}.metal_memory", ["time_ms", "metal_allocated_bytes"],
5  perf_report.py:831      table_files.write(
5  perf_report.py:836      (out / f"{label}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
6  perf_record.sh:163      [[ ${KEEP_TRACE:-0} == 1 ]] || rm -rf $out/$name.trace
6  perf_record.sh:164      if [[ ${KEEP_RUNS:-} == <1-> ]]; then zsh $here/prune_runs.sh $out $KEEP_RUNS; fi
7  perf_record.sh:68       rm -rf $lock
7  perf_record.sh:73       trap cleanup EXIT
8  recording.py:346        if config.MAX_DISK_MB and not preflight.recording_running():
8  recording.py:347        removed = retention.prune_to_quota(config.OUT, config.MAX_DISK_MB, json_path.stem)
8  recording.py:350        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

The order in time (2 before 7, 5 before 8) comes from the order of the lines and the calls. A live run of the sequence
with timestamps was **not reproduced**: it records.

### E12 Where the two retention variables appear

```text
$ rg -n "KEEP_RUNS|METAL_TRACE_MAX_DISK_MB" src
src/metal_gpu_trace/perf_record_windows.py:922:        keep_runs_env = os.environ.get("KEEP_RUNS")
src/metal_gpu_trace/project.py:3:The folder is checked before use, because KEEP_RUNS removes the older .json files in it
src/metal_gpu_trace/retention.py:1:"""Keeping the runs folder under a size limit (METAL_TRACE_MAX_DISK_MB): removes the heavy files of old recordings."""
src/metal_gpu_trace/config.py:22:    limit = environ.get("METAL_TRACE_MAX_DISK_MB", "").strip()
src/metal_gpu_trace/recording.py:338:    """Adds `layer`, the run's `context` and `tier` to the summary, applies METAL_TRACE_MAX_DISK_MB ...
src/metal_gpu_trace/perf_record.sh:164:if [[ ${KEEP_RUNS:-} == <1-> ]]; then zsh $here/prune_runs.sh $out $KEEP_RUNS; fi
```

Six of the 21 lines `rg` printed are shown (the ones that read or act on a variable); each is trimmed to 120
characters. The rest only mention a variable in a comment or a docstring.

`KEEP_RUNS` is read in `perf_record.sh:164` and in `perf_record_windows.py:922`, and acts in `prune_runs.sh:9` (that file
never names the variable: it receives the number as `keep`). `METAL_TRACE_MAX_DISK_MB` is read only in `config.py:22` and
acts in `retention.py` through `recording.py:346-347`.

### What was not reproduced

- A generation 2 or 3 summary of a real recording (needs Instruments).
- A `.csv.gz` on a real run and its compression ratio.
- A recording holding the lock, and the cleanup after a killed script.
- The quota removing files, `retention` appearing in a summary, `trace_dropped`, and `KEEP_RUNS` removing a `.trace`
  (they delete files).
- The listing of keys with `python3 -I -c`.

## See also

- [How it works](./how-it-works.md): layers and the path of one request.
- [ADR-0004](../adr/0004-project-file.md): the project file and the runs folder mark.
- [ADR-0006](../adr/0006-compressed-tables-and-disk-quota.md): compressed tables and the disk limit.
- [Proof of 0.27.0](../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit): the size limit measured.
