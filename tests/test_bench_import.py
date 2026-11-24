"""`metal-gpu-trace import-bench`: a VegaFlow `bench.ps1` result becomes a schema 3 summary the readers list and
compare. Only the jitter means the same in both tools; the other pacing numbers stay null and keep VegaFlow's own
names in `vegaflow_bench`. The base case is a real result (tests/data/vegaflow-bench.json, with its BOM); the edge
cases are copies of it with one mutation, because no real file carries `clean: false` or an empty `errors`."""
import json
import os
import pathlib
import subprocess
import sys

import support  # noqa: F401  (puts src/ on sys.path)
from support import PKG
from metal_gpu_trace import analysis, bench_import, config, metrics, paths

REAL = pathlib.Path(__file__).parent / "data" / "vegaflow-bench.json"
NAME = "n09fix-chr4-off-d3d11-1-20261109-162146"


def real():
    """Returns the real result as a dict."""
    return json.loads(REAL.read_text(encoding="utf-8-sig"))


def put(folder, name, value, bom=True):
    """Writes `value` (a dict, or raw text) as `name` in `folder`, with the BOM PowerShell leaves, and returns the path."""
    text = value if isinstance(value, str) else json.dumps(value, indent=4)
    path = folder / name
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return path


class Out:
    """Points the runs folder at a fresh one for the length of a `with`."""

    def __init__(self, folder):
        self.folder = folder / "runs"
        self.folder.mkdir()

    def __enter__(self):
        self.saved = (config.OUT, config.BASELINES)
        config.OUT, config.BASELINES = self.folder, self.folder / "baselines.json"
        return self.folder

    def __exit__(self, *exc):
        config.OUT, config.BASELINES = self.saved


def refused(path):
    """Returns the ToolError message import_file raises for `path`, or fails when it imports."""
    try:
        bench_import.import_file(path)
    except paths.ToolError as error:
        return str(error)
    raise AssertionError(f"{path.name} was imported")


def test_the_real_result_becomes_a_summary_with_the_shared_shape(tmp_path):
    summary = bench_import.from_json(REAL.read_text(encoding="utf-8-sig"))
    assert summary["schema_version"] == metrics.SCHEMA_VERSION
    assert summary["label"] == "n09fix-chr4-off-d3d11-1" and summary["process"] == {"name": "Octopath_Traveler2-Win64-Shipping.exe", "arguments": None}
    assert summary["device"] == {"platform": "Windows", "os-version": "10.0.26300.0"} and summary["duration_s"] == 115
    assert summary["gpu"]["frames"] == 3078 and summary["gpu"]["frame_jitter_ms"] == 3.849
    assert summary["gpu"]["source"] == "vegaflow-bench-json"
    assert set(summary["common"]) == {"frame_pacing", "memory_pressure", "boundness", "submission_overhead", "api"}
    assert "context" not in summary and "system_info" not in summary


def test_a_name_with_another_meaning_stays_under_its_own_name():
    """VegaFlow's 1% low averages the slowest 1 %; ours is the 99th percentile: the same word, 24 % apart."""
    summary = bench_import.from_json(REAL.read_text(encoding="utf-8-sig"))
    assert summary["gpu"]["fps_1pct_low"] is None and summary["gpu"]["fps_estimate"] is None
    assert summary["gpu"]["stutter_rate_pct"] is None
    assert summary["common"]["frame_pacing"]["fps_1pct_low"] is None and summary["common"]["frame_pacing"]["frame_jitter_ms"] == 3.849
    bench = summary["vegaflow_bench"]
    assert bench["fps_1pct_low"] == 18.58 and bench["avg_fps"] == 26.78 and bench["source"] == "vegaflow bench.ps1"
    assert bench["present_mode"] == "Hardware: Legacy Flip" and len(bench["errors"]) == 10


