"""MCP server (stdio, JSON-RPC 2.0, standard library only) that records Wine or macOS programs with Instruments'
Metal System Trace and reads the recordings and Metal .gputrace captures.

A metal-gpu-trace.json in the working directory or a folder above it (below the home folder) names the project and
the folder its recordings go to and are read from; METAL_TRACE_PROJECT names that file (or its folder) instead.

Environment: METAL_TRACE_OUT is where recordings go without a project file (default ./perf-runs); METAL_TRACE_READ lists more directories,
separated by ':', whose files the tools may read; METAL_TRACE_WINE is the default Wine directory; KEEP_RUNS caps the
recordings kept; METAL_TRACE_MAX_DISK_MB caps the size of the recordings folder (the oldest .trace and per-frame tables go first,
summaries never); METAL_TRACE_ALLOW_LOCKED=1 records with the screen locked (it is refused otherwise); METAL_TRACE_LOCK moves the lock that keeps recordings one at a time (in the cache folder below);
METAL_TRACE_LOG=off silences the one stderr line per call. Test programs that workload_fetch
downloads go to ~/Library/Caches/metal-gpu-trace.
"""
import json
import pathlib
import sys

__version__ = "0.27.2"
if __package__ in (None, ""):  # run by path: make the package importable
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from metal_gpu_trace import analysis, http_transport, paths, project, protocol, stdio, worker  # noqa: E402

INSTRUCTIONS = (
    "Records GPU use on Apple silicon with Metal System Trace. A metal-gpu-trace.json in the repository gives each "
    "project its own recordings folder; project_info says which project is active. One recording runs at a time; keep other GPU work off "
    "the Mac while it records, and keep the program's window visible: a hidden window stops presenting, and the work "
    "after that is left out of the frames (gpu.unpresented; perf_gate fails such a run). Under Wine record 30 s or more: Wine's start-up takes part of the recording. A recording needs about 0.8 GB of free disk "
    "per second for Instruments' temporary files (26 GB for 30 s, 50 GB for 60 s); perf_record refuses to start without it. Reading a "
    "recording back takes 1 to 14 s per recorded second. Compare only recordings with 100 frames or more, and repeat "
    "a run before calling a change real. perf_baseline (or perf_baseline_record, which records them) saves several equal runs as a named reference and perf_check says whether a new run regressed against their range. perf_diagnose says whether a run splits its GPU work into too many short "
    "encoders, as translation layers do; perf_compare says how much two runs differ; skip_s on perf_compare and perf_gate leaves out the first seconds (start-up) of each run; perf_history follows FPS, hitches and memory across runs with one name prefix, oldest first; perf_gate says whether a run meets budgets you set (FPS floor, hitch or memory ceiling). trace_tables and trace_query "
    "need the .trace, kept only with KEEP_TRACE=1. When perf_record ends it stops every program of its Wine prefix, "
    "or every process named like a native program. To compare native Metal with a translation layer without a game "
    "of one's own: workload_list, workload_fetch, then perf_record with workload and api (and example, for a workload "
    "that lists examples), or the compare-layer prompt. The diagnose-stutter prompt tells first-seen shader stutter from "
    "steady stutter; bisect-regression finds the commit that slowed a program. perf_sweep records one run per value of dim, example, api or an "
    "environment variable and fits GPU ms per frame on the value. trace_query with window_ms sums a long table by time window instead of listing rows. memory_free_pct holds the whole Mac short of memory "
    "while recording (keep other work off it) and background throttles the program: repeat a run that uses either. "
    "Use tier light to iterate, standard to decide, deep for GPU counters and a kept .trace (METAL_TRACE_MAX_DISK_MB may "
    "drop it); compare recordings of the same tier. "
    "perf_diagnose and perf_compare return suggested_actions: when it is not empty, run the first one that fits. On a "
    "laptop set cooldown_s on perf_baseline_record, perf_ab and perf_sweep so the Mac cools between recordings; a run "
    "whose summary has noisy_environment (another process was loading the GPU) is repeated before it is trusted. A "
    "recording is refused before it starts when its program, xcrun, the disk or the lock is not ready, or when the "
    "screen is locked (METAL_TRACE_ALLOW_LOCKED=1 allows that). When memory spikes or a run stalls, "
    "perf_memory_breakdown says which resource types it allocates and drops."
)

protocol.configure(instructions=INSTRUCTIONS, version=__version__)
worker.configure(send=stdio.send, answer=protocol.answer, finish=protocol.finish)


def check_cli(args):
    """Runs `check RUN BASELINE [--margin-pct N]` for CI: prints perf_check's verdict, reasons and hints as one JSON
    line and returns 0 when the run is the same or improved, 1 when it regressed, 2 when it could not be judged
    (no such run or reference), too short to judge (under 100 frames) or its program stopped presenting."""
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
        project.check()
        result = analysis.tool_perf_check(run, baseline, margin)
    except (paths.ToolError, FileNotFoundError, ValueError) as error:
        print(f"metal-gpu-trace: {error}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in result.items() if k not in ("comparison", "range")}))
    if "hint" in result or "unpresented" in result:
        return 2
    return 1 if result["verdict"] == "regressed" else 0


def main():
    """Serves newline-delimited JSON-RPC on stdin and stdout until stdin closes; --version prints the version, and
    `check` judges a run for CI (see check_cli)."""
    if sys.argv[1:] == ["--version"]:
        print(f"metal-gpu-trace {__version__}")
        return
    project.apply()
    if sys.argv[1:2] == ["check"]:
        sys.exit(check_cli(sys.argv[2:]))
    if sys.argv[1:2] == ["--http"]:
        try:
            port = int(sys.argv[3]) if sys.argv[2:3] == ["--port"] else 8765
        except (IndexError, ValueError):
            print("usage: metal-gpu-trace --http [--port N]", file=sys.stderr)
            sys.exit(2)
        sys.exit(http_transport.serve_http(port))
    stdio.serve_stdio()


if __name__ == "__main__":
    main()
