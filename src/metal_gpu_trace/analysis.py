"""Reading recordings back: runs, compare, baselines, checks, gates, history and diagnosis."""
import collections
import csv
import json
import statistics
import time

from metal_gpu_trace import config, metrics, paths, perf_report, recording


UNPRESENTED_NOTE = ("the program stopped presenting (its window hidden behind another, minimized or off screen, or a "
                    "load of a second or more that presented nothing) and "
                    "Instruments stopped numbering frames: the work from from_s for span_s is left out of the frame numbers, "
                    "which cover only the presented frames; record again with the program's window visible")


def unpresented(**summaries):
    """Returns {"runs": {name: gpu.unpresented}, "note": ...} for the named summaries whose program stopped presenting,
    or None when every one presented throughout."""
    runs = {name: s["gpu"]["unpresented"] for name, s in summaries.items() if (s.get("gpu") or {}).get("unpresented")}
    return {"runs": runs, "note": UNPRESENTED_NOTE} if runs else None


def tool_perf_runs(offset=0, limit=50):
    """Lists the saved recordings, newest first, with frames, FPS, GPU ms per frame, memory peaks and the translation
    layer each ran on (fingerprint and Wine, or native)."""
    runs = []
    for path in sorted(config.OUT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name == config.BASELINES.name:
            continue
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:  # a summary still being written
            continue
        gpu = s.get("gpu", {})
        runs.append({"run": path.stem, "program": (s.get("process") or {}).get("arguments"),
                     "frames": gpu.get("frames"), "fps": gpu.get("fps_estimate"),
                     "gpu_ms_mean": (gpu.get("frame_gpu_ms") or {}).get("mean"),
                     "metal_mib_peak": (s.get("metal_memory_mib") or {}).get("peak"),
                     "rss_mib_max": (s.get("process_rss_mib") or {}).get("max"),
                     "trace_kept": path.with_suffix(".trace").is_dir(), "layer": recording.layer_label(s.get("layer"))})
    return paths.page(runs, offset, limit)


def markdown_report(result):
    """Returns a perf_compare result as Markdown for a PR comment: one table of the headline and encoder numbers
    (a, b, change, change in %), and the five labels whose GPU ms per frame changed most."""
    rows = [(name, c) for group in (result["metrics"], {k: v for k, v in result.get("encoders", {}).items()
                                                        if isinstance(v, dict) and "a" in v}) for name, c in group.items()]
    cell = lambda v: "-" if v is None else str(v)
    lines = [f"**{result['a']}** (a) vs **{result['b']}** (b)", "", "| metric | a | b | change | % |", "|---|---|---|---|---|"]
    lines += [f"| {n} | {cell(c['a'])} | {cell(c['b'])} | {cell(c['change'])} | {cell(c['change_pct'])} |" for n, c in rows]
    labels = [l for l in result.get("labels", []) if l["ms_per_frame_change"]][:5]
    if labels:
        lines += ["", "| label | ms/frame a | ms/frame b | change |", "|---|---|---|---|"]
        lines += [f"| {l['label']} | {cell(l['ms_per_frame_a'])} | {cell(l['ms_per_frame_b'])} | "
                  f"{l['ms_per_frame_change']} |" for l in labels]
    if result.get("measure"):
        lines += ["", f"Not comparable between a Windows and a Metal run: {', '.join(result['measure']['not_comparable'])}."]
    if result["too_short"]:
        lines += ["", f"Too short to compare (under 100 frames): {', '.join(result['too_short'])}."]
    return "\n".join(lines)


def tool_perf_compare(a, b, short_us=25, markdown=False, skip_s=0):
    """Compares two saved recordings (names from perf_runs), a the reference and b the run after a change: the
    headline numbers (FPS, GPU ms, frame pacing, memory), then what changed in the GPU work and where: encoders and
    command buffers per frame, the share of encoders under short_us, the GPU's idle time, and each encoder label's
    count and GPU ms per frame, largest change first. layer says whether both ran on the same translation layer:
    with different layers it compares layers, not one change. A Windows run against a Metal run has `measure`: the
    GPU ms and Metal memory differ in kind and the encoders exist only in Metal, so use FPS, its lows, stutter and
    jitter. Recordings with under 100 frames are flagged: too short to compare. With markdown true the result also has
    `markdown`: the same numbers as tables for a PR comment. skip_s leaves out the first seconds of each recording,
    where shaders compile and resources load: the GPU numbers, hitches and Metal memory are recomputed from the
    per-frame files without them, and `skipped_s` says it; thermal state, process memory and encoders stay whole-run.
    `screen` appears when one run was recorded with the screen locked and the other not: FPS is then not comparable."""
    sa, sb = (steady_summary(r, skip_s) for r in (a, b))
    result = compare_summaries(sa, sb, a, b, short_us)
    if sa.get("steady"):
        result["skipped_s"] = sa["steady"]["skip_s"]
    return {**result, "markdown": markdown_report(result)} if markdown else result


NOT_COMPARABLE = ("gpu_ms_mean", "gpu_ms_p95", "metal_mib_peak")  # numbers a Windows run and a Metal run measure differently


def measurement(s):
    """Returns "windows" for a summary recorded on Windows (GPU time from PresentMon) and "metal" for one read from an
    Instruments trace (GPU time summed over the encoders)."""
    return "windows" if (s.get("device") or {}).get("platform") == "Windows" else "metal"


def gpu_state_level(s):
    """Returns the time-weighted GPU performance state of a summary (Minimum 0, Medium 1, Maximum 2), or None when it
    has no state shares."""
    share = s.get("gpu_performance_state_share") or {}
    levels = {"Minimum": 0, "Medium": 1, "Maximum": 2}
    return round(sum(levels[k] * v for k, v in share.items() if k in levels), 3) if share else None


def compare_summaries(sa, sb, a, b, short_us=25):
    """perf_compare over two loaded summaries named a and b."""
    numbers = {
        "fps": lambda s: s["gpu"].get("fps_estimate"),
        "fps_1pct_low": lambda s: s["gpu"].get("fps_1pct_low"),
        "fps_01pct_low": lambda s: s["gpu"].get("fps_01pct_low"),
        "stutter_rate_pct": lambda s: s["gpu"].get("stutter_rate_pct"),
        "frame_jitter_ms": lambda s: s["gpu"].get("frame_jitter_ms"),
        "gpu_ms_mean": lambda s: s["gpu"]["frame_gpu_ms"].get("mean"),
        "gpu_ms_p95": lambda s: s["gpu"]["frame_gpu_ms"].get("p95"),
        "frame_interval_ms_p95": lambda s: s["gpu"]["frame_interval_ms"].get("p95"),
        "metal_mib_peak": lambda s: s.get("metal_memory_mib", {}).get("peak"),
        "rss_mib_max": lambda s: s.get("process_rss_mib", {}).get("max"),
    }
    out = {}
    for name, get in numbers.items():
        try:
            out[name] = change(get(sa), get(sb))
        except (KeyError, TypeError):
            out[name] = change(None, None)
    short = [r for r, s in ((a, sa), (b, sb)) if (s.get("gpu") or {}).get("frames", 0) < 100]
    result = {"a": a, "b": b, "layer": recording.layer_change(sa, sb, a, b), "metrics": out, "too_short": short}
    stalled = unpresented(**{a: sa, b: sb})
    if stalled:
        result["unpresented"] = stalled
    locked = [(s.get("machine") or {}).get("screen_locked") for s in (sa, sb)]
    if None not in locked and locked[0] != locked[1]:
        result["screen"] = {"a": locked[0], "b": locked[1],
                            "note": "one run was recorded with the screen locked and the other not: a locked session may "
                                    "leave frames unpaced by the display, so FPS, and GPU ms (they follow the GPU's performance "
                                    "state), are not comparable; record both with the Mac unlocked"}
    levels = [gpu_state_level(s) for s in (sa, sb)]
    if None not in levels and abs(levels[0] - levels[1]) >= 0.25:
        result["gpu_state"] = {"a": levels[0], "b": levels[1],
                               "note": "the GPU spent its time in different performance states (0 is all Minimum, 1 all Medium, "
                                       "2 all Maximum): the same work takes more GPU ms in a lower state, so GPU ms per frame "
                                       "are not comparable; pace both runs alike or compare under load (drawstress at a high dim)"}
    ma, mb = measurement(sa), measurement(sb)
    if ma != mb:
        result["measure"] = {"a": ma, "b": mb, "not_comparable": list(NOT_COMPARABLE),
                             "note": "a Windows run's GPU ms come from PresentMon and a Metal run's from Instruments, and only "
                                     "Metal records memory and encoders: compare fps, fps_1pct_low, fps_01pct_low, "
                                     "stutter_rate_pct and frame_jitter_ms"}
        result["encoders"] = {"not_comparable": "encoder numbers exist only in Metal recordings"}
        return result
    missing = [r for r, s in ((a, sa), (b, sb)) if not s.get("encoders")]
    if missing:
        result["encoders"] = {"missing_in": missing, "hint": "summaries written before version 0.4.0 have no encoder "
                                                             "numbers; record these runs again"}
        return result
    cut = str(int(short_us))
    if int(short_us) not in metrics.SHORT_US:
        raise paths.ToolError(f"short_us is one of {', '.join(map(str, metrics.SHORT_US))}")
    gpu_idle = lambda s: s.get("gpu_idle") or {}
    work = {
        "encoders_per_frame_p50": lambda s: s["encoders"]["per_frame"].get("p50"),
        "command_buffers_per_frame_p50": lambda s: s["encoders"]["command_buffers_per_frame"].get("p50"),
        "short_encoder_share": lambda s: s["encoders"]["short_share"].get(cut),  # {} without encoder spans
        "gpu_idle_share": lambda s: gpu_idle(s).get("idle_share"),
        "idle_ms_per_frame_p50": lambda s: (gpu_idle(s).get("idle_ms_per_frame") or {}).get("p50"),
    }
    # a change in % of a share reads wrong (1.9 % to 49.7 % is +2516 %): shares give their change in points only
    result["encoders"] = {name: change(get(sa), get(sb), share=name.endswith("_share")) for name, get in work.items()}
    result["labels"] = label_changes(sa, sb)
    return result


# what decides a perf_check verdict: the metric, where it lives in a summary, and whether higher is worse
CHECKED = {
    "fps": (lambda s: s["gpu"].get("fps_estimate"), False),
    "gpu_ms_mean": (lambda s: s["gpu"]["frame_gpu_ms"].get("mean"), True),
    "encoders_per_frame_p50": (lambda s: s["encoders"]["per_frame"].get("p50"), True),
    "command_buffers_per_frame_p50": (lambda s: s["encoders"]["command_buffers_per_frame"].get("p50"), True),
}


def load_baselines():
    """Returns the saved references, by name."""
    return json.loads(config.BASELINES.read_text(encoding="utf-8")) if config.BASELINES.exists() else {}


def tool_perf_baseline(name=None, runs=None, skip_s=0):
    """Names a reference for perf_check, or lists them. With name and runs (names from perf_runs, several runs of the
    same program recorded with no change between them), it saves copies of their summaries as the reference `name`,
    replacing a previous one, and returns the range each number spans across them: that range, not one run, is what
    perf_check judges against, since repeated runs differ by a few percent, and `spread_pct`, each range's width in %
    of its midpoint: the noise of this program on this machine, which a change must exceed. With name alone it shows that reference;
    with nothing it lists them. With skip_s the reference keeps each run without its first skip_s seconds (the
    start-up, as perf_compare's skip_s) and perf_check applies the same cut to the run it judges, so both are
    steady-state; the runs need their per-frame files for that."""
    baselines = load_baselines()
    if name is not None and not paths.name_ok(name):
        raise paths.ToolError("a reference name holds only letters, digits, '.', '_' and '-'")
    if runs:
        if name is None:
            raise paths.ToolError("runs need a name for the reference")
        if isinstance(runs, str):
            runs = [runs]
        skip = paths.check_skip(skip_s)
        summaries = [steady_summary(r, skip) for r in runs]
        baselines[name] = {"runs": list(runs), "set": time.strftime("%Y-%m-%d"), "summaries": summaries,
                           **({"skip_s": skip} if skip else {})}
        config.OUT.mkdir(parents=True, exist_ok=True)
        config.BASELINES.write_text(json.dumps(baselines), encoding="utf-8")
    if name is not None:
        if name not in baselines:
            raise paths.ToolError(f"no reference {name}; perf_baseline with no arguments lists them")
        b = baselines[name]
        span = ranges(b["summaries"])
        stalled = unpresented(**dict(zip(b["runs"], b["summaries"])))
        return {"name": name, "runs": b["runs"], "set": b["set"], "range": span, "spread_pct": spreads(span),
                **({"skip_s": b["skip_s"]} if b.get("skip_s") else {}), **({"unpresented": stalled} if stalled else {})}
    return {"baselines": [{"name": n, "runs": b["runs"], "set": b["set"]} for n, b in baselines.items()]}


def ranges(summaries):
    """Returns the lowest and highest value of each checked metric across the summaries; None where one lacks it."""
    out = {}
    for metric, (get, _) in CHECKED.items():
        values = []
        for s in summaries:
            try:
                values.append(get(s))
            except (KeyError, TypeError):
                values.append(None)
        out[metric] = None if None in values else {"min": min(values), "max": max(values)}
    return out


def spreads(span):
    """Returns each range's width as a % of its midpoint: how far equal runs of the reference differ, the noise a
    change must beat. None where the range is None."""
    return {m: None if r is None else round(200 * (r["max"] - r["min"]) / (r["max"] + r["min"]), 1) if r["max"] + r["min"] else 0.0
            for m, r in span.items()}


def tool_perf_check(run, baseline, margin_pct=3):
    """Judges a recording against a reference saved with perf_baseline: regressed when FPS falls under the
    reference's lowest FPS by more than margin_pct, GPU ms per frame rises over its highest by more than margin_pct,
    or encoders or command buffers per frame exceed its highest; improved when a number leaves the range the other
    way and none regressed; same otherwise. Frame pacing, short encoders and GPU idle time are reported by the
    comparison but do not decide: they vary too much between equal runs. A run from Windows against a Metal
    reference (or the reverse) is judged on FPS alone. A reference saved with skip_s judges the run without its first
    skip_s seconds too (`skipped_s` says so). Returns the reasons and perf_compare's
    full comparison against the reference's first run."""
    baselines = load_baselines()
    if baseline not in baselines:
        raise paths.ToolError(f"no reference {baseline}; perf_baseline with no arguments lists them")
    ref = baselines[baseline]
    s = steady_summary(run, ref.get("skip_s", 0))
    span = ranges(ref["summaries"])
    worse, better, unchecked = [], [], []
    cross = measurement(ref["summaries"][0]) != measurement(s)
    for metric, (get, higher_is_worse) in CHECKED.items():
        if cross and metric != "fps":
            unchecked.append(metric)
            continue
        try:
            value = get(s)
        except (KeyError, TypeError):
            value = None
        if value is None or span[metric] is None:
            unchecked.append(metric)
            continue
        lo, hi = span[metric]["min"], span[metric]["max"]
        margin = 0 if metric.endswith("_p50") else margin_pct / 100
        if higher_is_worse and value > hi * (1 + margin):
            worse.append(reason(metric, value, lo, hi))
        elif not higher_is_worse and value < lo * (1 - margin):
            worse.append(reason(metric, value, lo, hi))
        elif higher_is_worse and value < lo * (1 - margin) or not higher_is_worse and value > hi * (1 + margin):
            better.append(reason(metric, value, lo, hi))
    verdict = "regressed" if worse else "improved" if better else "same"
    result = {"run": run, "baseline": baseline, "verdict": verdict, "margin_pct": margin_pct, "regressed": worse,
              "improved": better, "unchecked": unchecked, "range": span,
              "comparison": compare_summaries(ref["summaries"][0], s, ref["runs"][0], run)}
    if ref.get("skip_s"):
        result["skipped_s"] = ref["skip_s"]
    stalled = unpresented(**{run: s})
    if stalled:
        result["unpresented"] = stalled
    if (s.get("gpu") or {}).get("frames", 0) < 100:
        result["hint"] = "under 100 frames: too short to judge; record 30 s or more"
    if cross:
        result["hint_measure"] = "the reference and the run come from Windows and Metal: GPU ms and encoder numbers do not " \
                                 "measure the same thing, so only FPS decides"
    elif unchecked:
        result["hint_unchecked"] = "a summary written before version 0.4.0 has no encoder numbers; record it again"
    return result


def reason(metric, value, lo, hi):
    """Returns one verdict reason: the metric, the run's value and the reference's range."""
    return {"metric": metric, "value": value, "range_min": lo, "range_max": hi}


def change(va, vb, share=False):
    """Returns a number's value in a and b, its change and, unless it is a share, its change in %."""
    delta = None if va is None or vb is None else round(vb - va, 3)
    pct = None if share or delta is None or not va else round(100 * delta / va, 1)
    return {"a": va, "b": vb, "change": delta, "change_pct": pct}


def label_changes(sa, sb, top=20):
    """Returns each encoder label's count and GPU ms per frame in two summaries, largest change in ms per frame
    first. A label missing from a summary that holds the full 20 labels may only have fallen out of that list, so it
    is outside_top_20 rather than new or gone."""
    def per_frame(s):
        frames = (s.get("gpu") or {}).get("frames") or 1
        labels = s["encoders"]["by_label"]
        return {l["label"]: (l["per_frame"], round(l["total_ms"] / frames, 4)) for l in labels}, len(labels) >= top
    (la, full_a), (lb, full_b) = per_frame(sa), per_frame(sb)
    rows = []
    for name in sorted(la.keys() | lb.keys()):
        (count_a, ms_a), (count_b, ms_b) = la.get(name, (None, None)), lb.get(name, (None, None))
        if name not in lb:
            state = "outside_top_20" if full_b else "gone"
        elif name not in la:
            state = "outside_top_20" if full_a else "new"
        else:
            state = "same" if (count_a, ms_a) == (count_b, ms_b) else "changed"
        delta = None if state == "outside_top_20" else round((ms_b or 0) - (ms_a or 0), 4)
        rows.append({"label": name, "state": state, "per_frame_a": count_a, "per_frame_b": count_b,
                     "ms_per_frame_a": ms_a, "ms_per_frame_b": ms_b, "ms_per_frame_change": delta})
    rows.sort(key=lambda r: -abs(r["ms_per_frame_change"] or 0))
    return rows[:top]


def dig(s, path):
    """Returns the value at `path` (a tuple of keys) in a summary, or None where a key is missing."""
    for key in path:
        s = s.get(key) if isinstance(s, dict) else None
    return s


# what perf_history follows across recordings: where each number lives in a summary
HISTORY = {"fps": ("gpu", "fps_estimate"), "fps_1pct_low": ("gpu", "fps_1pct_low"),
           "gpu_ms_mean": ("gpu", "frame_gpu_ms", "mean"), "stutter_rate_pct": ("gpu", "stutter_rate_pct"),
           "hitches": ("hitches", "count"), "metal_mib_peak": ("metal_memory_mib", "peak")}


def tool_perf_history(prefix, limit=50, skip_s=0):
    """Lists the recordings whose name starts with `prefix`, oldest first, with their FPS, 1% low, GPU ms, stutter,
    hitches and peak Metal MiB, and the change from the first to the last: how a number moved over a series of runs, such as
    one recording per version of a translation layer. Read a trend as real only when it exceeds the spread_pct that
    perf_baseline reports for equal runs. Runs from Windows and Metal in one series are flagged: their GPU ms and
    memory do not compare. skip_s leaves out the first seconds of each recording (the start-up), as perf_compare does."""
    if not paths.name_ok(prefix):
        raise paths.ToolError("a prefix holds only letters, digits, '.', '_' and '-'")
    found = []
    for path in sorted(config.OUT.glob(f"{prefix}*.json"), key=lambda p: p.stat().st_mtime):
        if path == config.BASELINES:
            continue
        try:
            s = steady_summary(path.stem, skip_s)
        except ValueError:  # a summary still being written
            continue
        found.append((path.stem, s))
    if not found:
        raise paths.ToolError(f"no run starts with {prefix}; perf_runs lists them")
    found = found[-max(1, min(int(limit), config.MAX_LIMIT)):]
    rows = [{"run": run, "layer": recording.layer_label(s.get("layer")), "source": measurement(s),
             **{k: dig(s, path) for k, path in HISTORY.items()}} for run, s in found]
    result = {"prefix": prefix, "runs": rows,
              "change": {k: change(rows[0][k], rows[-1][k]) for k in HISTORY}}
    if len({r["source"] for r in rows}) > 1:
        result["hint"] = "the series mixes Windows and Metal runs: read only fps, fps_1pct_low and stutter_rate_pct"
    elif len(rows) < 3:
        result["hint"] = "under 3 runs: not a trend yet"
    return result


# what perf_gate can require: the argument, where the number lives in a summary and whether it is a floor or a ceiling
GATES = {"fps_min": (("gpu", "fps_estimate"), "min"), "fps_1pct_low_min": (("gpu", "fps_1pct_low"), "min"),
         "stutter_rate_pct_max": (("gpu", "stutter_rate_pct"), "max"), "gpu_ms_p95_max": (("gpu", "frame_gpu_ms", "p95"), "max"),
         "hitches_max": (("hitches", "count"), "max"), "metal_mib_max": (("metal_memory_mib", "peak"), "max")}


def tool_perf_gate(run, fps_min=None, fps_1pct_low_min=None, stutter_rate_pct_max=None, gpu_ms_p95_max=None,
                   hitches_max=None, metal_mib_max=None, skip_s=0):
    """Checks a recording against budgets and says pass or fail: a floor for FPS and the 1% low, a ceiling for the
    stutter rate, the p95 GPU ms per frame, the hitch count and the peak Metal MiB. Give at least one. A number the
    recording lacks fails its budget (value null): a gate must not pass on missing data, nor on a recording whose
    program stopped presenting (`unpresented`). Returns each budget with its
    limit, the value and whether it held. Use it as a bar a change must clear, where perf_check judges against equal runs.
    skip_s leaves out the first seconds of the recording (the start-up), as perf_compare does."""
    given = {k: v for k, v in (("fps_min", fps_min), ("fps_1pct_low_min", fps_1pct_low_min),
                               ("stutter_rate_pct_max", stutter_rate_pct_max), ("gpu_ms_p95_max", gpu_ms_p95_max),
                               ("hitches_max", hitches_max), ("metal_mib_max", metal_mib_max)) if v is not None}
    if not given:
        raise paths.ToolError(f"give at least one budget: {', '.join(GATES)}")
    s = steady_summary(run, skip_s)
    checks = []
    for budget, limit in given.items():
        path, kind = GATES[budget]
        value = dig(s, path)
        ok = value is not None and (value >= limit if kind == "min" else value <= limit)
        checks.append({"budget": budget, "limit": limit, "value": value, "ok": ok})
    stalled = unpresented(**{run: s})
    result = {"run": run, "pass": all(c["ok"] for c in checks) and not stalled, "checks": checks}
    if stalled:
        result["unpresented"] = stalled
    if s.get("steady"):
        result["skipped_s"] = s["steady"]["skip_s"]
    if (s.get("gpu") or {}).get("frames", 0) < 100:
        result["hint"] = "under 100 frames: too short to trust; record 30 s or more"
    return result


CSV_TOL_MS = 0.002  # frames.csv rounds start times to 0.001 ms, so a gap at the hitch threshold may read 0.001 ms short


def read_frames(run):
    """Returns a run's GPU frames as (frame, start ms, GPU ms) from its frames.csv."""
    source = config.OUT / f"{run}.frames.csv"
    if not source.exists():
        raise paths.ToolError(f"{run} has no per-frame file; record it again")
    with open(source, newline="", encoding="utf-8") as f:
        return [(int(r["frame"]), float(r["start_ms"]), float(r["gpu_ms_total"])) for r in csv.DictReader(f)]


def read_memory(run):
    """Returns a run's Metal memory as (ms, MiB) samples, or [] when it has none."""
    source = config.OUT / f"{run}.metal_memory.csv"
    if not source.exists():
        return []
    with open(source, newline="", encoding="utf-8") as f:
        return [(float(r["time_ms"]), int(r["metal_allocated_bytes"]) / 2**20) for r in csv.DictReader(f)]


def steady_summary(run, skip_s=0):
    """Returns a run's summary; with `skip_s` above 0, with the GPU numbers (FPS and its lows, GPU and interval ms,
    stutter, jitter), the hitches and the Metal memory recomputed from frames.csv and metal_memory.csv without the
    first `skip_s` seconds after its first frame: the start-up, where shaders compile and resources load. The CPU use
    is dropped; the thermal state, the process memory, the encoders and the GPU idle time stay those of the whole run,
    as `steady.whole_run` says. Causes are kept only for the hitches the summary lists (the 20 longest)."""
    s = json.loads(paths.run_path(run).read_text(encoding="utf-8"))
    skip = paths.check_skip(skip_s)
    if not skip:
        return s
    rows = read_frames(run)
    cut = rows[0][1] + skip * 1000 if rows else 0
    kept = [r for r in rows if r[1] >= cut]
    if len(kept) < 2:
        raise paths.ToolError(f"{run} has under 2 frames after the first {skip:g} s; use a smaller skip_s")
    starts, totals = [r[1] for r in kept], [r[2] for r in kept]
    gaps = [b - a for a, b in zip(starts, starts[1:]) if b > a]
    gpu = {k: v for k, v in (s.get("gpu") or {}).items() if k not in ("per_channel_ms", "intervals", "throttling_analysis")}
    gpu.update(frames=len(kept), frame_gpu_ms=metrics.stats(totals), frame_interval_ms=metrics.stats(gaps),
               fps_estimate=round(1000 / statistics.median(gaps), 1) if gaps else None,
               **{k: None for k in ("fps_1pct_low", "fps_01pct_low", "stutter_rate_pct", "frame_jitter_ms")})
    gpu.update(perf_report.frame_pacing(gaps, totals))
    old = s.get("hitches") or {}
    limit = old.get("threshold_ms")
    first = kept[0][0]
    count = sum(1 for a, b in zip(starts, starts[1:]) if limit and b - a > limit - CSV_TOL_MS)
    worst = [h for h in old.get("worst", []) if h["frame"] > first]
    hitches = {"count": count, "causes": dict(collections.Counter(h["cause"] for h in worst).most_common()),
               "worst": worst}
    span = starts[-1] - starts[0] if starts else 0
    hitches["per_minute"] = round(count / (span / 60000), 2) if span > 0 else None
    if limit:
        hitches["threshold_ms"] = limit
    if count > len(worst):
        hitches["causes_partial"] = True
    memory = [mib for t, mib in read_memory(run) if t >= cut]
    stall = gpu.get("unpresented")
    if stall and (stall["from_s"] + stall["span_s"]) * 1000 <= cut:
        gpu.pop("unpresented")
    s.update(gpu=gpu, hitches=hitches)
    s.pop("cpu", None)
    s.pop("metal_memory_mib", None)
    if memory:
        s["metal_memory_mib"] = {"peak": round(max(memory), 2), "samples": len(memory)}
    s["steady"] = {"skip_s": skip, "whole_run": ["thermal_state_share", "process_rss_mib", "encoders", "gpu_idle", "gpu_counters"]}
    return s


REFRESH_RATES = (24, 30, 48, 50, 60, 72, 75, 90, 100, 120, 144, 165, 240)  # common display rates, in Hz


def display_synced_hz(gpu):
    """Returns the display rate a run's FPS sits on, or None: the FPS within 1 % of a common rate and the 95th percentile
    frame interval within 30 % above the median, which is what a run paced by the display looks like (not proof; a real
    D3D11 run under Wine at 118.9 FPS had 17 %)."""
    fps, interval = gpu.get("fps_estimate"), gpu.get("frame_interval_ms") or {}
    p50, p95 = interval.get("p50"), interval.get("p95")
    if not fps or not p50 or not p95 or p95 > p50 * 1.3:
        return None
    return next((hz for hz in REFRESH_RATES if abs(fps - hz) <= hz * 0.01), None)


def tool_perf_diagnose(run, min_encoders=4, short_us=25, short_share=0.25):
    """Says whether a saved recording splits its GPU work into too many short encoders, the pattern of translation
    layers such as DXMT, Mullion or MoltenVK, with the numbers behind it: encoders and command buffers per frame, the
    share of short encoders, the labels with the most GPU time and the GPU's idle time. Read the idle time together
    with the FPS: a program waiting for vsync idles too. Defaults come from bgfx 17-drawstress on an M1 Pro: 7
    encoders per frame and 50% under 25 us under Mullion, 2 and 2% in native Metal."""
    s = json.loads(paths.run_path(run).read_text(encoding="utf-8"))
    encoders = s.get("encoders")
    if not encoders:
        raise paths.ToolError(f"{run} was summarized before version 0.4.0 and has no encoder numbers; record it again")
    if int(short_us) not in metrics.SHORT_US:
        raise paths.ToolError(f"short_us is one of {', '.join(map(str, metrics.SHORT_US))}")
    share = encoders["short_share"].get(str(int(short_us)))  # None without encoder spans (PresentMon, DWM)
    per_frame = encoders["per_frame"].get("p50", 0)
    gpu = s.get("gpu") or {}
    frames = gpu.get("frames", 0)
    too_many_short = per_frame >= min_encoders and share is not None and share >= short_share

    frame_gpu_ms = gpu.get("frame_gpu_ms") or {}
    frame_interval_ms = gpu.get("frame_interval_ms") or {}
    gpu_idle = s.get("gpu_idle") or {}
    stutter_rate = gpu.get("stutter_rate_pct") or 0.0
    jitter_ms = gpu.get("frame_jitter_ms") or 0.0
    worst_spike = frame_interval_ms.get("max") or frame_gpu_ms.get("max") or 0.0

    if gpu.get("stutter_rate_pct") is None:
        stutter_verdict = "UNKNOWN"
    elif stutter_rate > 7.0:
        stutter_verdict = "SEVERE_STUTTER"
    elif stutter_rate >= 2.0:
        stutter_verdict = "MICRO_STUTTER"
    else:
        stutter_verdict = "SMOOTH"

    idle_share = gpu_idle.get("idle_share")
    gpu_ms_mean = frame_gpu_ms.get("mean") or 0.0
    interval_ms_mean = frame_interval_ms.get("mean") or 0.0
    interval_p50 = frame_interval_ms.get("p50") or 0.0
    interval_p95 = frame_interval_ms.get("p95") or 0.0
    mem_working_set = max((s.get("process_rss_mib") or {}).get("max") or 0.0,
                          (s.get("metal_memory_mib") or {}).get("peak") or 0.0)

    high_variance = jitter_ms >= 3.0 or (interval_p95 - interval_p50) >= 5.0
    high_memory = mem_working_set >= 1500.0
    has_frame_data = bool(frame_gpu_ms.get("count", 0) > 0 or frame_interval_ms.get("count", 0) > 0)

    if has_frame_data and high_variance and high_memory:
        # Inferred from a large working set plus uneven frame times; memory bandwidth itself is not measured.
        bottleneck = "MEMORY_PRESSURE_SUSPECTED"
    elif idle_share is None:
        bottleneck = "UNKNOWN"
    elif has_frame_data and (idle_share >= 0.25 or (too_many_short and idle_share >= 0.20)):
        bottleneck = "CPU_SUBMISSION_BOUND"
    elif has_frame_data and idle_share <= 0.15 and gpu_ms_mean > 0 and (
            gpu_ms_mean >= 0.80 * interval_ms_mean if interval_ms_mean > 0 else True):
        bottleneck = "GPU_BOUND"
    else:
        bottleneck = "BALANCED"

    recommendations = []
    if bottleneck == "GPU_BOUND":
        recommendations.append("Activar FSR si la GPU está saturada al 100% o usar escalado dinámico de resolución.")
        recommendations.append("Reducir resolución interna de renderizado, calidad de postprocesado o sombreadores pesados.")
    elif bottleneck == "CPU_SUBMISSION_BOUND":
        if s.get("template") == "Windows Native Trace":
            recommendations.append("Fijar FlipQueueSize=3 en el controlador AMD o DirectX para amortiguar el despacho de la CPU.")
        recommendations.append("Consolidar draw calls mediante instancing o reducir complejidad de geometría y objetos dinámicos.")
    elif bottleneck == "MEMORY_PRESSURE_SUSPECTED":
        recommendations.append("Hipótesis (el ancho de banda no se mide): reducir resolución de sombras de 2048 a 1024 para aliviar el bus UMA.")
        recommendations.append("Hipótesis: limitar cascadas de sombras a 2 en exteriores para mitigar el consumo de memoria unificada.")
    if too_many_short:
        recommendations.append("Consolidar render passes y reducir encoders breves para mitigar sobrecarga en la capa de traducción.")
    if stutter_verdict in ("MICRO_STUTTER", "SEVERE_STUTTER"):
        recommendations.append("Activar un limitador de FPS (framerate cap) o sincronización vertical/VRR para estabilizar los intervalos de presentación.")
    throttling = gpu.get("throttling_analysis") or {}
    if throttling.get("thermal_throttling_detected"):
        drift_pct = throttling.get("fps_drift_pct", 0)
        recommendations.append(f"Estrangulamiento térmico detectado ({drift_pct}% caída de FPS): revisar curvas de ventilación y disipación térmica del APU/GPU.")
    hitches = s.get("hitches") or {}
    top_cause = next(iter(hitches.get("causes") or {}), None)
    if top_cause == "shader_compile":
        recommendations.append("Los tirones coinciden con el compilador gráfico: precompilar o calentar la caché de shaders.")
    elif top_cause == "memory_growth":
        recommendations.append("Los tirones coinciden con crecimiento de memoria Metal: revisar cargas de recursos en medio de la partida.")
    elif top_cause == "thermal":
        recommendations.append("Los tirones coinciden con un estado térmico distinto de Nominal.")
    synced = display_synced_hz(gpu)
    if synced:
        recommendations.append(f"El FPS ({gpu['fps_estimate']}) coincide con una pantalla de {synced} Hz y los intervalos son regulares: "
                               "probablemente sincronización vertical; la GPU tiene margen y baja de estado de rendimiento, así que sus ms por frame "
                               "suben: compare solo ejecuciones con el mismo ritmo.")
    activity = s.get("gpu_activity") or {}
    if activity.get("gpu_recovered"):
        n = activity["recoveries"]
        recommendations.append(f"La GPU se recuperó {n} {'vez' if n == 1 else 'veces'} durante la grabación (recoveryCount del "
                               "controlador): un cuelgue o un comando que superó su tiempo; las cifras de esta grabación no son fiables.")
    if (activity.get("split_scenes") or 0) > 0:
        recommendations.append(f"El contador SplitSceneCount del controlador creció en {activity['split_scenes']}: la GPU dividió "
                               f"{activity['split_scenes']} escenas; su causa no se mide aquí, compárelo entre grabaciones.")
    stalled = unpresented(**{run: s})
    if stalled:
        recommendations.insert(0, f"El programa dejó de presentar a los {gpu['unpresented']['from_s']} s (¿ventana tapada o "
                                  "minimizada, o una carga que no presentó nada): ese trabajo no cuenta como frames y este "
                                  "diagnóstico solo cubre los frames presentados; grabe de nuevo con la ventana visible.")
    if bottleneck == "UNKNOWN":
        recommendations.append("Sin datos de actividad de GPU en esta grabación: no hay veredicto de cuello de botella.")
    elif not recommendations:
        recommendations.append("Rendimiento equilibrado; no se detectan cuellos de botella críticos.")

    return {"run": run, "too_many_short_encoders": too_many_short,
            "thresholds": {"min_encoders": min_encoders, "short_us": int(short_us), "short_share": short_share},
            "encoders_per_frame_p50": per_frame,
            "command_buffers_per_frame_p50": encoders["command_buffers_per_frame"].get("p50"),
            "short_encoder_share": share, "fps": gpu.get("fps_estimate"),
            "bottleneck": bottleneck,
            "stutter_analysis": {"stutter_rate_pct": stutter_rate, "worst_spike_ms": worst_spike,
                                 "verdict": stutter_verdict},
            "recommendations": recommendations, "hitches": hitches or None,
            "display_synced_hz": synced, "gpu_idle": s.get("gpu_idle"), "gpu_activity": s.get("gpu_activity"), "by_label": encoders["by_label"],
            "too_short": frames < 100, **({"unpresented": stalled} if stalled else {})}
