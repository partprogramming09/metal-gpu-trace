"""Experiments that record several runs: baseline_record, A/B, cold/warm and sweeps."""
import re
import statistics
import sys

from metal_gpu_trace import analysis, paths, recording, workloads


def tool_perf_baseline_record(name, count=3, skip_s=0, **record):
    """Records the same program `count` times in a row with perf_record's arguments and saves the runs as the
    reference `name` for perf_check, returning the range each number spans across them. Runs are named
    `name`-1, `name`-2, ... Each recording takes its seconds plus about a minute to read back. skip_s as in
    perf_baseline: the reference leaves out each run's start-up."""
    if not paths.name_ok(name):
        raise paths.ToolError("a reference name holds only letters, digits, '.', '_' and '-'")
    paths.check_skip(skip_s)
    count = int(count)
    if not 1 <= count <= 10:
        raise paths.ToolError("count is 1 to 10")
    runs = []
    for i in range(1, count + 1):
        runs.append(recording.record_new_summary(f"{name}-{i}", **record)[0])
    return analysis.tool_perf_baseline(name, runs, skip_s)


# what perf_ab compares: where in a summary, and whether a higher number is better
AB_METRICS = {"fps_estimate": (("gpu", "fps_estimate"), True), "fps_1pct_low": (("gpu", "fps_1pct_low"), True),
              "frame_gpu_ms_mean": (("gpu", "frame_gpu_ms", "mean"), False),
              "stutter_rate_pct": (("gpu", "stutter_rate_pct"), False)}


def ab_verdict(a, b, higher_better):
    """Returns "better", "worse" or "same" for the values `b` against `a`: a change counts only when every b value lies
    outside the range the a values span, on one side, so a run's own spread never passes for an effect."""
    if not a or not b:
        return "unknown"
    if min(b) > max(a):
        return "better" if higher_better else "worse"
    if max(b) < min(a):
        return "worse" if higher_better else "better"
    return "same"


def tool_perf_ab(name, env_a, env_b, rounds=1, skip_s=0, **record):
    """Records the same program with two environments in the order A B B A (repeated `rounds` times, so drift hits both
    sides equally) and says per metric whether B is better, worse or the same as A, with every value behind it.
    env_a and env_b are NAME=VALUE pairs separated by spaces; empty means none. Runs are named `name`-a1, `name`-b1, ...
    Each recording takes its seconds plus about a minute to read back. skip_s leaves out the first seconds of every
    recording (the start-up) when the verdicts are drawn, as perf_compare does; the recordings are whole."""
    if not paths.name_ok(name):
        raise paths.ToolError("a name holds only letters, digits, '.', '_' and '-'")
    paths.check_skip(skip_s)
    rounds = int(rounds)
    if not 1 <= rounds <= 5:
        raise paths.ToolError("rounds is 1 to 5")
    recording.check_env(env_a), recording.check_env(env_b)
    runs = {"a": [], "b": []}
    for side in "abba" * rounds:
        label = f"{name}-{side}{len(runs[side]) + 1}"
        runs[side].append(recording.record_new_summary(label, env=env_a if side == "a" else env_b, **record)[0])
    return ab_report(name, env_a, env_b, runs, skip_s)


def cold_warm_report(name, first, second):
    """Builds perf_cold_warm's answer from the summaries of its two runs, each (run name, summary): per run the frames,
    hitches, their causes and the graphics compiler's busy ms, and `first_seen_hitches`, how many more shader_compile
    hitches the first run had than the second."""
    def part(run, summary):
        hitches = summary.get("hitches", {})
        return {"run": run, "frames": summary.get("gpu", {}).get("frames"), "hitches": hitches.get("count"),
                "per_minute": hitches.get("per_minute"), "causes": hitches.get("causes", {}),
                "compiler_busy_ms": summary.get("graphics_compiler", {}).get("busy_ms")}
    one, two = part(*first), part(*second)
    seen = max(0, one["causes"].get("shader_compile", 0) - two["causes"].get("shader_compile", 0))
    return {"name": name, "first": one, "second": two, "first_seen_hitches": seen,
            "extra_hitches_in_first": max(0, (one["hitches"] or 0) - (two["hitches"] or 0)),
            "hint": "the Metal shader cache is not cleared between the runs: the first run is cold only if the program's "
                    "pipelines were not built before; first_seen_hitches counts the shader_compile hitches the first run has "
                    "and the second does not, extra_hitches_in_first counts those of any cause, and start-up hitches are in both"}


def tool_perf_cold_warm(name, **record):
    """Records the same program twice in a row and says what the first run suffers that the second does not: hitches
    whose cause is a shader compile (first-seen pipelines: the first run's count minus the second's, never below 0), with
    each run's hitch count and graphics compiler time. macOS only. Runs are named `name`-first and `name`-second; each recording takes its seconds plus about a minute to read back."""
    if not paths.name_ok(name):
        raise paths.ToolError("a name holds only letters, digits, '.', '_' and '-'")
    if sys.platform == "win32":
        raise paths.ToolError("perf_cold_warm reads Metal's shader-compile and hitch tables: it runs on macOS only")
    runs = []
    for part in ("first", "second"):
        label = f"{name}-{part}"
        runs.append(recording.record_new_summary(label, **record))
    return cold_warm_report(name, *runs)


def line_fit(points):
    """Returns (intercept, slope, r2) of the least-squares line through [(x, y)], or None when x never changes."""
    mx, my = sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points)
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if not sxx:
        return None
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx
    total = sum((y - my) ** 2 for _, y in points)
    resid = sum((y - my - slope * (x - mx)) ** 2 for x, y in points)
    return my - slope * mx, slope, 1 - resid / total if total else 1.0


