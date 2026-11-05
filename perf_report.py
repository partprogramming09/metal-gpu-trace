"""Summarizes an Instruments "Metal System Trace" recording of one launched program: GPU time per frame and memory.

Usage: python3 -I perf_report.py <recording.trace> [--label NAME] [--out DIR] [--no-memory]
Writes <out>/<label>.json (summary), <label>.frames.csv (one row per GPU frame) and <label>.metal_memory.csv (Metal
memory over time). A <recording>.rss.csv beside the trace adds the process's resident memory.
"""
import argparse
import array
import collections
import concurrent.futures
import csv
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

# the tables a summary reads, one xpath each (a multi-table xpath keeps the first table's columns only)
MEMORY = "metal-current-allocated-size"
TABLES = ("metal-gpu-intervals", MEMORY, "gpu-performance-state-intervals")
# read only when the trace has it: without it encoders go without labels
OPTIONAL = ("metal-application-encoders-list", "graphics-compiler-activity-intervals", "device-thermal-state-intervals",
            "ProcessCPUUsage")
# each xctrace export keeps a temporary store of gigabytes on a big trace: two at a time bound the disk it needs
EXPORT_WORKERS = 2
# Metal GPU Counters (PERF_INSTRUMENTS): about 450 000 samples and 64 MB of XML per recorded second, so its export may take minutes
COUNTER_TABLES = ("gpu-counter-info", "gpu-counter-value")
EXPORT_TIMEOUTS = {"gpu-counter-value": 3600}
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


def rows(path):
    """Yields each row of an exported table as {column mnemonic: element}, with xctrace's id/ref values resolved,
    and deletes the file when done or closed early."""
    ids, columns = {}, []
    try:
        for _, el in ET.iterparse(path, events=("end",)):
            if "id" in el.attrib:
                ids[el.attrib["id"]] = el
            if el.tag == "col":
                columns.append(el.findtext("mnemonic"))
            elif el.tag == "row":
                values = [ids.get(c.attrib["ref"], c) if "ref" in c.attrib else c for c in el]
                yield dict(zip(columns, values))
    except ET.ParseError:
        if not complete_xml(path):  # a file cut at a row boundary by xctrace's crash has every row already
            raise
    finally:
        os.unlink(path)


def public_arguments(arguments):
    """Returns a command line with each absolute path cut to its file name, so summaries can be shared."""
    return " ".join(pathlib.Path(a).name if a.startswith("/") else a for a in (arguments or "").split())


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


