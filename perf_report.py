"""Summarizes an Instruments "Metal System Trace" recording of one launched program: GPU time per frame and memory.

Usage: python3 -I tools/perf_report.py <recording.trace> [--label NAME] [--out DIR]
Writes <out>/<label>.json (summary), <label>.frames.csv (one row per GPU frame) and <label>.metal_memory.csv (Metal
memory over time). A <recording>.rss.csv beside the trace adds the process's resident memory.
"""
import argparse
import collections
import csv
import json
import os
import pathlib
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
    if proc.returncode:
        os.unlink(out.name)
        reason = (proc.stderr.strip().splitlines() or ["no message"])[-1]
        raise RuntimeError(f"xctrace export of {pathlib.Path(trace).name} failed (exit {proc.returncode}): {reason}")
    return out.name


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
    finally:
        os.unlink(path)


def public_arguments(arguments):
    """Returns a command line with each absolute path cut to its file name, so summaries can be shared."""
    return " ".join(pathlib.Path(a).name if a.startswith("/") else a for a in (arguments or "").split())


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


def summarize(trace, label=None, out=None):
    """Summarizes `trace`, writes the JSON and CSV files into `out` (default: beside it) and returns the summary."""
    trace = pathlib.Path(trace)
    label = label or trace.stem
    out = pathlib.Path(out) if out else trace.parent
    out.mkdir(parents=True, exist_ok=True)

    toc = toc_of(trace)
    launched = toc.find(".//process[@type='launched']")
    if launched is None:
        raise ValueError("the trace has no launched process; record it with xctrace --launch")
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
    }

    # GPU work of the launched process, per frame and per channel (vertex, fragment, compute)
    frames = collections.defaultdict(lambda: collections.defaultdict(float))
    first_start = {}
    intervals = 0
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
