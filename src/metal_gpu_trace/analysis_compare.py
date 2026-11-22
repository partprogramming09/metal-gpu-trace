"""Comparing summaries: perf_compare's numbers and Markdown, the notes on unpresented or noisy runs, and the metric
ranges a perf_check verdict is judged against. Part of analysis, which re-exports these names."""
from metal_gpu_trace import metrics, paths, recording


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
    powers = [(s.get("machine") or {}).get("power") for s in (sa, sb)]
    if all(powers):
        starts = [p["start"] for p in powers]
        moved = [r for r, p in zip((a, b), powers) if p.get("changed")]
        differ = [k for k in ("low_power_mode", "thermal_warning")
                  if None not in (starts[0].get(k), starts[1].get(k)) and starts[0][k] != starts[1][k]]
        if differ or moved:
            result["power"] = {"a": starts[0], "b": starts[1], **({"changed_in": moved} if moved else {}),
                               "note": ("the runs were recorded with different low power mode or thermal state (the Mac "
                                        "lowers its clocks), so FPS and GPU ms are not comparable; record both with low "
                                        "power mode off and the Mac cool" if differ else
                                        "low power mode or the thermal state changed during a recording (changed_in): the "
                                        "run is not steady, repeat it") }
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
