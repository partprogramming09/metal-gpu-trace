"""Reading recordings back: runs, compare, baselines, checks, gates, history and diagnosis."""
import collections
import csv
import functools
import json
import math
import statistics
import time

from metal_gpu_trace import config, metrics, paths, perf_report, recording, tables


UNPRESENTED_NOTE = ("the program stopped presenting (its window hidden behind another, minimized or off screen, or a "
                    "load of a second or more that presented nothing) and "
                    "Instruments stopped numbering frames: the work from from_s for span_s is left out of the frame numbers, "
                    "which cover only the presented frames; record again with the program's window visible")


NOISY_NOTE = ("another process was loading the GPU while these recorded (the GPU's total use exceeded the program's own by "
              "20 points or more; noisy_basis in the summary has the numbers): close other GPU users and repeat the run "
              "before trusting its numbers")


def noisy(**summaries):
    """Returns {"runs": [names], "note": ...} for the named summaries recorded with noisy_environment true, or None."""
    runs = [name for name, s in summaries.items() if s.get("noisy_environment") is True]
    return {"runs": runs, "note": NOISY_NOTE} if runs else None


def unpresented(**summaries):
    """Returns {"runs": {name: gpu.unpresented}, "note": ...} for the named summaries whose program stopped presenting,
    or None when every one presented throughout."""
    runs = {name: s["gpu"]["unpresented"] for name, s in summaries.items() if (s.get("gpu") or {}).get("unpresented")}
    return {"runs": runs, "note": UNPRESENTED_NOTE} if runs else None


def reads_recordings(tool):
    """Makes a tool that reads recordings or references answer a summary whose sections have the wrong type with a
    ToolError (naming the kind of error, never a path), instead of an internal error."""
    @functools.wraps(tool)
    def guarded(*args, **kwargs):
        try:
            return tool(*args, **kwargs)
        except (KeyError, IndexError, TypeError, AttributeError, OverflowError, RecursionError, ZeroDivisionError) as error:
            raise paths.ToolError(f"{tool.__name__.removeprefix('tool_')} found a recording or reference not in the form the "
                                  f"recorder writes, or an argument it cannot use ({type(error).__name__}); record it "
                                  "again or check the arguments") from None
    return guarded


def _recordings(pattern="*.json"):
    """Returns the summaries in the runs folder that match `pattern`, oldest first: not baselines.json or the panel.json of 0.24.0,
    which are not recordings, nor a link to nothing."""
    found = []
    for path in config.OUT.glob(pattern):
        if path.name in (config.BASELINES.name, paths.LAYOUT_FILE):
            continue
        try:
            found.append((path.stat().st_mtime, path))
        except OSError:
            continue
    return [path for _, path in sorted(found, key=lambda f: f[0])]


def tool_perf_runs(offset=0, limit=50):
    """Lists the saved recordings, newest first, with frames, FPS, GPU ms per frame, memory peaks and the translation layer
    each ran on; project names the project they belong to."""
    runs = []
    for path in reversed(_recordings()):
        try:
            s = paths.read_object(path, path.name)
            gpu = s.get("gpu") or {}
            runs.append({"run": path.stem, "schema_version": metrics.schema_of(s), "program": (s.get("process") or {}).get("arguments"),
                         "frames": gpu.get("frames"), "fps": gpu.get("fps_estimate"),
                         "gpu_ms_mean": (gpu.get("frame_gpu_ms") or {}).get("mean"),
                         "metal_mib_peak": (s.get("metal_memory_mib") or {}).get("peak"),
                         "rss_mib_max": (s.get("process_rss_mib") or {}).get("max"),
                         "trace_kept": path.with_suffix(".trace").is_dir() and not path.with_suffix(".trace").is_symlink(), "layer": recording.layer_label(s.get("layer"))})
        except (paths.ToolError, *paths.MALFORMED):  # a summary still being written, or a file that is not one
            continue
    return {**paths.page(runs, offset, limit), "project": (config.PROJECT or {}).get("name")}


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


