"""Reading .trace and .gputrace files, and the Apple GPU family facts."""
import contextlib
import csv
import json
import os
import sqlite3
import subprocess

from metal_gpu_trace import config, gputrace_read, paths, perf_report, tabledb, tables as table_files  # tool_trace_count has a `tables` argument


def tool_perf_export_trace(run):
    """Writes a recording's GPU frames as `<run>.chrome-trace` in the runs directory, for ui.perfetto.dev and
    chrome://tracing: one slice per GPU frame. Returns the file name and the number of frames."""
    paths.run_path(run)
    source = table_files.find(config.OUT, f"{run}.frames")
    if source is None:
        raise paths.ToolError(f"{run} has no per-frame file; record it again")
    events = []
    try:
        with table_files.open_text(source) as f:
            for row in csv.DictReader(f):
                events.append({"name": "GPU frame", "ph": "X", "pid": 1, "tid": 1, "ts": float(row["start_ms"]) * 1000,
                               "dur": float(row["gpu_ms_total"]) * 1000,
                               "args": {"frame": int(row["frame"]), **{k[7:]: float(v) for k, v in row.items()
                                                                      if k.startswith("gpu_ms_") and k != "gpu_ms_total"}}})
    except (*table_files.UNREADABLE, KeyError, TypeError, ValueError):
        raise paths.ToolError(f"{source.name} cannot be read; record it again") from None
    target = config.OUT / f"{run}.chrome-trace"
    paths.write_file(target, json.dumps({"traceEvents": events, "displayTimeUnit": "ms"}))
    return {"file": target.name, "frames": len(events)}


def source_of(trace, filtering=False):
    """Returns (the .trace path, the tables file path or None) to read for `trace`: the .trace when it is there, else
    the tables file the recording left. A run with neither gets the .trace path, whose export says so (`missing`). With
    `filtering` (where, columns, order_by, group_by, aggregates) only the tables file can answer."""
    path = paths.trace_path(trace)
    db = tabledb.path_for(path)
    if filtering and not os.path.lexists(db):
        raise paths.ToolError(f"where, columns, order_by, descending, group_by and aggregates read the tables file, and "
                              f"{db.name} is not there (a recording made before it existed, or one with --no-tables): "
                              "leave them out, or record the run again")
    if filtering or (not path.exists() and os.path.lexists(db)):
        return path, db
    return path, None


def missing(path):
    """Returns the error for a run that has neither a .trace nor a tables file."""
    return paths.ToolError(f"no recording at {path.name} and no {tabledb.path_for(path).name}: the .trace is deleted once "
                           "its summary is written unless KEEP_TRACE=1, and the tables file is written at every recording "
                           "(not with --no-tables); record the run again")


@contextlib.contextmanager
def tables_file(db):
    """Opens the tables file `db` read-only; its errors (a link, a damaged file) are ToolErrors that never name a path."""
    try:
        conn = tabledb.connect(db)
    except ValueError as error:
        raise paths.ToolError(str(error)) from None
    try:
        yield conn
    except sqlite3.Error:
        raise paths.ToolError(f"{db.name} cannot be read; record the run again") from None
    finally:
        conn.close()


def tool_trace_tables(trace):
    """Lists the data tables of a recording: those of its .trace when kept, else those its tables file stored."""
    path, db = source_of(trace)
    if db is not None:
        with tables_file(db) as conn:
            return {"tables": tabledb.tables(conn)}
    try:
        toc = perf_report.toc_of(path)
    except FileNotFoundError:
        raise missing(path) from None
    return {"tables": sorted({t.attrib["schema"] for t in toc.iter("table") if "schema" in t.attrib})}


TIME_COLUMNS = ("start", "time")  # the GPU tables name their time column `start`, time-profile names it `time`; both in ns


