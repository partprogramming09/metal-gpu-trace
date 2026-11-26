"""Honest A/B (release 0.32): the files and variable names a run was made with, and what compare and perf_ab do with them."""
import json

import support  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import analysis, config, experiments, fingerprint, paths, recording


class Readable:
    """Makes `folder` a readable directory, as METAL_TRACE_READ would."""
    def __init__(self, folder):
        self.folder = folder

    def __enter__(self):
        self.saved = config.READ
        config.READ = [self.folder.resolve()]

    def __exit__(self, *exc):
        config.READ = self.saved


def readable(test):
    """Runs `test(tmp_path)` with tmp_path among the readable folders."""
    def run(tmp_path):
        with Readable(tmp_path):
            test(tmp_path)
    run.__name__ = test.__name__
    return run


def raises_tool_error(call):
    try:
        call()
    except paths.ToolError as error:
        return str(error)
    raise AssertionError("no ToolError")


@readable
def test_fingerprint_hashes_declared_files_by_content(tmp_path):
    (tmp_path / "game.exe").write_bytes(b"one")
    (tmp_path / "lib.dll").write_bytes(b"two")
    got = fingerprint.fingerprint_paths([tmp_path / "game.exe", str(tmp_path / "lib.dll")])
    assert [f["name"] for f in got] == ["game.exe", "lib.dll"] and [f["size"] for f in got] == [3, 3], got
    assert all(len(f["sha256"]) == 16 and set(f) == {"name", "sha256", "size"} for f in got), got
    (tmp_path / "game.exe").write_bytes(b"one!")
    assert fingerprint.fingerprint_paths([tmp_path / "game.exe"])[0]["sha256"] != got[0]["sha256"]
    assert fingerprint.fingerprint_paths([]) == []


@readable
def test_fingerprint_keeps_no_folder_in_what_it_returns(tmp_path):
    (tmp_path / "game.exe").write_bytes(b"x")
    assert str(tmp_path) not in json.dumps(fingerprint.fingerprint_paths([tmp_path / "game.exe"]))


@readable
def test_fingerprint_refuses_a_missing_file_a_folder_and_too_many(tmp_path):
    (tmp_path / "dir").mkdir()
    message = raises_tool_error(lambda: fingerprint.fingerprint_paths([tmp_path / "nope.exe"]))
    assert "nope.exe" in message and str(tmp_path) not in message, message
    assert "folder" in raises_tool_error(lambda: fingerprint.fingerprint_paths([tmp_path / "dir"]))
    (tmp_path / "f").write_bytes(b"x")
    assert "at most" in raises_tool_error(lambda: fingerprint.fingerprint_paths([tmp_path / "f"] * 33))
    assert "path" in raises_tool_error(lambda: fingerprint.fingerprint_paths(["a\0b"]))
    assert raises_tool_error(lambda: fingerprint.fingerprint_paths("f"))  # a string is not a list of paths


def test_fingerprint_refuses_files_outside_the_readable_folders_and_non_regular_ones(tmp_path):
    inside, outside = tmp_path / "in", tmp_path / "out"
    inside.mkdir(), outside.mkdir()
    (outside / "secret.bin").write_bytes(b"x")
    (inside / "ok.bin").write_bytes(b"x")
    (inside / "link.bin").symlink_to(outside / "secret.bin")
    with Readable(inside):
        assert "outside" in raises_tool_error(lambda: fingerprint.fingerprint_paths([outside / "secret.bin"]))
        assert "outside" in raises_tool_error(lambda: fingerprint.fingerprint_paths([inside / "link.bin"]))
        assert raises_tool_error(lambda: fingerprint.fingerprint_paths(["~nosuchuser_zz/x"]))
        assert fingerprint.fingerprint_paths([inside / "ok.bin"])[0]["name"] == "ok.bin"


def test_env_keys_keep_only_variable_names():
    got = fingerprint.env_keys("WINEDEBUG=-all /Users/alice/games/run.sh?a=1 --opt=v 9X=1 _OK=2")
    assert got == ["WINEDEBUG", "_OK"], got


def test_env_keys_keep_names_and_never_values():
    got = fingerprint.env_keys("B=secret A=1 B=2 C=")
    assert got == ["A", "B", "C"], got
    assert fingerprint.env_keys("") == [] and "secret" not in json.dumps(got)


def test_fingerprints_say_whether_two_runs_used_the_same_files():
    f1, f2 = [{"name": "g.exe", "sha256": "a" * 16, "size": 1}], [{"name": "g.exe", "sha256": "b" * 16, "size": 1}]
    assert fingerprint.compare(f1, list(f1)) == {"same": True}
    assert fingerprint.compare(f1, f2) == {"same": False, "changed": ["g.exe"]}
    assert fingerprint.compare(None, f1) is None and fingerprint.compare(f1, None) is None
    other = [{"name": "h.dll", "sha256": "c" * 16, "size": 1}]
    assert fingerprint.compare(f1, other) == {"same": False, "changed": ["g.exe", "h.dll"]}


def summary_with(context):
    return {"gpu": {"frames": 300, "fps_estimate": 60.0}, "context": {"git": {"commit": "abc", "dirty": False},
                                                                          "instruments": None, **context}}


