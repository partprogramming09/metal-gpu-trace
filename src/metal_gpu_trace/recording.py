"""Recording a run: perf_record and perf_attach, the layer overrides, memory pressure and cancellation."""
import hashlib
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

from metal_gpu_trace import app_metrics, config, fingerprint, metrics, paths, perf_report, preflight, retention, workloads


TIERS = ("light", "standard", "deep")


def resolve_tier(tier, memory, counters):
    """Returns (memory, counters, keep_trace) for a capture tier: light records neither Metal memory nor counters,
    standard the Metal memory, deep also the GPU counters and keeps the .trace (subject to METAL_TRACE_MAX_DISK_MB).
    A `memory` or `counters` that is not None replaces that part of the tier."""
    if tier not in TIERS:
        raise paths.ToolError("tier is one of light, standard, deep")
    if not all(value is None or isinstance(value, bool) for value in (memory, counters)):
        raise paths.ToolError("memory and counters are true or false")
    base_memory, base_counters, keep_trace = {"light": (False, False, False), "standard": (True, False, False),
                                              "deep": (True, True, True)}[tier]
    return (base_memory if memory is None else memory, base_counters if counters is None else counters, keep_trace)


def tool_perf_record(label, program=None, seconds=20, wine=None, prefix=None, workdir=None, args="", workload=None,
                     api=None, dim=None, memory=None, env="", counters=None, example=None, memory_free_pct=None,
                     background=False, size=None, tier="standard", fingerprint_paths=None):
    """Records `program` (an .exe under Wine, or a macOS binary with wine="native") or a test `workload` for `seconds` with
    Metal System Trace and returns its summary: GPU ms per frame, frame intervals, FPS, Metal and resident memory. It
    then stops every program of that Wine prefix (wineserver -k), or with native the program it launched and its children.
    tier sets memory and counters together; compare recordings of the same tier."""
    memory, counters, keep_trace = resolve_tier(tier, memory, counters)
    if tier == "deep" and sys.platform == "win32":
        raise paths.ToolError("deep needs Metal GPU counters: macOS only")
    check_levers(memory_free_pct, background)
    program_env, layer = check_env(env), None
    if workload:
        program, wine, args, workload_env = workloads.workload_command(workload, api, dim, wine, args, example, size)
        program_env = " ".join(filter(None, [workload_env, program_env]))
        layer = workloads.workload_layer(workload, api, dim)
    if size is not None and not workload:
        raise paths.ToolError("size applies to a workload that lists size_variables")
    if not program:
        raise paths.ToolError("pass program, or workload and api (workload_list lists them)")
    wine = wine or os.environ.get("METAL_TRACE_WINE")
    if not wine:
        if sys.platform != "win32":
            raise paths.ToolError("pass wine (a Wine directory holding bin/wine, or native) or set METAL_TRACE_WINE")
        wine = "native"
    program = pathlib.Path(program).expanduser()
    if not program.exists():
        raise paths.ToolError(f"no program at {program.name}")
    workdir = pathlib.Path(workdir).expanduser() if workdir else program.parent
    prefix = pathlib.Path(prefix or os.environ.get("WINEPREFIX", "~/.wine")).expanduser()
    extra = {"env_keys": fingerprint.env_keys(program_env)}
    if fingerprint_paths:
        extra["fingerprint"] = fingerprint.fingerprint_paths(fingerprint_paths)
    return record(label, seconds, wine, prefix, workdir,
                  [str(program.resolve()), *split_args(args)], program_env, memory, layer=layer, counters=counters,
                  background=background, memory_free_pct=memory_free_pct, keep_trace=keep_trace, tier=tier, context_extra=extra)


def check_env(env):
    """Returns `env` (NAME=VALUE pairs separated by spaces) after checking each pair, or raises ToolError."""
    for pair in env.split():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", pair):
            raise paths.ToolError(f"env holds NAME=VALUE pairs separated by spaces; {pair!r} is not one")
    return env


def split_args(text):
    """Splits a program's argument string; on Windows backslashes stay and the quotes around a token go."""
    if sys.platform != "win32":
        return shlex.split(text)
    return [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in shlex.split(text, posix=False)]


def tool_perf_attach(label, process, seconds=20):
    """Records a program that is already running, by pid or by a name in its command line, for `seconds`, and returns
    perf_record's summary; the program keeps running. For games from Steam, CrossOver or any launcher: start the game
    first."""
    return record(label, seconds, "attach", "-", "-", [str(process)])


