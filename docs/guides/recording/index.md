# Recording

**Reader:** people who change how a recording is made (`recording.py`, `preflight.py`, `workloads.py`, the two recording scripts and the files in `data/`), or who need to know why a recording was refused, stopped or came back empty. Reviewed 2026-11-16.

Español: [Grabar](../../es/guides/grabar/index.md)

**In short:** when an agent asks to record a program, the server first checks the computer in milliseconds, then starts
a script that runs Apple's Instruments tool on the program, waits, turns the raw capture into a small summary and
deletes the raw capture. If anything fails, or the client cancels, no file is left behind. On Windows a separate engine
measures when frames were shown instead. This guide is split by topic; start with the example below.

This guide follows one recording from the agent's request to the summary handed back. It does not repeat
[How it works](../how-it-works.md) (which layer calls which) or [Data and its lifecycle](../data-and-lifecycle/index.md)
(which files a recording leaves, the lock's life cycle, the retention settings); it links to them.

## The pages

| Page | What is in it |
|---|---|
| [The macOS journey](./macos-journey.md) | The request becomes a command, the wrapper, the script's environment, the watch loop, the kill sequence, what identifies a run |
| [Preflight](./preflight.md) | The six checks and each message, what preflight does not check, what each layer repeats |
| [Two rules](./rules.md) | One recording at a time; why 30 seconds or more under Wine |
| [The test programs](./test-programs.md) | The list, how a request becomes a command, how a download is verified, the pins, PresentMon |
| [The Windows engine](./windows-engine.md) | Why a separate engine, the three sources of frames, step by step, what differs from macOS |
| [The data files](./data-files.md) | The GPU families file and the workloads file |
| [When it fails](./failures.md) | What the client gets in each failure; touching it without breaking it |
| [Known limits](./limits.md) | 14 limits of today's behaviour, written down and not fixed |
| [Evidence](./evidence.md), [Evidence: data files](./evidence-data.md) | The commands (E1 to E10) and their real output; what was not reproduced |

## How to read the labels

Every technical claim is **confirmed** (with `file:line`, checked with `rg` or `sed` on 2026-11-16 against the working
tree, which is 0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`), **probable** (read from the code but not run
here) or **speculation** (a guess about why). **Not verified** marks an outside fact that was not checked against its
source. Lines move when the code changes: search the name, not only the number. Every number comes with the command that
produced it, in the evidence pages. **Not reproduced** means the behaviour could not be run for this guide: no recording
was made (that needs Instruments, a Windows machine and minutes of GPU time) and the session that wrote it could run
read-only commands only, so no check was run live either; the tests that pin each behaviour are named instead, and they
were **not run** for this guide.

## One example first

Suppose an agent asks the server to record a Windows program under Wine for 30 seconds:

```text
perf_record label=mygame program=~/Games/mygame.exe wine=~/wine seconds=30
```

What happens, in the order it happens:

| # | Who | What | Line |
|---|---|---|---|
| 1 | Server | Checks the request: tier, levers, environment pairs, that the program exists, then the label. Nothing has started | `recording.py:48-70`, `:312` |
| 2 | **Preflight** | Is there a Wine, is `xcrun` installed, is there room on the disk, is the screen unlocked, is another recording running? For 30 s it asks for `2 + (30 × 8 + 9) / 10 = 26` GB free ([E3](./evidence.md)). On a failure the call ends with a sentence that says what to do, and no process was started | `preflight.py` |
| 3 | Server | Starts `perf_record.sh` in its own process group and tells the client the worst case: "recording: up to 630 s including read-back" (15 s per recorded second plus 180). Then looks every second at the clock and at the client's cancel flag | `recording.py:371-372`, `:394-421` |
| 4 | Script | Takes the lock, starts Instruments on the program and two small samplers, waits 30 s, runs the report, deletes the raw `.trace` (the [data guide's Figure 2](../data-and-lifecycle/recording-to-disk.md#from-a-recording-to-disk)) | `perf_record.sh` |
| 5 | Server | Reads the summary the report wrote, adds what only it knows (translation layer, where the code came from, tier) and answers with it | `recording.py:437` |

The reply is the same summary every other tool reads. A cancel at any moment, or running past 630 s, kills the whole
thing and leaves no file behind.

## Why recording is shaped this way

| Choice | Why | Alternatives that were left out |
|---|---|---|
| Check everything in the server first (`preflight`), in milliseconds | A Wine D3D12 recording that fails late has already used up to 630 s and gigabytes of temporary disk. Each refusal names the fix (`preflight.py:1-3`, the module's own docstring). The script repeats the program, disk and lock checks as "defence in depth" (`preflight.py:1-3`) | Only the script's checks: its failures reach the client as `recording failed (exit N): <last line of stderr>` (`recording.py:425`) and some carry a local path ([limit 1](./limits.md)) |
| A zsh script drives Instruments; Python drives the script | The script is the thing that is allowed to die: its `EXIT` trap removes the lock, the samplers and the half-written files whatever way it ends (`perf_record.sh:65-73`). The server stays alive, kills the script's whole process group on cancel and cleans up after it (`recording.py:396-413`) | Python calling `xctrace` directly: **speculation** that it was left out because the cleanup is shell-shaped (background loops, traps); no ADR records the choice |
| One recording at a time, with a lock folder | Two programs sharing the GPU spoil both measurements (`perf_record.sh:40`). See [Two rules](./rules.md) | Relying on the worker thread alone: it serializes calls of one server only (`worker.py:1`), not two servers or a script run by hand |
| A deadline of 15 s per recorded second plus 180 s | Closing and reading back a Wine D3D12 trace is slow: a 30 s recording made a 614 MB trace that took minutes to close and 93 s to read, and overran the old limit (`CHANGELOG.md`, 0.8.1). Counters raise it to 55 s per second (`recording.py:266-269`) | A fixed limit: the first one (420 s) lost a real recording |
| Cancel and overrun kill the process group, then the program, then delete the new files | A half-recording is worse than none: it would be listed as a run. The program is stopped by name because a game that catches `SIGTERM` kept running for 40 minutes (`recording.py:255-258`) | Leaving partial files to the retention rules: they would show up in `perf_runs` |
| A separate engine for Windows | Windows has no Instruments or `xctrace`. The engine measures with PresentMon, or with the desktop compositor when PresentMon is absent, and writes the same summary shape through shared code in `metrics.py` (`perf_record_windows.py:24-28`) | One engine with `if` branches: the macOS path is a shell script, so there is nothing to share but the summary |
| Test programs pinned by SHA-256 and built by this project's workflow | A downloaded program is run, so the exact bytes matter; the build is reproducible from source (`data/workloads.json`: "built from source by .github/workflows/workloads.yml") | Downloading upstream binaries directly: the Godot editors are the exception, and they are pinned by SHA-512 (`workloads.py:166-171`) |
| The GPU families and the test programs live in JSON files in `data/` | Facts change faster than code: a new chip or a new program is a data edit with its test, not a logic change. Both are read once at import (`config.py:35-36`) | Constants in Python: **speculation**; no ADR records the choice |

## The pieces and where they live

| Piece | File | What it does | Page |
|---|---|---|---|
| The tools | `recording.py` (`tool_perf_record` `:36`, `tool_perf_attach` `:91`) | Check the request, build the command, call `record` | [Journey](./macos-journey.md) |
| The server-side wrapper | `recording.py` (`record` `:309`, `record_run` `:354`, `finish` `:337`) | Preflight, memory pressure, start the script, watch it, clean up, finish the summary | [Journey](./macos-journey.md) |
| What identifies a run | `recording.py` (`layer_of` `:127`, `run_context` `:168`) | The translation layer's fingerprint and where the code came from | [Journey](./macos-journey.md) |
| The checks | `preflight.py` | What a recording needs, refused in milliseconds | [Preflight](./preflight.md) |
| The macOS recorder | `perf_record.sh` | Lock, samplers, `xctrace`, report, cleanup | [Journey](./macos-journey.md) |
| The Windows recorder | `perf_record_windows.py` | The whole Windows recording; also runnable by hand | [Windows engine](./windows-engine.md) |
| The test programs | `workloads.py`, `data/workloads.json` | The list, the download, the pinned hashes, PresentMon | [Test programs](./test-programs.md) |
| The GPU facts | `data/apple-gpu-families.json` | Not used by recording itself; read by `gpu_family` | [Data files](./data-files.md) |

## See also

- [How it works](../how-it-works.md): layers and the path of one request.
- [Data and its lifecycle](../data-and-lifecycle/index.md): the files a recording leaves, the lock and the two retention settings.
- [Proof of 0.27.0](../../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit): the size limit measured.
