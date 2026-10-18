"""MCP server (stdio, JSON-RPC 2.0, standard library only) that records Wine or macOS programs with Instruments'
Metal System Trace and reads the recordings and Metal .gputrace captures.

Environment: METAL_TRACE_OUT is where recordings go (default ./perf-runs); METAL_TRACE_READ lists more directories,
separated by ':', whose files the tools may read; METAL_TRACE_WINE is the default Wine directory; KEEP_RUNS caps the
recordings kept; METAL_TRACE_LOG=off silences the one stderr line per call.
"""
import json
import os
import pathlib
import shlex
import shutil
import signal
import subprocess
import sys
import time

__version__ = "0.4.0"
TOOLS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
import gputrace_read  # noqa: E402
import perf_report  # noqa: E402

OUT = pathlib.Path(os.environ.get("METAL_TRACE_OUT", "perf-runs")).resolve()
READ = [OUT] + [pathlib.Path(p).resolve() for p in os.environ.get("METAL_TRACE_READ", "").split(":") if p]
FAMILIES = json.loads((TOOLS_DIR / "data" / "apple-gpu-families.json").read_text())
MAX_LIMIT = 500
# newest first; initialize answers with the client's version when listed here, else the first
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
# results stay under Claude Code's 50 000-character limit, above which it saves them to a file
MAX_TEXT = 40_000
INSTRUCTIONS = (
    "Records GPU use on Apple silicon with Metal System Trace. One recording runs at a time; keep other GPU work off "
    "the Mac while it records. Under Wine record 30 s or more: Wine's start-up takes part of the recording. Reading a "
    "recording back takes 1 to 9 s per recorded second. Compare only recordings with 100 frames or more, and repeat "
    "a run before calling a change real. perf_diagnose says whether a run splits its GPU work into too many short "
    "encoders, as translation layers do; perf_compare says how much two runs differ. trace_tables and trace_query need the .trace, kept only with KEEP_TRACE=1. "
    "When perf_record ends it stops every program of its Wine prefix, or every process named like a native program."
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
    if not path.exists():
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


def tool_perf_record(label, program, seconds=20, wine=None, prefix=None, workdir=None, args=""):
    """Records `program` (an .exe under Wine, or a macOS binary with wine="native") for `seconds` with Metal System
    Trace and returns its summary: GPU ms per frame, frame intervals, FPS, Metal and resident memory. When it ends it
    stops every program of that Wine prefix (wineserver -k), or every process named like the program with native."""
    wine = wine or os.environ.get("METAL_TRACE_WINE")
    if not wine:
        raise ToolError("pass wine (a Wine directory holding bin/wine, or native) or set METAL_TRACE_WINE")
    program = pathlib.Path(program).expanduser()
    if not program.exists():
        raise ToolError(f"no program at {program.name}")
    workdir = pathlib.Path(workdir).expanduser() if workdir else program.parent
    prefix = pathlib.Path(prefix or os.environ.get("WINEPREFIX", "~/.wine")).expanduser()
    return record(label, seconds, wine, prefix, workdir, [str(program.resolve()), *shlex.split(args)])


def tool_perf_attach(label, process, seconds=20):
    """Records a program that is already running, by pid or by a name in its command line (Game.exe under Wine),
    for `seconds` and returns the same summary as perf_record; the program keeps running. For games started by
    Steam, CrossOver, NotProton or any launcher: start the game or its benchmark there first."""
    return record(label, seconds, "attach", "-", "-", [str(process)])


def deadline(seconds):
    """Returns the seconds a recording of `seconds` may take in all; reading it back takes about 9 s per second."""
    return int(seconds) * 10 + 120


def record(label, seconds, wine, prefix, workdir, command):
    """Runs perf_record.sh and returns the summary it wrote, stopping the whole recording and deleting its files if
    it overruns."""
    if not name_ok(label):
        raise ToolError("label holds only letters, digits, '.', '_' and '-'")
    env = dict(os.environ, PERF_OUT=str(OUT))
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
    return json.loads(new[-1].read_text())


def tool_perf_runs(offset=0, limit=50):
    """Lists the saved recordings, newest first, with frames, FPS, GPU ms per frame and memory peaks."""
    runs = []
    for path in sorted(OUT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
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
                     "trace_kept": path.with_suffix(".trace").is_dir()})
    return page(runs, offset, limit)