def test_a_file_is_imported_once_and_the_second_time_is_the_same(tmp_path):
    with Out(tmp_path) as runs:
        source = put(tmp_path, NAME + ".json", real())
        assert bench_import.import_file(source) == ("imported", NAME)
        first = (runs / f"{NAME}.json").read_bytes()
        assert bench_import.import_file(source) == ("same", NAME)
        assert (runs / f"{NAME}.json").read_bytes() == first
        assert not [p for p in runs.iterdir() if p.name.startswith(".")]  # no temporary file left behind
        written = json.loads(first)
        assert written["gpu"]["source"] == "vegaflow-bench-json" and "_stamp" not in written


def test_the_file_date_is_the_date_of_the_measurement(tmp_path):
    """perf_history orders by the file's date; 7-digit fractions (PowerShell) and `Z` parse on Python 3.9 too."""
    with Out(tmp_path) as runs:
        bench_import.import_file(put(tmp_path, NAME + ".json", real()))
        assert abs(os.stat(runs / f"{NAME}.json").st_mtime - 1_794_259_428.72) < 1  # 2026-11-09T16:23:48-05:00
        for stamp in ("2026-11-09T16:23:48Z", "2026-11-09T16:23:48.7211343+00:00", "2026-11-09T16:23:48.5"):
            assert bench_import.from_json(json.dumps({**real(), "timestamp": stamp}))["vegaflow_bench"]["timestamp"] == stamp
        for stamp in ("x", None, 5, ""):
            assert "timestamp" in refused_json({**real(), "timestamp": stamp})
        no_stamp = real()
        del no_stamp["timestamp"]
        assert "timestamp" in refused_json(no_stamp)


def refused_json(value):
    """Returns the ToolError message from_json raises for `value` (a dict or raw text), or fails when it parses."""
    try:
        bench_import.from_json(value if isinstance(value, str) else json.dumps(value))
    except paths.ToolError as error:
        return str(error)
    raise AssertionError("it parsed")


def test_empty_and_not_object_inputs_are_refused(tmp_path):
    for text in ("", "   ", "\ufeff", "[]", '"x"', "null", "{", "5"):
        assert refused_json(text)
    with Out(tmp_path) as runs:
        put(tmp_path, "empty.json", "")
        assert "not valid JSON" in refused(tmp_path / "empty.json")
        assert list(runs.iterdir()) == []


def test_missing_keys_refuse_or_leave_null(tmp_path):
    for key in ("label", "frames", "seconds"):
        value = real()
        del value[key]
        assert key in refused_json(value), key
    value = real()
    del value["frametime_stddev_ms"], value["windows_build"]
    summary = bench_import.from_json(json.dumps(value))
    assert summary["gpu"]["frame_jitter_ms"] is None and summary["device"]["os-version"] is None
    assert summary["common"]["frame_pacing"]["frame_jitter_ms"] is None


def test_odd_types_are_refused_without_a_traceback():
    for frames in ("abc", -1, 0, True, None, [], {}, float("nan"), 1e400, 1.5):
        assert "frames" in refused_json(json.dumps({**real(), "frames": frames}).replace("Infinity", "1e999")), frames
    for seconds, warmup in ((5, 5), (5, 9), ("x", 1), (-3, 0), (10, -1), (10, "x")):
        assert refused_json({**real(), "seconds": seconds, "warmup_seconds": warmup}), (seconds, warmup)
    for label in ("", "a b", "../x", 5, None, "x" * 300):
        assert "label" in refused_json({**real(), "label": label}), label
    assert "process" in refused_json({**real(), "process": ""})
    assert "process" in refused_json({**real(), "process": 7})


def test_a_dirty_result_is_imported_and_never_called_noisy(tmp_path):
    """`clean` says whether the present mode held, not whether the machine was quiet: it is not `noisy_environment`."""
    for clean in (False, None):
        summary = bench_import.from_json(json.dumps({**real(), "clean": clean}))
        assert summary["vegaflow_bench"]["clean"] is clean and "noisy_environment" not in summary
    for errors in ([], None, "x", ["a"] * 10000, [1, "ok", None]):
        summary = bench_import.from_json(json.dumps({**real(), "errors": errors}))
        got = summary["vegaflow_bench"]["errors"]
        assert got is None or all(isinstance(e, str) for e in got), errors


