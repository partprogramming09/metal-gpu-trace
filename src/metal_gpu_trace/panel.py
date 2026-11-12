"""The HTML panel that shows one or two runs."""
import functools
import json

from metal_gpu_trace import analysis, config, paths, recording


PANEL_PRESETS = ("fps", "compare")
SECTIONS = ("frames", "hitches", "lows", "encoders", "counters", "memory", "thermal", "cpu")
REASONS = ("no_frames_file", "metal_only", "record_with_counters", "start_skipped", "not_in_recording")


def sections(s, has_frames, has_encoders, has_memory):
    """Returns which of SECTIONS a recording has data for and why the others are missing, as (has, missing): the
    reason is no_frames_file, metal_only (Windows has no encoders, Metal memory or counters), record_with_counters
    (a Metal run recorded without them), start_skipped (a skip_s cut drops the CPU use) or not_in_recording."""
    windows = analysis.measurement(s) == "windows"
    has = {"frames": has_frames, "hitches": (s.get("hitches") or {}).get("count") is not None,
           "lows": (s.get("gpu") or {}).get("fps_1pct_low") is not None, "encoders": has_encoders,
           "counters": s.get("gpu_counters") is not None, "memory": has_memory or (windows and bool(s.get("process_rss_mib"))),
           "thermal": s.get("thermal_state_share") is not None, "cpu": (s.get("cpu") or {}).get("mean") is not None}
    special = {"frames": "no_frames_file", "encoders": "metal_only" if windows else None, "memory": "metal_only" if windows else None,
               "counters": "metal_only" if windows else "record_with_counters", "cpu": "start_skipped" if s.get("steady") else None}
    missing = [{"id": i, "reason": special.get(i) or "not_in_recording"} for i in SECTIONS if not has[i]]
    return has, missing


@functools.lru_cache(maxsize=None)
def panel_html(connect_self):
    """Returns the text of the panel page, with no data in it. `connect_self` is true for the live panel that
    http_transport serves, whose page may fetch its data from the server it came from; the saved panel file loads
    nothing."""
    page = (config.PACKAGE_DIR / "data" / "panel.html").read_text(encoding="utf-8")
    return page.replace("default-src 'none'", "default-src 'none'; connect-src 'self'") if connect_self else page