def tool_perf_compare(a, b):
    """Compares two saved recordings (names from perf_runs): each headline number, its change and change in %.
    Recordings with under 100 frames are flagged: too short to compare."""
    sa, sb = (json.loads(run_path(r).read_text()) for r in (a, b))
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
            va, vb = get(sa), get(sb)
        except (KeyError, TypeError):
            va = vb = None
        change = None if va is None or vb is None else round(vb - va, 3)
        out[name] = {"a": va, "b": vb, "change": change,
                     "change_pct": None if change is None or not va else round(100 * change / va, 1)}
    short = [r for r, s in ((a, sa), (b, sb)) if (s.get("gpu") or {}).get("frames", 0) < 100]
    return {"a": a, "b": b, "metrics": out, "too_short": short}


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


def hints(title, destructive=None):
    """Returns a tool's MCP annotations: read-only unless `destructive` says whether its writes stop programs."""
    if destructive is None:
        return {"title": title, "readOnlyHint": True, "openWorldHint": False}
    return {"title": title, "readOnlyHint": False, "destructiveHint": destructive, "idempotentHint": False,
            "openWorldHint": False}


TOOLS = {
    "perf_record": (tool_perf_record, schema(
        {"label": {**S, "description": "name for the run: letters, digits, '.', '_', '-'"},
         "program": {**S, "description": "path of the .exe, or of the macOS binary with wine=native"},
         "seconds": {**I, "description": "recording length, default 20; use 30 under Wine, whose start-up takes part of it; the export afterwards takes about a minute"},
         "wine": {**S, "description": "Wine directory holding bin/wine, or native"},
         "prefix": {**S, "description": "Wine prefix, default WINEPREFIX or ~/.wine; ignored with native"},
         "workdir": {**S, "description": "directory the program starts in, default the program's own"},
         "args": {**S, "description": "program arguments as in a shell, quotes included"}}, ["label", "program"]),
        hints("Record a program", destructive=True)),
    "perf_attach": (tool_perf_attach, schema(
        {"label": {**S, "description": "name for the run: letters, digits, '.', '_', '-'"},
         "process": {**S, "description": "pid, or a name in the program's command line such as Game.exe"},
         "seconds": {**I, "description": "recording length, default 20; the export afterwards takes about a minute"}},
        ["label", "process"]), hints("Record a running program", destructive=False)),
    "perf_runs": (tool_perf_runs, schema(PAGE), hints("List recordings")),
    "perf_compare": (tool_perf_compare, schema(
        {"a": {**S, "description": "run name from perf_runs: the reference, such as the run before a change"},
         "b": {**S, "description": "run name from perf_runs: the run to compare against a"}}, ["a", "b"]),
        hints("Compare two recordings")),
    "perf_diagnose": (tool_perf_diagnose, schema(
        {"run": {**S, "description": "a run name from perf_runs"},
         "min_encoders": {**I, "description": "encoders per frame (median) from which the verdict can be yes, default 4"},
         "short_us": {**I, "description": "an encoder under this GPU time counts as short: 10, 25 (default), 50, 100, "
                                          "250, 500 or 1000"},
         "short_share": {"type": "number", "description": "share of short encoders from which the verdict is yes, "
                                                          "default 0.25"}}, ["run"]),
        hints("Diagnose encoder use")),
    "trace_tables": (tool_trace_tables, schema({"trace": TRACE}, ["trace"]), hints("List a trace's tables")),
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
}


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
                  "capabilities": {"tools": {}, "resources": {}},
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
        result = {"tools": [{"name": n, "description": f.__doc__.strip(), "inputSchema": s,
                             "annotations": hints} for n, (f, s, hints) in TOOLS.items()]}
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
