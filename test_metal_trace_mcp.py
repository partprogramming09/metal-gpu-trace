"""Self-check of metal_trace_mcp.py, perf_report.py and gputrace_read.py without Instruments: run it with python3 -I,
or with pytest."""
import functools
import json
import os
import shutil
import pathlib
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import gputrace_read  # noqa: E402
import perf_report  # noqa: E402


def write_capture(directory):
    """Writes a .gputrace holding three drawPrimitives records into `directory` and returns its path."""
    record = struct.pack("<Ii", 0x30, -16218) + bytes(0x24 - 8) + b"Cuu\0" + bytes(8)
    capture = directory / "frame.gputrace"
    capture.mkdir()
    (capture / "capture").write_bytes(b"MTSP" + bytes(4) + record * 3)
    return capture


def test_memory_param(tmp_path):
    """perf_record passes memory=false on to the recording, which sets PERF_MEMORY=0, and offers it in its schema."""
    import metal_trace_mcp as mcp
    seen = []
    saved = mcp.record
    mcp.record = lambda *args, **kw: seen.append(args[-1]) or {}
    program = tmp_path / "prog"
    program.write_text("")
    try:
        mcp.tool_perf_record("m", str(program), wine="native")
        mcp.tool_perf_record("m", str(program), wine="native", memory=False)
    finally:
        mcp.record = saved
    assert seen == [True, False], seen
    assert mcp.RECORD_PROPS["memory"]["type"] == "boolean"


def test_no_memory(tmp_path):
    """summarize() asks for the Metal memory table by default and leaves it out with memory=False."""
    asked = []

    def fake(trace, schemas, optional=()):
        asked.append(schemas)
        raise RuntimeError("stop")

    saved = perf_report.toc_and_tables
    perf_report.toc_and_tables = fake
    try:
        for memory in (True, False):
            try:
                perf_report.summarize(tmp_path / "x.trace", "x", tmp_path, memory=memory)
            except RuntimeError:
                pass
    finally:
        perf_report.toc_and_tables = saved
    assert perf_report.MEMORY in asked[0] and perf_report.MEMORY not in asked[1], asked


def macos_only(test):
    """Skips a test that needs macOS tools (zsh, xctrace, a shell-script Wine) when run on Windows."""
    @functools.wraps(test)
    def wrapper(tmp_path):
        if sys.platform == "win32":
            try:
                import pytest
            except ImportError:
                return None
            pytest.skip("needs macOS tools")
        return test(tmp_path)
    return wrapper


@macos_only
def test_disk_guard(tmp_path):
    """perf_record.sh refuses to start, before locking or recording, when the disk lacks the space Instruments needs."""
    script = TOOLS / "perf_record.sh"
    env = {**os.environ, "PERF_OUT": str(tmp_path), "PERF_MIN_FREE_GB": "99999999"}
    proc = subprocess.run(["zsh", str(script), "g", "30", "native", "-", "-", sys.executable], env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 4 and "not enough free disk" in proc.stderr and "99999999 GB needed" in proc.stderr, proc
    assert not (tmp_path / ".recording").exists(), "no lock is left behind"
    default = subprocess.run(["zsh", str(script), "g", "60", "native", "-", "-", sys.executable],
                             env={**os.environ, "PERF_OUT": str(tmp_path), "TMPDIR": "/nonexistent"},
                             capture_output=True, text=True, timeout=60)
    assert default.returncode != 0, "a missing TMPDIR volume must not pass the guard"


def test_toc_and_tables(tmp_path):
    """At most EXPORT_WORKERS exports run at once; an optional table the trace lacks is dropped and its file
    deleted, and a failing export leaves no file behind."""
    import threading
    import time
    toc = ET.fromstring('<trace-toc><run><data><table schema="a"/></data></run></trace-toc>')
    running, peak, lock = [0], [0], threading.Lock()

    def fake_export(trace, xpath=None, toc=False, timeout=600):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1
        if "fail" in xpath:
            raise RuntimeError("boom")
        path = tmp_path / (xpath.split('"')[-2] + ".xml")
        path.write_text("<x/>")
        return str(path)

    saved = perf_report.export, perf_report.toc_of
    perf_report.export, perf_report.toc_of = fake_export, lambda trace: toc
    try:
        got_toc, tables = perf_report.toc_and_tables("t", ("a", "c", "d", "e"), optional=("c", "d", "e"))
        assert peak[0] <= perf_report.EXPORT_WORKERS, peak
        for name in ("c", "d", "e"):
            assert not (tmp_path / f"{name}.xml").exists()
        got_toc, tables = perf_report.toc_and_tables("t", ("a",), optional=("b",))
        assert got_toc is toc and set(tables) == {"a"} and pathlib.Path(tables["a"]).exists()
        got_toc, tables = perf_report.toc_and_tables("t", ("a", "b"), optional=("b",))
        assert set(tables) == {"a"} and not (tmp_path / "b.xml").exists(), "the missing optional table's file goes"
        try:
            perf_report.toc_and_tables("t", ("a", "fail"), optional=())
            raise AssertionError("a failing export must raise")
        except RuntimeError:
            assert not (tmp_path / "a.xml").exists(), "the exports that did finish are deleted"
    finally:
        perf_report.export, perf_report.toc_of = saved


def test_report(tmp_path):
    """Exported rows resolve xctrace's refs, the export file goes once read, shared summaries hold no paths, and a
    trace without the GPU intervals table fails with a hint."""
    xml = tmp_path / "table.xml"
    for early in (False, True):
        xml.write_text('<trace-query-result><node><schema><col><mnemonic>process</mnemonic></col>'
                       '<col><mnemonic>duration</mnemonic></col></schema>'
                       '<row><process id="1"><pid>42</pid></process><duration>5</duration></row>'
                       '<row><process ref="1"/><duration>7</duration></row></node></trace-query-result>')
        got = perf_report.rows(str(xml))
        first = next(got)
        assert perf_report.pid_of(first["process"]) == 42
        rest = [] if early else list(got)
        got.close()
        assert early or perf_report.pid_of(rest[0]["process"]) == 42, rest
        assert not xml.exists(), "the exported XML must be deleted once read"
    assert perf_report.public_arguments("/opt/games/x/game.exe -w 1") == "game.exe -w 1"
    try:
        perf_report.export(tmp_path / "gone.trace", toc=True)
        raise AssertionError("a missing .trace must fail before xctrace runs")
    except FileNotFoundError as error:
        assert "KEEP_TRACE" in str(error) and str(tmp_path) not in str(error)
    # xctrace may write a table whole and then die with SIGTRAP: a complete file is kept, a cut one is an error
    import subprocess as sp

    def crash_after_writing(cmd, body):
        def run(c, **kw):
            pathlib.Path(c[c.index("--output") + 1]).write_text(body)
            return sp.CompletedProcess(c, 133, "", "")
        return run
    saved_run = perf_report.subprocess.run
    (tmp_path / "x.trace").mkdir()
    try:
        perf_report.subprocess.run = crash_after_writing(None, "<trace-query-result><node/></trace-query-result>")
        kept = perf_report.export(tmp_path / "x.trace", xpath="/x")
        assert pathlib.Path(kept).exists()
        os.unlink(kept)
        # cut right after the last row, as xctrace 27.1 leaves metal-resource-allocations: every row is read
        perf_report.subprocess.run = crash_after_writing(None, '<trace-query-result><node><schema><col><mnemonic>n'
                                                               '</mnemonic></col></schema><row><n>1</n></row>\n')
        cut_rows = list(perf_report.rows(perf_report.export(tmp_path / "x.trace", xpath="/x")))
        assert len(cut_rows) == 1 and cut_rows[0]["n"].text == "1", cut_rows
        # cut right after the schema, as xctrace 27.1 leaves an empty time-profile: zero rows, not an error
        perf_report.subprocess.run = crash_after_writing(None, '<trace-query-result><node><schema><col><mnemonic>n'
                                                               '</mnemonic></col></schema>')
        assert list(perf_report.rows(perf_report.export(tmp_path / "x.trace", xpath="/x"))) == []
        perf_report.subprocess.run = crash_after_writing(None, "<trace-query-result><node>")
        try:
            perf_report.export(tmp_path / "x.trace", xpath="/x")
            raise AssertionError("a cut export must fail")
        except RuntimeError as error:
            assert "exit 133" in str(error), error
    finally:
        perf_report.subprocess.run = saved_run
    toc = ET.fromstring('<trace-toc><run><data><table schema="metal-gpu-intervals"/></data></run></trace-toc>')
    assert perf_report.missing_tables(toc) == ["ProcessCPUUsage", "device-thermal-state-intervals", "gpu-performance-state-intervals",
                                               "graphics-compiler-activity-intervals", "metal-application-encoders-list",
                                               "metal-command-buffer-error", "metal-current-allocated-size",
                                               "metal-resource-allocations"]
    try:
        perf_report.missing_tables(ET.fromstring("<trace-toc/>"))
        raise AssertionError("a trace without metal-gpu-intervals must fail")
    except ValueError as error:
        assert "trace_tables" in str(error), error


def test_encoders(tmp_path):
    """Encoders, command buffers, short encoders, labels and idle gaps come out exact for two hand-made frames."""
    spans = [(1, 0, 5000, "a", "x"), (1, 5000, 5000, "b", "x"), (1, 20000, 100000, "c", "x"),
             (2, 2_000_000, 5000, "d", "y"), (2, 2_005_000, 1_000_000, "e", "z")]
    labels = {"a": "[0] Blit Command 0", "b": "[1] Blit Command 1", "c": "[2] Render Command 2",
              "d": "[0] Blit Command 0", "e": "[1] Render Command 1"}
    got = perf_report.encoder_stats(spans, labels)
    assert got["per_frame"]["p50"] == 3 and got["command_buffers_per_frame"]["p50"] == 2, got
    assert got["short_share"] == {"10": 0.6, "25": 0.6, "50": 0.6, "100": 0.6, "250": 0.8, "500": 0.8, "1000": 0.8}
    assert [(g["label"], g["per_frame"], g["total_ms"]) for g in got["by_label"]] == [
        ("Render Command", 1.0, 1.1), ("Blit Command", 1.5, 0.015)], got["by_label"]
    idle = perf_report.idle_gaps(spans)
    assert idle["idle_ms_per_frame"]["max"] == 1.88 and idle["gaps_over_1ms"] == 1, idle
    assert idle["idle_share"] == round(1.89 / 3.005, 3), idle


def test_pacing_and_hitches():
    """Pacing numbers come out exact for hand-made frames, and each slow frame gets the cause the trace shows."""
    gaps = [10.0] * 98 + [30.0, 10.0]
    got = perf_report.frame_pacing(gaps, [5.0] * 100)
    assert got["fps_1pct_low"] == 33.3 and got["fps_01pct_low"] is None, got
    assert got["stutter_rate_pct"] == 1.0 and got["frame_jitter_ms"] == 2.0, got
    assert got["throttling_analysis"]["thermal_throttling_detected"] is False, got
    assert perf_report.frame_pacing([], []) == {}
    uncapped = [1.8] * 90 + [3.0] * 9 + [24.0]
    quiet = perf_report.frame_pacing(uncapped, [1.0] * 100)
    assert quiet["stutter_rate_pct"] == 1.0, quiet
    starts = [sum(uncapped[:i]) for i in range(101)]
    noise = perf_report.attribute_hitches(list(range(101)), starts, [1.0] * 101, [], [], [])
    assert noise["count"] == 1 and noise["threshold_ms"] == 8.0 and noise["worst"][0]["interval_ms"] == 24.0, noise
    starts = [0, 10, 20, 50, 60, 100, 110, 150, 160, 200, 210]
    frames = list(range(len(starts)))
    totals = [5] * len(starts)
    totals[8] = 39
    memory = [(0, 0), (160, 0), (200, 20 * 2**20)]
    got = perf_report.attribute_hitches(frames, starts, totals, [(25, 30)], [(70, 80)], memory)
    assert got["count"] == 5 and got["threshold_ms"] == 15.0, got
    assert [h["cause"] for h in sorted(got["worst"], key=lambda h: h["frame"])] == [
        "shader_compile", "thermal", "cpu_or_wait", "gpu_heavy", "memory_growth"], got
    assert perf_report.attribute_hitches([1], [0], [1], [], [], []) == {"count": 0, "causes": {}, "worst": []}
    assert "cpu_pct" not in got["worst"][0], "no CPU samples, no cpu_pct"
    cpu = [(t, 300.0) for t in range(0, 160, 10)] + [(t, 100.0) for t in range(160, 211, 10)]
    busy = perf_report.attribute_hitches(frames, starts, totals, [(25, 30)], [(70, 80)], memory, cpu=cpu)
    by_frame = {h["frame"]: h["cpu_pct"] for h in busy["worst"]}
    assert by_frame[3] == 300.0 and by_frame[10] == 100.0, by_frame  # the interval before a hitch is where the mean is taken
    assert perf_report.attribute_hitches(frames, starts, totals, [], [], [], cpu=[(500, 1.0)])["worst"][0]["cpu_pct"] is None


def test_diagnose(tmp_path):
    """perf_diagnose gives a verdict from a summary's encoder numbers and asks to record again an older summary."""
    import metal_trace_mcp as mcp
    saved, mcp.OUT = mcp.OUT, tmp_path
    try:
        encoders = {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5},
                    "short_share": {"25": 0.497, "50": 0.572}, "by_label": []}
        (tmp_path / "new.json").write_text(json.dumps({"gpu": {"frames": 1378}, "encoders": encoders}))
        (tmp_path / "old.json").write_text(json.dumps({"gpu": {"frames": 1378}}))
        got = mcp.tool_perf_diagnose("new")
        assert got["too_many_short_encoders"] and not got["too_short"], got
        assert got["bottleneck"] == "UNKNOWN" and got["stutter_analysis"]["verdict"] == "UNKNOWN", got
        no_spans = {"gpu": {"frames": 500, "frame_gpu_ms": {"count": 500, "mean": 14.5},
                            "frame_interval_ms": {"count": 499, "mean": 16.7, "p50": 16.6, "p95": 17.0},
                            "stutter_rate_pct": 0.0, "frame_jitter_ms": 0.4},
                    "encoders": {"per_frame": {"count": 0}, "command_buffers_per_frame": {"count": 0},
                                 "short_share": {"25": 0.0}, "by_label": []},
                    "gpu_idle": {"idle_ms_per_frame": {"count": 0}, "gaps_over_1ms": 0, "idle_share": None}}
        (tmp_path / "pm.json").write_text(json.dumps(no_spans))
        got = mcp.tool_perf_diagnose("pm")
        assert got["bottleneck"] == "UNKNOWN" and got["stutter_analysis"]["verdict"] == "SMOOTH", got
        busy = {**no_spans, "gpu_idle": {"idle_ms_per_frame": {"count": 1}, "gaps_over_1ms": 0, "idle_share": 0.4},
                "hitches": {"count": 3, "causes": {"shader_compile": 3}, "worst": []}}
        (tmp_path / "cpu.json").write_text(json.dumps(busy))
        got = mcp.tool_perf_diagnose("cpu")
        assert got["bottleneck"] == "CPU_SUBMISSION_BOUND" and got["hitches"]["count"] == 3, got
        assert any("compilador gráfico" in r for r in got["recommendations"]), got
        assert not any("FlipQueueSize" in r for r in got["recommendations"]), got
        for fps, p50, p95, synced in ((119.9, 8.33, 8.9, 120), (60.1, 16.6, 17.2, 60), (119.9, 8.3, 14.0, None),
                                      (97.0, 10.3, 10.6, None), (None, None, None, None),
                                      (118.9, 8.41, 9.824, 120)):
            sync = {**no_spans, "gpu": {**no_spans["gpu"], "fps_estimate": fps,
                                        "frame_interval_ms": {"count": 499, "mean": 16.7, "p50": p50, "p95": p95}}}
            (tmp_path / "sync.json").write_text(json.dumps(sync))
            got = mcp.tool_perf_diagnose("sync")
            assert got["display_synced_hz"] == synced, (fps, got["display_synced_hz"])
            assert any("sincronización vertical" in r for r in got["recommendations"]) == bool(synced), got
        hung = {**no_spans, "gpu_activity": {"samples": 9, "device_pct": {"mean": 50}, "split_scenes": 12, "recoveries": 1,
                                             "gpu_recovered": True}}
        (tmp_path / "hung.json").write_text(json.dumps(hung))
        got = mcp.tool_perf_diagnose("hung")
        assert got["gpu_activity"]["gpu_recovered"] is True, got
        assert any("se recuperó 1 vez" in r for r in got["recommendations"]), got
        assert any("dividió 12 escenas" in r for r in got["recommendations"]), got
        calm = {**no_spans, "gpu_activity": {"samples": 9, "split_scenes": 0, "recoveries": 0, "gpu_recovered": False}}
        (tmp_path / "calm.json").write_text(json.dumps(calm))
        got = mcp.tool_perf_diagnose("calm")
        assert not any("recuper" in r or "dividió" in r for r in got["recommendations"]), got
        (tmp_path / "winbusy.json").write_text(json.dumps({**busy, "template": "Windows Native Trace"}))
        assert any("FlipQueueSize" in r for r in mcp.tool_perf_diagnose("winbusy")["recommendations"])
        assert not mcp.tool_perf_diagnose("new", min_encoders=8)["too_many_short_encoders"]
        for run, kwargs, words in (("old", {}, "record it again"), ("new", {"short_us": 30}, "short_us is one of")):
            try:
                mcp.tool_perf_diagnose(run, **kwargs)
                raise AssertionError(f"{run} {kwargs} must fail")
            except mcp.ToolError as error:
                assert words in str(error), error
    finally:
        mcp.OUT = saved


