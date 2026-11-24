"""The budget file `gate` reads: version 1, the metrics it may name, and the verdict for each limit."""
import json

import support  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import config, paths


def summary(**gpu):
    """A recording's summary with a number for every metric a budget may name; `gpu` overrides its gpu block."""
    return {"gpu": {"frames": 300, "fps_estimate": 60.0, "fps_1pct_low": 48.0,
                    "frame_gpu_ms": {"mean": 4.3, "p95": 8.0}, "frame_interval_ms": {"p95": 20.0},
                    "stutter_rate_pct": 0.4, **gpu},
            "hitches": {"count": 2}, "metal_memory_mib": {"peak": 420.5}}


def budgets_file(folder, data, name="metal-gpu-trace.budgets.json"):
    """Writes `data` (a dict, or text exactly as given) as the budgets file in `folder` and returns its path."""
    path = folder / name
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def gate(tmp_path, run="r", gpu=None, data=None):
    """Records `r` with `summary(**gpu)` in `tmp_path/runs`, judges it for `gate` against `data` (a v1 file naming
    every metric) and returns the verdict; config.OUT follows the folder for the length of the call."""
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run}.json").write_text(json.dumps(summary(**(gpu or {}))), encoding="utf-8")
    path = budgets_file(tmp_path, data or {"version": 1, "budgets": {"fps": {"min": 55}}})
    saved, config.OUT = config.OUT, runs
    try:
        from metal_gpu_trace import budgets
        return budgets.gate(run, path)
    finally:
        config.OUT = saved


def test_a_recording_within_its_limits_passes(tmp_path):
    """Every number inside its limit is `pass`: 0 in the command; the results keep the file's order and its limits."""
    from metal_gpu_trace import budgets
    got = gate(tmp_path, data={"version": 1, "budgets": {"fps": {"min": 55}, "gpu_ms_p95": {"max": 12.5},
                                                       "frame_interval_ms_p95": {"min": 10, "max": 25}}})
    assert got == {"run": "r", "verdict": "pass", "results": [
        {"metric": "fps", "value": 60.0, "min": 55, "status": "ok"},
        {"metric": "gpu_ms_p95", "value": 8.0, "max": 12.5, "status": "ok"},
        {"metric": "frame_interval_ms_p95", "value": 20.0, "min": 10, "max": 25, "status": "ok"}]}
    assert budgets.METRICS["gpu_ms_p95"] == ("gpu", "frame_gpu_ms", "p95")


def test_a_number_over_its_max_or_under_its_min_fails_with_its_status(tmp_path):
    """A number above its `max` is `over` and one below its `min` is `under`: either fails the recording (1)."""
    got = gate(tmp_path, gpu={"fps_estimate": 50.0, "frame_gpu_ms": {"mean": 4.3, "p95": 13.0}},
               data={"version": 1, "budgets": {"fps": {"min": 55}, "gpu_ms_p95": {"max": 12.5},
                                              "hitches": {"max": 5}}})
    assert got["verdict"] == "fail", got
    assert [(r["metric"], r["status"]) for r in got["results"]] == [
        ("fps", "under"), ("gpu_ms_p95", "over"), ("hitches", "ok")], got
    assert got["results"][0]["value"] == 50.0 and got["results"][1]["value"] == 13.0


def test_a_budget_with_both_limits_holds_between_them(tmp_path):
    """`min` and `max` together: the value inside is ok, and above or below says which side it left."""
    data = {"version": 1, "budgets": {"fps": {"min": 55, "max": 65}}}
    assert gate(tmp_path, data=data)["results"][0]["status"] == "ok"

    over = gate(tmp_path, gpu={"fps_estimate": 70.0}, data=data)["results"][0]
    assert over["status"] == "over" and over["min"] == 55 and over["max"] == 65, over

    under = gate(tmp_path, gpu={"fps_estimate": 50.0}, data=data)["results"][0]
    assert under["status"] == "under" and under["value"] == 50.0, under


def test_a_metric_the_recording_cannot_measure_is_never_a_pass(tmp_path):
    """A budget without a number does not pass in silence: the call raises ToolError naming the metric and the two
    ways to fix it, also when the summary marks the metric not comparable."""
    from metal_gpu_trace import budgets
    runs = tmp_path / "runs"
    runs.mkdir()
    path = budgets_file(tmp_path, {"version": 1, "budgets": {"fps_1pct_low": {"min": 30}}})
    saved, config.OUT = config.OUT, runs
    try:
        (runs / "r.json").write_text(json.dumps(summary(fps_1pct_low=None)), encoding="utf-8")
        with_missing = assert_tool_error(lambda: budgets.gate("r", path))
        assert "fps_1pct_low" in with_missing and "record" in with_missing, with_missing

        (runs / "r.json").write_text(json.dumps(summary(fps_1pct_low={"comparable": False, "reason": "Windows"})),
                                     encoding="utf-8")
        not_comparable = assert_tool_error(lambda: budgets.gate("r", path))
        assert "fps_1pct_low" in not_comparable, not_comparable
    finally:
        config.OUT = saved


def test_a_missing_budgets_file_says_which_one_and_how_to_write_it(tmp_path):
    """No file at the path: ToolError with the file's name (never the folder) and the way out."""
    from metal_gpu_trace import budgets
    error = assert_tool_error(lambda: budgets.load(tmp_path / "metal-gpu-trace.budgets.json"))
    assert "metal-gpu-trace.budgets.json" in error and "--budgets" in error, error
    assert str(tmp_path) not in error


