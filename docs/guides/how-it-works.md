# How it works

**Reader:** people who change the code. Reviewed 2026-11-15.

**In short:** the server is plain Python, speaks two MCP versions at once and runs one tool call at a time on a worker thread, while the transport keeps listening so a recording can be cancelled.

## Why it is shaped this way

The server has to run on a fresh Mac with nothing but the `python3` macOS ships, so it is standard library only
([ADR-0003](../adr/0003-python-3-9-floor.md)). It speaks two MCP eras at once ([ADR-0002](../adr/0002-dual-era-mcp.md)).
And a recording takes 30 seconds or more, so tool calls run one at a time on a worker thread while the transport
keeps reading messages (to cancel, or to answer `tools/list` meanwhile).

Think of it as a small restaurant: the transport is the waiter, `protocol` reads the order, the `worker` is the one
cook who makes one dish at a time, and the domain modules are the recipes.

## Layers

Each module may import only modules in its own layer or a lower one. `tests/test_architecture.py` holds the same
table (`LAYERS`) and fails when an import goes upward.

From the top (the entry point) to the bottom (what everything else rests on):

| Layer | Module | What it does |
|---|---|---|
| 7 | `metal_trace_mcp` | Entry point: `INSTRUCTIONS`, version, `main()`; configures `protocol` and `worker`; applies the project file at start-up |
| 6 | `stdio` | Newline-delimited JSON-RPC on stdin and stdout |
| 6 | `http_transport` | `POST /mcp` on 127.0.0.1 with a bearer token |
| 5 | `protocol` | One JSON-RPC request in, one reply out; picks the era, checks `_meta`, decorates results |
| 4 | `worker` | One tool call at a time, cancel, progress |
| 3 | `registry` | Tool list and schemas, resources, prompts (`compare-layer`, `diagnose-stutter`, `bisect-regression`: text for the agent; the server runs no command) |
| 2 | `recording` | Records a run (`perf_record`, `perf_attach`) and writes its `context` |
| 2 | `bench_import` | `metal-gpu-trace import-bench`: turns a VegaFlow `bench.ps1` result into a summary the readers list and compare (only the jitter is shared; the other numbers keep their own names) |
| 2 | `preflight` | What a recording needs, checked before any process starts: program, Wine, `xcrun`, disk, screen, lock |
| 2 | `analysis` | Runs, compare, baselines, checks, gates, diagnose |
| 2 | `experiments` | A/B, cold/warm, sweeps |
| 2 | `workloads` | Test programs, downloads, PresentMon |
| 2 | `traces` | `.trace` and `.gputrace` files (`trace_query` with `window_ms`, `capture_diff`), GPU families |
| 2 | `screenshots` | PNG screenshots of a run: black, flat, frozen or flickering (`screenshots_check`) |
| 1 | `retention` | Keeps the runs folder under `METAL_TRACE_MAX_DISK_MB`: removes the oldest heavy files, never a summary or a link's target |
| 1 | `paths` | Names and paths a caller may use, paging, reading a file of the runs folder |
| 1 | `project` | The `metal-gpu-trace.json` project file: finds it, checks it, points the recordings folder at it |
| 0 | `fingerprint` | A short hash of the files a run is declared to use, and the names (never the values) of its variables |
| 0 | `config` | Settings, read as `config.NAME` at use time |
| 0 | `logs` | One stderr line per tool call |
| 0 | `fingerprint` | A short hash of the files a run is declared to use, and the names (never the values) of its variables |
| 0 | `tables` | Reads and writes the per-frame and Metal memory tables, `.csv.gz` or the plain `.csv` of older recordings |
| 0 | `tabledb` | The `<run>.tables.sqlite` file: writes the tables a summary reads, reads them back through declarative filters ([ADR-0007](../adr/0007-sqlite-tables-beside-the-compressed-tables.md)) |
| 0 | `metrics` | Numbers that Mac and Windows summaries share |
| 0 | `perf_report` | Summarizes a `.trace` (also a script) |
| 0 | `perf_record_windows` | Windows recording (also a script) |
| 0 | `gputrace_read` | Reads a `.gputrace` (also a script) |

`perf_record.sh` (zsh) drives Instruments and calls `perf_report.py`; `src/metal_gpu_trace/data/` holds the GPU
family facts and the workload list.

## Two rules that keep it testable

1. **Import modules, not names:** `from metal_gpu_trace import config`, then `config.OUT`. A test patches one
   attribute and every reader sees it. The architecture test rejects `from metal_gpu_trace.config import OUT`.
2. **Inject upward dependencies:** `protocol` needs the entry point's `INSTRUCTIONS` and version, and `worker` needs
   the transport's `send` and the protocol's `answer` and `finish`; both sit below what they need, so
   `metal_trace_mcp` passes them in with `protocol.configure(instructions, version)` and
   `worker.configure(send, answer, finish)`. Both raise a clear error if used before that.

## One request, end to end

1. The client sends `tools/call` and the transport reads one JSON message.
2. The transport puts the raw message in the worker queue (at most `MAX_QUEUE` waiting): `stdio.py::serve_stdio`, `http_transport.py::do_POST`. Messages that are not tool calls (`ping`, `tools/list`, notifications) skip the queue and go straight to `protocol.handle`.
3. On the worker thread, `protocol.handle` checks the era, the `_meta` and that the tool exists.
4. Still on the worker thread, the tool runs from `registry`. Right before, it stops with the project file's error if that file is wrong (`project.check`).
5. `protocol` decorates the result for its era and the transport writes the reply.

The [Server and transport](./server-and-transport/) guide follows this path line by line.

