"""MCP server (stdio, JSON-RPC 2.0, standard library only) that records Wine or macOS programs with Instruments'
Metal System Trace and reads the recordings and Metal .gputrace captures.

Environment: METAL_TRACE_OUT is where recordings go (default ./perf-runs); METAL_TRACE_READ lists more directories,
separated by ':', whose files the tools may read; METAL_TRACE_WINE is the default Wine directory; KEEP_RUNS caps the
recordings kept; METAL_TRACE_LOG=off silences the one stderr line per call. Test programs that workload_fetch
downloads go to ~/Library/Caches/metal-gpu-trace.
"""
import collections
import csv
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import signal
import stat
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile

__version__ = "0.21.0"
TOOLS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
import gputrace_read  # noqa: E402
import perf_report  # noqa: E402
if sys.platform == "win32":
    import perf_record_windows  # noqa: E402

OUT = pathlib.Path(os.environ.get("METAL_TRACE_OUT", "perf-runs")).resolve()
READ = [OUT] + [pathlib.Path(p).resolve() for p in os.environ.get("METAL_TRACE_READ", "").split(os.pathsep) if p]
FAMILIES = json.loads((TOOLS_DIR / "data" / "apple-gpu-families.json").read_text(encoding="utf-8"))
WORKLOADS = json.loads((TOOLS_DIR / "data" / "workloads.json").read_text(encoding="utf-8"))["workloads"]
if sys.platform == "win32":
    CACHE = pathlib.Path(os.environ.get("LOCALAPPDATA", "~/.cache")).expanduser() / "metal-gpu-trace"
else:
    CACHE = pathlib.Path("~/Library/Caches/metal-gpu-trace").expanduser()
MAX_LIMIT = 500
# named references for perf_check: copies of their runs' summaries, so KEEP_RUNS deleting a run does not break them
BASELINES = OUT / "baselines.json"
# newest first; initialize answers with the client's version when listed here, else the first
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
# results stay under Claude Code's 50 000-character limit, above which it saves them to a file
MAX_TEXT = 40_000
INSTRUCTIONS = (
    "Records GPU use on Apple silicon with Metal System Trace. One recording runs at a time; keep other GPU work off "
    "the Mac while it records. Under Wine record 30 s or more: Wine's start-up takes part of the recording. A recording needs about 0.8 GB of free disk "
    "per second for Instruments' temporary files (26 GB for 30 s, 50 GB for 60 s); perf_record refuses to start without it. Reading a "
    "recording back takes 1 to 14 s per recorded second. Compare only recordings with 100 frames or more, and repeat "
    "a run before calling a change real. perf_baseline (or perf_baseline_record, which records them) saves several equal runs as a named reference and perf_check says whether a new run regressed against their range. perf_diagnose says whether a run splits its GPU work into too many short "
    "encoders, as translation layers do; perf_compare says how much two runs differ; skip_s on perf_compare, perf_gate and perf_panel leaves out the first seconds (start-up) of each run; perf_history follows FPS, hitches and memory across runs with one name prefix, oldest first; perf_gate says whether a run meets budgets you set (FPS floor, hitch or memory ceiling); perf_panel writes an HTML page to look at one or two runs in a browser.trace_tables and trace_query "
    "need the .trace, kept only with KEEP_TRACE=1. When perf_record ends it stops every program of its Wine prefix, "
    "or every process named like a native program. To compare native Metal with a translation layer without a game "
    "of one's own: workload_list, workload_fetch, then perf_record with workload and api (and example, for a workload "
    "that lists examples), or the compare-layer prompt. perf_sweep records one run per value of dim, example, api or an "
    "environment variable and fits GPU ms per frame on the value. memory_free_pct holds the whole Mac short of memory "
    "while recording (keep other work off it) and background throttles the program: repeat a run that uses either."
)


class ToolError(Exception):
    """A failure the caller can fix; its message says how."""


def allowed(path, roots=None):
    """Returns `path` resolved, or raises ToolError when it lies outside the readable directories."""
    resolved = pathlib.Path(path).expanduser().resolve()
    if not any(resolved.is_relative_to(root) for root in roots or READ):
        raise ToolError(f"{resolved.name} is outside the readable directories; add its directory to METAL_TRACE_READ")
    return resolved


def name_ok(name):
    """Returns whether `name` holds only letters, digits, '.', '_' and '-'."""
    return name.replace("-", "").replace("_", "").replace(".", "").isalnum()


def run_path(run):
    """Returns the summary path of a recording named as perf_runs lists it."""
    if not name_ok(run):
        raise ToolError("a run name holds only letters, digits, '.', '_' and '-'; take it from perf_runs")
    path = OUT / f"{run}.json"
    if path == BASELINES or not path.exists():
        raise ToolError(f"no run {run}; perf_runs lists them")
    return path


def trace_path(trace):
    """Returns the .trace of a run named as perf_runs lists it, or `trace` as a path inside the readable
    directories."""
    if name_ok(trace):
        return OUT / f"{trace.removesuffix('.trace')}.trace"
    return allowed(trace)


OBJECT = {"type": "object"}
PAGED = {"type": "object", "required": ["total", "offset", "rows", "next_offset"],
         "properties": {"total": {"type": "integer"}, "offset": {"type": "integer"}, "rows": {"type": "array"},
                        "next_offset": {"type": ["integer", "null"]}}}
PAGED_TOOLS = ("perf_runs", "trace_query", "capture_records")  # the tools that return page()


def page(items, offset, limit):
    """Returns one page of `items` with the total and the offset of the next page (None at the end)."""
    offset, limit = max(0, int(offset)), min(max(1, int(limit)), MAX_LIMIT)
    rows = items[offset:offset + limit]
    more = offset + len(rows) < len(items)
    return {"total": len(items), "offset": offset, "rows": rows, "next_offset": offset + len(rows) if more else None}


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
        program, wine, args, workload_env = workload_command(workload, api, dim, wine, args, example, size)
        program_env = " ".join(filter(None, [workload_env, program_env]))
        layer = workload_layer(workload, api, dim)
    if size is not None and not workload:
        raise ToolError("size applies to a workload that lists size_variables")
    if not program:
        raise ToolError("pass program, or workload and api (workload_list lists them)")
    wine = wine or os.environ.get("METAL_TRACE_WINE")
    if not wine:
        if sys.platform != "win32":
            raise ToolError("pass wine (a Wine directory holding bin/wine, or native) or set METAL_TRACE_WINE")
        wine = "native"
    program = pathlib.Path(program).expanduser()
    if not program.exists():
        raise ToolError(f"no program at {program.name}")
    workdir = pathlib.Path(workdir).expanduser() if workdir else program.parent
    prefix = pathlib.Path(prefix or os.environ.get("WINEPREFIX", "~/.wine")).expanduser()
    return record(label, seconds, wine, prefix, workdir,
                  [str(program.resolve()), *split_args(args)], program_env, memory, layer=layer, counters=counters,
                  background=background, memory_free_pct=memory_free_pct)


def check_env(env):
    """Returns `env` (NAME=VALUE pairs separated by spaces) after checking each pair, or raises ToolError."""
    for pair in env.split():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", pair):
            raise ToolError(f"env holds NAME=VALUE pairs separated by spaces; {pair!r} is not one")
    return env


def split_args(text):
    """Splits a program's argument string; on Windows backslashes stay and the quotes around a token go."""
    if sys.platform != "win32":
        return shlex.split(text)
    return [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in shlex.split(text, posix=False)]


def workload_entry(name):
    """Returns a test program's entry in data/workloads.json and the directory it is fetched into."""
    if name not in WORKLOADS:
        raise ToolError(f"no workload {name!r}; workload_list lists them")
    entry = WORKLOADS[name]
    return entry, CACHE / f"{name}-{entry['sha256'][:12]}"


def moltenvk_dir():
    """Returns the directory METAL_TRACE_MOLTENVK names. It must hold libMoltenVK.dylib (arm64) and no spaces, because
    the program's environment is passed to Instruments as space-separated NAME=VALUE pairs."""
    raw = os.environ.get("METAL_TRACE_MOLTENVK")
    if not raw:
        raise ToolError("api vk runs through MoltenVK: set METAL_TRACE_MOLTENVK to the directory holding libMoltenVK.dylib")
    path = pathlib.Path(raw).expanduser().resolve()
    if not (path / "libMoltenVK.dylib").is_file():
        raise ToolError("METAL_TRACE_MOLTENVK holds no libMoltenVK.dylib")
    if any(c.isspace() for c in str(path)):
        raise ToolError("the METAL_TRACE_MOLTENVK path may not contain spaces: copy libMoltenVK.dylib to another directory")
    return path


def workload_layer(name, api, dim):
    """Returns the layer a workload's api runs through (MoltenVK with its size and SHA-256, or Rosetta for Metal built for
    x86_64), or None when the api is native Metal or goes through Wine."""
    entry = workload_entry(name)[0]
    if entry["apis"].get(api, {}).get("rosetta"):
        return {"rosetta": "native Metal built for x86_64 and run under Rosetta 2, like Wine's programs",
                "program_env": f"{entry['dim_variable']}={int(dim)}" if dim else ""}
    if not entry["apis"].get(api, {}).get("moltenvk"):
        return None
    return {"moltenvk": "Vulkan on Metal through MoltenVK", "dylib": file_id(moltenvk_dir() / "libMoltenVK.dylib"),
            "program_env": f"{entry['dim_variable']}={int(dim)}" if dim else ""}


def check_size(size):
    """Returns (width, height) from a "WIDTHxHEIGHT" text between 320x240 and 7680x4320, or raises ToolError."""
    match = re.fullmatch(r"(\d{3,4})x(\d{3,4})", str(size))
    if not match or not (320 <= int(match[1]) <= 7680 and 240 <= int(match[2]) <= 4320):
        raise ToolError("size is WIDTHxHEIGHT, from 320x240 to 7680x4320")
    return int(match[1]), int(match[2])


def workload_command(name, api, dim, wine, args, example=None, size=None):
    """Returns the program, Wine, arguments and program environment that run a fetched workload with `api`; a workload
    with `examples` runs the one named by `example`."""
    entry, target = workload_entry(name)
    if api not in entry["apis"]:
        raise ToolError(f"api is one of {', '.join(entry['apis'])} for {name}")
    examples = entry.get("examples")
    if examples and example not in examples:
        raise ToolError(f"example is one of {', '.join(examples)} for {name}")
    if example and not examples:
        raise ToolError(f"{name} takes no example")
    if dim and "dim_variable" not in entry:
        raise ToolError(f"dim does not apply to {name}")
    if not target.is_dir():
        raise ToolError(f"{name} is not downloaded yet; call workload_fetch first")
    run = entry["apis"][api]
    program_env = f"{entry['dim_variable']}={int(dim)}" if dim else ""
    if size is not None:
        if not entry.get("size_variables"):
            raise ToolError(f"size does not apply to {name}")
        program_env = " ".join(filter(None, [program_env, *(f"{v}={n}" for v, n in zip(entry["size_variables"], check_size(size)))]))
    if run.get("moltenvk"):
        program_env = " ".join(filter(None, [program_env, f"DYLD_LIBRARY_PATH={moltenvk_dir()}"]))
    use_wine = run["wine"] and sys.platform != "win32"
    return (target / entry["dir"] / run["program"], wine if use_wine else "native",
            " ".join(filter(None, [run["args"].replace("{dir}", str(target / entry["dir"])),
                                   examples[example] if example else "", args])), program_env)


def tool_workload_list():
    """Lists the test programs workload_fetch can download, such as bgfx's drawstress: what each measures, its size,
    license and APIs, and whether it is already downloaded."""
    rows = []
    for name, entry in WORKLOADS.items():
        rows.append({"name": name, "title": entry["title"], "about": entry["about"],
                     "bytes": entry["bytes"] + sum(d["bytes"] for d in entry.get("downloads", [])),
                     "license": entry["license"], "apis": list(entry["apis"]),
                     **({"examples": list(entry["examples"])} if entry.get("examples") else {}),
                     **({"example_traits": dict(entry["example_traits"])} if entry.get("example_traits") else {}),
                     "fetched": workload_entry(name)[1].is_dir()})
    return {"workloads": rows}


def download(url, path, max_bytes):
    """Saves `url` to `path` over https with curl, which uses the system's certificates; fails above `max_bytes`."""
    proc = subprocess.run(["curl", "-fsSL", "--proto", "=https", "--max-filesize", str(max_bytes), "--max-time", "600",
                           "-o", str(path), url], capture_output=True, text=True)
    if proc.returncode:
        raise ToolError(f"the download failed (curl exit {proc.returncode}); check the network and try again")


def unpack(archive, target):
    """Extracts a .tar.gz into `target`, refusing links and any member that would land outside it."""
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not (member.isfile() or member.isdir()) or member.name.startswith("/") or ".." in member.name.split("/"):
                raise ToolError(f"the archive holds {member.name!r}, which may not be extracted; nothing was saved")
        tar.extractall(target, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))


def unzip(archive, target):
    """Extracts a .zip into `target`, refusing links and any member that would land outside it, and restores the
    Unix file modes the archive records (the zipfile module drops them)."""
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if (stat.S_ISLNK(info.external_attr >> 16) or info.filename.startswith("/")
                    or ".." in info.filename.split("/")):
                raise ToolError(f"the archive holds {info.filename!r}, which may not be extracted; nothing was saved")
        zf.extractall(target)
        for info in zf.infolist():
            mode = (info.external_attr >> 16) & 0o777
            if mode and not info.is_dir():
                (pathlib.Path(target) / info.filename).chmod(mode)