def test_compare(tmp_path):
    """perf_compare reports encoder and idle changes and each label's change in GPU ms per frame, largest first,
    and names a run summarized before encoders existed instead of returning nothing for it."""
    import metal_trace_mcp as mcp

    def summary(frames, encoders, buffers, short, idle, labels):
        return {"gpu": {"frames": frames, "fps_estimate": 100.0},
                "encoders": {"per_frame": {"p50": encoders}, "command_buffers_per_frame": {"p50": buffers},
                             "short_share": {"25": short, "50": short},
                             "by_label": [{"label": n, "per_frame": c, "total_ms": t} for n, c, t in labels]},
                "gpu_idle": {"idle_share": idle, "idle_ms_per_frame": {"p50": idle * 10}}}
    saved, mcp.OUT = mcp.OUT, tmp_path
    try:
        # a: 100 frames; b: 200 frames, so Blit's total doubles while its ms per frame stays
        (tmp_path / "a.json").write_text(json.dumps(summary(100, 2, 1, 0.02, 0.4, [
            ("Render Command", 1.0, 500.0), ("Blit Command", 1.0, 10.0), ("Old Pass", 1.0, 50.0)])))
        (tmp_path / "b.json").write_text(json.dumps(summary(200, 7, 5, 0.5, 0.75, [
            ("Render Command", 3.0, 800.0), ("Blit Command", 4.0, 20.0), ("New Pass", 1.0, 400.0)])))
        (tmp_path / "old.json").write_text(json.dumps({"gpu": {"frames": 300, "fps_estimate": 90.0}}))
        got = mcp.tool_perf_compare("a", "b")
        assert got["encoders"]["encoders_per_frame_p50"] == {"a": 2, "b": 7, "change": 5, "change_pct": 250.0}
        assert got["encoders"]["short_encoder_share"] == {"a": 0.02, "b": 0.5, "change": 0.48, "change_pct": None}
        assert got["encoders"]["gpu_idle_share"]["change"] == 0.35, got["encoders"]
        assert [(r["label"], r["state"], r["ms_per_frame_change"]) for r in got["labels"]] == [
            ("New Pass", "new", 2.0), ("Render Command", "changed", -1.0), ("Old Pass", "gone", -0.5),
            ("Blit Command", "changed", 0.0)], got["labels"]
        assert got["metrics"]["fps"]["change"] == 0.0 and got["too_short"] == []
        old = mcp.tool_perf_compare("old", "b")
        assert old["encoders"]["missing_in"] == ["old"] and "labels" not in old, old
        assert old["metrics"]["fps"] == {"a": 90.0, "b": 100.0, "change": 10.0, "change_pct": 11.1}, old["metrics"]
        try:
            mcp.tool_perf_compare("a", "b", short_us=30)
            raise AssertionError("short_us 30 must fail")
        except mcp.ToolError as error:
            assert "short_us is one of" in str(error), error
    finally:
        mcp.OUT = saved