def test_a_budgets_file_of_another_version_or_shape_is_refused(tmp_path):
    """Every malformed file is a format error that says what to fix, never a crash and never a path."""
    from metal_gpu_trace import budgets
    for data, said in (
            ('{"version": 1, "budgets": {"fps": {', "not valid JSON"),
            ("[]", "JSON object"),
            ('"text"', "JSON object"),
            ({"version": 2, "budgets": {"fps": {"min": 1}}}, "version 1"),
            ({"version": True, "budgets": {"fps": {"min": 1}}}, "version 1"),
            ({"budgets": {"fps": {"min": 1}}}, "version"),
            ({"version": 1}, "budgets"),
            ({"version": 1, "budgets": {}}, "at least one"),
            ({"version": 1, "budgets": [], "extra": 1}, "budgets"),
            ({"version": 1, "budgets": {"frame_time_ms": {"max": 5}}}, "frame_time_ms"),
            ({"version": 1, "budgets": {"fps": {"min": 1, "note": "x"}}}, "note"),
            ({"version": 1, "budgets": {"fps": {}}}, "min"),
            ({"version": 1, "budgets": {"fps": {"min": 70, "max": 60}}}, "above"),
            ({"version": 1, "budgets": {"fps": {"min": True}}}, "number"),
            ({"version": 1, "budgets": {"fps": {"max": "12"}}}, "number"),
            ('{"version": 1, "budgets": {"fps": {"min": NaN}}}', "number"),
            ({"version": 1, "budgets": {"fps": {"min": 1}}, "note": "x"}, "note")):
        error = assert_tool_error(lambda data=data: budgets.load(budgets_file(tmp_path, data)))
        assert said in error, (data, error)
        assert str(tmp_path) not in error, (data, error)


def test_a_recording_under_100_frames_is_not_judged(tmp_path):
    """Under 100 frames the run is too short: ToolError saying so, never a pass."""
    from metal_gpu_trace import budgets
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "r.json").write_text(json.dumps(summary(frames=99)), encoding="utf-8")
    path = budgets_file(tmp_path, {"version": 1, "budgets": {"fps": {"min": 55}}})
    saved, config.OUT = config.OUT, runs
    try:
        error = assert_tool_error(lambda: budgets.gate("r", path))
        assert "under 100 frames" in error and "99" in error, error
    finally:
        config.OUT = saved


def test_a_program_that_stopped_presenting_is_not_judged(tmp_path):
    """A run whose program stopped drawing counts no frames there: ToolError naming the stall and the way out."""
    from metal_gpu_trace import budgets
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "r.json").write_text(json.dumps(summary(unpresented={"from_s": 12.0, "span_s": 8.0})),
                                 encoding="utf-8")
    path = budgets_file(tmp_path, {"version": 1, "budgets": {"fps": {"min": 55}}})
    saved, config.OUT = config.OUT, runs
    try:
        error = assert_tool_error(lambda: budgets.gate("r", path))
        assert "stopped presenting" in error and "12" in error, error
    finally:
        config.OUT = saved


def test_an_unknown_recording_is_not_judged(tmp_path):
    """No such recording: ToolError naming the run and the tool that lists them."""
    from metal_gpu_trace import budgets
    path = budgets_file(tmp_path, {"version": 1, "budgets": {"fps": {"min": 55}}})
    error = assert_tool_error(lambda: budgets.gate("nope", path))
    assert "no run" in error and "nope" in error, error
    assert str(tmp_path) not in error


def test_an_older_summary_reads_as_unmeasurable_not_as_a_crash(tmp_path):
    """A generation 1 or 2 summary without the newer keys: a metric it holds is judged, a missing one is a ToolError."""
    from metal_gpu_trace import budgets
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "old.json").write_text(json.dumps({"schema_version": 2, "gpu": {"frames": 300, "fps_estimate": 58.0}}),
                                   encoding="utf-8")
    saved, config.OUT = config.OUT, runs
    try:
        old_path = budgets_file(tmp_path, {"version": 1, "budgets": {"fps": {"min": 55}}})

        assert budgets.gate("old", old_path)["verdict"] == "pass"

        new_path = budgets_file(tmp_path, {"version": 1, "budgets": {"gpu_ms_p95": {"max": 12.5}}})
        error = assert_tool_error(lambda: budgets.gate("old", new_path))
        assert "gpu_ms_p95" in error, error
    finally:
        config.OUT = saved


def test_the_two_new_metrics_do_not_change_what_history_returns():
    """`gpu_ms_p95` and `frame_interval_ms_p95` live in the budget table, not in `analysis.HISTORY` (whose columns are
    perf_history's), and the allowed metrics are exactly the eight of the format."""
    from metal_gpu_trace import analysis, budgets
    assert budgets.METRICS["gpu_ms_p95"] == ("gpu", "frame_gpu_ms", "p95")
    assert budgets.METRICS["frame_interval_ms_p95"] == ("gpu", "frame_interval_ms", "p95")
    assert "gpu_ms_p95" not in analysis.HISTORY and "frame_interval_ms_p95" not in analysis.HISTORY
    assert set(budgets.METRICS) == {"fps", "fps_1pct_low", "gpu_ms_mean", "stutter_rate_pct", "hitches",
                                    "metal_mib_peak", "gpu_ms_p95", "frame_interval_ms_p95"}


def assert_tool_error(call):
    """Runs `call`, which must raise paths.ToolError, and returns its message."""
    try:
        call()
    except paths.ToolError as error:
        return str(error)
    raise AssertionError("ToolError was not raised")
