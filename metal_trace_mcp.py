"""MCP server (stdio, JSON-RPC 2.0, standard library only) that records Wine or macOS programs with Instruments'
Metal System Trace and reads the recordings and Metal .gputrace captures.

Environment: METAL_TRACE_OUT is where recordings go (default ./perf-runs); METAL_TRACE_READ lists more directories,
separated by ':', whose files the tools may read; METAL_TRACE_WINE is the default Wine directory; KEEP_RUNS caps the
recordings kept; METAL_TRACE_LOG=off silences the one stderr line per call. Test programs that workload_fetch
downloads go to ~/Library/Caches/metal-gpu-trace.
"""
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time

__version__ = "0.7.0"
TOOLS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
import gputrace_read  # noqa: E402
import perf_report  # noqa: E402

OUT = pathlib.Path(os.environ.get("METAL_TRACE_OUT", "perf-runs")).resolve()
READ = [OUT] + [pathlib.Path(p).resolve() for p in os.environ.get("METAL_TRACE_READ", "").split(":") if p]
FAMILIES = json.loads((TOOLS_DIR / "data" / "apple-gpu-families.json").read_text())
WORKLOADS = json.loads((TOOLS_DIR / "data" / "workloads.json").read_text())["workloads"]
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
    "the Mac while it records. Under Wine record 30 s or more: Wine's start-up takes part of the recording. Reading a "
    "recording back takes 1 to 9 s per recorded second. Compare only recordings with 100 frames or more, and repeat "
    "a run before calling a change real. perf_baseline (or perf_baseline_record, which records them) saves several equal runs as a named reference and perf_check says whether a new run regressed against their range. perf_diagnose says whether a run splits its GPU work into too many short "
    "encoders, as translation layers do; perf_compare says how much two runs differ. trace_tables and trace_query "
    "need the .trace, kept only with KEEP_TRACE=1. When perf_record ends it stops every program of its Wine prefix, "
    "or every process named like a native program. To compare native Metal with a translation layer without a game "
    "of one's own: workload_list, workload_fetch, then perf_record with workload and api, or the compare-layer prompt."
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


def page(items, offset, limit):
    """Returns one page of `items` with the total and the offset of the next page (None at the end)."""
    offset, limit = max(0, int(offset)), min(max(1, int(limit)), MAX_LIMIT)
    rows = items[offset:offset + limit]
    more = offset + len(rows) < len(items)
    return {"total": len(items), "offset": offset, "rows": rows, "next_offset": offset + len(rows) if more else None}


def tool_perf_record(label, program=None, seconds=20, wine=None, prefix=None, workdir=None, args="", workload=None,
                     api=None, dim=None):
    """Records `program` (an .exe under Wine, or a macOS binary with wine="native"), or a test program fetched with
    workload_fetch (workload, api, dim), for `seconds` with Metal System Trace and returns its summary: GPU ms per
    frame, frame intervals, FPS, Metal and resident memory. When it ends it stops every program of that Wine prefix
    (wineserver -k), or every process named like the program with native."""
    program_env = ""
    if workload:
        program, wine, args, program_env = workload_command(workload, api, dim, wine, args)
    if not program:
        raise ToolError("pass program, or workload and api (workload_list lists them)")
    wine = wine or os.environ.get("METAL_TRACE_WINE")
    if not wine:
        raise ToolError("pass wine (a Wine directory holding bin/wine, or native) or set METAL_TRACE_WINE")
    program = pathlib.Path(program).expanduser()
    if not program.exists():
        raise ToolError(f"no program at {program.name}")
    workdir = pathlib.Path(workdir).expanduser() if workdir else program.parent
    prefix = pathlib.Path(prefix or os.environ.get("WINEPREFIX", "~/.wine")).expanduser()
    return record(label, seconds, wine, prefix, workdir, [str(program.resolve()), *shlex.split(args)], program_env)


def workload_entry(name):
    """Returns a test program's entry in data/workloads.json and the directory it is fetched into."""
    if name not in WORKLOADS:
        raise ToolError(f"no workload {name!r}; workload_list lists them")
    entry = WORKLOADS[name]
    return entry, CACHE / f"{name}-{entry['sha256'][:12]}"


def workload_command(name, api, dim, wine, args):
    """Returns the program, Wine, arguments and program environment that run a fetched workload with `api`."""
    entry, target = workload_entry(name)
    if api not in entry["apis"]:
        raise ToolError(f"api is one of {', '.join(entry['apis'])} for {name}")
    if not target.is_dir():
        raise ToolError(f"{name} is not downloaded yet; call workload_fetch first")
    run = entry["apis"][api]
    program_env = f"{entry['dim_variable']}={int(dim)}" if dim else ""
    return (target / entry["dir"] / run["program"], wine if run["wine"] else "native",
            " ".join(filter(None, [run["args"], args])), program_env)