def test_baseline(tmp_path):
    """perf_baseline saves copies of several runs as a reference with their range, perf_runs leaves the reference
    file out, and perf_check judges a run against that range: same inside it, regressed when FPS falls below it by
    more than the margin or an encoder per frame is added, improved when FPS rises above it, and still usable once
    the reference's runs are deleted."""
    import metal_trace_mcp as mcp

    def summary(fps, gpu_ms, encoders, frames=300):
        return {"gpu": {"frames": frames, "fps_estimate": fps, "frame_gpu_ms": {"mean": gpu_ms, "p95": gpu_ms * 2},
                        "frame_interval_ms": {"p95": 20.0}},
                "encoders": {"per_frame": {"p50": encoders}, "command_buffers_per_frame": {"p50": 5},
                             "short_share": {"25": 0.5}, "by_label": [{"label": "Render", "per_frame": 1.0, "total_ms": 1.0}]},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}}
    saved, (mcp.OUT, mcp.BASELINES) = (mcp.OUT, mcp.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        for tick, (name, fps) in enumerate((("r1", 60.0), ("r2", 62.0), ("r3", 61.0))):
            path = tmp_path / f"{name}.json"
            path.write_text(json.dumps(summary(fps, 4.3, 7)))
            os.utime(path, (1_000_000 + tick, 1_000_000 + tick))  # distinct times: file clocks can tie on Windows
        got = mcp.tool_perf_baseline("ds", ["r1", "r2", "r3"])
        assert got["range"]["fps"] == {"min": 60.0, "max": 62.0} and got["runs"] == ["r1", "r2", "r3"], got
        assert [r["run"] for r in mcp.tool_perf_runs()["rows"]] == ["r3", "r2", "r1"]
        assert mcp.tool_perf_baseline()["baselines"][0]["name"] == "ds"
        cases = {"same": summary(59.0, 4.4, 7), "regressed_fps": summary(55.0, 4.3, 7),
                 "regressed_enc": summary(61.0, 4.3, 8), "improved": summary(65.0, 4.3, 7),
                 "short": summary(61.0, 4.3, 7, frames=50), "old": {"gpu": {"frames": 300, "fps_estimate": 61.0}}}
        for name, s in cases.items():
            (tmp_path / f"{name}.json").write_text(json.dumps(s))
        assert mcp.tool_perf_check("same", "ds")["verdict"] == "same"
        fps = mcp.tool_perf_check("regressed_fps", "ds")
        assert fps["verdict"] == "regressed" and fps["regressed"][0]["metric"] == "fps", fps
        enc = mcp.tool_perf_check("regressed_enc", "ds")
        assert [r["metric"] for r in enc["regressed"]] == ["encoders_per_frame_p50"], enc
        assert enc["comparison"]["encoders"]["encoders_per_frame_p50"]["b"] == 8
        assert mcp.tool_perf_check("improved", "ds")["verdict"] == "improved"
        assert "hint" in mcp.tool_perf_check("short", "ds")
        old = mcp.tool_perf_check("old", "ds")
        assert old["verdict"] == "same" and "encoders_per_frame_p50" in old["unchecked"], old
        for name in ("r1", "r2", "r3"):
            (tmp_path / f"{name}.json").unlink()
        assert mcp.tool_perf_check("same", "ds")["verdict"] == "same", "a reference outlives its runs"
        for bad in (("bad name!", ["same"]), ("nope", None), (None, ["same"])):
            try:
                mcp.tool_perf_baseline(*bad)
                raise AssertionError(bad)
            except mcp.ToolError:
                pass
        try:
            mcp.tool_perf_check("same", "nope")
            raise AssertionError("missing reference must fail")
        except mcp.ToolError as error:
            assert "no reference" in str(error)
    finally:
        mcp.OUT, mcp.BASELINES = saved


def test_trace_count(tmp_path):
    """trace_count counts a table's rows in all and per process, names tables the trace lacks, and refuses odd names."""
    import metal_trace_mcp as mcp
    table = ('<trace-query-result><node><schema><col><mnemonic>process</mnemonic></col><col><mnemonic>n</mnemonic></col>'
             '</schema><row><process id="1" fmt="wine (42)"><pid>42</pid></process><n>1</n></row>'
             '<row><process ref="1"/><n>2</n></row><row><process id="2" fmt="WindowServer (7)"><pid>7</pid></process>'
             '<n>3</n></row></node></trace-query-result>')
    calls = []

    def export(trace, xpath=None, **_):
        calls.append(xpath)
        path = tmp_path / f"t{len(calls)}.xml"
        path.write_text(table)
        return str(path)
    saved = mcp.perf_report.export, mcp.tool_trace_tables, mcp.OUT
    mcp.perf_report.export, mcp.tool_trace_tables, mcp.OUT = export, lambda t: {"tables": ["spill-events"]}, tmp_path
    try:
        (tmp_path / "r1.trace").mkdir()
        got = mcp.tool_trace_count("r1", ["spill-events", "time-profile"])
        assert got["tables"]["spill-events"] == {"rows": 3, "by_process": {"wine (42)": 2, "WindowServer (7)": 1}}, got
        assert got["tables"]["time-profile"]["rows"] is None and len(calls) == 1, got
        try:
            mcp.tool_trace_count("r1", ["x;y"])
            raise AssertionError("an odd table name must fail")
        except mcp.ToolError:
            pass
    finally:
        mcp.perf_report.export, mcp.tool_trace_tables, mcp.OUT = saved


def test_baseline_record(tmp_path):
    """perf_baseline_record records count runs named name-1.. with perf_record's arguments and saves them as the
    reference; count outside 1 to 10 fails before recording."""
    import metal_trace_mcp as mcp
    made = []

    def fake_record(label, **kw):
        made.append((label, kw))
        (tmp_path / f"{label}_20261018-000000.json").write_text(json.dumps(
            {"gpu": {"frames": 300, "fps_estimate": 60.0 + len(made), "frame_gpu_ms": {"mean": 4.0}},
             "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5}}}))
    saved = mcp.tool_perf_record, mcp.OUT, mcp.BASELINES
    mcp.tool_perf_record, mcp.OUT, mcp.BASELINES = fake_record, tmp_path, tmp_path / "baselines.json"
    try:
        got = mcp.tool_perf_baseline_record("ds", count=2, workload="drawstress", api="d3d12", seconds=30)
        assert [m[0] for m in made] == ["ds-1", "ds-2"] and made[0][1] == {"workload": "drawstress", "api": "d3d12", "seconds": 30}
        assert got["runs"] == ["ds-1_20261018-000000", "ds-2_20261018-000000"], got
        assert got["range"]["fps"] == {"min": 61.0, "max": 62.0}, got
        for bad in (0, 11):
            try:
                mcp.tool_perf_baseline_record("ds", count=bad)
                raise AssertionError(bad)
            except mcp.ToolError:
                pass
        assert len(made) == 2
    finally:
        mcp.tool_perf_record, mcp.OUT, mcp.BASELINES = saved


def test_levers(tmp_path):
    """memory_free_pct holds memory_pressure around a recording and stops it even when the recording fails;
    background sets PERF_PREFIX for perf_record.sh; out-of-range or Windows use is refused before anything starts."""
    import metal_trace_mcp as mcp
    stable = tmp_path / "stable.sh"
    stable.write_text("#!/bin/sh\necho 'Stable at percent free: 40.'\nsleep 300\n")
    never = tmp_path / "never.sh"
    never.write_text("#!/bin/sh\nsleep 300\n")
    for script in (stable, never):
        script.chmod(0o755)
    assert mcp.BACKGROUND_PREFIX.startswith("/") and mcp.BACKGROUND_PREFIX.endswith(" -b"), mcp.BACKGROUND_PREFIX
    if sys.platform == "darwin":
        assert os.access(mcp.BACKGROUND_PREFIX.split()[0], os.X_OK), "taskpolicy must exist"
    saved = mcp.MEMORY_PRESSURE, mcp.record_run
    try:
        mcp.MEMORY_PRESSURE = [str(stable)]
        proc = mcp.hold_memory_pressure(40, 60)
        assert proc.poll() is None
        proc.terminate()
        proc.wait()
        mcp.MEMORY_PRESSURE = [str(never)]
        try:
            mcp.hold_memory_pressure(40, 60, wait_s=1)
            raise AssertionError("a pressure that is never reached must fail")
        except mcp.ToolError as error:
            assert "did not reach" in str(error), error
        started = []
        mcp.MEMORY_PRESSURE = [str(stable)]
        original = mcp.hold_memory_pressure

        def spy(*args, **kwargs):
            started.append(original(*args, **kwargs))
            return started[-1]
        mcp.hold_memory_pressure = spy
        seen = {}

        def fake_run(*args, **kwargs):
            seen.update(kwargs, held=started[0].poll() is None)
            raise RuntimeError("boom")
        mcp.record_run = fake_run
        try:
            mcp.record("x", 5, "native", "-", ".", ["p"], memory_free_pct=40, background=True)
            raise AssertionError("the failure must come out")
        except RuntimeError:
            pass
        assert seen["held"] and seen["background"] is True, seen
        started[0].wait(timeout=10)
        assert started[0].poll() is not None, "memory_pressure must be stopped after the recording"
        mcp.hold_memory_pressure = original
        for kwargs in ({"memory_free_pct": 10}, {"memory_free_pct": 61}, {"memory_free_pct": "x"}):
            try:
                mcp.check_levers(**kwargs)
                raise AssertionError(kwargs)
            except mcp.ToolError as error:
                assert "memory_free_pct" in str(error), error
        mcp.check_levers(memory_free_pct=20, background=True)
    finally:
        mcp.MEMORY_PRESSURE, mcp.record_run = saved
        mcp.hold_memory_pressure = original
    assert mcp.RECORD_PROPS["memory_free_pct"]["type"] == "integer" and mcp.RECORD_PROPS["background"]["type"] == "boolean"


def test_readme_lists_every_tool(tmp_path):
    """Both READMEs hold a table row for every tool the server offers, and name the words the 0.17.0 additions need."""
    import re
    import metal_trace_mcp as mcp
    for name in ("README.md", "es/README.md"):
        rows = set(re.findall(r"^\| `([a-z_]+)` \|", (TOOLS / name).read_text(encoding="utf-8"), re.M))
        missing = sorted(set(mcp.TOOLS) - rows)
        assert not missing, f"{name} lacks rows for {missing}"
        text = (TOOLS / name).read_text(encoding="utf-8")
        for word in ("mtl-x64", "bgfx-examples", "memory_free_pct", "gpu_state", "screen_locked", "resource_allocations"):
            assert word in text, f"{name} does not mention {word}"


def test_resource_summary(tmp_path):
    """resource_summary() counts one process's allocation events: total and per frame, by type, per second and after the
    first 3 s, and ignores other processes and events that are not allocations."""
    def cell(text, fmt=None):
        el = ET.Element("v", {"fmt": fmt} if fmt else {})
        el.text = text
        return el

    def process(pid):
        el = ET.Element("process")
        ET.SubElement(el, "pid", {"fmt": str(pid)})
        return el

    def row(pid, t_ms, size, kind="Buffer", event="Allocation"):
        return {"process": process(pid), "timestamp": cell(str(t_ms * 1_000_000)), "resource-size": cell(str(size)),
                "resource-type": cell(kind), "event-type": cell(event)}
    rows = [row(7, 100, 1 << 20), row(7, 900, 1 << 20), row(7, 1500, 2 << 20, "Texture"), row(7, 3200, 1 << 20),
            row(7, 3300, 512 << 10, event="Deallocation"), row(8, 200, 1 << 30), row(7, 5900, 1 << 20)]
    got = perf_report.resource_summary(rows, 7, frames=50)
    assert got["events"] == 5 and got["mib"] == 6.0 and got["per_frame"] == 0.1, got
    assert got["by_type"] == {"Buffer": {"count": 4, "mib": 4.0}, "Texture": {"count": 1, "mib": 2.0}}, got
    assert got["after_3s"] == {"count": 2, "mib": 2.0} and got["per_second"] == [2, 1, 0, 1, 0, 1], got
    assert perf_report.resource_summary(rows, 99, frames=50) == {"events": 0}
    assert perf_report.resource_summary(rows, 7, frames=0)["per_frame"] is None


def test_rosetta_layer(tmp_path):
    """An api marked rosetta in data/workloads.json is named as such in the run's layer, so perf_compare against native
    Metal says it compares two layers."""
    import metal_trace_mcp as mcp
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/x.tar.gz", "bytes": 1,
             "sha256": "0" * 64, "dir": "demo", "dim_variable": "DIM",
             "apis": {"mtl": {"program": "demo", "args": "--mtl", "wine": False},
                      "mtl-x64": {"program": "demo-x64", "args": "--mtl", "wine": False, "rosetta": True}}}
    saved = mcp.WORKLOADS
    mcp.WORKLOADS = {"demo": entry}
    try:
        assert mcp.workload_layer("demo", "mtl", 20) is None
        layer = mcp.workload_layer("demo", "mtl-x64", 20)
        assert "rosetta" in layer and layer["program_env"] == "DIM=20", layer
        assert mcp.layer_label(layer) == "rosetta"
        native = {"none": "native Metal, no translation layer", "program_env": "DIM=20"}
        ma = {"layer": native, "gpu": {"frames": 300}}
        mb = {"layer": layer, "gpu": {"frames": 300}}
        got = mcp.layer_change(ma, mb, "a", "b")
        assert got["same"] is False and got["b"] == "rosetta" and "two layers" in got["note"], got
    finally:
        mcp.WORKLOADS = saved
    shipped = json.loads((TOOLS / "data" / "workloads.json").read_text())["workloads"]["drawstress"]
    assert shipped["apis"]["mtl-x64"]["rosetta"] is True and shipped["size_variables"] == ["DRAWSTRESS_WIDTH", "DRAWSTRESS_HEIGHT"]
    assert "workloads-3" in shipped["url"] and len(shipped["sha256"]) == 64


def test_gpu_activity(tmp_path):
    """agx_summary() reads the per-second AGX sample: utilization stats, the growth of split scenes and of the recovery
    count, and it tolerates empty cells and a missing column."""
    csv_path = tmp_path / "r.agx.csv"
    csv_path.write_text("time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib\n"
                        "0,10,8,6,0,1,700\n1,50,40,30,2,1,710\n2,,,,5,2,720\n3,90,80,70,9,2,730\n")
    got = perf_report.agx_summary(csv_path)
    assert got["samples"] == 4 and got["device_pct"]["max"] == 90 and got["device_pct"]["count"] == 3, got
    assert got["split_scenes"] == 9 and got["recoveries"] == 1 and got["gpu_recovered"] is True, got
    assert got["in_use_mib"]["max"] == 730, got
    csv_path.write_text("time_s,device_pct\n0,10\n1,20\n")
    got = perf_report.agx_summary(csv_path)
    assert got["device_pct"]["mean"] == 15 and got["split_scenes"] is None and got["gpu_recovered"] is None, got
    csv_path.write_text("time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib\n")
    assert perf_report.agx_summary(csv_path) == {"samples": 0}
    assert perf_report.agx_summary(tmp_path / "none.csv") is None


def test_size(tmp_path):
    """size ("WxH") becomes the workload's two size variables, is refused for a workload without them or when badly
    written, and perf_sweep can sweep it."""
    import metal_trace_mcp as mcp
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/x.tar.gz", "bytes": 1,
             "sha256": "0" * 64, "dir": "demo", "dim_variable": "DIM", "size_variables": ["DEMO_W", "DEMO_H"],
             "apis": {"mtl": {"program": "demo", "args": "--mtl", "wine": False}}}
    plain = {k: v for k, v in entry.items() if k != "size_variables"}
    saved, cache = mcp.WORKLOADS, mcp.CACHE
    mcp.CACHE = tmp_path
    try:
        mcp.WORKLOADS = {"demo": entry, "plain": plain}
        for name in ("demo", "plain"):
            (tmp_path / f"{name}-{'0' * 12}").mkdir()
        got = mcp.workload_command("demo", "mtl", 20, None, "", size="1280x720")
        assert got[3] == "DIM=20 DEMO_W=1280 DEMO_H=720", got
        assert mcp.workload_command("demo", "mtl", None, None, "")[3] == ""
        for name, size, words in (("plain", "1280x720", "size does not apply to plain"),
                                  ("demo", "big", "size is WIDTHxHEIGHT"), ("demo", "100x100", "size is WIDTHxHEIGHT"),
                                  ("demo", "9000x720", "size is WIDTHxHEIGHT")):
            try:
                mcp.workload_command(name, "mtl", None, None, "", size=size)
                raise AssertionError((name, size))
            except mcp.ToolError as error:
                assert words in str(error), error
        made = []

        def fake_record(label, **kw):
            made.append((label, kw.get("size")))
            (tmp_path / f"{label}_20261018-000000.json").write_text(json.dumps(
                {"gpu": {"frames": 300, "fps_estimate": 100.0, "frame_gpu_ms": {"mean": 4.0}, "stutter_rate_pct": 0.0}}))
        saved_record, saved_out = mcp.tool_perf_record, mcp.OUT
        mcp.tool_perf_record, mcp.OUT = fake_record, tmp_path
        try:
            got = mcp.tool_perf_sweep("s", "size", ["640x360", "1280x720"], seconds=8)
            assert made == [("s-1-r1", "640x360"), ("s-2-r1", "1280x720")] and got["fit"] is None, (made, got)
            try:
                mcp.tool_perf_sweep("s", "size", ["640x360", "wide"])
                raise AssertionError("a bad size must fail before recording")
            except mcp.ToolError as error:
                assert "WIDTHxHEIGHT" in str(error), error
        finally:
            mcp.tool_perf_record, mcp.OUT = saved_record, saved_out
    finally:
        mcp.WORKLOADS, mcp.CACHE = saved, cache
    assert mcp.RECORD_PROPS["size"]["type"] == "string"


def test_perf_sweep(tmp_path):
    """perf_sweep records one run per value of one variable, alternating the order each round, takes each metric's
    median per value, fits GPU ms per frame on draws (dim^3) and refuses bad input before recording."""
    import metal_trace_mcp as mcp
    made = []

    def fake_record(label, **kw):
        made.append((label, kw.get("dim"), kw.get("env", "")))
        dim = kw.get("dim") or 10
        (tmp_path / f"{label}_20261018-000000.json").write_text(json.dumps(
            {"gpu": {"frames": 300, "fps_estimate": 1000 / (0.5 + 0.001 * dim ** 3), "frame_gpu_ms": {"mean": 0.5 + 0.001 * dim ** 3},
                     "stutter_rate_pct": 1.0}}))
    saved = mcp.tool_perf_record, mcp.OUT
    mcp.tool_perf_record, mcp.OUT = fake_record, tmp_path
    try:
        got = mcp.tool_perf_sweep("t", "dim", [10, 20, 30], rounds=2, seconds=30, label="ignored")
        assert [m[0] for m in made] == ["t-1-r1", "t-2-r1", "t-3-r1", "t-3-r2", "t-2-r2", "t-1-r2"], made
        assert [m[1] for m in made] == [10, 20, 30, 30, 20, 10], made
        assert [r["value"] for r in got["rows"]] == [10, 20, 30] and len(got["rows"][0]["runs"]) == 2, got
        assert got["rows"][2]["metrics"]["frame_gpu_ms_mean"] == 27.5, got
        fit = got["fit"]
        assert fit["x"] == "dim^3" and abs(fit["ms_per_unit"] - 0.001) < 1e-9 and abs(fit["ms_fixed"] - 0.5) < 1e-9, fit
        assert fit["r2"] == 1.0 and not got["too_short"], got
        made.clear()
        env = mcp.tool_perf_sweep("e", "env:MULLION_X", ["0", "1"], env="A=1")
        assert [m[2] for m in made] == ["A=1 MULLION_X=0", "A=1 MULLION_X=1"] and env["fit"] is None, (made, env)
        made.clear()
        for variable, values, rounds in (("fps", [1, 2], 1), ("dim", [10], 1), ("dim", list(range(2, 11)), 1),
                                         ("dim", [2, 3, 4, 5, 6, 7, 8], 4), ("dim", [10, "x"], 1), ("env:bad name", [1, 2], 1),
                                         ("dim", [10, 20], 0)):
            try:
                mcp.tool_perf_sweep("t", variable, values, rounds=rounds)
                raise AssertionError((variable, values, rounds))
            except mcp.ToolError:
                pass
        assert not made
    finally:
        mcp.tool_perf_record, mcp.OUT = saved


def test_perf_ab(tmp_path):
    """perf_ab records A B B A, passes each side's env on, and calls a metric better or worse only when every B value
    lies outside A's range; a bad env or rounds fails before recording."""
    import metal_trace_mcp as mcp
    made = []

    def fake_record(label, **kw):
        made.append((label, kw["env"]))
        fps = 100.0 if label.split("-")[-1][0] == "a" else 150.0
        (tmp_path / f"{label}_20261018-000000.json").write_text(json.dumps(
            {"gpu": {"frames": 300, "fps_estimate": fps + len(made) / 10, "frame_gpu_ms": {"mean": 4.0},
                     "stutter_rate_pct": 2.0}}))
    saved = mcp.tool_perf_record, mcp.OUT
    mcp.tool_perf_record, mcp.OUT = fake_record, tmp_path
    try:
        got = mcp.tool_perf_ab("t", "", "MULLION_X=1", seconds=30, label="ignored")
        assert made == [("t-a1", ""), ("t-b1", "MULLION_X=1"), ("t-b2", "MULLION_X=1"), ("t-a2", "")], made
        assert got["metrics"]["fps_estimate"]["verdict"] == "better", got
        assert got["metrics"]["frame_gpu_ms_mean"]["verdict"] == "same", got
        assert got["metrics"]["fps_1pct_low"]["verdict"] == "unknown" and not got["too_short"], got
        for kwargs in ({"env_b": "NOT A PAIR"}, {"rounds": 0}, {"rounds": 6}):
            try:
                mcp.tool_perf_ab("t", **({"env_a": "", "env_b": ""} | kwargs))
                raise AssertionError(kwargs)
            except mcp.ToolError:
                pass
        assert len(made) == 4
    finally:
        mcp.tool_perf_record, mcp.OUT = saved
    assert mcp.ab_verdict([10, 12], [11, 20], True) == "same"
    assert mcp.ab_verdict([10, 12], [5, 9], True) == "worse" and mcp.ab_verdict([10, 12], [5, 9], False) == "better"


@macos_only
def test_layer(tmp_path):
    """A recording's layer fingerprint is stable, changes with any Direct3D DLL, carries the overrides and program
    variables, and perf_compare tells two layers from one."""
    import metal_trace_mcp as mcp
    wine, prefix = tmp_path / "mullion-wine", tmp_path / "prefix"
    (wine / "bin").mkdir(parents=True)
    (wine / "bin" / "wine").write_text("#!/bin/sh\necho wine-11.0\n")
    (wine / "bin" / "wine").chmod(0o755)
    builtin, system32 = wine / "lib" / "wine" / "x86_64-windows", prefix / "drive_c" / "windows" / "system32"
    builtin.mkdir(parents=True)
    system32.mkdir(parents=True)
    for name in mcp.LAYER_DLLS:
        (builtin / f"{name}.dll").write_bytes(name.encode())
    (system32 / "d3d12.dll").write_bytes(b"d3d12")
    (prefix / "user.reg").write_text('[Software\\\\Wine\\\\DllOverrides] 1\n"*d3d12"="native,builtin"\n"comctl32"="n"\n'
                                     '[Software\\\\Wine\\\\Other] 2\n"dxgi"="n"\n')
    saved = os.environ.get("WINEDLLOVERRIDES")
    os.environ["WINEDLLOVERRIDES"] = "d3d11=n"
    try:
        one = mcp.layer_of(str(wine), str(prefix), "MULLION_DIAG=profile LOG=/tmp/x/log.txt")
        assert one == mcp.layer_of(str(wine), str(prefix), "MULLION_DIAG=profile LOG=/tmp/x/log.txt")
    finally:
        os.environ.pop("WINEDLLOVERRIDES") if saved is None else os.environ.update(WINEDLLOVERRIDES=saved)
    assert one["wine"] == "mullion-wine" and one["wine_version"] == "wine-11.0", one
    assert one["overrides"] == {"environment": "d3d11=n;mscoree=;mshtml=", "registry": {"*d3d12": "native,builtin"}}
    assert one["dlls"]["d3d12"]["prefix"]["bytes"] == 5 and one["dlls"]["dxgi"]["prefix"] is None, one["dlls"]
    assert one["program_env"] == "MULLION_DIAG=profile LOG=log.txt" and str(tmp_path) not in json.dumps(one)
    (builtin / "d3d11.dll").write_bytes(b"other build")
    two = mcp.layer_of(str(wine), str(prefix))
    assert two["fingerprint"] != one["fingerprint"]
    # Wine's first boot copies its own DLLs into the prefix: the same DLL, so nothing changes
    (system32 / "dxgi.dll").write_bytes(b"dxgi")
    assert mcp.layer_of(str(wine), str(prefix))["fingerprint"] == two["fingerprint"]
    (system32 / "dxgi.dll").write_bytes(b"other dxgi")
    three = mcp.layer_of(str(wine), str(prefix))
    assert three["fingerprint"] != two["fingerprint"]
    assert mcp.layer_change({"layer": two}, {"layer": three}, "a", "b")["differs"] == ["dxgi"]
    (system32 / "dxgi.dll").unlink()
    assert mcp.layer_of("native", "-") == {"none": "native Metal, no translation layer", "program_env": ""}
    runs = {"one": one, "one-again": one, "two": two, "native": mcp.layer_of("native", "-"), "old": None}
    same = mcp.layer_change({"layer": runs["one"]}, {"layer": runs["one-again"]}, "a", "b")
    assert same["same"] and same["differs"] == [] and "program_env" not in same, same
    other = mcp.layer_change({"layer": runs["one"]}, {"layer": runs["two"]}, "a", "b")
    assert not other["same"] and other["differs"] == ["d3d11"] and "two layers" in other["note"], other
    assert other["program_env"] == {"a": "MULLION_DIAG=profile LOG=log.txt", "b": ""}
    assert not mcp.layer_change({"layer": runs["native"]}, {"layer": runs["one"]}, "a", "b")["same"]
    assert mcp.layer_change({}, {"layer": runs["one"]}, "old", "b")["missing_in"] == ["old"]
    assert mcp.layer_label(runs["native"]) == "native" and mcp.layer_label(one).endswith("mullion-wine wine-11.0")


def test_workloads(tmp_path):
    """workload_fetch keeps an archive whose SHA-256 matches and refuses one that does not or that would extract
    outside its directory; perf_record turns a fetched workload into its program, Wine and arguments."""
    import hashlib
    import tarfile
    import metal_trace_mcp as mcp
    source = tmp_path / "src" / "demo"
    source.mkdir(parents=True)
    (source / "demo").write_text("#!/bin/sh\n")
    (source / "demo").chmod(0o755)
    good, evil = tmp_path / "good.tar.gz", tmp_path / "evil.tar.gz"
    with tarfile.open(good, "w:gz") as tar:
        tar.add(source, arcname="demo")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(source / "demo", arcname="../escape")
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/x.tar.gz", "bytes": 1 << 20,
             "dir": "demo", "dim_variable": "DIM", "apis": {"mtl": {"program": "demo", "args": "--mtl", "wine": False},
                                                         "d3d12": {"program": "demo", "args": "--d3d12", "wine": True}}}
    saved = mcp.WORKLOADS, mcp.CACHE, mcp.download
    served = {}
    mcp.CACHE, mcp.download = tmp_path / "cache", lambda url, path, max_bytes: shutil.copy(served["file"], path)
    try:
        for archive, sha, words in ((good, "0" * 64, "does not match"),
                                    (evil, hashlib.sha256(evil.read_bytes()).hexdigest(), "may not be extracted")):
            mcp.WORKLOADS, served["file"] = {"demo": {**entry, "sha256": sha}}, archive
            try:
                mcp.tool_workload_fetch("demo")
                raise AssertionError(f"{archive.name} must be refused")
            except mcp.ToolError as error:
                assert words in str(error), error
            assert not any(p.name.startswith("demo-") for p in mcp.CACHE.iterdir()), list(mcp.CACHE.iterdir())
        assert not (tmp_path / "escape").exists()
        mcp.WORKLOADS, served["file"] = {"demo": {**entry, "sha256": hashlib.sha256(good.read_bytes()).hexdigest()}}, good
        assert mcp.tool_workload_list()["workloads"][0]["fetched"] is False
        try:
            mcp.workload_command("demo", "mtl", None, None, "")
            raise AssertionError("an unfetched workload must fail")
        except mcp.ToolError as error:
            assert "workload_fetch" in str(error), error
        assert mcp.tool_workload_fetch("demo")["downloaded"] and not mcp.tool_workload_fetch("demo")["downloaded"]
        program, wine, args, env = mcp.workload_command("demo", "mtl", 20, "/opt/wine", "-x")
        assert program.is_file() and os.access(program, os.X_OK) and wine == "native", program
        assert (args, env) == ("--mtl -x", "DIM=20"), (args, env)
        layer_wine = "native" if sys.platform == "win32" else "/opt/wine"
        assert mcp.workload_command("demo", "d3d12", None, "/opt/wine", "")[1:] == (layer_wine, "--d3d12", "")
        for api in ("vulkan", None):
            try:
                mcp.workload_command("demo", api, None, None, "")
                raise AssertionError(f"api {api} must fail")
            except mcp.ToolError as error:
                assert "api is one of mtl, d3d12" in str(error), error
    finally:
        mcp.WORKLOADS, mcp.CACHE, mcp.download = saved
    shipped = json.loads((TOOLS / "data" / "workloads.json").read_text())["workloads"]["drawstress"]
    assert len(shipped["sha256"]) == 64 and shipped["sha256"] != "0" * 64 and shipped["url"].startswith("https://")
    examples = json.loads((TOOLS / "data" / "workloads.json").read_text())["workloads"]["bgfx-examples"]
    assert "workloads-4" in examples["url"] and len(examples["sha256"]) == 64, "workloads-2's archive has no dxil shaders"


def test_capture(tmp_path):
    """A small MTSP stream is read record by record, and the summary names the capture without its path."""
    summary = gputrace_read.summarize(write_capture(tmp_path))
    assert summary["capture"] == "frame.gputrace" and summary["draw_primitives"] == 3, summary


def test_server(tmp_path):
    """The server answers on stdout with JSON only, pages lists, refuses paths outside its directories and turns
    failures into isError results."""
    out = tmp_path / "runs"
    out.mkdir()
    for i in range(3):
        (out / f"run{i}_x.json").write_text(json.dumps({"gpu": {"frames": 100 * i}}))
    (out / "run3_x.json").write_text('{"gpu": {')
    (out / "run1_x.trace").mkdir()
    write_capture(out)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {"limit": 2}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "trace_tables", "arguments": {"trace": str(out / "gone.trace")}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "trace_tables", "arguments": {"trace": "/etc/hosts"}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "perf_compare", "arguments": {"a": "run0_x", "b": "../x"}}},
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {"bad": 1}}},
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "nope"}},
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
         "params": {"name": "gpu_family", "arguments": {"name": "M1 Pro"}}},
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
         "params": {"name": "gpu_family", "arguments": {"name": "Z80"}}},
        {"jsonrpc": "2.0", "id": 11, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 12, "method": "resources/read", "params": {"uri": "metal-trace://gpu-families/apple9"}},
        {"jsonrpc": "2.0", "id": 13, "method": "resources/read", "params": {"uri": "metal-trace://nope"}},
        {"jsonrpc": "2.0", "id": 14, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
        [1],
        {"jsonrpc": "2.0", "id": 15, "method": "ping"},
        {"jsonrpc": "2.0", "id": 16, "method": "tools/list", "params": [1]},
        {"jsonrpc": "2.0", "id": 17, "method": "resources/templates/list"},
        {"jsonrpc": "2.0", "id": 18, "method": "tools/call",
         "params": {"name": "perf_attach", "arguments": {"label": "a", "process": "no-such-program-4242.exe"}}},
        {"jsonrpc": "2.0", "id": 19, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 20, "method": "tools/call",
         "params": {"name": "trace_tables", "arguments": {"trace": "run0_x"}}},
        {"jsonrpc": "2.0", "id": 21, "method": "tools/call",
         "params": {"name": "capture_summary", "arguments": {"capture": str(out / "frame.gputrace")}}},
        {"jsonrpc": "2.0", "id": 22, "method": "prompts/list"},
        {"jsonrpc": "2.0", "id": 23, "method": "prompts/get",
         "params": {"name": "compare-layer", "arguments": {"workload": "drawstress", "api": "d3d11"}}},
        {"jsonrpc": "2.0", "id": 24, "method": "prompts/get",
         "params": {"name": "compare-layer", "arguments": {"api": "d3d12; rm -rf /"}}},
        {"jsonrpc": "2.0", "id": 25, "method": "prompts/get", "params": {"name": "nope"}},
        {"jsonrpc": "2.0", "id": 26, "method": "resources/read", "params": {"uri": "metal-trace://runs/run1_x"}},
        {"jsonrpc": "2.0", "id": 27, "method": "resources/read", "params": {"uri": "metal-trace://runs/../x"}},
        {"jsonrpc": "2.0", "id": 28, "method": "resources/read", "params": {"uri": "metal-trace://runs/gone"}},
    ]
    proc = subprocess.run([sys.executable, "-I", str(TOOLS / "metal_trace_mcp.py")], text=True, capture_output=True,
                          input="\n".join(json.dumps(r) for r in requests) + "\n", timeout=60,
                          env=dict(os.environ, METAL_TRACE_OUT=str(out), METAL_TRACE_LOG="info"))
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    replies = {r["id"]: r for r in lines if r["id"] is not None}
    assert sorted(replies) == list(range(1, 29)), (replies, proc.stderr)
    tools = {t["name"]: t for t in replies[2]["result"]["tools"]}
    assert all("outputSchema" in t for t in tools.values()), "every tool declares its output"
    paged = replies[3]["result"]["structuredContent"]
    assert set(tools["perf_runs"]["outputSchema"]["required"]) <= set(paged), paged
    assert [p["name"] for p in replies[22]["result"]["prompts"]] == ["compare-layer"]
    steps = replies[23]["result"]["messages"][0]["content"]["text"]
    assert all(w in steps for w in ("api=d3d11", "workload=drawstress", "perf_compare a=", "labels")), steps
    # an argument that is not a plain name is dropped, so the default api stays
    assert "rm -rf" not in replies[24]["result"]["messages"][0]["content"]["text"]
    assert replies[25]["error"]["code"] == -32602
    assert replies[1]["result"]["capabilities"]["prompts"] == {}
    assert [r["error"]["code"] for r in lines if r["id"] is None] == [-32600], lines
    assert replies[14]["result"]["protocolVersion"] == "2025-06-18"
    assert replies[15]["result"] == {} and replies[16]["error"]["code"] == -32600
    assert [x["uriTemplate"] for x in replies[17]["result"]["resourceTemplates"]] == ["metal-trace://runs/{run}"]
    assert json.loads(replies[26]["result"]["contents"][0]["text"]) == {"gpu": {"frames": 100}}
    assert replies[27]["error"]["code"] == replies[28]["error"]["code"] == -32002, "a bad run name is not found"
    assert len(replies[2]["result"]["tools"]) == 23
    assert replies[1]["result"]["capabilities"]["resources"] == {}
    assert "KEEP_TRACE=1" in replies[1]["result"]["instructions"]
    hints = {t["name"]: t["annotations"] for t in replies[2]["result"]["tools"]}
    asks = [t["name"] for t in replies[2]["result"]["tools"] if t.get("_meta", {}).get("anthropic/requiresUserInteraction")]
    assert asks == ["workload_fetch", "presentmon_install"] and hints["workload_fetch"]["openWorldHint"], (asks, hints)
    assert hints["perf_record"]["destructiveHint"] and not hints["perf_attach"]["destructiveHint"], hints
    assert hints["perf_runs"]["readOnlyHint"] and all(h["title"] for h in hints.values()), hints
    m1 = replies[9]["result"]["structuredContent"]
    assert m1["family"] == "Apple7" and m1["limits"]["mesh_grid_threadgroups"] == 1024, m1
    assert replies[10]["result"]["isError"] and "Apple7" in replies[10]["result"]["content"][0]["text"]
    assert len(replies[11]["result"]["resources"]) == 5
    apple9 = json.loads(replies[12]["result"]["contents"][0]["text"])
    assert apple9["family"] == "Apple9" and apple9["sources"]["feature_set_tables"].startswith("https://"), apple9
    assert replies[13]["error"]["code"] == -32002
    runs = replies[3]["result"]["structuredContent"]
    assert runs["total"] == 3 and len(runs["rows"]) == 2 and runs["next_offset"] == 2, runs
    kept = {r["run"]: r["trace_kept"] for r in replies[19]["result"]["structuredContent"]["rows"]}
    assert kept == {"run0_x": False, "run1_x": True, "run2_x": False}, kept
    capture = replies[21]["result"]["structuredContent"]
    assert capture["calls_total"] == 1 and len(capture["calls"]) == 1, capture
    for mid, words in ((4, "KEEP_TRACE"), (5, "outside"), (6, "only letters"), (7, "bad arguments"),
                       (18, "no running process matches"), (20, "KEEP_TRACE")):
        result = replies[mid]["result"]
        assert result.get("isError") and words in result["content"][0]["text"], (mid, result)
        assert str(tmp_path) not in result["content"][0]["text"], (mid, result)
    assert replies[8]["error"]["code"] == -32602
    assert proc.stderr.count("metal-trace:") == 11, proc.stderr


