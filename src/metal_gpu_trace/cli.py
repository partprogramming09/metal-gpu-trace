"""The short command line in front of the MCP server: `metal-gpu-trace [COMMAND]`.

With no command it serves MCP on stdin and stdout, which is what MCP clients start; the read-only commands here
(`doctor`, `runs`, `compare`, `gate`) reuse the functions the tools use, so a shell answer and an MCP answer never differ."""
import json
import os
import sys

from metal_gpu_trace import analysis, budgets, http_transport, paths, preflight, project, stdio


USAGE = """usage: metal-gpu-trace [COMMAND]

With no command it serves MCP on stdin and stdout, which is what MCP clients start.

Commands:
  init                    add the server to the AI apps installed here
  check RUN BASELINE      judge a run for CI; exits 0, 1 or 2
  gate RUN [--budgets FILE]
                          judge a run against the limits in a file of the repo (default metal-gpu-trace.budgets.json);
                          exits 0, 1 or 2
  --http [--port N]       serve MCP over Streamable HTTP on 127.0.0.1
  doctor                  say what a recording needs that is missing here
  runs [--limit N]        list the recordings, newest first
  compare A B             compare two recordings, A the reference and B after the change (--markdown for a table)
  --version               print the version
  --help, -h              print this help
"""
GATE_USAGE = "usage: metal-gpu-trace gate RUN [--budgets FILE]"


def _usage_error(message):
    """Prints why the command cannot run and the usage, and returns the exit code for a bad invocation."""
    print(message if message.startswith("usage:") else f"metal-gpu-trace: {message}", file=sys.stderr)
    print(USAGE, file=sys.stderr, end="")
    return 2


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


