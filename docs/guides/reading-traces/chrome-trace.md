# Exporting a `.chrome-trace`

**Reader:** people who want to see a run's frames on a timeline, or who change `tool_perf_export_trace`. Reviewed 2026-11-16.

Español: [Exportar un `.chrome-trace`](../../es/guides/leer-trazas/chrome-trace.md)

> **In short:** `perf_export_trace` turns a run's table of frames into a file that Perfetto (a free timeline viewer) opens.
> Each frame becomes one bar: it starts when the frame started and is as long as the GPU worked on it. It needs no `.trace`
> and no `xctrace`, only the per-frame table that every run keeps. It is a coarse view: one track, no encoders, no memory.

`tool_perf_export_trace(run)` (`traces.py:9-30`) answers "show me the frames of this run in a timeline". The file is JSON in
the Chrome trace event format, which `ui.perfetto.dev` and `chrome://tracing` open (docstring, `traces.py:10-13`; the viewers
were **not opened** for this guide). The worked example, with the real first row, is in the [index](./index.md#one-example-first).

## How it works, in order

| # | Step | Detail | Line |
|---|---|---|---|
| 1 | Check the run | `paths.run_path(run)`: valid name, `<run>.json` exists, is not a link, is not `baselines.json`. Unknown run: `no run <name>; perf_runs lists them` | `traces.py:14`, `paths.py:33-41` |
| 2 | Find the table | `table_files.find(config.OUT, f"{run}.frames")`: `<run>.frames.csv.gz` first, `.csv` second, not a link. None: `<run> has no per-frame file; record it again` | `traces.py:15`, `tables.py:13-20`, `:16-17` |
| 3 | One **complete event** per row | `"ph": "X"` (a slice with a start and a length), named `GPU frame`, process 1, thread 1: `ts = start_ms × 1000`, `dur = gpu_ms_total × 1000` (microseconds); `args` = the frame number plus each `gpu_ms_<channel>` column except the total, prefix cut (`compute`, `fragment`, `vertex`) | `:22-25` |
| 4 | Bad table | unreadable, a missing column or a non-number: `<file name> cannot be read; record it again`; no partial file is written | `:26-27` |
| 5 | Write | `{"traceEvents": [...], "displayTimeUnit": "ms"}` to `<runs folder>/<run>.chrome-trace`; returns `{"file": "<run>.chrome-trace", "frames": <events>}`. `paths.write_file` replaces an older file of that name and refuses to write through a link | `:28-30`, `paths.py:69-80` |

The tool's hints say it is idempotent and not destructive (`registry.py:129-131`): running it twice writes the same file.

## What the file shows and what it does not

| Aspect | What happens |
|---|---|
| **One track, one slice per frame** | Everything is on process 1 and thread 1, so a frame whose slice is longer than the gap to the next one overlaps it; Perfetto stacks them. The length is the GPU time, the **sum** over the three channels (`gpu_ms_total`), not the time between the first and last interval. The docstring says a frame with parallel encoders "can show shorter than it took", but a sum of parallel work is longer than the elapsed time, not shorter (finding F8, [limits](./limits.md)) |
| **Only the frames the summary kept** | A stretch where the program rendered but did not present is left out of `frames.csv` (see [Work that was never presented](../summarizing/trace-to-summary.md#work-that-was-never-presented)), so also from the timeline. The second real run of the clone has 153 frames (E4) for 20 seconds of recording |
| **No encoders, no command buffers, no memory** | One coarse track; the finer view is `trace_query` on the GPU intervals of a kept `.trace` |
| **A retention kind of its own** | A `.chrome-trace` is the second thing the disk quota deletes, after a `.trace` and before the tables, except that the **current** run's export stays (`retention.py:5-8`, `:30-43`; full order in the [data guide](../data-and-lifecycle/index.md)). It does not make a new run: `perf_runs` does not list it (`tests/test_analysis.py:333`, not run) |

Back to the [index](./index.md).