def test_no_runs_directory(tmp_path):
    """A server that only lists recordings does not create the recordings directory."""
    out = tmp_path / "never"
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {}}}
    proc = subprocess.run([sys.executable, "-I", str(TOOLS / "metal_trace_mcp.py")], text=True, capture_output=True,
                          input=json.dumps(request) + "\n", timeout=60,
                          env=dict(os.environ, METAL_TRACE_OUT=str(out), METAL_TRACE_LOG="off"))
    assert json.loads(proc.stdout)["result"]["structuredContent"]["total"] == 0, proc.stdout
    assert not out.exists()


@macos_only
def test_overrun(tmp_path):
    """A recording that overruns its deadline is stopped and leaves no files and no lock behind, and the deadline
    covers a 30 s Wine D3D12 recording (more than 407 s in all on an M1 Pro) and reading back a 60 s one."""
    import metal_trace_mcp as mcp
    assert mcp.deadline(30) > 407 and mcp.deadline(60) > 87 * 6
    stubs, out = tmp_path / "stubs", tmp_path / "overrun"
    stubs.mkdir()
    out.mkdir()
    # an xctrace that starts its .trace and never finishes
    xcrun = stubs / "xcrun"
    xcrun.write_text("#!/bin/zsh\nwhile [[ $1 != --output ]]; do shift; done\nmkdir -p $2\nsleep 60\n")
    xcrun.chmod(0o755)
    program = tmp_path / "hang-4242"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    saved = mcp.OUT, mcp.deadline, os.environ["PATH"]
    mcp.OUT, mcp.deadline = out, lambda seconds: 3
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    try:
        mcp.tool_perf_record("hang", str(program), seconds=1, wine="native")
        raise AssertionError("an overrunning recording must fail")
    except mcp.ToolError as error:
        assert "stopped" in str(error), error
    finally:
        mcp.OUT, mcp.deadline, os.environ["PATH"] = saved
    assert not list(out.iterdir()), list(out.iterdir())


