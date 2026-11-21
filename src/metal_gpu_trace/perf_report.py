"""Summarizes an Instruments "Metal System Trace" recording of one launched program: GPU time per frame and memory.

Usage: python3 -I src/metal_gpu_trace/perf_report.py <recording.trace> [--label NAME] [--out DIR] [--no-memory] [--no-tables]
Writes <out>/<label>.json (summary), <label>.frames.csv.gz (one row per GPU frame), <label>.metal_memory.csv.gz (Metal
memory over time) and <label>.tables.sqlite (the tables it read, for trace_query once the .trace is gone). A <recording>.rss.csv beside the trace adds the process's resident memory.
"""
import argparse
import array
import collections
import concurrent.futures
import csv
import html
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

if __package__ in (None, ""):  # run by path (perf_record.sh does): make the package importable
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from metal_gpu_trace import metrics, perf_report_frames, perf_report_host, tabledb, tables as table_files  # noqa: E402  (summarize has a local named tables)

# the numbers shared with the Windows recorder live in metrics; these names keep perf_report's interface
SHORT_US, stats, label_name = metrics.SHORT_US, metrics.stats, metrics.label_name
encoder_stats, idle_gaps, public_arguments = metrics.encoder_stats, metrics.idle_gaps, metrics.public_arguments
# frame pacing lives in perf_report_frames and the machine's state in perf_report_host; these names keep the interface
UNPRESENTED_MIN_BUFFERS, UNPRESENTED_FACTOR = perf_report_frames.UNPRESENTED_MIN_BUFFERS, perf_report_frames.UNPRESENTED_FACTOR
UNPRESENTED_MIN_S, STUTTER_FLOOR_MS = perf_report_frames.UNPRESENTED_MIN_S, perf_report_frames.STUTTER_FLOOR_MS
unpresented, presented, frame_pacing = perf_report_frames.unpresented, perf_report_frames.presented, perf_report_frames.frame_pacing
attribute_hitches, attach_limiters = perf_report_frames.attribute_hitches, perf_report_frames.attach_limiters
limiter_in, memory_trend = perf_report_frames.limiter_in, perf_report_frames.memory_trend
NOISY_EXTERNAL_PCT, noisy_environment = perf_report_host.NOISY_EXTERNAL_PCT, perf_report_host.noisy_environment
other_processes, read_command = perf_report_host.other_processes, perf_report_host.read_command
screen_locked, power_state, power_block = perf_report_host.screen_locked, perf_report_host.power_state, perf_report_host.power_block
machine_info = perf_report_host.machine_info

# the tables a summary reads, one xpath each (a multi-table xpath keeps the first table's columns only)
MEMORY = "metal-current-allocated-size"
TABLES = ("metal-gpu-intervals", MEMORY, "gpu-performance-state-intervals")
# read only when the trace has it: without it encoders go without labels
OPTIONAL = ("metal-application-encoders-list", "graphics-compiler-activity-intervals", "device-thermal-state-intervals",
            "ProcessCPUUsage", "metal-resource-allocations", "metal-command-buffer-error",
            "graphics-compiler-spill-events")
# each xctrace export keeps a temporary store of gigabytes on a big trace: two at a time bound the disk it needs
EXPORT_WORKERS = 2
# Metal GPU Counters (PERF_INSTRUMENTS): about 450 000 samples and 64 MB of XML per recorded second, so its export may take minutes
COUNTER_TABLES = ("gpu-counter-info", "gpu-counter-value")
EXPORT_TIMEOUTS = {"gpu-counter-value": 3600}
COUNTER_TIME = re.compile(r'<event-time (id|ref)="(\d+)"[^>]*?(?:/>|>([^<]*)</)')
COUNTER_BIN_NS = 10_000_000  # the Limiter counters are kept as means per 10 ms
COUNTER_CELL = re.compile(r'<(uint32|fixed-decimal) (id|ref)="(\d+)"[^>]*?(?:/>|>([^<]*)</)')


def export(trace, xpath=None, toc=False, timeout=600):
    """Returns the path of a temporary XML file holding the trace's table of contents or the table that `xpath`
    selects; `rows` and `toc_of` delete it once read."""
    if not pathlib.Path(trace).is_dir():
        raise FileNotFoundError(f"no recording at {pathlib.Path(trace).name}: perf_record.sh deletes the .trace once "
                                "its summary is written, unless KEEP_TRACE=1")
    out = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
    out.close()
    cmd = ["xcrun", "xctrace", "export", "--input", str(trace), "--output", out.name]
    cmd += ["--toc"] if toc else ["--xpath", xpath]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if proc.returncode and complete_xml(out.name):
        return out.name  # xctrace 27.1 writes some tables whole and then dies with SIGTRAP (exit 133, or -5 here)
    if proc.returncode:
        os.unlink(out.name)
        reason = (proc.stderr.strip().splitlines() or ["no message"])[-1]
        raise RuntimeError(f"xctrace export of {pathlib.Path(trace).name} failed (exit {proc.returncode}): {reason}")
    return out.name