def stats(values):
    """Returns count, mean, median, 95th percentile and maximum of `values`, rounded to microseconds when in ms."""
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": round(statistics.fmean(ordered), 3),
        "p50": round(ordered[len(ordered) // 2], 3),
        "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "max": round(ordered[-1], 3),
    }


def missing_tables(toc):
    """Returns the optional tables a trace's table of contents lacks; raises ValueError when it lacks the GPU
    intervals every summary needs, as when an Xcode version renames them."""
    schemas = {t.attrib.get("schema") for t in toc.iter("table")}
    if "metal-gpu-intervals" not in schemas:
        raise ValueError("the trace has no metal-gpu-intervals table; this Xcode may name it differently: "
                         "trace_tables lists the tables it has")
    return sorted(({"metal-current-allocated-size", "gpu-performance-state-intervals"} | set(OPTIONAL)) - schemas)


# a frame is a stutter or hitch only when it is also this much longer than the median interval: at 500 FPS a 3 ms frame
# is scheduler noise, not a stutter
STUTTER_FLOOR_MS = 8.0

# encoder GPU times, in µs, whose share of all encoders each summary keeps
SHORT_US = (10, 25, 50, 100, 250, 500, 1000)


def label_name(label):
    """Returns an encoder label without Instruments' "[n] " prefix and trailing index, so the same pass groups."""
    return re.sub(r" \d+$", "", re.sub(r"^\[\d+\] ", "", label)) or "?"


def encoder_stats(spans, labels):
    """Returns encoders and command buffers per frame, each encoder's GPU time, the share of encoders shorter than
    each of SHORT_US and the 20 labels with the most GPU time. `spans` holds (frame, start ns, duration ns, encoder
    id, command buffer id) and `labels` maps an encoder id to its label."""
    encoders, buffers, busy = collections.defaultdict(set), collections.defaultdict(set), collections.Counter()
    for frame, _, duration, encoder, buffer in spans:
        if encoder:
            encoders[frame].add(encoder)
            busy[encoder] += duration
        if buffer:
            buffers[frame].add(buffer)
    us = [ns / 1000 for ns in busy.values()]
    grouped = collections.defaultdict(list)
    for encoder, ns in busy.items():
        grouped[label_name(labels.get(encoder, ""))].append(ns / 1000)
    frames = len({s[0] for s in spans}) or 1
    top = sorted(grouped.items(), key=lambda kv: -sum(kv[1]))[:20]
    return {
        "per_frame": stats([len(e) for e in encoders.values()]),
        "command_buffers_per_frame": stats([len(b) for b in buffers.values()]),
        "encoder_us": stats(us),
        "short_share": {str(cut): round(sum(u < cut for u in us) / len(us), 3) for cut in SHORT_US} if us else {},
        "by_label": [{"label": name, "per_frame": round(len(v) / frames, 2), "total_ms": round(sum(v) / 1000, 3),
                      "mean_us": round(statistics.fmean(v), 1), "stdev_us": round(statistics.pstdev(v), 1)}
                     for name, v in top],
    }


def idle_gaps(spans):
    """Returns the time the GPU ran none of the process's work between its first and last interval: per frame (each
    gap counts in the frame of the work that ends it), gaps over 1 ms and share of the whole span. `spans` as in
    encoder_stats."""
    ordered = sorted((start, start + duration, frame) for frame, start, duration, _, _ in spans)
    if not ordered:
        return {"idle_ms_per_frame": {"count": 0}}
    idle, gaps, end = collections.Counter({frame: 0 for _, _, frame in ordered}), [], ordered[0][1]
    for start, stop, frame in ordered[1:]:
        if start > end:
            gaps.append((start - end) / 1e6)
            idle[frame] += (start - end) / 1e6
        end = max(end, stop)
    whole = (end - ordered[0][0]) / 1e6
    return {"idle_ms_per_frame": stats(list(idle.values())), "gaps_over_1ms": sum(g > 1 for g in gaps),
            "idle_share": round(sum(gaps) / whole, 3) if whole else None}


def frame_pacing(gaps, totals):
    """Returns the 1% and 0.1% low FPS, the share of frames longer than 1.5 median intervals and than STUTTER_FLOOR_MS
    (stutter), the interval
    jitter and whether FPS fell over the recording while GPU time rose. `gaps` are frame intervals and `totals` GPU
    times per frame, both in ms; a low needs 100 (1%) or 1000 (0.1%) frames behind it."""
    if not gaps:
        return {}
    med, ordered = statistics.median(gaps), sorted(gaps)

    def low(share, frames):
        worst = ordered[min(len(ordered) - 1, int(len(ordered) * share))]
        return round(1000 / worst, 1) if worst > 0 and len(gaps) >= frames else None

    out = {"fps_1pct_low": low(0.99, 100), "fps_01pct_low": low(0.999, 1000)}
    if len(gaps) > 1:
        out["stutter_rate_pct"] = round(sum(g > max(1.5 * med, STUTTER_FLOOR_MS) for g in gaps) / len(gaps) * 100, 2) if med > 0 else 0.0
        out["frame_jitter_ms"] = round(statistics.pstdev(gaps), 3)
    if len(gaps) >= 5:
        k = max(1, int(len(gaps) * 0.2))
        first, last = statistics.median(gaps[:k]), statistics.median(gaps[-k:])
        fps_first = round(1000 / first, 1) if first > 0 else None
        fps_last = round(1000 / last, 1) if last > 0 else None
        out["throttling_analysis"] = {
            "thermal_throttling_detected": bool(fps_first and fps_last and (fps_first - fps_last) / fps_first * 100 > 10
                                                and statistics.mean(totals[-k:]) > statistics.mean(totals[:k])) if totals else None,
            "fps_initial": fps_first, "fps_final": fps_last,
            "fps_drift_pct": round((fps_first - fps_last) / fps_first * 100, 1) if fps_first and fps_last else 0.0}
    return out


def attribute_hitches(frames, starts, totals, compiler, thermal, memory, growth_mib=8, cpu=()):
    """Names a cause for each frame whose interval exceeds 1.5 median intervals and STUTTER_FLOOR_MS, by what the trace shows in the
    interval before it: the graphics compiler running (shader_compile), a thermal state other than Nominal (thermal),
    Metal memory growing by `growth_mib` or more (memory_growth), the GPU busy for 80% of it (gpu_heavy) or none of
    these (cpu_or_wait). `frames`, `starts` (ms) and `totals` (GPU ms) go in frame order; `compiler` and `thermal`
    hold (start ms, end ms) spans and `memory` (ms, bytes) samples, sorted. `cpu` holds (ms, percent) samples of the
    process's CPU use; each hitch then carries `cpu_pct`, their mean over the interval before it (None with no sample):
    high means the program was busy, low that it waited. The 20 longest hitches are listed."""
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    if not gaps:
        return {"count": 0, "causes": {}, "worst": []}
    limit, causes, found = max(1.5 * statistics.median(gaps), STUTTER_FLOOR_MS), collections.Counter(), []
    for i, gap in enumerate(gaps, 1):
        if gap <= limit:
            continue
        lo, hi = starts[i - 1], starts[i]
        before = [size for t, size in memory if t <= lo][-1:] or [None]
        after = [size for t, size in memory if t <= hi][-1:] or [None]
        if any(a < hi and b > lo for a, b in compiler):
            cause = "shader_compile"
        elif any(a < hi and b > lo for a, b in thermal):
            cause = "thermal"
        elif None not in (before[0], after[0]) and after[0] - before[0] >= growth_mib * 2**20:
            cause = "memory_growth"
        elif totals[i - 1] >= 0.8 * gap:
            cause = "gpu_heavy"
        else:
            cause = "cpu_or_wait"
        causes[cause] += 1
        entry = {"frame": frames[i], "interval_ms": round(gap, 3), "cause": cause}
        if cpu:
            inside = [pct for t, pct in cpu if lo < t <= hi]
            entry["cpu_pct"] = round(statistics.fmean(inside), 1) if inside else None
        found.append(entry)
    return {"count": len(found), "threshold_ms": round(limit, 3), "causes": dict(causes.most_common()),
            "worst": sorted(found, key=lambda h: -h["interval_ms"])[:20]}


def counter_stats(info_path, value_path):
    """Returns the GPU counters of a recording as {"samples", "counters": [{name, type, unit, mean, p95, max}], "top_limiter"},
    read from the exported gpu-counter-info and gpu-counter-value files, which it deletes. The value table is read line
    by line: it holds millions of rows whose repeated cells are `ref`s to an earlier `id`, so the tree is never built.
    `top_limiter` is the counter named ... Limiter with the highest mean: the unit the GPU waited on most."""
    info = {}
    for row in rows(info_path):
        cid = number(row.get("counter-id"))
        if cid is not None:
            info[cid] = (text(row.get("name")), text(row.get("type")))
    ints, decimals, per, total = {}, array.array("f"), collections.defaultdict(lambda: array.array("f")), 0
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
    return {"samples": total, "counters": counters, "top_limiter": {"name": top["name"], "mean": top["mean"]} if top else None}


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
    return {"samples": len(rows),
            **{key: (stats(column(name)) if column(name) else None)
               for key, name in (("device_pct", "device_pct"), ("renderer_pct", "renderer_pct"),
                                 ("tiler_pct", "tiler_pct"), ("in_use_mib", "in_use_mib"))},
            "split_scenes": growth("split_scenes"), "recoveries": recoveries,
            "gpu_recovered": None if recoveries is None else recoveries > 0}


def read_command(argv):
    """Returns the standard output of one short system command."""
    return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=10).stdout


