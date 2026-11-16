"""Adversarial tests for tables, retention, preflight, analysis.suggested_actions, perf_report.noisy_environment,
paths.check_cooldown, and recording.resolve_tier."""
import csv
import gzip
import os
import random
import shutil
import sys

import support  # noqa: F401
from metal_gpu_trace import analysis, config, paths, perf_record_windows, perf_report, preflight, recording, retention, tables

MIB = 2**20
HEADER = ["frame", "start_ms", "gpu_ms_total"]


def _read_rows(path):
    with tables.open_text(path) as handle:
        return list(csv.DictReader(handle))


# --- 1) tables.py ---


def test_tables_every_truncation_of_gzip_is_unreadable(tmp_path):
    rows = [(i, round(i * 16.667, 3), 4.25) for i in range(60)]
    path = tables.write(tmp_path, "trunc.frames", HEADER, rows)
    full = path.read_bytes()
    for cut in range(len(full)):
        path.write_bytes(full[:cut])
        try:
            _read_rows(path)
        except tables.UNREADABLE:
            continue
        raise AssertionError(f"truncated gzip at {cut}/{len(full)} must raise tables.UNREADABLE")


def test_tables_random_corruptions_and_bad_bytes_are_unreadable(tmp_path):
    rng = random.Random(42)
    rows = [(i, i * 10.0, 2.5) for i in range(40)]
    valid = tables.write(tmp_path, "seed.frames", HEADER, rows).read_bytes()
    target = tmp_path / "fuzz.frames.csv.gz"
    mutable_indices = [0, 1, 2, 3, *range(10, len(valid))]
    for trial in range(50):
        buf = bytearray(valid)
        for _ in range(rng.randint(1, 6)):
            buf[rng.choice(mutable_indices)] ^= rng.randint(1, 255)
        if bytes(buf) == valid:
            continue
        target.write_bytes(bytes(buf))
        try:
            _read_rows(target)
        except tables.UNREADABLE:
            continue
        raise AssertionError(f"corrupted gzip trial {trial} must raise tables.UNREADABLE")
    bad_payloads = [
        ("trailing_garbage.csv.gz", valid + b"GARBAGE"),
        ("trailing_partial_gz.csv.gz", valid + valid[:6]),
        ("bad_utf8_in_gz.csv.gz", gzip.compress(b"frame,start_ms\n1,\xff\xfe\n")),
        ("bad_utf8.csv", b"frame,start_ms\n1,\xff\xfe\n"),
        ("random_bytes.csv.gz", rng.randbytes(128)),
    ]
    for name, content in bad_payloads:
        p = tmp_path / name
        p.write_bytes(content)
        try:
            _read_rows(p)
        except tables.UNREADABLE:
            continue
        raise AssertionError(f"{name} must raise tables.UNREADABLE")


def test_tables_atomic_overwrite_and_unicode_determinism(tmp_path):
    old_rows = [(1, 0.0, 1.0)]
    target = tables.write(tmp_path, "run.frames", HEADER, old_rows)
    original_bytes = target.read_bytes()

    def failing_rows():
        yield (1, 0.0, 99.0)
        raise RuntimeError("mid-write failure")

    try:
        tables.write(tmp_path, "run.frames", HEADER, failing_rows())
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError from failing generator")
    assert target.read_bytes() == original_bytes
    assert [p.name for p in tmp_path.iterdir()] == ["run.frames.csv.gz"]

    uni_header = ["frame", "note", "val"]
    uni_rows = [(1, "ñ, \"quoted\"\nline2", "日本語🚀"), (2, "", "0")]
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    p1 = tables.write(d1, "uni.frames", uni_header, uni_rows)
    p2 = tables.write(d2, "uni.frames", uni_header, uni_rows)
    assert p1.read_bytes() == p2.read_bytes()
    assert _read_rows(p1) == [{"frame": "1", "note": "ñ, \"quoted\"\nline2", "val": "日本語🚀"},
                              {"frame": "2", "note": "", "val": "0"}]


def test_tables_find_ignores_dirs_broken_links_and_temps(tmp_path):
    (tmp_path / "r.frames.csv.gz").mkdir()
    (tmp_path / "r.frames.csv").write_text("frame\n1\n", encoding="utf-8")
    assert tables.find(tmp_path, "r.frames") == tmp_path / "r.frames.csv"

    (tmp_path / "broken.frames.csv.gz").symlink_to(tmp_path / "missing")
    (tmp_path / "broken.frames.csv.gz.123.tmp").write_bytes(b"tmp")
    (tmp_path / "broken.frames.csv.tmp").write_bytes(b"tmp")
    assert tables.find(tmp_path, "broken.frames") is None


# --- 2) retention.py ---


