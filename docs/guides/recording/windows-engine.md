# The Windows engine

**Reader:** people who change `perf_record_windows.py` or who need to know why a Windows recording has no GPU timing per encoder. Reviewed 2026-11-16. Labels: see [Recording](./index.md#how-to-read-the-labels).

**In short:** Windows has no Instruments, so a separate engine records a Windows program by measuring when each frame
was shown on screen. It picks the best of three sources of frame data and writes the same kind of summary macOS does, with
some blocks empty. Example: for a game with PresentMon installed, the engine starts the game and PresentMon, waits the
requested seconds, and turns PresentMon's rows into the summary.

`perf_record_windows.py` is the whole of a Windows recording. `record_run` calls it when `sys.platform == "win32"`
(`recording.py::run_recording`), through a late import because something else may have imported the module already (`recording.py::run_recording`),
and ends in the same `finish` as macOS (`recording.py::run_recording`). It can run by hand: `python src\metal_gpu_trace\perf_record_windows.py <label> <seconds> <wine|native|attach> <prefix> <workdir> <command...>`
(`perf_record_windows.py::main`; running it on the Mac without arguments prints the usage line, **not reproduced**).

![Eight boxes in two rows joined by arrows. Top row: lock, program, frame source (a decision), one-second loop. Bottom row: stop and clean up, which frames (a decision), write, and recording.finish.](./img/windows-engine.png)
*Figure 1. One Windows recording. HTML source: `img/windows-engine.html`.*

## Why a separate engine, and what it measures

Instruments exists only on macOS: no `xctrace`, no Metal System Trace, no per-encoder timing, no `.trace`. The engine
measures **when frames were presented** and builds the same summary shape through `metrics.py` (`:24-28`, `perf_record_windows.py::record_windows`),
with several blocks empty or fixed: `missing_tables` lists three Metal tables by name, `metal_memory_mib` is
`{"samples": 0}`, and `encoders` and `gpu_idle` come from the spans of the one source that has any ([E8](./evidence.md)).
The keys are in the [data guide](../data-and-lifecycle/json-keys.md#a-windows-summary).

## The three sources of frames, and which one wins

| Order | Source | `gpu.source` | What it gives | What it cannot give |
|---|---|---|---|---|
| 1 | The program's own log: `DRAWSTRESS_LOG`, one line per batch of frames (`dim`, `draws`, `frame_us`, `frames`) | `drawstress-log` | GPU time per frame (a mean per line) and spans for the encoder statistics | A frame-level distribution: 1% low, 0.1% low, stutter rate and jitter are `null` (`perf_record_windows.py::record_windows`), each line being a mean |
| 2 | PresentMon rows: `MsBetweenPresents` and, when the column exists and is positive, `MsGPUTime` | `presentmon` | One row per `Present()` of that process, with its GPU time | Per-encoder timing |
| 3 | A 1 ms thread reading the compositor (`DwmGetCompositionTimingInfo`) | `dwm-composition` | Intervals between composed frames of the **whole desktop** | GPU time per frame, anything specific to the process |
| none | | | | The run fails: `no frame data` |

The order is that of the `if` chain (`perf_record_windows.py::record_windows`), so a **drawstress run with PresentMon installed
still runs PresentMon** (it starts in `perf_record_windows.py::record_windows`, before the log is read) **but its rows are not used**: the log wins
(confirmed by the code; not reproduced).

Why three: the log is exact for the project's own test program, PresentMon fits any other program, and the compositor is
a last resort needing no tool. Its sampler counts only the interval between two consecutive composed frames: a jump of
several frames is dropped, not split into equal parts (`perf_record_windows.py::sample_dwm_frame_times`), so it never invents frames.

## Step by step (Figure 1)

| # | Stage | What happens | Line |
|---|---|---|---|
| 1 | **Lock** | The server passes `config.LOCK`, the same folder macOS uses; by hand, the engine falls back to `<runs>/.recording` (`perf_record_windows.py::record_windows`). `mkdir`, write the pid; if it exists and its owner is dead, remove it and try once more (two attempts), otherwise `another recording is running (<lock>); remove it if none is` ([E9](./evidence.md)) | `perf_record_windows.py::record_windows` |
| 2 | **Program** | With `attach`, `find_attached_process` finds the pid by number or by a name inside the process name (highest pid wins, `perf_record_windows.py::find_attached_process`). Otherwise it merges `program_env` and `PERF_ENV` into the environment, sets `DRAWSTRESS_LOG` to `<runs>/<name>.drawstress.log` and starts the program with `Popen` | `perf_record_windows.py::record_windows` |
| 3 | **Frame source** | If `find_presentmon` found one, start it with `--process_id`, `--timed <seconds>`, `--terminate_after_timed`, `--stop_existing_session`; otherwise start the DWM thread | `perf_record_windows.py::record_windows` |
| 4 | **The loop** | Once per second: sample the working set (`rss.csv`), check the deadline and cancel flag, stop early if the program exited by itself. Progress every 5 s | `perf_record_windows.py::record_windows` |
| 5 | **Stop** | Stop the DWM thread; wait up to 15 s for PresentMon, killing it if it does not stop; on cancel or overrun, kill the program tree, delete every file starting with the run's name and raise `the recording was cancelled; nothing was saved` or `the recording took over N s and was stopped; nothing was saved` (`perf_record_windows.py::record_windows`). If the recording completed and the program is still alive, terminate it, then kill its tree | `perf_record_windows.py::record_windows` |
| 6 | **Which frames** | The table above | `perf_record_windows.py::record_windows` |
| 7 | **Write** | The `frames.csv.gz` table, the statistics (pacing numbers from `perf_report.frame_pacing`, the function macOS uses, `perf_record_windows.py::compute_precision_telemetry`), the summary, the `common` block, the `.json`, and `KEEP_RUNS` through its own `clean_runs` (`perf_record_windows.py::clean_runs`, `perf_record_windows.py::record_windows`; it skips the `.trace`) | `perf_record_windows.py::record_windows` |
| 8 | **Finish** | Back in `record_run`, `finish` adds `layer`, `context`, `tier` and the disk limit | `recording.py::record_run` |

A `finally` runs whenever the recording did not succeed: it stops the DWM thread and PresentMon, kills the program it
started (never an attached one), deletes every file starting with the run's name, then frees the lock (`perf_record_windows.py::record_windows`). The lock is released on success too.

## What differs from macOS

| | macOS | Windows |
|---|---|---|
| Recorder | `perf_record.sh` driving `xctrace` | `perf_record_windows.py`, in the server's own process |
| Tiers | `light`, `standard`, `deep` | `deep` refused (`recording.py::tool_perf_record`); `memory` has no effect: no Metal memory table |
| `memory_free_pct`, `background` | allowed | refused (`recording.py::check_levers`) |
| Disk needed | `2 + 0.8 GB` per second, in `TMPDIR` and the runs folder | 1 GB, in the runs folder (`preflight.py::disk_needed`, `preflight.py::check`) |
| `xcrun`, screen | checked | not checked (`preflight.py::check`) |
| Program's stop at the end | by name (`native`) or `wineserver -k` | the process tree (`perf_record_windows.py::kill_process_tree`) |
| Wine | yes | no: `wine` becomes `native` when none is given (`recording.py::tool_perf_record`), and an api marked `wine: true` runs natively (`workloads.py::workload_command`) |
| Lock life | `mkdir` + takeover under a second lock | `mkdir` + one stale takeover, no second lock ([limit 3](./limits.md)) |
| Frame table | `frames.csv.gz` with one `gpu_ms_<channel>` per channel | `frames.csv.gz` with `gpu_ms_draw` and `gpu_ms_total` (`perf_record_windows.py::record_windows`) |

## Hardware facts for the `device` block

It reads Win32 for the processor, RAM and OS version, and when a `vegaflow_daemon.exe` is found next to the clone, a
`--system-info` call with a 1 s timeout that adds CPU and GPU architecture names (`collect_device_info`, `daemon_info`,
`daemon_candidates`). VegaFlow is a separate, optional Windows daemon for AMD APUs: this package only runs its
`--system-info` and answers nothing else of it ([limit 14](./limits.md)). Set `METAL_TRACE_DAEMON_NAMES` (comma-separated
file names, no paths) to look for a daemon with another name too.

A null, blank or non-text architecture adds no key. When a daemon was found but gave no usable answer, the `device` block
gets `daemon_info_error`: `timeout`, `invalid_json` (not JSON, or not an object) or `missing` (it would not run, exited
non-zero or printed nothing); the daemon's path is never in it. Without a daemon, nothing is added: that is the normal case.
The recording still falls back to the Win32 facts.