# the Direct3D DLLs a translation layer replaces (Mullion's README lists the same five for its overrides)
LAYER_DLLS = ("d3d12", "d3d12core", "d3d11", "d3d10core", "dxgi")


def registry_overrides(prefix):
    """Returns the prefix's [Software\\Wine\\DllOverrides] entries for LAYER_DLLS from its user.reg."""
    reg, found, inside = prefix / "user.reg", {}, False
    if not reg.is_file():
        return found
    for line in reg.read_text(errors="replace").splitlines():
        if line.startswith("["):
            inside = line.lower().startswith("[software\\\\wine\\\\dlloverrides]")
        elif inside and line.startswith('"') and "=" in line:
            name, value = (part.strip().strip('"') for part in line.split("=", 1))
            if name.lstrip("*").lower() in LAYER_DLLS:
                found[name] = value
    return found


def wine_version(printed):
    """Returns the one-line version `wine --version` printed: CrossOver's "Product Name" and "Public Version" lines
    joined, a plain Wine's line as is, or None when it printed nothing."""
    lines = [line.strip() for line in printed.splitlines() if line.strip()]
    fields = dict(line.split(": ", 1) for line in lines if ": " in line)
    if "Product Name" in fields and "Public Version" in fields:
        return f"{fields['Product Name']} {fields['Public Version']}"
    return lines[0] if lines else None


def layer_of(wine, prefix, program_env=""):
    """Returns what identifies the translation layer a recording runs on: the Wine version, the overrides in force
    and the size and SHA-256 of LAYER_DLLS in Wine and in the prefix, with a short fingerprint of all of it. Which of
    the two copies Wine loads is not known: Instruments does not keep Wine's own log."""
    # NAME=/an/absolute/path keeps only the file name, so summaries can be shared
    pairs = [pair.partition("=") for pair in program_env.split()]
    env = " ".join(f"{k}={pathlib.Path(v).name}" if s and v.startswith("/") else k + s + v for k, s, v in pairs)
    if wine == "native":
        return {"none": "native Metal, no translation layer", "program_env": env}
    if wine == "attach":
        return {"unknown": "an attached process's Wine and prefix are not known", "program_env": env}
    wine, prefix = pathlib.Path(wine), pathlib.Path(prefix)
    try:
        version = wine_version(subprocess.run([str(wine / "bin" / "wine"), "--version"], capture_output=True, text=True,
                                              timeout=30).stdout)
    except (OSError, subprocess.TimeoutExpired):
        version = None
    caller = os.environ.get("WINEDLLOVERRIDES")
    identity = {
        "wine": wine.name, "wine_version": version,
        # what perf_record.sh passes, then the prefix's registry entries
        "overrides": {"environment": f"{caller};mscoree=;mshtml=" if caller else "mscoree=;mshtml=",
                      "registry": registry_overrides(prefix)},
        "dlls": {name: {"builtin": workloads.file_id(wine / "lib" / "wine" / "x86_64-windows" / f"{name}.dll"),
                        "prefix": workloads.file_id(prefix / "drive_c" / "windows" / "system32" / f"{name}.dll")}
                 for name in LAYER_DLLS},
    }
    # a prefix copy identical to Wine's (Wine's first boot makes one) is the same DLL, so it changes nothing
    layer_hash = hashlib.sha256(json.dumps({**identity, "dlls": effective_dlls(identity)},
                                            sort_keys=True).encode()).hexdigest()[:12]
    return {"fingerprint": layer_hash, **identity, "program_env": env}


def effective_dlls(layer):
    """Returns, per DLL, the copy Wine most likely loads: the prefix's when it exists, else Wine's own."""
    return {name: copies.get("prefix") or copies.get("builtin") for name, copies in (layer.get("dlls") or {}).items()}


layer_label = metrics.layer_label  # one copy, shared with the engines (metrics cannot import this module)


