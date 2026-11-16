"""Adversarial tests targeting `gputrace_read.diff`/`counts` and `traces.windows_of`/`check_window`/`tool_trace_query`.

Boundaries, Unicode/NUL inputs, fuzzing and properties, plus the `capture`-is-a-directory case the attack found.
"""
import collections
import random
import struct

import support  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import gputrace_read, paths, perf_report, traces  # noqa: E402

PUSH, SIGNPOST, POP, DRAW, PIPELINE = -16244, -16245, -16243, -16218, -16279
SEED = 20261115


def _record(call, body_after_sig=b""):
    body = bytes(0x24 - 8) + b"Cuu\0" + body_after_sig
    return struct.pack("<Ii", 8 + len(body), call) + body


def _bundle(tmp_path, name, raw):
    bundle = tmp_path / f"{name}.gputrace"
    bundle.mkdir(exist_ok=True)
    (bundle / "capture").write_bytes(raw)
    return bundle


def _mtsp(tmp_path, name, recs):
    return _bundle(tmp_path, name, b"MTSP" + bytes(4) + b"".join(recs))


def _query_xml(tmp_path, columns, rows, **kwargs):
    cols = "".join(f"<col><mnemonic>{c}</mnemonic></col>" for c in columns)
    body = "".join("<row>" + "".join(f'<{c} fmt="{f}">{v}</{c}>' for c, (f, v) in zip(columns, row)) + "</row>"
                   for row in rows)
    xml_path = tmp_path / "attack.xml"
    xml_path.write_text(f"<trace-query-result><node><schema>{cols}</schema>{body}</node></trace-query-result>")
    saved = perf_report.export, paths.trace_path
    perf_report.export = lambda trace, xpath=None, **_: str(xml_path)
    paths.trace_path = lambda trace: tmp_path / "r.trace"
    try:
        return traces.tool_trace_query("r", "metal-gpu-intervals", **kwargs)
    finally:
        perf_report.export, paths.trace_path = saved


# --- safety net: new boundary, Unicode, fuzz and property coverage -----------------------------------------------

def test_diff_property_group_order_and_exact_deltas(tmp_path):
    """Property (fixed seed): permuting top-level debug groups preserves diff totals and leaves groups empty when
    identical, and per-call deltas match b - a across random captures without leaking paths."""
    r = random.Random(SEED)
    confirmed = [c for c, (_, cert) in gputrace_read.CALLS.items()
                 if cert == "confirmado" and c not in (PUSH, SIGNPOST, POP)]
    ignored = [c for c, (_, cert) in gputrace_read.CALLS.items() if cert != "confirmado"] + [SIGNPOST, 999999]
    labels = ["shadow", "main", "ui", "ab", "x" * 220, "pass_1"]

    for _ in range(100):
        blocks_a, blocks_b = [], []
        expected_a, expected_b = collections.Counter(), collections.Counter()
        for _ in range(r.randint(0, 6)):
            lbl = r.choice(labels)
            calls_a = [r.choice(confirmed + ignored) for _ in range(r.randint(0, 6))]
            calls_b = [r.choice(confirmed + ignored) for _ in range(r.randint(0, 6))]
            blocks_a.append([_record(PUSH, lbl.encode() + b"\0"), *(_record(c) for c in calls_a), _record(POP)])
            blocks_b.append([_record(PUSH, lbl.encode() + b"\0"), *(_record(c) for c in calls_b), _record(POP)])
            for c in calls_a:
                if c in confirmed:
                    expected_a[gputrace_read.CALLS[c][0]] += 1
            for c in calls_b:
                if c in confirmed:
                    expected_b[gputrace_read.CALLS[c][0]] += 1

        reordered = [list(b) for b in blocks_a]
        r.shuffle(reordered)
        a = _mtsp(tmp_path, "a", [x for blk in blocks_a for x in blk])
        a_perm = _mtsp(tmp_path, "aperm", [x for blk in reordered for x in blk])
        b = _mtsp(tmp_path, "b", [x for blk in blocks_b for x in blk])

        same = gputrace_read.diff(a, a_perm)
        assert same["groups"] == [] and all(t["delta"] == 0 for t in same["totals"].values()), same
        got = gputrace_read.diff(a, b)
        assert str(tmp_path) not in str(got)
        for name, entry in got["totals"].items():
            assert entry == {"a": expected_a[name], "b": expected_b[name], "delta": expected_b[name] - expected_a[name]}


