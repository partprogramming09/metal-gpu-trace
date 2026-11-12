"""Recording a run: perf_record and perf_attach, the layer overrides, memory pressure and cancellation."""
import hashlib
import json
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

from metal_gpu_trace import config, paths, workloads
if sys.platform == "win32":
    from metal_gpu_trace import perf_record_windows


def tool_perf_record(label, program=None, seconds=20, wine=None, prefix=None, workdir=None, args="", workload=None,
                     api=None, dim=None, memory=True, env="", counters=False, example=None, memory_free_pct=None,
                     background=False, size=None):
    """Records `program` (an .exe under Wine, or a macOS binary with wine="native"), or a test program fetched with
    workload_fetch (workload, api, dim), for `seconds` with Metal System Trace and returns its summary: GPU ms per
    frame, frame intervals, FPS, Metal and resident memory (memory=false skips the Metal memory table, the slowest
    to read). When it ends it stops every program of that Wine prefix (wineserver -k), or every process named like
    the program with native. counters=true also records Metal GPU Counters (`gpu_counters` in the summary: the units the
    GPU waited on, its utilization, occupancy and memory bandwidth); it adds about 40 s of read-back per recorded second."""
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
    return record(label, seconds, wine, prefix, workdir,
                  [str(program.resolve()), *split_args(args)], program_env, memory, layer=layer, counters=counters,
                  background=background, memory_free_pct=memory_free_pct)


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
    """Records a program that is already running, by pid or by a name in its command line (Game.exe under Wine),
    for `seconds` and returns the same summary as perf_record; the program keeps running. For games started by
    Steam, CrossOver, NotProton or any launcher: start the game or its benchmark there first."""
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
        version = subprocess.run([str(wine / "bin" / "wine"), "--version"], capture_output=True, text=True,
                                 timeout=30).stdout.strip()
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
    fingerprint = hashlib.sha256(json.dumps({**identity, "dlls": effective_dlls(identity)},
                                            sort_keys=True).encode()).hexdigest()[:12]
    return {"fingerprint": fingerprint, **identity, "program_env": env}


def effective_dlls(layer):
    """Returns, per DLL, the copy Wine most likely loads: the prefix's when it exists, else Wine's own."""
    return {name: copies.get("prefix") or copies.get("builtin") for name, copies in (layer.get("dlls") or {}).items()}


def layer_label(layer):
    """Returns a short name for a summary's layer: native, attached, or its fingerprint and Wine; None if absent."""
    if not layer:
        return None
    if "none" in layer:
        return "native"
    if "unknown" in layer:
        return "attached"
    if "rosetta" in layer:
        return "rosetta"
    if "moltenvk" in layer:
        return f"moltenvk {((layer.get('dylib') or {}).get('sha256') or '')[:12]}".strip()
    return f"{layer['fingerprint']} {layer['wine']} {layer['wine_version'] or ''}".strip()


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


def kill_program(name):
    """Stops every process named `name`: SIGTERM first, then SIGKILL for the ones that ignore it (a game that catches
    SIGTERM kept running for 40 minutes after its recording was cancelled)."""
    subprocess.run(["pkill", "-x", name], capture_output=True, timeout=30)
    for _ in range(6):
        if subprocess.run(["pgrep", "-x", name], capture_output=True, timeout=30).returncode:
            return
        time.sleep(0.5)
    subprocess.run(["pkill", "-KILL", "-x", name], capture_output=True, timeout=30)


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
    check_levers(memory_free_pct, options.get("background", False))
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

def record_run(label, seconds, wine, prefix, workdir, command, program_env="", memory=True, layer=None, counters=False,
               background=False):
    """Runs perf_record.sh and returns the summary it wrote, stopping the whole recording and deleting its files if
    it overruns; `program_env` adds NAME=VALUE pairs to PERF_ENV, `memory` false sets PERF_MEMORY=0, and `layer`
    names the translation layer a native run goes through (MoltenVK) instead of "native Metal"."""
    if not paths.name_ok(label, 100):
        raise paths.ToolError("label holds up to 100 letters, digits, '.', '_' and '-'")
    env = dict(os.environ, PERF_OUT=str(config.OUT), PERF_LOCK=str(config.LOCK), PERF_PARENT_PID=str(os.getpid()),
               PERF_ENV=" ".join(filter(None, [os.environ.get("PERF_ENV", ""), program_env])))
    if not memory:
        env["PERF_MEMORY"] = "0"
    if background:
        env["PERF_PREFIX"] = BACKGROUND_PREFIX
    if counters:
        env["PERF_INSTRUMENTS"] = ";".join(filter(None, [os.environ.get("PERF_INSTRUMENTS", ""), "Metal GPU Counters"]))
    layer = layer or layer_of(wine, prefix, env["PERF_ENV"])
    if sys.platform == "win32":
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
        summary["layer"] = layer
        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return summary
    before = set(config.OUT.glob(f"{label}_*"))
    tmp = pathlib.Path(os.environ.get("TMPDIR", "/tmp"))
    ktraces = set(tmp.glob("instruments*.ktrace"))
    proc = subprocess.Popen(["zsh", str(config.PACKAGE_DIR / "perf_record.sh"), label, str(int(seconds)), str(wine),
                             str(prefix), str(workdir), *command],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                            start_new_session=True)
    limit, started, ticks = (deadline(seconds, True) if counters else deadline(seconds)), time.monotonic(), 0
    while True:
        left = limit - (time.monotonic() - started)
        if left <= 0 or cancelled():
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            if wine == "native":
                kill_program(pathlib.Path(command[0]).name)
            elif wine != "attach":
                subprocess.run([str(pathlib.Path(wine) / "bin" / "wineserver"), "-k"],
                               env=dict(env, WINEPREFIX=str(prefix)), capture_output=True, timeout=30)
            free_lock(proc.pid)
            # the partial .trace and CSVs of this run
            for path in (set(config.OUT.glob(f"{label}_*")) - before) | (set(tmp.glob("instruments*.ktrace")) - ktraces):
                shutil.rmtree(path) if path.is_dir() else path.unlink()
            if left > 0:
                raise paths.ToolError("the recording was cancelled; nothing was saved")
            raise paths.ToolError(f"the recording took over {limit} s and was stopped; nothing was saved")
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
    summary["layer"] = layer
    new[-1].write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def record_new_summary(label, **record):
    """Records with tool_perf_record(label, **record) and returns (run name, summary) of the summary that recording
    wrote: experiments that record several runs read each one back through here."""
    known = set(config.OUT.glob(f"{label}_*.json"))
    tool_perf_record(label, **record)
    new = sorted(set(config.OUT.glob(f"{label}_*.json")) - known)
    if not new:
        raise paths.ToolError(f"the recording of {label} wrote no summary")
    return new[-1].stem, json.loads(new[-1].read_text(encoding="utf-8"))