def machine_info(device, read=read_command):
    """Returns the chip, CPU and GPU core counts, RAM, macOS and whether the screen is locked (a locked session may leave
    windows unpaced by the display) of this Mac, with no name or UUID, or None when its RAM
    or macOS differ from the trace's `device` (it is not the machine that recorded it) or a fact cannot be read."""
    try:
        sysctl = lambda key: read(("sysctl", "-n", key)).strip()
        gpu = read(("ioreg", "-c", "AGXAccelerator", "-r", "-d", "1"))
        ram, macos = int(sysctl("hw.memsize")), read(("sw_vers", "-productVersion")).strip()
        try:
            locked = "CGSSessionScreenIsLocked" in read(("ioreg", "-n", "Root", "-d1", "-a"))
        except (KeyError, OSError, subprocess.SubprocessError):
            locked = None
        if str(ram) != device.get("memory-size") or macos != (device.get("os-version") or "").split(" ")[0]:
            return None
        return {"chip": sysctl("machdep.cpu.brand_string"), "cpu_cores_p": int(sysctl("hw.perflevel0.logicalcpu")),
                "cpu_cores_e": int(sysctl("hw.perflevel1.logicalcpu")),
                "gpu_cores": int(re.search(r'"gpu-core-count" = (\d+)', gpu).group(1)),
                "gpu_class": re.search(r'"IOClass" = "(AGX\w+)"', gpu).group(1), "ram_gib": ram // 2 ** 30, "macos": macos,
                "screen_locked": locked}
    except (KeyError, ValueError, AttributeError, OSError, subprocess.SubprocessError):
        return None