def run_context(read=perf_report.read_command):
    """Returns where a run came from: `git` (the 12-character commit and whether any tracked file of the whole
    repository had changes; new untracked files do not count) of the repository that holds the project file, null when
    there is no project file or its folder is not a git repository, and `instruments` (xctrace's version), null where
    xctrace is missing. The GIT_* variables of the environment are dropped so they cannot point at another repository.
    No branch, path, user or machine name: summaries are shared."""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    def ask(*argv):
        try:
            return read(argv, env=clean_env).strip()
        except (OSError, subprocess.SubprocessError):
            return None
    root = (config.PROJECT or {}).get("root")
    git = ("git", "--no-optional-locks", "-C", str(root))
    commit = ask(*git, "rev-parse", "--short=12", "HEAD") if root else None
    changes = ask(*git, "status", "--porcelain", "--untracked-files=no") if commit else None
    xctrace = ask("xcrun", "xctrace", "version") or ""
    version = re.search(r"version (\S+(?: \(\w+\))?)", xctrace)
    return {"git": {"commit": commit, "dirty": bool(changes)} if commit and changes is not None else None,
            "instruments": version.group(1) if version else None}


def context_change(sa, sb, a, b):
    """Returns whether two runs share a context (commit, dirty flag, Instruments version); a run recorded before
    0.26.0 is named in missing_in, and a run whose commit is unknown (no project file or no git repository) in
    unknown_in: `same` is then null, because nothing says the code is the same. `same` keeps that meaning; when both
    runs name their declared files (`fingerprint`) or variable names (`env_keys`), the answer adds a `fingerprint` and
    an `env_keys` block of its own."""
    ca, cb = sa.get("context"), sb.get("context")
    missing = [r for r, context in ((a, ca), (b, cb)) if not context]
    if missing:
        return {"missing_in": missing}
    unknown = [r for r, context in ((a, ca), (b, cb)) if not context.get("git")]
    code = lambda c: {k: c.get(k) for k in ("git", "instruments")}
    if unknown and code(ca) == code(cb):
        out = {"same": None, "unknown_in": unknown}
    elif code(ca) == code(cb):
        out = {"same": True}
    else:
        out = {"same": False, "a": ca, "b": cb, **({"unknown_in": unknown} if unknown else {})}
    files = fingerprint.compare(ca.get("fingerprint"), cb.get("fingerprint"))
    if files:
        out["fingerprint"] = files
    if "env_keys" in ca and "env_keys" in cb:
        ka, kb = set(ca["env_keys"]), set(cb["env_keys"])
        out["env_keys"] = {"same": ka == kb, "only_a": sorted(ka - kb), "only_b": sorted(kb - ka)}
    return out


def layer_change(sa, sb, a, b):
    """Returns whether two runs share a translation layer, which DLLs differ and whether the program's variables
    differ; a run recorded before 0.6.0, or with perf_record.sh by hand, is named in missing_in."""
    la, lb = sa.get("layer"), sb.get("layer")
    missing = [r for r, layer in ((a, la), (b, lb)) if not layer]
    if missing:
        return {"missing_in": missing, "hint": "runs recorded before version 0.6.0, or with perf_record.sh by hand, "
                                               "do not name their layer"}
    def identity(layer):
        return (layer_label(layer).split(" ", 1)[-1], layer.get("overrides"), effective_dlls(layer))
    same = layer_label(la) == layer_label(lb) if "fingerprint" not in la or "fingerprint" not in lb \
        else identity(la) == identity(lb)
    out = {"same": same, "a": layer_label(la), "b": layer_label(lb),
           "differs": [d for d in LAYER_DLLS if effective_dlls(la).get(d) != effective_dlls(lb).get(d)],
           "note": "same layer: the change comes from the program, its settings or run-to-run noise" if same else
                   "different layers: this compares two layers, not one change"}
    if la.get("program_env") != lb.get("program_env"):
        out["program_env"] = {"a": la.get("program_env"), "b": lb.get("program_env")}
    return out
RUN = threading.local()  # the cancel event and progress sender of the tool call this thread is serving


def cancelled():
    """Returns whether the client cancelled the tool call this thread is serving."""
    event = getattr(RUN, "cancel", None)
    return bool(event and event.is_set())


def progress(done, total, message):
    """Tells the client how far the running tool call is, when it asked for progress; a no-op otherwise."""
    send = getattr(RUN, "progress", None)
    if send:
        send(done, total, message)


def cooldown(seconds):
    """Rests for `seconds` between two recordings, a laptop cooling off, in slices of at most 1 s: each sends a progress
    line, and a cancelled call ends it with a ToolError, so no further recording starts."""
    total = left = float(seconds)
    while True:
        if cancelled():
            raise paths.ToolError("cancelled while cooling down")
        if left <= 0:
            return
        progress(total - left, total, f"cooling down: {math.ceil(left)} s left")
        step = min(1.0, left)
        time.sleep(step)
        left -= step