@reads_recordings
def tool_perf_compare(a, b, short_us=25, markdown=False, skip_s=0):
    """Compares two saved recordings, a the reference and b the run after a change: headline numbers (FPS, GPU ms, frame
    pacing, memory), then the GPU work: encoders and command buffers per frame, share of short encoders, idle time, and
    each encoder label's change, largest first. `layer` says whether both ran on the same translation layer; `measure`
    marks Windows against Metal (use FPS, lows, stutter, jitter); runs under 100 frames are flagged. `screen`,
    `noisy_environment` flag runs that do not compare; `suggested_actions` says what to call next."""
    sa, sb = (steady_summary(r, skip_s) for r in (a, b))
    result = compare_summaries(sa, sb, a, b, short_us)
    skip = paths.check_skip(skip_s)
    result["suggested_actions"] = [x for r, s in ((a, sa), (b, sb))
                                   for x in suggested_actions(s, r, skip, lambda r=r: _frames_or_none(r))]
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


def memory_pressure_change(sa, sb):
    """Returns the change of `common.memory_pressure` between two summaries when both measured it the same way, an
    explanation when they measured it differently (a Metal allocation and a process RSS are two things), and None when
    either has no usable `common` block (generation 1 or 2, or hand-edited) or did not measure memory at all."""
    pa, pb = ((s.get("common") or {}).get("memory_pressure") if isinstance(s.get("common"), dict) else None
              for s in (sa, sb))
    if not (isinstance(pa, dict) and isinstance(pb, dict)) or pa.get("source") is None or pb.get("source") is None:
        return None
    if pa["source"] != pb["source"]:
        return {"comparable": False, "a": pa, "b": pb,
                "note": "the two runs measured memory differently, so their peaks are not subtracted"}
    peaks = (pa.get("peak_mib"), pb.get("peak_mib"))
    if any(type(v) not in (int, float) for v in peaks):
        return None
    return {"comparable": True, "source": pa["source"], "change": change(*peaks)}


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
        "gpu_start_latency_ms_p50": lambda s: (s["gpu"].get("start_latency_ms") or {}).get("p50"),
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
    result = {"a": a, "b": b, "layer": recording.layer_change(sa, sb, a, b), "context": recording.context_change(sa, sb, a, b), "metrics": out, "too_short": short}
    stalled = unpresented(**{a: sa, b: sb})
    if stalled:
        result["unpresented"] = stalled
    loud = noisy(**{a: sa, b: sb})
    if loud:
        result["noisy_environment"] = loud
    locked = [(s.get("machine") or {}).get("screen_locked") for s in (sa, sb)]
    if None not in locked and locked[0] != locked[1]:
        result["screen"] = {"a": locked[0], "b": locked[1],
                            "note": "one run was recorded with the screen locked and the other not: a locked session may "
                                    "leave frames unpaced by the display, so FPS, and GPU ms (they follow the GPU's performance "
                                    "state), are not comparable; record both with the Mac unlocked"}
    tiers = [s.get("tier") for s in (sa, sb)]
    if None not in tiers and tiers[0] != tiers[1]:
        result["tier"] = {"a": tiers[0], "b": tiers[1],
                          "note": "the recordings were made at different tiers: a light recording has no Metal memory "
                                  "or counters, so compare memory only between recordings of the same tier"}
    levels = [gpu_state_level(s) for s in (sa, sb)]
    if None not in levels and abs(levels[0] - levels[1]) >= 0.25:
        result["gpu_state"] = {"a": levels[0], "b": levels[1],
                               "note": "the GPU spent its time in different performance states (0 is all Minimum, 1 all Medium, "
                                       "2 all Maximum): the same work takes more GPU ms in a lower state, so GPU ms per frame "
                                       "are not comparable; pace both runs alike or compare under load (drawstress at a high dim)"}
    pressure = memory_pressure_change(sa, sb)
    if pressure:
        result["memory_pressure"] = pressure
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
    return paths.read_object(config.BASELINES, config.BASELINES.name) if config.BASELINES.exists() else {}


