"""Fixed budgets in a versioned file: `metal-gpu-trace gate RUN [--budgets FILE]` judges a recording against them.

The file lives in the project's repository, so CI in any project can say "FPS never below 55, p95 GPU ms never over
12.5" without naming a project or a machine; `perf_check` compares against a reference of this machine instead."""
import json
import math
import pathlib

from metal_gpu_trace import analysis, paths

FILE_NAME = "metal-gpu-trace.budgets.json"
VERSION = 1
LIMITS = ("min", "max")
FRAMES_MIN = 100  # under this many frames a recording is too short to judge
# the metrics a budget may name and where each lives in a summary; the two p95 rows are kept out of analysis.HISTORY
# because those columns are perf_history's
METRICS = {**analysis.HISTORY, "gpu_ms_p95": ("gpu", "frame_gpu_ms", "p95"),
           "frame_interval_ms_p95": ("gpu", "frame_interval_ms", "p95")}


def _number(value):
    """Returns `value` when it is a finite number a summary or a budgets file holds; None for a bool, NaN, infinity,
    a string or a mapping such as `{"comparable": false}`."""
    try:
        return value if type(value) in (int, float) and math.isfinite(value) else None
    except OverflowError:  # an integer too large for a float
        return None


def load(path=None):
    """Returns the budgets a recording must meet, `{metric: {"min": n, "max": n}}` in the file's order, read from
    `path` (the default file name in the current folder). Raises ToolError, saying how to fix it and naming no folder,
    when the file is missing, is not JSON or is not the version 1 shape."""
    path = pathlib.Path(path) if path is not None else pathlib.Path(FILE_NAME)
    name = path.name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise paths.ToolError(f"no budgets file {name}: add one to the project (version 1) or pass --budgets FILE") from None
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):  # also UnicodeDecodeError
        raise paths.ToolError(f"{name} is not valid JSON; fix it or write a version {VERSION} file") from None
    if not isinstance(data, dict):
        raise paths.ToolError(f"{name} must be one JSON object with version and budgets; see the gate section of the "
                              "README for the version 1 shape")
    unknown = sorted(set(data) - {"version", "budgets"})
    if unknown:
        raise paths.ToolError(f"{name} holds {', '.join(repr(key[:40]) for key in unknown[:5])} beside version and "
                              f"budgets: a version {VERSION} file has only those two")
    if type(data.get("version")) is not int or data["version"] != VERSION:
        raise paths.ToolError(f"{name} has version {data.get('version')!r}: this gate reads version {VERSION}")
    budgets = data.get("budgets")
    if not isinstance(budgets, dict) or not budgets:
        raise paths.ToolError(f'{name} needs "budgets" with at least one metric, such as {{"fps": {{"min": 55}}}}')
    for metric, limits in budgets.items():
        if metric not in METRICS:
            raise paths.ToolError(f"{name} budgets {metric}, which is not measured here; the metrics are "
                                  f"{', '.join(METRICS)}")
        if not isinstance(limits, dict):
            raise paths.ToolError(f'the {metric} budget is an object with "min", "max" or both, such as {{"max": 12.5}}')
        extra = sorted(set(limits) - set(LIMITS))
        if extra:
            raise paths.ToolError(f"the {metric} budget holds {', '.join(repr(key[:40]) for key in extra)}: only min "
                                  "and max are read")
        if not limits:
            raise paths.ToolError(f'the {metric} budget needs "min", "max" or both')
        for kind in LIMITS:
            if kind in limits and _number(limits[kind]) is None:
                raise paths.ToolError(f"the {metric} budget has {kind} {limits[kind]!r}: give a finite number")
        if "min" in limits and "max" in limits and limits["min"] > limits["max"]:
            raise paths.ToolError(f"the {metric} budget has min {limits['min']} above max {limits['max']}: swap them")
    return {metric: {kind: limits[kind] for kind in LIMITS if kind in limits} for metric, limits in budgets.items()}


def gate(run, path=None):
    """Judges `run` against the budgets in `path`: returns `{"run", "verdict", "results"}`, one result per budget in
    the file's order, each `{"metric", "value", "min"?, "max"?, "status"}`, where the status is `ok`, `over` its max or
    `under` its min. Raises ToolError, saying how to fix it, when the budgets cannot be read, the run does not exist,
    it has under 100 frames, its program stopped presenting or a budgeted metric cannot be measured."""
    wanted = load(path)
    s = analysis.steady_summary(run)
    frames = _number(analysis.dig(s, ("gpu", "frames")))
    if frames is None or frames < FRAMES_MIN:
        raise paths.ToolError(f"{run} has " + (f"{frames:g} frames" if frames is not None else "no frame count") +
                              f": under {FRAMES_MIN} frames is too short to judge; record 30 s or more")
    if analysis.unpresented(**{run: s}):
        stall = analysis.dig(s, ("gpu", "unpresented", "from_s"))
        where = f" at {stall:g} s" if _number(stall) is not None else ""
        raise paths.ToolError(f"the program of {run} stopped presenting{where}: record it again with the window visible")
    values = {metric: _number(analysis.dig(s, where)) for metric, where in METRICS.items() if metric in wanted}
    missing = [metric for metric in wanted if values[metric] is None]
    if missing:
        raise paths.ToolError(f"{', '.join(missing)} cannot be measured in {run}: record it again with this version, "
                              "or take that budget out of the budgets file")
    results = []
    for metric, limits in wanted.items():
        value = values[metric]
        status = "ok"
        if "max" in limits and value > limits["max"]:
            status = "over"
        elif "min" in limits and value < limits["min"]:
            status = "under"
        results.append({"metric": metric, "value": value, **limits, "status": status})
    return {"run": run, "verdict": "pass" if all(r["status"] == "ok" for r in results) else "fail",
            "results": results}
