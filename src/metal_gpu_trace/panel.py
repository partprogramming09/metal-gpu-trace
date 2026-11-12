"""The HTML panel that shows one or two runs."""
import functools
import json

from metal_gpu_trace import analysis, config, paths, recording


PANEL_PRESETS = ("fps", "compare")


@functools.lru_cache(maxsize=None)
def panel_html(connect_self):
    """Returns the text of the panel page, with no data in it. `connect_self` is true for the live panel that
    http_transport serves, whose page may fetch its data from the server it came from; the saved panel file loads
    nothing."""
    page = (config.PACKAGE_DIR / "data" / "panel.html").read_text(encoding="utf-8")
    return page.replace("default-src 'none'", "default-src 'none'; connect-src 'self'") if connect_self else page


def panel_run(run, skip_s=0):
    """Returns what the panel shows for one recording: numbers and labels from its summary, its GPU frames and Metal
    memory cut to PANEL_POINTS points that keep every hitch, and no path. With `skip_s`, as steady_summary."""
    s = analysis.steady_summary(run, skip_s)
    rows = analysis.read_frames(run)
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
    return {"name": run, "layer": recording.layer_label(s.get("layer")), "source": analysis.measurement(s), "gpu": s.get("gpu"), "hitches": hitches,
            "thermal_state_share": s.get("thermal_state_share"), "metal_memory_mib": s.get("metal_memory_mib"),
            "process_rss_mib": s.get("process_rss_mib"), "cpu": s.get("cpu"), "counters": s.get("gpu_counters"), "frames": frames, "marks": marks, "memory": memory,
            "encoders": [] if analysis.measurement(s) == "windows" else (s.get("encoders") or {}).get("by_label", [])[:20]}


TAB_IDS = ("summary", "ab", "frames", "encoders", "counters", "memory", "data")


def read_layout():
    """Returns the panel layout saved as panel.json in the runs directory, a list of {id, on} tabs, or None when there is
    none; a file that is not that list raises ToolError."""
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
    compare, not_comparable, labels = None, [], []
    if len(runs) == 2:
        try:
            sa, sb = (analysis.steady_summary(r, skip) for r in runs)
            result = analysis.compare_summaries(sa, sb, *runs)
            compare, not_comparable = result["metrics"], (result.get("measure") or {}).get("not_comparable", [])
            labels = result.get("labels") or []
        except (KeyError, TypeError):  # a summary from before the numbers the comparison reads
            pass
    return {"preset": preset, "runs": data, "compare": compare, "not_comparable": not_comparable, "labels": labels[:10],
            "skip_s": skip, "layout": read_layout()}


def tool_perf_panel(name, runs, preset="fps", skip_s=0, layout=None):
    """Writes one HTML file, `<name>.panel.html` in the runs directory, that shows one or two recordings in a
    browser without a server: GPU time per frame with the hitches marked, the numbers (FPS and its lows, frame
    time, jitter, stutter, memory, thermal state), Metal memory over time and, for two runs, A against B. The file
    holds the data itself, no path, and loads nothing from the network; the viewer can hide and reorder the
    widgets and export the layout as JSON. preset `fps` is the timeline, numbers and memory; `compare` (two runs)
    puts A against B first. skip_s leaves out the first seconds of each recording (the start-up), as perf_compare does.
    layout (tab ids in the order to show) is saved as panel.json in the runs directory and becomes the default tab
    order of every panel, the live one too, until the viewer changes it in the browser; ids left out are hidden but
    can be switched back on; tabs are summary, ab, frames, encoders, counters, memory and data, and a panel.json
    you wrote yourself, or copied from the panel's Layout JSON, works the same.
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