@reads_recordings
def tool_perf_baseline(name=None, runs=None, skip_s=0):
    """Names a reference for perf_check, or lists them. With name and runs (equal runs of one program) it saves their
    summaries as the reference, replacing a previous one, and returns each number's range and `spread_pct`: the noise a
    change must exceed. With name alone it shows that reference; with nothing it lists them."""
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
        paths.write_file(config.BASELINES, json.dumps(baselines))
    if name is not None:
        if name not in baselines:
            raise paths.ToolError(f"no reference {name}; perf_baseline with no arguments lists them")
        b = baselines[name]
        span = ranges(b["summaries"])
        stalled = unpresented(**dict(zip(b["runs"], b["summaries"])))
        loud = noisy(**dict(zip(b["runs"], b["summaries"])))
        return {"name": name, "runs": b["runs"], "set": b["set"], "range": span, "spread_pct": spreads(span),
                **({"skip_s": b["skip_s"]} if b.get("skip_s") else {}), **({"unpresented": stalled} if stalled else {}),
                **({"noisy_environment": loud} if loud else {})}
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


def judge(metric, value, span, margin_pct):
    """Returns how a checked metric's `value` stands against the reference's `span` ({"min", "max"}): worse when it is
    past the bad end by more than margin_pct (no margin for the encoder and command buffer counts, which are
    exact), better when past the good end, same inside; None when the value or the span is missing. This is
    perf_check's rule."""
    if value is None or span is None:
        return None
    higher_is_worse = CHECKED[metric][1]
    margin = 0 if metric.endswith("_p50") else margin_pct / 100
    if higher_is_worse and value > span["max"] * (1 + margin) or not higher_is_worse and value < span["min"] * (1 - margin):
        return "worse"
    if higher_is_worse and value < span["min"] * (1 - margin) or not higher_is_worse and value > span["max"] * (1 + margin):
        return "better"
    return "same"


@reads_recordings
def tool_perf_check(run, baseline, margin_pct=3):
    """Judges a recording against a reference from perf_baseline: regressed when FPS falls under the reference's lowest, or
    GPU ms per frame rises over its highest, by more than margin_pct, or encoders or command buffers per frame exceed
    its highest; improved when a number leaves the range the other way and none regressed; same otherwise. Windows
    against Metal is judged on FPS alone. Returns the reasons and perf_compare's comparison."""
    baselines = load_baselines()
    if baseline not in baselines:
        raise paths.ToolError(f"no reference {baseline}; perf_baseline with no arguments lists them")
    ref = baselines[baseline]
    s = steady_summary(run, ref.get("skip_s", 0))
    span = ranges(ref["summaries"])
    worse, better, unchecked = [], [], []
    cross = measurement(ref["summaries"][0]) != measurement(s)
    for metric, (get, _) in CHECKED.items():
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
        direction = judge(metric, value, span[metric], margin_pct)
        lo, hi = span[metric]["min"], span[metric]["max"]
        if direction == "worse":
            worse.append(reason(metric, value, lo, hi))
        elif direction == "better":
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
    if len(ref["summaries"]) == 1 and verdict != "same":
        result["note"] = "the reference is one run, so its noise is not measured and a small change may be noise; " \
                         "save 2 or more runs with perf_baseline"
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
    """Lists the recordings whose name starts with `prefix`, oldest first, with FPS, 1% low, GPU ms, stutter, hitches and
    peak Metal MiB, and the change from first to last. A trend is real only above the spread_pct of perf_baseline.
    Windows and Metal runs in one series are flagged."""
    if not paths.name_ok(prefix):
        raise paths.ToolError("a prefix holds only letters, digits, '.', '_' and '-'")
    rows = []
    for path in _recordings(f"{prefix}*.json"):
        try:
            s = steady_summary(path.stem, skip_s)
            rows.append({"run": path.stem, "layer": recording.layer_label(s.get("layer")), "source": measurement(s),
                         **{k: dig(s, where) for k, where in HISTORY.items()}})
        except (paths.ToolError, *paths.MALFORMED):  # a summary still being written, or in the wrong form
            continue
    if not rows:
        raise paths.ToolError(f"no run starts with {prefix}; perf_runs lists them")
    rows = rows[-max(1, min(int(limit), config.MAX_LIMIT)):]
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