def complete_xml(path):
    """Returns whether the file ends with the export's closing tag, at a row boundary or right after the schema of an
    empty table, so a crash after writing the rows loses nothing."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 64))
            tail = f.read().rstrip()
        return tail.endswith((b"</trace-query-result>", b"</trace-toc>", b"</row>", b"</schema>"))
    except OSError:
        return False


def toc_of(trace):
    """Returns the root element of the trace's table of contents."""
    path = export(trace, toc=True)
    try:
        return ET.parse(path).getroot()
    finally:
        os.unlink(path)


def table_xpath(schema):
    """Returns the xpath that selects one table of the first run."""
    return f'/trace-toc/run[@number="1"]/data/table[@schema="{schema}"]'


def toc_and_tables(trace, schemas, optional=()):
    """Returns the table of contents' root element and one exported file per schema, with at most EXPORT_WORKERS
    xctrace calls in flight: they overlap a little, and each keeps a temporary store of gigabytes on a big trace.
    A schema in `optional` that the table of contents lacks is left out of the files (xctrace fails on a table that is
    not there). The caller owns the table files; nothing is left behind if a call fails."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=EXPORT_WORKERS) as pool:
        toc_future = pool.submit(toc_of, trace)
        futures = {schema: pool.submit(export, trace, table_xpath(schema), False, EXPORT_TIMEOUTS.get(schema, 600))
                   for schema in schemas}
        concurrent.futures.wait([*futures.values(), toc_future])

    def discard():
        for future in futures.values():
            if future.done() and future.exception() is None and os.path.exists(future.result()):
                os.unlink(future.result())

    try:
        toc = toc_future.result()
        present = {t.attrib.get("schema") for t in toc.iter("table")}
        tables = {}
        for schema, future in futures.items():
            if schema in present or schema not in optional:
                tables[schema] = future.result()
            elif future.exception() is None:
                os.unlink(future.result())  # exported even without its table: keep nothing
        return toc, tables
    except Exception:
        discard()
        raise


REF_CHUNK = 1 << 20  # bytes read at a time by referenced_ids; a test shrinks it
REF_TAIL = 64  # bytes kept between chunks so a ref="..." cut by a boundary is found; far more than an id is long
REF_ATTRIBUTE = re.compile(rb'\bref="([^"]*)"')


def referenced_ids(path):
    """Returns every value that a ref="..." in the file names, found by reading it in chunks. A false positive (the text
    ref="x" inside a cell) only keeps one more id."""
    found, tail = set(), b""
    with open(path, "rb") as f:
        while chunk := f.read(REF_CHUNK):
            data = tail + chunk
            found.update(html.unescape(m.decode("utf-8", "replace")) for m in REF_ATTRIBUTE.findall(data))
            tail = data[-REF_TAIL:]
    return found


def rows(path, sink=None, keep=False):
    """Yields each row of an exported table as {column mnemonic: element}, with xctrace's id/ref values resolved,
    and deletes the file when done or closed early (not with `keep`). Memory follows the values that rows share, not the
    rows: each row is freed after its turn (its elements are valid until the next one) and only the cells that a later ref
    names are kept, found by a first pass over the file. A `sink` (tabledb.TableSink) gets the columns and each row as
    it goes by, so the table is stored without a second read."""
    ids, columns, node, announced = {}, [], None, False
    try:
        referenced = referenced_ids(path)
        for event, el in ET.iterparse(path, events=("start", "end")):
            if event == "start":
                if node is None and el.tag == "node":
                    node = el  # the parent of the rows
                continue
            if "id" in el.attrib and el.attrib["id"] in referenced:
                ids[el.attrib["id"]] = el
            if el.tag == "col":
                columns.append(el.findtext("mnemonic"))
            elif el.tag == "row":
                values = [ids.get(c.attrib["ref"], c) if "ref" in c.attrib else c for c in el]
                row = dict(zip(columns, values))
                if sink is not None:
                    if not announced:
                        sink.columns(columns)
                        announced = True
                    sink.add(row)
                yield row
                el.clear()  # the row only: a cell in ids stays whole, because later rows refer to it
                if node is not None:  # xctrace always wraps the rows in a <node>
                    del node[:]
    except ET.ParseError:
        if not complete_xml(path):  # a file cut at a row boundary by xctrace's crash has every row already
            raise
    finally:
        if sink is not None and not announced:
            sink.columns(columns)  # a table of no rows still has its columns
        if not keep:
            os.unlink(path)


def text(el):
    """Returns an exported cell's formatted value, or "" for a missing cell."""
    return (el.attrib.get("fmt") or el.text or "").strip() if el is not None else ""