def tool_workload_fetch(name):
    """Downloads a test program from this project's GitHub releases once, checks its SHA-256 against the one this
    package pins, and keeps it in ~/Library/Caches/metal-gpu-trace; later calls reuse it. The programs are built
    from source by the project's workloads workflow. A workload with `downloads` (Godot) also fetches each of those
    zip files from its own publisher, checks its SHA-512 against the one data/workloads.json pins and unzips it into
    the workload's folder."""
    entry, target = workload_entry(name)
    if target.is_dir():
        return {"name": name, "downloaded": False, "fetched": True, "apis": list(entry["apis"])}
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CACHE) as tmp:
        archive = pathlib.Path(tmp) / "archive.tar.gz"
        download(entry["url"], archive, entry["bytes"])
        if file_id(archive)["sha256"] != entry["sha256"]:
            raise ToolError(f"{name}'s download does not match the SHA-256 this package pins; nothing was saved")
        unpack(archive, pathlib.Path(tmp) / "out")
        for item in entry.get("downloads", []):
            part = pathlib.Path(tmp) / "part.zip"
            download(item["url"], part, item["bytes"])
            digest = hashlib.sha512()
            with open(part, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    digest.update(block)
            if digest.hexdigest() != item["sha512"]:
                raise ToolError(f"{name}'s {item['into']} download does not match the SHA-512 this package pins; nothing was saved")
            unzip(part, pathlib.Path(tmp) / "out" / entry["dir"] / item["into"])
            part.unlink()
        (pathlib.Path(tmp) / "out").rename(target)
    return {"name": name, "downloaded": True, "fetched": True, "bytes": entry["bytes"] + sum(d["bytes"] for d in entry.get("downloads", [])),
            "apis": list(entry["apis"])}


# the PresentMon console application perf_record uses on Windows, pinned by size and SHA-256
PRESENTMON = {
    "version": "2.6.0", "bytes": 980320,
    "sha256": "b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af",
    "url": "https://github.com/GameTechDev/PresentMon/releases/download/v2.6.0/PresentMon-2.6.0-x64.exe",
}


def tool_presentmon_install():
    """Windows only: downloads Intel's PresentMon console application (MIT) from its GitHub release, checks its
    SHA-256 against the one this package pins, and keeps it in %LOCALAPPDATA%\\metal-gpu-trace, where perf_record and
    perf_attach find it; later calls reuse it. It needs administrator rights or the Performance Log Users group to run."""
    if sys.platform != "win32":
        raise ToolError("PresentMon runs only on Windows")
    target_dir = perf_record_windows.presentmon_dir()
    target = target_dir / f"PresentMon-{PRESENTMON['version']}-x64.exe"
    if target.is_file() and file_id(target)["sha256"] == PRESENTMON["sha256"]:
        return {"installed": False, "path": str(target), "version": PRESENTMON["version"]}
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target_dir) as tmp:
        part = pathlib.Path(tmp) / "PresentMon.exe"
        download(PRESENTMON["url"], part, PRESENTMON["bytes"] * 2)
        if file_id(part)["sha256"] != PRESENTMON["sha256"]:
            raise ToolError("PresentMon's download does not match the SHA-256 this package pins; nothing was saved")
        part.replace(target)
    return {"installed": True, "path": str(target), "version": PRESENTMON["version"], "bytes": PRESENTMON["bytes"]}


def tool_perf_attach(label, process, seconds=20):
    """Records a program that is already running, by pid or by a name in its command line (Game.exe under Wine),
    for `seconds` and returns the same summary as perf_record; the program keeps running. For games started by
    Steam, CrossOver, NotProton or any launcher: start the game or its benchmark there first."""
    return record(label, seconds, "attach", "-", "-", [str(process)])


# the Direct3D DLLs a translation layer replaces (Mullion's README lists the same five for its overrides)
LAYER_DLLS = ("d3d12", "d3d12core", "d3d11", "d3d10core", "dxgi")