def _put(out, name, size=0, age=0):
    path = out / name
    path.write_bytes(b"x" * size)
    os.utime(path, (1_000_000 + age, 1_000_000 + age))
    return path


def test_retention_unicode_and_protected_files_and_symlinks(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "keep.bin"
    secret.write_bytes(b"z" * (3 * MIB))

    out = tmp_path / "runs"
    out.mkdir()
    current = "sesión ñ 日本語 v1"
    protected = [
        f"{current}.json",
        f"{current}.chrome-trace",
        f"{current}.frames.csv",
        f"{current}.frames.csv.gz",
        f"{current}.metal_memory.csv",
        f"{current}.metal_memory.csv.gz",
        f"{current}.rss.csv",
        f"{current}.agx.csv",
        "baselines.json",
        "panel.json",
        "other.json",
        "other.rss.csv",
        "other.agx.csv",
    ]
    for name in protected:
        _put(out, name, 100, 1)

    _put(out, "viejo ñ.trace", MIB, 0)
    _put(out, "viejo ñ.chrome-trace", MIB, 2)
    _put(out, "viejo ñ.metal_memory.csv", MIB, 3)
    (out / "link.trace").symlink_to(outside, target_is_directory=True)
    (out / "broken.frames.csv.gz").symlink_to(outside / "missing")
    _put(out, f"{current}.trace", 2 * MIB, 10)

    got = retention.prune_to_quota(out, 1, current)
    remaining = {p.name for p in out.iterdir()}
    assert set(protected).issubset(remaining), remaining
    assert f"{current}.trace" not in remaining and got["trace_dropped"] is True
    assert secret.read_bytes() == b"z" * (3 * MIB)


def test_retention_vanishing_file_inside_trace_dir_still_prunes(tmp_path):
    """If a file inside a .trace directory disappears while rmtree runs, pruning must still finish removing the folder
    and meet the quota instead of aborting the rmtree and counting 0 freed."""
    out = tmp_path / "runs"
    out.mkdir()
    trace_dir = out / "old.trace"
    trace_dir.mkdir()
    vanishing = trace_dir / "a_vanish.bin"
    remaining_big = trace_dir / "b_big.bin"
    vanishing.write_bytes(b"a" * MIB)
    remaining_big.write_bytes(b"b" * (2 * MIB))
    _put(out, "cur.json", 10, 9)

    real_unlink = os.unlink

    def race_unlink(path, *args, **kwargs):
        if str(path).endswith("a_vanish.bin"):
            real_unlink(path, *args, **kwargs)  # rmtree passes dir_fd: the file really goes, then the error is raised
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real_unlink(path, *args, **kwargs)

    os.unlink = race_unlink
    try:
        retention.prune_to_quota(out, 1, "cur")
    finally:
        os.unlink = real_unlink

    total_after = sum(retention.size_of(p) for p in out.iterdir())
    assert not trace_dir.exists(), "old.trace must still be removed when a child file vanishes mid-prune"
    assert total_after <= MIB, f"folder must be <= 1 MiB after pruning, got {total_after}"


def test_retention_randomized_invariants(tmp_path):
    rng = random.Random(42)
    for trial in range(15):
        out = tmp_path / f"t{trial}"
        out.mkdir()
        current = "cur"
        protected = set()
        for idx in range(rng.randint(4, 12)):
            stem = f"run_{idx}" if idx else current
            age = rng.randint(0, 100)
            kind = rng.choice([".trace", ".chrome-trace", ".frames.csv", ".frames.csv.gz",
                               ".metal_memory.csv.gz", ".json", ".rss.csv", ".agx.csv"])
            name = stem + kind
            if kind in (".json", ".rss.csv", ".agx.csv") or (stem == current and kind != ".trace"):
                protected.add(name)
            if kind == ".trace" and rng.random() < 0.4:
                d = out / name
                d.mkdir(exist_ok=True)
                _put(d, "data.bin", rng.randint(50_000, 400_000), age)
                os.utime(d, (1_000_000 + age, 1_000_000 + age))
            elif not (out / name).exists():
                _put(out, name, rng.randint(50_000, 400_000), age)
        max_mb = rng.choice([0, 1, 2])
        got = retention.prune_to_quota(out, max_mb, current)
        after = {p.name for p in out.iterdir()}
        assert protected.issubset(after), (trial, protected - after)
        assert got["trace_dropped"] is (f"{current}.trace" not in after if (out / f"{current}.json").exists() or got["trace_dropped"] else got["trace_dropped"])
        removable_left = [p for p in out.iterdir() if retention.kind_of(p.name, current) is not None]
        if removable_left:
            total = sum(retention.size_of(p) for p in out.iterdir())
            assert total <= max_mb * MIB, (trial, total, max_mb * MIB)


# --- 3) preflight.py ---


class _SavedPreflight:
    def __enter__(self):
        self.state = config.OUT, config.LOCK, shutil.disk_usage, sys.platform, os.kill, shutil.which
        return self

    def __exit__(self, *exc):
        config.OUT, config.LOCK, shutil.disk_usage, sys.platform, os.kill, shutil.which = self.state


def _preflight_kw(tmp_path):
    wine = tmp_path / "wine"
    (wine / "bin").mkdir(parents=True, exist_ok=True)
    (wine / "bin" / "wine").write_text("#!/bin/sh\n")
    (wine / "bin" / "wine").chmod(0o755)
    prog = tmp_path / "prog"
    prog.write_text("#!/bin/sh\n")
    prog.chmod(0o755)
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    (stubs / "xcrun").write_text("#!/bin/sh\n")
    (stubs / "xcrun").chmod(0o755)
    config.OUT = tmp_path / "runs"
    config.OUT.mkdir(exist_ok=True)
    config.LOCK = tmp_path / "lock"
    return {
        "wine": str(wine),
        "command": [str(prog)],
        "seconds": 10,
        "environ": {"PATH": str(stubs), "TMPDIR": str(tmp_path)},
        "read": lambda argv: "ok",
        "alive": lambda pid: False,
    }


def _assert_tool_error(fn, label):
    try:
        fn()
    except paths.ToolError:
        return
    except Exception as exc:
        raise AssertionError(f"{label} raised {type(exc).__name__} instead of paths.ToolError: {exc}") from exc
    raise AssertionError(f"{label} did not raise paths.ToolError")


def test_preflight_hostile_seconds_only_raises_tool_error(tmp_path):
    with _SavedPreflight():
        kw = _preflight_kw(tmp_path)
        for bad in ("--10", "²", "²³", "1.0", "1e2", "10_0", "\x00", float("nan"), float("inf"), float("-inf")):
            _assert_tool_error(lambda b=bad: preflight.check(**{**kw, "seconds": b}), f"seconds={bad!r}")


def test_preflight_hostile_wine_and_command_only_raises_tool_error(tmp_path):
    with _SavedPreflight():
        kw = _preflight_kw(tmp_path)
        for bad_wine in (None, 123, ["wine"], "bad\x00wine"):
            _assert_tool_error(lambda w=bad_wine: preflight.check(**{**kw, "wine": w}), f"wine={bad_wine!r}")
        for bad_cmd in ([], None, 123, "/bin/sh", [None], [123], ["prog\x00"], {1: "x"}):
            _assert_tool_error(
                lambda c=bad_cmd: preflight.check(**{**kw, "wine": "native", "command": c}),
                f"command={bad_cmd!r}",
            )


def test_preflight_hostile_environ_only_raises_tool_error(tmp_path):
    with _SavedPreflight():
        kw = _preflight_kw(tmp_path)
        bad_environs = [
            "not-a-dict",
            123,
            [],
            {"PATH": 123, "TMPDIR": str(tmp_path)},
            {"PATH": kw["environ"]["PATH"], "TMPDIR": 123},
            {"PATH": kw["environ"]["PATH"], "TMPDIR": str(tmp_path), "PERF_MIN_FREE_GB": 10},
        ]
        if sys.platform != "win32":  # under Windows preflight does not read TMPDIR, so a bad one is not an error
            bad_environs.append({"PATH": kw["environ"]["PATH"], "TMPDIR": "bad\x00tmp"})
        for bad_env in bad_environs:
            _assert_tool_error(lambda e=bad_env: preflight.check(**{**kw, "environ": e}), f"environ={bad_env!r}")


def test_preflight_process_alive_and_windows_no_signals(tmp_path):
    for bad_pid in (0, -1, -2**31, 2**31, 2**31 + 1, 2**63, True, False, 1.5, "1", None):
        assert preflight.process_alive(bad_pid) is False, bad_pid
    assert preflight.process_alive(os.getpid()) is True

    with _SavedPreflight():
        kw = _preflight_kw(tmp_path)
        del kw["alive"]
        sys.platform = "win32"
        os.kill = lambda pid, sig: (_ for _ in ()).throw(AssertionError("os.kill called on Windows"))
        config.LOCK.mkdir()
        (config.LOCK / "pid").write_text(f"{os.getpid()}\n")
        saved_win = perf_record_windows.is_process_alive
        perf_record_windows.is_process_alive = lambda pid: False
        try:
            preflight.check(**kw)
        finally:
            perf_record_windows.is_process_alive = saved_win


# --- 4) analysis.py ---


def _valid_actions_shape(actions):
    assert isinstance(actions, list), type(actions)
    for item in actions:
        assert isinstance(item, dict) and set(item) == {"tool", "arguments", "reason"}, item
        assert isinstance(item["tool"], str) and isinstance(item["arguments"], dict) and isinstance(item["reason"], str)


def test_suggested_actions_hostile_and_fuzzed_summaries():
    hostile = [
        None, [], "bad", 123, True, float("nan"), float("inf"),
        {"gpu": "bad", "hitches": ["bad"], "label": ["x"], "noisy_environment": "yes", "duration_s": "ten"},
        {"gpu": {"frames": float("nan"), "throttling_analysis": "hot", "unpresented": []}, "hitches": {"causes": []}},
        {"gpu": {"frames": float("inf")}, "hitches": {"causes": {"shader_compile": None}, "worst": "nope"}, "duration_s": float("nan")},
        {"gpu": {"frames": True}, "hitches": {"causes": {"shader_compile": 1}, "worst": [{"cause": "shader_compile", "window_ms": "xy"}]}, "duration_s": 20},
        {"gpu": {"frames": 10}, "hitches": {"causes": {"shader_compile": 1}, "worst": [{"cause": "shader_compile", "window_ms": [0, 5000]}]}, "duration_s": 20},
    ]
    for s in hostile:
        for rows in (None, [], "abc", 123, [(1, float("nan"), 2)], [(1, 0.0, 2.0)]):
            _valid_actions_shape(analysis.suggested_actions(s, "run_1", 0, rows))

    rng = random.Random(42)
    pool = [None, True, False, 0, -5, 1e308, float("nan"), float("inf"), "", "shader_compile", "thermal", [], {}, [0, 1000]]
    for _ in range(100):
        s = {
            "label": rng.choice(pool),
            "duration_s": rng.choice(pool),
            "noisy_environment": rng.choice(pool),
            "gpu": rng.choice([None, "x", [], {"frames": rng.choice(pool), "unpresented": rng.choice(pool),
                                                 "throttling_analysis": rng.choice([None, [], {"thermal_throttling_detected": rng.choice(pool)}])}]),
            "hitches": rng.choice([None, "x", [], {"causes": rng.choice([None, [], {"shader_compile": 1}, {"thermal": 1}]),
                                                     "worst": rng.choice([None, "x", [{"cause": rng.choice(pool), "window_ms": rng.choice(pool)}]])}]),
        }
        rows = rng.choice([None, [], "x", [(1, rng.choice(pool), 2.0)]])
        _valid_actions_shape(analysis.suggested_actions(s, "fuzz", 0, rows))


# --- 5) perf_report.py ---


def test_noisy_environment_extreme_and_fuzzed_inputs_never_raise():
    cases = [
        ({"device_pct": {"mean": 50.0}}, {"idle_share": -1e307}),
        ({"device_pct": {"mean": 50.0}}, {"idle_share": 1e307}),
        ({"device_pct": {"mean": 1e308}}, {"idle_share": 1e306}),
        ({"device_pct": {"mean": -1e308}}, {"idle_share": -1e306}),
    ]
    for activity, idle in cases:
        got = perf_report.noisy_environment(activity, idle)
        assert got is None or isinstance(got, dict), (activity, idle, got)

    rng = random.Random(42)
    pool = [None, True, False, 0, -1, 0.5, 1e308, float("nan"), float("inf"), "", "50", [], {}, {"mean": 10.0}]
    for _ in range(100):
        act = rng.choice([None, [], "x", {"device_pct": rng.choice(pool)}, {"device_pct": {"mean": rng.choice(pool)}}])
        idl = rng.choice([None, [], "x", {"idle_share": rng.choice(pool)}])
        got = perf_report.noisy_environment(act, idl)
        assert got is None or isinstance(got, dict), (act, idl, got)


# --- 6) paths.check_cooldown and recording.resolve_tier ---


def test_check_cooldown_rejects_falsy_and_invalid_values():
    for bad in ("", " ", [], {}, (), set(), 0j, False, True, -0.001, 600.001, float("nan"), float("inf"), float("-inf"), "nan"):
        _assert_tool_error(lambda v=bad: paths.check_cooldown(v), f"check_cooldown({bad!r})")
    for valid, expected in ((None, 0.0), (0, 0.0), (600, 600.0), ("0", 0.0), ("600", 600.0), (12.5, 12.5)):
        assert paths.check_cooldown(valid) == expected


def test_resolve_tier_rejects_invalid_memory_and_counters():
    for bad_tier in ("", "light ", "STANDARD", b"light", None, 0, True, ["deep"]):
        _assert_tool_error(lambda t=bad_tier: recording.resolve_tier(t, None, None), f"tier={bad_tier!r}")
    for bad_flag in ("no", "false", "true", "", 0, 1, [], {}, 1.0):
        _assert_tool_error(lambda f=bad_flag: recording.resolve_tier("standard", f, None), f"memory={bad_flag!r}")
        _assert_tool_error(lambda f=bad_flag: recording.resolve_tier("standard", None, f), f"counters={bad_flag!r}")