def number(el):
    return int(el.text) if el is not None and el.text and el.text.strip().lstrip("-").isdigit() else None


def pid_of(process):
    """Returns the pid of a <process> value, whose <pid> child may itself be a reference."""
    if process is None:
        return None
    pid = process.find("pid")
    return int(pid.attrib.get("fmt") or pid.text) if pid is not None and (pid.text or pid.attrib.get("fmt")) else None


def missing_tables(toc):
    """Returns the optional tables a trace's table of contents lacks; raises ValueError when it lacks the GPU
    intervals every summary needs, as when an Xcode version renames them."""
    schemas = {t.attrib.get("schema") for t in toc.iter("table")}
    if "metal-gpu-intervals" not in schemas:
        raise ValueError("the trace has no metal-gpu-intervals table; this Xcode may name it differently: "
                         "trace_tables lists the tables it has")
    return sorted(({"metal-current-allocated-size", "gpu-performance-state-intervals"} | set(OPTIONAL)) - schemas)


def counter_stats(info_path, value_path, info_sink=None):
    """Returns the GPU counters of a recording as {"samples", "counters": [{name, type, unit, mean, p95, max}], "top_limiter"},
    read from the exported gpu-counter-info and gpu-counter-value files, which it deletes. The value table is read line
    by line: it holds millions of rows whose repeated cells are `ref`s to an earlier `id`, so the tree is never built.
    `top_limiter` is the counter named ... Limiter with the highest mean: the unit the GPU waited on most."""
    info = {}
    for row in rows(info_path, sink=info_sink):
        cid = number(row.get("counter-id"))
        if cid is not None:
            info[cid] = (text(row.get("name")), text(row.get("type")))
    ints, decimals, per, total = {}, array.array("f"), collections.defaultdict(lambda: array.array("f")), 0
    limiters, times, bins = {cid for cid, (name, _) in info.items() if name.endswith("Limiter")}, {}, {}
    try:
        with open(value_path, encoding="utf-8") as f:
            for line in f:
                start = line.find("<row>")  # the first row shares a line with the schema
                if start < 0:
                    continue
                cells = COUNTER_CELL.findall(line, start)
                if len(cells) < 2:
                    continue
                for tag, kind, number_, raw in cells:
                    if kind == "id":
                        if tag == "uint32":
                            if len(raw) < 4:  # a counter id is small; the sample and ring buffer indexes are distinct per row
                                ints[number_] = int(raw)
                        else:
                            index = int(number_)
                            if index >= len(decimals):
                                decimals.extend(array.array("f", [0.0]) * (index + 1 - len(decimals)))
                            decimals[index] = float(raw)
                counter, value = cells[0], cells[1]
                cid = ints.get(counter[2]) if counter[1] == "ref" else int(counter[3])
                number_ = int(value[2])
                per[cid].append(float(value[3]) if value[1] == "id" else decimals[number_])
                total += 1
                stamp = COUNTER_TIME.search(line, start)
                if stamp:
                    if stamp[1] == "id" and (stamp[3] or "").strip().isdigit():
                        times[stamp[2]] = int(stamp[3])
                    when = times.get(stamp[2])
                    if when is not None and cid in limiters:
                        slot = bins.setdefault(when // COUNTER_BIN_NS, {}).setdefault(cid, [0.0, 0])
                        slot[0] += per[cid][-1]
                        slot[1] += 1
    finally:
        os.unlink(value_path)
    counters = []
    for cid, values in sorted(per.items()):
        name, kind = info.get(cid, (f"counter {cid}", ""))
        ordered = sorted(values)
        unit = "%" if kind == "Percentage" else "GB/s" if "Bandwidth" in name else ""
        counters.append({"name": name, "type": kind, "unit": unit, "mean": round(sum(ordered) / len(ordered), 3),
                         "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3), "max": round(ordered[-1], 3)})
    limiters = [c for c in counters if c["name"].endswith("Limiter")]
    top = max(limiters, key=lambda c: c["mean"]) if limiters else None
    series = {"bin_ms": COUNTER_BIN_NS // 1_000_000,
              "bins": {b: {info[cid][0]: slot for cid, slot in by_counter.items()} for b, by_counter in bins.items()}}
    return {"samples": total, "counters": counters, "top_limiter": {"name": top["name"], "mean": top["mean"]} if top else None,
            "_series": series}


VALIDATION_MESSAGE = re.compile(r"^(?:Invalid Metal usage:|-\[MTL.*?\]:\d+: failed assertion)\s*(.*)$")
PATH_TEXT = re.compile(r"/(?:[\w.@+-]+/)+[\w.@+-]*")
VALIDATION_KINDS = 20


def validation_summary(lines):
    """Counts Metal validation messages in a program's output by kind (the message without its offset and function, paths
    replaced by <path>) and returns {"messages", "by_kind" (at most VALIDATION_KINDS, the rest under "other"), "examples" (the
    first full line of up to five kinds)}, or None when there are none. `lines` is read once. The shader validation layer prints
    "Invalid Metal usage: <kind> at offset N, executing compute function: "name"" and the API layer a "-[MTL...]:N: failed
    assertion" line."""
    kinds, examples = collections.Counter(), {}
    for line in lines:
        found = VALIDATION_MESSAGE.match(line.strip())
        if found:
            text = PATH_TEXT.sub("<path>", line.strip())
            kind = re.sub(r" at offset \d+.*$", "", PATH_TEXT.sub("<path>", found[1])).strip()
            kinds[kind] += 1
            if len(examples) < 5:
                examples.setdefault(kind, text)
    if not kinds:
        return None
    top = kinds.most_common(VALIDATION_KINDS)
    by_kind = dict(top)
    if len(kinds) > len(top):
        by_kind["other"] = sum(kinds.values()) - sum(n for _, n in top)
    return {"messages": sum(kinds.values()), "by_kind": by_kind, "examples": list(examples.values())}


# the memory modes a resource allocation's label can name
RESOURCE_MODES = ("Shared", "Private", "Managed", "Memoryless")


def resource_summary(table_rows, pid, frames):
    """Summarizes the Metal resource allocation events of process `pid` from the rows of `metal-resource-allocations`:
    `events` and `mib` allocated (a running total, not memory in use: a drawable's texture each frame counts), `per_frame`, `by_type` (buffer, texture...), `after_3s` (events after the first 3 s of
    the trace, the start-up) and `per_second` counts from second 0. `live` is what was allocated and not freed by the
    end (a lower bound: what was allocated before the recording does not show), by `by_mode` (Shared, Private...,
    "unknown" when the label has none) and `by_type`; `freed` what was allocated here and freed, and
    `freed_before_recording` the deallocations whose allocation is not in the recording. Pairs by resource-id; an empty
    id is ignored and a repeated one replaces the earlier. Other processes are left out; {"events": 0} when there are
    no allocations."""
    events, total, after, after_bytes, by_type, per_second = 0, 0, 0, 0, {}, collections.Counter()
    live, freed, freed_bytes, early = {}, 0, 0, 0  # resource-id -> (mode, type, size)
    for row in table_rows:
        when, size = number(row.get("timestamp")), number(row.get("resource-size")) or 0
        if pid_of(row.get("process")) != pid or when is None:
            continue
        event, rid, kind_name = text(row.get("event-type")), text(row.get("resource-id")), text(row.get("resource-type")) or "other"
        if event == "Deallocation" and rid:
            gone = live.pop(rid, None)
            if gone:
                freed, freed_bytes = freed + 1, freed_bytes + gone[2]
            else:
                early += 1
        if event != "Allocation":
            continue
        if rid:
            label = text(row.get("event-label"))
            live[rid] = (next((m for m in RESOURCE_MODES if m in label), "unknown"), kind_name, size)
        events += 1
        total += size
        kind = by_type.setdefault(kind_name, [0, 0])
        kind[0] += 1
        kind[1] += size
        per_second[when // 1_000_000_000] += 1
        if when >= 3_000_000_000:
            after += 1
            after_bytes += size
    if not events:
        return {"events": 0}
    mib = lambda n: round(n / 2 ** 20, 1)
    groups = {"by_mode": collections.defaultdict(lambda: [0, 0]), "by_type": collections.defaultdict(lambda: [0, 0])}
    for mode, kind_name, size in live.values():
        for group, key in (("by_mode", mode), ("by_type", kind_name)):
            groups[group][key][0] += 1
            groups[group][key][1] += size
    return {"events": events,
            "live": {"count": len(live), "mib": mib(sum(v[2] for v in live.values())),
                     **{g: {k: {"count": v[0], "mib": mib(v[1])} for k, v in sorted(d.items())} for g, d in groups.items()}},
            "freed": {"count": freed, "mib": mib(freed_bytes)}, "freed_before_recording": early, "mib": mib(total), "per_frame": round(events / frames, 2) if frames else None,
            "by_type": {k: {"count": v[0], "mib": mib(v[1])} for k, v in sorted(by_type.items())},
            "after_3s": {"count": after, "mib": mib(after_bytes)},
            "per_second": [per_second[s] for s in range(max(per_second) + 1)]}


def spill_summary(table_rows, pid):
    """Counts the shader register spills of process `pid` from the rows of `graphics-compiler-spill-events`: `events`,
    `bytes` spilled and the distinct `encoders` (rows without an encoder-id are not counted as one). {"events": 0}
    when the program has no row."""
    events, spilled, encoders = 0, 0, set()
    for row in table_rows:
        if pid_of(row.get("process")) != pid:
            continue
        events += 1
        spilled += number(row.get("spilled-bytes")) or 0
        if text(row.get("encoder-id")):
            encoders.add(text(row.get("encoder-id")))
    return {"events": events, "bytes": spilled, "encoders": len(encoders)} if events else {"events": 0}


def command_buffer_errors(error_rows, program_buffers):
    """Returns {"count", "by_code"}: the errors of the program's command buffers in `metal-command-buffer-error`, by
    `error-code` ("unknown" when a row has none). That table has no process column, so a buffer is the program's when
    its `cmdbuffer-id` is in `program_buffers` (those `metal-application-encoders-list` names under the program's pid);
    errors of other or unknown buffers do not count. None when `program_buffers` is None (no encoders table): whose
    errors they are cannot be told."""
    if program_buffers is None:
        return None
    by_code = collections.Counter(text(row.get("error-code")) or "unknown"
                                  for row in error_rows if text(row.get("cmdbuffer-id")) in program_buffers)
    return {"count": sum(by_code.values()), "by_code": dict(by_code.most_common())}


def compiler_summary(intervals, startup_until_ms=None):
    """Returns the graphics compiler's work of the program from its (start, end) intervals in ms: `intervals`, `busy_ms`,
    and `duration_ms` (count, mean, p50, p95, max of one compile) when there is any. With `startup_until_ms` (when the
    10th frame begins), `startup` and `in_flight` split the intervals by their start: compiles in the start-up are
    expected, those in flight can cause a hitch."""
    out = {"intervals": len(intervals), "busy_ms": round(sum(b - a for a, b in intervals), 3)}
    if intervals:
        out["duration_ms"] = metrics.stats([b - a for a, b in intervals])
    if startup_until_ms is not None:
        early = [i for i in intervals if i[0] < startup_until_ms]
        late = [i for i in intervals if i[0] >= startup_until_ms]
        out["startup"] = {"intervals": len(early), "busy_ms": round(sum(b - a for a, b in early), 3)}
        out["in_flight"] = {"intervals": len(late), "busy_ms": round(sum(b - a for a, b in late), 3)}
    return out


def agx_summary(path):
    """Summarizes a recording's `.agx.csv`, one row per second of the GPU driver's counters, which cover the whole GPU
    and not only the recorded program: utilization of the device, renderer and tiler as stats, `split_scenes` (growth of
    SplitSceneCount), `recoveries` (growth of recoveryCount) with `gpu_recovered` true when the GPU recovered during the
    run, and the driver's in-use memory in MiB. A column that is absent or empty gives None. Returns None when the file
    cannot be read and {"samples": 0} when it has no rows."""
    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return None
    if not rows:
        return {"samples": 0}

    def column(name):
        values = []
        for row in rows:
            try:
                values.append(float(row[name]))
            except (KeyError, ValueError, TypeError):
                pass
        return values

    def growth(name):
        values = column(name)
        return int(values[-1] - values[0]) if values else None
    recoveries = growth("recovery_count")
    times = column("time_s")
    span = times[-1] - times[0] if len(times) > 1 else 0

    def per_minute(count):
        return round(count / span * 60, 3) if count is not None and span > 0 else None
    splits = growth("split_scenes")
    return {"samples": len(rows),
            **{key: (stats(column(name)) if column(name) else None)
               for key, name in (("device_pct", "device_pct"), ("renderer_pct", "renderer_pct"),
                                 ("tiler_pct", "tiler_pct"), ("in_use_mib", "in_use_mib"))},
            "split_scenes": splits, "split_scenes_per_min": per_minute(splits),
            "recoveries": recoveries, "recoveries_per_min": per_minute(recoveries),
            "gpu_recovered": None if recoveries is None else recoveries > 0}


def summarize(trace, label=None, out=None, memory=True, counters=None, tables_db=True):
    """Summarizes `trace`, writes the JSON and CSV files into `out` (default: beside it) and returns the summary.
    With `memory` false the Metal memory table, the slowest to read, is skipped: no metal_memory_mib and no CSV.
    With `counters` true, or None when PERF_INSTRUMENTS names Metal GPU Counters, the counter tables are read too
    (`gpu_counters`): minutes more on a long recording. With `tables_db` (the default) every table it reads is also stored,
    cleaned of home folders, in `<label>.tables.sqlite` (tabledb) before the exports are deleted."""
    if counters is None:
        counters = "Metal GPU Counters" in os.environ.get("PERF_INSTRUMENTS", "").split(";")
    trace = pathlib.Path(trace)
    label = label or trace.stem
    out = pathlib.Path(out) if out else trace.parent
    out.mkdir(parents=True, exist_ok=True)

    schemas = [t for t in TABLES if memory or t != MEMORY]
    extra = COUNTER_TABLES if counters else ()
    toc, tables = toc_and_tables(trace, tuple(schemas) + OPTIONAL + extra, optional=OPTIONAL + extra)
    writer = tabledb.Writer(out / f"{label}{tabledb.SUFFIX}") if tables_db else None
    stored = None

    def read(schema):
        return rows(tables[schema], sink=writer.table(schema) if writer is not None else None)

    try:
        launched = next((p for p in toc.iter("process") if p.attrib.get("type") in ("launched", "attached")), None)
        if launched is None:
            raise ValueError("the trace has no launched or attached process; record it with xctrace --launch or --attach")
        pid = int(launched.attrib["pid"])
        summary = {
            "schema_version": metrics.SCHEMA_VERSION,
            "label": label,
            "trace": trace.name,
            "process": {k: launched.attrib.get(k) for k in ("name", "pid", "termination-reason")}
                       | {"arguments": public_arguments(launched.attrib.get("arguments"))},
            # the machine's name and UUID stay out: these summaries are meant to be shared
            "device": {
                k: v
                for k, v in (toc.find(".//device").attrib.items() if toc.find(".//device") is not None else [])
                if k in ("platform", "model", "memory-size", "os-version")
            },
            "template": toc.findtext(".//template-name"),
            "duration_s": float(toc.findtext(".//summary/duration") or 0),
            "machine": machine_info({k: v for k, v in (toc.find(".//device").attrib.items()
                                                       if toc.find(".//device") is not None else [])}),
            # their numbers come out empty
            "missing_tables": missing_tables(toc),
        }

        # GPU work of the launched process, per frame and per channel (vertex, fragment, compute)
        frames = collections.defaultdict(lambda: collections.defaultdict(float))
        first_start = {}
        intervals = 0
        spans = []
        latency_frames, latency_ns = array.array("q"), array.array("q")  # start-latency of each row that has one
        by_process, own_ns = collections.Counter(), 0  # GPU ns of every other process, by pid, and of the program
        for row in read("metal-gpu-intervals"):
            if pid_of(row.get("process")) != pid:
                other_pid, other = pid_of(row.get("process")), number(row.get("duration"))
                if other_pid is not None and other and other > 0:
                    by_process[other_pid] += other
                continue
            own_ns += number(row.get("duration")) or 0
            frame, start, duration = number(row.get("frame-number")), number(row.get("start")), number(row.get("duration"))
            if frame is None or duration is None:
                continue
            channel = (row.get("channel-name").text or "?").strip() if row.get("channel-name") is not None else "?"
            frames[frame][channel] += duration / 1e6
            latency = number(row.get("start-latency"))
            if latency is not None and 0 <= latency < 2**62 and abs(frame) < 2**62:  # a sentinel is not a latency
                latency_frames.append(frame)
                latency_ns.append(latency)
            first_start[frame] = min(first_start.get(frame, start), start)
            intervals += 1
            if start is not None:
                spans.append((frame, start, duration, text(row.get("encoder-id")), text(row.get("cmdbuffer-id"))))

        # work the program never presented is not a frame: it is left out and reported in gpu.unpresented
        stalled = unpresented(spans)
        kept = presented(spans, stalled)
        if stalled:
            intervals -= len(spans) - len(kept["spans"])
            for frame in stalled["frames"]:
                del frames[frame], first_start[frame]

        ordered = sorted(frames)
        channels = sorted({c for f in frames.values() for c in f})
        totals = [sum(frames[f].values()) for f in ordered]
        starts = [first_start[f] / 1e6 for f in ordered]
        gaps = kept["gaps"]
        left_out = set(stalled["frames"]) if stalled else set()
        summary["gpu"] = {
            "intervals": intervals,
            "frames": len(ordered),
            "frame_gpu_ms": stats(totals),
            "per_channel_ms": {c: stats([frames[f].get(c, 0.0) for f in ordered]) for c in channels},
            "frame_interval_ms": stats(gaps),
            # how long the GPU takes to start work once it is sent; the whole run, as frames.csv does not keep it
            "start_latency_ms": stats([ns / 1e6 for f, ns in zip(latency_frames, latency_ns)
                                       if f not in left_out]),
            "fps_estimate": round(1000 / statistics.median(gaps), 1) if gaps else None,
        }
        if stalled:
            summary["gpu"]["unpresented"] = stalled

        # how the work splits into encoders, and when the GPU waits for it
        labels, program_buffers = {}, None  # the table is read once: its file is deleted as it is read
        if "metal-application-encoders-list" in tables:
            program_buffers = set()
            for row in read("metal-application-encoders-list"):
                labels[text(row.get("encoder-id"))] = text(row.get("encoder-label-indexed"))
                if pid_of(row.get("process")) == pid:
                    program_buffers.add(text(row.get("cmdbuffer-id")))
            program_buffers -= {None, ""}
        summary["encoders"] = encoder_stats(kept["spans"], labels)
        summary["gpu_idle"] = kept["idle"]

        # Metal memory the launched process holds over time
        allocated = []
        if memory:
            for row in read(MEMORY):
                size, start = number(row.get("current-allocated-size")), number(row.get("start"))
                if pid_of(row.get("process")) == pid and size is not None and start is not None:
                    allocated.append((start / 1e6, size))
            allocated.sort()
            mib = [size / 2**20 for _, size in allocated]
            summary["metal_memory_mib"] = (
                {"samples": len(mib), "peak": round(max(mib), 2), "final": round(mib[-1], 2), "mean": round(statistics.fmean(mib), 2),
                 "trend_mib_per_min": memory_trend(allocated)}
                if mib else {"samples": 0}
            )
            table_files.write(out, f"{label}.metal_memory", ["time_ms", "metal_allocated_bytes"],
                              ((round(t, 3), size) for t, size in allocated))

        # the process's resident memory, sampled by perf_record.sh beside the trace
        rss_csv = trace.with_suffix(".rss.csv")
        if rss_csv.exists():
            with open(rss_csv) as f:
                rss = [int(r["rss_kib"]) / 1024 for r in csv.DictReader(f) if r["rss_kib"].isdigit()]
            summary["process_rss_mib"] = stats(rss) if rss else {"count": 0}
        activity = agx_summary(trace.with_suffix(".agx.csv"))
        if activity:
            summary["gpu_activity"] = activity
        noisy = noisy_environment(activity, summary.get("gpu_idle"))
        if noisy:
            summary["noisy_environment"] = noisy["flag"]
            if noisy["flag"]:
                summary["noisy_basis"] = {k: noisy[k] for k in ("gpu_device_pct_mean", "process_busy_pct", "external_pct")}
                summary["noisy_basis"]["other_processes"] = other_processes(by_process, own_ns)

        # the GPU's clock states over the recording, as a share of time
        states = collections.Counter()
        for row in read("gpu-performance-state-intervals"):
            state, duration = row.get("gpu-performance-state"), number(row.get("duration"))
            if state is not None and duration:
                states[(state.attrib.get("fmt") or state.text or "?").strip()] += duration
        total_state = sum(states.values())
        summary["gpu_performance_state_share"] = {k: round(v / total_state, 3) for k, v in states.most_common()} if total_state else {}

        # the graphics compiler's activity for the process and the device's thermal state, in ms
        compiler, thermal, thermal_time = [], [], collections.Counter()
        if "graphics-compiler-activity-intervals" in tables:
            for row in read("graphics-compiler-activity-intervals"):
                start, duration = number(row.get("start")), number(row.get("duration"))
                if pid_of(row.get("process")) == pid and start is not None and duration is not None:
                    compiler.append((start / 1e6, (start + duration) / 1e6))
            frame_starts = sorted(first_start.values())
            summary["graphics_compiler"] = compiler_summary(
                compiler, frame_starts[9] / 1e6 if len(frame_starts) > 9 else None)
        if "device-thermal-state-intervals" in tables:
            for row in read("device-thermal-state-intervals"):
                start, duration, state = number(row.get("start")), number(row.get("duration")), text(row.get("thermal-state"))
                if start is not None and duration:
                    thermal_time[state] += duration
                    if state != "Nominal":
                        thermal.append((start / 1e6, (start + duration) / 1e6))
            total_thermal = sum(thermal_time.values())
            summary["thermal_state_share"] = {k: round(v / total_thermal, 3) for k, v in thermal_time.most_common()}
        cpu = []
        if "ProcessCPUUsage" in tables:
            for row in read("ProcessCPUUsage"):
                start, pct = number(row.get("start")), text(row.get("cpu-usage")).rstrip("%")
                if pid_of(row.get("process")) == pid and start is not None and pct.replace(".", "", 1).isdigit():
                    cpu.append((start / 1e6, float(pct)))
            if cpu:
                summary["cpu"] = stats([pct for _, pct in cpu])
        if "metal-resource-allocations" in tables:
            allocations = resource_summary(read("metal-resource-allocations"), pid, len(frames))
            if allocations["events"]:
                summary["resource_allocations"] = allocations
        if "graphics-compiler-spill-events" in tables:
            summary["shader_spills"] = spill_summary(read("graphics-compiler-spill-events"), pid)
        if "metal-command-buffer-error" in tables:
            errors = list(read("metal-command-buffer-error"))
            mine = command_buffer_errors(errors, program_buffers)
            if mine is None:  # no encoders table: every process's errors, said in `command_buffer_errors_scope`
                summary["command_buffer_errors"], summary["command_buffer_errors_scope"] = len(errors), "all_processes"
            else:  # scope "program" (summaries without this key counted every process)
                summary["command_buffer_errors"], summary["command_buffer_errors_scope"] = mine["count"], "program"
                if mine["by_code"]:
                    summary["command_buffer_error_codes"] = mine["by_code"]
        log = out / f"{label}.validation.log"
        if log.is_file():
            with log.open(errors="replace") as handle:
                found = validation_summary(handle)
            summary["validation"] = found or {"messages": 0}
        counter_series = None
        if all(schema in tables for schema in COUNTER_TABLES):
            # the tables file keeps gpu-counter-info only: the samples are millions of rows (229 MB of a 233 MB file for 6 s,
            # the .trace was 90 MB) and the summary already holds each counter's mean, p95 and max
            found = counter_stats(tables[COUNTER_TABLES[0]], tables[COUNTER_TABLES[1]],
                                  writer.table(COUNTER_TABLES[0]) if writer is not None else None)
            counter_series = found.pop("_series")
            if found["samples"]:
                summary["gpu_counters"] = found
        pacing = frame_pacing(gaps, totals)
        if "thermal_state_share" in summary and "throttling_analysis" in pacing:
            pacing["throttling_analysis"]["thermal_throttling_detected"] = bool(thermal)
        summary["gpu"].update(pacing)
        summary["hitches"] = attribute_hitches(ordered, starts, totals, sorted(compiler), sorted(thermal), allocated, cpu=sorted(cpu))
        if counter_series and counter_series["bins"]:
            attach_limiters(summary["hitches"]["worst"], counter_series)
        if writer is not None:
            stored = writer.commit()
            if not stored:
                print(f"{label}{tabledb.SUFFIX} was not written ({writer.failed}); the summary is complete", file=sys.stderr)
    finally:
        if writer is not None and stored is None:
            writer.abort()
        # rows() deletes each table's file once read; one left unread by a failure is removed here
        for path in tables.values():
            if os.path.exists(path):
                os.unlink(path)

    table_files.write(
        out, f"{label}.frames", ["frame", "start_ms"] + [f"gpu_ms_{c.lower()}" for c in channels] + ["gpu_ms_total"],
        ([frame, round(start, 3)] + [round(frames[frame].get(c, 0.0), 4) for c in channels] + [round(total, 4)]
         for frame, start, total in zip(ordered, starts, totals)))
    summary["common"] = metrics.common_block(summary)
    (out / f"{label}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trace", type=pathlib.Path)
    parser.add_argument("--label", help="name of the output files; defaults to the trace's name")
    parser.add_argument("--out", type=pathlib.Path, help="output directory; defaults to the trace's directory")
    parser.add_argument("--no-memory", action="store_true", help="skip the Metal memory table, the slowest to read")
    parser.add_argument("--no-tables", action="store_true", help="do not store the tables in <label>.tables.sqlite")
    parser.add_argument("--counters", action="store_true", help="read the GPU counter tables of a trace recorded with PERF_INSTRUMENTS='Metal GPU Counters'")
    args = parser.parse_args()
    try:
        summary = summarize(args.trace, args.label, args.out, memory=not args.no_memory, counters=True if args.counters else None,
                            tables_db=not args.no_tables)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        sys.exit(str(error))
    print(json.dumps({k: summary.get(k) for k in ("gpu", "metal_memory_mib", "process_rss_mib")}, indent=2))


if __name__ == "__main__":
    main()
