"""trace_query with window_ms: rows of a trace table grouped by time window instead of listed one by one."""
import os

from support import ROOT  # noqa: F401  (puts src/ on sys.path)

from metal_gpu_trace import config, paths, perf_report, traces


def table(tmp_path, columns, rows):
    """Writes an xctrace-style export with `columns` (mnemonics) and `rows` (lists of {fmt, text} per column)."""
    cols = "".join(f"<col><mnemonic>{c}</mnemonic></col>" for c in columns)
    body = "".join("<row>" + "".join(f'<{c} fmt="{f}">{v}</{c}>' for c, (f, v) in zip(columns, row)) + "</row>"
                   for row in rows)
    path = tmp_path / "t.xml"
    path.write_text(f"<trace-query-result><node><schema>{cols}</schema>{body}</node></trace-query-result>")
    return str(path)


EXPORTED = []  # the files the stubbed export wrote, to check that they are deleted


def query(tmp_path, columns, rows, **kwargs):
    """Runs tool_trace_query over one synthetic table."""
    saved = perf_report.export, paths.trace_path, config.OUT
    perf_report.export = lambda trace, xpath=None, **_: EXPORTED.append(table(tmp_path, columns, rows)) or EXPORTED[-1]
    paths.trace_path = lambda trace: tmp_path / "r.trace"
    try:
        return traces.tool_trace_query("r", "metal-gpu-intervals", **kwargs)
    finally:
        perf_report.export, paths.trace_path, config.OUT = saved


def gpu_row(start_ns, duration_ns):
    return [(f"{start_ns}", start_ns), (f"{duration_ns}", duration_ns)]


def test_without_window_ms_rows_are_unchanged(tmp_path):
    got = query(tmp_path, ["start", "duration"], [gpu_row(1_000_000, 500_000)])
    assert got["rows"] == [{"start": "1000000", "duration": "500000"}] and "window_ms" not in got, got


def test_window_ms_groups_rows_by_window(tmp_path):
    rows = [gpu_row(1_000_000, 2_000_000), gpu_row(9_000_000, 1_000_000), gpu_row(12_000_000, 4_000_000)]
    got = query(tmp_path, ["start", "duration"], rows, window_ms=10)
    assert got["window_ms"] == 10 and got["total"] == 2, got
    assert got["rows"] == [{"start_ms": 0, "count": 2, "duration_ms": 3.0},
                           {"start_ms": 10, "count": 1, "duration_ms": 4.0}], got


def test_window_ms_works_on_a_table_whose_time_column_is_time(tmp_path):
    """time-profile names its column `time` and has no duration: windows then carry only the row count."""
    got = query(tmp_path, ["time", "weight"], [[("a", 836_018_750), ("b", 1_000_000)]], window_ms=500)
    assert got["rows"] == [{"start_ms": 500, "count": 1}], got


def test_window_ms_rejects_zero_negative_and_non_numbers(tmp_path):
    for bad in (0, -5, 3_600_001, True, 1.5, float("nan"), float("inf"), "10"):
        try:
            query(tmp_path, ["start", "duration"], [gpu_row(1, 1)], window_ms=bad)
        except paths.ToolError as error:
            assert "window_ms" in str(error), (bad, error)
        else:
            raise AssertionError(f"window_ms={bad!r} was accepted")


def test_window_ms_rejects_table_without_time_column(tmp_path):
    try:
        query(tmp_path, ["process", "n"], [[("p", 1), ("n", 2)]], window_ms=10)
    except paths.ToolError as error:
        assert "time column" in str(error), error
    else:
        raise AssertionError("a table without a time column was windowed")


def test_window_ms_on_an_empty_table_returns_no_windows(tmp_path):
    got = query(tmp_path, ["start", "duration"], [], window_ms=10)
    assert got["rows"] == [] and got["total"] == 0, got


def test_window_ms_counts_rows_it_cannot_place(tmp_path):
    rows = [gpu_row(1_000_000, 1_000_000), [("x", "n/a"), ("1", 1)]]
    got = query(tmp_path, ["start", "duration"], rows, window_ms=10)
    assert got["rows"][0]["count"] == 1 and got["skipped_rows"] == 1, got


def test_window_ms_accepts_a_whole_float_as_an_integer(tmp_path):
    got = query(tmp_path, ["start", "duration"], [gpu_row(11_000_000, 1)], window_ms=10.0)
    assert got["window_ms"] == 10 and got["rows"][0]["start_ms"] == 10 and isinstance(got["rows"][0]["start_ms"], int), got


def test_window_ms_skips_negative_and_missing_times_and_keeps_a_zero_duration(tmp_path):
    rows = [gpu_row(1_000_000, 1_000_000), [("-5", -5), ("1", 1)], [("x", None), ("1", 1)], [("a", 2_000_000), ("n/a", "n/a")]]
    got = query(tmp_path, ["start", "duration"], rows, window_ms=10)
    assert got["skipped_rows"] == 2 and got["rows"] == [{"start_ms": 0, "count": 2, "duration_ms": 1.0}], got
    only_bad = query(tmp_path, ["start", "duration"], [[("a", 1_000_000), ("n/a", "n/a")]], window_ms=10)
    assert only_bad["rows"] == [{"start_ms": 0, "count": 1, "duration_ms": 0.0}], only_bad


def test_window_ms_pages_its_windows(tmp_path):
    rows = [gpu_row(n * 10_000_000, 1_000_000) for n in range(5)]
    first = query(tmp_path, ["start", "duration"], rows, window_ms=10, limit=2)
    assert [w["start_ms"] for w in first["rows"]] == [0, 10] and first["total"] == 5 and first["next_offset"] == 2, first
    last = query(tmp_path, ["start", "duration"], rows, window_ms=10, offset=4, limit=2)
    assert [w["start_ms"] for w in last["rows"]] == [40] and last["next_offset"] is None, last


def test_window_ms_keeps_only_the_given_process(tmp_path):
    rows = [[("a", 1_000_000), ("p", 42)], [("b", 2_000_000), ("q", 7)], [("c", 15_000_000), ("p", 42)]]
    saved = perf_report.pid_of
    perf_report.pid_of = lambda element: int(element.text)
    try:
        got = query(tmp_path, ["start", "process"], rows, window_ms=10, pid=42)
    finally:
        perf_report.pid_of = saved
    assert got["rows"] == [{"start_ms": 0, "count": 1}, {"start_ms": 10, "count": 1}], got


def test_the_exported_file_is_deleted_also_when_the_table_has_no_time_column(tmp_path):
    """perf_report.rows deletes its export when closed; an error halfway must not leave a large file behind."""
    for window in (10, None):
        try:
            query(tmp_path, ["process", "n"], [[("p", 1), ("n", 2)]], window_ms=window)
        except paths.ToolError:
            assert window == 10
        assert not os.path.exists(EXPORTED[-1]), "the export was left on disk"