def panel_run(run, skip_s=0):
    """Returns what the panel shows for one recording: numbers and labels from its summary, its GPU frames and Metal
    memory cut to PANEL_POINTS points that keep every hitch, and no path. With `skip_s`, as steady_summary. A run
    with no frames.csv has the numbers of its summary and no curves; with `skip_s` it is an error, as in steady_summary."""
    s = analysis.steady_summary(run, skip_s)
    rows = analysis.read_frames(run) if (config.OUT / f"{run}.frames.csv").exists() else []
    has_frames = bool(rows)
    if s.get("steady") and rows:
        cut = rows[0][1] + s["steady"]["skip_s"] * 1000
        rows = [r for r in rows if r[1] >= cut]
    hitches = s.get("hitches") or {}
    limit, causes = hitches.get("threshold_ms"), {h["frame"]: h for h in hitches.get("worst", [])}
    marks = [[b[1], b[2], round(b[1] - a[1], 3), causes.get(b[0], {}).get("cause", ""), causes.get(b[0], {}).get("cpu_pct")]
             for a, b in zip(rows, rows[1:]) if limit and b[1] - a[1] > limit - analysis.CSV_TOL_MS]
    marked = {m[0] for m in marks}
    stride = max(1, len(rows) // config.PANEL_POINTS)
    frames = [[t, ms] for i, (_, t, ms) in enumerate(rows) if i % stride == 0 or t in marked]
    samples = analysis.read_memory(run)
    if s.get("steady") and rows:
        samples = [x for x in samples if x[0] >= rows[0][1]]
    memory = [[t, round(mib, 2)] for t, mib in samples[::max(1, len(samples) // config.PANEL_POINTS)]]
    encoders = [] if analysis.measurement(s) == "windows" else (s.get("encoders") or {}).get("by_label", [])[:20]
    has, missing = sections(s, has_frames, bool(encoders), bool(memory))
    return {"has": has, "missing": missing, "name": run, "layer": recording.layer_label(s.get("layer")), "source": analysis.measurement(s), "gpu": s.get("gpu"), "hitches": hitches,
            "thermal_state_share": s.get("thermal_state_share"), "metal_memory_mib": s.get("metal_memory_mib"),
            "process_rss_mib": s.get("process_rss_mib"), "cpu": s.get("cpu"), "counters": s.get("gpu_counters"), "frames": frames, "marks": marks, "memory": memory,
            "encoders": encoders}


RULES = {"min_frames": 100, "min_seconds_wine": 30, "noise_pct": 3}
LOWER_IS_BETTER = {"fps": False, "gpu_ms_mean": True}


def direction(metric, change):
    """Returns better, worse or same for a comparison entry of `metric` (the panel's own rule: under noise_pct is
    same), or None when it cannot be told."""
    if not change or change.get("change") is None or metric not in LOWER_IS_BETTER:
        return None
    pct = change.get("change_pct")
    if change["change"] == 0 or (pct is not None and abs(pct) < RULES["noise_pct"]):
        return "same"
    return "better" if (change["change"] < 0) == LOWER_IS_BETTER[metric] else "worse"


def warnings_for(runs, summaries, data, skip, compare, not_comparable):
    """Returns the confidence warnings as [{"id", "run"}], each once: skip_applied, few_frames, short_wine and
    summary_only per run, and, for two runs, single_run_each, layers_differ, windows_vs_metal and gpu_not_limit."""
    out = [{"id": "skip_applied", "run": None}] if skip else []
    for name, s, d in zip(runs, summaries, data):
        if ((s.get("gpu") or {}).get("frames") or 0) < RULES["min_frames"]:
            out.append({"id": "few_frames", "run": name})
        duration = s.get("duration_s")
        if "wine" in (s.get("layer") or {}) and duration is not None and duration < RULES["min_seconds_wine"]:
            out.append({"id": "short_wine", "run": name})
        if not d["has"]["frames"]:
            out.append({"id": "summary_only", "run": name})
    if len(runs) == 2:
        out.append({"id": "single_run_each", "run": None})
        if len({recording.layer_label(s.get("layer")) or "native" for s in summaries}) == 2:
            out.append({"id": "layers_differ", "run": None})
        if not_comparable:
            out.append({"id": "windows_vs_metal", "run": None})
        if compare and not not_comparable and direction("fps", compare.get("fps")) == "worse" and direction("gpu_ms_mean", compare.get("gpu_ms_mean")) == "better":
            out.append({"id": "gpu_not_limit", "run": None})
    return list({(w["id"], w["run"]): w for w in out}.values())


def tests_mode(runs, baseline):
    """Returns (tests, hint): perf_check's verdict for each run against the project's reference `baseline`, with the
    reference's runs, skip_s, range and spread, or (None, why) when there is no reference to judge against. A run
    perf_check cannot judge carries its reason; the others are unaffected."""
    if baseline is None:
        return None, "no_project_baseline"
    try:
        saved = analysis.load_baselines().get(baseline)
        span = analysis.ranges(saved["summaries"]) if saved else None
        runs_of_reference = list(saved["runs"]) if saved else None
    except (ValueError, KeyError, TypeError, AttributeError, OSError):  # baselines.json that is not a reference file
        saved = None
    if saved is None:
        return None, "baseline_not_found"
    checks = {}
    for run in runs:
        try:
            result = analysis.tool_perf_check(run, baseline, margin_pct=RULES["noise_pct"])
            checks[run] = {k: result[k] for k in ("verdict", "regressed", "improved", "unchecked")}
            seen = analysis.steady_summary(run, saved.get("skip_s", 0))
            checks[run]["values"] = {m: metric_value(m, seen) for m in analysis.CHECKED}
            if len(result["unchecked"]) == len(analysis.CHECKED):  # perf_check says same when it checked nothing
                checks[run] = {"verdict": None, "error": f"{run} has no number perf_check can judge; record it again"}
        except paths.ToolError as error:
            checks[run] = {"verdict": None, "error": str(error)}
        except (KeyError, TypeError):  # a summary from before the numbers the verdict reads
            checks[run] = {"verdict": None, "error": f"{run} cannot be judged; record it again"}
    return {"baseline": baseline, "runs": runs_of_reference, "skip_s": saved.get("skip_s", 0), "range": span,
            "spread_pct": analysis.spreads(span), "checks": checks}, None


CHANGE_METRICS = (*analysis.CHECKED, "metal_mib_peak")


def metric_value(metric, s):
    """Returns a summary's value of one of CHANGE_METRICS, or None when it lacks it."""
    try:
        return s.get("metal_memory_mib", {}).get("peak") if metric == "metal_mib_peak" else analysis.CHECKED[metric][0](s)
    except (KeyError, TypeError, AttributeError):
        return None


def changes_against(baseline, limit=8):
    """Returns how the newest `limit` recordings of the reference's program (same process.arguments, not the
    reference's own runs, oldest first) stand against the reference `baseline`: its mean, min and max per metric and,
    per run, the value, its % against the mean and its direction (better, worse or same by analysis.judge, which is
    perf_check's rule; None where perf_check does not judge: Metal memory, a number the run lacks, or a Windows run
    against a Metal reference except for FPS). A run that cannot be read the way the reference was saved (it lacks the
    frames a skip_s needs) is left out. No path travels."""
    saved = analysis.load_baselines().get(baseline)
    if saved is None:
        raise paths.ToolError(f"no reference {baseline}; perf_baseline with no arguments lists them")
    first, skip = saved["summaries"][0], saved.get("skip_s", 0)
    span = analysis.ranges(saved["summaries"])
    reference = {}
    for metric in CHANGE_METRICS:
        values = [metric_value(metric, s) for s in saved["summaries"]]
        reference[metric] = None if None in values else {"mean": round(sum(values) / len(values), 3), "min": min(values), "max": max(values)}
    program = (first.get("process") or {}).get("arguments")
    found = []
    if program is None:  # no program to match: every summary without one would match
        return {"metrics": list(CHANGE_METRICS), "reference": reference, "runs": []}
    for path in config.OUT.glob("*.json"):
        if path.name in (config.BASELINES.name, "panel.json") or path.stem in saved["runs"]:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        process = raw.get("process") if isinstance(raw, dict) else None
        if isinstance(process, dict) and process.get("arguments") == program:
            found.append((path.stat().st_mtime, path.stem))
    runs = []
    for _, name in sorted(found, reverse=True)[:limit][::-1]:
        try:
            s = analysis.steady_summary(name, skip)
        except paths.ToolError:
            continue
        cross = analysis.measurement(first) != analysis.measurement(s)
        values = {}
        for metric in CHANGE_METRICS:
            value, mean = metric_value(metric, s), (reference[metric] or {}).get("mean")
            judged = metric in analysis.CHECKED and not (cross and metric != "fps")
            values[metric] = {"value": value, "pct": round(100 * (value - mean) / mean, 1) if value is not None and mean else None,
                              "direction": analysis.judge(metric, value, span[metric], RULES["noise_pct"]) if judged else None}
        runs.append({"run": name, "values": values})
    return {"metrics": list(CHANGE_METRICS), "reference": reference, "runs": runs}


TAB_IDS = ("tests", "summary", "ab", "frames", "encoders", "counters", "memory", "data")


def read_layout():
    """Returns the panel layout saved as panel.json in the runs directory, a list of {id, on} sections, or None when there
    is none; a file that is not that list raises ToolError. A file from before a section existed is valid: the page
    shows the sections it does not name."""
    path = config.OUT / "panel.json"
    if not path.exists():
        return None
    try:
        layout = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise paths.ToolError("panel.json is not valid JSON") from None
    if not isinstance(layout, list) or not all(isinstance(w, dict) and w.get("id") in TAB_IDS and isinstance(w.get("on"), bool) for w in layout):
        raise paths.ToolError(f"panel.json is a list of {{\"id\": tab, \"on\": true or false}} with tab one of {', '.join(TAB_IDS)}")
    return [{"id": w["id"], "on": w["on"]} for w in layout]


def panel_data(runs, preset=None, skip_s=0):
    """Returns the payload a panel shows for one or two runs: the preset, each run's panel_run and, for two runs, the
    headline comparison. `preset` defaults to compare for two runs and fps for one; `skip_s` leaves out the start-up."""
    preset = preset or ("compare" if len(runs) == 2 else "fps")
    if preset not in PANEL_PRESETS:
        raise paths.ToolError(f"preset is one of {', '.join(PANEL_PRESETS)}")
    if not 1 <= len(runs) <= 2 or (preset == "compare" and len(runs) != 2):
        raise paths.ToolError("runs holds one or two run names from perf_runs; the compare preset needs two")
    skip = paths.check_skip(skip_s)
    data = [panel_run(r, skip) for r in runs]
    summaries = [analysis.steady_summary(r, skip) for r in runs]
    compare, not_comparable, labels = None, [], []
    if len(runs) == 2:
        try:
            result = analysis.compare_summaries(summaries[0], summaries[1], *runs)
            compare, not_comparable = result["metrics"], (result.get("measure") or {}).get("not_comparable", [])
            labels = result.get("labels") or []
        except (KeyError, TypeError):  # a summary from before the numbers the comparison reads
            pass
    project = config.PROJECT or {}
    profile = project.get("profile", "generic")
    tests, tests_hint = tests_mode(runs, project.get("baseline"))
    warnings = warnings_for(runs, summaries, data, skip, compare, not_comparable)
    if tests and tests["skip_s"] != skip:
        warnings.append({"id": "reference_skip", "run": None})
    return {"preset": preset, "runs": data, "compare": compare, "not_comparable": not_comparable, "labels": labels[:10],
            "skip_s": skip, "layout": read_layout(), "project": {"name": project.get("name"), "profile": profile},
            "primary": "gpu_ms_mean" if profile == "translation-layer" else "fps", "rules": dict(RULES),
            "warnings": warnings, "tests": tests, "tests_hint": tests_hint,
            "changes": changes_against(tests["baseline"]) if tests else None}


def tool_perf_panel(name, runs, preset="fps", skip_s=0, layout=None):
    """Writes one HTML file, `<name>.panel.html` in the runs directory, that shows one or two recordings in a
    browser without a server: GPU time per frame with the hitches marked, the numbers (FPS and its lows, frame
    time, jitter, stutter, memory, thermal state), Metal memory over time and, for two runs, A against B. The file
    holds the data itself, no path, and loads nothing from the network; the viewer can hide and reorder the
    widgets and export the layout as JSON. preset `fps` is the timeline, numbers and memory; `compare` (two runs)
    puts A against B first. skip_s leaves out the first seconds of each recording (the start-up), as perf_compare does.
    layout (tab ids in the order to show) is saved as panel.json in the runs directory and becomes the default tab
    order of every panel, the live one too, until the viewer changes it in the browser; ids left out are hidden but
    can be switched back on; tabs are tests (each run against the project's reference), summary, ab, frames, encoders, counters,
    memory and data (a panel.json that does not name tests shows it first; one that leaves out any other keeps it hidden),
    and a panel.json you wrote yourself, or copied from the panel's Layout JSON, works the same.
    Returns the file name, the runs, the frames shown and the file's bytes."""
    if not paths.name_ok(name):
        raise paths.ToolError("a panel name holds only letters, digits, '.', '_' and '-'")
    if layout is not None:
        if isinstance(layout, str) or not all(i in TAB_IDS for i in layout):
            raise paths.ToolError(f"layout is a list of tabs, each one of {', '.join(TAB_IDS)}")
        config.OUT.mkdir(parents=True, exist_ok=True)
        (config.OUT / "panel.json").write_text(json.dumps([{"id": i, "on": True} for i in dict.fromkeys(layout)] +
                                                   [{"id": i, "on": False} for i in TAB_IDS if i not in layout]) + "\n", encoding="utf-8")
    payload = panel_data(runs, preset, skip_s)
    data = payload["runs"]
    text = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")
    page_html = panel_html(False).replace("/*PAYLOAD*/null", text)
    target = config.OUT / f"{name}.panel.html"
    target.write_text(page_html, encoding="utf-8")
    return {"file": target.name, "runs": list(runs), "frames": sum(len(r["frames"]) for r in data),
            "bytes": target.stat().st_size}
