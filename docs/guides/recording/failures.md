# When it fails, and touching it without breaking it

**Reader:** people who debug a refused, stopped or empty recording, and people who change the recorder. Reviewed 2026-11-16. Labels: see [Recording](./index.md#how-to-read-the-labels).

**In short:** whatever goes wrong, a recording either gives a summary or leaves nothing behind: no half-finished files
and no stuck lock. This page lists, for each failure, the message seen and what is left on disk, then the rules for
changing the recorder so the cleanup keeps working. Example: if the client cancels, the answer is
`the recording was cancelled; nothing was saved` and the runs folder is as it was.

## macOS

| What goes wrong | What they get | What is left | Line |
|---|---|---|---|
| A preflight check fails | The message in the [table](./preflight.md) | Nothing: no process was started | `preflight.py:101-137` |
| `memory_pressure` is missing, or does not reach the percentage in 90 s | `memory_pressure is not available`, or `memory_pressure did not reach that free percentage; the Mac may already be below it` | Nothing; the helper is stopped | `recording.py:287-306` |
| The script itself refuses (label, program header, no process to attach to, disk, lock) | `recording failed (exit N): <the script's last line>`; exit 2 for arguments, 4 for disk, 3 for the lock | Nothing: the script exits before it takes the lock or writes | `perf_record.sh:10-24`, `:37`, `:47-50`; `recording.py::run_recording` |
| Instruments fails or dies at once | `recording failed (exit 1): no recording at <path>` | Nothing: the trap deletes the run's files | `perf_record.sh:139-156`; `test_script_failure_cleanup` `:534` |
| Instruments dies **part-way** | See [below](#what-happens-if-instruments-dies-part-way) | | |
| The client cancels | `the recording was cancelled; nothing was saved` | Nothing (the [kill sequence](./macos-journey.md#the-kill-sequence)) | `recording.py:396-409` |
| The recording runs past its deadline | `the recording took over N s and was stopped; nothing was saved. The likely cause is a hidden window: ...` | Nothing | `recording.py::run_recording` |
| The program does no GPU work | `the program did no GPU work: it ended (<reason>) after N s of recording, and its summary was not saved; check that it starts (under Wine: the Wine build, the prefix and the program's own log)` | The `.trace` only if it was asked to be kept; the message says so | `recording.py::run_recording` |
| The server dies mid-recording | Nothing to see | A watcher loop in the script stops the program and Instruments | `perf_record.sh:82-92` |
| `wine --version` hangs | The layer's version is `null`; the recording goes on | | `recording.py::layer_of` |
| Two recordings race for a lock whose owner is dead | One takes it, the other gets `another recording is running` | | `perf_record.sh:44-61`, [data guide](../data-and-lifecycle/cache-and-lock.md#the-lock) |

### What happens if Instruments dies part-way

`xcrun xctrace record ... || true` ignores the exit status on purpose (`perf_record.sh:140-151`), so the script always
continues to `kill $sampler` (`:155`) and then:

- **No** `.trace` folder: exit 1 with `no recording at <path>` (`:156`), and the `EXIT` trap deletes the run's files
  (`:71`). Pinned by `test_script_failure_cleanup`, where a stub `xcrun` exits at once.
- A `.trace` folder **exists** (partial): the script runs the report on it (`:160`). **Not reproduced**: no real `xctrace`
  was killed. By the code, either `perf_report.py` exits non-zero (`set -e`, `:5`), the trap deletes the run and the error
  is `recording failed (exit N): <last line>`, or it writes a summary of what was readable; with no GPU intervals the
  server turns it into `the program did no GPU work` and deletes the run (`recording.py::run_recording`). Which happens depends
  on `perf_report.py`, the subject of a later guide.
- **The server** is killed, not Instruments: the script's watcher loop notices (`kill -0 $PERF_PARENT_PID`, `:84`), stops
  the program, kills `xctrace` and the report, and ends the script, whose trap cleans up (`:82-92`).

## The Windows engine

| What goes wrong | The message | Line |
|---|---|---|
| Bad label or seconds (run by hand) | `label may hold only letters, digits, '.', '_' and '-'`, `seconds must be 1 to 3600` | `perf_record_windows.py:560-564` |
| A live recording holds the lock | `another recording is running (<lock>); remove it if none is` | `:597` |
| No process matches the attach target | `no running process matches <target>` | `:475`, `:480` |
| The program cannot be started | `recording failed: <the OS's message>` (an `OSError`) | `recording.py:383-384` |
| Cancel or overrun | the two messages of [step 5](./windows-engine.md#step-by-step-figure-1) | `:744-746` |
| No frames, PresentMon ran | `no frame data: PresentMon saw no Present() calls from this process; it is idle, minimized, or a launcher whose game runs in another process (use perf_attach on the game)` plus PresentMon's last stderr line | `:833-839` |
| No frames, no PresentMon | `no frame data: the program wrote no DRAWSTRESS_LOG, PresentMon is not installed (call presentmon_install) and DWM gave no samples (DwmGetCompositionTimingInfo needs the interactive desktop session, not SSH or a service)` | `:840-844` |

A `RuntimeError` or `ValueError` from the engine becomes a `ToolError` with the same text (`recording.py:381-382`). All
**not reproduced** (no Windows machine); `test_no_frame_data_is_an_error`, `test_timeout_and_cleanup` and
`test_lock_handling` (`tests/test_perf_record_windows.py:623`, `:281`, `:87`) pin them (not run for this guide).

## Touching it without breaking it

| You add | Do this |
|---|---|
| A new refusal | Put it in `preflight.check` **before** anything that starts a process, make the message say what to do, keep paths out, add the test beside its siblings in `tests/test_preflight.py` (each asserts the wording). If the script should refuse too, repeat it there with its exit code and update the [table](./preflight.md#what-each-layer-repeats) |
| A new variable for the script | Set it in `record_run` (`recording.py:360-370`), read it in `perf_record.sh`, document it in the [table](./macos-journey.md#step-3-the-environment-the-script-gets). `PERF_ENV` pairs are split on spaces: no value may hold one (`check_env`) |
| Anything the server kills on cancel | List it **before** it starts, as `record_run` does with `before` and `ktraces` (`recording.py:386-388`): a cleanup that deletes what it did not create deletes a person's file |
| A new field in the summary | Write it in the shared code in `metrics.py` for both engines (see the [data guide](../data-and-lifecycle/limits.md#touching-it-without-breaking-it)) |
| A new test program | See [To add a program](./data-files.md#the-workloads-file). Never pin by tag or name: the hash is the identity |
| Windows code that asks whether a process is alive | Not `os.kill` (it ends the process there): use `is_process_alive` (`preflight.py:18-20`) |
| A new file for a Windows run | The engine's `finally` deletes every file starting with the run's name (`:937-941`): keep it as prefix so it is cleaned and pruned with the run |