def sweep_values(variable, values):
    """Returns the values of a sweep checked and typed (integers for dim), or raises ToolError."""
    env_name = variable[4:] if variable.startswith("env:") else None
    if env_name is None and variable not in ("dim", "example", "api", "size"):
        raise paths.ToolError("variable is dim, example, api, size or env:NAME")
    if env_name is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise paths.ToolError("env:NAME takes a variable name of letters, digits and '_'")
    if not isinstance(values, list) or not 2 <= len(values) <= 8:
        raise paths.ToolError("values is 2 to 8 values")
    if variable == "dim":
        try:
            values = [int(v) for v in values]
        except (TypeError, ValueError) as error:
            raise paths.ToolError("dim values are whole numbers") from error
        if min(values) < 1:
            raise paths.ToolError("dim values are 1 or more")
    elif variable == "size":
        for v in values:
            workloads.check_size(v)
    elif any(not re.fullmatch(r"\S+", str(v)) for v in values):
        raise paths.ToolError("a value holds no spaces")
    return values if variable == "dim" else [str(v) for v in values]


def tool_perf_sweep(name, variable, values, rounds=1, skip_s=0, **record):
    """Records the same program once per value of one variable (dim, example, api, size, or env:NAME for an environment
    variable) and returns, per value, the median of FPS, 1 % low, GPU ms per frame and stutter, and with 3 or more
    numeric values the straight line GPU ms per frame follows (fixed ms plus ms per draw for dim, per unit otherwise)
    with its r2. With rounds above 1 the values run in opposite order every other round, so drift hits all alike.
    Runs are named `name`-<value number>-r<round>; each takes its seconds plus about a minute to read back."""
    if not paths.name_ok(name):
        raise paths.ToolError("a name holds only letters, digits, '.', '_' and '-'")
    paths.check_skip(skip_s)
    rounds = int(rounds)
    if not 1 <= rounds <= 5:
        raise paths.ToolError("rounds is 1 to 5")
    values = sweep_values(variable, values)
    if len(values) * rounds > 24:
        raise paths.ToolError("at most 24 recordings: fewer values or rounds")
    base_env = recording.check_env(record.pop("env", ""))
    runs = [[] for _ in values]
    for rnd in range(rounds):
        for i in (range(len(values)) if rnd % 2 == 0 else reversed(range(len(values)))):
            kwargs = dict(record)
            if variable.startswith("env:"):
                kwargs["env"] = " ".join(filter(None, [base_env, f"{variable[4:]}={values[i]}"]))
            else:
                kwargs[variable] = values[i]
                if base_env:
                    kwargs["env"] = base_env
            label = f"{name}-{i + 1}-r{rnd + 1}"
            runs[i].append(recording.record_new_summary(label, **kwargs)[0])
    rows, frames = [], []
    for value, names in zip(values, runs):
        summaries = [analysis.steady_summary(r, skip_s) for r in names]
        frames += [(s.get("gpu") or {}).get("frames", 0) for s in summaries]
        metrics = {}
        for key, (path, _) in AB_METRICS.items():
            found = []
            for item in summaries:
                for step in path:
                    item = item.get(step) if isinstance(item, dict) else None
                if isinstance(item, (int, float)):
                    found.append(item)
            metrics[key] = statistics.median(found) if found else None
        rows.append({"value": value, "runs": names, "metrics": metrics})
    result = {"name": name, "variable": variable, "rows": rows, "fit": None, "too_short": min(frames, default=0) < 100}
    try:
        xs = [v ** 3 if variable == "dim" else float(v) for v in values]
    except ValueError:
        xs = []
    points = [(x, r["metrics"]["frame_gpu_ms_mean"]) for x, r in zip(xs, rows) if r["metrics"]["frame_gpu_ms_mean"] is not None]
    fit = line_fit(points) if len(points) >= 3 else None
    if fit:
        result["fit"] = {"x": "dim^3" if variable == "dim" else variable, "ms_fixed": round(fit[0], 6),
                         "ms_per_unit": round(fit[1], 6), "r2": round(fit[2], 4)}
    if paths.check_skip(skip_s):
        result["skipped_s"] = paths.check_skip(skip_s)
    return result


def ab_report(name, env_a, env_b, runs, skip_s=0):
    """Builds perf_ab's answer from the summaries of its runs, named in `runs` as {"a": [...], "b": [...]}, each
    without its first `skip_s` seconds."""
    summaries = {side: [analysis.steady_summary(r, skip_s) for r in names] for side, names in runs.items()}
    metrics = {}
    for key, (path, higher) in AB_METRICS.items():
        values = {}
        for side, items in summaries.items():
            values[side] = []
            for item in items:
                for step in path:
                    item = item.get(step) if isinstance(item, dict) else None
                if isinstance(item, (int, float)):
                    values[side].append(item)
        metrics[key] = {"a": values["a"], "b": values["b"], "verdict": ab_verdict(values["a"], values["b"], higher)}
    frames = [(s.get("gpu") or {}).get("frames", 0) for items in summaries.values() for s in items]
    result = {"name": name, "env_a": env_a, "env_b": env_b, "runs": runs, "metrics": metrics,
              "too_short": min(frames, default=0) < 100}
    if paths.check_skip(skip_s):
        result["skipped_s"] = paths.check_skip(skip_s)
    return result
