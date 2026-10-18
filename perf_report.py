"""Summarizes an Instruments "Metal System Trace" recording of one launched program: GPU time per frame and memory.

Usage: python3 -I perf_report.py <recording.trace> [--label NAME] [--out DIR]
Writes <out>/<label>.json (summary), <label>.frames.csv (one row per GPU frame) and <label>.metal_memory.csv (Metal
memory over time). A <recording>.rss.csv beside the trace adds the process's resident memory.
"""
import argparse
import collections
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
        return out.name  # xctrace 27.1 writes some tables whole and then dies with SIGTRAP (exit 133)
    if proc.returncode:
        os.unlink(out.name)
        reason = (proc.stderr.strip().splitlines() or ["no message"])[-1]
        raise RuntimeError(f"xctrace export of {pathlib.Path(trace).name} failed (exit {proc.returncode}): {reason}")
    return out.name


def complete_xml(path):
    """Returns whether the file ends with the export's closing tag or at a row boundary, so a crash after writing
    the rows loses nothing."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 64))
            tail = f.read().rstrip()
        return tail.endswith((b"</trace-query-result>", b"</trace-toc>", b"</row>"))
    except OSError:
        return False


def toc_of(trace):
    """Returns the root element of the trace's table of contents."""
    path = export(trace, toc=True)
    try:
        return ET.parse(path).getroot()
    finally:
        os.unlink(path)


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
    return sorted({"metal-current-allocated-size", "gpu-performance-state-intervals",
                   "metal-application-encoders-list"} - schemas)


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


def summarize(trace, label=None, out=None):
    """Summarizes `trace`, writes the JSON and CSV files into `out` (default: beside it) and returns the summary."""
    trace = pathlib.Path(trace)
    label = label or trace.stem
    out = pathlib.Path(out) if out else trace.parent
    out.mkdir(parents=True, exist_ok=True)

    toc = toc_of(trace)
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
        # their numbers come out empty
        "missing_tables": missing_tables(toc),
    }

    # GPU work of the launched process, per frame and per channel (vertex, fragment, compute)
    frames = collections.defaultdict(lambda: collections.defaultdict(float))
    first_start = {}
    intervals = 0
    spans = []
    for row in rows(export(trace, xpath='/trace-toc/run[@number="1"]/data/table[@schema="metal-gpu-intervals"]')):
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
    if "metal-application-encoders-list" not in summary["missing_tables"]:
        xpath = '/trace-toc/run[@number="1"]/data/table[@schema="metal-application-encoders-list"]'
        labels = {text(row.get("encoder-id")): text(row.get("encoder-label-indexed"))
                  for row in rows(export(trace, xpath=xpath))}
    summary["encoders"] = encoder_stats(spans, labels)
    summary["gpu_idle"] = idle_gaps(spans)

    # Metal memory the launched process holds over time
    allocated = []
    for row in rows(export(trace, xpath='/trace-toc/run[@number="1"]/data/table[@schema="metal-current-allocated-size"]')):
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

    # the GPU's clock states over the recording, as a share of time
    states = collections.Counter()
    for row in rows(export(trace, xpath='/trace-toc/run[@number="1"]/data/table[@schema="gpu-performance-state-intervals"]')):
        state, duration = row.get("gpu-performance-state"), number(row.get("duration"))
        if state is not None and duration:
            states[(state.attrib.get("fmt") or state.text or "?").strip()] += duration
    total_state = sum(states.values())
    summary["gpu_performance_state_share"] = {k: round(v / total_state, 3) for k, v in states.most_common()} if total_state else {}

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
    args = parser.parse_args()
    try:
        summary = summarize(args.trace, args.label, args.out)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        sys.exit(str(error))
    print(json.dumps({k: summary.get(k) for k in ("gpu", "metal_memory_mib", "process_rss_mib")}, indent=2))


if __name__ == "__main__":
    main()
