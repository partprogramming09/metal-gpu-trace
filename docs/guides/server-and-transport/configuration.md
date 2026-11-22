# Configuration

**Reader:** people who set up the server: environment variables and project files.

[Index](./index.md)

**In short:** the server reads its settings from environment variables (named values set before it starts) and from a small project file, `metal-gpu-trace.json`, that a repository can hold. Set two things first: where recordings go (`METAL_TRACE_OUT`, as an absolute path; a project file takes precedence) and how much is kept (`KEEP_RUNS` for the number of recordings, `METAL_TRACE_MAX_DISK_MB` for the disk size). The tables below list every setting and what it changes.

## Environment variables

| Variable | What it sets |
| --- | --- |
| `METAL_TRACE_OUT` | Where recordings go. Give an absolute path: the default, `./perf-runs`, depends on the client's working directory. A project file takes precedence. |
| `METAL_TRACE_PROJECT` | The project file to use (or the folder holding it), instead of searching from the working directory. |
| `METAL_TRACE_WINE` | The Wine directory (holding `bin/wine`) that `perf_record` uses when the call names none. |
| `WINEPREFIX` | The Wine prefix used when the call names none; `~/.wine` otherwise. |
| `METAL_TRACE_READ` | More directories the tools may read, separated by `:` (`;` on Windows). |
| `METAL_TRACE_LOG` | `off` silences the one-line stderr log per call. |
| `KEEP_TRACE` | `1` keeps each recording's `.trace`, for Instruments or the raw export (the tables file already answers `trace_tables`, `trace_count` and `trace_query`). |
| `PERF_TABLES` | `0` skips writing `<run>.tables.sqlite`. |
| `METAL_TRACE_ALLOW_LOCKED` | `1` records with the screen locked. Without it a recording is refused: a locked session leaves the frames unpaced. |
| `METAL_TRACE_MAX_DISK_MB` | Size limit of the runs folder, in MiB. After each recording the oldest `.trace` goes first, then `.chrome-trace`, then per-frame and memory tables; summaries and `baselines.json` never. [Retention](../../guides/data-and-lifecycle/retention.md) |
| `KEEP_RUNS` | Keeps only the newest N recordings. It never removes a `.trace`, and `baselines.json` is never removed. [Retention](../../guides/data-and-lifecycle/retention.md) |
| `METAL_TRACE_LOCK` | The lock that keeps recordings one at a time, whatever folder each goes to (default `~/Library/Caches/metal-gpu-trace/recording.lock`). [Cache and lock](../../guides/data-and-lifecycle/cache-and-lock.md) |
| `PERF_ENV` | `NAME=VALUE` pairs, separated by spaces, set for the recorded program. |
| `METAL_TRACE_APP_METRICS_MAX_MB` | How many MiB of the program's telemetry file are read (default 8), a whole number of 1 or more. Any other value keeps 8 and says so in `app_metrics.issues.max_mb`. [Program telemetry](../recording/macos-journey.md#program-telemetry) |
| `PERF_INSTRUMENTS` | Instruments added to the Metal System Trace template, separated by `;` (`xcrun xctrace list instruments` names them). Their tables need the `.trace`: pair it with `KEEP_TRACE=1`. |

## Projects

A repository can hold a `metal-gpu-trace.json` that names its project and the folder of its recordings:

```json
{"name": "my-game", "runs": "perf-runs", "baseline": "main-ref"}
```

The server looks for it in its working directory and the folders above it, stopping below the home folder, so one file at a repository's root serves every folder inside it. When it finds one, recordings go to and are read from `runs` instead of `METAL_TRACE_OUT`, and `baselines.json` lives there too: projects do not mix their recordings. [Project file](../../guides/data-and-lifecycle/project-and-config.md)

| Key | Meaning |
| --- | --- |
| `name` | The project's name (letters, digits, `.`, `_`, `-`). Required. |
| `runs` | The recordings folder. Required. It must be new, empty or already marked by the server (a plain `.metal-gpu-trace-runs` file, not a folder or a link). A folder with other files is refused, because `KEEP_RUNS` removes old `.json` files there. A folder marked with another project's name is refused; to hand it over, edit or remove the mark. |
| `baseline` | The name of the project's reference (`perf_baseline`). `project_info` reports it. |
| `format` | `metal-gpu-trace`, the only one for now. |

Any other key, or a wrong value, is an error that every tool reports, naming the field, until the file is fixed. Without a project file, `METAL_TRACE_OUT`, or `./perf-runs`, is used as before.
