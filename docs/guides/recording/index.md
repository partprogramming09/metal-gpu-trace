# Recording

**Reader:** people who change how a recording is made (`recording.py`, `preflight.py`, `workloads.py`, the two recording scripts and the files in `data/`), or who need to know why a recording was refused, stopped or came back empty. Reviewed 2026-11-16.

Español: [Grabar](../../es/guides/grabar/index.md)

**In short:** when an agent asks to record a program, the server first checks the computer in milliseconds, then starts
a script that runs Apple's Instruments tool on the program, waits, turns the raw capture into a small summary and
deletes the raw capture. If anything fails, or the client cancels, no file is left behind. On Windows a separate engine
measures when frames were shown instead. Start with the example below.

It does not repeat [How it works](../how-it-works.md) (which layer calls which) or
[Data and its lifecycle](../data-and-lifecycle/index.md) (files a recording leaves, the lock, retention); it links to them.

## The pages

[The macOS journey](./macos-journey.md), [Preflight](./preflight.md), [Two rules](./rules.md),
[The test programs](./test-programs.md), [The Windows engine](./windows-engine.md), [The data files](./data-files.md),
[When it fails](./failures.md), [Known limits](./limits.md) (14 limits of today's behaviour, written down and not fixed),
[Evidence](./evidence.md) and [Evidence: data files](./evidence-data.md) (commands E1 to E10 with their real output; what was not reproduced).

## How to read the labels

Every technical claim is **confirmed** (with `file:line`, checked with `rg` or `sed` on 2026-11-16 against the working
tree, which is 0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`), **probable** (read from the code but not run
here) or **speculation** (a guess about why). **Not verified** marks an outside fact not checked against its source.
Lines move: search the name, not only the number. Every number comes with its command in the evidence pages.
**Not reproduced** means the behaviour could not be run for this guide: no recording was made (it needs Instruments, a
Windows machine and minutes of GPU time) and the session could run read-only commands only; the tests that pin each
behaviour are named instead, and they were **not run**.

## One example first

Suppose an agent asks the server to record a Windows program under Wine for 30 seconds:

```text
perf_record label=mygame program=~/Games/mygame.exe wine=~/wine seconds=30
```

| # | Who | What | Line |
|---|---|---|---|
| 1 | Server | Checks the request: tier, levers, environment pairs, that the program exists, then the label. Nothing has started | `recording.py:48-70`, `:312` |
| 2 | **Preflight** | Is there a Wine, is `xcrun` installed, is there room on the disk, is the screen unlocked, is another recording running? For 30 s it asks for `2 + (30 × 8 + 9) / 10 = 26` GB free ([E3](./evidence.md)). On a failure the call ends with a sentence that says what to do; no process was started | `preflight.py` |
| 3 | Server | Starts `perf_record.sh` in its own process group and tells the client the worst case: "recording: up to 630 s including read-back" (15 s per recorded second plus 180). Then looks every second at the clock and the client's cancel flag | `recording.py:371-372`, `:394-421` |
| 4 | Script | Takes the lock, starts Instruments on the program and two small samplers, waits 30 s, runs the report, deletes the raw `.trace` ([data guide's Figure 2](../data-and-lifecycle/recording-to-disk.md#from-a-recording-to-disk)) | `perf_record.sh` |
| 5 | Server | Reads the summary the report wrote, adds what only it knows (translation layer, where the code came from, tier) and answers with it | `recording.py:437` |

The reply is the same summary every other tool reads. A cancel, or running past 630 s, kills everything and leaves no file.

## Why recording is shaped this way

| Choice | Why | Alternatives that were left out |
|---|---|---|
| Check everything in the server first (`preflight`), in milliseconds | A Wine D3D12 recording that fails late has already used up to 630 s and gigabytes of temporary disk. Each refusal names the fix. The script repeats the program, disk and lock checks as "defence in depth" (`preflight.py:1-3`, the module's docstring) | Only the script's checks: its failures reach the client as `recording failed (exit N): <last line of stderr>` (`recording.py:425`) and some carry a local path ([limit 1](./limits.md)) |
| A zsh script drives Instruments; Python drives the script | The script is what may die: its `EXIT` trap removes the lock, samplers and half-written files however it ends (`perf_record.sh:65-73`). The server stays alive, kills the script's process group on cancel and cleans up (`recording.py:396-413`) | Python calling `xctrace` directly: **speculation** that it was left out because the cleanup is shell-shaped; no ADR records the choice |
| One recording at a time, with a lock folder | Two programs sharing the GPU spoil both measurements (`perf_record.sh:40`). See [Two rules](./rules.md) | The worker thread alone: it serializes one server only (`worker.py:1`), not two servers or a script run by hand |
| A deadline of 15 s per recorded second plus 180 s | A 30 s Wine D3D12 recording made a 614 MB trace that took minutes to close and 93 s to read, and overran the old limit (`CHANGELOG.md`, 0.8.1). Counters raise it to 55 s per second (`recording.py:266-269`) | A fixed limit: the first one (420 s) lost a real recording |
| Cancel and overrun kill the process group, then the program, then delete the new files | A half-recording would be listed as a run. The program is stopped by name because a game that catches `SIGTERM` kept running for 40 minutes (`recording.py:255-258`) | Leaving partial files to retention: they would show up in `perf_runs` |
| A separate engine for Windows | No Instruments or `xctrace` there. It measures with PresentMon, or the desktop compositor when PresentMon is absent, and writes the same summary through shared code in `metrics.py` (`perf_record_windows.py:24-28`) | One engine with `if` branches: the macOS path is a shell script, so only the summary is shareable |
| Test programs pinned by SHA-256 and built by this project's workflow | A downloaded program is run, so the exact bytes matter; the build is reproducible (`data/workloads.json`: "built from source by .github/workflows/workloads.yml") | Upstream binaries: the Godot editors are the exception, pinned by SHA-512 (`workloads.py:166-171`) |
| GPU families and test programs live in JSON files in `data/` | Facts change faster than code: a new chip or program is a data edit with its test. Both are read once at import (`config.py:35-36`) | Constants in Python: **speculation**; no ADR records the choice |

## The pieces and where they live

| Piece | File | What it does |
|---|---|---|
| Tools, server-side wrapper, what identifies a run | `recording.py` (`tool_perf_record` `:36`, `tool_perf_attach` `:91`, `record` `:309`, `record_run` `:354`, `finish` `:337`, `layer_of` `:127`, `run_context` `:168`) | Check the request, build the command; preflight, memory pressure, start and watch the script, clean up, finish the summary; the translation layer's fingerprint and where the code came from |
| The checks | `preflight.py` | What a recording needs, refused in milliseconds |
| The macOS recorder | `perf_record.sh` | Lock, samplers, `xctrace`, report, cleanup |
| The Windows recorder | `perf_record_windows.py` | The whole Windows recording; also runnable by hand |
| The test programs | `workloads.py`, `data/workloads.json` | The list, the download, the pinned hashes, PresentMon |
| The GPU facts | `data/apple-gpu-families.json` | Not used by recording itself; read by `gpu_family` |

## See also

[How it works](../how-it-works.md), [Data and its lifecycle](../data-and-lifecycle/index.md) and
[Proof of 0.27.0](../../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit) (the size limit measured).
