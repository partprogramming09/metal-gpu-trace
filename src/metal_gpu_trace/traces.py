"""Reading .trace and .gputrace files, and the Apple GPU family facts."""
import csv
import json
import subprocess

from metal_gpu_trace import config, gputrace_read, paths, perf_report


def tool_perf_export_trace(run):
    """Writes a recording's GPU frames as a Chrome trace file, `<run>.chrome-trace` in the runs directory, that
    ui.perfetto.dev and chrome://tracing open: one slice per GPU frame, from its start for its GPU time (the sum of
    its encoders' time, so a frame with parallel encoders can show shorter than it took), with the compute, fragment
    and vertex split as arguments. Returns the file name and the number of frames."""
    paths.run_path(run)
    source = config.OUT / f"{run}.frames.csv"
    if not source.exists():
        raise paths.ToolError(f"{run} has no per-frame file; record it again")
    events = []
    with open(source, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            events.append({"name": "GPU frame", "ph": "X", "pid": 1, "tid": 1, "ts": float(row["start_ms"]) * 1000,
                           "dur": float(row["gpu_ms_total"]) * 1000,
                           "args": {"frame": int(row["frame"]), **{k[7:]: float(v) for k, v in row.items()
                                                                  if k.startswith("gpu_ms_") and k != "gpu_ms_total"}}})
    target = config.OUT / f"{run}.chrome-trace"
    paths.write_file(target, json.dumps({"traceEvents": events, "displayTimeUnit": "ms"}))
    return {"file": target.name, "frames": len(events)}


def tool_trace_tables(trace):
    """Lists the data tables (schemas) a .trace recording holds; recordings keep their .trace only with KEEP_TRACE=1."""
    toc = perf_report.toc_of(paths.trace_path(trace))
    return {"tables": sorted({t.attrib["schema"] for t in toc.iter("table") if "schema" in t.attrib})}


def tool_trace_query(trace, schema, offset=0, limit=50, pid=None):
    """Returns one page of rows of one table of a .trace as {column: value}, optionally only one process's rows."""
    if not schema.replace("-", "").isalnum():
        raise paths.ToolError("schema holds only letters, digits and '-'; trace_tables lists them")
    xpath = f'/trace-toc/run[@number="1"]/data/table[@schema="{schema}"]'
    rows = []
    for row in perf_report.rows(perf_report.export(paths.trace_path(trace), xpath=xpath)):
        if pid is not None and "process" in row and perf_report.pid_of(row["process"]) != int(pid):
            continue
        rows.append({k: (v.attrib.get("fmt") or v.text) if v is not None else None for k, v in row.items()})
    return paths.page(rows, offset, limit)


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
            raise paths.ToolError("a table name holds only letters, digits and '-'; trace_tables lists them")
        if schema not in known:
            out[schema] = {"rows": None, "note": "not in this trace"}
            continue
        xpath = f'/trace-toc/run[@number="1"]/data/table[@schema="{schema}"]'
        total, per = 0, {}
        try:
            for row in perf_report.rows(perf_report.export(paths.trace_path(trace), xpath=xpath)):
                total += 1
                if "process" in row and row["process"] is not None:
                    name = row["process"].attrib.get("fmt") or str(perf_report.pid_of(row["process"]))
                    per[name] = per.get(name, 0) + 1
        except (RuntimeError, subprocess.TimeoutExpired) as error:  # one table's export failing leaves the others
            out[schema] = {"rows": None, "note": str(error)}
            continue
        out[schema] = {"rows": total, "by_process": dict(sorted(per.items(), key=lambda kv: -kv[1])[:10])}
    return {"trace": trace, "tables": out}


def tool_capture_summary(capture):
    """Reads a Metal .gputrace capture without Xcode: command buffers, encoders, draws, debug groups, and the 100
    most frequent call ids out of calls_total."""
    summary = gputrace_read.summarize(paths.allowed(capture))
    summary["calls_total"] = len(summary["calls"])
    summary["calls"] = summary["calls"][:100]
    return summary


def tool_capture_records(capture, offset=0, limit=100):
    """Returns one page of the records of a .gputrace command stream, with their Metal call names when known."""
    out = [{"offset": off, "size": size, "id": call, "signature": signature,
            "name": gputrace_read.CALLS.get(call, (None,))[0], "strings": strings[:3]}
           for off, size, call, signature, strings in gputrace_read.records(paths.allowed(capture) / "capture")]
    return paths.page(out, offset, limit)


def family_of(name):
    """Returns the Metal family key for a family ("apple7") or chip name ("M1 Pro", "A15"), or None."""
    wanted = name.strip().lower().replace(" ", "")
    for key, family in config.FAMILIES["families"].items():
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
        raise paths.ToolError(f"unknown family or chip {name!r}; try one of {', '.join(config.FAMILIES['families'])} or a chip "
                        "such as M1 Pro, M2, M3 Max, A17 Pro")
    return {"family": key, **config.FAMILIES["families"][key], "same_on_all": config.FAMILIES["same_on_all"],
            "footnotes": config.FAMILIES["footnotes"], "guards": config.FAMILIES["guards"], "sources": config.FAMILIES["sources"]}
