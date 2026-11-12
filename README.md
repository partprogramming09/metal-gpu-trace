# metal-gpu-trace

[![test](https://github.com/partprogramming09/metal-gpu-trace/actions/workflows/test.yml/badge.svg)](https://github.com/partprogramming09/metal-gpu-trace/actions/workflows/test.yml)

<!-- mcp-name: io.github.partprogramming09/metal-gpu-trace -->

Measure how a Wine or macOS program uses the GPU on an Apple silicon Mac, from the command line or through an AI
coding agent: GPU time per frame, frame pacing, FPS and memory, recorded with Instruments' Metal System Trace; whether
a translation layer (DXMT, Mullion, MoltenVK) splits the work into too many short encoders; Metal
`.gputrace` captures read without Xcode; and Apple's published facts on each GPU family to read the numbers against.
Python 3.9+ standard library, `zsh`, and Xcode (for `xctrace`). MIT license. [Español](es/README.md).

Architecture, decisions and guides: [`docs/README.md`](docs/README.md). Sending a change: [`CONTRIBUTING.md`](CONTRIBUTING.md).

| File | What it does |
| --- | --- |
| `src/metal_gpu_trace/perf_record.sh` | Records a program for N seconds with Metal System Trace and writes `<label>_<date>.json` (GPU ms per frame, frame intervals, FPS, Metal and resident memory) plus per-frame and memory CSVs. Deletes the `.trace` afterwards unless `KEEP_TRACE=1`. |
| `src/metal_gpu_trace/perf_report.py` | Summarizes an existing `.trace` the same way. |
| `src/metal_gpu_trace/gputrace_read.py` | Reads a Metal `.gputrace` capture without Xcode: command buffers, encoders, draws, debug groups. Call names marked `probable` are not confirmed. |
| `src/metal_gpu_trace/data/apple-gpu-families.json` | Apple7 to Apple10: chips, what each family adds, limits that differ, with Apple's sources. |
| `src/metal_gpu_trace/metal_trace_mcp.py` | An MCP server over all of the above. |
| `tests/` | Self-check without Instruments: `python3 -I tests/run.py` prints `ok`; `pytest tests` runs the same tests. |

## Recording

```sh
PERF_OUT=~/perf-runs zsh src/metal_gpu_trace/perf_record.sh game-d3d12 30 /path/to/wine ~/.wine /path/to/game game.exe
PERF_OUT=~/perf-runs zsh src/metal_gpu_trace/perf_record.sh app-metal 30 native - /path/to/app ./app
```

Arguments: label, seconds, a Wine directory holding `bin/wine` (or `native`), the Wine prefix, the working directory,
the program and its arguments. Without `PERF_OUT`, runs go to `./perf-runs`. Reading the trace afterwards takes about
a minute on an M1 Pro (87 s for a 10 s recording); through the MCP server the whole call times out after 10 s per
recorded second plus 120 s, and an overrun recording leaves no files behind. One recording runs at a time; keep other GPU work off the Mac while it records.

Under Wine, give it 30 s: Wine's start-up takes part of the recording. A recording with under 100 frames is too short
to compare.

## Disk use

Each recording keeps a JSON summary and three CSVs, about 2 MB for 10 s (most of it the Metal memory samples). The
`.trace` (tens to hundreds of MB) is deleted unless `KEEP_TRACE=1`. `KEEP_RUNS=N` keeps only the newest N recordings. `PERF_MEMORY=0` skips the Metal memory table, the slowest to read:
the summary then has no `metal_memory_mib` and there is no memory CSV (41 % faster to summarize a 626 MB trace).
The MCP tools `perf_record` and `perf_baseline_record` offer the same as `memory=false`.

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
| `METAL_TRACE_OUT` | Where recordings go. Give an absolute path: the default, `./perf-runs`, depends on the client's working directory. A project file (below) takes precedence. |
| `METAL_TRACE_PROJECT` | The project file to use (or the folder holding it), instead of looking for one from the working directory. |
| `METAL_TRACE_WINE` | The Wine directory (holding `bin/wine`) that `perf_record` uses when the call names none. |
| `WINEPREFIX` | The Wine prefix used when the call names none; `~/.wine` otherwise. |
| `METAL_TRACE_READ` | More directories the tools may read, separated by `:`. |
| `METAL_TRACE_LOG` | `off` silences the one-line stderr log per call. |
| `KEEP_TRACE` | `1` keeps each recording's `.trace`, for `trace_tables`, `trace_query` or Instruments. |
| `KEEP_RUNS` | Keeps only the newest N recordings; `baselines.json` and `panel.json` are never removed. |
| `METAL_TRACE_LOCK` | The lock that keeps recordings one at a time, whatever folder each goes to (default `~/Library/Caches/metal-gpu-trace/recording.lock`). `perf_record.sh` run by hand takes the same one, or the one `PERF_LOCK` names. |
| `PERF_ENV` | `NAME=VALUE` pairs, separated by spaces, set for the recorded program. |
| `PERF_INSTRUMENTS` | Instruments added to the Metal System Trace template, separated by `;` (`xcrun xctrace list instruments` names them); their tables need the `.trace`, so pair it with `KEEP_TRACE=1`. |

### Projects

A repository can hold a `metal-gpu-trace.json` that names its project and the folder of its recordings:

```json
{"name": "my-game", "runs": "perf-runs", "profile": "translation-layer", "baseline": "main-ref"}
```

The server looks for it in its working directory and the folders above it, stopping below the home folder, so one
file at a repository's root serves every folder inside it. When it finds one, recordings go to and are read from
`runs` instead of `METAL_TRACE_OUT` (`METAL_TRACE_READ` still adds folders to read), and `baselines.json` lives there too: projects no longer mix their recordings, and `KEEP_RUNS` prunes
each project's folder on its own. `runs` is relative to the file, starts with `~/`, or is absolute.

| Key | Meaning |
| --- | --- |
| `name` | The project's name (letters, digits, `.`, `_`, `-`). Required. |
| `runs` | The recordings folder. Required. It must be new, empty or already marked by the server (a plain `.metal-gpu-trace-runs` file, not a folder or a link): `KEEP_RUNS` removes old `.json` files there, so a folder holding other files is refused. |
| `profile` | `translation-layer`, `native` or `generic` (the default). For now `project_info` only reports it. |
| `baseline` | The name of the project's reference (`perf_baseline`). For now `project_info` only reports it; `perf_check` still takes the reference it is given. |
| `format` | `metal-gpu-trace`, the only one for now. |

Any other key, or a wrong value, is an error that every tool reports, naming the field, until the file is fixed.
`project_info` says which project is active and where its folder comes from. Without a project file nothing changes:
`METAL_TRACE_OUT`, or `./perf-runs`, is used as before.

### Claude Code

```sh
claude mcp add --scope user metal-trace -e METAL_TRACE_OUT=$HOME/perf-runs -e METAL_TRACE_WINE=/path/to/wine \
  -- uvx metal-gpu-trace
claude mcp list
```

`claude mcp list` shows `metal-trace` as connected. `--scope user` makes it available in every project; leave it out
to add it to the current project only.

### Windows

On Windows the server records native programs (`src/metal_gpu_trace/perf_record_windows.py`); no Wine and no Metal. `METAL_TRACE_WINE` is not needed: `perf_record` and `perf_attach` use `native`. `METAL_TRACE_READ` is separated by `;`.

Frames come from Intel's [PresentMon](https://github.com/GameTechDev/PresentMon) console application (MIT): one row per `Present()` of the process, with `MsBetweenPresents` and the GPU time `MsGPUTime`. Download `PresentMon-<version>-x64.exe` from its releases, check its SHA-256 against the one GitHub shows, and call the `presentmon_install` tool, or put it in `%LOCALAPPDATA%\metal-gpu-trace` or on `PATH`, or point `PRESENTMON_EXE` at it. The user must be an administrator or in the "Performance Log Users" group. Without PresentMon the summary falls back to DWM composition intervals (`gpu.source` is `dwm-composition`): they cover the whole desktop, miss games in exclusive full screen, and carry no GPU time. With neither a frame log, PresentMon nor DWM samples, a recording fails; it never invents frames.

What cannot be measured is `null`, not zero: the 1% low needs 100 frames and the 0.1% low 1000; stutter rate and jitter need two frames; `thermal_throttling_detected` needs GPU times; a drawstress log holds one mean per line, so its summary (`gpu.frame_times`) has no frame-level percentiles, stutter or jitter. DWM keeps only intervals between consecutive composed frames and drops a jump of several frames. `perf_diagnose` calls a large working set with uneven frame times `MEMORY_PRESSURE_SUSPECTED`: a suspicion, since memory bandwidth is not measured.

```powershell
winget install --id=astral-sh.uv -e
claude mcp add --scope user metal-trace -e METAL_TRACE_OUT=%USERPROFILE%\perf-runs -- uvx metal-gpu-trace
claude mcp list
```

To run from a clone instead of PyPI (needs Python 3.9 or newer):

```powershell
claude mcp add --scope user metal-trace -e METAL_TRACE_OUT=%USERPROFILE%\perf-runs -- python C:\path\to\metal-gpu-trace\src\metal_gpu_trace\metal_trace_mcp.py
```

In JSON clients use `"command": "uvx"` (or the full path `where uvx` prints) and Windows paths with doubled backslashes. Claude Desktop reads `%APPDATA%\Claude\claude_desktop_config.json`. Run the Windows tests with `python -m pytest tests/test_perf_record_windows.py`.

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
| `perf_record` | Records a program and returns its summary; when it ends it stops every program of its Wine prefix, or every process named like a native program. `counters=true` also records Metal GPU Counters: `gpu_counters` (the limiters, utilization, occupancy and memory bandwidth of the GPU, with the main limiter) in the summary, at about 40 s of read-back per recorded second; not under Windows |
| `perf_attach` | Records a program that is already running, by pid or name, and leaves it running |
| `project_info` | Says which project is active (from `metal-gpu-trace.json`), its profile and baseline, and its recordings folder and where that comes from |
| `perf_runs` | Lists recordings, newest first, one page at a time, whether each kept its `.trace`, and the translation layer it ran on (a fingerprint of its Direct3D DLLs, and its Wine); `project` names the active project |
| `perf_compare` | Compares two recordings: headline numbers, encoders, GPU idle time and each encoder label's GPU ms per frame, largest change first; flags those under 100 frames. `markdown=true` adds the numbers as Markdown tables for a PR comment; `skip_s` leaves out the first seconds of each recording (start-up) and recomputes the GPU numbers, hitches and Metal memory without them. `perf_gate` and `perf_panel` take `skip_s` too |
| `perf_baseline` | Saves several equal recordings as a named reference and returns the range each number spans across them and `spread_pct`, how much equal runs differ (the noise a change must beat); alone, lists the references. `skip_s` saves each run without its first seconds and `perf_check` applies the same cut to the run it judges |
| `perf_baseline_record` | Records the same program `count` times (default 3) with `perf_record`'s arguments and saves the runs as a reference in one call. `skip_s` as in `perf_baseline` |
| `perf_cold_warm` | Records the same program twice in a row and says how many more shader-compile hitches the first run has than the second (`first_seen_hitches`), with each run's hitches, hitches per minute and graphics compiler time; the Metal shader cache is not cleared between them |
| `perf_ab` | Records the same program with two environments (`env_a`, `env_b`: `NAME=VALUE` pairs) in the order A B B A and says per metric (FPS, 1 % low, GPU ms, stutter) whether B is better, worse or the same: better or worse only when every B value is outside A's range |
| `perf_sweep` | Records the same program once per value of one variable (`dim`, `size`, `example`, `api` or `env:NAME`), 2 to 8 values, `rounds` times (every other round in reverse order), and returns per value the median FPS, 1 % low, GPU ms per frame and stutter; with 3 or more numeric values it fits GPU ms per frame on the value (fixed ms and ms per draw for `dim`) with its r2 |
| `perf_check` | Judges a recording against a reference: `regressed` when FPS falls under the range by more than `margin_pct` (default 3), GPU ms per frame rises over it, or encoders or command buffers per frame exceed it; `improved` or `same` otherwise, with the reasons and the full comparison |
| `perf_gate` | Checks a recording against budgets you set (FPS and 1% low floors; stutter, p95 GPU ms, hitch and Metal MiB ceilings) and returns pass or fail with each limit and value; a missing number fails |
| `perf_history` | Follows FPS, 1% low, GPU ms, stutter, hitches and Metal MiB across the runs whose name starts with a prefix, oldest first, with the change from first to last |
| `perf_panel` | Writes `<name>.panel.html`: a page with GPU time per frame and its hitches, the numbers, Metal memory and, for two runs, A against B. It has no server and loads nothing from the network; the viewer hides or reorders widgets and exports the layout as JSON. With `--http`, `/panel#token=...&runs=a,b` shows it live, refreshed every 10 s. `layout` (tab ids in order) saves `panel.json` in the runs directory as the default tabs of every panel, the live one included; the GPU counters tab shows when a run has them |
| `perf_export_trace` | Writes a recording's GPU frames as `<run>.chrome-trace`, one slice per frame, for ui.perfetto.dev or chrome://tracing |
| `perf_diagnose` | Says whether a recording splits its GPU work into too many short encoders, as translation layers do, with encoders and command buffers per frame, the labels with the most GPU time and the GPU's idle time |
| `trace_tables` | Lists the tables of a kept `.trace`, named by its run or its path |
| `trace_count` | Counts the rows of several tables of a kept `.trace`, in all and per process; by default the tables that matter for a translation layer (GPU intervals, encoders, compiler spills, compiled shaders, allocations, counters, Time Profiler), so an empty one shows before reading it |
| `trace_query` | One page of rows of one table, optionally one process |
| `capture_summary` | Summarizes a `.gputrace`; lists its 100 most frequent calls out of `calls_total` |
| `capture_records` | One page of a `.gputrace`'s records |
| `gpu_family` | Apple's facts for a family or chip (`Apple7`, `M1 Pro`, `M3 Max`) |
| `presentmon_install` | Windows only: downloads PresentMon, checks its pinned SHA-256 and keeps it in `%LOCALAPPDATA%\metal-gpu-trace`, where `perf_record` and `perf_attach` find it; Claude Code asks before every call |
| `workload_list` | Lists the test programs `workload_fetch` can download; for `bgfx-examples`, `example_traits` gives each example's class and its encoders per frame in native Metal |
| `workload_fetch` | Downloads a test program once, checks its SHA-256 and keeps it in `~/Library/Caches/metal-gpu-trace`; Claude Code asks before every call |

`perf_record` takes `workload`, `api` (`mtl`, `mtl-x64`, `vk`, `d3d11` or `d3d12`), `dim`, `size` and `example` instead of
`program`, to record a fetched test program (`workload_list` says what each has). `mtl-x64` is native Metal built for
x86_64 and run under Rosetta, like Wine's programs; `size` (`"1920x1080"`) sets drawstress's window. The first workload is bgfx's
[17-drawstress](https://github.com/partprogramming09/metal-gpu-trace/releases/tag/workloads-3) (BSD-2, 9.3 MB),
built from source by `.github/workflows/workloads.yml`: a grid of cubes, `dim`³ draws per frame, with its shaders
inside the program. The `compare-layer` prompt (`/metal-trace:compare-layer drawstress d3d12` in Claude Code) records it
in native Metal and under the Wine in `METAL_TRACE_WINE`, then runs `perf_diagnose` and `perf_compare`.

The second workload, `bgfx-examples` (55 MiB), holds thirty bgfx examples, each a different load (many cubes, textures,
render-target chains, a G-buffer, compute, reflective shadow maps, post-processing, draws the GPU decides, text and
interface, shadows, transparency, GPU read-back, virtual textures, upscaling, texture formats, occlusion queries, tessellation,
multiple windows, off-screen rendering; the last twenty-one measured in
native Metal and Wine D3D12 only, `example_traits` in `workload_list` gives each one's class and encoders per frame in both,
and 40-svt writes a 370 MB tile cache to `temp/` in the workload's folder on its first run):
`perf_record(workload="bgfx-examples", api="d3d12", example="21-deferred")`. Two macOS levers change the Mac under a
recording: `memory_free_pct` (20 to 60) holds the whole Mac at that percentage of RAM free (`memory_pressure`), and
`background` runs the program under `taskpolicy -b`, a hard throttle. A small GPU-bound program does not feel the first
(drawstress stayed at 728 FPS and its resident memory fell); the second slows it several times over. Repeat a run that
uses either.

The third workload, `godot`, is a lit 3D scene a real engine builds from code (Godot 4.7.2, Forward+): 400 meshes, 8 lights,
a shadowed sun, `api="mtl"` for Godot's Metal driver and `api="d3d12"` under Wine for its Direct3D 12 driver, with
`args="-- meshes=800 lights=16"` to change it. `workload_fetch("godot")` keeps the 10 KB project from this repository's release and
downloads Godot's official macOS (171 MB) and Windows (86 MB) builds from godotengine/godot-builds, checking the SHA-512
this package pins; it needs about 257 MB and some seconds. The scene has no imported assets, so Godot does not import anything.
Godot compiles its pipelines on every start, which makes it a case for `perf_cold_warm`: its shader-compile hitches came back
unchanged in the second run.

### Reading the numbers across runs

- A summary says where it ran and what the GPU did: `machine` (chip, cores, RAM, macOS, `screen_locked`), `gpu_activity`
  (utilization of the device, renderer and tiler, split scenes, GPU recoveries: it covers the whole GPU, not only the
  program), `resource_allocations` (allocation events per frame, by type; a running total, not memory in use) and
  `command_buffer_errors`.
- A locked Mac session leaves native Metal windows unpaced: 3 000 to 4 000 FPS against 120 with vsync, on the same
  examples. Record with the Mac unlocked; `perf_compare` returns `screen` when one run was recorded locked and the other not.
- GPU ms per frame follow the GPU's performance state: a run paced at 120 FPS sits in Minimum and takes more ms for
  the same work (21-deferred: 1.75 ms paced, 0.27 ms unpaced). `perf_compare` returns `gpu_state` when two runs sat in
  different states, and `perf_diagnose` returns `display_synced_hz` when the FPS sits on a display rate. Compare runs paced
  alike: native Metal and D3D12 under Wine with Mullion, both at 120 FPS, do compare.
- With `counters=true`, each listed hitch also has `top_limiter`: the Limiter counter with the highest mean over the interval
  before it (`window_ms`, read in whole 10 ms bins; `null` when no sample falls in it), which can differ from the whole run's
  main limiter.

`api=vk` runs the same program through Vulkan on MoltenVK. MoltenVK is not shipped: set `METAL_TRACE_MOLTENVK` to a
directory (no spaces) holding an arm64 `libMoltenVK.dylib`, such as the one in a Vulkan SDK or `brew install molten-vk`.
The run's `layer` names MoltenVK with the library's SHA-256, so `perf_compare` against a native Metal run says it
compares two layers. In one measurement at `dim=20`, 10 s each: native Metal 2 encoders per frame; MoltenVK 13, 91 % of
them short, and the GPU idle 89 % of the time (`perf_diagnose`: `too_many_short_encoders` true). One pair of runs, not a
benchmark.

`api=vk` is native only. `drawstress.exe --vk` under Wine needs a Wine built with Vulkan: the Wine of DXMT and Apple's
Game Porting Toolkit were tried and both log `Wine was built without Vulkan support`, so the recording holds no GPU
frames. CrossOver's Wine has Vulkan but runs only inside one of its bottles, which was not tried.

The same facts are MCP resources: `metal-trace://gpu-families` (all) and `metal-trace://gpu-families/apple7` to
`apple10`. Each saved run is a resource too: `metal-trace://runs/<run>` reads its summary. They restate Apple's [Metal Feature Set Tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf)
of 21 May 2026, [`MTLGPUFamily`](https://developer.apple.com/documentation/metal/mtlgpufamily) and the
[M3 tech talk](https://developer.apple.com/videos/play/tech-talks/111375/); check a device with `supportsFamily`.

How it follows the MCP specification ([2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25) and
[2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)) and
[Claude Code's limits](https://code.claude.com/docs/en/mcp):

- stdout carries only MCP messages; each tool call logs one line to stderr (`METAL_TRACE_LOG=off` silences it), with
  no arguments or paths.
- Lists come in pages (`offset`, `limit`, default 50, at most 500) with `total` and `next_offset`; a result over
  40 000 characters is refused with a hint to ask for a smaller page.
- Files are read only inside `METAL_TRACE_OUT` and the directories in `METAL_TRACE_READ` (separated by `:`).
- Failures come back as `isError` results that say what to do, without stack traces or local paths. Summaries cut
  absolute paths to file names, so they can be shared.
- Every `xctrace` call has a timeout.

## HTTP

`METAL_TRACE_TOKEN=<secret of 16+ characters> metal-gpu-trace --http [--port N]` serves the same tools at
`POST http://127.0.0.1:8765/mcp` (Streamable HTTP, one JSON reply per request), for a client on the same Mac that cannot
start a stdio server. Every request needs `Authorization: Bearer <token>`. It listens on 127.0.0.1 only, refuses a
request whose Host or Origin is not localhost or 127.0.0.1 (DNS rebinding), and does not start without the token. It
speaks both MCP eras: a client that sends `initialize` gets the behaviour it always had; one that sends
`MCP-Protocol-Version: 2026-07-28` is stateless and must also send `Mcp-Method` (and `Mcp-Name` for `tools/call`,
`prompts/get` and `resources/read`), which the server checks against the body (400 with `-32020` when they differ). A
modern client cancels a running call by closing the connection; an `initialize` client sends `notifications/cancelled`
from another connection. There is no progress stream over HTTP, and no remote access: reach another Mac through an SSH
tunnel (`ssh -L 8765:127.0.0.1:8765 mac`), not by opening the port. Why two eras:
[`docs/adr/0002-dual-era-mcp.md`](docs/adr/0002-dual-era-mcp.md).

## Windows tests on a real machine

GitHub's `windows-latest` has no GPU and no desktop session, so PresentMon and DWM recordings are only tested on a real
Windows machine. `windows/winbridge-run-tests.ps1` updates a checkout there and runs `tests/test_perf_record_windows.py`; it is
written as a [WinBridge](https://github.com/partprogramming09/winbridge) task (fixed name, script pinned by SHA-256, no
arguments). To register it, copy it to the laptop, set `$repo` to the checkout's path, take its hash there with
`Get-FileHash <file> -Algorithm SHA256` (Git may have changed the line endings, so the hash of the copy in this repo is
not the one to use), and add a `[tasks.<name>]` table with `script` and `sha256` to the agent's TOML.

## CI gate

`metal-gpu-trace check RUN BASELINE [--margin-pct N]` runs `perf_check` without a client and prints one JSON line
(verdict, reasons, hints). Exit code 0: same or improved; 1: regressed; 2: could not be judged (no such run or
reference, or under 100 frames). Runs are read from `METAL_TRACE_OUT`. Recording needs Instruments, so the job runs on
a self-hosted macOS runner:

```yaml
jobs:
  perf:
    runs-on: [self-hosted, macOS, ARM64]
    steps:
      - run: PERF_OUT=~/perf-runs zsh path/to/metal-gpu-trace/src/metal_gpu_trace/perf_record.sh pr 30 native - . ./app
      - run: METAL_TRACE_OUT=~/perf-runs metal-gpu-trace check "$(ls -t ~/perf-runs/pr_*.json | head -1 | xargs basename -s .json)" main-ref
```

## Credits

- The record layout of a `.gputrace` command stream follows [tmc/gputrace](https://github.com/tmc/gputrace) (MIT); no
  code is copied. The call ids were matched against Xcode's command list on macOS 27.0.1.
- GPU family facts: Apple's documents linked above, restated, not quoted.
