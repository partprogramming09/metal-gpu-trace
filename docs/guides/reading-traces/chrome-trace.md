# Exporting a `.chrome-trace`

**Reader:** people who want to see a run's frames on a timeline, or who change `tool_perf_export_trace`. Reviewed 2026-11-16.

> **In short:** `perf_export_trace` turns a run's table of frames into a file Perfetto (a free timeline viewer) opens. Each
> frame is one bar, as long as the GPU worked on it. It needs no `.trace` and no `xctrace`, only the per-frame table every run
> keeps. It is a coarse view: one track, no encoders, no memory.

`tool_perf_export_trace(run)` (`traces.py:9-30`) writes JSON in the Chrome trace event format, which `ui.perfetto.dev` and
`chrome://tracing` open (docstring, `traces.py:10-13`; the viewers were **not opened**). Worked example with the real first row:
[index](./index.md#one-example-first).

## How it works, in order

| # | Step | Detail | Line |
|---|---|---|---|
| 1 | Check the run | `paths.run_path(run)`: valid name, `<run>.json` exists, not a link, not `baselines.json`. Unknown: `no run <name>; perf_runs lists them` | `traces.py::tool_perf_export_trace`, `paths.py:33-41` |
| 2 | Find the table | `table_files.find(config.OUT, f"{run}.frames")`: `<run>.frames.csv.gz` first, `.csv` second, not a link. None: `<run> has no per-frame file; record it again` | `traces.py::tool_perf_export_trace`, `tables.py::find`, `:16-17` |
| 3 | One **complete event** per row | `"ph": "X"` (a slice with start and length), named `GPU frame`, process 1, thread 1: `ts = start_ms × 1000`, `dur = gpu_ms_total × 1000` (microseconds); `args` = frame number plus each `gpu_ms_<channel>` except the total, prefix cut (`compute`, `fragment`, `vertex`) | `:22-25` |
| 4 | Bad table | unreadable, a missing column or a non-number: `<file name> cannot be read; record it again`; no partial file | `:26-27` |
| 5 | Write | `{"traceEvents": [...], "displayTimeUnit": "ms"}` to `<runs folder>/<run>.chrome-trace`; returns `{"file": "<run>.chrome-trace", "frames": <events>}`. `paths.write_file` replaces an older file and refuses to write through a link | `:28-30`, `paths.py:69-80` |

The hints say it is idempotent and not destructive (`registry.py:129-131`): running it twice writes the same file.

## What the file shows and what it does not

| Aspect | What happens |
|---|---|
| **One track, one slice per frame** | Everything is on process 1, thread 1, so a slice longer than the gap to the next frame overlaps it; Perfetto stacks them. The length is the **sum** over the three channels (`gpu_ms_total`), not first-to-last interval. The docstring says parallel encoders "can show shorter than it took", but a sum of parallel work is longer, not shorter (F8, [limits](./limits.md)) |
| **Only the frames the summary kept** | Stretches rendered but not presented are out of `frames.csv` (see [Work that was never presented](../summarizing/trace-to-summary.md#work-that-was-never-presented)), so out of the timeline. The second real run has 153 frames (E4) for 20 seconds |
| **No encoders, command buffers or memory** | The finer view is `trace_query` on the GPU intervals of a kept `.trace` |
| **A retention kind of its own** | The disk quota deletes it second, after a `.trace` and before the tables, but the **current** run's export stays (`retention.py:5-8`, `:30-43`; [data guide](../data-and-lifecycle/index.md)). It makes no new run: `perf_runs` does not list it (`tests/test_analysis.py:333`, not run) |

Back to the [index](./index.md).