## Where recordings live, and what reads them

Think of the runs folder as one drawer per project: everything about a project (its recordings and its `baselines.json`) is in its own drawer, so one project's clean-up never touches another's.

- **Which drawer.** `main()` calls `project.apply()` once at start-up (also for `metal-gpu-trace check`). It looks for
  `metal-gpu-trace.json` from the working directory upwards, or where `METAL_TRACE_PROJECT` points, validates it, and
  sets `config.OUT`, `config.READ[0]` and `config.BASELINES` to the project's `runs` folder; the parsed file stays in
  `config.PROJECT`. Without a file, `METAL_TRACE_OUT` decides, as before. A wrong file does not stop the server: its
  message goes to `config.PROJECT_ERROR` and every tool answers with it. Why a file per repository and not a central
  list: [ADR-0004](../adr/0004-project-file.md). `project` sits in layer 1 beside `paths` because `config` and `paths` are
  all it needs and the tools above read what it set.
- **What counts as a recording.** A `.json` in the runs folder, except `baselines.json` and the `panel.json` that 0.24.0 and older left
  (`paths.LAYOUT_FILE`); `paths.run_path` and `perf_runs` skip both. Names are at most 120 characters
  (`paths.name_ok`), because each recording adds suffixes to its file names.
- **How a file is read.** Summaries go through `paths.read_object` and the per-frame and memory tables through
  `tables` (`find` looks for `<run>.frames.csv.gz` first and `<run>.frames.csv` second; `open_text` reads either;
  `write` writes the compressed one, byte for byte the same for the same rows), read by `analysis._csv_rows` and
  `traces.tool_perf_export_trace`. A summary without `schema_version` is generation 1 (`metrics.schema_of`). Generation 3 adds `common`, built by `metrics.common_block` for both engines: `frame_pacing` and `memory_pressure` (each with its `source`), `api` (`runtime`, `translation_layer`), and `boundness` and `submission_overhead` as `comparable: false` until both platforms measure them alike. The keys each backend already had stay where they are. `perf_compare` subtracts memory peaks only when both runs measured the same thing. A truncated or malformed file becomes a `ToolError` that names the file (such as `<run>.json`) and never a path;
  a CSV line that cannot be read, or that holds a value that is not finite, is left out instead of failing the whole read.
- **The program's own numbers.** `record_run` points the program at a private CSV file through `METAL_TRACE_APP_METRICS`;
  `recording.finish` reads it with `app_metrics.safe_read` into the summary's `app_metrics` (top level, never comparable)
  and the folder is removed whatever happened. Details: [Program telemetry](./recording/macos-journey.md#program-telemetry).
- **Where a run came from.** `recording.run_context` adds `context` to each new summary: the 12-character commit and the
  dirty flag of the repository that holds the project file (`null` without a project file or a git repository) and
  Instruments' version. It drops the `GIT_*` variables before running git, so they cannot point at another repository,
  and leaves out the branch. `perf_compare` returns `context` (`same`, different, unknown, or missing for a run from
  before 0.26.0).
- **Long tables and captures.** `trace_query` with `window_ms` sums a table by time window (`traces.windows_of`) instead
  of returning rows; `capture_diff` counts the confirmed Metal calls of two `.gputrace` captures with
  `gputrace_read.diff`, matching debug groups by label.
- **Disk limit.** `record_run` ends through `recording.finish` (both the macOS and the Windows branch), which calls
  `retention.prune_to_quota` when `config.MAX_DISK_MB` is set and notes what it removed in the summary's `retention`. It
  measures with `lstat`, never follows a link and removes one with `unlink`. Why and at what cost:
  [ADR-0006](../adr/0006-compressed-tables-and-disk-quota.md).
- **Before a recording.** `recording.record` calls `preflight.check` before it starts `memory_pressure`, so a doomed run
  starts nothing. The lock is read without following a link and without blocking; on Windows `os.kill` is never used
  (it ends the process there), `perf_record_windows.is_process_alive` is. `perf_record.sh` repeats the program, disk and
  lock checks; only the locked screen is checked just here (`METAL_TRACE_ALLOW_LOCKED=1` allows it).
- **What to do next.** `analysis.suggested_actions` turns a summary into `{tool, arguments, reason}` items (shown by
  `perf_diagnose` and `perf_compare`); `recording.cooldown` rests between recordings of `perf_baseline_record`,
  `perf_ab` and `perf_sweep`; `perf_report.noisy_environment` compares the GPU's total use (`gpu_activity`) with the
  program's own busy share (`gpu_idle`) and flags a gap of 20 points or more, a provisional threshold.
- **Capture tiers.** `recording.resolve_tier` turns `tier` (`light`, `standard`, `deep`) into memory, counters and
  keep-trace; a `memory` or `counters` passed on its own wins. The summary keeps the `tier`.
- **One recording at a time, everywhere.** The lock is not per project: `config.LOCK` (`recording.lock` in the user's
  cache folder, moved by `METAL_TRACE_LOCK`; `PERF_LOCK` for `perf_record.sh` run by hand) is taken by every recording,
  because two programs sharing the GPU spoil both measurements whatever folder they write to.

## Where the facts are pinned

- `tests/golden/protocol.json`: the replies to a fixed list of messages in both eras.
- `tests/golden/metrics.json`: the summary numbers from fixed inputs.
- `tests/conformance/`: the official MCP SDK as an outside client (stdio both eras, HTTP modern era).

Key points:
- Imports only go down the layer table; the test says which one went up.
- The worker is the only place tool calls run; transports never run tools themselves.
- A change in replies or numbers shows up as a diff in `tests/golden/`.
