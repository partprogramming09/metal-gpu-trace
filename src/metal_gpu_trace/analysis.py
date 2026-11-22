"""Reading recordings back: runs, compare, baselines, checks, gates, history and diagnosis."""
import collections
import csv
import functools
import json
import math
import statistics
import time

from metal_gpu_trace import analysis_advice, analysis_compare, config, metrics, paths, perf_report, recording, tabledb, tables

# comparing summaries lives in analysis_compare and the advice in analysis_advice; these names keep the interface
UNPRESENTED_NOTE, NOISY_NOTE = analysis_compare.UNPRESENTED_NOTE, analysis_compare.NOISY_NOTE
noisy, unpresented, markdown_report = analysis_compare.noisy, analysis_compare.unpresented, analysis_compare.markdown_report
NOT_COMPARABLE, measurement = analysis_compare.NOT_COMPARABLE, analysis_compare.measurement
gpu_state_level, memory_pressure_change = analysis_compare.gpu_state_level, analysis_compare.memory_pressure_change
compare_summaries, CHECKED, ranges = analysis_compare.compare_summaries, analysis_compare.CHECKED, analysis_compare.ranges
spreads, judge, change = analysis_compare.spreads, analysis_compare.judge, analysis_compare.change
label_changes = analysis_compare.label_changes
reason, REFRESH_RATES = analysis_advice.reason, analysis_advice.REFRESH_RATES
display_synced_hz, _number = analysis_advice.display_synced_hz, analysis_advice._number
suggested_actions, _startup_skip_s = analysis_advice.suggested_actions, analysis_advice._startup_skip_s


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
                         "trace_kept": path.with_suffix(".trace").is_dir() and not path.with_suffix(".trace").is_symlink(),
                         "tables_kept": tabledb.path_for(path.with_suffix(".trace")).is_file() and not tabledb.path_for(path.with_suffix(".trace")).is_symlink(), "layer": recording.layer_label(s.get("layer"))})
        except (paths.ToolError, *paths.MALFORMED):  # a summary still being written, or a file that is not one
            continue
    return {**paths.page(runs, offset, limit), "project": (config.PROJECT or {}).get("name")}


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


def _frames_or_none(run):
    """Returns the run's frames, or None when it has no per-frame file or it cannot be read."""
    try:
        return read_frames(run)
    except paths.ToolError:
        return None


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
        # A program locked to the display waits for it, so its GPU idle time says nothing about the CPU.
        bottleneck = "DISPLAY_SYNCED" if display_synced_hz(gpu) else "CPU_SUBMISSION_BOUND"
    elif has_frame_data and idle_share <= 0.15 and gpu_ms_mean > 0 and (
            gpu_ms_mean >= 0.80 * interval_ms_mean if interval_ms_mean > 0 else True):
        bottleneck = "GPU_BOUND"
    else:
        bottleneck = "BALANCED"

    recommendations = []
    if bottleneck == "GPU_BOUND":
        recommendations.append("Enable FSR if the GPU is saturated at 100%, or use dynamic resolution scaling.")
        recommendations.append("Lower the internal render resolution, the post-processing quality or the heavy shaders.")
    elif bottleneck == "CPU_SUBMISSION_BOUND":
        if s.get("template") == "Windows Native Trace":
            recommendations.append("Set FlipQueueSize=3 in the AMD or DirectX driver to smooth out the CPU's submission.")
        recommendations.append("Merge draw calls with instancing, or reduce geometry complexity and dynamic objects.")
    elif bottleneck == "MEMORY_PRESSURE_SUSPECTED":
        recommendations.append("Hypothesis (bandwidth is not measured): lower the shadow resolution from 2048 to 1024 to ease the UMA bus.")
        recommendations.append("Hypothesis: limit shadow cascades to 2 outdoors to reduce unified memory use.")
    if too_many_short:
        recommendations.append("Merge render passes and reduce short encoders to cut the overhead of the translation layer.")
    if stutter_verdict in ("MICRO_STUTTER", "SEVERE_STUTTER"):
        recommendations.append("Turn on a frame rate cap or vertical sync/VRR to steady the presentation intervals.")
    throttling = gpu.get("throttling_analysis") or {}
    if throttling.get("thermal_throttling_detected"):
        drift_pct = throttling.get("fps_drift_pct", 0)
        recommendations.append(f"Thermal throttling detected ({drift_pct}% FPS drop): check the fan curves and the cooling of the APU/GPU.")
    hitches = s.get("hitches") or {}
    top_cause = next(iter(hitches.get("causes") or {}), None)
    if top_cause == "shader_compile":
        recommendations.append("The hitches coincide with the graphics shader compiler: precompile or warm up the shader cache.")
    elif top_cause == "memory_growth":
        recommendations.append("The hitches coincide with Metal memory growth: check for resources loaded in the middle of play.")
    elif top_cause == "thermal":
        recommendations.append("The hitches coincide with a thermal state other than Nominal.")
    spills = s.get("shader_spills") or {}
    if spills.get("events"):
        where = f" in {spills['encoders']} encoders" if spills.get("encoders") else ""
        recommendations.append(f"There are {spills['events']} shader register spills ({spills.get('bytes', 0)} bytes{where}): "
                               "simplify or split the shader that causes them.")
    synced = display_synced_hz(gpu)
    if synced:
        recommendations.append(f"The FPS ({gpu['fps_estimate']}) matches a {synced} Hz display and the intervals are regular: "
                               "probably vsync; the GPU has headroom and drops to a lower performance state, so its ms per frame "
                               "rise: compare only runs with the same pace.")
    activity = s.get("gpu_activity") or {}
    if activity.get("gpu_recovered"):
        n = activity["recoveries"]
        recommendations.append(f"The GPU recovered {n} {'time' if n == 1 else 'times'} during the recording (the driver's "
                               "recoveryCount): a hang or a command that timed out; the numbers of this recording are not reliable.")
    if (activity.get("split_scenes") or 0) > 0:
        recommendations.append(f"The driver's SplitSceneCount counter grew by {activity['split_scenes']}: the GPU split "
                               f"{activity['split_scenes']} scenes; the cause is not measured here, compare it between recordings.")
    stalled = unpresented(**{run: s})
    if stalled:
        recommendations.insert(0, f"The program stopped presenting at {gpu['unpresented']['from_s']} s (window covered or "
                                  "minimized, or a load that presented nothing): that work does not count as frames and this "
                                  "diagnosis only covers the presented frames; record again with the window visible.")
    if bottleneck == "UNKNOWN":
        recommendations.append("No GPU activity data in this recording: there is no bottleneck verdict.")
    elif not recommendations:
        recommendations.append("Balanced performance; no critical bottlenecks detected.")

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