def check_window(window_ms):
    """Returns `window_ms` as a whole number of milliseconds from 1 to 3600000 (10.0 counts as 10), or None when it is
    None."""
    if window_ms is None:
        return None
    if isinstance(window_ms, float) and window_ms.is_integer():
        window_ms = int(window_ms)
    if isinstance(window_ms, bool) or not isinstance(window_ms, int) or not 1 <= window_ms <= 3_600_000:
        raise paths.ToolError("window_ms is a whole number of milliseconds from 1 to 3600000")
    return window_ms


def windows_of(rows, window_ms):
    """Groups `rows` ({column: element}) by `window_ms` of their time column: returns (windows, skipped), the windows
    as {"start_ms", "count"} plus "duration_ms" when the table has a duration column, and `skipped` the rows whose time
    is not a number of ns from 0 (or whose time column is missing: the first row decides which column the table has).
    Only windows that hold a row are listed."""
    found, skipped, key, has_duration = {}, 0, None, False
    for number, row in enumerate(rows):
        if number == 0:
            key = next((k for k in TIME_COLUMNS if k in row), None)
            has_duration = "duration" in row
            if key is None:
                raise paths.ToolError("window_ms needs a table with a time column (start or time); trace_tables lists "
                                      "the tables and trace_query without window_ms shows the columns")
        try:
            ns = int(row[key].text)
            if ns < 0:
                raise ValueError
        except (KeyError, AttributeError, TypeError, ValueError):
            skipped += 1
            continue
        index = ns // (window_ms * 1_000_000)
        window = found.setdefault(index, {"start_ms": index * window_ms, "count": 0, "duration_ns": 0})
        window["count"] += 1
        if has_duration:
            try:
                window["duration_ns"] += int(row["duration"].text)
            except (KeyError, AttributeError, TypeError, ValueError):
                pass
    out = []
    for index in sorted(found):
        window = found[index]
        ns = window.pop("duration_ns")
        if has_duration:
            window["duration_ms"] = round(ns / 1_000_000, 3)
        out.append(window)
    return out, skipped


def tool_trace_query(trace, schema, offset=0, limit=50, pid=None, window_ms=None, where=None, columns=None,
                     order_by=None, descending=None, group_by=None, aggregates=None):
    """Returns one page of rows of one table of a recording as {column: value}, optionally one process's. With window_ms the
    page holds time windows instead ({start_ms, count}, plus duration_ms when the table has a duration column). Rows come
    from the .trace when kept, else from the tables file; where, columns, order_by with descending, and group_by with
    aggregates filter and summarize the tables file (never SQL) and need it."""
    window = check_window(window_ms)
    if not schema.replace("-", "").isalnum():
        raise paths.ToolError("schema holds only letters, digits and '-'; trace_tables lists them")
    declarative = {"where": where, "columns": columns, "order_by": order_by, "descending": descending,
                   "group_by": group_by, "aggregates": aggregates}
    filtering = any(v is not None for v in declarative.values())
    if window is not None and any(declarative[k] is not None for k in ("columns", "order_by", "descending", "group_by", "aggregates")):
        raise paths.ToolError("window_ms combines only with where and pid")
    path, db = source_of(trace, filtering)
    if db is not None:
        return query_tables_file(db, schema, window, pid, offset, limit, declarative)
    xpath = f'/trace-toc/run[@number="1"]/data/table[@schema="{schema}"]'
    try:
        exported = perf_report.rows(perf_report.export(path, xpath=xpath))
    except FileNotFoundError:
        raise missing(path) from None
    selected = (row for row in exported
                if pid is None or "process" not in row or perf_report.pid_of(row["process"]) == int(pid))
    try:
        if window is not None:
            windows, skipped = windows_of(selected, window)
            got = {**paths.page(windows, offset, limit), "window_ms": window}
            if skipped:
                got["skipped_rows"] = skipped
            return got
        return paths.page([{k: (v.attrib.get("fmt") or v.text) if v is not None else None for k, v in row.items()}
                           for row in selected], offset, limit)
    finally:
        exported.close()  # deletes the exported file now, also when windows_of raised