def hang_stubs(tmp_path):
    """Returns (stubs directory, runs directory, program) for a recording whose xctrace starts and never finishes."""
    stubs, out = tmp_path / "stubs", tmp_path / "runs"
    stubs.mkdir()
    out.mkdir()
    xcrun = stubs / "xcrun"
    xcrun.write_text("#!/bin/zsh\nwhile [[ $1 != --output ]]; do shift; done\nmkdir -p $2\nsleep 60\n")
    xcrun.chmod(0o755)
    program = tmp_path / "hang-4242"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    pkill = stubs / "pkill"  # records which program the stop path kills
    pkill.write_text(f"#!/bin/zsh\necho $@ >> {tmp_path}/pkill.log\n")
    pkill.chmod(0o755)
    return stubs, out, program


def test_progress_and_cancel(tmp_path):
    """A recording reports progress to a client that sent a progressToken and stops, leaving no files, when the client
    cancels it; ping is answered while it runs."""
    import threading
    import time
    import metal_trace_mcp as mcp
    stubs, out, program = hang_stubs(tmp_path)
    seen, cancel = [], threading.Event()
    saved = mcp.OUT, mcp.PROGRESS_TICKS, os.environ["PATH"]
    mcp.OUT, mcp.PROGRESS_TICKS = out, 1
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    mcp.RUN.cancel, mcp.RUN.progress = cancel, lambda *a: seen.append(a) or (len(seen) == 2 and cancel.set())
    try:
        mcp.tool_perf_record("hang", str(program), seconds=1, wine="native")
        raise AssertionError("a cancelled recording must fail")
    except mcp.ToolError as error:
        assert "cancelled" in str(error), error
    finally:
        mcp.OUT, mcp.PROGRESS_TICKS, os.environ["PATH"] = saved
        mcp.RUN.cancel = mcp.RUN.progress = None
    assert (tmp_path / "pkill.log").read_text().split() == ["-x", "hang-4242"], "the launched program must be killed"
    assert len(seen) == 2 and seen[1][0] > seen[0][0] and seen[0][1] == mcp.deadline(1), seen
    assert not list(out.iterdir()), list(out.iterdir())
    import io
    real, sys.stdout = sys.stdout, io.StringIO()
    mcp.TOOLS["t"] = (lambda: mcp.progress(1, 2, "half") or {}, None, None)
    try:
        mcp.call("t", {}, 7, "tok")
        line = sys.stdout.getvalue()
    finally:
        sys.stdout = real
        del mcp.TOOLS["t"]
    assert json.loads(line) == {"jsonrpc": "2.0", "method": "notifications/progress", "params": {
        "progressToken": "tok", "progress": 1, "total": 2, "message": "half"}}, line
    # over stdio: the cancel notification ends the call while the server still answers ping
    proc = subprocess.Popen([sys.executable, "-I", str(TOOLS / "metal_trace_mcp.py")], text=True, bufsize=1,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=dict(os.environ, METAL_TRACE_OUT=str(out), PATH=f"{stubs}:{os.environ['PATH']}"))
    def say(message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
    try:
        say({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "perf_record", "_meta": {"progressToken": "t"},
            "arguments": {"label": "hang", "program": str(program), "seconds": 1, "wine": "native"}}})
        time.sleep(2)
        say({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        assert json.loads(proc.stdout.readline())["id"] == 2, "ping must be answered during a recording"
        say({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}})
        reply = json.loads(proc.stdout.readline())
        assert reply["id"] == 1 and reply["result"]["isError"] and "cancelled" in reply["result"]["content"][0]["text"]
    finally:
        proc.kill()
        proc.wait()
    assert not list(out.iterdir()), list(out.iterdir())


def test_markdown_and_export(tmp_path):
    """perf_compare markdown=true adds tables with the headline numbers and the labels that changed most, and
    perf_export_trace writes one Chrome trace slice per GPU frame without making a new run."""
    import metal_trace_mcp as mcp

    def summary(fps, ms):
        return {"gpu": {"frames": 300, "fps_estimate": fps, "frame_gpu_ms": {"mean": ms, "p95": ms * 2},
                        "frame_interval_ms": {"p95": 20.0}},
                "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5},
                             "short_share": {"25": 0.5}, "by_label": [{"label": "Render", "per_frame": 1.0, "total_ms": ms * 300}]},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}}
    (tmp_path / "a.json").write_text(json.dumps(summary(60.0, 4.0)))
    (tmp_path / "b.json").write_text(json.dumps(summary(50.0, 5.0)))
    (tmp_path / "a.frames.csv").write_text("frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total\n"
                                           "1,10.5,0.1,0.2,0.3,0.6\n2,27.0,0.1,0.2,0.3,0.6\n")
    saved, mcp.OUT = mcp.OUT, tmp_path
    try:
        assert "markdown" not in mcp.tool_perf_compare("a", "b")
        md = mcp.tool_perf_compare("a", "b", markdown=True)["markdown"]
        assert "| fps | 60.0 | 50.0 | -10.0 | -16.7 |" in md and "| Render |" in md, md
        got = mcp.tool_perf_export_trace("a")
        assert got == {"file": "a.chrome-trace", "frames": 2}, got
        events = json.loads((tmp_path / got["file"]).read_text())["traceEvents"]
        assert events[0]["ts"] == 10500.0 and events[0]["dur"] == 600.0 and events[0]["args"]["fragment"] == 0.2, events
        assert sorted(r["run"] for r in mcp.tool_perf_runs()["rows"]) == ["a", "b"], "the export is not a run"
        try:
            mcp.tool_perf_export_trace("b")
            raise AssertionError("a run without frames.csv must fail")
        except mcp.ToolError as error:
            assert "per-frame" in str(error)
    finally:
        mcp.OUT = saved


def test_check_cli(tmp_path):
    """`metal-gpu-trace check` exits 0 for same or improved, 1 for regressed, 2 for a run that cannot be judged, and
    prints one JSON line without the full comparison."""
    import metal_trace_mcp as mcp

    def summary(fps, frames=300):
        return {"gpu": {"frames": frames, "fps_estimate": fps, "frame_gpu_ms": {"mean": 4.3, "p95": 8.0},
                        "frame_interval_ms": {"p95": 20.0}},
                "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5},
                             "short_share": {"25": 0.5}, "by_label": []},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}}
    for name, s in {"r1": summary(60.0), "r2": summary(62.0), "ok": summary(61.0), "bad": summary(40.0),
                    "short": summary(61.0, frames=50)}.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(s))
    saved, (mcp.OUT, mcp.BASELINES) = (mcp.OUT, mcp.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        mcp.tool_perf_baseline("ds", ["r1", "r2"])
    finally:
        mcp.OUT, mcp.BASELINES = saved

    def check(*args):
        proc = subprocess.run([sys.executable, "-I", str(TOOLS / "metal_trace_mcp.py"), "check", *args], text=True,
                              capture_output=True, env=dict(os.environ, METAL_TRACE_OUT=str(tmp_path)))
        return proc.returncode, proc.stdout, proc.stderr
    code, out, _ = check("ok", "ds")
    assert code == 0 and json.loads(out)["verdict"] == "same" and "comparison" not in out, (code, out)
    code, out, _ = check("bad", "ds")
    assert code == 1 and json.loads(out)["regressed"][0]["metric"] == "fps", (code, out)
    assert check("bad", "ds", "--margin-pct", "99")[0] == 0, "a wide margin lets it pass"
    assert check("short", "ds")[0] == 2, "a run under 100 frames cannot be judged"
    for bad in (("nope", "ds"), ("ok", "nope"), ("ok",), ("ok", "ds", "--margin-pct", "x")):
        assert check(*bad)[0] == 2, bad


def test_http(tmp_path):
    """`--http` serves POST /mcp on 127.0.0.1 only: it refuses to start without a token, answers 401 without the
    token, 403 for a foreign Host or Origin, 405 for GET and 202 for a notification, serves tools, and a cancel
    request from a second connection stops a running recording."""
    import http.client
    import socket
    import threading
    import time
    stubs, out, program = hang_stubs(tmp_path)
    script = [sys.executable, "-I", str(TOOLS / "metal_trace_mcp.py"), "--http", "--port"]
    env = dict(os.environ, METAL_TRACE_OUT=str(out), METAL_TRACE_LOG="off", PATH=f"{stubs}:{os.environ['PATH']}")
    without = subprocess.run([*script, "0"], capture_output=True, text=True, timeout=30,
                             env={k: v for k, v in env.items() if k != "METAL_TRACE_TOKEN"})
    assert without.returncode == 2 and "METAL_TRACE_TOKEN" in without.stderr, without
    assert subprocess.run([*script, "0"], capture_output=True, text=True, timeout=30,
                          env=dict(env, METAL_TRACE_TOKEN="short")).returncode == 2, "a short token is refused"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    token = "t" * 32
    proc = subprocess.Popen([*script, str(port)], env=dict(env, METAL_TRACE_TOKEN=token), stderr=subprocess.DEVNULL)

    def post(body, headers=None, path="/mcp", method="POST"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        h = {"Content-Type": "application/json", "Authorization": f"Bearer {token}", **(headers or {})}
        conn.request(method, path, json.dumps(body) if body is not None else None, h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, json.loads(data) if data else None
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        assert post(ping) == (200, {"jsonrpc": "2.0", "id": 1, "result": {}})
        assert post(ping, {"Authorization": "Bearer nope"})[0] == 401
        assert post(ping, {"Authorization": ""})[0] == 401
        assert post(ping, {"Origin": "http://evil.example"})[0] == 403
        assert post(ping, {"Origin": "http://localhost.evil.example"})[0] == 403
        assert post(ping, {"Host": "evil.example"})[0] == 403
        assert post(ping, {"Origin": f"http://localhost:{port}"})[0] == 200
        assert post(None, method="GET")[0] == 405
        assert post(ping, path="/other")[0] == 404
        assert post({"jsonrpc": "2.0", "method": "notifications/initialized"}) == (202, None)
        code, tools = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert code == 200 and len(tools["result"]["tools"]) == 23
        code, runs = post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                           "params": {"name": "perf_runs", "arguments": {}, "_meta": {"progressToken": "x"}}})
        assert code == 200 and runs["result"]["structuredContent"]["total"] == 0, runs

        def get(path, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            conn.request("GET", path, headers=headers or {})
            r = conn.getresponse()
            body = r.read().decode()
            conn.close()
            return r.status, r.getheader("Content-Type"), body
        auth = {"Authorization": f"Bearer {token}"}
        status, kind, page_html = get("/panel")
        assert status == 200 and kind.startswith("text/html") and "connect-src 'self'" in page_html, (status, kind)
        assert token not in page_html and get("/panel", {"Host": "evil.example"})[0] == 403
        assert get("/panel/data")[0] == 401 and get("/panel/data", {**auth, "Origin": "http://evil.example"})[0] == 403
        status, _, body = get("/panel/data", auth)
        assert status == 400 and "no recordings" in body, (status, body)
        (out / "a.json").write_text(json.dumps({"gpu": {"frames": 2, "fps_estimate": 60.0}, "hitches": {}}))
        (out / "a.frames.csv").write_text("frame,start_ms,gpu_ms_total\n1,0.0,4.0\n2,16.0,4.0\n")
        status, kind, body = get("/panel/data", auth)
        assert status == 200 and json.loads(body)["runs"][0]["name"] == "a" and json.loads(body)["preset"] == "fps", body
        assert get("/panel/data?runs=a,a&preset=compare", auth)[0] == 200
        assert get("/panel/data?runs=../x", auth)[0] == 400 and get("/panel/data?preset=nope", auth)[0] == 400
        (out / "a.json").unlink()
        (out / "a.frames.csv").unlink()
        result = []
        call = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "perf_record", "arguments": {"label": "hang", "program": str(program), "seconds": 1, "wine": "native"}}}
        thread = threading.Thread(target=lambda: result.append(post(call)))
        thread.start()
        time.sleep(2)
        assert post({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 7}})[0] == 202
        thread.join(30)
        code, reply = result[0]
        assert code == 200 and reply["result"]["isError"] and "cancelled" in reply["result"]["content"][0]["text"], reply
    finally:
        proc.kill()
        proc.wait()
    assert not list(out.iterdir()), list(out.iterdir())


def test_queue(tmp_path):
    """Tool calls wait in a queue of MAX_QUEUE: one past it is refused at once, and cancelling a queued call answers
    it at once instead of after the call ahead of it."""
    import threading
    import time
    import metal_trace_mcp as mcp
    gate, replies, log = threading.Event(), {}, os.environ.get("METAL_TRACE_LOG")
    os.environ["METAL_TRACE_LOG"] = "off"
    mcp.TOOLS["slow"] = (lambda: gate.wait(20) and {}, {"type": "object"}, {})

    def submit(i):
        mcp.CALLS[i] = threading.Event()
        mcp.submit({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "slow", "arguments": {}}},
                   lambda r: replies.__setitem__(i, r))
    try:
        submit(0)
        time.sleep(0.3)  # the worker has taken call 0 and waits on the gate
        for i in range(1, mcp.MAX_QUEUE + 1):
            submit(i)
        submit(999)
        assert "waiting" in replies[999]["result"]["content"][0]["text"] and 999 not in mcp.CALLS, replies.get(999)
        mcp.cancel_call(5)
        assert 5 in replies and "cancelled" in replies[5]["result"]["content"][0]["text"], "a queued cancel answers at once"
        mcp.cancel_call([1])  # an unhashable id is ignored
        mcp.cancel_call(123456)
    finally:
        gate.set()
        mcp.stop_worker()
        mcp.WORKER.clear()
        del mcp.TOOLS["slow"]
        os.environ.pop("METAL_TRACE_LOG") if log is None else os.environ.__setitem__("METAL_TRACE_LOG", log)
    assert sorted(replies) == sorted(set(range(mcp.MAX_QUEUE + 1)) | {999}), sorted(replies)
    assert not mcp.CALLS, mcp.CALLS