def test_context_change_keeps_same_for_code_and_reports_files_and_variables_apart():
    one = summary_with({"env_keys": ["A"], "fingerprint": [{"name": "g", "sha256": "a" * 16, "size": 1}]})
    two = summary_with({"env_keys": ["A", "B"], "fingerprint": [{"name": "g", "sha256": "b" * 16, "size": 1}]})
    got = recording.context_change(one, two, "a", "b")
    assert got["same"] is True, "the commit is the same: `same` keeps its meaning"
    assert got["fingerprint"] == {"same": False, "changed": ["g"]}, got
    assert got["env_keys"] == {"same": False, "only_a": [], "only_b": ["B"]}, got
    plain = recording.context_change(summary_with({}), summary_with({}), "a", "b")
    assert plain == {"same": True}, "runs recorded before 0.32 gain no keys"


def test_perf_compare_warns_when_the_runs_are_far_apart_in_time(tmp_path):
    for name in ("t_20261101-100000", "t_20261101-103000", "t_20261108-100000", "imported"):
        (tmp_path / f"{name}.json").write_text(json.dumps(summary_with({})))
    saved, config.OUT = config.OUT, tmp_path
    try:
        near = analysis.tool_perf_compare("t_20261101-100000", "t_20261101-103000")
        far = analysis.tool_perf_compare("t_20261101-100000", "t_20261108-100000")
        unknown = analysis.tool_perf_compare("t_20261101-100000", "imported")
    finally:
        config.OUT = saved
    assert "time_apart" not in near and "time_apart" not in unknown, (near.get("time_apart"), unknown.get("time_apart"))
    assert far["time_apart"]["hours"] == 168.0 and "far apart" in far["time_apart"]["warning"], far["time_apart"]


def ab_with(tmp_path, fingerprints, files):
    """Runs perf_ab with recording stubbed; `fingerprints` is the list fingerprint_paths returns, call by call."""
    events, calls = [], iter(fingerprints)
    saved = recording.record_new_summary, fingerprint.fingerprint_paths, analysis.steady_summary, config.OUT
    config.OUT = tmp_path
    recording.record_new_summary = lambda label, **kw: (events.append(("rec", label, kw)) or
                                                       (label, {"gpu": {"frames": 300, "fps_estimate": 60.0}}))
    fingerprint.fingerprint_paths = lambda given: next(calls)
    analysis.steady_summary = lambda run, skip_s=0: {"gpu": {"frames": 300, "fps_estimate": 60.0}}
    try:
        try:
            result = experiments.tool_perf_ab("x", "A=1", "A=2", fingerprint_paths=files)
        except paths.ToolError as error:
            result = str(error)
    finally:
        recording.record_new_summary, fingerprint.fingerprint_paths, analysis.steady_summary, config.OUT = saved
    return result, events


def test_perf_ab_records_when_the_files_stay_the_same(tmp_path):
    same = [{"name": "g", "sha256": "a" * 16, "size": 1}]
    result, events = ab_with(tmp_path, [same] * 5, ["g"])  # before each of 4 recordings, and once after
    assert len(events) == 4 and result["fingerprint"] == {"same": True}, result
    assert all(kw["fingerprint_paths"] == ["g"] for _, _, kw in events), events


def test_perf_ab_reports_a_file_that_changed_during_the_last_recording(tmp_path):
    a, b = [{"name": "g", "sha256": "a" * 16, "size": 1}], [{"name": "g", "sha256": "b" * 16, "size": 1}]
    result, events = ab_with(tmp_path, [a, a, a, a, b], ["g"])
    assert len(events) == 4 and result["fingerprint"] == {"same": False, "changed": ["g"]}, result


def test_perf_ab_refuses_before_the_next_recording_when_a_file_changed(tmp_path):
    a, b = [{"name": "g", "sha256": "a" * 16, "size": 1}], [{"name": "g", "sha256": "b" * 16, "size": 1}]
    message, events = ab_with(tmp_path, [a, a, b], ["g"])
    assert isinstance(message, str) and "changed" in message and "g" in message, message
    assert len(events) == 2, "the recording after the change never started"


def test_perf_ab_without_declared_files_asks_nothing_of_them(tmp_path):
    result, events = ab_with(tmp_path, [], None)
    assert len(events) == 4 and "fingerprint" not in result, result
    assert all("fingerprint_paths" not in kw for _, _, kw in events), events


def test_the_summary_gets_the_variable_names_and_the_files(tmp_path):
    summary = {"gpu": {"intervals": 1}}
    saved = recording.run_context, config.MAX_DISK_MB
    recording.run_context, config.MAX_DISK_MB = (lambda: {"git": None, "instruments": None}), 0
    try:
        got = recording.finish(summary, tmp_path / "r.json", None, None,
                               context_extra={"env_keys": ["A"], "fingerprint": []})
        again = recording.finish({"gpu": {}}, tmp_path / "s.json", None, None)
    finally:
        recording.run_context, config.MAX_DISK_MB = saved
    assert got["context"] == {"git": None, "instruments": None, "env_keys": ["A"]}, "an empty fingerprint is left out"
    assert again["context"] == {"git": None, "instruments": None}, again