def test_the_privacy_keys_are_never_copied(tmp_path):
    value = {**real(), "process": "C:\\Users\\someone\\games\\game.exe", "system_info": {"machine": "PC-OF-SOMEONE"}, "host": "x"}
    summary = bench_import.from_json(json.dumps(value))
    assert summary["process"]["name"] == "game.exe"
    assert "PC-OF-SOMEONE" not in json.dumps(summary) and "someone" not in json.dumps(summary)
    assert "system_info" not in summary and "system_info" not in summary["vegaflow_bench"]
    with Out(tmp_path):
        put(tmp_path, "x-equipo.json", {"label": "x", "system_info": {"machine": "PC"}})
        assert refused(tmp_path / "x-equipo.json")  # has no frames


def test_a_big_file_is_refused_before_it_is_read(tmp_path):
    with Out(tmp_path) as runs:
        big = tmp_path / "big.json"
        big.write_bytes(b" " * (1024 * 1024 + 1))
        assert "large" in refused(big)
        assert list(runs.iterdir()) == []


def test_names_a_run_cannot_take_are_refused(tmp_path):
    with Out(tmp_path) as runs:
        (runs / "baselines.json").write_text('{"kept": true}')
        for name in ("a b.json", "baselines.json", "Baselines.json", "Panel.json", "panel.json", ".hidden.json"):
            folder = tmp_path / "in"
            folder.mkdir(exist_ok=True)
            assert refused(put(folder, name, real())), name
        assert (runs / "baselines.json").read_text() == '{"kept": true}'
        assert sorted(p.name for p in runs.iterdir()) == ["baselines.json"]
        other = tmp_path / "other.txt"
        other.write_text("{}")
        assert refused(other)  # not a .json file


def test_a_different_file_under_a_taken_name_is_refused_and_the_first_stays(tmp_path):
    with Out(tmp_path) as runs:
        bench_import.import_file(put(tmp_path, NAME + ".json", real()))
        first = (runs / f"{NAME}.json").read_bytes()
        other = tmp_path / "in"
        other.mkdir()
        assert "already" in refused(put(other, NAME + ".json", {**real(), "frames": 999}))
        assert (runs / f"{NAME}.json").read_bytes() == first


def test_links_are_refused_on_both_ends(tmp_path):
    with Out(tmp_path) as runs:
        source = put(tmp_path, "real.json", real())
        link = tmp_path / "link.json"
        link.symlink_to(source)
        assert refused(link)
        (runs / "target.json").symlink_to(source)
        sent = tmp_path / "in"
        sent.mkdir()
        assert "link" in refused(put(sent, "target.json", real()))
        assert source.read_bytes().startswith(b"\xef\xbb\xbf") and json.loads(source.read_bytes().decode("utf-8-sig")) == real()


def test_a_folder_that_cannot_be_written_says_so_and_leaves_nothing(tmp_path):
    with Out(tmp_path) as runs:
        source = put(tmp_path, NAME + ".json", real())
        runs.chmod(0o500)
        try:
            if os.access(runs, os.W_OK):  # running as root: permissions do not apply
                return
            assert "permission" in refused(source) or "cannot be written" in refused(source)
        finally:
            runs.chmod(0o700)
        assert list(runs.iterdir()) == []


def test_the_readers_list_compare_and_order_the_imports(tmp_path):
    with Out(tmp_path):
        for i, stamp in enumerate(("2026-11-09T16:20:00Z", "2026-11-09T16:10:00Z", "2026-11-09T16:30:00Z")):
            name = f"n09fix-none-on-{i}-20261109-16{i}000"
            bench_import.import_file(put(tmp_path, name + ".json", {**real(), "label": f"n09fix-none-on-{i}", "timestamp": stamp,
                                                                  "frametime_stddev_ms": 1.0 + i}))
        listed = analysis.tool_perf_runs()
        assert listed["total"] == 3 and all(r["fps"] is None for r in listed["rows"]), listed
        # the files are dated by the measurement: oldest 16:10 (label -1), then 16:20 (-0), then 16:30 (-2)
        history = analysis.tool_perf_history("n09fix-none-on")
        assert [r["run"].split("-")[3] for r in history["runs"]] == ["1", "0", "2"], history
        compared = analysis.tool_perf_compare("n09fix-none-on-0-20261109-160000", "n09fix-none-on-2-20261109-162000")
        assert compared["metrics"]["frame_jitter_ms"]["a"] == 1.0 and compared["metrics"]["frame_jitter_ms"]["b"] == 3.0, compared
        assert compared["metrics"]["fps"]["a"] is None and compared["metrics"]["fps_1pct_low"]["b"] is None


