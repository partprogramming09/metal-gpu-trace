# Architecture

**Reader:** people who change the code. Reviewed 2026-11-12.

## Why it is shaped this way

The server has to run on a fresh Mac with nothing but the `python3` macOS ships, so it is standard library only
([ADR-0003](adr/0003-python-3-9-floor.md)). It speaks two MCP eras at once ([ADR-0002](adr/0002-dual-era-mcp.md)).
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
| 6 | `http_transport` | `POST /mcp` on 127.0.0.1 with a bearer token, and the panel pages |
| 5 | `protocol` | One JSON-RPC request in, one reply out; picks the era, checks `_meta`, decorates results |
| 4 | `worker` | One tool call at a time, cancel, progress |
| 3 | `registry` | Tool list and schemas, resources, prompts |
| 2 | `recording` | Records a run (`perf_record`, `perf_attach`) |
| 2 | `analysis` | Runs, compare, baselines, checks, gates, diagnose |
| 2 | `experiments` | A/B, cold/warm, sweeps |
| 2 | `workloads` | Test programs, downloads, PresentMon |
| 2 | `traces` | `.trace` and `.gputrace` files, GPU families |
| 2 | `panel` | The HTML panel: builds its data (`panel_data`) and writes the saved page |
| 1 | `paths` | Names and paths a caller may use, paging, reading a file of the runs folder |
| 1 | `project` | The `metal-gpu-trace.json` project file: finds it, checks it, points the recordings folder at it |
| 0 | `config` | Settings, read as `config.NAME` at use time |
| 0 | `logs` | One stderr line per tool call |
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
2. `protocol.handle` checks the era, the `_meta` and that the tool exists.
3. The call waits in the worker queue (at most `MAX_QUEUE` waiting).
4. The worker thread runs the tool from `registry`. Right before, it stops with the project file's error if that file is wrong (`project.check`).
5. `protocol` decorates the result for its era and the transport writes the reply.

## Where recordings live, and what reads them

Think of the runs folder as one drawer per project: everything about a project (its recordings, its `baselines.json`,
its `panel.json`) is in its own drawer, so one project's clean-up never touches another's.

- **Which drawer.** `main()` calls `project.apply()` once at start-up (also for `metal-gpu-trace check`). It looks for
  `metal-gpu-trace.json` from the working directory upwards, or where `METAL_TRACE_PROJECT` points, validates it, and
  sets `config.OUT`, `config.READ[0]` and `config.BASELINES` to the project's `runs` folder; the parsed file stays in
  `config.PROJECT`. Without a file, `METAL_TRACE_OUT` decides, as before. A wrong file does not stop the server: its
  message goes to `config.PROJECT_ERROR` and every tool answers with it. Why a file per repository and not a central
  list: [ADR-0004](adr/0004-project-file.md). `project` sits in layer 1 beside `paths` because `config` and `paths` are
  all it needs and the tools above read what it set.
- **What counts as a recording.** A `.json` in the runs folder, except `baselines.json` and `panel.json`
  (`paths.LAYOUT_FILE`); `paths.run_path` and `perf_runs` skip both. Names are at most 120 characters
  (`paths.name_ok`), because each recording adds suffixes to its file names.
- **How a file is read.** Summaries go through `paths.read_object` and the per-frame and memory CSVs through
  `analysis._csv_rows`. A truncated or malformed file becomes a `ToolError` that names the file (such as `<run>.json`) and never a path;
  a CSV line that cannot be read, or that holds a value that is not finite, is left out instead of failing the whole read.
- **One recording at a time, everywhere.** The lock is not per project: `config.LOCK` (`recording.lock` in the user's
  cache folder, moved by `METAL_TRACE_LOCK`; `PERF_LOCK` for `perf_record.sh` run by hand) is taken by every recording,
  because two programs sharing the GPU spoil both measurements whatever folder they write to.

## The panel

`panel.panel_data` decides everything the page shows and `data/panel.html` only draws it; the saved file
(`perf_panel`) and the live page (`http_transport`, `/panel` and `/panel/data`) use the same data. It is built from the
recordings' summaries (and CSVs), the project and `panel.json`:

- `runs`: each recording's numbers and curves, with `has` (which sections it has data for) and `missing` (why each other
  one is missing: Metal-only, recorded without counters, cut by `skip_s`, or not in the recording). A recording without
  its `.frames.csv` is accepted and has no curves.
- `project` and `primary`: the project's `profile` decides the main metric: `gpu_ms_mean` for `translation-layer`,
  `fps` for `native` and `generic`.
- `tests` and `changes`: when the project names a `baseline`, `tests_mode` asks `analysis.tool_perf_check` for each run's
  verdict (the same rule and margin as the tool) and `changes_against` sets the newest builds of the same program
  against the reference's mean. Without a reference, or with one that cannot be read, `tests` is null and `tests_hint`
  says why; the rest of the page still draws.
- `warnings`: confidence notes, each once (few frames, short Wine run, a single run each, different layers, and so on).
- `layout`: the order and visibility of the sections from `panel.json`; `tests` is a section like the others, first by
  default, and a `panel.json` written before it existed stays valid.

`perf_panel` checks everything before it writes: a call that fails changes nothing on disk, and it refuses to write over a
symbolic link. Numbers that JSON cannot hold (NaN, infinity) become `null`.

## Where the facts are pinned

- `tests/golden/protocol.json`: the replies to a fixed list of messages in both eras.
- `tests/golden/metrics.json`: the summary numbers from fixed inputs.
- `tests/conformance/`: the official MCP SDK as an outside client (stdio both eras, HTTP modern era).

Key points:
- Imports only go down the layer table; the test says which one went up.
- The worker is the only place tool calls run; transports never run tools themselves.
- A change in replies or numbers shows up as a diff in `tests/golden/`.