def tool_workload_list():
    """Lists the test programs workload_fetch can download, such as bgfx's drawstress: what each measures, its size,
    license and APIs, and whether it is already downloaded."""
    rows = []
    for name, entry in WORKLOADS.items():
        rows.append({"name": name, "title": entry["title"], "about": entry["about"], "bytes": entry["bytes"],
                     "license": entry["license"], "apis": list(entry["apis"]),
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


def tool_workload_fetch(name):
    """Downloads a test program from this project's GitHub releases once, checks its SHA-256 against the one this
    package pins, and keeps it in ~/Library/Caches/metal-gpu-trace; later calls reuse it. The programs are built
    from source by the project's workloads workflow."""
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
        (pathlib.Path(tmp) / "out").rename(target)
    return {"name": name, "downloaded": True, "fetched": True, "bytes": entry["bytes"], "apis": list(entry["apis"])}


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


def deadline(seconds):
    """Returns the seconds a recording of `seconds` may take in all; reading it back takes about 9 s per second."""
    return int(seconds) * 10 + 120


def record(label, seconds, wine, prefix, workdir, command, program_env=""):
    """Runs perf_record.sh and returns the summary it wrote, stopping the whole recording and deleting its files if
    it overruns; `program_env` adds NAME=VALUE pairs to PERF_ENV."""
    if not name_ok(label):
        raise ToolError("label holds only letters, digits, '.', '_' and '-'")
    env = dict(os.environ, PERF_OUT=str(OUT),
               PERF_ENV=" ".join(filter(None, [os.environ.get("PERF_ENV", ""), program_env])))
    layer = layer_of(wine, prefix, env["PERF_ENV"])
    before = set(OUT.glob(f"{label}_*"))
    proc = subprocess.Popen(["zsh", str(TOOLS_DIR / "perf_record.sh"), label, str(int(seconds)), str(wine),
                             str(prefix), str(workdir), *command],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                            start_new_session=True)
    try:
        _, stderr = proc.communicate(timeout=deadline(seconds))
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        if wine not in ("native", "attach"):
            subprocess.run([str(pathlib.Path(wine) / "bin" / "wineserver"), "-k"], env=dict(env, WINEPREFIX=str(prefix)),
                           capture_output=True, timeout=30)
        if (OUT / ".recording").is_dir():
            (OUT / ".recording").rmdir()
        # the partial .trace and CSVs of this run
        for path in set(OUT.glob(f"{label}_*")) - before:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        raise ToolError(f"the recording took over {deadline(seconds)} s and was stopped; nothing was saved")
    new = sorted(set(OUT.glob(f"{label}_*.json")) - before)
    if proc.returncode or not new:
        reason = (stderr.strip().splitlines() or ["no summary was written"])[-1]
        raise ToolError(f"recording failed (exit {proc.returncode}): {reason}")
    summary = json.loads(new[-1].read_text())
    summary["layer"] = layer
    new[-1].write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    return summary


def tool_perf_runs(offset=0, limit=50):
    """Lists the saved recordings, newest first, with frames, FPS, GPU ms per frame, memory peaks and the translation
    layer each ran on (fingerprint and Wine, or native)."""
    runs = []
    for path in sorted(OUT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name == BASELINES.name:
            continue
        try:
            s = json.loads(path.read_text())
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


def tool_perf_compare(a, b, short_us=25):
    """Compares two saved recordings (names from perf_runs), a the reference and b the run after a change: the
    headline numbers (FPS, GPU ms, frame pacing, memory), then what changed in the GPU work and where: encoders and
    command buffers per frame, the share of encoders under short_us, the GPU's idle time, and each encoder label's
    count and GPU ms per frame, largest change first. layer says whether both ran on the same translation layer:
    with different layers it compares layers, not one change. Recordings with under 100 frames are flagged: too
    short to compare."""
    sa, sb = (json.loads(run_path(r).read_text()) for r in (a, b))
    return compare_summaries(sa, sb, a, b, short_us)


def compare_summaries(sa, sb, a, b, short_us=25):
    """perf_compare over two loaded summaries named a and b."""
    metrics = {
        "fps": lambda s: s["gpu"].get("fps_estimate"),
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
    return json.loads(BASELINES.read_text()) if BASELINES.exists() else {}


def tool_perf_baseline(name=None, runs=None):
    """Names a reference for perf_check, or lists them. With name and runs (names from perf_runs, several runs of the
    same program recorded with no change between them), it saves copies of their summaries as the reference `name`,
    replacing a previous one, and returns the range each number spans across them: that range, not one run, is what
    perf_check judges against, since repeated runs differ by a few percent. With name alone it shows that reference;
    with nothing it lists them."""
    baselines = load_baselines()
    if name is not None and not name_ok(name):
        raise ToolError("a reference name holds only letters, digits, '.', '_' and '-'")
    if runs:
        if name is None:
            raise ToolError("runs need a name for the reference")
        if isinstance(runs, str):
            runs = [runs]
        summaries = [json.loads(run_path(r).read_text()) for r in runs]
        baselines[name] = {"runs": list(runs), "set": time.strftime("%Y-%m-%d"), "summaries": summaries}
        OUT.mkdir(parents=True, exist_ok=True)
        BASELINES.write_text(json.dumps(baselines))
    if name is not None:
        if name not in baselines:
            raise ToolError(f"no reference {name}; perf_baseline with no arguments lists them")
        b = baselines[name]
        return {"name": name, "runs": b["runs"], "set": b["set"], "range": ranges(b["summaries"])}
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


def tool_perf_check(run, baseline, margin_pct=3):
    """Judges a recording against a reference saved with perf_baseline: regressed when FPS falls under the
    reference's lowest FPS by more than margin_pct, GPU ms per frame rises over its highest by more than margin_pct,
    or encoders or command buffers per frame exceed its highest; improved when a number leaves the range the other
    way and none regressed; same otherwise. Frame pacing, short encoders and GPU idle time are reported by the
    comparison but do not decide: they vary too much between equal runs. Returns the reasons and perf_compare's
    full comparison against the reference's first run."""
    baselines = load_baselines()
    if baseline not in baselines:
        raise ToolError(f"no reference {baseline}; perf_baseline with no arguments lists them")
    ref = baselines[baseline]
    s = json.loads(run_path(run).read_text())
    span = ranges(ref["summaries"])
    worse, better, unchecked = [], [], []
    for metric, (get, higher_is_worse) in CHECKED.items():
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
    if (s.get("gpu") or {}).get("frames", 0) < 100:
        result["hint"] = "under 100 frames: too short to judge; record 30 s or more"
    if unchecked:
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


def tool_perf_diagnose(run, min_encoders=4, short_us=25, short_share=0.25):
    """Says whether a saved recording splits its GPU work into too many short encoders, the pattern of translation
    layers such as DXMT, Mullion or MoltenVK, with the numbers behind it: encoders and command buffers per frame, the
    share of short encoders, the labels with the most GPU time and the GPU's idle time. Read the idle time together
    with the FPS: a program waiting for vsync idles too. Defaults come from bgfx 17-drawstress on an M1 Pro: 7
    encoders per frame and 50% under 25 us under Mullion, 2 and 2% in native Metal."""
    s = json.loads(run_path(run).read_text())
    encoders = s.get("encoders")
    if not encoders:
        raise ToolError(f"{run} was summarized before version 0.4.0 and has no encoder numbers; record it again")
    share = encoders["short_share"].get(str(int(short_us)))
    if share is None:
        raise ToolError(f"short_us is one of {', '.join(map(str, perf_report.SHORT_US))}")
    per_frame = encoders["per_frame"].get("p50", 0)
    frames = (s.get("gpu") or {}).get("frames", 0)
    return {"run": run, "too_many_short_encoders": per_frame >= min_encoders and share >= short_share,
            "thresholds": {"min_encoders": min_encoders, "short_us": int(short_us), "short_share": short_share},
            "encoders_per_frame_p50": per_frame,
            "command_buffers_per_frame_p50": encoders["command_buffers_per_frame"].get("p50"),
            "short_encoder_share": share, "fps": (s.get("gpu") or {}).get("fps_estimate"),
            "gpu_idle": s.get("gpu_idle"), "by_label": encoders["by_label"], "too_short": frames < 100}


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


def tool_perf_baseline_record(name, count=3, **record):
    """Records the same program `count` times in a row with perf_record's arguments and saves the runs as the
    reference `name` for perf_check, returning the range each number spans across them. Runs are named
    `name`-1, `name`-2, ... Each recording takes its seconds plus about a minute to read back."""
    if not name_ok(name):
        raise ToolError("a reference name holds only letters, digits, '.', '_' and '-'")
    count = int(count)
    if not 1 <= count <= 10:
        raise ToolError("count is 1 to 10")
    runs = []
    for i in range(1, count + 1):
        before = set(OUT.glob(f"{name}-{i}_*.json"))
        tool_perf_record(f"{name}-{i}", **record)
        runs.append(next(iter(set(OUT.glob(f"{name}-{i}_*.json")) - before)).stem)
    return tool_perf_baseline(name, runs)


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
         "seconds": {**I, "description": "recording length, default 20; use 30 under Wine, whose start-up takes part of it; the export afterwards takes about a minute"},
         "wine": {**S, "description": "Wine directory holding bin/wine, or native"},
         "prefix": {**S, "description": "Wine prefix, default WINEPREFIX or ~/.wine; ignored with native"},
         "workdir": {**S, "description": "directory the program starts in, default the program's own"},
         "args": {**S, "description": "program arguments as in a shell, quotes included"},
         "workload": {**S, "description": "a test program from workload_list, fetched with workload_fetch, instead "
                                          "of program"},
         "api": {**S, "description": "with workload: mtl (native Metal), d3d11 or d3d12 (under wine)"},
         "dim": {**I, "description": "with workload drawstress: side of the cube grid, dim^3 draws per frame"}}

TOOLS = {
    "perf_record": (tool_perf_record, schema(RECORD_PROPS, ["label"]), hints("Record a program", destructive=True)),
    "perf_baseline_record": (tool_perf_baseline_record, schema(
        {"name": {**S, "description": "reference name: letters, digits, '.', '_', '-'"},
         "count": {**I, "description": "equal recordings to make, default 3"},
         **{k: v for k, v in RECORD_PROPS.items() if k != "label"}}, ["name"]),
        hints("Record a reference", destructive=True)),
    "perf_attach": (tool_perf_attach, schema(
        {"label": {**S, "description": "name for the run: letters, digits, '.', '_', '-'"},
         "process": {**S, "description": "pid, or a name in the program's command line such as Game.exe"},
         "seconds": {**I, "description": "recording length, default 20; the export afterwards takes about a minute"}},
        ["label", "process"]), hints("Record a running program", destructive=False)),
    "perf_runs": (tool_perf_runs, schema(PAGE), hints("List recordings")),
    "perf_compare": (tool_perf_compare, schema(
        {"a": {**S, "description": "run name from perf_runs: the reference, such as the run before a change"},
         "b": {**S, "description": "run name from perf_runs: the run to compare against a"},
         "short_us": {**I, "description": "an encoder under this GPU time counts as short: 10, 25 (default), 50, 100, "
                                          "250, 500 or 1000"}}, ["a", "b"]),
        hints("Compare two recordings")),
    "perf_baseline": (tool_perf_baseline, schema(
        {"name": {**S, "description": "reference name: letters, digits, '.', '_', '-'; alone, shows that reference"},
         "runs": {"type": "array", "items": S, "description": "run names from perf_runs to save as this reference, "
                                                             "ideally 3 or more equal runs; replaces a previous one"}}),
        hints("Name a reference", destructive=False, idempotent=True)),
    "perf_check": (tool_perf_check, schema(
        {"run": {**S, "description": "a run name from perf_runs"},
         "baseline": {**S, "description": "a reference name from perf_baseline"},
         "margin_pct": {"type": "number", "description": "how far outside the reference's range FPS or GPU ms per "
                                                         "frame may fall before counting, default 3"}},
        ["run", "baseline"]), hints("Check a run against a reference")),
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
}
# Claude Code asks the user before every call of these tools
META = {"workload_fetch": {"anthropic/requiresUserInteraction": True}}

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


def log(message):
    """Writes one line to stderr, the only log channel a stdio server may use."""
    if os.environ.get("METAL_TRACE_LOG") != "off":
        print(f"metal-trace: {message}", file=sys.stderr, flush=True)


def call(name, arguments):
    """Runs one tool and returns its MCP result, with failures as isError results that say what to do."""
    started = time.monotonic()
    try:
        value = TOOLS[name][0](**arguments)
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
        result = {"resourceTemplates": []}
    elif method == "resources/list":
        result = {"resources": [{"uri": uri, "name": name, "description": about, "mimeType": "application/json"}
                                for uri, (name, about, _) in RESOURCES.items()]}
    elif method == "resources/read":
        uri = params.get("uri")
        if uri not in RESOURCES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32002, "message": "Resource not found",
                                                           "data": {"uri": uri}}}
        result = {"contents": [{"uri": uri, "mimeType": "application/json",
                                "text": json.dumps(RESOURCES[uri][2](), ensure_ascii=False)}]}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": f.__doc__.strip(), "inputSchema": s, "annotations": hints}
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
        result = call(name, params.get("arguments") or {})
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    """Serves newline-delimited JSON-RPC on stdin and stdout until stdin closes; --version prints the version."""
    if sys.argv[1:] == ["--version"]:
        print(f"metal-gpu-trace {__version__}")
        return
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        except Exception as error:  # a malformed request must not stop the server
            log(f"internal error {type(error).__name__}")
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "internal error"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