def summarize(trace, label=None, out=None, memory=True, counters=None):
    """Summarizes `trace`, writes the JSON and CSV files into `out` (default: beside it) and returns the summary.
    With `memory` false the Metal memory table, the slowest to read, is skipped: no metal_memory_mib and no CSV.
    With `counters` true, or None when PERF_INSTRUMENTS names Metal GPU Counters, the counter tables are read too
    (`gpu_counters`): minutes more on a long recording."""
    if counters is None:
        counters = "Metal GPU Counters" in os.environ.get("PERF_INSTRUMENTS", "").split(";")
    trace = pathlib.Path(trace)
    label = label or trace.stem
    out = pathlib.Path(out) if out else trace.parent
    out.mkdir(parents=True, exist_ok=True)

    schemas = [t for t in TABLES if memory or t != MEMORY]
    extra = COUNTER_TABLES if counters else ()
    toc, tables = toc_and_tables(trace, tuple(schemas) + OPTIONAL + extra, optional=OPTIONAL + extra)
    try:
        launched = next((p for p in toc.iter("process") if p.attrib.get("type") in ("launched", "attached")), None)
        if launched is None:
            raise ValueError("the trace has no launched or attached process; record it with xctrace --launch or --attach")
        pid = int(launched.attrib["pid"])
        summary = {
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
        for row in rows(tables["metal-gpu-intervals"]):
            if pid_of(row.get("process")) != pid:
                continue
            frame, start, duration = number(row.get("frame-number")), number(row.get("start")), number(row.get("duration"))
            if frame is None or duration is None:
                continue
            channel = (row.get("channel-name").text or "?").strip() if row.get("channel-name") is not None else "?"
            frames[frame][channel] += duration / 1e6
            first_start[frame] = min(first_start.get(frame, start), start)
            intervals += 1
            if start is not None:
                spans.append((frame, start, duration, text(row.get("encoder-id")), text(row.get("cmdbuffer-id"))))

        ordered = sorted(frames)
        channels = sorted({c for f in frames.values() for c in f})
        totals = [sum(frames[f].values()) for f in ordered]
        starts = [first_start[f] / 1e6 for f in ordered]
        gaps = [b - a for a, b in zip(starts, starts[1:]) if b > a]
        summary["gpu"] = {
            "intervals": intervals,
            "frames": len(ordered),
            "frame_gpu_ms": stats(totals),
            "per_channel_ms": {c: stats([frames[f].get(c, 0.0) for f in ordered]) for c in channels},
            "frame_interval_ms": stats(gaps),
            "fps_estimate": round(1000 / statistics.median(gaps), 1) if gaps else None,
        }

        # how the work splits into encoders, and when the GPU waits for it
        labels = {}
        if "metal-application-encoders-list" in tables:
            labels = {text(row.get("encoder-id")): text(row.get("encoder-label-indexed"))
                      for row in rows(tables["metal-application-encoders-list"])}
        summary["encoders"] = encoder_stats(spans, labels)
        summary["gpu_idle"] = idle_gaps(spans)

        # Metal memory the launched process holds over time
        allocated = []
        if memory:
            for row in rows(tables[MEMORY]):
                size, start = number(row.get("current-allocated-size")), number(row.get("start"))
                if pid_of(row.get("process")) == pid and size is not None and start is not None:
                    allocated.append((start / 1e6, size))
            allocated.sort()
            mib = [size / 2**20 for _, size in allocated]
            summary["metal_memory_mib"] = (
                {"samples": len(mib), "peak": round(max(mib), 2), "final": round(mib[-1], 2), "mean": round(statistics.fmean(mib), 2)}
                if mib else {"samples": 0}
            )
            with open(out / f"{label}.metal_memory.csv", "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time_ms", "metal_allocated_bytes"])
                writer.writerows((round(t, 3), size) for t, size in allocated)

        # the process's resident memory, sampled by perf_record.sh beside the trace
        rss_csv = trace.with_suffix(".rss.csv")
        if rss_csv.exists():
            with open(rss_csv) as f:
                rss = [int(r["rss_kib"]) / 1024 for r in csv.DictReader(f) if r["rss_kib"].isdigit()]
            summary["process_rss_mib"] = stats(rss) if rss else {"count": 0}
        activity = agx_summary(trace.with_suffix(".agx.csv"))
        if activity:
            summary["gpu_activity"] = activity

        # the GPU's clock states over the recording, as a share of time
        states = collections.Counter()
        for row in rows(tables["gpu-performance-state-intervals"]):
            state, duration = row.get("gpu-performance-state"), number(row.get("duration"))
            if state is not None and duration:
                states[(state.attrib.get("fmt") or state.text or "?").strip()] += duration
        total_state = sum(states.values())
        summary["gpu_performance_state_share"] = {k: round(v / total_state, 3) for k, v in states.most_common()} if total_state else {}

        # the graphics compiler's activity for the process and the device's thermal state, in ms
        compiler, thermal, thermal_time = [], [], collections.Counter()
        if "graphics-compiler-activity-intervals" in tables:
            for row in rows(tables["graphics-compiler-activity-intervals"]):
                start, duration = number(row.get("start")), number(row.get("duration"))
                if pid_of(row.get("process")) == pid and start is not None and duration is not None:
                    compiler.append((start / 1e6, (start + duration) / 1e6))
            summary["graphics_compiler"] = {"intervals": len(compiler),
                                            "busy_ms": round(sum(b - a for a, b in compiler), 3)}
        if "device-thermal-state-intervals" in tables:
            for row in rows(tables["device-thermal-state-intervals"]):
                start, duration, state = number(row.get("start")), number(row.get("duration")), text(row.get("thermal-state"))
                if start is not None and duration:
                    thermal_time[state] += duration
                    if state != "Nominal":
                        thermal.append((start / 1e6, (start + duration) / 1e6))
            total_thermal = sum(thermal_time.values())
            summary["thermal_state_share"] = {k: round(v / total_thermal, 3) for k, v in thermal_time.most_common()}
        cpu = []
        if "ProcessCPUUsage" in tables:
            for row in rows(tables["ProcessCPUUsage"]):
                start, pct = number(row.get("start")), text(row.get("cpu-usage")).rstrip("%")
                if pid_of(row.get("process")) == pid and start is not None and pct.replace(".", "", 1).isdigit():
                    cpu.append((start / 1e6, float(pct)))
            if cpu:
                summary["cpu"] = stats([pct for _, pct in cpu])
        if all(schema in tables for schema in COUNTER_TABLES):
            found = counter_stats(tables[COUNTER_TABLES[0]], tables[COUNTER_TABLES[1]])
            if found["samples"]:
                summary["gpu_counters"] = found
        pacing = frame_pacing(gaps, totals)
        if "thermal_state_share" in summary and "throttling_analysis" in pacing:
            pacing["throttling_analysis"]["thermal_throttling_detected"] = bool(thermal)
        summary["gpu"].update(pacing)
        summary["hitches"] = attribute_hitches(ordered, starts, totals, sorted(compiler), sorted(thermal), allocated, cpu=sorted(cpu))
    finally:
        # rows() deletes each table's file once read; one left unread by a failure is removed here
        for path in tables.values():
            if os.path.exists(path):
                os.unlink(path)

    with open(out / f"{label}.frames.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "start_ms"] + [f"gpu_ms_{c.lower()}" for c in channels] + ["gpu_ms_total"])
        for frame, start, total in zip(ordered, starts, totals):
            writer.writerow([frame, round(start, 3)] + [round(frames[frame].get(c, 0.0), 4) for c in channels] + [round(total, 4)])
    (out / f"{label}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trace", type=pathlib.Path)
    parser.add_argument("--label", help="name of the output files; defaults to the trace's name")
    parser.add_argument("--out", type=pathlib.Path, help="output directory; defaults to the trace's directory")
    parser.add_argument("--no-memory", action="store_true", help="skip the Metal memory table, the slowest to read")
    parser.add_argument("--counters", action="store_true", help="read the GPU counter tables of a trace recorded with PERF_INSTRUMENTS='Metal GPU Counters'")
    args = parser.parse_args()
    try:
        summary = summarize(args.trace, args.label, args.out, memory=not args.no_memory, counters=True if args.counters else None)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        sys.exit(str(error))
    print(json.dumps({k: summary.get(k) for k in ("gpu", "metal_memory_mib", "process_rss_mib")}, indent=2))


if __name__ == "__main__":
    main()
