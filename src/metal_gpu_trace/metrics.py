"""The numbers Mac (perf_report) and Windows (perf_record_windows) summaries share, in one copy so their schema
stays the same: statistics, encoder and idle-gap figures, label grouping and shareable command lines."""
import collections
import pathlib
import re
import statistics

# encoder GPU times, in µs, whose share of all encoders each summary keeps
SHORT_US = (10, 25, 50, 100, 250, 500, 1000)


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


def public_arguments(arguments):
    """Returns a command line with each absolute path cut to its file name, so summaries can be shared: POSIX paths
    and Windows drive paths (C:\\… or C:/…, as a Wine program gets them), on every platform."""
    def clean(arg):
        if arg.startswith("/"):
            return pathlib.PurePosixPath(arg).name
        if re.match(r"^[a-zA-Z]:[\\/]", arg):
            return pathlib.PureWindowsPath(arg).name
        return arg
    return " ".join(clean(a) for a in (arguments or "").split())