def test_counts_unicode_nul_and_control_bytes_in_labels(tmp_path):
    """Group labels pick the first >=3 printable ASCII run after signature+NUL, ignoring short/non-ASCII prefixes."""
    recs = [
        _record(PUSH, b"ab\x00\x01\xffreal_tag\x00"),
        _record(DRAW),
        _record(POP),
        _record(PUSH, "Páss".encode("utf-8") + b"\0"),  # split by non-ASCII -> no >=3 ASCII run
        _record(DRAW),
        _record(POP),
        _record(PUSH, b"a\nb\tc\x7f"),  # control/DEL chars split runs -> "(unnamed)"
        _record(DRAW),
        _record(POP),
    ]
    totals, groups = gputrace_read.counts(_mtsp(tmp_path, "labels", recs))
    assert totals["drawPrimitives"] == 3
    assert groups["real_tag"] == {"drawPrimitives": 1}
    assert groups["(unnamed)"] == {"drawPrimitives": 2}


def test_diff_fuzz_hostile_sizes_never_hang_or_leak(tmp_path):
    """Fuzz: records with zero, sub-header, or 4 GiB sizes raise ValueError naming only the bundle, never hanging."""
    r = random.Random(SEED)
    a = _mtsp(tmp_path, "good", [_record(DRAW)])
    for size in (0, 1, 7, 0x7FFFFFFF, 0xFFFFFFFF):
        bad = _bundle(tmp_path, f"bad_{size}", b"MTSP\0\0\0\0" + struct.pack("<Ii", size, DRAW) + bytes(16))
        try:
            gputrace_read.diff(a, bad)
        except ValueError as error:
            assert str(tmp_path) not in str(error) and bad.name in str(error), error
        else:
            raise AssertionError(f"corrupt size {size:#x} was accepted")

    for i in range(100):
        payload = bytes(r.randrange(256) for _ in range(r.randint(8, 128)))
        fuzz = _bundle(tmp_path, f"fuzz_{i}", b"MTSP\0\0\0\0" + payload)
        try:
            gputrace_read.counts(fuzz)
        except ValueError as error:
            assert str(tmp_path) not in str(error), error


def test_window_boundaries_and_hostile_time_cells(tmp_path):
    """check_window boundaries (1, 1.0, 3600000, -0.0, inf) and tool_trace_query window edges and all-invalid rows."""
    assert traces.check_window(1) == 1 and traces.check_window(1.0) == 1
    assert traces.check_window(3_600_000) == 3_600_000 and traces.check_window(3_600_000.0) == 3_600_000
    for bad in (-0.0, False, float("-inf"), 1e-9, complex(10, 0), 10**20):
        try:
            traces.check_window(bad)
        except paths.ToolError:
            pass
        else:
            raise AssertionError(f"check_window({bad!r}) was accepted")

    # Boundary ns: 0 stays in window 0, 9_999_999 stays in window 0, 10_000_000 starts window 10
    rows = [[("0", 0), ("1", 1)], [("9999999", 9_999_999), ("2", 2)], [("10000000", 10_000_000), ("3", 3)]]
    got = _query_xml(tmp_path, ["start", "duration"], rows, window_ms=10)
    assert got["rows"] == [
        {"start_ms": 0, "count": 2, "duration_ms": 0.0},
        {"start_ms": 10, "count": 1, "duration_ms": 0.0},
    ], got

    # All rows with invalid time -> empty windows and skipped_rows == 3
    bad_rows = [[("a", "NaN")], [("b", "")], [("c", -1)]]
    got_bad = _query_xml(tmp_path, ["time"], bad_rows, window_ms=10)
    assert got_bad["rows"] == [] and got_bad["skipped_rows"] == 3, got_bad


# --- reproducers: bugs found while attacking --------------------------------------------------------------------

def test_counts_when_capture_is_a_directory_raises_without_absolute_path(tmp_path):
    """`<bundle>/capture` as a directory is not a capture: FileNotFoundError naming only the bundle, no absolute path."""
    bundle = tmp_path / "dir.gputrace"
    (bundle / "capture").mkdir(parents=True)
    try:
        gputrace_read.counts(bundle)
    except FileNotFoundError as error:
        assert str(tmp_path) not in str(error) and "dir.gputrace" in str(error), error
    else:
        raise AssertionError("a directory was read as a capture")
