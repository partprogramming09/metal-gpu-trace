# Preflight

**Reader:** people who add or change a refusal in `preflight.py` or in `perf_record.sh`. Reviewed 2026-11-16. Labels: see [Recording](./index.md#how-to-read-the-labels).

Español: [Preflight](../../es/guides/grabar/preflight.md)

**In short:** before anything starts, the server checks in milliseconds that the recording can work: valid numbers, the
program and Wine exist, Xcode's tools are installed, there is enough disk, the screen is unlocked and nobody else is
recording. The first check that fails stops the call with a sentence that says what to do. Nothing was started, so there
is nothing to clean up. Example: `seconds=5000` ends at once with `seconds is a whole number from 1 to 3600`.

`preflight.check` (`preflight.py:101-137`) runs six checks in a fixed order and raises a `ToolError` at the first one
that fails ([E1](./evidence.md)). All checks are in milliseconds and none starts a process, except reading the screen
state (`ioreg`, timeout 10 s, `perf_report.py:593-604`).

![Seven boxes in a row, left to right: arguments, program, xcrun, disk, screen, lock and start. Under each of the first six the exact message it refuses with is written. If all pass, the recording starts.](./img/preflight-checks.png)
*Figure 1. The checks of `preflight.check` and the message each one gives. HTML source: `img/preflight-checks.html`.*

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

## How the numbers in check 4 come out

- The need is `PERF_MIN_FREE_GB` when it is a plain number, else `2 + (seconds × 8 + 9) / 10` in integer division
  (`preflight.py:44-50`), which is 18 GB for 20 s, 26 for 30 s and 50 for 60 s ([E3](./evidence.md)). Under Windows it
  is 1 GB, because there is no Instruments (`:50`). The shell script computes the same formula (`perf_record.sh:34`);
  `test_disk_formula_matches_the_shell` (`tests/test_preflight.py:101`) pins that the two agree.
- The temporary folder is `TMPDIR` of the request's environment, or `/tmp` (`:126`): that is where `xctrace` writes its
  `.ktrace` files while recording.
- A runs folder that does not exist yet is measured at its nearest existing parent (`free_gb`, `:61-71`).

## The lock check

`lock_owner_alive` (`:74-93`) is built for a folder anyone can write to:

The reason is the lock's location: a hostile or broken `pid` file must not hang a recording, signal a whole process
group or crash the check.

| It does | Against |
|---|---|
| Refuses to follow a link | (the page does not state a separate reason) |
| Reads at most 32 bytes with a non-blocking open | a hang (a pipe) |
| Accepts only ASCII digits up to 10 characters and a pid from 1 to 2³¹−1 | signalling a whole process group (pid 0 or −1, `:16`) |
| Treats anything odd as "no live owner" | a crash of the check |

On Windows `os.kill` is never used, since there it ends the process; `perf_record_windows.is_process_alive` asks
`OpenProcess` instead (`:18-20`). `test_hostile_pid_files_are_not_a_live_owner` (`tests/test_preflight.py:336`) pins the
odd cases.

## What preflight does not check

| Not checked | Who catches it, and how | Line |
|---|---|---|
| That a process to attach to exists (`perf_attach` passes preflight with any text) | The script: `no running process matches <name>` (exit 2). The Windows engine: the same as a `RuntimeError`. It arrives as `recording failed ...` or as a plain `ToolError` | `perf_record.sh:24`; `perf_record_windows.py:475`, `:480` |
| The Wine prefix, the working directory, the `api` against the platform | Used later, by the script or by `Popen` | |
| That the program is a Mach-O | The script compares the first four bytes against a list of Mach-O magic numbers (and ELF and `#!`, "for the Linux CI") and refuses with `<name> is not a program the system can run (no Mach-O or #! header)` | `perf_record.sh:14-19` |
| The label | `record` checks it before preflight, and the script checks it again | `recording.py:312`; `perf_record.sh:10` |

## What each layer repeats

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

The script's exit codes and messages are in [E2](./evidence.md).