def holds_program(group, name):
    """Returns whether process group `group` is still the one of the program `name`: its leader runs that program, or
    the leader is gone while the group lives on (a pid is not reused while a process group holds its number)."""
    leader = subprocess.run(["ps", "-o", "comm=", "-p", str(group)], capture_output=True, text=True,
                            timeout=30).stdout.strip()
    return not leader or pathlib.PurePath(leader).name == name


def kill_program(group, name):
    """Stops the process group `group`, the program `name` a recording launched and the children it started, never
    another process with its name: SIGTERM first, then SIGKILL when it ignores it (a game that catches SIGTERM kept
    running for 40 minutes after its recording was cancelled). A group that is gone, 0 or the caller's own, 1 and
    below, or whose leader now runs another program, is left alone. shortcut: a child that leaves the group (setsid
    or setpgid) is out of reach; following it means tracking every descendant, worth it only if a program does that."""
    if group <= 1 or group == os.getpgrp() or not holds_program(group, name):
        return
    try:
        os.killpg(group, signal.SIGTERM)
        for _ in range(6):
            time.sleep(0.5)
            os.killpg(group, 0)
        if holds_program(group, name):
            os.killpg(group, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def worst_case_message(limit, windows):
    """Returns the first progress line: the worst case in seconds, with read-back only where there is one."""
    return f"recording: up to {limit} s" + ("" if windows else " including read-back")


def deadline(seconds, counters=False):
    """Returns the seconds a recording of `seconds` may take in all; closing and reading back a Wine D3D12 trace takes
    up to 14 s per recorded second on an M1 Pro, and the GPU counters table about 40 more (an M-series Mac, native)."""
    return int(seconds) * (55 if counters else 15) + 180
# xctrace --launch takes an absolute path only
BACKGROUND_PREFIX = "/usr/sbin/taskpolicy -b"


def check_levers(memory_free_pct=None, background=False):
    """Refuses a memory_free_pct outside 20 to 60, and either lever under Windows."""
    if memory_free_pct is not None:
        try:
            ok = 20 <= int(memory_free_pct) <= 60
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise paths.ToolError("memory_free_pct is 20 to 60, the percentage of RAM left free; lower values can freeze the Mac")
    if (memory_free_pct or background) and sys.platform == "win32":
        raise paths.ToolError("memory_free_pct and background work on macOS only")


def hold_memory_pressure(free_pct, hold_s, wait_s=90):
    """Starts memory_pressure to hold the Mac at `free_pct` percent free for `hold_s` seconds and returns the process
    once it reports stable; stops it and raises ToolError when it does not within `wait_s` seconds."""
    log = tempfile.TemporaryFile("w+")
    try:
        proc = subprocess.Popen([*config.MEMORY_PRESSURE, "-p", str(int(free_pct)), "-y", str(int(hold_s)), "-Q"],
                                stdout=log, stderr=subprocess.STDOUT)
    except OSError as error:
        log.close()
        raise paths.ToolError("memory_pressure is not available") from error
    end = time.monotonic() + wait_s
    while time.monotonic() < end and proc.poll() is None:
        log.seek(0)
        if "Stable at percent free" in log.read():
            return proc
        time.sleep(0.5)
    proc.terminate()
    proc.wait()
    log.close()
    raise paths.ToolError("memory_pressure did not reach that free percentage; the Mac may already be below it")


def record(label, seconds, wine, prefix, workdir, command, *args, memory_free_pct=None, **options):
    """Runs record_run, holding the Mac at `memory_free_pct` percent free meanwhile when it is given, and stopping
    that pressure whatever happens."""
    if not paths.name_ok(label, 100):
        raise paths.ToolError("label holds up to 100 letters, digits, '.', '_' and '-'")
    check_levers(memory_free_pct, options.get("background", False))
    preflight.check(wine=wine, command=command, seconds=seconds)
    hold = hold_memory_pressure(memory_free_pct, int(seconds) + 120) if memory_free_pct else None
    try:
        return record_run(label, seconds, wine, prefix, workdir, command, *args, **options)
    finally:
        if hold:
            hold.terminate()
            hold.wait()



def free_lock(pid):
    """Removes the recording lock (config.LOCK) of a recording that was killed, when it holds `pid` (perf_record.sh's
    own pid): a lock with another pid, or with none yet, may belong to another recording and stays."""
    lock = config.LOCK
    try:
        owner = (lock / "pid").read_text().strip()
    except OSError:
        return
    if owner == str(pid):
        shutil.rmtree(lock, ignore_errors=True)


def launched_group(pid):
    """Returns the process group of the program that perf_record.sh (pid `pid`) launched, which the script keeps in
    its lock, or None when the lock belongs to another recording or names no program yet."""
    try:
        if (config.LOCK / "pid").read_text().strip() != str(pid):
            return None
        text = (config.LOCK / "program").read_text().strip()
    except OSError:
        return None
    # a pid has at most 10 digits; int() raises on a string of over 4300
    return int(text) if len(text) <= 10 and text.isascii() and text.isdigit() and int(text) > 1 else None

def finish(summary, json_path, layer, tier, app_file=None, context_extra=None):
    """Adds `layer`, the run's `context` and `tier` to the summary, applies METAL_TRACE_MAX_DISK_MB (the run just recorded
    is `json_path`'s; not while another recording runs, whose .trace is being written into the same folder): when files
    had to go, notes it in the summary's `retention`; writes the JSON and returns the summary. Both engines end here."""
    summary["layer"], summary["context"] = layer, run_context()
    summary["context"].update({k: v for k, v in (context_extra or {}).items() if v})  # env_keys, fingerprint
    if app_file and (block := app_metrics.safe_read(app_file)):  # the program's own telemetry, when it wrote any
        summary["app_metrics"] = block
    if "common" in summary:  # built before the layer was known
        summary["common"] = metrics.common_block(summary)
    if tier:
        summary["tier"] = tier
    if config.MAX_DISK_MB and not preflight.recording_running():
        removed = retention.prune_to_quota(config.OUT, config.MAX_DISK_MB, json_path.stem)
        if removed["removed"]:
            summary["retention"] = removed
    paths.write_file(json_path, json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    return summary


def record_run(label, seconds, wine, prefix, workdir, command, program_env="", *args, **options):
    """Runs the recording (see run_recording) with METAL_TRACE_APP_METRICS pointing at a private file the program may
    write its telemetry to; the file is read into the summary's `app_metrics` and always removed."""
    app_file = app_metrics.path_for([tempfile.gettempdir(), config.OUT])
    if app_file:
        program_env = " ".join(filter(None, [program_env, f"{app_metrics.ENV}={app_file}"]))
    try:
        return run_recording(label, seconds, wine, prefix, workdir, command, program_env, *args, app_file=app_file, **options)
    finally:
        app_metrics.discard(app_file)


def run_recording(label, seconds, wine, prefix, workdir, command, program_env="", memory=True, layer=None, counters=False,
                  background=False, keep_trace=False, tier=None, app_file=None, context_extra=None):
    """Runs perf_record.sh and returns the summary it wrote, stopping the whole recording and deleting its files if
    it overruns; `program_env` adds NAME=VALUE pairs to PERF_ENV, `memory` false sets PERF_MEMORY=0, and `layer`
    names the translation layer a native run goes through (MoltenVK) instead of "native Metal"; `keep_trace` sets KEEP_TRACE=1
    for the script; `tier` is written into the summary."""
    env = dict(os.environ, PERF_OUT=str(config.OUT), PERF_LOCK=str(config.LOCK), PERF_PARENT_PID=str(os.getpid()),
               PERF_ENV=" ".join(filter(None, [os.environ.get("PERF_ENV", ""), program_env])))
    if not memory:
        env["PERF_MEMORY"] = "0"
    if keep_trace:
        env["KEEP_TRACE"] = "1"
    if background:
        env["PERF_PREFIX"] = BACKGROUND_PREFIX
    if counters:
        env["PERF_INSTRUMENTS"] = ";".join(filter(None, [os.environ.get("PERF_INSTRUMENTS", ""), "Metal GPU Counters"]))
    layer = layer or layer_of(wine, prefix, env["PERF_ENV"])
    limit = deadline(seconds, True) if counters and sys.platform != "win32" else deadline(seconds)
    progress(0, limit, worst_case_message(limit, sys.platform == "win32"))
    if sys.platform == "win32":
        from metal_gpu_trace import perf_record_windows  # here, not at import: the module may have been imported elsewhere
        try:
            summary, json_path = perf_record_windows.record_windows(
                label, int(seconds), wine, prefix, workdir, command, env["PERF_ENV"],
                out_dir=config.OUT, timeout=deadline(seconds), cancelled=cancelled, progress=progress,
                lock_path=config.LOCK
            )
        except (RuntimeError, ValueError) as error:
            raise paths.ToolError(str(error)) from error
        except OSError as error:
            raise paths.ToolError(f"recording failed: {error}") from error
        return finish(summary, json_path, layer, tier, app_file, context_extra)
    power_start = perf_report.power_state()
    before = set(config.OUT.glob(f"{label}_*"))
    tmp = pathlib.Path(os.environ.get("TMPDIR", "/tmp"))
    ktraces = set(tmp.glob("instruments*.ktrace"))
    proc = subprocess.Popen(["zsh", str(config.PACKAGE_DIR / "perf_record.sh"), label, str(int(seconds)), str(wine),
                             str(prefix), str(workdir), *command],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                            start_new_session=True)
    started, ticks = time.monotonic(), 0
    while True:
        left = limit - (time.monotonic() - started)
        if left <= 0 or cancelled():
            # read while the script still holds its lock: once it is dead, another recording may take the lock
            group = launched_group(proc.pid) if wine == "native" else None
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            if group:
                kill_program(group, pathlib.Path(command[0]).name)
            elif wine not in ("native", "attach"):
                subprocess.run([str(pathlib.Path(wine) / "bin" / "wineserver"), "-k"],
                               env=dict(env, WINEPREFIX=str(prefix)), capture_output=True, timeout=30)
            free_lock(proc.pid)
            # the partial .trace and CSVs of this run
            for path in (set(config.OUT.glob(f"{label}_*")) - before) | (set(tmp.glob("instruments*.ktrace")) - ktraces):
                shutil.rmtree(path) if path.is_dir() else path.unlink()
            if left > 0:
                raise paths.ToolError("the recording was cancelled; nothing was saved")
            raise paths.ToolError(f"the recording took over {limit} s and was stopped; nothing was saved. The likely "
                                  "cause is a hidden window: the program stops presenting, renders without the "
                                  "display's pace, and Instruments takes minutes to close that much data; record "
                                  "again with the program's window visible, or for fewer seconds")
        try:
            _, stderr = proc.communicate(timeout=min(1, left))
            break
        except subprocess.TimeoutExpired:
            ticks += 1
            if ticks % config.PROGRESS_TICKS == 0:
                done = time.monotonic() - started
                progress(done, limit, f"recording and reading back: {int(done)} s of up to {limit} s")
    new = sorted(set(config.OUT.glob(f"{label}_*.json")) - before)
    if proc.returncode or not new:
        reason = (stderr.strip().splitlines() or ["no summary was written"])[-1]
        raise paths.ToolError(f"recording failed (exit {proc.returncode}): {reason}")
    summary = json.loads(new[-1].read_text(encoding="utf-8"))
    if not (summary.get("gpu") or {}).get("intervals"):
        run, keep = new[-1].stem, keep_trace or os.environ.get("KEEP_TRACE") == "1"
        for path in set(config.OUT.glob(f"{run}.*")) - before:
            if not (keep and path.suffix == ".trace"):
                shutil.rmtree(path) if path.is_dir() else path.unlink()
        ended = (summary.get("process") or {}).get("termination-reason") or "unknown"
        kept = f"; {run}.trace is kept (KEEP_RUNS does not remove it; METAL_TRACE_MAX_DISK_MB, when set, prunes it at the next recording)" if keep and (config.OUT / f"{run}.trace").exists() else ""
        raise paths.ToolError(f"the program did no GPU work: it ended ({ended}) after {summary.get('duration_s', 0):.1f} s "
                              f"of recording, and its summary was not saved{kept}; check that it starts (under Wine: "
                              "the Wine build, the prefix and the program's own log)")
    if isinstance(summary.get("machine"), dict):  # the machine is known: say its power state at both ends
        summary["machine"]["power"] = perf_report.power_block(power_start, perf_report.power_state())
    return finish(summary, new[-1], layer, tier, app_file, context_extra)


def record_new_summary(label, **record):
    """Records with tool_perf_record(label, **record) and returns (run name, summary) of the summary that recording
    wrote: experiments that record several runs read each one back through here."""
    known = set(config.OUT.glob(f"{label}_*.json"))
    tool_perf_record(label, **record)
    new = sorted(set(config.OUT.glob(f"{label}_*.json")) - known)
    if not new:
        raise paths.ToolError(f"the recording of {label} wrote no summary")
    return new[-1].stem, json.loads(new[-1].read_text(encoding="utf-8"))
