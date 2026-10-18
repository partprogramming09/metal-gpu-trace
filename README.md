# metal-gpu-trace

[![test](https://github.com/partprogramming09/metal-gpu-trace/actions/workflows/test.yml/badge.svg)](https://github.com/partprogramming09/metal-gpu-trace/actions/workflows/test.yml)

<!-- mcp-name: io.github.partprogramming09/metal-gpu-trace -->

Measure how a Wine or macOS program uses the GPU on an Apple silicon Mac, from the command line or through an AI
coding agent: GPU time per frame, frame pacing, FPS and memory, recorded with Instruments' Metal System Trace; whether
a translation layer (DXMT, Mullion, MoltenVK) splits the work into too many short encoders; Metal
`.gputrace` captures read without Xcode; and Apple's published facts on each GPU family to read the numbers against.
Python 3.9+ standard library, `zsh`, and Xcode (for `xctrace`). MIT license. [Español](es/README.md).

| File | What it does |
| --- | --- |
| `perf_record.sh` | Records a program for N seconds with Metal System Trace and writes `<label>_<date>.json` (GPU ms per frame, frame intervals, FPS, Metal and resident memory) plus per-frame and memory CSVs. Deletes the `.trace` afterwards unless `KEEP_TRACE=1`. |
| `perf_report.py` | Summarizes an existing `.trace` the same way. |
| `gputrace_read.py` | Reads a Metal `.gputrace` capture without Xcode: command buffers, encoders, draws, debug groups. Call names marked `probable` are not confirmed. |
| `data/apple-gpu-families.json` | Apple7 to Apple10: chips, what each family adds, limits that differ, with Apple's sources. |
| `metal_trace_mcp.py` | An MCP server over all of the above. |
| `test_metal_trace_mcp.py` | Self-check without Instruments: `python3 -I test_metal_trace_mcp.py` prints `ok`; `pytest` runs the same tests. |

## Recording

```sh
PERF_OUT=~/perf-runs zsh perf_record.sh game-d3d12 30 /path/to/wine ~/.wine /path/to/game game.exe
PERF_OUT=~/perf-runs zsh perf_record.sh app-metal 30 native - /path/to/app ./app
```

Arguments: label, seconds, a Wine directory holding `bin/wine` (or `native`), the Wine prefix, the working directory,
the program and its arguments. Without `PERF_OUT`, runs go to `./perf-runs`. Reading the trace afterwards takes about
a minute on an M1 Pro (87 s for a 10 s recording); through the MCP server the whole call times out after 10 s per
recorded second plus 120 s, and an overrun recording leaves no files behind. One recording runs at a time; keep other GPU work off the Mac while it records.

Under Wine, give it 30 s: Wine's start-up takes part of the recording. A recording with under 100 frames is too short
to compare.

## Disk use

Each recording keeps a JSON summary and three CSVs, about 2 MB for 10 s (most of it the Metal memory samples). The
`.trace` (tens to hundreds of MB) is deleted unless `KEEP_TRACE=1`. `KEEP_RUNS=N` keeps only the newest N recordings.

## MCP server

### Install

The server runs with [`uvx`](https://docs.astral.sh/uv/) from [PyPI](https://pypi.org/project/metal-gpu-trace/), with nothing to clone
(`brew install uv` installs it). Recording also needs Xcode installed (`xcrun xctrace version` prints a version).

```sh
uvx metal-gpu-trace
```

This is the command each client below runs. Desktop apps do not see Homebrew's `PATH`: give them the full path that
`which uvx` prints (`/opt/homebrew/bin/uvx` on Apple silicon). `uvx` keeps the version it first downloaded; run
the command once with `--refresh` after `uvx` to get the latest. `uvx metal-gpu-trace@0.4.0` pins a version.

The server reads these environment variables:

| Variable | What it sets |
| --- | --- |
| `METAL_TRACE_OUT` | Where recordings go. Give an absolute path: the default, `./perf-runs`, depends on the client's working directory. |
| `METAL_TRACE_WINE` | The Wine directory (holding `bin/wine`) that `perf_record` uses when the call names none. |
| `WINEPREFIX` | The Wine prefix used when the call names none; `~/.wine` otherwise. |
| `METAL_TRACE_READ` | More directories the tools may read, separated by `:`. |
| `METAL_TRACE_LOG` | `off` silences the one-line stderr log per call. |
| `KEEP_TRACE` | `1` keeps each recording's `.trace`, for `trace_tables`, `trace_query` or Instruments. |
| `KEEP_RUNS` | Keeps only the newest N recordings. |
| `PERF_ENV` | `NAME=VALUE` pairs, separated by spaces, set for the recorded program. |

### Claude Code

```sh
claude mcp add --scope user metal-trace -e METAL_TRACE_OUT=$HOME/perf-runs -e METAL_TRACE_WINE=/path/to/wine \
  -- uvx metal-gpu-trace
claude mcp list
```

`claude mcp list` shows `metal-trace` as connected. `--scope user` makes it available in every project; leave it out
to add it to the current project only.

### Claude Desktop, Cursor and other JSON clients

These apps do not expand `~` or `$HOME`: write absolute paths.

```json
{
  "mcpServers": {
    "metal-trace": {
      "command": "/opt/homebrew/bin/uvx",
      "args": ["metal-gpu-trace"],
      "env": {
        "METAL_TRACE_OUT": "/absolute/path/to/perf-runs",
        "METAL_TRACE_WINE": "/absolute/path/to/wine"
      }
    }
  }
}
```

| Client | File |
| --- | --- |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (Settings, Developer, Edit Config); restart the app |
| Cursor | `~/.cursor/mcp.json` |
| VS Code | `.vscode/mcp.json` in the project; the top key is `servers` instead of `mcpServers`, and the server adds `"type": "stdio"` |

### Codex CLI

In `~/.codex/config.toml`:

```toml
[mcp_servers.metal-trace]
command = "/opt/homebrew/bin/uvx"
args = ["metal-gpu-trace"]
env = { METAL_TRACE_OUT = "/absolute/path/to/perf-runs", METAL_TRACE_WINE = "/absolute/path/to/wine" }
```

### Tools

| Tool | Reads or records |
| --- | --- |
| `perf_record` | Records a program and returns its summary; when it ends it stops every program of its Wine prefix, or every process named like a native program |
| `perf_attach` | Records a program that is already running, by pid or name, and leaves it running |
| `perf_runs` | Lists recordings, newest first, one page at a time, whether each kept its `.trace`, and the translation layer it ran on (a fingerprint of its Direct3D DLLs, and its Wine) |
| `perf_compare` | Compares two recordings: headline numbers, encoders, GPU idle time and each encoder label's GPU ms per frame, largest change first; flags those under 100 frames |
| `perf_baseline` | Saves several equal recordings as a named reference and returns the range each number spans across them; alone, lists the references |
| `perf_check` | Judges a recording against a reference: `regressed` when FPS falls under the range by more than `margin_pct` (default 3), GPU ms per frame rises over it, or encoders or command buffers per frame exceed it; `improved` or `same` otherwise, with the reasons and the full comparison |
| `perf_diagnose` | Says whether a recording splits its GPU work into too many short encoders, as translation layers do, with encoders and command buffers per frame, the labels with the most GPU time and the GPU's idle time |
| `trace_tables` | Lists the tables of a kept `.trace`, named by its run or its path |
| `trace_query` | One page of rows of one table, optionally one process |
| `capture_summary` | Summarizes a `.gputrace`; lists its 100 most frequent calls out of `calls_total` |
| `capture_records` | One page of a `.gputrace`'s records |
| `gpu_family` | Apple's facts for a family or chip (`Apple7`, `M1 Pro`, `M3 Max`) |
| `workload_list` | Lists the test programs `workload_fetch` can download |
| `workload_fetch` | Downloads a test program once, checks its SHA-256 and keeps it in `~/Library/Caches/metal-gpu-trace`; Claude Code asks before every call |

`perf_record` takes `workload`, `api` (`mtl`, `d3d11` or `d3d12`) and `dim` instead of `program`, to record a fetched
test program. The first one is bgfx's
[17-drawstress](https://github.com/partprogramming09/metal-gpu-trace/releases/tag/workloads-1) (BSD-2, 7.5 MB),
built from source by `.github/workflows/workloads.yml`: a grid of cubes, `dim`³ draws per frame, with its shaders
inside the program. The `compare-layer` prompt (`/metal-trace:compare-layer drawstress d3d12` in Claude Code) records it
in native Metal and under the Wine in `METAL_TRACE_WINE`, then runs `perf_diagnose` and `perf_compare`.

The same facts are MCP resources: `metal-trace://gpu-families` (all) and `metal-trace://gpu-families/apple7` to
`apple10`. They restate Apple's [Metal Feature Set Tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf)
of 21 May 2026, [`MTLGPUFamily`](https://developer.apple.com/documentation/metal/mtlgpufamily) and the
[M3 tech talk](https://developer.apple.com/videos/play/tech-talks/111375/); check a device with `supportsFamily`.

How it follows the [MCP specification](https://modelcontextprotocol.io/specification/2025-06-18) and
[Claude Code's limits](https://code.claude.com/docs/en/mcp):

- stdout carries only MCP messages; each tool call logs one line to stderr (`METAL_TRACE_LOG=off` silences it), with
  no arguments or paths.
- Lists come in pages (`offset`, `limit`, default 50, at most 500) with `total` and `next_offset`; a result over
  40 000 characters is refused with a hint to ask for a smaller page.
- Files are read only inside `METAL_TRACE_OUT` and the directories in `METAL_TRACE_READ` (separated by `:`).
- Failures come back as `isError` results that say what to do, without stack traces or local paths. Summaries cut
  absolute paths to file names, so they can be shared.
- Every `xctrace` call has a timeout.

## Credits

- The record layout of a `.gputrace` command stream follows [tmc/gputrace](https://github.com/tmc/gputrace) (MIT); no
  code is copied. The call ids were matched against Xcode's command list on macOS 27.0.1.
- GPU family facts: Apple's documents linked above, restated, not quoted.
