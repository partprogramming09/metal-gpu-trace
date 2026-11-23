# Known limits

**Reader:** people who decide what to fix next in recording. Reviewed 2026-11-16. Labels: see [Recording](./index.md#how-to-read-the-labels).

**In short:** things recording does today that a reader might not expect: a few error messages show a local path, the
README and the code disagree on the deadline, some Windows details are rougher than on macOS. Each item says where it
is in the code and how sure we are; none is fixed by this guide.

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | The script's own refusals carry a local path in the client's error: the folder in `not enough free disk on <dir>`, the lock in `another recording is running (<lock>)` and the `.trace` in `no recording at <path>`; they reach the client through the last stderr line. Preflight's messages and the script's "not an executable file" keep paths out (and a test says so), so these are the exceptions. Preflight normally refuses first, so only the race or a hand-run script shows them | `perf_record.sh:37`, `:48`, `:156`; `recording.py::run_recording`; `tests/test_recording.py::test_script_failure_cleanup` | Confirmed by the code |
| 2 | `README.md` says the call times out "after 10 s per recorded second plus 120 s"; the code uses 15 s per second plus 180 (55 with counters) since 0.8.1 | `README.md:135-136`, `recording.py::deadline` | Resolved in Unreleased: the README now says what the code does (`CHANGELOG.md`) |
| 3 | The Windows lock takeover is not atomic. The macOS script takes a second lock while it takes over a stale one; the Windows engine removes the stale lock and creates a new one in two steps, so two processes that both see the same dead owner can both end up holding it | `perf_record_windows.py::record_windows` against `perf_record.sh:44-61` | Probable (read from the code; not reproduced: it is a race). The single worker thread makes it unlikely inside one server |
| 4 | PresentMon's hash is checked when it is installed, not when it is used; a file named by `PRESENTMON_EXE` or found on the `PATH` is run unchecked | `perf_record_windows.py::find_presentmon`, `workloads.py::tool_presentmon_install` | Confirmed |
| 5 | A Windows recording with the `drawstress-log` source leaves `<run>.drawstress.log` (and `<run>.presentmon.csv` when PresentMon ran) on disk: only a failed run deletes them. The [data guide](../data-and-lifecycle/index.md) lists `.drawstress.log` in its file table, and the quota ignores both | `perf_record_windows.py::record_windows`; `retention.py::size_of` | Confirmed by the code; not reproduced |
| 6 | Cancelling a Windows recording waits for PresentMon first: `presentmon_proc.wait(timeout=15)` runs before the cancel branch, so a cancel can take up to 15 s to act | `perf_record_windows.py::record_windows` | Probable |
| 7 | `perf_record` stops **every** process with the program's name when it ends or is cancelled, not only the one it started: a second copy of the same program, such as an editor you had open, ends too | `perf_record.sh:80`, `recording.py::kill_program` | Confirmed; the tool's description says "every process named like the program" (`recording.py::tool_perf_record`) |
| 8 | The first progress message says "up to N s including read-back" on Windows too, where there is no read-back | `recording.py::run_recording` | Resolved in Unreleased: on Windows the line is "up to N s" |
| 9 | On Windows nothing refuses an api that cannot run there (`mtl`, `vk`, `mtl-x64` are macOS programs): `os.access(..., X_OK)` is true for any file on Windows, so preflight passes and `Popen` fails | `workloads.py::workload_command`, `preflight.py::check` | Probable: not reproduced |
| 10 | `.drawstress.log` lines are means, so a drawstress run on Windows has no 1% low, stutter rate or jitter | `perf_record_windows.py::record_windows` | Confirmed (a limit of the source, not a bug) |
| 11 | The DWM source measures the whole desktop's compositor, not the program | `perf_record_windows.py::sample_dwm_frame_times`, `perf_record_windows.py::record_windows` | Confirmed |
| 12 | The cache of test programs has no cleanup | `workloads.py::tool_workload_fetch` | See the [data guide](../data-and-lifecycle/cache-and-lock.md#the-cache-is-not-the-recordings) |
| 13 | How long Wine's start-up takes, and so whether 30 s is the right number, is not measured here | `metal_trace_mcp.py::INSTRUCTIONS` | Not reproduced |
| 14 | What VegaFlow is was not documented in the guides | `perf_record_windows.py` (`collect_device_info`) | Resolved in Unreleased: see [the Windows engine](./windows-engine.md#hardware-facts-for-the-device-block) |