@reads_recordings
def tool_perf_gate(run, fps_min=None, fps_1pct_low_min=None, stutter_rate_pct_max=None, gpu_ms_p95_max=None,
                   hitches_max=None, metal_mib_max=None, skip_s=0):
    """Checks a recording against budgets and says pass or fail: FPS and 1% low floors, ceilings for stutter rate, p95 GPU
    ms per frame, hitches and peak Metal MiB. Give at least one. A number the recording lacks fails its budget (value
    null), and so does a run that stopped presenting (`unpresented`). Returns each budget with its limit, value and
    whether it held."""
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
    source = tables.find(config.OUT, f"{run}.frames")
    if source is None:
        raise paths.ToolError(f"{run} has no per-frame file; record it again")
    try:
        stat = source.stat()
    except OSError:  # pruned between find and stat
        raise paths.ToolError(f"{run} has no per-frame file; record it again") from None
    return list(_frames(source, stat.st_mtime_ns, stat.st_size))


@functools.lru_cache(maxsize=4)  # the last few files read stay in memory, keyed by time and size
def _frames(source, mtime_ns, size):
    """Returns the rows of a frames.csv as a tuple; the file's time and size are the key, so a changed file is read
    again (a call that fails is not kept)."""
    return tuple(_csv_rows(source, lambda r: (int(r["frame"]), float(r["start_ms"]), float(r["gpu_ms_total"]))))


def read_memory(run):
    """Returns a run's Metal memory as (ms, MiB) samples, or [] when it has none."""
    source = tables.find(config.OUT, f"{run}.metal_memory")
    if source is None:
        return []
    return _csv_rows(source, lambda r: (float(r["time_ms"]), int(r["metal_allocated_bytes"]) / 2**20))


def _csv_rows(source, row):
    """Returns `row(r)` for each line of a recording's CSV, leaving out the lines it cannot read (the last one of a
    recording cut short, a value that is not a finite number); a file that cannot be read at all raises ToolError."""
    out = []
    try:
        with tables.open_text(source) as f:
            for r in csv.DictReader(f):
                try:
                    values = row(r)
                    finite = all(math.isfinite(v) for v in values)
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if finite:
                    out.append(values)
    except tables.UNREADABLE:
        raise paths.ToolError(f"{source.name} cannot be read; record it again") from None
    return out


def steady_summary(run, skip_s=0):
    """Returns a run's summary; with `skip_s` above 0, with the GPU numbers (FPS and its lows, GPU and interval ms,
    stutter, jitter), the hitches and the Metal memory recomputed from frames.csv and metal_memory.csv without the
    first `skip_s` seconds after its first frame: the start-up, where shaders compile and resources load. The CPU use
    is dropped; the thermal state, the process memory, the encoders and the GPU idle time stay those of the whole run,
    as `steady.whole_run` says. Causes are kept only for the hitches the summary lists (the 20 longest)."""
    s = paths.read_object(paths.run_path(run), f"{run}.json")
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
    if "common" in s:  # follows the recomputed numbers
        s["common"] = metrics.common_block(s)
    s["steady"] = {"skip_s": skip, "whole_run": ["gpu.start_latency_ms", "thermal_state_share", "process_rss_mib", "encoders", "gpu_idle", "gpu_counters"]}
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


def _frames_or_none(run):
    """Returns the run's frames, or None when it has no per-frame file or it cannot be read."""
    try:
        return read_frames(run)
    except paths.ToolError:
        return None