def query_tables_file(db, schema, window, pid, offset, limit, declarative):
    """trace_query over the tables file `db`: the same rows and windows as the export gives, plus the declarative filters."""
    with tables_file(db) as conn:
        if schema not in tabledb.tables(conn):
            raise paths.ToolError(f"{schema} is not in {db.name}; trace_tables lists the tables it holds")
        try:
            if window is not None:
                windows, skipped = windows_of(tabledb.time_rows(conn, schema, (*TIME_COLUMNS, "duration"), pid, declarative["where"]), window)
                got = {**paths.page(windows, offset, limit), "window_ms": window}
                if skipped:
                    got["skipped_rows"] = skipped
                return got
            return tabledb.select(conn, schema, declarative["where"], declarative["columns"], declarative["order_by"],
                                  declarative["descending"], declarative["group_by"], declarative["aggregates"], pid, offset, limit)
        except (ValueError, OverflowError) as error:  # OverflowError: a number beyond SQLite's 64 bits
            raise paths.ToolError(str(error)) from None


# the tables of a kept .trace that say most about a translation layer, counted by trace_count when none are named
COUNTED_TABLES = ["metal-gpu-intervals", "metal-application-encoders-list", "metal-command-buffer-completed",
                  "graphics-compiler-spill-events", "graphics-compiler-activity-intervals",
                  "metal-shader-profiler-shader-list", "metal-resource-allocations", "metal-gpu-counter-intervals",
                  "gpu-shader-profiler-sample", "time-profile"]


def tool_trace_count(trace, tables=None):
    """Counts the rows of tables of a recording, in all and per process: a table with 0 rows needs another instrument or
    Xcode, not a bigger page. Reads the .trace when kept, else the tables file."""
    tables = tables or COUNTED_TABLES
    for schema in tables:
        if not isinstance(schema, str) or not schema.replace("-", "").isalnum():
            raise paths.ToolError("a table name holds only letters, digits and '-'; trace_tables lists them")
    path, db = source_of(trace)
    out = {}
    if db is not None:
        with tables_file(db) as conn:
            known = set(tabledb.tables(conn))
            for schema in tables:
                if schema not in known:
                    out[schema] = {"rows": None, "note": "not in this trace's tables file"}
                    continue
                total, per = tabledb.process_counts(conn, schema)
                out[schema] = {"rows": total, "by_process": per}
        return {"trace": trace, "tables": out}
    known = set(tool_trace_tables(trace)["tables"])
    for schema in tables:
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


def tool_capture_diff(a, b):
    """Compares two .gputrace captures by their confirmed Metal calls: totals per call (a, b, delta) and the 100 debug
    groups with the largest change. Needs no Xcode."""
    result = gputrace_read.diff(paths.allowed(a), paths.allowed(b))
    result["groups_total"] = len(result["groups"])
    result["groups"] = result["groups"][:100]
    return result


def tool_capture_records(capture, offset=0, limit=100):
    """Returns one page of the records of a .gputrace command stream, with their Metal call names when known."""
    out = [{"offset": off, "size": size, "id": call, "signature": signature,
            "name": gputrace_read.CALLS.get(call, (None,))[0], "strings": strings[:3]}
           for off, size, call, signature, strings in gputrace_read.records(gputrace_read.stream_of(paths.allowed(capture))[1])]
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
    """Apple's published facts for one GPU family ("Apple7") or chip ("M1 Pro"): its chips, what it adds, its limits, the
    limits shared by all families, footnotes and source URLs."""
    key = family_of(name)
    if key is None:
        raise paths.ToolError(f"unknown family or chip {name!r}; try one of {', '.join(config.FAMILIES['families'])} or a chip "
                        "such as M1 Pro, M2, M3 Max, A17 Pro")
    return {"family": key, **config.FAMILIES["families"][key], "same_on_all": config.FAMILIES["same_on_all"],
            "footnotes": config.FAMILIES["footnotes"], "guards": config.FAMILIES["guards"], "sources": config.FAMILIES["sources"]}