def file_id(path):
    """Returns a file's size and SHA-256, read in 1 MiB blocks, or None when there is no such file."""
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


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
        "dlls": {name: {"builtin": file_id(wine / "lib" / "wine" / "x86_64-windows" / f"{name}.dll"),
                        "prefix": file_id(prefix / "drive_c" / "windows" / "system32" / f"{name}.dll")}
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


PROGRESS_TICKS = 5  # seconds between progress notifications while a recording runs
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


MEMORY_PRESSURE = ["memory_pressure"]
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
            raise ToolError("memory_free_pct is 20 to 60, the percentage of RAM left free; lower values can freeze the Mac")
    if (memory_free_pct or background) and sys.platform == "win32":
        raise ToolError("memory_free_pct and background work on macOS only")


def hold_memory_pressure(free_pct, hold_s, wait_s=90):
    """Starts memory_pressure to hold the Mac at `free_pct` percent free for `hold_s` seconds and returns the process
    once it reports stable; stops it and raises ToolError when it does not within `wait_s` seconds."""
    log = tempfile.TemporaryFile("w+")
    try:
        proc = subprocess.Popen([*MEMORY_PRESSURE, "-p", str(int(free_pct)), "-y", str(int(hold_s)), "-Q"],
                                stdout=log, stderr=subprocess.STDOUT)
    except OSError as error:
        log.close()
        raise ToolError("memory_pressure is not available") from error
    end = time.monotonic() + wait_s
    while time.monotonic() < end and proc.poll() is None:
        log.seek(0)
        if "Stable at percent free" in log.read():
            return proc
        time.sleep(0.5)
    proc.terminate()
    proc.wait()
    log.close()
    raise ToolError("memory_pressure did not reach that free percentage; the Mac may already be below it")


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


def record_run(label, seconds, wine, prefix, workdir, command, program_env="", memory=True, layer=None, counters=False,
               background=False):
    """Runs perf_record.sh and returns the summary it wrote, stopping the whole recording and deleting its files if
    it overruns; `program_env` adds NAME=VALUE pairs to PERF_ENV, `memory` false sets PERF_MEMORY=0, and `layer`
    names the translation layer a native run goes through (MoltenVK) instead of "native Metal"."""
    if not name_ok(label):
        raise ToolError("label holds only letters, digits, '.', '_' and '-'")
    env = dict(os.environ, PERF_OUT=str(OUT), PERF_PARENT_PID=str(os.getpid()),
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
                out_dir=OUT, timeout=deadline(seconds), cancelled=cancelled, progress=progress
            )
        except (RuntimeError, ValueError) as error:
            raise ToolError(str(error)) from error
        except OSError as error:
            raise ToolError(f"recording failed: {error}") from error
        summary["layer"] = layer
        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return summary
    before = set(OUT.glob(f"{label}_*"))
    tmp = pathlib.Path(os.environ.get("TMPDIR", "/tmp"))
    ktraces = set(tmp.glob("instruments*.ktrace"))
    proc = subprocess.Popen(["zsh", str(TOOLS_DIR / "perf_record.sh"), label, str(int(seconds)), str(wine),
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
            if (OUT / ".recording").is_dir():
                (OUT / ".recording").rmdir()
            # the partial .trace and CSVs of this run
            for path in (set(OUT.glob(f"{label}_*")) - before) | (set(tmp.glob("instruments*.ktrace")) - ktraces):
                shutil.rmtree(path) if path.is_dir() else path.unlink()
            if left > 0:
                raise ToolError("the recording was cancelled; nothing was saved")
            raise ToolError(f"the recording took over {limit} s and was stopped; nothing was saved")
        try:
            _, stderr = proc.communicate(timeout=min(1, left))
            break
        except subprocess.TimeoutExpired:
            ticks += 1
            if ticks % PROGRESS_TICKS == 0:
                done = time.monotonic() - started
                progress(done, limit, f"recording and reading back: {int(done)} s of up to {limit} s")
    new = sorted(set(OUT.glob(f"{label}_*.json")) - before)
    if proc.returncode or not new:
        reason = (stderr.strip().splitlines() or ["no summary was written"])[-1]
        raise ToolError(f"recording failed (exit {proc.returncode}): {reason}")
    summary = json.loads(new[-1].read_text(encoding="utf-8"))
    summary["layer"] = layer
    new[-1].write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def tool_perf_runs(offset=0, limit=50):
    """Lists the saved recordings, newest first, with frames, FPS, GPU ms per frame, memory peaks and the translation
    layer each ran on (fingerprint and Wine, or native)."""
    runs = []
    for path in sorted(OUT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name == BASELINES.name:
            continue
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:  # a summary still being written
            continue
        gpu = s.get("gpu", {})
        runs.append({"run": path.stem, "program": (s.get("process") or {}).get("arguments"),
                     "frames": gpu.get("frames"), "fps": gpu.get("fps_estimate"),
                     "gpu_ms_mean": (gpu.get("frame_gpu_ms") or {}).get("mean"),
                     "metal_mib_peak": (s.get("metal_memory_mib") or {}).get("peak"),
                     "rss_mib_max": (s.get("process_rss_mib") or {}).get("max"),
                     "trace_kept": path.with_suffix(".trace").is_dir(), "layer": layer_label(s.get("layer"))})
    return page(runs, offset, limit)


def markdown_report(result):
    """Returns a perf_compare result as Markdown for a PR comment: one table of the headline and encoder numbers
    (a, b, change, change in %), and the five labels whose GPU ms per frame changed most."""
    rows = [(name, c) for group in (result["metrics"], {k: v for k, v in result.get("encoders", {}).items()
                                                        if isinstance(v, dict) and "a" in v}) for name, c in group.items()]
    cell = lambda v: "-" if v is None else str(v)
    lines = [f"**{result['a']}** (a) vs **{result['b']}** (b)", "", "| metric | a | b | change | % |", "|---|---|---|---|---|"]
    lines += [f"| {n} | {cell(c['a'])} | {cell(c['b'])} | {cell(c['change'])} | {cell(c['change_pct'])} |" for n, c in rows]
    labels = [l for l in result.get("labels", []) if l["ms_per_frame_change"]][:5]
    if labels:
        lines += ["", "| label | ms/frame a | ms/frame b | change |", "|---|---|---|---|"]
        lines += [f"| {l['label']} | {cell(l['ms_per_frame_a'])} | {cell(l['ms_per_frame_b'])} | "
                  f"{l['ms_per_frame_change']} |" for l in labels]
    if result.get("measure"):
        lines += ["", f"Not comparable between a Windows and a Metal run: {', '.join(result['measure']['not_comparable'])}."]
    if result["too_short"]:
        lines += ["", f"Too short to compare (under 100 frames): {', '.join(result['too_short'])}."]
    return "\n".join(lines)


def tool_perf_compare(a, b, short_us=25, markdown=False, skip_s=0):
    """Compares two saved recordings (names from perf_runs), a the reference and b the run after a change: the
    headline numbers (FPS, GPU ms, frame pacing, memory), then what changed in the GPU work and where: encoders and
    command buffers per frame, the share of encoders under short_us, the GPU's idle time, and each encoder label's
    count and GPU ms per frame, largest change first. layer says whether both ran on the same translation layer:
    with different layers it compares layers, not one change. A Windows run against a Metal run has `measure`: the
    GPU ms and Metal memory differ in kind and the encoders exist only in Metal, so use FPS, its lows, stutter and
    jitter. Recordings with under 100 frames are flagged: too short to compare. With markdown true the result also has
    `markdown`: the same numbers as tables for a PR comment. skip_s leaves out the first seconds of each recording,
    where shaders compile and resources load: the GPU numbers, hitches and Metal memory are recomputed from the
    per-frame files without them, and `skipped_s` says it; thermal state, process memory and encoders stay whole-run.
    `screen` appears when one run was recorded with the screen locked and the other not: FPS is then not comparable."""
    sa, sb = (steady_summary(r, skip_s) for r in (a, b))
    result = compare_summaries(sa, sb, a, b, short_us)
    if sa.get("steady"):
        result["skipped_s"] = sa["steady"]["skip_s"]
    return {**result, "markdown": markdown_report(result)} if markdown else result


NOT_COMPARABLE = ("gpu_ms_mean", "gpu_ms_p95", "metal_mib_peak")  # numbers a Windows run and a Metal run measure differently


def measurement(s):
    """Returns "windows" for a summary recorded on Windows (GPU time from PresentMon) and "metal" for one read from an
    Instruments trace (GPU time summed over the encoders)."""
    return "windows" if (s.get("device") or {}).get("platform") == "Windows" else "metal"


def gpu_state_level(s):
    """Returns the time-weighted GPU performance state of a summary (Minimum 0, Medium 1, Maximum 2), or None when it
    has no state shares."""
    share = s.get("gpu_performance_state_share") or {}
    levels = {"Minimum": 0, "Medium": 1, "Maximum": 2}
    return round(sum(levels[k] * v for k, v in share.items() if k in levels), 3) if share else None


def compare_summaries(sa, sb, a, b, short_us=25):
    """perf_compare over two loaded summaries named a and b."""
    metrics = {
        "fps": lambda s: s["gpu"].get("fps_estimate"),
        "fps_1pct_low": lambda s: s["gpu"].get("fps_1pct_low"),
        "fps_01pct_low": lambda s: s["gpu"].get("fps_01pct_low"),
        "stutter_rate_pct": lambda s: s["gpu"].get("stutter_rate_pct"),
        "frame_jitter_ms": lambda s: s["gpu"].get("frame_jitter_ms"),
        "gpu_ms_mean": lambda s: s["gpu"]["frame_gpu_ms"].get("mean"),
        "gpu_ms_p95": lambda s: s["gpu"]["frame_gpu_ms"].get("p95"),
        "frame_interval_ms_p95": lambda s: s["gpu"]["frame_interval_ms"].get("p95"),
        "metal_mib_peak": lambda s: s.get("metal_memory_mib", {}).get("peak"),
        "rss_mib_max": lambda s: s.get("process_rss_mib", {}).get("max"),
    }
    out = {}
    for name, get in metrics.items():
        try:
            out[name] = change(get(sa), get(sb))
        except (KeyError, TypeError):
            out[name] = change(None, None)
    short = [r for r, s in ((a, sa), (b, sb)) if (s.get("gpu") or {}).get("frames", 0) < 100]
    result = {"a": a, "b": b, "layer": layer_change(sa, sb, a, b), "metrics": out, "too_short": short}
    locked = [(s.get("machine") or {}).get("screen_locked") for s in (sa, sb)]
    if None not in locked and locked[0] != locked[1]:
        result["screen"] = {"a": locked[0], "b": locked[1],
                            "note": "one run was recorded with the screen locked and the other not: a locked session may "
                                    "leave frames unpaced by the display, so FPS, and GPU ms (they follow the GPU's performance "
                                    "state), are not comparable; record both with the Mac unlocked"}
    levels = [gpu_state_level(s) for s in (sa, sb)]
    if None not in levels and abs(levels[0] - levels[1]) >= 0.25:
        result["gpu_state"] = {"a": levels[0], "b": levels[1],
                               "note": "the GPU spent its time in different performance states (0 is all Minimum, 1 all Medium, "
                                       "2 all Maximum): the same work takes more GPU ms in a lower state, so GPU ms per frame "
                                       "are not comparable; pace both runs alike or compare under load (drawstress at a high dim)"}
    ma, mb = measurement(sa), measurement(sb)
    if ma != mb:
        result["measure"] = {"a": ma, "b": mb, "not_comparable": list(NOT_COMPARABLE),
                             "note": "a Windows run's GPU ms come from PresentMon and a Metal run's from Instruments, and only "
                                     "Metal records memory and encoders: compare fps, fps_1pct_low, fps_01pct_low, "
                                     "stutter_rate_pct and frame_jitter_ms"}
        result["encoders"] = {"not_comparable": "encoder numbers exist only in Metal recordings"}
        return result
    missing = [r for r, s in ((a, sa), (b, sb)) if not s.get("encoders")]
    if missing:
        result["encoders"] = {"missing_in": missing, "hint": "summaries written before version 0.4.0 have no encoder "
                                                             "numbers; record these runs again"}
        return result
    cut = str(int(short_us))
    if cut not in sa["encoders"]["short_share"] or cut not in sb["encoders"]["short_share"]:
        raise ToolError(f"short_us is one of {', '.join(map(str, perf_report.SHORT_US))}")
    gpu_idle = lambda s: s.get("gpu_idle") or {}
    work = {
        "encoders_per_frame_p50": lambda s: s["encoders"]["per_frame"].get("p50"),
        "command_buffers_per_frame_p50": lambda s: s["encoders"]["command_buffers_per_frame"].get("p50"),
        "short_encoder_share": lambda s: s["encoders"]["short_share"][cut],
        "gpu_idle_share": lambda s: gpu_idle(s).get("idle_share"),
        "idle_ms_per_frame_p50": lambda s: (gpu_idle(s).get("idle_ms_per_frame") or {}).get("p50"),
    }
    # a change in % of a share reads wrong (1.9 % to 49.7 % is +2516 %): shares give their change in points only
    result["encoders"] = {name: change(get(sa), get(sb), share=name.endswith("_share")) for name, get in work.items()}
    result["labels"] = label_changes(sa, sb)
    return result


# what decides a perf_check verdict: the metric, where it lives in a summary, and whether higher is worse
CHECKED = {
    "fps": (lambda s: s["gpu"].get("fps_estimate"), False),
    "gpu_ms_mean": (lambda s: s["gpu"]["frame_gpu_ms"].get("mean"), True),
    "encoders_per_frame_p50": (lambda s: s["encoders"]["per_frame"].get("p50"), True),
    "command_buffers_per_frame_p50": (lambda s: s["encoders"]["command_buffers_per_frame"].get("p50"), True),
}


def load_baselines():
    """Returns the saved references, by name."""
    return json.loads(BASELINES.read_text(encoding="utf-8")) if BASELINES.exists() else {}


def tool_perf_baseline(name=None, runs=None, skip_s=0):
    """Names a reference for perf_check, or lists them. With name and runs (names from perf_runs, several runs of the
    same program recorded with no change between them), it saves copies of their summaries as the reference `name`,
    replacing a previous one, and returns the range each number spans across them: that range, not one run, is what
    perf_check judges against, since repeated runs differ by a few percent, and `spread_pct`, each range's width in %
    of its midpoint: the noise of this program on this machine, which a change must exceed. With name alone it shows that reference;
    with nothing it lists them. With skip_s the reference keeps each run without its first skip_s seconds (the
    start-up, as perf_compare's skip_s) and perf_check applies the same cut to the run it judges, so both are
    steady-state; the runs need their per-frame files for that."""
    baselines = load_baselines()
    if name is not None and not name_ok(name):
        raise ToolError("a reference name holds only letters, digits, '.', '_' and '-'")
    if runs:
        if name is None:
            raise ToolError("runs need a name for the reference")
        if isinstance(runs, str):
            runs = [runs]
        skip = check_skip(skip_s)
        summaries = [steady_summary(r, skip) for r in runs]
        baselines[name] = {"runs": list(runs), "set": time.strftime("%Y-%m-%d"), "summaries": summaries,
                           **({"skip_s": skip} if skip else {})}
        OUT.mkdir(parents=True, exist_ok=True)
        BASELINES.write_text(json.dumps(baselines), encoding="utf-8")
    if name is not None:
        if name not in baselines:
            raise ToolError(f"no reference {name}; perf_baseline with no arguments lists them")
        b = baselines[name]
        span = ranges(b["summaries"])
        return {"name": name, "runs": b["runs"], "set": b["set"], "range": span, "spread_pct": spreads(span),
                **({"skip_s": b["skip_s"]} if b.get("skip_s") else {})}
    return {"baselines": [{"name": n, "runs": b["runs"], "set": b["set"]} for n, b in baselines.items()]}


def ranges(summaries):
    """Returns the lowest and highest value of each checked metric across the summaries; None where one lacks it."""
    out = {}
    for metric, (get, _) in CHECKED.items():
        values = []
        for s in summaries:
            try:
                values.append(get(s))
            except (KeyError, TypeError):
                values.append(None)
        out[metric] = None if None in values else {"min": min(values), "max": max(values)}
    return out


def spreads(span):
    """Returns each range's width as a % of its midpoint: how far equal runs of the reference differ, the noise a
    change must beat. None where the range is None."""
    return {m: None if r is None else round(200 * (r["max"] - r["min"]) / (r["max"] + r["min"]), 1) if r["max"] + r["min"] else 0.0
            for m, r in span.items()}


def tool_perf_check(run, baseline, margin_pct=3):
    """Judges a recording against a reference saved with perf_baseline: regressed when FPS falls under the
    reference's lowest FPS by more than margin_pct, GPU ms per frame rises over its highest by more than margin_pct,
    or encoders or command buffers per frame exceed its highest; improved when a number leaves the range the other
    way and none regressed; same otherwise. Frame pacing, short encoders and GPU idle time are reported by the
    comparison but do not decide: they vary too much between equal runs. A run from Windows against a Metal
    reference (or the reverse) is judged on FPS alone. A reference saved with skip_s judges the run without its first
    skip_s seconds too (`skipped_s` says so). Returns the reasons and perf_compare's
    full comparison against the reference's first run."""
    baselines = load_baselines()
    if baseline not in baselines:
        raise ToolError(f"no reference {baseline}; perf_baseline with no arguments lists them")
    ref = baselines[baseline]
    s = steady_summary(run, ref.get("skip_s", 0))
    span = ranges(ref["summaries"])
    worse, better, unchecked = [], [], []
    cross = measurement(ref["summaries"][0]) != measurement(s)
    for metric, (get, higher_is_worse) in CHECKED.items():
        if cross and metric != "fps":
            unchecked.append(metric)
            continue
        try:
            value = get(s)
        except (KeyError, TypeError):
            value = None
        if value is None or span[metric] is None:
            unchecked.append(metric)
            continue
        lo, hi = span[metric]["min"], span[metric]["max"]
        margin = 0 if metric.endswith("_p50") else margin_pct / 100
        if higher_is_worse and value > hi * (1 + margin):
            worse.append(reason(metric, value, lo, hi))
        elif not higher_is_worse and value < lo * (1 - margin):
            worse.append(reason(metric, value, lo, hi))
        elif higher_is_worse and value < lo * (1 - margin) or not higher_is_worse and value > hi * (1 + margin):
            better.append(reason(metric, value, lo, hi))
    verdict = "regressed" if worse else "improved" if better else "same"
    result = {"run": run, "baseline": baseline, "verdict": verdict, "margin_pct": margin_pct, "regressed": worse,
              "improved": better, "unchecked": unchecked, "range": span,
              "comparison": compare_summaries(ref["summaries"][0], s, ref["runs"][0], run)}
    if ref.get("skip_s"):
        result["skipped_s"] = ref["skip_s"]
    if (s.get("gpu") or {}).get("frames", 0) < 100:
        result["hint"] = "under 100 frames: too short to judge; record 30 s or more"
    if cross:
        result["hint_measure"] = "the reference and the run come from Windows and Metal: GPU ms and encoder numbers do not " \
                                 "measure the same thing, so only FPS decides"
    elif unchecked:
        result["hint_unchecked"] = "a summary written before version 0.4.0 has no encoder numbers; record it again"
    return result


def reason(metric, value, lo, hi):
    """Returns one verdict reason: the metric, the run's value and the reference's range."""
    return {"metric": metric, "value": value, "range_min": lo, "range_max": hi}


def change(va, vb, share=False):
    """Returns a number's value in a and b, its change and, unless it is a share, its change in %."""
    delta = None if va is None or vb is None else round(vb - va, 3)
    pct = None if share or delta is None or not va else round(100 * delta / va, 1)
    return {"a": va, "b": vb, "change": delta, "change_pct": pct}


def label_changes(sa, sb, top=20):
    """Returns each encoder label's count and GPU ms per frame in two summaries, largest change in ms per frame
    first. A label missing from a summary that holds the full 20 labels may only have fallen out of that list, so it
    is outside_top_20 rather than new or gone."""
    def per_frame(s):
        frames = (s.get("gpu") or {}).get("frames") or 1
        labels = s["encoders"]["by_label"]
        return {l["label"]: (l["per_frame"], round(l["total_ms"] / frames, 4)) for l in labels}, len(labels) >= top
    (la, full_a), (lb, full_b) = per_frame(sa), per_frame(sb)
    rows = []
    for name in sorted(la.keys() | lb.keys()):
        (count_a, ms_a), (count_b, ms_b) = la.get(name, (None, None)), lb.get(name, (None, None))
        if name not in lb:
            state = "outside_top_20" if full_b else "gone"
        elif name not in la:
            state = "outside_top_20" if full_a else "new"
        else:
            state = "same" if (count_a, ms_a) == (count_b, ms_b) else "changed"
        delta = None if state == "outside_top_20" else round((ms_b or 0) - (ms_a or 0), 4)
        rows.append({"label": name, "state": state, "per_frame_a": count_a, "per_frame_b": count_b,
                     "ms_per_frame_a": ms_a, "ms_per_frame_b": ms_b, "ms_per_frame_change": delta})
    rows.sort(key=lambda r: -abs(r["ms_per_frame_change"] or 0))
    return rows[:top]


def tool_perf_export_trace(run):
    """Writes a recording's GPU frames as a Chrome trace file, `<run>.chrome-trace` in the runs directory, that
    ui.perfetto.dev and chrome://tracing open: one slice per GPU frame, from its start for its GPU time (the sum of
    its encoders' time, so a frame with parallel encoders can show shorter than it took), with the compute, fragment
    and vertex split as arguments. Returns the file name and the number of frames."""
    run_path(run)
    source = OUT / f"{run}.frames.csv"
    if not source.exists():
        raise ToolError(f"{run} has no per-frame file; record it again")
    events = []
    with open(source, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            events.append({"name": "GPU frame", "ph": "X", "pid": 1, "tid": 1, "ts": float(row["start_ms"]) * 1000,
                           "dur": float(row["gpu_ms_total"]) * 1000,
                           "args": {"frame": int(row["frame"]), **{k[7:]: float(v) for k, v in row.items()
                                                                  if k.startswith("gpu_ms_") and k != "gpu_ms_total"}}})
    target = OUT / f"{run}.chrome-trace"
    target.write_text(json.dumps({"traceEvents": events, "displayTimeUnit": "ms"}), encoding="utf-8")
    return {"file": target.name, "frames": len(events)}


PANEL_PRESETS = ("fps", "compare")
PANEL_POINTS = 5000


def dig(s, path):
    """Returns the value at `path` (a tuple of keys) in a summary, or None where a key is missing."""
    for key in path:
        s = s.get(key) if isinstance(s, dict) else None
    return s


# what perf_history follows across recordings: where each number lives in a summary
HISTORY = {"fps": ("gpu", "fps_estimate"), "fps_1pct_low": ("gpu", "fps_1pct_low"),
           "gpu_ms_mean": ("gpu", "frame_gpu_ms", "mean"), "stutter_rate_pct": ("gpu", "stutter_rate_pct"),
           "hitches": ("hitches", "count"), "metal_mib_peak": ("metal_memory_mib", "peak")}


def tool_perf_history(prefix, limit=50, skip_s=0):
    """Lists the recordings whose name starts with `prefix`, oldest first, with their FPS, 1% low, GPU ms, stutter,
    hitches and peak Metal MiB, and the change from the first to the last: how a number moved over a series of runs, such as
    one recording per version of a translation layer. Read a trend as real only when it exceeds the spread_pct that
    perf_baseline reports for equal runs. Runs from Windows and Metal in one series are flagged: their GPU ms and
    memory do not compare. skip_s leaves out the first seconds of each recording (the start-up), as perf_compare does."""
    if not name_ok(prefix):
        raise ToolError("a prefix holds only letters, digits, '.', '_' and '-'")
    found = []
    for path in sorted(OUT.glob(f"{prefix}*.json"), key=lambda p: p.stat().st_mtime):
        if path == BASELINES:
            continue
        try:
            s = steady_summary(path.stem, skip_s)
        except ValueError:  # a summary still being written
            continue
        found.append((path.stem, s))
    if not found:
        raise ToolError(f"no run starts with {prefix}; perf_runs lists them")
    found = found[-max(1, min(int(limit), MAX_LIMIT)):]
    rows = [{"run": run, "layer": layer_label(s.get("layer")), "source": measurement(s),
             **{k: dig(s, path) for k, path in HISTORY.items()}} for run, s in found]
    result = {"prefix": prefix, "runs": rows,
              "change": {k: change(rows[0][k], rows[-1][k]) for k in HISTORY}}
    if len({r["source"] for r in rows}) > 1:
        result["hint"] = "the series mixes Windows and Metal runs: read only fps, fps_1pct_low and stutter_rate_pct"
    elif len(rows) < 3:
        result["hint"] = "under 3 runs: not a trend yet"
    return result


# what perf_gate can require: the argument, where the number lives in a summary and whether it is a floor or a ceiling
GATES = {"fps_min": (("gpu", "fps_estimate"), "min"), "fps_1pct_low_min": (("gpu", "fps_1pct_low"), "min"),
         "stutter_rate_pct_max": (("gpu", "stutter_rate_pct"), "max"), "gpu_ms_p95_max": (("gpu", "frame_gpu_ms", "p95"), "max"),
         "hitches_max": (("hitches", "count"), "max"), "metal_mib_max": (("metal_memory_mib", "peak"), "max")}


def tool_perf_gate(run, fps_min=None, fps_1pct_low_min=None, stutter_rate_pct_max=None, gpu_ms_p95_max=None,
                   hitches_max=None, metal_mib_max=None, skip_s=0):
    """Checks a recording against budgets and says pass or fail: a floor for FPS and the 1% low, a ceiling for the
    stutter rate, the p95 GPU ms per frame, the hitch count and the peak Metal MiB. Give at least one. A number the
    recording lacks fails its budget (value null): a gate must not pass on missing data. Returns each budget with its
    limit, the value and whether it held. Use it as a bar a change must clear, where perf_check judges against equal runs.
    skip_s leaves out the first seconds of the recording (the start-up), as perf_compare does."""
    given = {k: v for k, v in (("fps_min", fps_min), ("fps_1pct_low_min", fps_1pct_low_min),
                               ("stutter_rate_pct_max", stutter_rate_pct_max), ("gpu_ms_p95_max", gpu_ms_p95_max),
                               ("hitches_max", hitches_max), ("metal_mib_max", metal_mib_max)) if v is not None}
    if not given:
        raise ToolError(f"give at least one budget: {', '.join(GATES)}")
    s = steady_summary(run, skip_s)
    checks = []
    for budget, limit in given.items():
        path, kind = GATES[budget]
        value = dig(s, path)
        ok = value is not None and (value >= limit if kind == "min" else value <= limit)
        checks.append({"budget": budget, "limit": limit, "value": value, "ok": ok})
    result = {"run": run, "pass": all(c["ok"] for c in checks), "checks": checks}
    if s.get("steady"):
        result["skipped_s"] = s["steady"]["skip_s"]
    if (s.get("gpu") or {}).get("frames", 0) < 100:
        result["hint"] = "under 100 frames: too short to trust; record 30 s or more"
    return result


CSV_TOL_MS = 0.002  # frames.csv rounds start times to 0.001 ms, so a gap at the hitch threshold may read 0.001 ms short


def read_frames(run):
    """Returns a run's GPU frames as (frame, start ms, GPU ms) from its frames.csv."""
    source = OUT / f"{run}.frames.csv"
    if not source.exists():
        raise ToolError(f"{run} has no per-frame file; record it again")
    with open(source, newline="", encoding="utf-8") as f:
        return [(int(r["frame"]), float(r["start_ms"]), float(r["gpu_ms_total"])) for r in csv.DictReader(f)]


def read_memory(run):
    """Returns a run's Metal memory as (ms, MiB) samples, or [] when it has none."""
    source = OUT / f"{run}.metal_memory.csv"
    if not source.exists():
        return []
    with open(source, newline="", encoding="utf-8") as f:
        return [(float(r["time_ms"]), int(r["metal_allocated_bytes"]) / 2**20) for r in csv.DictReader(f)]


def check_skip(skip_s):
    """Returns `skip_s` as a number of seconds from 0 to 600, or raises ToolError."""
    try:
        skip = float(skip_s or 0)
    except (TypeError, ValueError):
        raise ToolError("skip_s is a number of seconds") from None
    if not 0 <= skip <= 600:
        raise ToolError("skip_s is 0 to 600 seconds")
    return skip


def steady_summary(run, skip_s=0):
    """Returns a run's summary; with `skip_s` above 0, with the GPU numbers (FPS and its lows, GPU and interval ms,
    stutter, jitter), the hitches and the Metal memory recomputed from frames.csv and metal_memory.csv without the
    first `skip_s` seconds after its first frame: the start-up, where shaders compile and resources load. The CPU use
    is dropped; the thermal state, the process memory, the encoders and the GPU idle time stay those of the whole run,
    as `steady.whole_run` says. Causes are kept only for the hitches the summary lists (the 20 longest)."""
    s = json.loads(run_path(run).read_text(encoding="utf-8"))
    skip = check_skip(skip_s)
    if not skip:
        return s
    rows = read_frames(run)
    cut = rows[0][1] + skip * 1000 if rows else 0
    kept = [r for r in rows if r[1] >= cut]
    if len(kept) < 2:
        raise ToolError(f"{run} has under 2 frames after the first {skip:g} s; use a smaller skip_s")
    starts, totals = [r[1] for r in kept], [r[2] for r in kept]
    gaps = [b - a for a, b in zip(starts, starts[1:]) if b > a]
    gpu = {k: v for k, v in (s.get("gpu") or {}).items() if k not in ("per_channel_ms", "intervals", "throttling_analysis")}
    gpu.update(frames=len(kept), frame_gpu_ms=perf_report.stats(totals), frame_interval_ms=perf_report.stats(gaps),
               fps_estimate=round(1000 / statistics.median(gaps), 1) if gaps else None,
               **{k: None for k in ("fps_1pct_low", "fps_01pct_low", "stutter_rate_pct", "frame_jitter_ms")})
    gpu.update(perf_report.frame_pacing(gaps, totals))
    old = s.get("hitches") or {}
    limit = old.get("threshold_ms")
    first = kept[0][0]
    count = sum(1 for a, b in zip(starts, starts[1:]) if limit and b - a > limit - CSV_TOL_MS)
    worst = [h for h in old.get("worst", []) if h["frame"] > first]
    hitches = {"count": count, "causes": dict(collections.Counter(h["cause"] for h in worst).most_common()),
               "worst": worst}
    span = starts[-1] - starts[0] if starts else 0
    hitches["per_minute"] = round(count / (span / 60000), 2) if span > 0 else None
    if limit:
        hitches["threshold_ms"] = limit
    if count > len(worst):
        hitches["causes_partial"] = True
    memory = [mib for t, mib in read_memory(run) if t >= cut]
    s.update(gpu=gpu, hitches=hitches)
    s.pop("cpu", None)
    s.pop("metal_memory_mib", None)
    if memory:
        s["metal_memory_mib"] = {"peak": round(max(memory), 2), "samples": len(memory)}
    s["steady"] = {"skip_s": skip, "whole_run": ["thermal_state_share", "process_rss_mib", "encoders", "gpu_idle", "gpu_counters"]}
    return s


def panel_run(run, skip_s=0):
    """Returns what the panel shows for one recording: numbers and labels from its summary, its GPU frames and Metal
    memory cut to PANEL_POINTS points that keep every hitch, and no path. With `skip_s`, as steady_summary."""
    s = steady_summary(run, skip_s)
    rows = read_frames(run)
    if s.get("steady") and rows:
        cut = rows[0][1] + s["steady"]["skip_s"] * 1000
        rows = [r for r in rows if r[1] >= cut]
    hitches = s.get("hitches") or {}
    limit, causes = hitches.get("threshold_ms"), {h["frame"]: h for h in hitches.get("worst", [])}
    marks = [[b[1], b[2], round(b[1] - a[1], 3), causes.get(b[0], {}).get("cause", ""), causes.get(b[0], {}).get("cpu_pct")]
             for a, b in zip(rows, rows[1:]) if limit and b[1] - a[1] > limit - CSV_TOL_MS]
    marked = {m[0] for m in marks}
    stride = max(1, len(rows) // PANEL_POINTS)
    frames = [[t, ms] for i, (_, t, ms) in enumerate(rows) if i % stride == 0 or t in marked]
    samples = read_memory(run)
    if s.get("steady") and rows:
        samples = [x for x in samples if x[0] >= rows[0][1]]
    memory = [[t, round(mib, 2)] for t, mib in samples[::max(1, len(samples) // PANEL_POINTS)]]
    return {"name": run, "layer": layer_label(s.get("layer")), "source": measurement(s), "gpu": s.get("gpu"), "hitches": hitches,
            "thermal_state_share": s.get("thermal_state_share"), "metal_memory_mib": s.get("metal_memory_mib"),
            "process_rss_mib": s.get("process_rss_mib"), "cpu": s.get("cpu"), "counters": s.get("gpu_counters"), "frames": frames, "marks": marks, "memory": memory,
            "encoders": [] if measurement(s) == "windows" else (s.get("encoders") or {}).get("by_label", [])[:20]}


TAB_IDS = ("summary", "ab", "frames", "encoders", "counters", "memory", "data")


def read_layout():
    """Returns the panel layout saved as panel.json in the runs directory, a list of {id, on} tabs, or None when there is
    none; a file that is not that list raises ToolError."""
    path = OUT / "panel.json"
    if not path.exists():
        return None
    try:
        layout = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ToolError("panel.json is not valid JSON") from None
    if not isinstance(layout, list) or not all(isinstance(w, dict) and w.get("id") in TAB_IDS and isinstance(w.get("on"), bool) for w in layout):
        raise ToolError(f"panel.json is a list of {{\"id\": tab, \"on\": true or false}} with tab one of {', '.join(TAB_IDS)}")
    return [{"id": w["id"], "on": w["on"]} for w in layout]


def panel_data(runs, preset=None, skip_s=0):
    """Returns the payload a panel shows for one or two runs: the preset, each run's panel_run and, for two runs, the
    headline comparison. `preset` defaults to compare for two runs and fps for one; `skip_s` leaves out the start-up."""
    preset = preset or ("compare" if len(runs) == 2 else "fps")
    if preset not in PANEL_PRESETS:
        raise ToolError(f"preset is one of {', '.join(PANEL_PRESETS)}")
    if not 1 <= len(runs) <= 2 or (preset == "compare" and len(runs) != 2):
        raise ToolError("runs holds one or two run names from perf_runs; the compare preset needs two")
    skip = check_skip(skip_s)
    data = [panel_run(r, skip) for r in runs]
    compare, not_comparable, labels = None, [], []
    if len(runs) == 2:
        try:
            sa, sb = (steady_summary(r, skip) for r in runs)
            result = compare_summaries(sa, sb, *runs)
            compare, not_comparable = result["metrics"], (result.get("measure") or {}).get("not_comparable", [])
            labels = result.get("labels") or []
        except (KeyError, TypeError):  # a summary from before the numbers the comparison reads
            pass
    return {"preset": preset, "runs": data, "compare": compare, "not_comparable": not_comparable, "labels": labels[:10],
            "skip_s": skip, "layout": read_layout()}


def tool_perf_panel(name, runs, preset="fps", skip_s=0, layout=None):
    """Writes one HTML file, `<name>.panel.html` in the runs directory, that shows one or two recordings in a
    browser without a server: GPU time per frame with the hitches marked, the numbers (FPS and its lows, frame
    time, jitter, stutter, memory, thermal state), Metal memory over time and, for two runs, A against B. The file
    holds the data itself, no path, and loads nothing from the network; the viewer can hide and reorder the
    widgets and export the layout as JSON. preset `fps` is the timeline, numbers and memory; `compare` (two runs)
    puts A against B first. skip_s leaves out the first seconds of each recording (the start-up), as perf_compare does.
    layout (tab ids in the order to show) is saved as panel.json in the runs directory and becomes the default tab
    order of every panel, the live one too, until the viewer changes it in the browser; ids left out are hidden but
    can be switched back on; tabs are summary, ab, frames, encoders, counters, memory and data, and a panel.json
    you wrote yourself, or copied from the panel's Layout JSON, works the same.
    Returns the file name, the runs, the frames shown and the file's bytes."""
    if not name_ok(name):
        raise ToolError("a panel name holds only letters, digits, '.', '_' and '-'")
    if layout is not None:
        if isinstance(layout, str) or not all(i in TAB_IDS for i in layout):
            raise ToolError(f"layout is a list of tabs, each one of {', '.join(TAB_IDS)}")
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "panel.json").write_text(json.dumps([{"id": i, "on": True} for i in dict.fromkeys(layout)] +
                                                   [{"id": i, "on": False} for i in TAB_IDS if i not in layout]) + "\n", encoding="utf-8")
    payload = panel_data(runs, preset, skip_s)
    data = payload["runs"]
    text = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")
    page_html = (TOOLS_DIR / "data" / "panel.html").read_text(encoding="utf-8").replace("/*PAYLOAD*/null", text)
    target = OUT / f"{name}.panel.html"
    target.write_text(page_html, encoding="utf-8")
    return {"file": target.name, "runs": list(runs), "frames": sum(len(r["frames"]) for r in data),
            "bytes": target.stat().st_size}


REFRESH_RATES = (24, 30, 48, 50, 60, 72, 75, 90, 100, 120, 144, 165, 240)  # common display rates, in Hz


def display_synced_hz(gpu):
    """Returns the display rate a run's FPS sits on, or None: the FPS within 1 % of a common rate and the 95th percentile
    frame interval within 30 % above the median, which is what a run paced by the display looks like (not proof; a real
    D3D11 run under Wine at 118.9 FPS had 17 %)."""
    fps, interval = gpu.get("fps_estimate"), gpu.get("frame_interval_ms") or {}
    p50, p95 = interval.get("p50"), interval.get("p95")
    if not fps or not p50 or not p95 or p95 > p50 * 1.3:
        return None
    return next((hz for hz in REFRESH_RATES if abs(fps - hz) <= hz * 0.01), None)


def tool_perf_diagnose(run, min_encoders=4, short_us=25, short_share=0.25):
    """Says whether a saved recording splits its GPU work into too many short encoders, the pattern of translation
    layers such as DXMT, Mullion or MoltenVK, with the numbers behind it: encoders and command buffers per frame, the
    share of short encoders, the labels with the most GPU time and the GPU's idle time. Read the idle time together
    with the FPS: a program waiting for vsync idles too. Defaults come from bgfx 17-drawstress on an M1 Pro: 7
    encoders per frame and 50% under 25 us under Mullion, 2 and 2% in native Metal."""
    s = json.loads(run_path(run).read_text(encoding="utf-8"))
    encoders = s.get("encoders")
    if not encoders:
        raise ToolError(f"{run} was summarized before version 0.4.0 and has no encoder numbers; record it again")
    share = encoders["short_share"].get(str(int(short_us)))
    if share is None:
        raise ToolError(f"short_us is one of {', '.join(map(str, perf_report.SHORT_US))}")
    per_frame = encoders["per_frame"].get("p50", 0)
    gpu = s.get("gpu") or {}
    frames = gpu.get("frames", 0)
    too_many_short = per_frame >= min_encoders and share >= short_share

    frame_gpu_ms = gpu.get("frame_gpu_ms") or {}
    frame_interval_ms = gpu.get("frame_interval_ms") or {}
    gpu_idle = s.get("gpu_idle") or {}
    stutter_rate = gpu.get("stutter_rate_pct") or 0.0
    jitter_ms = gpu.get("frame_jitter_ms") or 0.0
    worst_spike = frame_interval_ms.get("max") or frame_gpu_ms.get("max") or 0.0

    if gpu.get("stutter_rate_pct") is None:
        stutter_verdict = "UNKNOWN"
    elif stutter_rate > 7.0:
        stutter_verdict = "SEVERE_STUTTER"
    elif stutter_rate >= 2.0:
        stutter_verdict = "MICRO_STUTTER"
    else:
        stutter_verdict = "SMOOTH"

    idle_share = gpu_idle.get("idle_share")
    gpu_ms_mean = frame_gpu_ms.get("mean") or 0.0
    interval_ms_mean = frame_interval_ms.get("mean") or 0.0
    interval_p50 = frame_interval_ms.get("p50") or 0.0
    interval_p95 = frame_interval_ms.get("p95") or 0.0
    mem_working_set = max((s.get("process_rss_mib") or {}).get("max") or 0.0,
                          (s.get("metal_memory_mib") or {}).get("peak") or 0.0)

    high_variance = jitter_ms >= 3.0 or (interval_p95 - interval_p50) >= 5.0
    high_memory = mem_working_set >= 1500.0
    has_frame_data = bool(frame_gpu_ms.get("count", 0) > 0 or frame_interval_ms.get("count", 0) > 0)

    if has_frame_data and high_variance and high_memory:
        # Inferred from a large working set plus uneven frame times; memory bandwidth itself is not measured.
        bottleneck = "MEMORY_PRESSURE_SUSPECTED"
    elif idle_share is None:
        bottleneck = "UNKNOWN"
    elif has_frame_data and (idle_share >= 0.25 or (too_many_short and idle_share >= 0.20)):
        bottleneck = "CPU_SUBMISSION_BOUND"
    elif has_frame_data and idle_share <= 0.15 and gpu_ms_mean > 0 and (
            gpu_ms_mean >= 0.80 * interval_ms_mean if interval_ms_mean > 0 else True):
        bottleneck = "GPU_BOUND"
    else:
        bottleneck = "BALANCED"

    recommendations = []
    if bottleneck == "GPU_BOUND":
        recommendations.append("Activar FSR si la GPU está saturada al 100% o usar escalado dinámico de resolución.")
        recommendations.append("Reducir resolución interna de renderizado, calidad de postprocesado o sombreadores pesados.")
    elif bottleneck == "CPU_SUBMISSION_BOUND":
        if s.get("template") == "Windows Native Trace":
            recommendations.append("Fijar FlipQueueSize=3 en el controlador AMD o DirectX para amortiguar el despacho de la CPU.")
        recommendations.append("Consolidar draw calls mediante instancing o reducir complejidad de geometría y objetos dinámicos.")
    elif bottleneck == "MEMORY_PRESSURE_SUSPECTED":
        recommendations.append("Hipótesis (el ancho de banda no se mide): reducir resolución de sombras de 2048 a 1024 para aliviar el bus UMA.")
        recommendations.append("Hipótesis: limitar cascadas de sombras a 2 en exteriores para mitigar el consumo de memoria unificada.")
    if too_many_short:
        recommendations.append("Consolidar render passes y reducir encoders breves para mitigar sobrecarga en la capa de traducción.")
    if stutter_verdict in ("MICRO_STUTTER", "SEVERE_STUTTER"):
        recommendations.append("Activar un limitador de FPS (framerate cap) o sincronización vertical/VRR para estabilizar los intervalos de presentación.")
    throttling = gpu.get("throttling_analysis") or {}
    if throttling.get("thermal_throttling_detected"):
        drift_pct = throttling.get("fps_drift_pct", 0)
        recommendations.append(f"Estrangulamiento térmico detectado ({drift_pct}% caída de FPS): revisar curvas de ventilación y disipación térmica del APU/GPU.")
    hitches = s.get("hitches") or {}
    top_cause = next(iter(hitches.get("causes") or {}), None)
    if top_cause == "shader_compile":
        recommendations.append("Los tirones coinciden con el compilador gráfico: precompilar o calentar la caché de shaders.")
    elif top_cause == "memory_growth":
        recommendations.append("Los tirones coinciden con crecimiento de memoria Metal: revisar cargas de recursos en medio de la partida.")
    elif top_cause == "thermal":
        recommendations.append("Los tirones coinciden con un estado térmico distinto de Nominal.")
    synced = display_synced_hz(gpu)
    if synced:
        recommendations.append(f"El FPS ({gpu['fps_estimate']}) coincide con una pantalla de {synced} Hz y los intervalos son regulares: "
                               "probablemente sincronización vertical; la GPU tiene margen y baja de estado de rendimiento, así que sus ms por frame "
                               "suben: compare solo ejecuciones con el mismo ritmo.")
    activity = s.get("gpu_activity") or {}
    if activity.get("gpu_recovered"):
        n = activity["recoveries"]
        recommendations.append(f"La GPU se recuperó {n} {'vez' if n == 1 else 'veces'} durante la grabación (recoveryCount del "
                               "controlador): un cuelgue o un comando que superó su tiempo; las cifras de esta grabación no son fiables.")
    if (activity.get("split_scenes") or 0) > 0:
        recommendations.append(f"El contador SplitSceneCount del controlador creció en {activity['split_scenes']}: la GPU dividió "
                               f"{activity['split_scenes']} escenas; su causa no se mide aquí, compárelo entre grabaciones.")
    if bottleneck == "UNKNOWN":
        recommendations.append("Sin datos de actividad de GPU en esta grabación: no hay veredicto de cuello de botella.")
    elif not recommendations:
        recommendations.append("Rendimiento equilibrado; no se detectan cuellos de botella críticos.")

    return {"run": run, "too_many_short_encoders": too_many_short,
            "thresholds": {"min_encoders": min_encoders, "short_us": int(short_us), "short_share": short_share},
            "encoders_per_frame_p50": per_frame,
            "command_buffers_per_frame_p50": encoders["command_buffers_per_frame"].get("p50"),
            "short_encoder_share": share, "fps": gpu.get("fps_estimate"),
            "bottleneck": bottleneck,
            "stutter_analysis": {"stutter_rate_pct": stutter_rate, "worst_spike_ms": worst_spike,
                                 "verdict": stutter_verdict},
            "recommendations": recommendations, "hitches": hitches or None,
            "display_synced_hz": synced, "gpu_idle": s.get("gpu_idle"), "gpu_activity": s.get("gpu_activity"), "by_label": encoders["by_label"],
            "too_short": frames < 100}


def tool_trace_tables(trace):
    """Lists the data tables (schemas) a .trace recording holds; recordings keep their .trace only with KEEP_TRACE=1."""
    toc = perf_report.toc_of(trace_path(trace))
    return {"tables": sorted({t.attrib["schema"] for t in toc.iter("table") if "schema" in t.attrib})}


def tool_trace_query(trace, schema, offset=0, limit=50, pid=None):
    """Returns one page of rows of one table of a .trace as {column: value}, optionally only one process's rows."""
    if not schema.replace("-", "").isalnum():
        raise ToolError("schema holds only letters, digits and '-'; trace_tables lists them")
    xpath = f'/trace-toc/run[@number="1"]/data/table[@schema="{schema}"]'
    rows = []
    for row in perf_report.rows(perf_report.export(trace_path(trace), xpath=xpath)):
        if pid is not None and "process" in row and perf_report.pid_of(row["process"]) != int(pid):
            continue
        rows.append({k: (v.attrib.get("fmt") or v.text) if v is not None else None for k, v in row.items()})
    return page(rows, offset, limit)


# the tables of a kept .trace that say most about a translation layer, counted by trace_count when none are named
COUNTED_TABLES = ["metal-gpu-intervals", "metal-application-encoders-list", "metal-command-buffer-completed",
                  "graphics-compiler-spill-events", "graphics-compiler-activity-intervals",
                  "metal-shader-profiler-shader-list", "metal-resource-allocations", "metal-gpu-counter-intervals",
                  "gpu-shader-profiler-sample", "time-profile"]


def tool_trace_count(trace, tables=None):
    """Counts the rows of several tables of a kept .trace, in all and per process, so a recording's useful tables
    show before reading them: a table with 0 rows needs another instrument or Xcode, not a bigger page."""
    tables = tables or COUNTED_TABLES
    known = set(tool_trace_tables(trace)["tables"])
    out = {}
    for schema in tables:
        if not schema.replace("-", "").isalnum():
            raise ToolError("a table name holds only letters, digits and '-'; trace_tables lists them")
        if schema not in known:
            out[schema] = {"rows": None, "note": "not in this trace"}
            continue
        xpath = f'/trace-toc/run[@number="1"]/data/table[@schema="{schema}"]'
        total, per = 0, {}
        try:
            for row in perf_report.rows(perf_report.export(trace_path(trace), xpath=xpath)):
                total += 1
                if "process" in row and row["process"] is not None:
                    name = row["process"].attrib.get("fmt") or str(perf_report.pid_of(row["process"]))
                    per[name] = per.get(name, 0) + 1
        except (RuntimeError, subprocess.TimeoutExpired) as error:  # one table's export failing leaves the others
            out[schema] = {"rows": None, "note": str(error)}
            continue
        out[schema] = {"rows": total, "by_process": dict(sorted(per.items(), key=lambda kv: -kv[1])[:10])}
    return {"trace": trace, "tables": out}


def tool_perf_baseline_record(name, count=3, skip_s=0, **record):
    """Records the same program `count` times in a row with perf_record's arguments and saves the runs as the
    reference `name` for perf_check, returning the range each number spans across them. Runs are named
    `name`-1, `name`-2, ... Each recording takes its seconds plus about a minute to read back. skip_s as in
    perf_baseline: the reference leaves out each run's start-up."""
    if not name_ok(name):
        raise ToolError("a reference name holds only letters, digits, '.', '_' and '-'")
    check_skip(skip_s)
    count = int(count)
    if not 1 <= count <= 10:
        raise ToolError("count is 1 to 10")
    runs = []
    for i in range(1, count + 1):
        before = set(OUT.glob(f"{name}-{i}_*.json"))
        tool_perf_record(f"{name}-{i}", **record)
        runs.append(next(iter(set(OUT.glob(f"{name}-{i}_*.json")) - before)).stem)
    return tool_perf_baseline(name, runs, skip_s)


# what perf_ab compares: where in a summary, and whether a higher number is better
AB_METRICS = {"fps_estimate": (("gpu", "fps_estimate"), True), "fps_1pct_low": (("gpu", "fps_1pct_low"), True),
              "frame_gpu_ms_mean": (("gpu", "frame_gpu_ms", "mean"), False),
              "stutter_rate_pct": (("gpu", "stutter_rate_pct"), False)}


def ab_verdict(a, b, higher_better):
    """Returns "better", "worse" or "same" for the values `b` against `a`: a change counts only when every b value lies
    outside the range the a values span, on one side, so a run's own spread never passes for an effect."""
    if not a or not b:
        return "unknown"
    if min(b) > max(a):
        return "better" if higher_better else "worse"
    if max(b) < min(a):
        return "worse" if higher_better else "better"
    return "same"


def tool_perf_ab(name, env_a, env_b, rounds=1, skip_s=0, **record):
    """Records the same program with two environments in the order A B B A (repeated `rounds` times, so drift hits both
    sides equally) and says per metric whether B is better, worse or the same as A, with every value behind it.
    env_a and env_b are NAME=VALUE pairs separated by spaces; empty means none. Runs are named `name`-a1, `name`-b1, ...
    Each recording takes its seconds plus about a minute to read back. skip_s leaves out the first seconds of every
    recording (the start-up) when the verdicts are drawn, as perf_compare does; the recordings are whole."""
    if not name_ok(name):
        raise ToolError("a name holds only letters, digits, '.', '_' and '-'")
    check_skip(skip_s)
    rounds = int(rounds)
    if not 1 <= rounds <= 5:
        raise ToolError("rounds is 1 to 5")
    record.pop("env", None)
    record.pop("label", None)
    check_env(env_a), check_env(env_b)
    runs = {"a": [], "b": []}
    for side in "abba" * rounds:
        label = f"{name}-{side}{len(runs[side]) + 1}"
        before = set(OUT.glob(f"{label}_*.json"))
        tool_perf_record(label, env=env_a if side == "a" else env_b, **record)
        runs[side].append(next(iter(set(OUT.glob(f"{label}_*.json")) - before)).stem)
    return ab_report(name, env_a, env_b, runs, skip_s)


def cold_warm_report(name, first, second):
    """Builds perf_cold_warm's answer from the summaries of its two runs, each (run name, summary): per run the frames,
    hitches, their causes and the graphics compiler's busy ms, and `first_seen_hitches`, how many more shader_compile
    hitches the first run had than the second."""
    def part(run, summary):
        hitches = summary.get("hitches", {})
        return {"run": run, "frames": summary.get("gpu", {}).get("frames"), "hitches": hitches.get("count"),
                "per_minute": hitches.get("per_minute"), "causes": hitches.get("causes", {}),
                "compiler_busy_ms": summary.get("graphics_compiler", {}).get("busy_ms")}
    one, two = part(*first), part(*second)
    seen = max(0, one["causes"].get("shader_compile", 0) - two["causes"].get("shader_compile", 0))
    return {"name": name, "first": one, "second": two, "first_seen_hitches": seen,
            "extra_hitches_in_first": max(0, (one["hitches"] or 0) - (two["hitches"] or 0)),
            "hint": "the Metal shader cache is not cleared between the runs: the first run is cold only if the program's "
                    "pipelines were not built before; first_seen_hitches counts the shader_compile hitches the first run has "
                    "and the second does not, extra_hitches_in_first counts those of any cause, and start-up hitches are in both"}


def tool_perf_cold_warm(name, **record):
    """Records the same program twice in a row and says what the first run suffers that the second does not: hitches
    whose cause is a shader compile (first-seen pipelines: the first run's count minus the second's, never below 0), with
    each run's hitch count and graphics compiler time. macOS only. Runs are named `name`-first and `name`-second; each recording takes its seconds plus about a minute to read back."""
    if not name_ok(name):
        raise ToolError("a name holds only letters, digits, '.', '_' and '-'")
    if sys.platform == "win32":
        raise ToolError("perf_cold_warm reads Metal's shader-compile and hitch tables: it runs on macOS only")
    record.pop("label", None)
    runs = []
    for part in ("first", "second"):
        label = f"{name}-{part}"
        before = set(OUT.glob(f"{label}_*.json"))
        tool_perf_record(label, **record)
        path = next(iter(set(OUT.glob(f"{label}_*.json")) - before))
        runs.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
    return cold_warm_report(name, *runs)


def line_fit(points):
    """Returns (intercept, slope, r2) of the least-squares line through [(x, y)], or None when x never changes."""
    mx, my = sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points)
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if not sxx:
        return None
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx
    total = sum((y - my) ** 2 for _, y in points)
    resid = sum((y - my - slope * (x - mx)) ** 2 for x, y in points)
    return my - slope * mx, slope, 1 - resid / total if total else 1.0


def sweep_values(variable, values):
    """Returns the values of a sweep checked and typed (integers for dim), or raises ToolError."""
    env_name = variable[4:] if variable.startswith("env:") else None
    if env_name is None and variable not in ("dim", "example", "api", "size"):
        raise ToolError("variable is dim, example, api, size or env:NAME")
    if env_name is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise ToolError("env:NAME takes a variable name of letters, digits and '_'")
    if not isinstance(values, list) or not 2 <= len(values) <= 8:
        raise ToolError("values is 2 to 8 values")
    if variable == "dim":
        try:
            values = [int(v) for v in values]
        except (TypeError, ValueError) as error:
            raise ToolError("dim values are whole numbers") from error
        if min(values) < 1:
            raise ToolError("dim values are 1 or more")
    elif variable == "size":
        for v in values:
            check_size(v)
    elif any(not re.fullmatch(r"\S+", str(v)) for v in values):
        raise ToolError("a value holds no spaces")
    return values if variable == "dim" else [str(v) for v in values]


def tool_perf_sweep(name, variable, values, rounds=1, skip_s=0, **record):
    """Records the same program once per value of one variable (dim, example, api, size, or env:NAME for an environment
    variable) and returns, per value, the median of FPS, 1 % low, GPU ms per frame and stutter, and with 3 or more
    numeric values the straight line GPU ms per frame follows (fixed ms plus ms per draw for dim, per unit otherwise)
    with its r2. With rounds above 1 the values run in opposite order every other round, so drift hits all alike.
    Runs are named `name`-<value number>-r<round>; each takes its seconds plus about a minute to read back."""
    if not name_ok(name):
        raise ToolError("a name holds only letters, digits, '.', '_' and '-'")
    check_skip(skip_s)
    rounds = int(rounds)
    if not 1 <= rounds <= 5:
        raise ToolError("rounds is 1 to 5")
    values = sweep_values(variable, values)
    if len(values) * rounds > 24:
        raise ToolError("at most 24 recordings: fewer values or rounds")
    record.pop("label", None)
    base_env = check_env(record.pop("env", ""))
    runs = [[] for _ in values]
    for rnd in range(rounds):
        for i in (range(len(values)) if rnd % 2 == 0 else reversed(range(len(values)))):
            kwargs = dict(record)
            if variable.startswith("env:"):
                kwargs["env"] = " ".join(filter(None, [base_env, f"{variable[4:]}={values[i]}"]))
            else:
                kwargs[variable] = values[i]
                if base_env:
                    kwargs["env"] = base_env
            label = f"{name}-{i + 1}-r{rnd + 1}"
            before = set(OUT.glob(f"{label}_*.json"))
            tool_perf_record(label, **kwargs)
            runs[i].append(next(iter(set(OUT.glob(f"{label}_*.json")) - before)).stem)
    rows, frames = [], []
    for value, names in zip(values, runs):
        summaries = [steady_summary(r, skip_s) for r in names]
        frames += [(s.get("gpu") or {}).get("frames", 0) for s in summaries]
        metrics = {}
        for key, (path, _) in AB_METRICS.items():
            found = []
            for item in summaries:
                for step in path:
                    item = item.get(step) if isinstance(item, dict) else None
                if isinstance(item, (int, float)):
                    found.append(item)
            metrics[key] = statistics.median(found) if found else None
        rows.append({"value": value, "runs": names, "metrics": metrics})
    result = {"name": name, "variable": variable, "rows": rows, "fit": None, "too_short": min(frames, default=0) < 100}
    try:
        xs = [v ** 3 if variable == "dim" else float(v) for v in values]
    except ValueError:
        xs = []
    points = [(x, r["metrics"]["frame_gpu_ms_mean"]) for x, r in zip(xs, rows) if r["metrics"]["frame_gpu_ms_mean"] is not None]
    fit = line_fit(points) if len(points) >= 3 else None
    if fit:
        result["fit"] = {"x": "dim^3" if variable == "dim" else variable, "ms_fixed": round(fit[0], 6),
                         "ms_per_unit": round(fit[1], 6), "r2": round(fit[2], 4)}
    if check_skip(skip_s):
        result["skipped_s"] = check_skip(skip_s)
    return result


def ab_report(name, env_a, env_b, runs, skip_s=0):
    """Builds perf_ab's answer from the summaries of its runs, named in `runs` as {"a": [...], "b": [...]}, each
    without its first `skip_s` seconds."""
    summaries = {side: [steady_summary(r, skip_s) for r in names] for side, names in runs.items()}
    metrics = {}
    for key, (path, higher) in AB_METRICS.items():
        values = {}
        for side, items in summaries.items():
            values[side] = []
            for item in items:
                for step in path:
                    item = item.get(step) if isinstance(item, dict) else None
                if isinstance(item, (int, float)):
                    values[side].append(item)
        metrics[key] = {"a": values["a"], "b": values["b"], "verdict": ab_verdict(values["a"], values["b"], higher)}
    frames = [(s.get("gpu") or {}).get("frames", 0) for items in summaries.values() for s in items]
    result = {"name": name, "env_a": env_a, "env_b": env_b, "runs": runs, "metrics": metrics,
              "too_short": min(frames, default=0) < 100}
    if check_skip(skip_s):
        result["skipped_s"] = check_skip(skip_s)
    return result


def tool_capture_summary(capture):
    """Reads a Metal .gputrace capture without Xcode: command buffers, encoders, draws, debug groups, and the 100
    most frequent call ids out of calls_total."""
    summary = gputrace_read.summarize(allowed(capture))
    summary["calls_total"] = len(summary["calls"])
    summary["calls"] = summary["calls"][:100]
    return summary


def tool_capture_records(capture, offset=0, limit=100):
    """Returns one page of the records of a .gputrace command stream, with their Metal call names when known."""
    out = [{"offset": off, "size": size, "id": call, "signature": signature,
            "name": gputrace_read.CALLS.get(call, (None,))[0], "strings": strings[:3]}
           for off, size, call, signature, strings in gputrace_read.records(allowed(capture) / "capture")]
    return page(out, offset, limit)


def family_of(name):
    """Returns the Metal family key for a family ("apple7") or chip name ("M1 Pro", "A15"), or None."""
    wanted = name.strip().lower().replace(" ", "")
    for key, family in FAMILIES["families"].items():
        chips = [c.lower().replace(" ", "").removesuffix("series") for c in family["mac_chips"] + family["other_chips"]]
        base = wanted.removesuffix("ultra").removesuffix("max").removesuffix("pro")
        if wanted == key.lower() or wanted in chips or base in chips:
            return key
    return None


def tool_gpu_family(name):
    """Apple's published facts for one GPU family, by family ("Apple7") or chip ("M1 Pro"): its chips, what it adds,
    its limits, plus the limits shared by all families and the footnotes. Source URLs are in the result."""
    key = family_of(name)
    if key is None:
        raise ToolError(f"unknown family or chip {name!r}; try one of {', '.join(FAMILIES['families'])} or a chip "
                        "such as M1 Pro, M2, M3 Max, A17 Pro")
    return {"family": key, **FAMILIES["families"][key], "same_on_all": FAMILIES["same_on_all"],
            "footnotes": FAMILIES["footnotes"], "guards": FAMILIES["guards"], "sources": FAMILIES["sources"]}


RESOURCES = {"metal-trace://gpu-families": ("Apple GPU families", FAMILIES["about"], lambda: FAMILIES)} | {
    f"metal-trace://gpu-families/{key.lower()}": (f"{key} GPU family", f"Apple's published facts for {key}",
                                                  lambda key=key: tool_gpu_family(key))
    for key in FAMILIES["families"]}

S, I = {"type": "string"}, {"type": "integer"}
PAGE = {"offset": {**I, "description": "first row, default 0"},
        "limit": {**I, "description": f"rows per page, default 50, at most {MAX_LIMIT}"}}
TRACE = {**S, "description": "a run name from perf_runs whose trace_kept is true, or the path of a .trace"}
CAPTURE = {**S, "description": "path of a .gputrace bundle saved from Xcode, inside METAL_TRACE_OUT or METAL_TRACE_READ"}


def schema(properties, required=()):
    """Returns a JSON Schema object with these properties."""
    return {"type": "object", "properties": properties, "required": list(required)}


def hints(title, destructive=None, idempotent=False, open_world=False):
    """Returns a tool's MCP annotations: read-only unless `destructive` says whether its writes stop programs."""
    if destructive is None:
        return {"title": title, "readOnlyHint": True, "openWorldHint": open_world}
    return {"title": title, "readOnlyHint": False, "destructiveHint": destructive, "idempotentHint": idempotent,
            "openWorldHint": open_world}


RECORD_PROPS = {"label": {**S, "description": "name for the run: letters, digits, '.', '_', '-'"},
         "program": {**S, "description": "path of the .exe, or of the macOS binary with wine=native"},
         "seconds": {**I, "description": "recording length, default 20; use 30 under Wine, whose start-up takes part of it; the export afterwards takes several minutes under Wine"},
         "wine": {**S, "description": "Wine directory holding bin/wine, or native"},
         "prefix": {**S, "description": "Wine prefix, default WINEPREFIX or ~/.wine; ignored with native"},
         "workdir": {**S, "description": "directory the program starts in, default the program's own"},
         "args": {**S, "description": "program arguments as in a shell, quotes included"},
         "workload": {**S, "description": "a test program from workload_list, fetched with workload_fetch, instead "
                                          "of program"},
         "api": {**S, "description": "with workload: mtl (native Metal), mtl-x64 (Metal built for x86_64, run under Rosetta like Wine), vk (Vulkan through MoltenVK: set "
                                                        "METAL_TRACE_MOLTENVK), d3d11 or d3d12 (under wine)"},
         "dim": {**I, "description": "with workload drawstress: side of the cube grid, dim^3 draws per frame"},
         "example": {**S, "description": "with a workload that lists examples in workload_list: the one to run"},
         "size": {**S, "description": "with a workload that has size_variables (drawstress): the window size, WIDTHxHEIGHT such as 1920x1080"},
         "memory": {"type": "boolean", "description": "default true; false skips the Metal memory table, the slowest "
                                                      "to read (about 40 % faster summary): no metal_mib_peak"},
         "env": {**S, "description": "NAME=VALUE pairs separated by spaces, set in the program's environment; MTL_SHADER_VALIDATION=1 or MTL_DEBUG_LAYER=1 adds `validation` to the summary: the layers' messages counted by kind"},
         "memory_free_pct": {**I, "description": "macOS only, 20 to 60: holds the whole Mac at this percentage of RAM free "
                                                 "while recording (memory_pressure), to see how the program behaves short of memory; lower can freeze the Mac"},
         "background": {"type": "boolean", "description": "macOS only, default false; true runs the program under taskpolicy -b, "
                                                        "which throttles it hard and unevenly (drawstress: 18 to 280 times slower): repeat the run"},
         "counters": {"type": "boolean", "description": "default false; true also records Metal GPU Counters (gpu_counters in "
                                                        "the summary); not under Windows; adds about 40 s of read-back per recorded second"}}

SKIP = ("seconds to leave out at the start of each recording, where shaders compile and resources load; 0 (default) "
        "keeps all. The GPU numbers, hitches and Metal memory are recomputed without them")

TOOLS = {
    "perf_record": (tool_perf_record, schema(RECORD_PROPS, ["label"]), hints("Record a program", destructive=True)),
    "perf_baseline_record": (tool_perf_baseline_record, schema(
        {"name": {**S, "description": "reference name: letters, digits, '.', '_', '-'"},
         "count": {**I, "description": "equal recordings to make, default 3"},
         "skip_s": {"type": "number", "description": SKIP + "; perf_check applies the same cut to the run it judges"},
         **{k: v for k, v in RECORD_PROPS.items() if k != "label"}}, ["name"]),
        hints("Record a reference", destructive=True)),
    "perf_sweep": (tool_perf_sweep, schema(
        {"name": {**S, "description": "name for the runs: letters, digits, '.', '_', '-'"},
         "variable": {**S, "description": "what changes between runs: dim, example, api, size, or env:NAME for an environment variable"},
         "values": {"type": "array", "items": {"type": ["string", "integer"]},
                    "description": "2 to 8 values of the variable, such as [10, 20, 30] for dim"},
         "rounds": {**I, "description": "rounds, default 1, at most 5 and at most 24 recordings in all; every other round runs the values in reverse"},
         "skip_s": {"type": "number", "description": SKIP},
         **{k: v for k, v in RECORD_PROPS.items() if k != "label"}}, ["name", "variable", "values"]),
        hints("Record one run per value of a variable", destructive=True)),
    "perf_ab": (tool_perf_ab, schema(
        {"name": {**S, "description": "name for the runs: letters, digits, '.', '_', '-'"},
         "env_a": {**S, "description": "NAME=VALUE pairs for side A, the reference (empty: none)"},
         "env_b": {**S, "description": "NAME=VALUE pairs for side B, the change under test (empty: none)"},
         "rounds": {**I, "description": "A B B A rounds, default 1 (4 recordings), at most 5"},
         "skip_s": {"type": "number", "description": SKIP},
         **{k: v for k, v in RECORD_PROPS.items() if k not in ("label", "env")}}, ["name", "env_a", "env_b"]),
        hints("Record two settings in A B B A order", destructive=True)),
    "perf_cold_warm": (tool_perf_cold_warm, schema(
        {"name": {**S, "description": "name for the runs: letters, digits, '.', '_', '-'"},
         **{k: v for k, v in RECORD_PROPS.items() if k != "label"}}, ["name"]),
        hints("Record a run twice to find first-seen shader stutter", destructive=True)),
    "perf_attach": (tool_perf_attach, schema(
        {"label": {**S, "description": "name for the run: letters, digits, '.', '_', '-'"},
         "process": {**S, "description": "pid, or a name in the program's command line such as Game.exe"},
         "seconds": {**I, "description": "recording length, default 20; the export afterwards takes several minutes under Wine"}},
        ["label", "process"]), hints("Record a running program", destructive=False)),
    "perf_runs": (tool_perf_runs, schema(PAGE), hints("List recordings")),
    "perf_compare": (tool_perf_compare, schema(
        {"a": {**S, "description": "run name from perf_runs: the reference, such as the run before a change"},
         "b": {**S, "description": "run name from perf_runs: the run to compare against a"},
         "short_us": {**I, "description": "an encoder under this GPU time counts as short: 10, 25 (default), 50, 100, "
                                          "250, 500 or 1000"},
         "markdown": {"type": "boolean", "description": "also return the numbers as Markdown tables, default false"},
         "skip_s": {"type": "number", "description": SKIP}},
        ["a", "b"]),
        hints("Compare two recordings")),
    "perf_baseline": (tool_perf_baseline, schema(
        {"name": {**S, "description": "reference name: letters, digits, '.', '_', '-'; alone, shows that reference"},
         "runs": {"type": "array", "items": S, "description": "run names from perf_runs to save as this reference, "
                                                             "ideally 3 or more equal runs; replaces a previous one"},
         "skip_s": {"type": "number", "description": SKIP + "; perf_check applies the same cut to the run it judges"}}),
        hints("Name a reference", destructive=False, idempotent=True)),
    "perf_check": (tool_perf_check, schema(
        {"run": {**S, "description": "a run name from perf_runs"},
         "baseline": {**S, "description": "a reference name from perf_baseline"},
         "margin_pct": {"type": "number", "description": "how far outside the reference's range FPS or GPU ms per "
                                                         "frame may fall before counting, default 3"}},
        ["run", "baseline"]), hints("Check a run against a reference")),
    "perf_export_trace": (tool_perf_export_trace, schema(
        {"run": {**S, "description": "a run name from perf_runs"}}, ["run"]),
        hints("Export frames to Perfetto", destructive=False, idempotent=True)),
    "perf_gate": (tool_perf_gate, schema(
        {"run": {**S, "description": "a run name from perf_runs"},
         "fps_min": {"type": "number", "description": "the FPS must be at least this"},
         "fps_1pct_low_min": {"type": "number", "description": "the 1% low FPS must be at least this"},
         "stutter_rate_pct_max": {"type": "number", "description": "the share of stutter frames, in %, at most this"},
         "gpu_ms_p95_max": {"type": "number", "description": "the p95 GPU ms per frame at most this"},
         "hitches_max": {"type": "number", "description": "the number of hitches at most this"},
         "metal_mib_max": {"type": "number", "description": "the peak Metal memory in MiB at most this"},
         "skip_s": {"type": "number", "description": SKIP}}, ["run"]),
        hints("Check a run against budgets")),
    "perf_history": (tool_perf_history, schema(
        {"prefix": {**S, "description": "the start of the run names to follow: letters, digits, '.', '_', '-'"},
         "limit": {**I, "description": "newest runs to keep, default 50"},
         "skip_s": {"type": "number", "description": SKIP}}, ["prefix"]),
        hints("Follow a number across runs")),
    "perf_panel": (tool_perf_panel, schema(
        {"name": {**S, "description": "name for the panel file: letters, digits, '.', '_', '-'"},
         "runs": {"type": "array", "items": S, "description": "one or two run names from perf_runs; with two, the first "
                                                             "is A, the reference"},
         "preset": {**S, "description": "fps (default) or compare (needs two runs)"},
         "skip_s": {"type": "number", "description": SKIP},
         "layout": {"type": "array", "items": S, "description": "tabs to show, in order: summary, ab, frames, encoders, counters, memory, data; "
                                                                "saved as panel.json in the runs directory as the default for every panel"}},
        ["name", "runs"]),
        hints("Write an HTML panel", destructive=False, idempotent=True)),
    "perf_diagnose": (tool_perf_diagnose, schema(
        {"run": {**S, "description": "a run name from perf_runs"},
         "min_encoders": {**I, "description": "encoders per frame (median) from which the verdict can be yes, default 4"},
         "short_us": {**I, "description": "an encoder under this GPU time counts as short: 10, 25 (default), 50, 100, "
                                          "250, 500 or 1000"},
         "short_share": {"type": "number", "description": "share of short encoders from which the verdict is yes, "
                                                          "default 0.25"}}, ["run"]),
        hints("Diagnose encoder use")),
    "trace_tables": (tool_trace_tables, schema({"trace": TRACE}, ["trace"]), hints("List a trace's tables")),
    "trace_count": (tool_trace_count, schema(
        {"trace": TRACE,
         "tables": {"type": "array", "items": S, "description": "table names from trace_tables; default the tables "
                                                                 "that matter for a translation layer"}}, ["trace"]),
                    hints("Count a trace's rows")),
    "trace_query": (tool_trace_query, schema(
        {"trace": TRACE, "schema": {**S, "description": "a table name that trace_tables lists, such as metal-gpu-intervals"},
         "pid": {**I, "description": "keep only this process's rows"}, **PAGE}, ["trace", "schema"]),
                    hints("Read a trace table")),
    "capture_summary": (tool_capture_summary, schema({"capture": CAPTURE}, ["capture"]), hints("Summarize a capture")),
    "capture_records": (tool_capture_records, schema({"capture": CAPTURE, **PAGE}, ["capture"]),
                        hints("Read a capture's records")),
    "gpu_family": (tool_gpu_family, schema(
        {"name": {**S, "description": "a family (Apple7 to Apple10) or a chip (M1 Pro, M2, M4 Max, A17 Pro)"}},
        ["name"]), hints("Apple GPU family facts")),
    "workload_list": (tool_workload_list, schema({}), hints("List test programs")),
    "workload_fetch": (tool_workload_fetch, schema(
        {"name": {**S, "description": "a workload name from workload_list, such as drawstress"}}, ["name"]),
        hints("Download a test program", destructive=False, idempotent=True, open_world=True)),
    "presentmon_install": (tool_presentmon_install, schema({}),
                           hints("Install PresentMon (Windows)", destructive=False, idempotent=True, open_world=True)),
}
# Claude Code asks the user before every call of these tools
META = {"workload_fetch": {"anthropic/requiresUserInteraction": True},
        "presentmon_install": {"anthropic/requiresUserInteraction": True}}

PROMPTS = {
    "compare-layer": {
        "description": "Records a test program in native Metal and under a translation layer, then diagnoses and "
                       "compares both runs",
        "arguments": [{"name": "workload", "description": "a workload from workload_list, default drawstress"},
                      {"name": "api", "description": "the API run under Wine: d3d12 (default) or d3d11"}],
    },
}


def prompt_compare_layer(workload="drawstress", api="d3d12"):
    """Returns the steps of the compare-layer prompt for `workload` and `api`."""
    return (
        f"Compare {workload} in native Metal with {workload} through {api} under the Wine in METAL_TRACE_WINE, with "
        "the metal-trace tools:\n"
        f"1. workload_fetch name={workload} (it is skipped when already downloaded).\n"
        f"2. perf_record label={workload}-mtl workload={workload} api=mtl seconds=20.\n"
        f"3. perf_record label={workload}-{api} workload={workload} api={api} seconds=30.\n"
        "4. perf_compare a=<the mtl run> b=<the other run>, and perf_diagnose on the other run for its verdict.\n"
        "Report perf_compare's metrics and encoders as one table (a, b, change), then its labels with the largest "
        "change in GPU ms per frame, then the verdict. Say which runs are in too_short, and that one pair of runs is "
        "not enough to call a difference real: repeat both before concluding."
    )


CALLS = {}  # request id -> cancel event, for the tool calls in flight
OUT_LOCK = threading.Lock()
QUEUE, WAKE, WORKER = collections.deque(), threading.Condition(), []  # tool calls waiting for the one worker thread
MAX_QUEUE = 64


def error_result(request_id, text):
    """Returns a tools/call reply that failed with `text`."""
    return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}], "isError": True}}


def submit(message, reply):
    """Queues a tools/call for the worker thread, which runs calls one at a time; `reply` receives its JSON-RPC reply.
    A queue of MAX_QUEUE calls is answered at once with an error instead of growing without limit."""
    with WAKE:
        full = len(QUEUE) >= MAX_QUEUE
        if not full:
            QUEUE.append((message, reply))
            if not WORKER:
                WORKER.append(threading.Thread(target=work, daemon=True))
                WORKER[0].start()
            WAKE.notify()
    if full:
        CALLS.pop(message["id"], None)
        reply(error_result(message["id"], f"{MAX_QUEUE} calls are already waiting; try again when one finishes"))


def work():
    """Runs the queued tool calls in order until it takes the None that stop_worker queues."""
    while True:
        with WAKE:
            while not QUEUE:
                WAKE.wait()
            item = QUEUE.popleft()
        if item is None:
            return
        reply = item[1]
        reply(answer(item[0]))


def stop_worker():
    """Lets the queued tool calls finish, then ends the worker thread."""
    with WAKE:
        if not WORKER:
            return
        QUEUE.append(None)
        WAKE.notify()
    WORKER[0].join()


def cancel_call(request_id):
    """Cancels the tool call `request_id`: one still queued is answered at once, a running one is told to stop."""
    try:
        hash(request_id)
    except TypeError:
        return
    with WAKE:
        queued = next((item for item in QUEUE if item and item[0].get("id") == request_id), None)
        if queued:
            QUEUE.remove(queued)
    if queued:
        CALLS.pop(request_id, None)
        queued[1](error_result(request_id, "the call was cancelled before it started"))
    elif request_id in CALLS:
        CALLS[request_id].set()


def send(message):
    """Writes one JSON-RPC message to stdout; the lock keeps lines from different threads whole."""
    with OUT_LOCK:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def log(message):
    """Writes one line to stderr, the only log channel a stdio server may use."""
    if os.environ.get("METAL_TRACE_LOG") != "off":
        print(f"metal-trace: {message}", file=sys.stderr, flush=True)


def call(name, arguments, request_id=None, token=None):
    """Runs one tool and returns its MCP result, with failures as isError results that say what to do. A client's
    notifications/cancelled for `request_id` stops it; `token` is the client's progressToken, if it sent one."""
    started = time.monotonic()
    RUN.cancel = CALLS.setdefault(request_id, threading.Event()) if request_id is not None else None
    RUN.progress = None if token is None else lambda done, total, message: send(
        {"jsonrpc": "2.0", "method": "notifications/progress",
         "params": {"progressToken": token, "progress": done, "total": total, "message": message}})
    try:
        if cancelled():
            raise ToolError("the call was cancelled before it started")
        value = TOOLS[name][0](**arguments)
        if not isinstance(value, dict):
            raise RuntimeError(f"{name} returned {type(value).__name__}, not an object")
        text = json.dumps(value, ensure_ascii=False)
        if len(text) > MAX_TEXT:
            raise ToolError(f"the result has {len(text)} characters; ask for a smaller page with limit")
        result = {"content": [{"type": "text", "text": text}], "structuredContent": value}
    except TypeError as error:
        result = {"content": [{"type": "text", "text": f"bad arguments: {error}"}], "isError": True}
    except (ToolError, FileNotFoundError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
    except Exception as error:  # an unexpected failure is reported to the client, not fatal to the server
        result = {"content": [{"type": "text", "text": f"internal error: {type(error).__name__}"}], "isError": True}
    CALLS.pop(request_id, None)
    log(f"{name} {'error' if result.get('isError') else 'ok'} in {time.monotonic() - started:.1f} s")
    return result


def handle(message):
    """Answers one JSON-RPC request; returns None for notifications."""
    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    method, mid, params = message.get("method"), message.get("id"), message.get("params") or {}
    if mid is None:
        return None
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32600, "message": "params must be an object"}}
    if method == "initialize":
        asked = params.get("protocolVersion")
        result = {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                  "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                  "serverInfo": {"name": "metal-trace", "version": __version__}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "resources/templates/list":
        result = {"resourceTemplates": [{"uriTemplate": "metal-trace://runs/{run}", "name": "Run summary",
                                         "description": "The saved summary of a recording named as perf_runs lists it",
                                         "mimeType": "application/json"}]}
    elif method == "resources/list":
        result = {"resources": [{"uri": uri, "name": name, "description": about, "mimeType": "application/json"}
                                for uri, (name, about, _) in RESOURCES.items()]}
    elif method == "resources/read":
        uri = params.get("uri")
        if isinstance(uri, str) and uri.startswith("metal-trace://runs/"):
            try:
                text = run_path(uri[len("metal-trace://runs/"):]).read_text(encoding="utf-8")
            except ToolError:
                text = None
            if text is None:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32002, "message": "Resource not found",
                                                               "data": {"uri": uri}}}
            return {"jsonrpc": "2.0", "id": mid, "result": {"contents": [{"uri": uri, "mimeType": "application/json",
                                                                         "text": text}]}}
        if uri not in RESOURCES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32002, "message": "Resource not found",
                                                           "data": {"uri": uri}}}
        result = {"contents": [{"uri": uri, "mimeType": "application/json",
                                "text": json.dumps(RESOURCES[uri][2](), ensure_ascii=False)}]}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": f.__doc__.strip(), "inputSchema": s,
                             "outputSchema": PAGED if n in PAGED_TOOLS else OBJECT, "annotations": hints}
                            | ({"_meta": META[n]} if n in META else {}) for n, (f, s, hints) in TOOLS.items()]}
    elif method == "prompts/list":
        result = {"prompts": [{"name": name, **p} for name, p in PROMPTS.items()]}
    elif method == "prompts/get":
        if params.get("name") not in PROMPTS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown prompt"}}
        arguments = {k: v for k, v in (params.get("arguments") or {}).items() if v and name_ok(str(v))}
        try:
            text = prompt_compare_layer(**arguments)
        except TypeError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown prompt argument"}}
        result = {"description": PROMPTS["compare-layer"]["description"],
                  "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    elif method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        result = call(name, params.get("arguments") or {}, mid if isinstance(mid, (str, int)) else None,
                      (params.get("_meta") or {}).get("progressToken"))
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def check_cli(args):
    """Runs `check RUN BASELINE [--margin-pct N]` for CI: prints perf_check's verdict, reasons and hints as one JSON
    line and returns 0 when the run is the same or improved, 1 when it regressed, 2 when it could not be judged
    (no such run or reference), or too short to judge (under 100 frames)."""
    run, baseline, margin = (args + [None, None])[:2] + [3.0]
    if "--margin-pct" in args:
        try:
            margin = float(args[args.index("--margin-pct") + 1])
        except (IndexError, ValueError):
            print("usage: metal-gpu-trace check RUN BASELINE [--margin-pct N]", file=sys.stderr)
            return 2
    if not run or not baseline or run.startswith("--") or baseline.startswith("--"):
        print("usage: metal-gpu-trace check RUN BASELINE [--margin-pct N]", file=sys.stderr)
        return 2
    try:
        result = tool_perf_check(run, baseline, margin)
    except (ToolError, FileNotFoundError, ValueError) as error:
        print(f"metal-gpu-trace: {error}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in result.items() if k not in ("comparison", "range")}))
    if "hint" in result:
        return 2
    return 1 if result["verdict"] == "regressed" else 0


def main():
    """Serves newline-delimited JSON-RPC on stdin and stdout until stdin closes; --version prints the version, and
    `check` judges a run for CI (see check_cli)."""
    if sys.argv[1:] == ["--version"]:
        print(f"metal-gpu-trace {__version__}")
        return
    if sys.argv[1:2] == ["check"]:
        sys.exit(check_cli(sys.argv[2:]))
    if sys.argv[1:2] == ["--http"]:
        try:
            port = int(sys.argv[3]) if sys.argv[2:3] == ["--port"] else 8765
        except (IndexError, ValueError):
            print("usage: metal-gpu-trace --http [--port N]", file=sys.stderr)
            sys.exit(2)
        sys.exit(serve_http(port))
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if isinstance(message, dict) and message.get("method") == "notifications/cancelled":
                cancel_call(request_id_of(message))
                continue
            if isinstance(message, dict) and message.get("method") == "tools/call" and \
                    isinstance(message.get("id"), (str, int)):
                # a tool call runs on the worker thread so ping and notifications/cancelled are read meanwhile; calls
                # still run one at a time, as only one recording may run at once
                CALLS[message["id"]] = threading.Event()
                submit(message, send)
                continue
            reply = handle(message)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        except Exception as error:  # a malformed request must not stop the server
            log(f"internal error {type(error).__name__}")
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "internal error"}}
        if reply is not None:
            send(reply)
    stop_worker()


