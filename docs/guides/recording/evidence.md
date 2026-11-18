# Evidence: preflight, script, deadline, Windows engine

**Reader:** people who want to repeat a check or see where a claim in the recording guide comes from. Reviewed 2026-11-16. Labels: see [Recording](./index.md#how-to-read-the-labels).

**In short:** every number and message in the recording guide comes from a command anyone can run. This page has the
commands for the checks, the script, the deadline and disk formulas, the Windows engine and PresentMon (E1, E2, E3, E6,
E8, E9, E10), with their real output, and ends with what was **not** reproduced. The test programs and the data files
(E4, E5, E7) are in [Evidence: data files](./evidence-data.md).

Collected on 2026-11-16 on an Apple silicon Mac. All commands only read. Paths are shortened: the home folder is `~`. The
session could run read-only commands (`rg`, `sed`, `jq`, `ls`, `du`), not Python or the scripts, so nothing below is the
output of a recording or of a check run live: what a check *says* is read from the line that raises it.

## E1 Every message preflight can raise, with its line

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

`cut` trims each line to 175 characters. The line numbers in order (108, 116, 121, 130, 133, 136) are the order the checks
run. `preflight.check` itself with a stub per failure was **not reproduced**; `tests/test_preflight.py` has one test per
failure (`:65` to `:162`), not run. Used by [Preflight](./preflight.md).

## E2 What the script itself refuses, and with which exit code

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
… recortado (lines 55 `trap 'exit 130' INT TERM` and 74 `trap 'rm -rf $out/$name.*(N); exit 143' TERM`)
156:[ -d $out/$name.trace ] || { echo "no recording at $out/$name.trace" >&2; exit 1; }
```

The lock message is the `echo` of the line before 49, `perf_record.sh:48`. Lines 12, 37, 48 and 156 print a path or
folder; 13 and 18 print only the file name, which a test asserts (`tests/test_recording.py:565`, [limit 1](./limits.md)).
Running the script with a bad argument was **not reproduced**.

## E3 The numbers: deadline and disk, by the formulas of the code

```text
$ jq -n -c '{deadline_s:([20,30,60]|map(.*15+180)), deadline_counters_s:([20,30,60]|map(.*55+180)), disk_gb:([20,30,60]|map(2+((.*8+9)/10|floor))), disk_gb_windows:1}'
{"deadline_s":[480,630,1080],"deadline_counters_s":[1280,1830,3480],"disk_gb":[18,26,50],"disk_gb_windows":1}
```

The formulas are `seconds × 15 + 180` (`recording.py:269`, 55 with counters) and `2 + (seconds × 8 + 9) / 10` in
integer division (`preflight.py:50`). They reproduce what the server states: 630 s for 30 s of Wine, and "26 GB for 30
s, 50 GB for 60 s" (`metal_trace_mcp.py:27-28`). These are the code's formulas evaluated by `jq`, not a measurement.

## E6 Where the server sets the script's environment

```text
$ rg -n 'env\["|PERF_OUT=|PERF_LOCK=|PERF_PARENT_PID=|PERF_ENV=' src/metal_gpu_trace/recording.py
360:    env = dict(os.environ, PERF_OUT=str(config.OUT), PERF_LOCK=str(config.LOCK), PERF_PARENT_PID=str(os.getpid()),
361:               PERF_ENV=" ".join(filter(None, [os.environ.get("PERF_ENV", ""), program_env])))
363:        env["PERF_MEMORY"] = "0"
365:        env["KEEP_TRACE"] = "1"
367:        env["PERF_PREFIX"] = BACKGROUND_PREFIX
369:        env["PERF_INSTRUMENTS"] = ";".join(filter(None, [os.environ.get("PERF_INSTRUMENTS", ""), "Metal GPU Counters"]))
370:    layer = layer or layer_of(wine, prefix, env["PERF_ENV"])
… recortado (377: the call into the Windows engine)
```

Used by [The macOS journey, step 3](./macos-journey.md#step-3-the-environment-the-script-gets).

## E8 Which source the Windows engine uses, and where it says so

```text
$ rg -n '"source": |if entries:|elif pm_intervals|elif dwm_samples' src/metal_gpu_trace/perf_record_windows.py
787:        if entries:
808:        elif pm_intervals:
819:        elif dwm_samples:
859:        if entries:
876:            "source": "drawstress-log" if entries else "presentmon" if pm_intervals else "dwm-composition",
… recortado (878: another `if entries:`)
```

The closing `else` at line 830 is a bare keyword this pattern does not match; `sed -n 830,844p` shows the two `no frame
data` errors. The chain is the order of the table in
[The Windows engine](./windows-engine.md#the-three-sources-of-frames-and-which-one-wins); line 859 nulls the
frame-level pacing numbers for the log. An engine recording was **not reproduced** (no Windows machine).

## E9 The Windows lock and cleanup lines

```text
$ rg -n "lock_path|FileExistsError|is_process_alive" src/metal_gpu_trace/perf_record_windows.py
332:def is_process_alive(pid):
574:    lock_path = pathlib.Path(lock_path) if lock_path is not None else out_dir / ".recording"
579:            lock_path.mkdir(exist_ok=False)
583:        except FileExistsError:
587:                stale = not is_process_alive(int(owner.read_text(encoding="utf-8").strip()))
593:                    lock_path.rmdir()
597:            raise RuntimeError(f"another recording is running ({lock_path}); remove it if none is") from None
942:        if lock_acquired and lock_path.exists():
945:                lock_path.rmdir()
… recortado (394, 555, 575, 580, 584, 944)
```

Lines 590-596 are the whole takeover: remove the `pid`, `rmdir`, try again, with no second lock: [limit 3](./limits.md).

## E10 PresentMon: where the pin and the search live

```text
$ rg -n "find_presentmon|PRESENTMON_EXE|presentmon_dir|PRESENTMON\[" src/metal_gpu_trace/perf_record_windows.py src/metal_gpu_trace/workloads.py | cut -c1-140
src/metal_gpu_trace/workloads.py:196:    if target.is_file() and file_id(target)["sha256"] == PRESENTMON["sha256"]:
src/metal_gpu_trace/workloads.py:201:        download(PRESENTMON["url"], part, PRESENTMON["bytes"] * 2)
src/metal_gpu_trace/workloads.py:202:        if file_id(part)["sha256"] != PRESENTMON["sha256"]:
… recortado (workloads.py:194-195, 197, 205)
src/metal_gpu_trace/perf_record_windows.py:420:def find_presentmon():
src/metal_gpu_trace/perf_record_windows.py:424:    explicit = os.environ.get("PRESENTMON_EXE")
src/metal_gpu_trace/perf_record_windows.py:427:    cache = presentmon_dir()
src/metal_gpu_trace/perf_record_windows.py:649:        presentmon_exe = find_presentmon()
```

The hash is compared in `workloads.py:196` and `:202` (install) and nowhere in `find_presentmon` (`:420-430`): [limit 4](./limits.md).

## What was not reproduced

- Any recording, macOS or Windows (needs Instruments, a Windows machine and GPU time), and so every timing of the guide.
- `preflight.check` itself, with a failing input, and each message printed live (read from the source, E1, and pinned by tests not run).
- `perf_record.sh` or `perf_record_windows.py` with bad arguments, including their usage lines.
- A download: `workload_fetch`, `presentmon_install`, and a `shasum` of what the project's releases publish today.
- A partial `.trace` from an interrupted Instruments, and the cancel of a Windows recording.
- How many seconds Wine's start-up takes.
