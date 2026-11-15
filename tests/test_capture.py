"""Tests of gputrace_read: reading a Metal .gputrace capture."""
import struct

from support import write_capture  # also puts src/ on sys.path
from metal_gpu_trace import config, gputrace_read, paths, traces  # noqa: E402


def test_capture(tmp_path):
    """A small MTSP stream is read record by record, and the summary names the capture without its path."""
    summary = gputrace_read.summarize(write_capture(tmp_path))
    assert summary["capture"] == "frame.gputrace" and summary["draw_primitives"] == 3, summary


PUSH, POP, DRAW, PIPELINE = -16244, -16243, -16218, -16279


def record(call, label=None):
    """One MTSP record: the 0x24-byte head, a signature, and `label` as the string after it."""
    body = bytes(0x24 - 8) + b"Cuu\0" + (label.encode() + b"\0" if label else bytes(8))
    return struct.pack("<Ii", 8 + len(body), call) + body


def capture(tmp_path, name, records):
    """Writes a .gputrace called `name` holding `records` (a list of record() bytes) and returns its path."""
    bundle = tmp_path / f"{name}.gputrace"
    bundle.mkdir()
    (bundle / "capture").write_bytes(b"MTSP" + bytes(4) + b"".join(records))
    return bundle


def group(label, *calls):
    return [record(PUSH, label), *[record(c) for c in calls], record(POP)]


def test_diff_same_capture_is_zero(tmp_path):
    a = capture(tmp_path, "a", group("shadow", DRAW, DRAW) + group("main", PIPELINE, DRAW))
    got = gputrace_read.diff(a, a)
    assert got["groups"] == [] and all(t["delta"] == 0 for t in got["totals"].values()), got
    assert got["totals"]["drawPrimitives"] == {"a": 3, "b": 3, "delta": 0}, got


def test_diff_counts_new_draws(tmp_path):
    a = capture(tmp_path, "a", group("main", DRAW))
    b = capture(tmp_path, "b", group("main", DRAW, DRAW, DRAW))
    got = gputrace_read.diff(a, b)
    assert got["aligned_by"] == "debug_group" and got["totals"]["drawPrimitives"] == {"a": 1, "b": 3, "delta": 2}, got
    assert got["groups"] == [{"name": "main", "a": {"drawPrimitives": 1}, "b": {"drawPrimitives": 3}}], got


def test_diff_aligns_by_debug_group(tmp_path):
    """The same groups in another order give the same answer: a group is matched by its label, not its position."""
    a = capture(tmp_path, "a", group("shadow", DRAW) + group("main", DRAW, DRAW))
    b = capture(tmp_path, "b", group("main", DRAW, DRAW, DRAW) + group("shadow", DRAW))
    assert gputrace_read.diff(a, b)["groups"] == [
        {"name": "main", "a": {"drawPrimitives": 2}, "b": {"drawPrimitives": 3}}]


def test_diff_lists_a_group_only_one_capture_has(tmp_path):
    a = capture(tmp_path, "a", group("main", DRAW))
    b = capture(tmp_path, "b", group("main", DRAW) + group("blur", PIPELINE))
    assert gputrace_read.diff(a, b)["groups"] == [
        {"name": "blur", "a": {}, "b": {"setRenderPipelineState": 1}}]


def test_diff_without_groups_uses_whole_capture(tmp_path):
    a = capture(tmp_path, "a", [record(DRAW)])
    b = capture(tmp_path, "b", [record(DRAW), record(DRAW)])
    got = gputrace_read.diff(a, b)
    assert got["aligned_by"] == "whole_capture" and got["groups"] == [], got
    assert got["totals"]["drawPrimitives"]["delta"] == 1, got


def test_diff_ignores_probable_and_unknown_calls_and_an_unbalanced_pop(tmp_path):
    a = capture(tmp_path, "a", [record(-16353), record(12345), record(POP), record(DRAW)])
    totals = gputrace_read.diff(a, a)["totals"]
    assert "renderCommandEncoder" not in totals and totals["drawPrimitives"]["a"] == 1, totals


def test_diff_counts_calls_in_the_innermost_of_nested_groups(tmp_path):
    a = capture(tmp_path, "a", [record(PUSH, "frame"), record(PUSH, "pass"), record(DRAW), record(POP), record(DRAW), record(POP)])
    b = capture(tmp_path, "b", [record(PUSH, "frame"), record(PUSH, "pass"), record(POP), record(DRAW), record(POP)])
    assert gputrace_read.diff(a, b)["groups"] == [
        {"name": "pass", "a": {"drawPrimitives": 1}, "b": {}}], "only the draw inside `pass` changed"


