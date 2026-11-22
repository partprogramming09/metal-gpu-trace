"""Frame pacing of a Metal System Trace summary: unpresented frames, stutters and hitches, the Limiter behind each hitch
and the Metal memory trend. Part of perf_report, which re-exports these names."""
import collections
import statistics

from metal_gpu_trace import metrics

idle_gaps = metrics.idle_gaps  # the same alias perf_report keeps

# a frame number holding this many command buffers, this many times the run's median, over this long was never presented
UNPRESENTED_MIN_BUFFERS = 32
UNPRESENTED_FACTOR = 8
UNPRESENTED_MIN_S = 1.0


def unpresented(spans):
    """Returns the frame numbers that hold work never presented, with when it began, how long it lasted, its command
    buffers and GPU time, or None when every frame presented. Instruments numbers frames by presents, so a program that
    renders without presenting (its window hidden) leaves every later command buffer in its last frame number. spans
    are (frame, start ns, duration ns, encoder id, command buffer id)."""
    buffers, first, last, busy = collections.defaultdict(set), {}, {}, collections.defaultdict(int)
    for frame, start, duration, _, buffer in spans:
        buffers[frame].add(buffer)
        first[frame] = min(first.get(frame, start), start)
        last[frame] = max(last.get(frame, start + duration), start + duration)
        busy[frame] += duration
    if not buffers:
        return None
    usual = statistics.median(len(b) for b in buffers.values())
    stalled = sorted(f for f, b in buffers.items()
                     if len(b) >= max(UNPRESENTED_MIN_BUFFERS, UNPRESENTED_FACTOR * usual)
                     and (last[f] - first[f]) / 1e9 >= UNPRESENTED_MIN_S)
    if not stalled:
        return None
    total = sum(busy.values())
    held = sum(busy[f] for f in stalled)
    return {"frames": stalled, "from_s": round(first[stalled[0]] / 1e9, 3),
            "span_s": round(sum(last[f] - first[f] for f in stalled) / 1e9, 3),
            "command_buffers": sum(len(buffers[f]) for f in stalled), "gpu_ms": round(held / 1e6, 3),
            "share_of_gpu_time": round(held / total, 3) if total else None}


def presented(spans, stall):
    """Returns the spans of presented frames, the GPU's idle time (the unpresented work kept: the GPU ran it, but its
    frame is not counted per frame) and the intervals between presented frames in ms, none across an unpresented
    frame. stall is what unpresented() returned."""
    left_out = set(stall["frames"]) if stall else set()
    first = {}
    for frame, start, _, _, _ in spans:
        if frame not in left_out:
            first[frame] = min(first.get(frame, start), start)
    ordered = sorted(first)
    gaps = [(first[b] - first[a]) / 1e6 for a, b in zip(ordered, ordered[1:])
            if first[b] > first[a] and not any(a < f < b for f in left_out)]
    return {"spans": [s for s in spans if s[0] not in left_out], "idle": idle_gaps(spans, left_out), "gaps": gaps}


# a frame is a stutter or hitch only when it is also this much longer than the median interval: at 500 FPS a 3 ms frame
# is scheduler noise, not a stutter
STUTTER_FLOOR_MS = 8.0


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
        return {"count": 0, "per_minute": None, "causes": {}, "worst": []}
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
        entry = {"frame": frames[i], "interval_ms": round(gap, 3), "cause": cause, "window_ms": [round(lo, 3), round(hi, 3)]}
        if cpu:
            inside = [pct for t, pct in cpu if lo < t <= hi]
            entry["cpu_pct"] = round(statistics.fmean(inside), 1) if inside else None
        found.append(entry)
    minutes = (starts[-1] - starts[0]) / 60000
    return {"count": len(found), "per_minute": round(len(found) / minutes, 2) if minutes > 0 else None,
            "threshold_ms": round(limit, 3), "causes": dict(causes.most_common()),
            "worst": sorted(found, key=lambda h: -h["interval_ms"])[:20]}


def attach_limiters(hitches, series):
    """Sets `top_limiter` on each hitch of a summary's `worst` list: the Limiter that led in its `window_ms`, or None
    when no counter sample falls in it."""
    for hitch in hitches:
        hitch["top_limiter"] = limiter_in(series, *hitch["window_ms"])


def limiter_in(series, lo_ms, hi_ms):
    """Returns the Limiter counter with the highest mean over [lo_ms, hi_ms) in a counter_stats `_series`, as
    {"name", "mean"}, or None when no sample falls in the window. The series holds whole 10 ms bins, so a window is read
    at that resolution: the bins it touches, the one that starts at hi_ms left out."""
    totals, width = {}, series["bin_ms"]
    first = int(lo_ms // width)
    for index in range(first, max(first, int(-(-hi_ms // width)) - 1) + 1):  # the bin that starts at hi_ms is left out
        for name, (total, count) in series["bins"].get(index, {}).items():
            slot = totals.setdefault(name, [0.0, 0])
            slot[0] += total
            slot[1] += count
    if not totals:
        return None
    name, (total, count) = max(totals.items(), key=lambda item: item[1][0] / item[1][1])
    return {"name": name, "mean": round(total / count, 3)}


def memory_trend(allocated):
    """Returns the slope, in MiB per minute, of the least-squares line through the Metal memory samples of the second half of
    the recorded time (`allocated` holds (ms, bytes) sorted by time; a burst of samples while loading does not move the cut):
    what the program keeps growing by once it has warmed up. None with under 5 samples in that half or under 5 s between them."""
    if not allocated:
        return None
    cut = (allocated[0][0] + allocated[-1][0]) / 2
    half = [sample for sample in allocated if sample[0] >= cut]
    if len(half) < 5 or half[-1][0] - half[0][0] < 5000:
        return None
    mx, my = statistics.fmean(t for t, _ in half), statistics.fmean(s for _, s in half)
    sxx = sum((t - mx) ** 2 for t, _ in half)
    return round(sum((t - mx) * (s - my) for t, s in half) / sxx * 60000 / 2**20, 2) if sxx else None