def gate_cli(args):
    """Runs `gate RUN [--budgets FILE]` for CI: judges a recording against the fixed limits of a versioned file in the
    project, prints one JSON line and returns 0 when every metric is within its limits, 1 when one is not, and 2 when
    it could not be judged (bad arguments, no budgets file or a broken one, no such run, under 100 frames, a program
    that stopped presenting, or a metric the recording cannot measure)."""
    rest = list(args)
    path = None
    if "--budgets" in rest:
        index = rest.index("--budgets")
        path = rest[index + 1] if index + 1 < len(rest) else None
        del rest[index:index + 2]
        if not path or path.startswith("--"):
            print(GATE_USAGE, file=sys.stderr)
            return 2
    if len(rest) != 1 or rest[0].startswith("--"):
        print(GATE_USAGE, file=sys.stderr)
        return 2
    try:
        result = budgets.gate(rest[0], path)
    except (paths.ToolError, FileNotFoundError, ValueError) as error:
        print(f"metal-gpu-trace: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0 if result["verdict"] == "pass" else 1


def _cell(value):
    """Returns a table cell: `-` for a number a run does not have, at most three decimals otherwise."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{round(value, 3):.3f}".rstrip("0").rstrip(".")
    return str(value)


def doctor(args):
    """Prints preflight's report of what a recording needs here (the checks `init` notes and a recording refuses on):
    one line per check, `ok` or what is missing with the exact fix. Exits 0 when a recording could start, else 2."""
    if args:
        return _usage_error("usage: metal-gpu-trace doctor")
    project.apply()
    try:
        project.check()
    except paths.ToolError as error:
        print(f"metal-gpu-trace: {error}", file=sys.stderr)
        return 2
    report = preflight.environment_report(wine=os.environ.get("METAL_TRACE_WINE") or None, seconds=30)
    for item in report["checks"]:
        line = f"{item['status']:<8} {item['name']}"
        if item.get("solution"):
            line += f": {item['solution']}"
        print(line)
    print("ok: a recording can start" if report["ok"] else "missing: fix the items above before recording")
    return 0 if report["ok"] else 2


def runs(args):
    """Runs `runs [--limit N]`: lists the recordings newest first, as `perf_runs` does, one line each."""
    if not args:
        limit = 50
    elif len(args) == 2 and args[0] == "--limit" and args[1].isascii() and args[1].isdigit() \
            and int(args[1]) >= 1:
        limit = int(args[1])
    else:
        return _usage_error("usage: metal-gpu-trace runs [--limit N]")
    project.apply()
    try:
        project.check()
        result = analysis.tool_perf_runs(limit=limit)
    except (paths.ToolError, FileNotFoundError, ValueError) as error:
        print(f"metal-gpu-trace: {error}", file=sys.stderr)
        return 2
    if not result["rows"]:
        print("no recordings")
        return 0
    print(f"{'run':<40} {'frames':>7} {'fps':>7} {'gpu ms':>7} {'metal MiB':>10} {'rss MiB':>8}  layer")
    for row in result["rows"]:
        print(f"{row['run']:<40} {_cell(row['frames']):>7} {_cell(row['fps']):>7} {_cell(row['gpu_ms_mean']):>7} "
              f"{_cell(row['metal_mib_peak']):>10} {_cell(row['rss_mib_max']):>8}  {row['layer'] or '-'}")
    if result["next_offset"] is not None:
        print(f"{result['total'] - result['next_offset']} more; raise --limit to list them")
    return 0


def _print_compare(result):
    """Prints a `perf_compare` result as the headline table, then the first thing to call next when there is one."""
    print(f"{result['a']} (a) vs {result['b']} (b)")
    print(f"{'metric':<28} {'a':>10} {'b':>10} {'change':>10} {'%':>8}")
    for name, item in result["metrics"].items():
        print(f"{name:<28} {_cell(item['a']):>10} {_cell(item['b']):>10} {_cell(item['change']):>10} "
              f"{_cell(item['change_pct']):>8}")
    if result.get("too_short"):
        print(f"too short to compare (under 100 frames): {', '.join(result['too_short'])}")
    layer = result.get("layer") or {}
    if layer.get("note"):
        print(layer["note"])
    actions = result.get("suggested_actions") or []
    if actions:
        print(f"next: {actions[0]['tool']} {json.dumps(actions[0]['arguments'])}: {actions[0]['reason']}")


def compare(args):
    """Runs `compare A B [--markdown]`: compares two recordings (A the reference, B after a change) with
    `perf_compare`, as a plain table or as its Markdown report."""
    markdown = "--markdown" in args
    names = [arg for arg in args if arg != "--markdown"]
    if len(names) != 2 or any(name.startswith("--") for name in names):
        return _usage_error("usage: metal-gpu-trace compare A B [--markdown]")
    project.apply()
    try:
        project.check()
        result = analysis.tool_perf_compare(names[0], names[1], markdown=markdown)
    except (paths.ToolError, FileNotFoundError, ValueError) as error:
        print(f"metal-gpu-trace: {error}", file=sys.stderr)
        return 2
    if markdown:
        print(result["markdown"])
    else:
        _print_compare(result)
    return 0


def _http(args):
    """Serves Streamable HTTP on 127.0.0.1 (`--http [--port N]`) and returns `serve_http`'s exit code."""
    if not args:
        return http_transport.serve_http(8765)
    try:
        port = int(args[1]) if args[0] == "--port" and len(args) == 2 else None
    except ValueError:
        port = None
    if port is None:
        return _usage_error("usage: metal-gpu-trace --http [--port N]")
    return http_transport.serve_http(port)


def main(args, version):
    """Runs the command in `args` (without the program name) and returns its exit code. No command serves MCP on
    stdin and stdout; `--help` and an unknown command answer in the terminal instead of waiting for a client."""
    if args == ["--version"]:
        print(f"metal-gpu-trace {version}")
        return 0
    if args[:1] in (["--help"], ["-h"]):
        print(USAGE, end="")
        return 0
    command, rest = (args[0], args[1:]) if args else (None, [])
    if command in ("check", "doctor", "runs", "compare", "gate") and rest[:1] in (["--help"], ["-h"]):
        print(USAGE, end="")
        return 0
    if command == "init":  # before project.apply(): it only edits client config files
        from metal_gpu_trace import init
        return init.main(rest)
    if command is None:  # an MCP client starts the server this way: the transport must not change
        project.apply()
        stdio.serve_stdio()
        return 0
    if command == "check":
        project.apply()
        return check_cli(rest)
    if command == "gate":
        project.apply()
        return gate_cli(rest)
    if command == "--http":
        project.apply()
        return _http(rest)
    if command == "doctor":
        return doctor(rest)
    if command == "runs":
        return runs(rest)
    if command == "compare":
        return compare(rest)
    return _usage_error(f"unknown command {command!r}")