def test_malformed_record_raises_valueerror(tmp_path):
    a = capture(tmp_path, "a", [record(DRAW)])
    bad = capture(tmp_path, "bad", [record(DRAW), struct.pack("<Ii", 999, DRAW)])
    for pair in ((a, bad), (bad, a)):
        try:
            gputrace_read.diff(*pair)
        except ValueError as error:
            assert str(tmp_path) not in str(error) and "bad.gputrace" in str(error), error
            continue
        raise AssertionError("a truncated record was read")


def test_diff_names_no_absolute_path(tmp_path):
    a, b = capture(tmp_path, "a", [record(DRAW)]), capture(tmp_path, "b", [record(DRAW)])
    assert str(tmp_path) not in str(gputrace_read.diff(a, b))


def test_a_capture_without_its_stream_is_an_error(tmp_path):
    empty = tmp_path / "e.gputrace"
    empty.mkdir()
    for pair in ((empty, empty), (capture(tmp_path, "a", []), empty)):
        try:
            gputrace_read.diff(*pair)
        except FileNotFoundError as error:
            assert str(tmp_path) not in str(error), error
            continue
        raise AssertionError("a capture without a stream was read")


def test_capture_diff_tool_rejects_a_path_outside_the_readable_directories(tmp_path):
    inside, outside = tmp_path / "in", tmp_path / "out"
    inside.mkdir(), outside.mkdir()
    a, b = capture(inside, "a", [record(DRAW)]), capture(outside, "b", [record(DRAW)])
    saved = config.READ
    config.READ = [inside.resolve()]
    try:
        assert traces.tool_capture_diff(str(a), str(a))["totals"]["drawPrimitives"]["delta"] == 0
        for pair in ((a, b), (b, a)):
            try:
                traces.tool_capture_diff(*map(str, pair))
            except paths.ToolError as error:
                assert str(tmp_path) not in str(error), error
                continue
            raise AssertionError("a capture outside the readable directories was read")
    finally:
        config.READ = saved


def test_capture_diff_tool_keeps_the_biggest_groups_and_says_how_many(tmp_path):
    a = capture(tmp_path, "a", [])
    b = capture(tmp_path, "b", sum((group(f"g{n:03d}", *([DRAW] * (n + 1))) for n in range(120)), []))
    saved = config.READ
    config.READ = [tmp_path.resolve()]
    try:
        got = traces.tool_capture_diff(str(a), str(b))
    finally:
        config.READ = saved
    assert got["groups_total"] == 120 and len(got["groups"]) == 100 and got["groups"][0]["name"] == "g119", got


def test_diff_of_the_example_in_the_evidence(tmp_path):
    """docs/evidence/v0.26.0.md shows this exact pair."""
    a = capture(tmp_path, "before", group("shadow", DRAW) + group("main", PIPELINE, DRAW, DRAW))
    b = capture(tmp_path, "after", group("main", PIPELINE, DRAW, DRAW, DRAW, DRAW) + group("shadow", DRAW))
    got = gputrace_read.diff(a, b)
    assert got["totals"] == {"drawPrimitives": {"a": 3, "b": 5, "delta": 2},
                             "setRenderPipelineState": {"a": 1, "b": 1, "delta": 0}}, got
    assert got["groups"] == [{"name": "main", "a": {"drawPrimitives": 2}, "b": {"drawPrimitives": 4}}], got


def test_groups_with_the_same_label_add_up_and_an_unpopped_group_runs_to_the_end(tmp_path):
    a = capture(tmp_path, "a", group("pass", DRAW) + group("pass", DRAW))
    b = capture(tmp_path, "b", group("pass", DRAW) + [record(PUSH, "pass"), record(DRAW), record(DRAW)])
    assert gputrace_read.diff(a, b)["groups"] == [
        {"name": "pass", "a": {"drawPrimitives": 2}, "b": {"drawPrimitives": 3}}]


def test_a_group_without_a_readable_label_is_unnamed_and_a_long_label_is_cut(tmp_path):
    a = capture(tmp_path, "a", [record(PUSH, "ab"), record(DRAW), record(POP)])
    assert [g["name"] for g in gputrace_read.diff(a, capture(tmp_path, "b", []))["groups"]] == ["(unnamed)"]
    long = capture(tmp_path, "long", [record(PUSH, "x" * 5000), record(DRAW), record(POP)])
    assert [len(g["name"]) for g in gputrace_read.diff(long, a)["groups"]] == [len("(unnamed)"), 200]


def test_summarize_and_diff_errors_name_no_folder_when_the_stream_is_missing(tmp_path):
    empty = tmp_path / "e.gputrace"
    empty.mkdir()
    try:
        gputrace_read.summarize(empty)
    except FileNotFoundError as error:
        assert str(tmp_path) not in str(error) and "e.gputrace" in str(error), error
    else:
        raise AssertionError("a capture without a stream was summarized")
