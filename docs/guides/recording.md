# Recording

**Reader:** people who change how a recording is made (`recording.py`, `preflight.py`, `workloads.py`, the two recording scripts and the files in `data/`), or who need to know why a recording was refused, stopped or came back empty. Reviewed 2026-11-16.

Español: [Grabar](../es/guides/grabar.md)

This page follows one recording from the agent's request to the moment the summary is handed back, and says what each
piece does and what happens when it fails. It does not repeat [How it works](./how-it-works.md) (which layer calls
which) or [Data and its lifecycle](./data-and-lifecycle.md) (which files a recording leaves, the lock's life cycle, the
retention settings); it links to them where the story continues.

How to read the labels: every technical claim is **confirmed** (with `file:line`, checked with `rg` or `sed` on
2026-11-16 against the working tree, which is 0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`), **probable**
(read from the code but not run here) or **speculation** (a guess about why). **Not verified** marks an outside fact
that was not checked against its source. Lines move when the code changes: search the name, not only the number. Every
number comes with the command that produced it, in [Evidence](#evidence-the-commands-and-their-real-output). **Not
reproduced** means the behaviour could not be run for this page: no recording was made (that needs Instruments, a
Windows machine and minutes of GPU time) and the session that wrote it could run read-only commands only, so no check
was run live either; the tests that pin each behaviour are named instead, and they were **not run** for this page.

## One example first

Suppose an agent asks the server to record a Windows program under Wine for 30 seconds:

```text
perf_record label=mygame program=~/Games/mygame.exe wine=~/wine seconds=30
```

What happens, in the order it happens:

1. The server checks the request: the tier, the levers, the environment pairs, that the program exists, then the label
   (`recording.py:48-70`, `:312`). Nothing has started yet.
2. **Preflight** looks at the Mac: is there a Wine, is `xcrun` installed, is there room on the disk, is the screen
   unlocked, is another recording running? For 30 seconds it asks for `2 + (30 × 8 + 9) / 10 = 26` GB free (E3). If
   anything is wrong the call ends here with a sentence that says what to do, and no process was started.
3. The server starts `perf_record.sh` in its own process group and tells the client the worst case: "recording: up to
   630 s including read-back" (`recording.py:371-372`; 15 s for each recorded second plus 180). It then looks every
   second at the clock and at the client's cancel flag (`recording.py:394-421`).
4. The script takes the lock, starts Instruments on the program and two small samplers, waits 30 s, runs the report and
   deletes the raw `.trace` (this part is the [data guide's Figure 2](./data-and-lifecycle.md#from-a-recording-to-disk)).
5. The server reads the summary the report wrote, adds what only it knows (the translation layer, where the code came
   from, the tier) and answers with it (`recording.py:437`).

The reply is the same summary every other tool reads. A cancel at any moment, or running past 630 s, kills the whole
thing and leaves no file behind.

## Why recording is shaped this way

| Choice | Why | Alternatives that were left out |
|---|---|---|
| Check everything in the server first (`preflight`), in milliseconds | A Wine D3D12 recording that fails late has already used up to 630 s and gigabytes of temporary disk. Each refusal names the fix (`preflight.py:1-3`, the module's own docstring). The script repeats the program, disk and lock checks as "defence in depth" (`preflight.py:1-3`) | Only the script's checks: its failures reach the client as `recording failed (exit N): <last line of stderr>` (`recording.py:425`) and some carry a local path (limit 1) |
| A zsh script drives Instruments; Python drives the script | The script is the thing that is allowed to die: its `EXIT` trap removes the lock, the samplers and the half-written files whatever way it ends (`perf_record.sh:65-73`). The server stays alive, kills the script's whole process group on cancel and cleans up after it (`recording.py:396-413`) | Python calling `xctrace` directly: **speculation** that it was left out because the cleanup is shell-shaped (background loops, traps); no ADR records the choice |
| One recording at a time, with a lock folder | Two programs sharing the GPU spoil both measurements (`perf_record.sh:40`). See [One recording at a time](#one-recording-at-a-time) | Relying on the worker thread alone: it serializes calls of one server only (`worker.py:1`), not two servers or a script run by hand |
| A deadline of 15 s per recorded second plus 180 s | Closing and reading back a Wine D3D12 trace is slow: a 30 s recording made a 614 MB trace that took minutes to close and 93 s to read, and overran the old limit (`CHANGELOG.md`, 0.8.1). Counters raise it to 55 s per second (`recording.py:266-269`) | A fixed limit: the first one (420 s) lost a real recording |
| Cancel and overrun kill the process group, then the program, then delete the new files | A half-recording is worse than none: it would be listed as a run. The program is stopped by name because a game that catches `SIGTERM` kept running for 40 minutes (`recording.py:255-258`) | Leaving partial files to the retention rules: they would show up in `perf_runs` |
| A separate engine for Windows | Windows has no Instruments or `xctrace`. The engine measures with PresentMon, or with the desktop compositor when PresentMon is absent, and writes the same summary shape through shared code in `metrics.py` (`perf_record_windows.py:24-28`) | One engine with `if` branches: the macOS path is a shell script, so there is nothing to share but the summary |
| Test programs pinned by SHA-256 and built by this project's workflow | A downloaded program is run, so the exact bytes matter; the build is reproducible from source (`data/workloads.json`: "built from source by .github/workflows/workloads.yml") | Downloading upstream binaries directly: the Godot editors are the exception, and they are pinned by SHA-512 (`workloads.py:166-171`) |
| The GPU families and the test programs live in JSON files in `data/` | Facts change faster than code: a new chip or a new program is a data edit with its test, not a logic change. Both are read once at import (`config.py:35-36`) | Constants in Python: **speculation**; no ADR records the choice |

## The pieces and where they live

| Piece | File | What it does |
|---|---|---|
| The tools | `recording.py` (`tool_perf_record` `:36`, `tool_perf_attach` `:91`) | Check the request, build the command, call `record` |
| The server-side wrapper | `recording.py` (`record` `:309`, `record_run` `:354`, `finish` `:337`) | Preflight, memory pressure, start the script, watch it, clean up, finish the summary |
| What identifies a run | `recording.py` (`layer_of` `:127`, `run_context` `:168`) | The translation layer's fingerprint and where the code came from |
| The checks | `preflight.py` | What a recording needs, refused in milliseconds |
| The macOS recorder | `perf_record.sh` | Lock, samplers, `xctrace`, report, cleanup |
| The Windows recorder | `perf_record_windows.py` | The whole Windows recording; also runnable by hand |
| The test programs | `workloads.py`, `data/workloads.json` | The list, the download, the pinned hashes, PresentMon |
| The GPU facts | `data/apple-gpu-families.json` | Not used by recording itself; read by `gpu_family` (see [The data files](#the-data-files)) |

## The journey of a recording, step by step (macOS)

Everything below is **confirmed** by the lines named. The files it leaves are in the
[data guide](./data-and-lifecycle.md#what-a-recording-leaves-on-disk).

### Step 1: the request becomes a command

`tool_perf_record`, `recording.py:36-73`.

1. `resolve_tier` turns `tier` into three settings (`recording.py:23-33`):

   | Tier | Metal memory | GPU counters | `.trace` kept | What it costs |
   |---|---|---|---|---|
   | `light` | no | no | no | seconds of read-back: to iterate |
   | `standard` (default) | yes | no | no | the memory table is the slowest to read |
   | `deep` | yes | yes | yes (unless the disk limit drops it) | counters add about 40 s of read-back per recorded second (`recording.py:44`) |

   A `memory` or `counters` passed on its own replaces that part of the tier. `deep` is refused on Windows
   (`recording.py:49-50`).
2. `check_levers` refuses a `memory_free_pct` outside 20 to 60 and either lever on Windows (`recording.py:274-284`).
3. `check_env` accepts only `NAME=VALUE` pairs separated by spaces (`recording.py:76-81`): the script later splits the
   text on spaces, so a space inside a value would break it.
4. With `workload`, `workloads.workload_command` supplies the program, the Wine mode, the arguments and the environment
   (`recording.py:53-56`; [The test programs](#the-test-programs)). `size` without a workload is refused (`:57-58`);
   no `program` is refused (`:59-60`).
5. Without `wine`, `METAL_TRACE_WINE` is used; on macOS with neither, the call is refused (`:61-65`). The program must
   exist (`:66-68`); the error names the file, not the path.
6. `perf_attach` skips most of that: `record(label, seconds, "attach", "-", "-", [process])` (`recording.py:95`). It
   has no tier, so the summary has no `tier` key (`recording.py:344-345`), and the program keeps running afterwards.

### Step 2: the wrapper

`record`, `recording.py:309-322`. In this order: the label (letters, digits, `.`, `_`, `-`, at most 100, `:312`), the levers (`:314`), **preflight**
(`:315`), then `memory_pressure` if `memory_free_pct` was given (`:316`, `hold_memory_pressure` `:287-306`: it waits up
to 90 s for "Stable at percent free" and refuses if it never comes), then `record_run`. A `finally` stops the pressure
whatever happens (`:319-322`).

Preflight goes before the pressure on purpose: a refused run must start nothing. `test_record_runs_preflight_before_memory_pressure`
and `test_preflight_failure_starts_no_process` (`tests/test_preflight.py:275`, `:296`) pin that (not run for this page).

### Step 3: the environment the script gets

`record_run` builds it at `recording.py:360-370`.

| Variable | Set when | Meaning for the script |
|---|---|---|
| `PERF_OUT` | always | the runs folder (`config.OUT`) |
| `PERF_LOCK` | always | the lock folder (`config.LOCK`), so the server and the script share one |
| `PERF_PARENT_PID` | always | the server's pid: the script stops its program if the server dies (`perf_record.sh:82-92`) |
| `PERF_ENV` | always | the program's `NAME=VALUE` variables, from the environment plus `env` and the workload |
| `PERF_MEMORY=0` | `memory` is false | skip the Metal memory table |
| `KEEP_TRACE=1` | tier `deep` | keep the `.trace` |
| `PERF_PREFIX` | `background` | run the program under `taskpolicy -b` (`recording.py:271`) |
| `PERF_INSTRUMENTS` | counters | add the `Metal GPU Counters` instrument |

`KEEP_RUNS` and `PERF_MIN_FREE_GB` are not set here: the script reads them from the environment the server passed on
(`dict(os.environ, ...)`, `recording.py:360`).

Then `layer_of` runs (`recording.py:370`): it asks the Wine for its version (`wine --version`, timeout 30 s, `:140-143`)
and fingerprints the layer (see [What identifies a run](#what-identifies-a-run)).

### Step 4: the watch loop

`record_run`, `recording.py:386-421`. Before it starts the script the server remembers which `<label>_*` files and which `instruments*.ktrace` already exist
(`:386-388`); that list is what it may delete later, so it never deletes a file it did not create. The script starts
with `start_new_session=True` (`:389-392`): it leads its own process group, which is what `os.killpg` kills.

Then a loop of at most one-second turns (`:394-421`): if the time is over or the client cancelled, it goes to the kill
sequence below; otherwise it waits up to a second for the script and, every `PROGRESS_TICKS` (5, `config.py:48`) turns,
sends a progress line "recording and reading back: N s of up to M s".

### Step 5: when the script returns

- A non-zero exit, or no new `.json`: `recording failed (exit N): <last line of stderr>` (`recording.py:422-425`).
- A summary with no GPU intervals: the program did no GPU work; the run's files are deleted and the error says how it
  ended (`:427-436`; see [When it fails](#when-it-fails)).
- Otherwise `finish` adds `layer`, `context`, `tier`, applies the disk limit and rewrites the summary
  (`recording.py:337-351`, `:437`). The summary key tables are in the [data guide](./data-and-lifecycle.md#the-summary-key-by-key).

### The kill sequence

Cancel and overrun end the same way, in this order (`recording.py:396-413`):

1. `os.killpg(proc.pid, SIGKILL)`: the script and everything it started (`:397`). `SIGKILL` cannot be caught, so the
   script's own trap does not run: the server has to clean up itself.
2. Stop the program: with `native`, every process of that name (`kill_program`, `:255-263`: `SIGTERM`, up to 3 s of
   waiting, then `SIGKILL`); with Wine, `wineserver -k` for the prefix (`:402-403`); with `attach`, nothing: the program
   was not ours (`:401`).
3. `free_lock(proc.pid)`: remove the lock only if it still holds the script's pid (`:326-335`).
4. Delete the files this run created: new `<label>_*` entries and new `instruments*.ktrace` (`:406-407`).
5. Raise `the recording was cancelled; nothing was saved`, or, for an overrun, the message that names the likely cause
   (a hidden window) (`:408-413`).

`test_overrun`, `test_overrun_removes_lock_with_pid` and `test_free_lock_only_frees_its_own`
(`tests/test_recording.py:358`, `:387`, `:733`) pin this (not run for this page).

## One recording at a time

The rule is in the server's instructions ("One recording runs at a time", `metal_trace_mcp.py:25`), and it is enforced
at three levels that guard against different things:

| Level | What it stops | Where |
|---|---|---|
| The worker thread | Two tool calls of one server running at once | `worker.py:1` |
| The lock folder, read by preflight | A recording starting while another one, from any server or by hand, holds the lock | `preflight.py:74-98`, `:135-137` |
| The lock folder, taken by the script (or the Windows engine) | The same, at the moment that matters: `mkdir` is atomic, so only one process can create it | `perf_record.sh:52-62`, `perf_record_windows.py:577-598` |

**Why.** The comment at `perf_record.sh:40` says it: "two programs sharing the GPU spoil both measurements" (confirmed).
The summary even has a way to notice it after the fact: `noisy_environment` compares the GPU's total use with the
program's own busy share and flags a gap of 20 points or more, a provisional threshold (`how-it-works.md`, "What to do
next"; the key is described in the [data guide](./data-and-lifecycle.md#keys-of-a-macos-summary-present-only-on-a-condition)).

**Why it is one lock for every folder.** Each project has its own runs folder, but there is one GPU: the lock lives in
the cache folder, not in the runs folder (`config.py:41-42`; `test_recordings_into_two_folders_run_one_at_a_time`,
`tests/test_recording.py:854`).

The lock's own life (take over a dead owner, release, who removes it) is in the
[data guide](./data-and-lifecycle.md#the-lock). What is new here: a held lock makes the second recording refuse **before**
it starts anything (`preflight.py:135-137`), and the message is `another recording is running; one runs at a time. If
none is, remove the lock folder (METAL_TRACE_LOCK names it)`.

## Why 30 seconds or more under Wine

The instruction reads: "Under Wine record 30 s or more: Wine's start-up takes part of the recording"
(`metal_trace_mcp.py:27`; the same sentence is in the `seconds` description, `registry.py:39`, and in `README.md:138`).
That is **confirmed as the project's stated reason**. What is behind it, in two parts:

- **The first seconds are not the program's steady state.** Wine boots, the program opens its window and compiles its
  shaders while Instruments is already recording. `skip_s` exists to cut that start-up off a comparison
  (`metal_trace_mcp.py:31`), and `analysis._startup_skip_s` looks for shader-compile hitches that end within the first
  quarter of the run (`analysis.py:670-690`). A 30 s run keeps most of its length after the start-up. **How many seconds
  the start-up takes was not measured for this page**; the number 30 is the project's rule of thumb (**probable**).
- **It is not the 100-frame rule.** A run under 100 frames is flagged separately (`analysis.py:378`, `:499`, `:655`: "under 100 frames: too
  short to judge; record 30 s or more"), and at 60 FPS 100 frames is under 2 seconds. So 100 frames is a floor for comparing
  at all, and 30 s is about the start-up (**speculation**: derived by arithmetic from two rules the code states, not from a
  measurement).

The cost side is real and is why the deadline is what it is: a 30 s Wine D3D12 recording took a 614 MB trace and about
93 s just to read (`CHANGELOG.md`, 0.8.1), and each recorded second needs about 0.8 GB of temporary disk (`perf_record.sh:33`,
a code comment: **probable**). Native Metal runs are shorter: one changelog entry
mentions native 10 s runs next to 30 s runs under Wine (`CHANGELOG.md:309`).

## What preflight checks, and what it says

`preflight.check` (`preflight.py:101-137`) runs six checks in a fixed order and raises a `ToolError` at the first one
that fails. All checks are in milliseconds and none starts a process, except reading the screen state (`ioreg`, timeout
10 s, `perf_report.py:593-604`).

![Seven boxes in a row, left to right: arguments, program, xcrun, disk, screen, lock and start. Under each of the first six the exact message it refuses with is written. If all pass, the recording starts.](/diagrams/recording-preflight.png)
*Figure 1. The checks of `preflight.check` and the message each one gives. HTML source: `docs/diagrams/recording-preflight.html`.*

| # | What it checks | Message when it fails | Line | Test (not run here) |
|---|---|---|---|---|
| 1 | `seconds` is a whole number from 1 to 3600 (`whole_seconds` refuses `10.5`, `True` and `"1_0"`, forms Python accepts and the shell would not) | `seconds is a whole number from 1 to 3600` | `preflight.py:107-108`, `:30-41` | `test_seconds_are_checked_before_anything_else` `:357` |
| 1 | `environ` is a mapping of text; `wine` is a path or `native` or `attach`; `command` is a list of strings | `environ is a mapping of text`, `wine is a path or native or attach, and the command a list of strings` | `:109-114` | |
| 2 | A Wine directory holds an executable `bin/wine` | `no Wine at bin/wine inside that Wine directory (pass native for a macOS program)` | `:115-116` | `test_missing_wine_binary` `:65` |
| 2 | With `native`: the program is a file with the execute bit | `<name> is not an executable file` (the file name only) | `:117-119` | `test_native_program_not_executable` `:72` |
| 3 | `xcrun` is on the `PATH` of the request's environment (not on Windows) | `xcrun is not on PATH: install Xcode or the command line tools (xcode-select --install)` | `:120-121` | `test_no_xcrun` `:81` |
| 4 | Free GB in the temporary folder and in the runs folder, each at least the need | `not enough free disk on the temporary folder (TMPDIR): N GB free, M GB needed (PERF_MIN_FREE_GB overrides)` (or `the runs folder`) | `:122-131` | `test_not_enough_disk_names_the_override` `:89` |
| 4 | The free space can be read (a path with a null byte, a failing `disk_usage`) | `the free disk space cannot be read for the runs or the temporary folder` | `:61-71` | |
| 5 | The login session's screen is not locked (`ioreg`); not on Windows; `METAL_TRACE_ALLOW_LOCKED=1` skips it; an unreadable state passes | `the screen is locked: a locked session leaves the program's frames unpaced by the display, so the numbers do not compare; unlock the Mac, or set METAL_TRACE_ALLOW_LOCKED=1 to record anyway` | `:132-134` | `test_locked_screen_refuses_and_names_the_override` `:118` |
| 6 | The lock folder does not name a live process | `another recording is running; one runs at a time. If none is, remove the lock folder (METAL_TRACE_LOCK names it)` | `:135-137` | `test_live_lock_refuses` `:152` |

How the numbers in check 4 come out:

- The need is `PERF_MIN_FREE_GB` when it is a plain number, else `2 + (seconds × 8 + 9) / 10` in integer division
  (`preflight.py:44-50`), which is 18 GB for 20 s, 26 for 30 s and 50 for 60 s (E3). Under Windows it is 1 GB, because there
  is no Instruments (`:50`). The shell script computes the same formula (`perf_record.sh:34`); `test_disk_formula_matches_the_shell`
  (`tests/test_preflight.py:101`) pins that the two agree.
- The temporary folder is `TMPDIR` of the request's environment, or `/tmp` (`:126`): that is where `xctrace` writes its
  `.ktrace` files while recording.
- A runs folder that does not exist yet is measured at its nearest existing parent (`free_gb`, `:61-71`).

The lock check (`lock_owner_alive`, `:74-93`) is built for a folder anyone can write to. It refuses to follow a link,
reads at most 32 bytes of the `pid` file with a non-blocking open, accepts only ASCII digits up to 10 characters and a pid
from 1 to 2³¹−1, and treats anything odd as "no live owner". The reason is the lock's location: a hostile or broken
`pid` file must not make a recording hang (a pipe), signal a whole process group (pid 0 or −1, `:16`), or crash the check.
On Windows `os.kill` is never used, since there it ends the process; `perf_record_windows.is_process_alive` asks `OpenProcess` instead
(`:18-20`). `test_hostile_pid_files_are_not_a_live_owner` (`tests/test_preflight.py:336`) pins the odd cases.

### What preflight does not check

- **That a process to attach to exists.** `perf_attach` passes preflight with any text; the script says
  `no running process matches <name>` (exit 2, `perf_record.sh:24`) and the Windows engine says the same as a
  `RuntimeError` (`perf_record_windows.py:475`, `:480`). In both cases it arrives as `recording failed ...` or as a plain
  `ToolError`.
- **The Wine prefix, the working directory, the `api` against the platform.** They are used later, by the script or by `Popen`.
- **That the program is a Mach-O.** The script checks the first four bytes against a list of Mach-O magic numbers (and
  ELF and `#!`, "for the Linux CI") and refuses with `<name> is not a program the system can run (no Mach-O or #! header)`
  (`perf_record.sh:14-19`).
- **The label.** `record` checks it before preflight (`recording.py:312`), and the script checks it again
  (`perf_record.sh:10`).

### What each layer repeats

| Check | `recording.py` / `preflight.py` | `perf_record.sh` |
|---|---|---|
| Label | `recording.py:312` | `:10` (exit 2) |
| Seconds 1 to 3600 | `preflight.py:107` | `:11` (exit 2) |
| Wine directory | `preflight.py:115` | `:12` (exit 2) |
| Native program | `preflight.py:117` | `:13`, `:14-19` (exit 2) |
| `xcrun` | `preflight.py:120` | none: `xcrun` is simply called |
| Disk | `preflight.py:122-131` | `:34-38` (exit 4, the message carries the folder) |
| Screen locked | `preflight.py:132` | none |
| Lock | `preflight.py:135` | `:47-61` (exit 3) |
| Process to attach to | none | `:20-25` (exit 2) |

## What identifies a run

Two things are computed in the server, not in the script, because they need to read the machine and the repository:

- **`layer_of`** (`recording.py:127-157`) says what translation layer the recording ran on. `native` gives
  `{"none": "native Metal, no translation layer"}` and `attach` gives `{"unknown": ...}` (`:134-137`). With Wine it
  records the Wine version (`wine_version`, `:117-124`, which joins CrossOver's "Product Name" and "Public Version"
  lines), the `WINEDLLOVERRIDES` the script will pass, the prefix's DLL overrides read from `user.reg`
  (`registry_overrides`, `:102-114`), and the size and SHA-256 of five DLLs (`d3d12`, `d3d12core`, `d3d11`, `d3d10core`,
  `dxgi`, `LAYER_DLLS` `:99`) both in Wine and in the prefix, plus a 12-character fingerprint of all of it. Which of the
  two copies Wine really loads is **not known** (`:128-130`: Instruments does not keep Wine's own log), so the
  fingerprint treats the prefix's copy as the effective one when it exists (`effective_dlls`, `:160-162`).
  Why: `perf_compare` must say whether two runs share a layer before it says one is faster
  (`layer_change`, `:205-223`).
- **`run_context`** (`recording.py:168-188`) says where the code came from: the short commit and whether tracked files were
  changed, of the repository that holds the project file, and `xctrace`'s version. It drops every `GIT_*` variable so
  none can point git at another repository, and leaves out the branch, the path and the user name: summaries are shared.

A workload that goes through MoltenVK or Rosetta passes its own `layer` instead (`workloads.workload_layer`,
`workloads.py:39-49`), so a comparison against native says "different layers".

## The test programs

`workload_list` shows them, `workload_fetch` downloads one, `perf_record` with `workload`, `api` (and `dim`, `example`,
`size`) runs it. They exist so two people on two Macs can record the same load and compare numbers.

### What is in the list (E4)

| Name | What it draws | `api` values | Download | License |
|---|---|---|---|---|
| `drawstress` | bgfx's 17-drawstress: a grid of cubes, `dim`³ draw calls per frame (64 000 at `dim` 40): the cost of one draw, native and through a layer | `mtl`, `mtl-x64` (Metal built for x86_64, run under Rosetta like a Wine program), `vk` (Vulkan through MoltenVK), `d3d11`, `d3d12` | 9 291 979 bytes | BSD-2-Clause (bgfx) |
| `bgfx-examples` | 30 bgfx examples, each a different load, chosen with `example` | `mtl`, `d3d11`, `d3d12` | 57 350 072 bytes | BSD-2-Clause (bgfx) |
| `godot` | A Godot 4.7.2 scene built from code (400 shapes, 8 lights, shadows, an orbiting camera), no imported assets | `mtl`, `d3d12` | 1 525 bytes, plus two Godot editor builds of 170 622 178 and 86 013 866 bytes | MIT (Godot); the scene is this repository's |

`example_traits` lists, for each of the 30 examples, a class (`cpu_submit`, `compute`, `postprocess`, ...) and how many
encoders per frame to expect native and under D3D12 (E4: 30 examples, 30 traits), so a recording can be checked against
what the program should do (`tool_workload_list`, `workloads.py:101-112`).

### How a request becomes a command (`workload_command`, `workloads.py:65-91`)

1. The `api` must be in the entry (`:69-70`): `api is one of mtl, mtl-x64, vk, d3d11, d3d12 for drawstress`.
2. A workload with `examples` needs `example` to be one of them; one without them refuses it (`:71-75`).
3. `dim` needs the entry to have a `dim_variable` (`DRAWSTRESS_DIM`) (`:76-77`); `size` needs `size_variables`
   (`DRAWSTRESS_WIDTH`, `DRAWSTRESS_HEIGHT`) and is `WIDTHxHEIGHT` from 320x240 to 7680x4320 (`:52-57`, `:82-85`).
4. The folder must be downloaded: `<name> is not downloaded yet; call workload_fetch first` (`:78-79`).
5. `vk` also needs `METAL_TRACE_MOLTENVK`, a folder with `libMoltenVK.dylib` and no spaces (`:25-36`), which goes into
   `DYLD_LIBRARY_PATH` (`:86-87`).
6. The result is the program (`<cache>/<name>-<12 hex>/<dir>/<program>`), `wine` when the api needs it and the platform
   is not Windows, otherwise `native` (`:88-89`), the arguments with each `{dir}` replaced by the quoted folder
   (`dir_in_args`, `:94-98`) and the program's environment (`:81-87`).

`workload_layer` (`:39-49`) names the layer for the summary: Rosetta for an api marked `rosetta`, MoltenVK (with the dylib's
size and SHA-256) for one marked `moltenvk`, and `None` otherwise: the normal Wine and native layers come from `layer_of`.

### How a download is verified (`tool_workload_fetch`, `workloads.py:147-176`)

This section has no figure of its own: the steps are a straight line with one refusal at each of 4 and 6.

1. If `<cache>/<name>-<first 12 hex of sha256>` already exists, return at once (`:154-155`).
2. Otherwise make a temporary folder **inside the cache** (so the final rename stays on one disk) (`:157`).
3. `download` runs `curl -fsSL --proto =https --max-filesize <bytes> --max-time 600` (`:115-120`): https only, never more
   than the size the data file says, at most 10 minutes. It uses `curl` because curl uses the system's certificates.
4. The archive's SHA-256 must equal the pinned one, else `<name>'s download does not match the SHA-256 this package pins;
   nothing was saved` (`:160-161`).
5. `unpack` refuses any member that is not a plain file or folder, that starts with `/` or holds `..` (`:123-129`).
6. For each entry of `downloads` (Godot's two editors), the same, with a **SHA-512** pinned in the data file and
   `unzip` refusing links and bad paths and restoring the Unix modes (`:163-173`, `:132-144`).
7. Rename the temporary `out` folder to the final name (`:174`): the folder appears whole or not at all.

If anything raises, the temporary folder goes with its `with` block (`:157`) and nothing reaches the cache. That is **confirmed
by the code**; a failed download or a wrong hash was **not reproduced** (it needs the network and a wrong archive;
`test_workload_downloads`, `tests/test_recording.py:286`, builds a fake one and pins the refusals; not run for this page).

### The pins (E4, E5)

The data file pins each archive by its SHA-256, and the cache folder is named with the first 12 characters of it
(`workloads.py:22`), so a new release of an archive is a new folder, never an overwrite:

| Workload | Release tag | SHA-256 (full) |
|---|---|---|
| `drawstress` | `workloads-3` | `2b3b01fa2dd0a7d5a1629046305319130d58ce4d843bd22c3f736071c0bfde2e` |
| `bgfx-examples` | `workloads-8` | `1d120363981ced4ae01dad57085258206fbc84f35bd9bcdcfe656b1af355d091` |
| `godot` | `workloads-9` | `a85320f08e1ac2721288441a5317796de4673a6df6fc727b71c135503adc09c5` |

The archives are built from source by `.github/workflows/workloads.yml` and uploaded to the project's GitHub releases with a
`.sha256` file (`workloads.yml:35`, `:43`, `:102`, `:111`). Each archive carries a `BUILD.txt` with the commits it was
built from (E5), and the license of what it contains. Whether the published asset's digest today equals the pin
was **not verified** (no network call was made for this page), and a download was **not reproduced**.

Godot's two editor builds come straight from the Godot project's releases and are pinned by SHA-512 in the same file
(first 16 characters in E4: `38aa16e5bba20839` for macOS, `83decd58fdf67b9d` for Windows).

Because a new pin makes a new folder and nothing deletes the old one, the cache grows: 8 folders for 3 pins on the machine
this page was checked on (E5). The numbers and the open question are in the
[data guide](./data-and-lifecycle.md#the-cache-is-not-the-recordings).

### PresentMon (`tool_presentmon_install`, `workloads.py:179-205`)

PresentMon is Intel's console program (MIT) that logs every `Present()` of a process on Windows. The package pins version 2.6.0
(980 320 bytes, SHA-256 `b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af`, `workloads.py:180-184`).
`presentmon_install`:

1. Refuses on any platform but Windows (`:191-192`).
2. Does nothing if the file is already in `%LOCALAPPDATA%\metal-gpu-trace` and its hash matches (`:194-197`).
3. Otherwise downloads into a temporary folder (twice the pinned size is the ceiling, `:201`), checks the SHA-256 and
   replaces the target file (`:199-204`).

It needs administrator rights or membership of the Performance Log Users group to run (the tool's own description,
`workloads.py:187-190`: **not verified** against Intel's documentation).

At **recording** time the engine looks for PresentMon in this order (`find_presentmon`, `perf_record_windows.py:420-430`):
the file named by `PRESENTMON_EXE` (and if that is set but missing, **none**, with no fallback), the newest
`PresentMon*.exe` in the cache folder, then `PresentMon` or `PresentMon-x64` on the `PATH`. The hash is checked at install
only, not at use (limit 4).

## The Windows engine

`perf_record_windows.py` is the whole of a Windows recording. The server calls it from `record_run` when
`sys.platform == "win32"` (`recording.py:373-385`), through a late import because the module may have been imported
already by something else (`:374`), and `record_run` then ends in the same `finish` as macOS (`:385`). It can also run by
hand: `python src\metal_gpu_trace\perf_record_windows.py <label> <seconds> <wine|native|attach> <prefix> <workdir> <command...>`
(`main`, `:950-962`; running it on the Mac without arguments prints the usage line, which was **not reproduced** here).

![Eight boxes in two rows joined by arrows. Top row: lock, program, frame source (a decision), one-second loop. Bottom row: stop and clean up, which frames (a decision), write, and recording.finish.](/diagrams/recording-windows-engine.png)
*Figure 2. One Windows recording. HTML source: `docs/diagrams/recording-windows-engine.html`.*

### Why a separate engine, and what it measures

Instruments exists only on macOS, so the Windows engine cannot produce a `.trace`: there is no `xctrace`, no Metal System Trace,
no per-encoder timing. What it can measure is **when frames were presented**. It builds the same summary shape
through `metrics.py` (`:24-28`, `:887-917`), but several blocks are empty or fixed: `missing_tables` lists three Metal tables
by name, `metal_memory_mib` is `{"samples": 0}`, and `encoders` and `gpu_idle` are computed from the spans of the one source
that has any (E8). The summary's keys are in the [data guide](./data-and-lifecycle.md#a-windows-summary).

### The three sources of frames, and which one wins

| Order | Source | `gpu.source` | What it gives | What it cannot give |
|---|---|---|---|---|
| 1 | The program's own log: `DRAWSTRESS_LOG`, one line per batch of frames (`dim`, `draws`, `frame_us`, `frames`) | `drawstress-log` | GPU time per frame (a mean per line) and spans for the encoder statistics | A frame-level distribution: 1% low, 0.1% low, stutter rate and jitter are `null` (`:859-862`), because each line is already a mean |
| 2 | PresentMon rows: `MsBetweenPresents` and, when the column exists and is positive, `MsGPUTime` | `presentmon` | One row per `Present()` of that process, with its GPU time | Per-encoder timing |
| 3 | A 1 ms thread reading the compositor (`DwmGetCompositionTimingInfo`) | `dwm-composition` | Intervals between composed frames of the **whole desktop** | GPU time per frame, and anything specific to the process |
| none | | | | The run fails: `no frame data` |

The order is the order of the `if` chain (`:787`, `:808`, `:819`, `:830`), so a **drawstress run on a machine that has PresentMon
installed still runs PresentMon** (it starts at `:652-659`, before the program's log is read) **but its rows are not used**: the log
wins. This is confirmed by the code; it was not reproduced.

Why three sources: the log is exact for the project's own test program, PresentMon is the right tool for any other program,
and the compositor is a last resort that works with no installed tool. The compositor sampler only counts an interval
between two consecutive composed frames: a jump of several frames is dropped rather than split into equal parts
(`:403-407`), so it never invents frames.

### Step by step (Figure 2)

1. **Lock** (`:573-597`). The server passes `config.LOCK`, the same folder macOS uses; run by hand, the engine falls back to
   `<runs>/.recording` (`:574`). `mkdir`, write the pid; if it exists and its owner is dead, remove it and try once more
   (two attempts), otherwise `another recording is running (<lock>); remove it if none is` (`:597`).
2. **Program** (`:612-645`). With `attach`, `find_attached_process` finds the pid by number or by a name inside the process name (the
   highest pid wins, `:457-483`). Otherwise it merges `program_env` and `PERF_ENV` into the environment, sets
   `DRAWSTRESS_LOG` to `<runs>/<name>.drawstress.log` and starts the program with `Popen`.
3. **Frame source** (`:647-666`). If `find_presentmon` found one, start it with `--process_id`, `--timed <seconds>`,
   `--terminate_after_timed`, `--stop_existing_session`; otherwise start the DWM thread.
4. **The loop** (`:673-705`). Once per second: sample the working set (`rss.csv`), look at the deadline and the cancel flag,
   and stop early if the program exited by itself. Progress goes out every 5 s.
5. **Stop** (`:707-757`). Stop the DWM thread; wait up to 15 s for PresentMon, killing it if it does not stop; on cancel or
   overrun, kill the program tree, delete every file starting with the run's name and raise `the recording was cancelled; nothing
   was saved` or `the recording took over N s and was stopped; nothing was saved` (`:744-746`). If the recording completed and the
   program is still alive, terminate it, then kill its tree.
6. **Which frames** (`:759-844`): the table above.
7. **Write** (`:846-927`): the `frames.csv.gz` table, the statistics (the pacing numbers come from `perf_report.frame_pacing`,
   the same function macOS uses, `:489`), the summary, the `common` block, the `.json`, and `KEEP_RUNS` through its own `clean_runs`
   (`:503-518`, `:921-924`).
8. **Finish**: back in `record_run`, `finish` adds `layer`, `context`, `tier` and the disk limit (`recording.py:385`).

A `finally` runs whenever the recording did not succeed: it stops the DWM thread and PresentMon, kills the program it started
(never an attached one) and deletes every file starting with the run's name, then frees the lock (`:929-947`). The lock is
released on success too.

### What differs from macOS

| | macOS | Windows |
|---|---|---|
| Recorder | `perf_record.sh` driving `xctrace` | `perf_record_windows.py`, in the server's own process |
| Tiers | `light`, `standard`, `deep` | `deep` refused (`recording.py:49-50`); `memory` has no effect: there is no Metal memory table |
| `memory_free_pct`, `background` | allowed | refused (`recording.py:283-284`) |
| Disk needed | `2 + 0.8 GB` per second, in `TMPDIR` and the runs folder | 1 GB, in the runs folder (`preflight.py:50`, `:123-124`) |
| `xcrun`, screen | checked | not checked (`preflight.py:120`, `:132`) |
| Program's stop at the end | by name (`native`) or `wineserver -k` | the process tree (`kill_process_tree`, `:521-551`) |
| Wine | yes | no: `wine` becomes `native` when none is given (`recording.py:61-65`), and an api marked `wine: true` runs natively (`workloads.py:88-89`) |
| Lock life | `mkdir` + takeover under a second lock | `mkdir` + one stale takeover, with no second lock (limit 3) |
| Frame table | `frames.csv.gz` with one `gpu_ms_<channel>` per channel | `frames.csv.gz` with `gpu_ms_draw` and `gpu_ms_total` (`:847`) |

`perf_record_windows.py` also reads hardware facts for the `device` block: Win32 for the processor, RAM and OS version, and
when a `vegaflow_daemon.exe` is found next to the clone, a `--system-info` call with a 1 s timeout that adds CPU and GPU
architecture names (`collect_device_info`, `:242-283`; `daemon_candidates` `:231-239`). Any failure falls back to the Win32 facts
silently. What VegaFlow is, where it comes from and who runs it is **not documented in this repository's
guides** and was not investigated: pending confirmation.

## The data files

The folder is `src/metal_gpu_trace/data/`. Both are plain JSON read **once, at import**, by `config.py:35-36`. There is no `try` around them: a missing or broken
file stops the server at start-up, not at the first call (**confirmed by the code**; that no test covers it was not
checked).

### The GPU families file

`apple-gpu-families.json`, 63 lines.

Facts about Apple silicon GPU families Apple7 to Apple10: for each, the Mac chips and other chips, the features it
adds and the limits that differ (`mesh_grid_threadgroups`, `texture_2d_px`, ...); then what is the same on all, footnotes and
`guards` such as `M1 only: Apple7 && !Apple8`. Its `about` says these are "facts restated from Apple's public documents, not Apple's
text", and `sources` names three URLs, one with the date 2026-05-21. Whether each fact matches those documents today was
**not verified** for this page.

| Reader | What it does | Line |
|---|---|---|
| `traces.family_of`, `tool_gpu_family` | Finds a family by key (`Apple9`) or chip (`M1 Pro`, `A17 Pro`); the chip match drops `series` and a `pro`/`max`/`ultra` suffix | `traces.py:177-197` |
| `registry.RESOURCES` | One resource `metal-trace://gpu-families` for the whole file and one per family key | `registry.py:12-15` |

What happens with a missing entry: `gpu_family` with an unknown name raises `unknown family or chip '<name>'; try one of
Apple10, Apple7, Apple8, Apple9 or a chip such as M1 Pro, M2, M3 Max, A17 Pro` (`traces.py:193`; the list is built from the file's keys,
E7). A family without `mac_chips` or `other_chips` would raise a `KeyError` inside `family_of` (`traces.py:181`; **probable**, not
tested). To add a family, add a key: its resource appears by itself (`registry.py:14-15`).

Recording does not read this file. It is described here because it is the other half of `data/`.

### The workloads file

`workloads.json`, 99 lines. An `about` line and a `workloads` object with one entry per test program. The fields and who reads them:

| Field | Meaning | Read by |
|---|---|---|
| `title`, `about`, `license` | What `workload_list` shows | `workloads.py:101-112` |
| `url`, `sha256`, `bytes` | The pinned archive: where it is, its hash, its exact size | `workloads.py:159-161` |
| `dir` | The folder inside the archive that holds the program | `workloads.py:89` |
| `apis` | For each api: `program`, `args`, `wine` (true: run under Wine), and optionally `rosetta` or `moltenvk` | `workloads.py:43-47`, `:80-89` |
| `dim_variable`, `size_variables` | The environment variables that `dim` and `size` set | `workloads.py:76-85` |
| `examples`, `example_traits` | The names `example` accepts, with the prefix the program takes, and the expected class and encoder counts | `workloads.py:71-75`, `:101-112` |
| `downloads` | Extra archives fetched from another publisher: `url`, `sha512`, `bytes`, `into` | `workloads.py:163-173` |

What happens if an entry is missing or wrong: an unknown **name** raises `no workload '<name>'; workload_list lists them`
(`workloads.py:19-20`); an unknown **api**, **example**, **dim** or **size** raises the messages listed above; a **missing field** inside an
entry (say `apis`) would raise a `KeyError` that the tool wrapper turns into an error (**probable**: not traced, not tested). The shipped
file is checked by tests: the drawstress entry must have a 64-character hash and an `https` url, `mtl-x64` must be
marked `rosetta`, and `bgfx-examples` must come from `workloads-8` (`tests/test_recording.py:127-129`, `:281-284`; not run).

**To add a program:** build and upload an archive with the workflow, take the SHA-256 of what was uploaded, add the entry with its
`bytes`, and add a test that reads the shipped entry. Pin by hash: the code refuses anything else (`workloads.py:160-161`).

## When it fails

The first column is what the person or agent sees.

| What goes wrong | What they get | What is left | Line |
|---|---|---|---|
| A preflight check fails | The message in the [table](#what-preflight-checks-and-what-it-says) | Nothing: no process was started | `preflight.py:101-137` |
| `memory_pressure` is missing, or does not reach the percentage in 90 s | `memory_pressure is not available`, or `memory_pressure did not reach that free percentage; the Mac may already be below it` | Nothing; the helper is stopped | `recording.py:287-306` |
| The script itself refuses (label, program header, no process to attach to, disk, lock) | `recording failed (exit N): <the script's last line>`; exit 2 for arguments, 4 for disk, 3 for the lock | Nothing: the script exits before it takes the lock or before it writes | `perf_record.sh:10-24`, `:37`, `:47-50`; `recording.py:422-425` |
| Instruments fails or dies at once | `no recording at <path>` from the script, so `recording failed (exit 1): no recording at <path>` | Nothing: the trap deletes the run's files | `perf_record.sh:139-156`; `test_script_failure_cleanup` `:534` |
| Instruments dies **part-way** | See [below](#what-happens-if-instruments-dies-part-way) | | |
| The client cancels | `the recording was cancelled; nothing was saved` | Nothing (the [kill sequence](#the-kill-sequence)) | `recording.py:396-409` |
| The recording runs past its deadline | `the recording took over N s and was stopped; nothing was saved. The likely cause is a hidden window: ...` | Nothing | `recording.py:410-413` |
| The program does no GPU work | `the program did no GPU work: it ended (<reason>) after N s of recording, and its summary was not saved; check that it starts (under Wine: the Wine build, the prefix and the program's own log)` | The `.trace` only if it was asked to be kept; the message says so | `recording.py:427-436` |
| The server dies mid-recording | Nothing to see: there is no server | A watcher loop in the script stops the program and Instruments | `perf_record.sh:82-92` |
| `wine --version` hangs | The layer's version is `null`; the recording goes on | | `recording.py:140-143` |
| Two recordings race for a lock whose owner is dead (macOS) | One takes it, the other gets `another recording is running` | | `perf_record.sh:44-61`, [the data guide](./data-and-lifecycle.md#the-lock) |

### What happens if Instruments dies part-way

`xcrun xctrace record ... || true` ignores the exit status on purpose (`perf_record.sh:140-151`), so the script always continues to
`kill $sampler` (`:155`) and then:

- If there is **no** `.trace` folder, the script exits 1 with `no recording at <path>` (`:156`), and the `EXIT` trap deletes
  the run's files (`:71`). That branch is pinned by `test_script_failure_cleanup`, where a stub `xcrun` exits at once.
- If a `.trace` folder **exists** (a partial one) the script runs the report on it (`:160`). **Not reproduced**: no real
  `xctrace` was killed. By the code, two things can follow: `perf_report.py` exits non-zero (`set -e`, `:5`), the trap deletes
  the run and the error is `recording failed (exit N): <last line>`, or it writes a summary of what was readable; if that has
  no GPU intervals, the server turns it into `the program did no GPU work` and deletes the run (`recording.py:427-436`). Which
  of the two happens for a given partial trace depends on `perf_report.py`, which is the subject of a later guide.
- If **the server** is killed, not Instruments, the watcher loop in the script notices (`kill -0 $PERF_PARENT_PID`, `:84`),
  stops the program, kills `xctrace` and the report, and terminates the script, whose trap cleans up (`:82-92`).

### When the Windows engine fails

| What goes wrong | The message | Line |
|---|---|---|
| Bad label or seconds (run by hand) | `label may hold only letters, digits, '.', '_' and '-'`, `seconds must be 1 to 3600` | `perf_record_windows.py:560-564` |
| A live recording holds the lock | `another recording is running (<lock>); remove it if none is` | `:597` |
| No process matches the attach target | `no running process matches <target>` | `:475`, `:480` |
| The program cannot be started | `recording failed: <the OS's message>` (an `OSError`) | `recording.py:383-384` |
| Cancel or overrun | the two messages of step 5 | `:744-746` |
| No source gave frames, PresentMon ran | `no frame data: PresentMon saw no Present() calls from this process; it is idle, minimized, or a launcher whose game runs in another process (use perf_attach on the game)` plus PresentMon's last stderr line | `:833-839` |
| No source gave frames, no PresentMon | `no frame data: the program wrote no DRAWSTRESS_LOG, PresentMon is not installed (call presentmon_install) and DWM gave no samples (DwmGetCompositionTimingInfo needs the interactive desktop session, not SSH or a service)` | `:840-844` |

A `RuntimeError` or `ValueError` from the engine becomes a `ToolError` with the same text (`recording.py:381-382`). All of
these were **not reproduced** (no Windows machine); `test_no_frame_data_is_an_error`, `test_timeout_and_cleanup` and
`test_lock_handling` (`tests/test_perf_record_windows.py:623`, `:281`, `:87`) pin them (not run for this page).

## Known limits

Each item is a limit of today's behaviour, written down, not fixed here.

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | The script's own refusals carry a local path in the client's error: the folder in `not enough free disk on <dir>`, the lock in `another recording is running (<lock>)` and the `.trace` in `no recording at <path>`; they reach the client through the last stderr line. Preflight's messages and the script's "not an executable file" keep paths out (and a test says so), so these are the exceptions. Preflight normally refuses first, so only the race or a hand-run script shows them | `perf_record.sh:37`, `:48`, `:156`; `recording.py:424-425`; `tests/test_recording.py:565` | Confirmed by the code |
| 2 | `README.md` says the call times out "after 10 s per recorded second plus 120 s"; the code uses 15 s per second plus 180 (55 with counters) since 0.8.1 | `README.md:135-136`, `recording.py:266-269` | Confirmed: the two differ; which one the README should say is a decision for the owner |
| 3 | The Windows lock takeover is not atomic. The macOS script takes a second lock while it takes over a stale one; the Windows engine removes the stale lock and creates a new one in two steps, so two processes that both see the same dead owner can both end up holding it | `perf_record_windows.py:583-597` against `perf_record.sh:44-61` | Probable (read from the code; not reproduced: it is a race). The single worker thread makes it unlikely inside one server |
| 4 | PresentMon's hash is checked when it is installed, not when it is used; a file named by `PRESENTMON_EXE` or found on the `PATH` is run unchecked | `perf_record_windows.py:420-430`, `workloads.py:196-204` | Confirmed |
| 5 | A Windows recording with the `drawstress-log` source leaves `<run>.drawstress.log` (and `<run>.presentmon.csv` when PresentMon ran) on disk: only a failed run deletes them. The [data guide](./data-and-lifecycle) lists `.drawstress.log` in its file table, and the quota ignores both | `perf_record_windows.py:632-633`, `:762-764`, `:937-941`; `retention.py:30-43` | Confirmed by the code; not reproduced |
| 6 | Cancelling a Windows recording waits for PresentMon first: `presentmon_proc.wait(timeout=15)` runs before the cancel branch, so a cancel can take up to 15 s to act | `perf_record_windows.py:711-723`, `:726-746` | Probable |
| 7 | `perf_record` stops **every** process with the program's name when it ends or is cancelled, not only the one it started: a second copy of the same program, such as an editor you had open, ends too | `perf_record.sh:80`, `recording.py:255-263` | Confirmed; the tool's description says "every process named like the program" (`recording.py:42`) |
| 8 | The first progress message says "up to N s including read-back" on Windows too, where there is no read-back | `recording.py:371-372` | Confirmed (cosmetic) |
| 9 | On Windows nothing refuses an api that cannot run there (`mtl`, `vk`, `mtl-x64` are macOS programs): `os.access(..., X_OK)` is true for any file on Windows, so preflight passes and `Popen` fails | `workloads.py:88-89`, `preflight.py:117-119` | Probable: not reproduced |
| 10 | `.drawstress.log` lines are means, so a drawstress run on Windows has no 1% low, stutter rate or jitter | `perf_record_windows.py:859-862` | Confirmed (a limit of the source, not a bug) |
| 11 | The DWM source measures the whole desktop's compositor, not the program | `perf_record_windows.py:351-363`, `:819-829` | Confirmed |
| 12 | The cache of test programs has no cleanup | `workloads.py:147-176` | See the [data guide](./data-and-lifecycle.md#the-cache-is-not-the-recordings) |
| 13 | How long Wine's start-up takes, and so whether 30 s is the right number, is not measured here | `metal_trace_mcp.py:27` | Not reproduced |
| 14 | What VegaFlow is is not documented in the guides | `perf_record_windows.py:181-283` | Pending confirmation |

## Touching it without breaking it

- A new refusal: put it in `preflight.check` **before** anything that starts a process, make the message say what to do, keep
  paths out of it, and add the test next to its siblings in `tests/test_preflight.py` (each existing one asserts the
  wording). If the shell script should refuse too, repeat it there with its exit code and update the
  [table](#what-each-layer-repeats).
- A new variable for the script: set it in `record_run` (`recording.py:360-370`), read it in `perf_record.sh` and document it in
  the [table](#step-3-the-environment-the-script-gets). `PERF_ENV` pairs are split on spaces: no value may
  hold one (`check_env`).
- Anything the server kills on cancel must be listed **before** it starts, as `record_run` does with `before` and `ktraces`
  (`recording.py:386-388`): a cleanup that deletes what it did not create deletes a person's file.
- A new field in the summary: write it in the shared code in `metrics.py` for both engines, not by hand twice (see the
  [data guide](./data-and-lifecycle.md#touching-it-without-breaking-it)).
- A new test program: see [To add a program](#the-workloads-file). Never pin by tag or by name: the hash is the identity.
- Windows code must not call `os.kill` to ask whether a process is alive (it ends the process there): use
  `is_process_alive` (`preflight.py:18-20`).
- The engine's `finally` deletes every file that starts with the run's name (`:937-941`); a new file for a Windows run
  should keep the run's name as its prefix so it is cleaned and pruned with the run.

## Evidence: the commands and their real output

Collected on 2026-11-16 on an Apple silicon Mac. All commands only read. Paths are shortened: the home folder is `~`. The
session that collected them could run read-only commands (`rg`, `sed`, `jq`, `ls`, `du`), not Python or the scripts, so
nothing below is the output of a recording or of a check run live: what a check *says* is read from the line that raises it.

### E1 Every message preflight can raise, with its line

```text
$ rg -n "raise paths.ToolError" src/metal_gpu_trace/preflight.py | cut -c1-175
71:        raise paths.ToolError("the free disk space cannot be read for the runs or the temporary folder") from None
108:        raise paths.ToolError("seconds is a whole number from 1 to 3600")
110:        raise paths.ToolError("environ is a mapping of text")
113:        raise paths.ToolError("wine is a path or native or attach, and the command a list of strings")
116:        raise paths.ToolError("no Wine at bin/wine inside that Wine directory (pass native for a macOS program)")
119:        raise paths.ToolError(f"{name} is not an executable file")
121:        raise paths.ToolError("xcrun is not on PATH: install Xcode or the command line tools (xcode-select --install)")
130:            raise paths.ToolError(f"not enough free disk on {what}: {free} GB free, {need} GB needed "
133:        raise paths.ToolError("the screen is locked: a locked session leaves the program's frames unpaced by the display, "
136:        raise paths.ToolError("another recording is running; one runs at a time. If none is, remove the lock folder "
```

Each line is trimmed to 175 characters by `cut`. The order of the line numbers (108 before 116 before 121 before 130
before 133 before 136) is the order the checks run. Running `preflight.check` itself, with a stub for each failure, was
**not reproduced**; `tests/test_preflight.py` has one test per failure (`:65` to `:162`), not run for this page.

### E2 What the script itself refuses, and with which exit code

```text
$ rg -n "exit [0-9]+|exit \$\{" src/metal_gpu_trace/perf_record.sh | cut -c1-170
10:[[ $label =~ '^[A-Za-z0-9._-]+$' ]] || { echo "label may hold only letters, digits, '.', '_' and '-'" >&2; exit 2; }
11:[[ $seconds == <1-3600> ]] || { echo "seconds must be 1 to 3600" >&2; exit 2; }
12:[[ $wine == (native|attach) || -x $wine/bin/wine ]] || { echo "no Wine at $wine/bin/wine (or pass native or attach)" >&2; exit 2; }
13:[[ $wine != native || ( -f $1 && -x $1 ) ]] || { echo "${1:t} is not an executable file" >&2; exit 2; }
18:    { echo "${1:t} is not a program the system can run (no Mach-O or #! header)" >&2; exit 2; }
24:  [[ -n $pid ]] && kill -0 $pid 2>/dev/null || { echo "no running process matches $1" >&2; exit 2; }
37:  (( free >= need )) || { echo "not enough free disk on $dir: $free GB free, $need GB needed (PERF_MIN_FREE_GB overrides)" >&2; exit 4; }
49:  exit 3
55:  trap 'exit 130' INT TERM
74:trap 'rm -rf $out/$name.*(N); exit 143' TERM
156:[ -d $out/$name.trace ] || { echo "no recording at $out/$name.trace" >&2; exit 1; }
```

(The lock message is the `echo` of the line before 49, `perf_record.sh:48`.) Lines 12, 37, 48 and 156 print a path or a folder; 13 and
18 print only the file name, which a test asserts (`tests/test_recording.py:565`, limit 1). Running the script with a
bad argument was **not reproduced**.

### E3 The numbers: deadline and disk, by the formulas of the code

```text
$ jq -n -c '{deadline_s:([20,30,60]|map(.*15+180)), deadline_counters_s:([20,30,60]|map(.*55+180)), disk_gb:([20,30,60]|map(2+((.*8+9)/10|floor))), disk_gb_windows:1}'
{"deadline_s":[480,630,1080],"deadline_counters_s":[1280,1830,3480],"disk_gb":[18,26,50],"disk_gb_windows":1}
```

The formulas are `seconds × 15 + 180` (`recording.py:269`, 55 with counters) and `2 + (seconds × 8 + 9) / 10` in
integer division (`preflight.py:50`). They reproduce the figures the server states: 630 s for 30 s of Wine, and "26 GB for 30 s, 50
GB for 60 s" (`metal_trace_mcp.py:27-28`). These are the code's formulas evaluated by `jq`, not a measurement of a
real recording.

### E4 The pinned test programs

```text
$ jq -r '.workloads|to_entries[]|"\(.key)\t\(.value.sha256)\t\(.value.bytes)\t\(.value.url|split("/")|.[7:]|join("/"))\t\(.value.apis|keys|join(","))"' src/metal_gpu_trace/data/workloads.json
drawstress	2b3b01fa2dd0a7d5a1629046305319130d58ce4d843bd22c3f736071c0bfde2e	9291979	workloads-3/drawstress-workloads-3.tar.gz	d3d11,d3d12,mtl,mtl-x64,vk
bgfx-examples	1d120363981ced4ae01dad57085258206fbc84f35bd9bcdcfe656b1af355d091	57350072	workloads-8/bgfx-examples-workloads-8.tar.gz	d3d11,d3d12,mtl
godot	a85320f08e1ac2721288441a5317796de4673a6df6fc727b71c135503adc09c5	1525	workloads-9/godot-workloads-9.tar.gz	d3d12,mtl

$ jq -r '.workloads.godot.downloads[]|"\(.into)\t\(.bytes)\t\(.sha512[0:16])"' src/metal_gpu_trace/data/workloads.json
bin/mac	170622178	38aa16e5bba20839
bin/win	86013866	83decd58fdf67b9d

$ jq -r '.workloads["bgfx-examples"].examples|length' src/metal_gpu_trace/data/workloads.json
30
$ jq -r '.workloads["bgfx-examples"].example_traits|length' src/metal_gpu_trace/data/workloads.json
30

$ jq -r '.workloads.drawstress.apis|to_entries[]|"\(.key) \(.value|tostring)"' src/metal_gpu_trace/data/workloads.json
mtl {"program":"drawstress","args":"--mtl","wine":false}
mtl-x64 {"program":"drawstress-x64","args":"--mtl","wine":false,"rosetta":true}
vk {"program":"drawstress","args":"--vk","wine":false,"moltenvk":true}
d3d11 {"program":"drawstress.exe","args":"--d3d11","wine":true}
d3d12 {"program":"drawstress.exe","args":"--d3d12","wine":true}
```

(The URL's host and project are cut by `.[7:]`; the full URL is `https://github.com/<project>/releases/download/<tag>/<file>`.)
The sizes are the ones the code uses as `--max-filesize`. A `curl` of these URLs, and a `shasum` of what is published, were **not reproduced**.

### E5 What the cache holds, against the pins

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

$ cd ~/Library/Caches/metal-gpu-trace
$ ls -1 drawstress-2b3b01fa2dd0/drawstress
BUILD.txt
LICENSE-bgfx
bgfx-drawstress-env.patch
drawstress
drawstress-x64
drawstress.exe

$ ls -1 godot-a85320f08e1a/godot godot-a85320f08e1a/godot/bin
godot-a85320f08e1a/godot:
BUILD.txt
bin
project

godot-a85320f08e1a/godot/bin:
mac
win

$ sed -n 2,6p drawstress-2b3b01fa2dd0/drawstress/BUILD.txt
GENie f7055e309a5c2bc28d7abd35960e14b9864fc5ea
bgfx 71539c41e7e782ccf30f19ae4498d25ddc7bc68c
bx d4e6ed3cf4f75c355bb04088bc1c13cd919aafa6
bimg 671fe06dd7012a1ab85aa931019ed16112909756
llvm-mingw 20260908 ucrt macos-universal
```

The three folder names that match a pin in E4 (`bgfx-examples-1d120363981c`, `drawstress-2b3b01fa2dd0`,
`godot-a85320f08e1a`) are the current ones; the other five do not. No `recording.lock` is in the folder: nothing is recording. The
folder names are the first 12 characters of the hash (`workloads.py:22`).

### E6 Where the server sets the script's environment

```text
$ rg -n 'env\["|PERF_OUT=|PERF_LOCK=|PERF_PARENT_PID=|PERF_ENV=' src/metal_gpu_trace/recording.py
360:    env = dict(os.environ, PERF_OUT=str(config.OUT), PERF_LOCK=str(config.LOCK), PERF_PARENT_PID=str(os.getpid()),
361:               PERF_ENV=" ".join(filter(None, [os.environ.get("PERF_ENV", ""), program_env])))
363:        env["PERF_MEMORY"] = "0"
365:        env["KEEP_TRACE"] = "1"
367:        env["PERF_PREFIX"] = BACKGROUND_PREFIX
369:        env["PERF_INSTRUMENTS"] = ";".join(filter(None, [os.environ.get("PERF_INSTRUMENTS", ""), "Metal GPU Counters"]))
370:    layer = layer or layer_of(wine, prefix, env["PERF_ENV"])
377:                label, int(seconds), wine, prefix, workdir, command, env["PERF_ENV"],
```

### E7 What the GPU families file holds

```text
$ jq -r '.families|keys|join(" ")' src/metal_gpu_trace/data/apple-gpu-families.json
Apple10 Apple7 Apple8 Apple9

$ jq -r '.families.Apple9|keys|join(" ")' src/metal_gpu_trace/data/apple-gpu-families.json
adds limits mac_chips other_chips

$ jq -r '.families|to_entries[]|"\(.key): \(.value.mac_chips|join(", "))"' src/metal_gpu_trace/data/apple-gpu-families.json
Apple7: M1, M1 Pro, M1 Max, M1 Ultra
Apple8: M2 series
Apple9: M3 series, M4 series
Apple10: M5 series

$ jq -r '.sources.feature_set_tables_date' src/metal_gpu_trace/data/apple-gpu-families.json
2026-05-21

$ rg -n "FAMILIES|WORKLOADS" src/metal_gpu_trace --glob '*.py' | cut -c1-120
src/metal_gpu_trace/workloads.py:19:    if name not in config.WORKLOADS:
src/metal_gpu_trace/workloads.py:21:    entry = config.WORKLOADS[name]
src/metal_gpu_trace/workloads.py:105:    for name, entry in config.WORKLOADS.items():
src/metal_gpu_trace/traces.py:180:    for key, family in config.FAMILIES["families"].items():
src/metal_gpu_trace/traces.py:193:        raise paths.ToolError(f"unknown family or chip {name!r}; try one of {', '.join
src/metal_gpu_trace/traces.py:195:    return {"family": key, **config.FAMILIES["families"][key], "same_on_all": config.F
src/metal_gpu_trace/traces.py:196:            "footnotes": config.FAMILIES["footnotes"], "guards": config.FAMILIES["guar
src/metal_gpu_trace/registry.py:12:RESOURCES = {"metal-trace://gpu-families": ("Apple GPU families", config.FAMILIES["ab
src/metal_gpu_trace/registry.py:15:    for key in config.FAMILIES["families"]}
src/metal_gpu_trace/config.py:35:FAMILIES = json.loads((PACKAGE_DIR / "data" / "apple-gpu-families.json").read_text(enco
src/metal_gpu_trace/config.py:36:WORKLOADS = json.loads((PACKAGE_DIR / "data" / "workloads.json").read_text(encoding="ut
```

The `rg` output has the readers of the two files: `workloads.py` reads `WORKLOADS`, `traces.py` and `registry.py` read `FAMILIES`,
and recording code reads neither (the `rg` finds no `FAMILIES` in `recording.py` or `preflight.py`).

### E8 Which source the Windows engine uses, and where it says so

```text
$ rg -n '"source": |if entries:|elif pm_intervals|elif dwm_samples' src/metal_gpu_trace/perf_record_windows.py
787:        if entries:
808:        elif pm_intervals:
819:        elif dwm_samples:
859:        if entries:
876:            "source": "drawstress-log" if entries else "presentmon" if pm_intervals else "dwm-composition",
878:        if entries:
```

(The closing `else` at line 830 is a bare keyword that this pattern does not match; it is read with `sed -n 830,844p`, which
shows the two `no frame data` errors.)

The chain `if entries` / `elif pm_intervals` / `elif dwm_samples` / `else` (line 830) is the order of the table in
[The Windows engine](#the-three-sources-of-frames-and-which-one-wins); line 859 is the one that nulls the frame-level pacing
numbers for the log. Running an engine recording was **not reproduced** (no Windows machine here).

### E9 The Windows lock and cleanup lines

```text
$ rg -n "lock_path|FileExistsError|is_process_alive" src/metal_gpu_trace/perf_record_windows.py
332:def is_process_alive(pid):
394:                if pid and not is_process_alive(pid):
555:                   cancelled=None, progress=None, lock_path=None):
574:    lock_path = pathlib.Path(lock_path) if lock_path is not None else out_dir / ".recording"
575:    lock_path.parent.mkdir(parents=True, exist_ok=True)
579:            lock_path.mkdir(exist_ok=False)
580:            (lock_path / "pid").write_text(str(os.getpid()), encoding="utf-8")
583:        except FileExistsError:
584:            owner = lock_path / "pid"
587:                stale = not is_process_alive(int(owner.read_text(encoding="utf-8").strip()))
593:                    lock_path.rmdir()
597:            raise RuntimeError(f"another recording is running ({lock_path}); remove it if none is") from None
942:        if lock_acquired and lock_path.exists():
944:                (lock_path / "pid").unlink(missing_ok=True)
945:                lock_path.rmdir()
```

Lines 590-596 are the whole takeover: remove the `pid`, `rmdir`, try again. There is no second lock around them, which is limit 3.

### E10 PresentMon: where the pin and the search live

```text
$ rg -n "find_presentmon|PRESENTMON_EXE|presentmon_dir|PRESENTMON\[" src/metal_gpu_trace/perf_record_windows.py src/metal_gpu_trace/workloads.py | cut -c1-140
src/metal_gpu_trace/workloads.py:194:    target_dir = perf_record_windows.presentmon_dir()
src/metal_gpu_trace/workloads.py:195:    target = target_dir / f"PresentMon-{PRESENTMON['version']}-x64.exe"
src/metal_gpu_trace/workloads.py:196:    if target.is_file() and file_id(target)["sha256"] == PRESENTMON["sha256"]:
src/metal_gpu_trace/workloads.py:197:        return {"installed": False, "path": str(target), "version": PRESENTMON["version"]}
src/metal_gpu_trace/workloads.py:201:        download(PRESENTMON["url"], part, PRESENTMON["bytes"] * 2)
src/metal_gpu_trace/workloads.py:202:        if file_id(part)["sha256"] != PRESENTMON["sha256"]:
src/metal_gpu_trace/workloads.py:205:    return {"installed": True, "path": str(target), "version": PRESENTMON["version"], "bytes": PRESENTM
src/metal_gpu_trace/perf_record_windows.py:415:def presentmon_dir():
src/metal_gpu_trace/perf_record_windows.py:420:def find_presentmon():
src/metal_gpu_trace/perf_record_windows.py:421:    """Returns the path of Intel's PresentMon console application, or None: $PRESENTMON_EXE, 
src/metal_gpu_trace/perf_record_windows.py:424:    explicit = os.environ.get("PRESENTMON_EXE")
src/metal_gpu_trace/perf_record_windows.py:427:    cache = presentmon_dir()
src/metal_gpu_trace/perf_record_windows.py:649:        presentmon_exe = find_presentmon()
```

The hash is compared in `workloads.py:196` and `:202` (install) and nowhere in `find_presentmon` (`:420-430`): limit 4.

### What was not reproduced

- Any recording, macOS or Windows (needs Instruments, a Windows machine and GPU time), and so every timing of the page.
- `preflight.check` itself, with a failing input, and each message as printed live (the messages are read from the
  source, E1, and pinned by tests that were not run).
- `perf_record.sh` or `perf_record_windows.py` with bad arguments, including their usage lines.
- A download: `workload_fetch`, `presentmon_install`, and a `shasum` of what the project's releases publish today.
- A partial `.trace` from an interrupted Instruments, and the cancel of a Windows recording.
- How many seconds Wine's start-up takes.

## See also

- [How it works](./how-it-works.md): layers and the path of one request.
- [Data and its lifecycle](./data-and-lifecycle.md): the files a recording leaves, the lock and the two retention settings.
- [Proof of 0.27.0](../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit): the size limit measured.
