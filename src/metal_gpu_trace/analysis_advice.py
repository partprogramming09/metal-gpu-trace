"""Advice from a recording: the display rate its frames lock to, the actions perf_diagnose suggests and the reason
entries of a verdict. Part of analysis, which re-exports these names."""
import math

from metal_gpu_trace import paths


def reason(metric, value, lo, hi):
    """Returns one verdict reason: the metric, the run's value and the reference's range."""
    return {"metric": metric, "value": value, "range_min": lo, "range_max": hi}


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