def request_id_of(message):
    """Returns the requestId of a notifications/cancelled message, or None when its params are not an object."""
    params = message.get("params")
    return params.get("requestId") if isinstance(params, dict) else None


def answer(message):
    """Returns the reply to one tools/call."""
    try:
        return handle(message)
    except Exception as error:  # a malformed request must not stop the server
        log(f"internal error {type(error).__name__}")
        CALLS.pop(message.get("id"), None)
        return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": "internal error"}}


MIN_TOKEN = 16
MAX_BODY = 1_000_000
HTTP_TIMEOUT = 15  # seconds a client may take to send its request


def local_host(value):
    """Returns whether a Host or Origin header names this machine's loopback: localhost or 127.0.0.1, with any port."""
    host = (value or "").split("://", 1)[-1].split("/", 1)[0]
    return host.partition(":")[0] in ("localhost", "127.0.0.1")


def http_handler(token):
    """Returns the request handler class of the Streamable HTTP endpoint POST /mcp: one JSON-RPC message in, one JSON
    reply out (202 for a notification). A request needs the bearer `token`, a loopback Host and no foreign Origin,
    which also stops a web page from reaching the server through DNS rebinding. GET /panel serves the panel page
    (no data) and GET /panel/data?runs=a,b&preset=fps its data, with the same checks; without runs it is the newest."""
    import hmac
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        timeout = HTTP_TIMEOUT  # a client that stalls mid-request is dropped, not kept as a thread forever

        def reply(self, code, body=None, kind="application/json"):
            data = b"" if body is None else body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def foreign(self):
            """Returns whether the request names a Host or an Origin that is not this machine."""
            return not local_host(self.headers.get("Host")) or bool(self.headers.get("Origin") and
                                                                   not local_host(self.headers.get("Origin")))

        def unauthorized(self):
            """Returns whether the request lacks the bearer token."""
            given = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
            return not hmac.compare_digest(given.encode(), token.encode())

        def do_POST(self):
            if self.path != "/mcp":
                return self.reply(404)
            if self.foreign():
                return self.reply(403)
            if self.unauthorized():
                return self.reply(401)
            length = int(self.headers.get("Content-Length") or 0) if (self.headers.get("Content-Length") or "0").isdigit() else -1
            if not 0 <= length <= MAX_BODY:
                return self.reply(413)
            try:
                message = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            if isinstance(message, dict) and message.get("method") == "notifications/cancelled":
                cancel_call(request_id_of(message))
                return self.reply(202)
            if isinstance(message, dict) and message.get("method") == "tools/call" and \
                    isinstance(message.get("id"), (str, int)):
                # progress goes out as notifications, which this endpoint does not stream: no progressToken
                if isinstance(message.get("params"), dict):
                    message["params"].pop("_meta", None)
                CALLS[message["id"]] = threading.Event()
                done, box = threading.Event(), []
                submit(message, lambda reply: (box.append(reply), done.set()))
                done.wait()
                return self.reply(200, box[0])
            try:
                reply = handle(message)
            except Exception as error:  # a malformed request must not stop the server
                log(f"internal error {type(error).__name__}")
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "internal error"}}
            self.reply(202 if reply is None else 200, reply)

        def do_GET(self):
            from urllib.parse import parse_qs, urlsplit
            url = urlsplit(self.path)
            if url.path not in ("/panel", "/panel/data"):
                return self.reply(405)
            if self.foreign():
                return self.reply(403)
            if url.path == "/panel":
                # the page holds no data and reads the token from the URL fragment, which never reaches the server
                page_html = (TOOLS_DIR / "data" / "panel.html").read_text(encoding="utf-8")
                return self.reply(200, page_html.replace("default-src 'none'", "default-src 'none'; connect-src 'self'"),
                                  "text/html; charset=utf-8")
            if self.unauthorized():
                return self.reply(401)
            query = parse_qs(url.query)
            runs = [r for r in (query.get("runs") or [""])[0].split(",") if r]
            skip = (query.get("skip_s") or [0])[0]
            try:
                if not runs:
                    runs = [tool_perf_runs(0, 1)["rows"][0]["run"]]
                self.reply(200, panel_data(runs, (query.get("preset") or [None])[0], skip))
            except (ToolError, IndexError) as error:
                self.reply(400, {"error": str(error) if isinstance(error, ToolError) else "no recordings yet"})
            except Exception as error:  # a damaged summary must not stop the server
                log(f"internal error {type(error).__name__}")
                self.reply(500, {"error": "internal error"})

        def log_message(self, *args):
            pass

    return Handler


def serve_http(port):
    """Serves the MCP endpoint over HTTP on 127.0.0.1 only, until interrupted. METAL_TRACE_TOKEN (at least MIN_TOKEN
    characters) is the bearer token every request must carry; without it the server refuses to start."""
    from http.server import ThreadingHTTPServer
    token = os.environ.get("METAL_TRACE_TOKEN", "")
    if len(token) < MIN_TOKEN:
        print(f"metal-gpu-trace: set METAL_TRACE_TOKEN to a secret of at least {MIN_TOKEN} characters", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", port), http_handler(token))
    log(f"serving http://127.0.0.1:{server.server_address[1]}/mcp")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    main()