def test_http_timeout(tmp_path):
    """A client that stalls in the middle of its request is dropped after HTTP_TIMEOUT instead of holding a thread."""
    import socket
    import threading
    from http.server import ThreadingHTTPServer
    import metal_trace_mcp as mcp
    saved, mcp.HTTP_TIMEOUT = mcp.HTTP_TIMEOUT, 1
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), mcp.http_handler("t" * 32))
    finally:
        mcp.HTTP_TIMEOUT = saved
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        stalled = socket.create_connection(server.server_address, timeout=3)
        stalled.sendall(b"POST /mcp HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\n")
        stalled.settimeout(10)
        assert stalled.recv(10) == b"", "the server must close a stalled connection"
        stalled.close()
    finally:
        server.shutdown()
        server.server_close()


def test_kill_program_and_watchdog(tmp_path):
    """kill_program ends a program that ignores SIGTERM, and perf_record.sh stops its recording, frees its lock and
    its program when the server named in PERF_PARENT_PID dies."""
    import shutil
    import time
    import metal_trace_mcp as mcp
    stubs, out, program = hang_stubs(tmp_path)
    # a program that ignores SIGTERM, under a name only this test uses
    stubborn = tmp_path / "ignoreterm-4242"
    shutil.copy(shutil.which("sleep"), stubborn)
    proc = subprocess.Popen(["sh", "-c", f"trap '' TERM; exec {stubborn} 60"])
    time.sleep(0.5)
    mcp.kill_program("ignoreterm-4242")
    assert proc.wait(timeout=15) is not None, "kill_program must escalate to SIGKILL"
    # the recording's parent dies: the script must exit and free its lock
    parent = subprocess.Popen(["sleep", "60"])
    (stubs / "pkill").unlink()  # the script needs the real pkill
    # PERF_MIN_FREE_GB=0: the disk check needs 26 GB for 30 s, and a CI runner's free space varies
    env = dict(os.environ, PERF_OUT=str(out), PERF_PARENT_PID=str(parent.pid), PERF_MIN_FREE_GB="0",
               PATH=f"{stubs}:{os.environ['PATH']}")
    logfile = tmp_path / "script.log"  # a file, not a pipe: the stub's orphaned sleep would hold a pipe open
    script = subprocess.Popen(["zsh", str(TOOLS / "perf_record.sh"), "orphan", "30", "native", "-", str(tmp_path),
                               str(program)], env=env, stdout=open(logfile, "w"), stderr=subprocess.STDOUT,
                              start_new_session=True)
    try:
        deadline = time.time() + 40
        while not (out / ".recording").is_dir() and time.time() < deadline:
            time.sleep(0.2)
        assert (out / ".recording").is_dir(), (f"the recording never started; the script's exit code is {script.poll()} "
                                               f"and its output {logfile.read_text()[-600:]!r}")
        parent.kill()
        parent.wait()
        script.wait(timeout=30)
    finally:
        if script.poll() is None:
            script.kill()
        subprocess.run(["pkill", "-f", str(stubs / "xcrun")], capture_output=True)
    assert not list(out.iterdir()), f"the lock and the partial files must go: {list(out.iterdir())} {logfile.read_text()[-400:]!r}"


def test_script_failure_cleanup(tmp_path):
    """perf_record.sh frees its lock and deletes its partial files when a recording fails, and refuses a program that
    is not an executable file before it starts Instruments."""
    stubs, out = tmp_path / "stubs", tmp_path / "runs"
    stubs.mkdir()
    out.mkdir()
    xcrun = stubs / "xcrun"  # an xctrace that fails at once
    xcrun.write_text("#!/bin/zsh\nexit 1\n")
    xcrun.chmod(0o755)
    program, text = tmp_path / "prog", tmp_path / "notes.txt"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    text.write_text("x")
    env = dict(os.environ, PERF_OUT=str(out), PERF_MIN_FREE_GB="0", PATH=f"{stubs}:{os.environ['PATH']}")

    def run(path):
        return subprocess.run(["zsh", str(TOOLS / "perf_record.sh"), "f", "2", "native", "-", str(tmp_path), str(path)],
                              capture_output=True, text=True, env=env, timeout=60)
    failed = run(program)
    assert failed.returncode == 1 and "no recording" in failed.stderr, failed
    assert not list(out.iterdir()), f"a failed recording left {list(out.iterdir())}"
    empty = tmp_path / "empty"  # the execute bit, but no program inside
    empty.touch()
    empty.chmod(0o755)
    refused = run(empty)
    assert refused.returncode == 2 and "not a program the system can run" in refused.stderr, refused
    assert not list(out.iterdir())
    for bad in (text, tmp_path, tmp_path / "missing"):
        refused = run(bad)
        assert refused.returncode == 2 and "not an executable file" in refused.stderr, (bad, refused)
        assert str(tmp_path) not in refused.stderr, "the error must not carry a local path"
    assert not list(out.iterdir())


def test_moltenvk(tmp_path):
    """api vk needs METAL_TRACE_MOLTENVK (a directory with libMoltenVK.dylib and no spaces), runs the program with
    DYLD_LIBRARY_PATH set to it, and names MoltenVK as the layer without a local path, so perf_compare tells a
    MoltenVK run from a native Metal run."""
    import metal_trace_mcp as mcp
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/x.tar.gz", "bytes": 1,
             "sha256": "0" * 64, "dir": "demo", "dim_variable": "DIM",
             "apis": {"mtl": {"program": "demo", "args": "--mtl", "wine": False},
                      "vk": {"program": "demo", "args": "--vk", "wine": False, "moltenvk": True}}}
    cache = tmp_path / "cache"
    (cache / ("demo-" + "0" * 12) / "demo").mkdir(parents=True)
    (cache / ("demo-" + "0" * 12) / "demo" / "demo").write_text("#!/bin/sh\n")
    lib, spaced = tmp_path / "mvk", tmp_path / "with space"
    lib.mkdir()
    spaced.mkdir()
    (lib / "libMoltenVK.dylib").write_bytes(b"fake")
    (spaced / "libMoltenVK.dylib").write_bytes(b"fake")
    saved = mcp.WORKLOADS, mcp.CACHE, mcp.record, os.environ.get("METAL_TRACE_MOLTENVK")
    mcp.WORKLOADS, mcp.CACHE = {"demo": entry}, cache
    seen = {}
    mcp.record = lambda *args, **kw: seen.update(args=args, kw=kw) or {}

    def refused(path, words):
        os.environ.pop("METAL_TRACE_MOLTENVK", None) if path is None else os.environ.__setitem__("METAL_TRACE_MOLTENVK", str(path))
        try:
            mcp.workload_command("demo", "vk", None, None, "")
            raise AssertionError(f"{path} must be refused")
        except mcp.ToolError as error:
            assert words in str(error) and str(tmp_path) not in str(error), error
    try:
        refused(None, "set METAL_TRACE_MOLTENVK")
        refused(tmp_path, "holds no libMoltenVK.dylib")
        refused(spaced, "spaces")
        os.environ["METAL_TRACE_MOLTENVK"] = str(lib)
        program, wine, args, env = mcp.workload_command("demo", "vk", 20, None, "-x")
        assert wine == "native" and args == "--vk -x" and env == f"DIM=20 DYLD_LIBRARY_PATH={lib.resolve()}", (wine, args, env)
        layer = mcp.workload_layer("demo", "vk", 20)
        assert layer["moltenvk"] and len(layer["dylib"]["sha256"]) == 64 and layer["program_env"] == "DIM=20", layer
        assert str(tmp_path) not in json.dumps(layer), "the layer must not carry a local path"
        assert mcp.workload_layer("demo", "mtl", 20) is None
        mcp.tool_perf_record("v", workload="demo", api="vk", seconds=5)
        assert seen["kw"]["layer"]["moltenvk"] and "DYLD_LIBRARY_PATH=" in seen["args"][6], seen
        mcp.tool_perf_record("m", workload="demo", api="mtl", seconds=5)
        assert seen["kw"]["layer"] is None
    finally:
        mcp.WORKLOADS, mcp.CACHE, mcp.record = saved[:3]
        os.environ.pop("METAL_TRACE_MOLTENVK", None) if saved[3] is None else os.environ.__setitem__("METAL_TRACE_MOLTENVK", saved[3])
    vk, vk2 = {"layer": layer}, {"layer": {**layer}}
    native = {"layer": {"none": "native Metal, no translation layer", "program_env": "DIM=20"}}
    assert mcp.layer_label(layer).startswith("moltenvk ") and len(mcp.layer_label(layer)) == 21
    assert mcp.layer_change(native, vk, "a", "b")["same"] is False
    assert mcp.layer_change(vk, vk2, "a", "b")["same"] is True
    assert "vk" in json.loads((TOOLS / "data" / "workloads.json").read_text())["workloads"]["drawstress"]["apis"]


def test_panel(tmp_path):
    """perf_panel writes one self-contained page: no path, no raw </script> from a label, every hitch kept when the
    frames are cut, and an error for a run without frames, a bad preset or the wrong number of runs."""
    import metal_trace_mcp as mcp

    evil = "</script><script>x</script>"
    def summary(fps):
        return {"gpu": {"frames": 400, "fps_estimate": fps, "frame_gpu_ms": {"mean": 4.0, "p50": 4.0, "p95": 6.0, "max": 9.0},
                        "frame_interval_ms": {"p95": 20.0}},
                "hitches": {"count": 1, "threshold_ms": 30.0, "causes": {evil: 1},
                            "worst": [{"frame": 202, "interval_ms": 60.0, "cause": evil, "cpu_pct": 120.0}]},
                "process": {"arguments": f"{tmp_path}/game.exe"}, "layer": {"none": "native"},
                "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5}, "short_share": {"25": 0.5},
                             "by_label": [{"label": evil, "per_frame": 1.0, "total_ms": 5.0}]},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}, "metal_memory_mib": {"peak": 90.0}}
    for run, fps in (("a", 60.0), ("b", 50.0)):
        (tmp_path / f"{run}.json").write_text(json.dumps(summary(fps)))
    starts = [i * 16.0 + (44.0 if i >= 201 else 0.0) for i in range(400)]
    frames = "frame,start_ms,gpu_ms_total\n" + "".join(f"{i + 1},{t},4.0\n" for i, t in enumerate(starts))
    (tmp_path / "a.frames.csv").write_text(frames)
    (tmp_path / "b.frames.csv").write_text(frames)
    (tmp_path / "a.metal_memory.csv").write_text("time_ms,metal_allocated_bytes\n0,1048576\n100,2097152\n")
    saved, saved_points = mcp.OUT, mcp.PANEL_POINTS
    mcp.OUT, mcp.PANEL_POINTS = tmp_path, 50
    try:
        got = mcp.tool_perf_panel("p", ["a", "b"], "compare")
        html = (tmp_path / got["file"]).read_text()
        assert got["file"] == "p.panel.html" and got["runs"] == ["a", "b"] and got["bytes"] == len(html.encode()), got
        assert str(tmp_path) not in html and evil not in html, "no path and no raw </script> in the page"
        assert html.count("<script") == 1 and "default-src 'none'" in html
        assert html.count("runName(i, true)") >= 3 and html.count("cTitle:") == 2 and "working set" in html, "short run names in cards and tables; the RSS note"
        assert html.count("wBottleneck:") == 2 and "direction(\"fps\", DATA.compare.fps)" in html, "the FPS-worse-GPU-better warning"
        assert html.count("shader_compile:") == 2 and all(f'{tab}(card)' in html for tab in ("summary", "frames", "memory", "ab", "data", "encoders", "counters")), \
            "both languages explain the causes and every tab exists"
        payload = json.loads(html.split("let DATA = ", 1)[1].split(";\nconst COLORS", 1)[0].replace("\\u003c", "<"))
        run = payload["runs"][0]
        assert run["marks"] == [[3260.0, 4.0, 60.0, evil, 120.0]] and [3260.0, 4.0] in run["frames"], run["marks"]
        assert len(run["frames"]) < 60 and run["memory"] == [[0.0, 1.0], [100.0, 2.0]], len(run["frames"])
        assert payload["compare"]["fps"]["change"] == -10.0 and run["encoders"][0]["label"] == evil
        assert payload["labels"] and payload["labels"][0]["label"] == evil, "the changed labels travel with the panel"
        assert sorted(r["run"] for r in mcp.tool_perf_runs()["rows"]) == ["a", "b"], "the panel is not a run"
        assert mcp.tool_perf_panel("one", ["a"])["runs"] == ["a"]
        (tmp_path / "c.json").write_text(json.dumps(summary(40.0)))
        for args in (("p", ["c"]), ("p", ["a"], "nope"), ("p", ["a"], "compare"), ("p", []), ("../p", ["a"])):
            try:
                mcp.tool_perf_panel(*args)
                raise AssertionError(f"{args} must fail")
            except mcp.ToolError:
                pass
    finally:
        mcp.OUT, mcp.PANEL_POINTS = saved, saved_points


