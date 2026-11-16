# Two rules: one at a time, and 30 seconds under Wine

**Reader:** people who change the lock or the advice about recording length. Reviewed 2026-11-16. Labels: see [Recording](./index.md#how-to-read-the-labels).

Español: [Dos reglas](../../es/guides/grabar/reglas.md)

**In short:** only one recording may run at a time on a Mac, because two programs sharing the graphics chip spoil each
other's numbers. Under Wine, a recording should last 30 seconds or more, because the first seconds are spent starting up
and are not the program's normal behaviour. Example: a second `perf_record` while one is running is refused before it
starts anything.

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
next"; the key is described in the
[data guide](../data-and-lifecycle/json-keys.md#keys-of-a-macos-summary-present-only-on-a-condition)).

**Why one lock for every folder.** Each project has its own runs folder, but there is one GPU: the lock lives in the
cache folder, not in the runs folder (`config.py:41-42`; `test_recordings_into_two_folders_run_one_at_a_time`,
`tests/test_recording.py:854`).

The lock's own life (take over a dead owner, release, who removes it) is in the
[data guide](../data-and-lifecycle/cache-and-lock.md#the-lock). What is new here: a held lock makes the second recording refuse
**before** it starts anything (`preflight.py:135-137`), with `another recording is running; one runs at a time. If none
is, remove the lock folder (METAL_TRACE_LOCK names it)`.

## Why 30 seconds or more under Wine

The instruction reads: "Under Wine record 30 s or more: Wine's start-up takes part of the recording"
(`metal_trace_mcp.py:27`; the same sentence is in the `seconds` description, `registry.py:39`, and in `README.md:138`).
That is **confirmed as the project's stated reason**. What is behind it, in two parts:

| Part | What the code says | Label |
|---|---|---|
| **The first seconds are not the program's steady state.** Wine boots, the program opens its window and compiles its shaders while Instruments is already recording | `skip_s` exists to cut that start-up off a comparison (`metal_trace_mcp.py:31`); `analysis._startup_skip_s` looks for shader-compile hitches that end within the first quarter of the run (`analysis.py:670-690`). A 30 s run keeps most of its length after the start-up. **How many seconds the start-up takes was not measured for this guide**; the number 30 is the project's rule of thumb | **probable** |
| **It is not the 100-frame rule.** A run under 100 frames is flagged separately | `analysis.py:378`, `:499`, `:655`: "under 100 frames: too short to judge; record 30 s or more". At 60 FPS 100 frames is under 2 seconds, so 100 frames is a floor for comparing at all, and 30 s is about the start-up | **speculation**: derived by arithmetic from two rules the code states, not from a measurement |

The cost side is real and is why the deadline is what it is:

- A 30 s Wine D3D12 recording took a 614 MB trace and about 93 s just to read (`CHANGELOG.md`, 0.8.1).
- Each recorded second needs about 0.8 GB of temporary disk (`perf_record.sh:33`, a code comment: **probable**).
- Native Metal runs are shorter: one changelog entry mentions native 10 s runs next to 30 s runs under Wine
  (`CHANGELOG.md:309`).