def _number(value):
    """Returns `value` when it is a finite number (not a bool), else None."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def suggested_actions(summary, run, skip_s=0, rows=None):
    """Returns what to call next for a run, as [{"tool", "arguments", "reason"}] (empty when nothing applies): `tool` is one
    of this server's, `arguments` only what the rule knows (the program's own arguments are not known, and the reason says
    so). `rows` is the run's frames from read_frames, None when it has no per-frame file; a function that returns them is
    called only when a rule needs them."""
    summary = summary if isinstance(summary, dict) else {}
    gpu, hitches = (summary.get(k) if isinstance(summary.get(k), dict) else {} for k in ("gpu", "hitches"))
    causes = hitches.get("causes") if isinstance(hitches.get("causes"), dict) else {}
    first_cause = next(iter(causes), None)
    actions = []

    def add(tool, arguments, reason):
        actions.append({"tool": tool, "arguments": arguments, "reason": f"{run}: {reason}"})
    if first_cause == "shader_compile":
        label = summary.get("label")
        base = label if isinstance(label, str) and label and paths.name_ok(label) else run
        # perf_cold_warm names its runs <name>-first and <name>-second, and a recording's label is 100 characters at most
        name = f"{base[:90]}-cw"
        add("perf_cold_warm", {"name": name}, "the hitches come from compiling shaders: a cold and a warm run tell first-run "
            "compilation from steady state (use the same program arguments)")
        skip = _startup_skip_s(hitches, summary, rows() if callable(rows) else rows)
        if skip is not None and skip > skip_s:
            add("perf_compare", {"skip_s": skip}, f"every shader hitch among the 20 longest ends within the first {skip} s: "
                "compare without that start-up (this reads only the 20 longest hitches)")
    frames = _number(gpu.get("frames"))
    if frames is not None and frames < 100:
        add("perf_record", {"seconds": 30}, f"only {int(frames)} frames: too short to trust; record 30 s or more "
            "(with the same program arguments)")
    if summary.get("noisy_environment") is True:
        add("perf_record", {}, "another process was loading the GPU while it recorded: close other GPU users first and "
            "record again (with the same program arguments)")
    if gpu.get("unpresented"):
        add("perf_record", {}, "the program stopped presenting: keep its window visible and record again (with the same "
            "program arguments)")
    throttling = gpu.get("throttling_analysis") if isinstance(gpu.get("throttling_analysis"), dict) else {}
    if throttling.get("thermal_throttling_detected") is True or first_cause == "thermal":
        add("perf_ab", {"cooldown_s": 60}, "the Mac throttled: rest between recordings; 60 s is a starting value, not a "
            "measurement (with the same program arguments)")
    return actions


def _startup_skip_s(hitches, summary, rows):
    """Returns the whole seconds that cover the shader-compile hitches among the 20 longest, when that is at most a quarter
    of the run (start-up compilation), else None."""
    duration = _number(summary.get("duration_s"))
    if not rows or not duration or duration <= 0 or not isinstance(hitches.get("worst"), list):
        return None
    ends = []
    for hitch in hitches["worst"]:
        try:
            if hitch["cause"] == "shader_compile":
                ends.append(_number(hitch["window_ms"][1]))
        except (KeyError, TypeError, IndexError):
            continue
    try:
        first = _number(rows[0][1])
    except (IndexError, TypeError, KeyError):
        return None
    if not ends or None in ends or first is None:
        return None
    span = (max(ends) - first) / 1000
    return math.ceil(span) if 0 < span <= 0.25 * duration else None


@reads_recordings
def tool_perf_diagnose(run, min_encoders=4, short_us=25, short_share=0.25):
    """Says whether a saved recording splits its GPU work into too many short encoders (the pattern of translation layers
    such as DXMT, Mullion or MoltenVK), with the numbers: encoders and command buffers per frame, share of short
    encoders, labels with the most GPU time, idle time (read with the FPS: vsync idles too). `suggested_actions` says
    what to call next."""
    s = paths.read_object(paths.run_path(run), f"{run}.json")
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
    spills = s.get("shader_spills") or {}
    if spills.get("events"):
        where = f" en {spills['encoders']} encoders" if spills.get("encoders") else ""
        recommendations.append(f"Hay {spills['events']} derrames de registros de shader ({spills.get('bytes', 0)} bytes{where}): "
                               "simplificar o dividir el shader que los causa.")
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
            "too_short": frames < 100, **({"unpresented": stalled} if stalled else {}),
            "suggested_actions": suggested_actions(s, run, 0, lambda: _frames_or_none(run))}


@reads_recordings
def tool_perf_memory_breakdown(run, top=10):
    """Breaks down the Metal allocations of a saved recording by type (texture, buffer, heap...): allocated, still live and
    `gone` per type. A small live share of a large allocated size is churn, the pattern behind a memory spike or a
    stall. Also totals, live memory by mode, allocation rate and peak. Needs a Metal recording above tier light."""
    if type(top) is not int or top < 1:
        raise paths.ToolError("top is a whole number of 1 or more")
    s = paths.read_object(paths.run_path(run), f"{run}.json")
    found = s.get("resource_allocations")
    if not found or not found.get("events"):
        windows = (s.get("device") or {}).get("platform") == "Windows"
        raise paths.ToolError(f"{run} has no resource allocations: " + (
            "a Windows recording has no Metal resource table" if windows else
            "record it again with the Metal resource allocation table (not at tier light)"))
    live = found.get("live")  # absent in a run recorded before 0.27.0: unknown, not zero
    good = lambda v: type(v) in (int, float) and math.isfinite(v) and v >= 0  # not a bool, NaN or negative size
    sizes = [found["events"], found["mib"], *(v for t in found["by_type"].values() for v in (t["count"], t["mib"])),
             *((live["count"], live["mib"], *(v for t in live["by_type"].values() for v in (t["count"], t["mib"])))
               if live else ())]
    if not all(good(v) for v in sizes) or not isinstance(found.get("per_second", []), list):
        raise TypeError("resource_allocations holds a number that cannot be a count or a size")  # reads_recordings
    live_types = (live or {}).get("by_type") or {}
    types = []
    for name, got in sorted(found["by_type"].items(), key=lambda kv: -kv[1]["mib"])[:top]:
        here = (live_types.get(name) or {"count": 0, "mib": 0.0}) if live else None
        types.append({"type": name,
                      "allocated": {"count": got["count"], "mib": got["mib"],
                                    "mean_mib": round(got["mib"] / got["count"], 3) if got["count"] else None},
                      "live": {"count": here["count"], "mib": here["mib"]} if here else None,
                      "live_share_pct": round(100 * here["mib"] / got["mib"], 1) if here and got["mib"] else None,
                      "gone": max(got["count"] - here["count"], 0) if here else None})
    after, seconds = found.get("after_3s") or {}, len(found.get("per_second") or []) - 3
    return {"run": run, "events": found["events"], "allocated_mib": found["mib"], "per_frame": found.get("per_frame"),
            "types": types,
            "live": {"count": live.get("count"), "mib": live.get("mib"), "by_mode": live.get("by_mode") or {}} if live else None,
            "freed": found.get("freed"), "freed_before_recording": found.get("freed_before_recording"),
            "allocated_mib_per_live_mib": round(found["mib"] / live["mib"], 2) if live and live.get("mib") else None,
            "events_per_s_after_3s": round(after["count"] / seconds, 1) if after.get("count") is not None and seconds > 0 else None,
            "peak_metal_mib": (s.get("metal_memory_mib") or {}).get("peak"),
            "how_to_read": ("live is a lower bound (what was allocated before the recording does not show); a type with a "
                           "large allocated size and a small live share is created and dropped over and over; events "
                           "without a resource id are never counted as live, so `gone` can include them" if live else
                           "this recording predates the live numbers: record it again to see what stayed allocated")}