def command(*args, folder, env=None):
    return subprocess.run([sys.executable, "-I", str(PKG / "metal_trace_mcp.py"), "import-bench", *args], text=True,
                          capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
                          env={**os.environ, "METAL_TRACE_LOG": "off", "METAL_TRACE_OUT": str(folder), **(env or {})})


def test_the_command_prints_one_line_per_file_and_the_exit_code_follows(tmp_path):
    runs = tmp_path / "runs"
    good = put(tmp_path, NAME + ".json", real())
    bad = put(tmp_path, "bad.json", "{")
    done = command(str(good), folder=runs)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.splitlines()[0])["status"] == "imported"
    again = command(str(good), folder=runs)
    assert again.returncode == 0 and json.loads(again.stdout.splitlines()[0])["status"] == "same"
    mixed = command(str(good), str(bad), folder=runs)
    lines = [json.loads(line) for line in mixed.stdout.splitlines()]
    assert mixed.returncode == 2 and [l["status"] for l in lines] == ["same", "refused"] and "reason" in lines[1]
    assert str(tmp_path) not in mixed.stdout + mixed.stderr
    none = command(folder=runs)
    assert none.returncode == 2 and "usage: metal-gpu-trace import-bench" in none.stderr
    missing = command(str(tmp_path / "nope.json"), folder=runs)
    assert missing.returncode == 2 and str(tmp_path) not in missing.stdout + missing.stderr
    dirty = command(str(put(tmp_path, "dirty-1.json", {**real(), "clean": False})), folder=runs)
    assert dirty.returncode == 0 and "not stable" in dirty.stderr


def test_the_command_is_listed_in_the_help(tmp_path):
    done = subprocess.run([sys.executable, "-I", str(PKG / "metal_trace_mcp.py"), "--help"], text=True, capture_output=True)
    assert "import-bench" in done.stdout


def test_a_huge_number_is_refused_not_a_crash(tmp_path):
    """`math.isfinite(10 ** 400)` raises OverflowError: a number too big for a float is a bad value, not a traceback."""
    huge = "1" + "0" * 400
    text = REAL.read_text(encoding="utf-8-sig").replace('"frames":  3078', f'"frames": {huge}')
    assert huge in text and "frames" in refused_json(text)
    # a huge value in an optional key only turns that key null
    text = REAL.read_text(encoding="utf-8-sig").replace('"avg_fps":  26.78', f'"avg_fps": {huge}')
    assert bench_import.from_json(text)["vegaflow_bench"]["avg_fps"] is None
    with Out(tmp_path) as runs:
        source = tmp_path / "h.json"
        source.write_text(REAL.read_text(encoding="utf-8-sig").replace('"frames":  3078', f'"frames": {huge}'))
        done = command(str(source), folder=runs)
        assert done.returncode == 2 and "Traceback" not in done.stderr and "refused" in done.stdout, done


def test_from_json_takes_only_text():
    for value in (None, b"{}", 5, [], {}):
        assert "text" in refused_json_value(value), value


def refused_json_value(value):
    try:
        bench_import.from_json(value)
    except paths.ToolError as error:
        return str(error)
    raise AssertionError("it parsed")


def test_a_date_outside_a_plausible_range_is_refused(tmp_path):
    """A measurement dated before 2000 or after tomorrow would sit at either end of perf_runs for ever (os.utime clamps
    the year 1 and the year 9999 to the system's limits)."""
    for stamp in ("0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z", "0001-01-01T00:00:00+23:59", "1999-12-31T23:59:59Z", "2999-01-01T00:00:00Z"):
        assert "timestamp" in refused_json({**real(), "timestamp": stamp}), stamp