def test_windows_against_metal(tmp_path):
    """A Windows run against a Metal run says which numbers do not compare and skips the encoders, in perf_compare, its
    Markdown and the panel; two runs from one side compare as before."""
    import metal_trace_mcp as mcp

    def summary(platform, fps):
        return {"device": {"platform": platform},
                "gpu": {"frames": 300, "fps_estimate": fps, "frame_gpu_ms": {"mean": 4.0, "p95": 6.0}, "frame_interval_ms": {"p95": 20.0}},
                "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5}, "short_share": {"25": 0.5},
                             "by_label": []},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}}
    for run, platform in (("mac", "macOS"), ("mac2", "macOS"), ("win", "Windows")):
        (tmp_path / f"{run}.json").write_text(json.dumps(summary(platform, 60.0)))
        (tmp_path / f"{run}.frames.csv").write_text("frame,start_ms,gpu_ms_total\n1,0.0,4.0\n2,16.0,4.0\n")
    saved, (mcp.OUT, mcp.BASELINES) = (mcp.OUT, mcp.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        cross = mcp.tool_perf_compare("mac", "win", markdown=True)
        assert cross["measure"]["a"] == "metal" and cross["measure"]["b"] == "windows", cross.get("measure")
        assert cross["measure"]["not_comparable"] == ["gpu_ms_mean", "gpu_ms_p95", "metal_mib_peak"]
        assert "not_comparable" in cross["encoders"] and "labels" not in cross
        assert "Not comparable between a Windows and a Metal run" in cross["markdown"]
        assert "measure" not in mcp.tool_perf_compare("mac", "mac2")
        for run, locked in (("mac", True), ("mac2", False)):
            locked_summary = summary("macOS", 60.0)
            locked_summary["machine"] = {"screen_locked": locked}
            (tmp_path / f"{run}.json").write_text(json.dumps(locked_summary))
        screen = mcp.tool_perf_compare("mac", "mac2")["screen"]
        assert screen["a"] is True and screen["b"] is False and "GPU ms" in screen["note"] and "unlocked" in screen["note"], screen
        for run, share in (("mac", {"Minimum": 0.65, "Medium": 0.35, "Maximum": 0.0}), ("mac2", {"Minimum": 1.0})):
            state_summary = summary("macOS", 60.0)
            state_summary["gpu_performance_state_share"] = share
            (tmp_path / f"{run}.json").write_text(json.dumps(state_summary))
        state = mcp.tool_perf_compare("mac", "mac2")["gpu_state"]
        assert state["a"] == 0.35 and state["b"] == 0.0 and "GPU ms" in state["note"] and "performance state" in state["note"], state
        for share_b in ({"Minimum": 0.8, "Medium": 0.2}, None):
            near = summary("macOS", 60.0)
            if share_b:
                near["gpu_performance_state_share"] = share_b
            (tmp_path / "mac2.json").write_text(json.dumps(near))
            assert "gpu_state" not in mcp.tool_perf_compare("mac", "mac2"), share_b
        locked_summary["machine"] = {"screen_locked": True}
        (tmp_path / "mac2.json").write_text(json.dumps(locked_summary))
        assert "screen" not in mcp.tool_perf_compare("mac", "mac2")
        (tmp_path / "mac.json").write_text(json.dumps(summary("macOS", 60.0)))
        (tmp_path / "mac2.json").write_text(json.dumps(summary("macOS", 60.0)))
        assert "screen" not in mcp.tool_perf_compare("mac", "mac2")
        data = mcp.panel_data(["mac", "win"])
        assert data["not_comparable"] == ["gpu_ms_mean", "gpu_ms_p95", "metal_mib_peak"]
        assert [r["source"] for r in data["runs"]] == ["metal", "windows"]
        assert data["runs"][1]["encoders"] == [] and data["labels"] == [], "Windows has no encoders to show"
        assert mcp.panel_data(["mac", "mac2"])["not_comparable"] == []
        slow = summary("Windows", 60.0)
        slow["gpu"]["frame_gpu_ms"]["mean"] = 9.0
        (tmp_path / "win-slow.json").write_text(json.dumps(slow))
        mcp.tool_perf_baseline("ref", ["mac", "mac2"])
        check = mcp.tool_perf_check("win-slow", "ref")
        assert check["verdict"] == "same" and "gpu_ms_mean" in check["unchecked"] and "hint_measure" in check, check
        assert mcp.tool_perf_check("mac2", "ref")["verdict"] == "same" and "hint_measure" not in mcp.tool_perf_check("mac2", "ref")
    finally:
        mcp.OUT, mcp.BASELINES = saved


def test_gate_and_spread(tmp_path):
    """perf_gate passes only when every budget holds and fails on a missing number; perf_baseline reports the spread of
    its runs as a % of the midpoint."""
    import metal_trace_mcp as mcp

    def summary(fps):
        return {"gpu": {"frames": 300, "fps_estimate": fps, "fps_1pct_low": 40.0, "stutter_rate_pct": 0.5,
                        "frame_gpu_ms": {"mean": 4.0, "p95": 6.0}}, "hitches": {"count": 2}, "metal_memory_mib": {"peak": 120.0},
                "encoders": {"per_frame": {"p50": 3}, "command_buffers_per_frame": {"p50": 2}}}
    for run, fps in (("g1", 60.0), ("g2", 66.0)):
        (tmp_path / f"{run}.json").write_text(json.dumps(summary(fps)))
    saved, (mcp.OUT, mcp.BASELINES) = (mcp.OUT, mcp.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        ok = mcp.tool_perf_gate("g1", fps_min=55, hitches_max=2, metal_mib_max=150)
        assert ok["pass"] and [c["ok"] for c in ok["checks"]] == [True, True, True], ok
        bad = mcp.tool_perf_gate("g1", fps_min=61, gpu_ms_p95_max=6.0)
        assert not bad["pass"] and [c["ok"] for c in bad["checks"]] == [False, True], bad
        (tmp_path / "g3.json").write_text(json.dumps({"gpu": {"frames": 300}}))
        missing = mcp.tool_perf_gate("g3", fps_1pct_low_min=30)
        assert not missing["pass"] and missing["checks"][0]["value"] is None, missing
        for kwargs in ({}, {"run": "nope", "fps_min": 1}):
            try:
                mcp.tool_perf_gate(**({"run": "g1"} | kwargs))
                raise AssertionError(f"{kwargs} must fail")
            except mcp.ToolError:
                pass
        got = mcp.tool_perf_baseline("ref", ["g1", "g2"])
        assert got["spread_pct"]["fps"] == 9.5 and got["range"]["fps"] == {"min": 60.0, "max": 66.0}, got
    finally:
        mcp.OUT, mcp.BASELINES = saved


def test_history(tmp_path):
    """perf_history lists the runs of a prefix oldest first with the change from first to last, flags a series that
    mixes Windows and Metal or has under 3 runs, and refuses an unknown prefix."""
    import metal_trace_mcp as mcp

    def summary(platform, fps, hitches):
        return {"device": {"platform": platform}, "gpu": {"frames": 300, "fps_estimate": fps, "frame_gpu_ms": {"mean": 4.0}},
                "hitches": {"count": hitches}}
    for i, (platform, fps, hitches) in enumerate((("macOS", 60.0, 1), ("macOS", 57.0, 3), ("macOS", 54.0, 4))):
        path = tmp_path / f"v{i}.json"
        path.write_text(json.dumps(summary(platform, fps, hitches)))
        os.utime(path, (1000 + i, 1000 + i))
    saved, (mcp.OUT, mcp.BASELINES) = (mcp.OUT, mcp.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        got = mcp.tool_perf_history("v")
        assert [r["run"] for r in got["runs"]] == ["v0", "v1", "v2"] and got["change"]["fps"]["change"] == -6.0, got
        assert got["change"]["hitches"]["change"] == 3 and "hint" not in got, got
        assert mcp.tool_perf_history("v", limit=2)["runs"][0]["run"] == "v1"
        assert "under 3 runs" in mcp.tool_perf_history("v0")["hint"]
        (tmp_path / "w0.json").write_text(json.dumps(summary("Windows", 50.0, 0)))
        (tmp_path / "v9.json").write_text(json.dumps(summary("Windows", 50.0, 0)))
        assert "mixes Windows and Metal" in mcp.tool_perf_history("v")["hint"]
        for prefix in ("zzz", "../v"):
            try:
                mcp.tool_perf_history(prefix)
                raise AssertionError(f"{prefix} must fail")
            except mcp.ToolError:
                pass
    finally:
        mcp.OUT, mcp.BASELINES = saved


def test_skip_start_up(tmp_path):
    """skip_s recomputes FPS, lows, hitches and Metal memory from the per-frame files without the first seconds, keeps
    the whole-run numbers it cannot recompute, reaches perf_compare, perf_gate and the panel, and refuses a bad value."""
    import metal_trace_mcp as mcp

    starts, t = [], 0.0
    for i in range(400):  # 10 ms frames; three 40 ms hitches in the first second and one at frame 300
        t += 40.0 if i in (20, 50, 80, 300) else 10.0
        starts.append(round(t, 3))
    frames = "frame,start_ms,gpu_ms_total\n" + "".join(f"{i + 1},{s},4.0\n" for i, s in enumerate(starts))
    worst = [{"frame": f, "interval_ms": 40.0, "cause": "shader_compile", "cpu_pct": 100.0} for f in (21, 51, 81, 301)]
    summary = {"gpu": {"frames": 400, "fps_estimate": 90.0, "frame_gpu_ms": {"mean": 4.0, "p50": 4.0, "p95": 4.0, "max": 4.0},
                       "frame_interval_ms": {"p95": 10.0}, "per_channel_ms": {"x": 1}},
               "hitches": {"count": 4, "threshold_ms": 15.0, "causes": {"shader_compile": 4}, "worst": worst},
               "cpu": {"mean": 300.0}, "metal_memory_mib": {"peak": 90.0}, "thermal_state_share": {"Nominal": 1.0},
               "encoders": {"per_frame": {"p50": 2}, "command_buffers_per_frame": {"p50": 1}, "short_share": {"25": 0.1}, "by_label": []},
               "gpu_idle": {"idle_share": 0.1, "idle_ms_per_frame": {"p50": 1}}}
    memory = "time_ms,metal_allocated_bytes\n" + "".join(f"{s},{(90 if s < 1500 else 60) * 2**20}\n" for s in starts[::10])
    for run in ("s1", "s2"):
        (tmp_path / f"{run}.json").write_text(json.dumps(summary))
        (tmp_path / f"{run}.frames.csv").write_text(frames)
        (tmp_path / f"{run}.metal_memory.csv").write_text(memory)
    saved, (mcp.OUT, mcp.BASELINES) = (mcp.OUT, mcp.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        assert mcp.steady_summary("s1") == summary, "no skip, the summary as saved"
        s = mcp.steady_summary("s1", 1.5)  # the first frame is at 10 ms: frames from 1510 ms on
        assert s["gpu"]["frames"] < 400 and s["hitches"]["count"] == 1, s["hitches"]
        assert [h["frame"] for h in s["hitches"]["worst"]] == [301] and s["hitches"]["causes"] == {"shader_compile": 1}
        assert "cpu" not in s and s["metal_memory_mib"]["peak"] == 60.0 and "per_channel_ms" not in s["gpu"]
        assert s["gpu"]["fps_estimate"] == 100.0 and s["steady"]["skip_s"] == 1.5 and "thermal_state_share" in s["steady"]["whole_run"]
        win = dict(summary, device={"platform": "Windows"})
        win.pop("metal_memory_mib"), win.pop("cpu")
        (tmp_path / "w1.json").write_text(json.dumps(win))
        (tmp_path / "w1.frames.csv").write_text(frames)  # a Windows run has no Metal memory: skip_s must still compare
        mixed = mcp.tool_perf_compare("s1", "w1", skip_s=1.5)
        assert mixed["measure"]["b"] == "windows" and mixed["metrics"]["metal_mib_peak"]["b"] is None, mixed["metrics"]["metal_mib_peak"]
        assert mcp.panel_data(["s1", "w1"], skip_s=1.5)["not_comparable"], "the panel too"
        both = mcp.tool_perf_compare("s1", "s2", skip_s=1.5)
        assert both["skipped_s"] == 1.5 and both["metrics"]["fps"]["a"] == 100.0, both["metrics"]["fps"]
        assert "skipped_s" not in mcp.tool_perf_compare("s1", "s2")
        gate = mcp.tool_perf_gate("s1", hitches_max=1, metal_mib_max=70, skip_s=1.5)
        assert gate["pass"] and gate["skipped_s"] == 1.5, gate
        assert not mcp.tool_perf_gate("s1", hitches_max=1, metal_mib_max=70)["pass"], "the whole run has 4 hitches and 90 MiB"
        data = mcp.panel_data(["s1", "s2"], skip_s=1.5)
        run = data["runs"][0]
        assert data["skip_s"] == 1.5 and len(run["marks"]) == 1 and run["frames"][0][0] >= 1510 and run["memory"][0][0] >= 1510, run["marks"]
        assert mcp.panel_data(["s1", "s2"])["skip_s"] == 0
        ref = mcp.tool_perf_baseline("bs", ["s1", "s2"], skip_s=1.5)
        assert ref["skip_s"] == 1.5 and ref["range"]["fps"] == {"min": 100.0, "max": 100.0}, ref
        check = mcp.tool_perf_check("s1", "bs")  # the whole run reads 90 FPS: judged without its start-up it is 100, the reference
        assert check["verdict"] == "same" and check["skipped_s"] == 1.5, check
        whole = mcp.tool_perf_baseline("bw", ["s1", "s2"])
        assert "skip_s" not in whole and whole["range"]["fps"]["min"] == 90.0 and "skipped_s" not in mcp.tool_perf_check("s1", "bw")
        seen = []
        saved_baseline, saved_record = mcp.tool_perf_baseline, mcp.tool_perf_record
        mcp.tool_perf_baseline = lambda name, runs, skip_s=0: seen.append((name, skip_s)) or {}
        mcp.tool_perf_record = lambda label, **kw: (tmp_path / f"{label}_x.json").write_text("{}")
        try:
            mcp.tool_perf_baseline_record("rec", count=1, skip_s=2)
        finally:
            mcp.tool_perf_baseline, mcp.tool_perf_record = saved_baseline, saved_record
        assert seen == [("rec", 2)], seen
        hist = mcp.tool_perf_history("s", skip_s=1.5)
        assert [r["hitches"] for r in hist["runs"]] == [1, 1] and mcp.tool_perf_history("s")["runs"][0]["hitches"] == 4, hist
        ab = mcp.ab_report("x", "", "A=1", {"a": ["s1"], "b": ["s2"]}, skip_s=1.5)
        assert ab["skipped_s"] == 1.5 and ab["metrics"]["fps_estimate"]["a"] == [100.0], ab
        assert "skipped_s" not in mcp.ab_report("x", "", "A=1", {"a": ["s1"], "b": ["s2"]})
        try:
            mcp.tool_perf_ab("x", "", "A=1", skip_s=-1)
            raise AssertionError("a bad skip_s must fail before recording")
        except mcp.ToolError:
            pass
        for bad in (-1, 601, "x"):
            try:
                mcp.steady_summary("s1", bad)
                raise AssertionError(f"{bad} must fail")
            except mcp.ToolError:
                pass
        try:
            mcp.steady_summary("s1", 500)
            raise AssertionError("a skip past the last frame must fail")
        except mcp.ToolError as error:
            assert "under 2 frames" in str(error)
    finally:
        mcp.OUT, mcp.BASELINES = saved


def test_gpu_counters(tmp_path):
    """counter_stats reads the line-per-row GPU counter table whose cells are refs to earlier ids (the first row shares a
    line with the schema, and a counter id may be a ref to an id first written as a sample index), summarizes each counter
    and names the top limiter; summarize asks for the counter tables only when told; perf_record passes counters on."""
    import metal_trace_mcp as mcp

    info = tmp_path / "info.xml"
    info.write_text("<trace-query-result><node xpath='x'><schema name=\"gpu-counter-info\"><col><mnemonic>counter-id</mnemonic></col>"
                    "<col><mnemonic>name</mnemonic></col><col><mnemonic>type</mnemonic></col></schema>"
                    "<row><uint32 id=\"1\" fmt=\"0\">0</uint32><string id=\"2\" fmt=\"ALU Limiter\">ALU Limiter</string><string id=\"3\" fmt=\"Percentage\">Percentage</string></row>\n"
                    "<row><uint32 id=\"4\" fmt=\"1\">1</uint32><string id=\"5\" fmt=\"Cache Limiter\">Cache Limiter</string><string ref=\"3\"/></row>\n"
                    "<row><uint32 id=\"6\" fmt=\"2\">2</uint32><string id=\"7\" fmt=\"GPU Read Bandwidth\">GPU Read Bandwidth</string><string id=\"8\" fmt=\"Value\">Value</string></row>\n"
                    "</node></trace-query-result>\n")
    values = tmp_path / "values.xml"
    # sample 0 of ring buffer 1: counters 0 (10.0), 1 (30.0) and 2 (2.5); counter 1 is a ref to id 5, first written as the ring buffer index
    values.write_text("<?xml version=\"1.0\"?>\n<trace-query-result>\n<node xpath='x'><schema name=\"gpu-counter-value\"></schema>"
                      "<row><event-time id=\"1\" fmt=\"00:00.910.037\">910037000</event-time><uint32 id=\"2\" fmt=\"0\">0</uint32>"
                      "<fixed-decimal id=\"3\" fmt=\"10,0\">10.0</fixed-decimal><uint64 id=\"4\" fmt=\"7\">7</uint64><uint32 ref=\"2\"/>"
                      "<uint32 id=\"5\" fmt=\"1\">1</uint32></row>\n"
                      "<row><event-time ref=\"1\"/><uint32 ref=\"5\"/><fixed-decimal id=\"6\" fmt=\"30,0\">30.0</fixed-decimal><uint64 ref=\"4\"/>"
                      "<uint32 ref=\"2\"/><uint32 ref=\"5\"/></row>\n"
                      "<row><event-time ref=\"1\"/><uint32 id=\"7\" fmt=\"2\">2</uint32><fixed-decimal id=\"8\" fmt=\"2,5\">2.5</fixed-decimal>"
                      "<uint64 ref=\"4\"/><uint32 ref=\"2\"/><uint32 ref=\"5\"/></row>\n"
                      "<row><event-time id=\"9\" fmt=\"x\">910038000</event-time><uint32 ref=\"2\"/><fixed-decimal ref=\"6\"/><uint64 ref=\"4\"/>"
                      "<uint32 id=\"10\" fmt=\"1\">1</uint32><uint32 ref=\"5\"/></row>\n"
                      "</node></trace-query-result>\n")
    got = perf_report.counter_stats(info, values)
    by = {c["name"]: c for c in got["counters"]}
    assert got["samples"] == 4 and not info.exists() and not values.exists(), "both files are read and deleted"
    assert by["ALU Limiter"]["mean"] == 20.0 and by["ALU Limiter"]["max"] == 30.0, by  # 10.0 and a ref to 30.0
    assert by["Cache Limiter"]["mean"] == 30.0 and by["GPU Read Bandwidth"]["unit"] == "GB/s" and by["ALU Limiter"]["unit"] == "%", by
    assert got["top_limiter"] == {"name": "Cache Limiter", "mean": 30.0}, got["top_limiter"]

    asked = []

    def fake(trace, schemas, optional=()):
        asked.append(schemas)
        raise RuntimeError("stop")
    saved, env = perf_report.toc_and_tables, os.environ.get("PERF_INSTRUMENTS")
    perf_report.toc_and_tables = fake
    try:
        for counters, instruments in ((None, ""), (True, ""), (None, "Time Profiler;Metal GPU Counters")):
            os.environ["PERF_INSTRUMENTS"] = instruments
            try:
                perf_report.summarize(tmp_path / "x.trace", "x", tmp_path, counters=counters)
            except RuntimeError:
                pass
    finally:
        perf_report.toc_and_tables = saved
        os.environ.pop("PERF_INSTRUMENTS", None) if env is None else os.environ.__setitem__("PERF_INSTRUMENTS", env)
    wants = ["gpu-counter-value" in s for s in asked]
    assert wants == [False, True, True], wants

    seen = []
    saved_record = mcp.record
    mcp.record = lambda *args, **kw: seen.append(kw.get("counters")) or {}
    program = tmp_path / "prog"
    program.write_text("")
    try:
        mcp.tool_perf_record("m", str(program), wine="native")
        mcp.tool_perf_record("m", str(program), wine="native", counters=True)
    finally:
        mcp.record = saved_record
    assert seen == [False, True] and mcp.RECORD_PROPS["counters"]["type"] == "boolean", seen
    assert mcp.deadline(10, True) > mcp.deadline(10) and mcp.deadline(10) == 330


def test_layout(tmp_path):
    """perf_panel(layout=...) saves panel.json (the listed tabs on, in order, the rest off), every panel carries it, and a
    panel.json that is not a list of tabs, or a layout with an unknown tab, is refused."""
    import metal_trace_mcp as mcp

    (tmp_path / "a.json").write_text(json.dumps({"gpu": {"frames": 2, "fps_estimate": 60.0}, "hitches": {}}))
    (tmp_path / "a.frames.csv").write_text("frame,start_ms,gpu_ms_total\n1,0.0,4.0\n2,16.0,4.0\n")
    saved = mcp.OUT
    mcp.OUT = tmp_path
    try:
        assert mcp.panel_data(["a"])["layout"] is None, "no panel.json, the preset's tabs"
        mcp.tool_perf_panel("p", ["a"], layout=["frames", "summary"])
        saved_layout = json.loads((tmp_path / "panel.json").read_text())
        assert [w["id"] for w in saved_layout[:2]] == ["frames", "summary"] and all(w["on"] for w in saved_layout[:2]), saved_layout
        assert {w["id"] for w in saved_layout} == set(mcp.TAB_IDS) and not any(w["on"] for w in saved_layout[2:]), saved_layout
        html = (tmp_path / "p.panel.html").read_text()
        payload = json.loads(html.split("let DATA = ", 1)[1].split(";\nconst COLORS", 1)[0])
        assert payload["layout"] == saved_layout and mcp.panel_data(["a"])["layout"] == saved_layout
        assert "defaultLayout()" in html
        mcp.tool_perf_panel("q", ["a"])  # a panel without layout keeps the saved one
        assert json.loads((tmp_path / "panel.json").read_text()) == saved_layout
        for bad in ("summary", ["nope"]):
            try:
                mcp.tool_perf_panel("r", ["a"], layout=bad)
                raise AssertionError(f"{bad!r} must fail")
            except mcp.ToolError:
                pass
        for text in ("not json", '{"id": "frames"}', '[{"id": "x", "on": true}]', '[{"id": "frames", "on": 1}]'):
            (tmp_path / "panel.json").write_text(text)
            try:
                mcp.panel_data(["a"])
                raise AssertionError(f"{text} must fail")
            except mcp.ToolError as error:
                assert "panel.json" in str(error)
    finally:
        mcp.OUT = saved


def test_pack_examples(tmp_path):
    """pack-examples.sh puts both binaries and only the named assets in one flat folder, and fails when one is missing."""
    bgfx, out = tmp_path / "bgfx", tmp_path / "out"
    runtime = bgfx / "examples" / "runtime"
    for folder in ("shaders/metal", "shaders/dxbc", "shaders/dxil", "shaders/glsl", "textures", "meshes"):
        (runtime / folder).mkdir(parents=True)
    for asset in ("shaders/metal/vs.bin", "shaders/dxbc/vs.bin", "shaders/dxil/vs.bin", "shaders/glsl/vs.bin", "textures/uffizi.ktx",
                  "textures/other.dds", "meshes/bunny.bin", "meshes/other.bin"):
        (runtime / asset).write_text("x")
    for path in ("osx-arm64/bin/examples.app/Contents/MacOS/examplesRelease",
                 "win64_mingw-gcc/bin/examples.app/Contents/MacOS/examplesRelease.exe"):
        (bgfx / ".build" / path).parent.mkdir(parents=True)
        (bgfx / ".build" / path).write_text("bin")
    script = str(TOOLS / "workloads" / "pack-examples.sh")
    result = subprocess.run(["sh", script, str(bgfx), str(out)], capture_output=True, text=True)
    assert result.returncode, "a missing asset (fieldstone, meshes) must fail the script"
    for asset in ("textures/fieldstone-n.dds", "textures/fieldstone-rgba.dds", "meshes/column.bin", "meshes/cube.bin",
                  "meshes/hollowcube.bin", "meshes/orb.bin", "meshes/tree.bin", "meshes/unit_sphere.bin"):
        (runtime / asset).write_text("x")
    shutil.rmtree(out)
    result = subprocess.run(["sh", script, str(bgfx), str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    packed = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    assert "examples" in packed and "examples.exe" in packed and "shaders/metal/vs.bin" in packed, packed
    assert "shaders/dxbc/vs.bin" in packed and "shaders/dxil/vs.bin" in packed, "Direct3D 11 reads dxbc and 12 reads dxil"
    assert "shaders/glsl/vs.bin" not in packed and "textures/other.dds" not in packed and "meshes/other.bin" not in packed, packed


def test_workload_example(tmp_path):
    """A workload with `examples` needs one named, and its argument follows the api's arguments."""
    import metal_trace_mcp as mcp
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/x.tar.gz", "bytes": 1,
             "sha256": "0" * 64, "dir": "demo", "dim_variable": "DIM",
             "examples": {"21-deferred": "21-", "01-cubes": "01-"},
             "apis": {"mtl": {"program": "demo", "args": "--mtl", "wine": False}}}
    plain = {k: v for k, v in entry.items() if k != "examples"}
    saved = mcp.WORKLOADS, mcp.CACHE
    mcp.CACHE = tmp_path
    try:
        mcp.WORKLOADS = {"demo": entry, "plain": plain}
        for name in ("demo", "plain"):
            (tmp_path / f"{name}-{'0' * 12}").mkdir()
        assert mcp.workload_command("demo", "mtl", None, None, "-x", example="21-deferred")[2] == "--mtl 21- -x"
        for name, example, words in (("demo", None, "example is one of 21-deferred, 01-cubes"),
                                     ("demo", "nope", "example is one of 21-deferred, 01-cubes"),
                                     ("plain", "21-deferred", "takes no example")):
            try:
                mcp.workload_command(name, "mtl", None, None, "", example=example)
                raise AssertionError(f"{name} with example {example} must fail")
            except mcp.ToolError as error:
                assert words in str(error), error
        assert mcp.workload_command("plain", "mtl", None, None, "")[2] == "--mtl"
        no_dim = {k: v for k, v in entry.items() if k != "dim_variable"}
        mcp.WORKLOADS = {"demo": no_dim}
        try:
            mcp.workload_command("demo", "mtl", 20, None, "", example="01-cubes")
            raise AssertionError("dim on a workload without dim_variable must fail")
        except mcp.ToolError as error:
            assert "dim does not apply to demo" in str(error), error
        assert mcp.workload_command("demo", "mtl", None, None, "", example="01-cubes")[3] == ""
        mcp.WORKLOADS = {"demo": entry, "plain": plain}
        assert mcp.tool_workload_list()["workloads"][0]["examples"] == ["21-deferred", "01-cubes"]
    finally:
        mcp.WORKLOADS, mcp.CACHE = saved
    assert mcp.RECORD_PROPS["example"]["type"] == "string"


def test_machine(tmp_path):
    """machine_info() names the chip, cores, RAM and macOS without host name or UUID, and gives None when the machine
    is not the one that recorded the trace or its facts cannot be read."""
    facts = {
        ("sysctl", "-n", "machdep.cpu.brand_string"): "Apple M1 Pro\n",
        ("sysctl", "-n", "hw.perflevel0.logicalcpu"): "8\n",
        ("sysctl", "-n", "hw.perflevel1.logicalcpu"): "2\n",
        ("sysctl", "-n", "hw.memsize"): "17179869184\n",
        ("sw_vers", "-productVersion"): "27.0.1\n",
        ("ioreg", "-c", "AGXAccelerator", "-r", "-d", "1"): '"gpu-core-count" = 16\n"IOClass" = "AGXAcceleratorG13X"\n',
        ("ioreg", "-n", "Root", "-d1", "-a"): "<key>CGSSessionScreenIsLocked</key><true/>",
    }
    device = {"memory-size": "17179869184", "os-version": "27.0.1 (26A434)"}
    got = perf_report.machine_info(device, facts.__getitem__)
    assert got == {"chip": "Apple M1 Pro", "cpu_cores_p": 8, "cpu_cores_e": 2, "gpu_cores": 16,
                   "gpu_class": "AGXAcceleratorG13X", "ram_gib": 16, "macos": "27.0.1", "screen_locked": True}, got
    facts[("ioreg", "-n", "Root", "-d1", "-a")] = "<key>IOConsoleUsers</key>"
    assert perf_report.machine_info(device, facts.__getitem__)["screen_locked"] is False
    del facts[("ioreg", "-n", "Root", "-d1", "-a")]
    assert perf_report.machine_info(device, facts.__getitem__)["screen_locked"] is None
    assert perf_report.machine_info(dict(device, **{"memory-size": "8589934592"}), facts.__getitem__) is None
    assert perf_report.machine_info(dict(device, **{"os-version": "26.4 (25E1)"}), facts.__getitem__) is None
    assert perf_report.machine_info({}, facts.__getitem__) is None
    assert perf_report.machine_info(device, {}.__getitem__) is None


def main():
    tests = [test_readme_lists_every_tool, test_resource_summary, test_rosetta_layer, test_gpu_activity, test_size, test_levers, test_perf_sweep, test_pack_examples, test_workload_example, test_machine, test_layout, test_gpu_counters, test_skip_start_up, test_history, test_gate_and_spread, test_windows_against_metal, test_panel,test_disk_guard, test_memory_param, test_no_memory, test_toc_and_tables,test_report,test_encoders, test_diagnose, test_compare, test_baseline, test_trace_count, test_baseline_record, test_layer, test_workloads, test_capture, test_server, test_no_runs_directory, test_overrun, test_progress_and_cancel, test_check_cli, test_markdown_and_export, test_http, test_queue, test_http_timeout, test_kill_program_and_watchdog, test_script_failure_cleanup, test_moltenvk]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(pathlib.Path(tmp).resolve())
    print("ok")


if __name__ == "__main__":
    main()
