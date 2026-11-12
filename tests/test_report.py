"""Tests of perf_report: exports, encoders, pacing, counters, memory, validation and the machine block."""
import json
import os
import pathlib
import subprocess
import xml.etree.ElementTree as ET

from support import PKG, golden  # also puts src/ on sys.path
from metal_gpu_trace import perf_report  # noqa: E402


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
    # jitter is the population standard deviation of the intervals (statistics.pstdev), not the sample one (2.0)
    assert got["stutter_rate_pct"] == 1.0 and got["frame_jitter_ms"] == 1.99, got
    assert got["throttling_analysis"]["thermal_throttling_detected"] is False, got
    assert perf_report.frame_pacing([], []) == {}
    uncapped = [1.8] * 90 + [3.0] * 9 + [24.0]
    quiet = perf_report.frame_pacing(uncapped, [1.0] * 100)
    assert quiet["stutter_rate_pct"] == 1.0, quiet
    starts = [sum(uncapped[:i]) for i in range(101)]
    noise = perf_report.attribute_hitches(list(range(101)), starts, [1.0] * 101, [], [], [])
    assert noise["count"] == 1 and noise["threshold_ms"] == 8.0 and noise["worst"][0]["interval_ms"] == 24.0, noise
    # five long intervals, one cause each: 20-50 compiler, 60-100 thermal, 110-150 nothing (cpu_or_wait),
    # 160-200 GPU busy for 39 of 40 ms (gpu_heavy), 200-250 Metal memory +20 MiB (memory_growth)
    starts = [0, 10, 20, 50, 60, 100, 110, 150, 160, 200, 250, 260]
    frames = list(range(len(starts)))
    totals = [5] * len(starts)
    totals[8] = 39
    memory = [(0, 0), (200, 0), (250, 20 * 2**20)]
    got = perf_report.attribute_hitches(frames, starts, totals, [(25, 30)], [(70, 80)], memory)
    assert got["count"] == 5 and got["threshold_ms"] == 15.0, got
    assert [h["cause"] for h in sorted(got["worst"], key=lambda h: h["frame"])] == [
        "shader_compile", "thermal", "cpu_or_wait", "gpu_heavy", "memory_growth"], got
    assert perf_report.attribute_hitches([1], [0], [1], [], [], []) == {"count": 0, "per_minute": None, "causes": {},
                                                                        "worst": []}
    assert "cpu_pct" not in got["worst"][0], "no CPU samples, no cpu_pct"
    cpu = [(t, 300.0) for t in range(0, 160, 10)] + [(t, 100.0) for t in range(160, 211, 10)]
    busy = perf_report.attribute_hitches(frames, starts, totals, [(25, 30)], [(70, 80)], memory, cpu=cpu)
    by_frame = {h["frame"]: h["cpu_pct"] for h in busy["worst"]}
    assert by_frame[3] == 300.0 and by_frame[10] == 100.0, by_frame  # the interval before a hitch is where the mean is taken
    assert perf_report.attribute_hitches(frames, starts, totals, [], [], [], cpu=[(500, 1.0)])["worst"][0]["cpu_pct"] is None

def test_trace_count(tmp_path):
    """trace_count counts a table's rows in all and per process, names tables the trace lacks, and refuses odd names."""
    from metal_gpu_trace import metal_trace_mcp as mcp
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

def test_counter_windows(tmp_path):
    """counter_stats keeps each Limiter's mean per 10 ms bin, and limiter_in names the Limiter with the highest mean over a
    window; a hitch window with no samples gets None, and attribute_hitches records each hitch's window."""
    info = tmp_path / "info.xml"
    info.write_text("<trace-query-result><node xpath='x'><schema name=\"gpu-counter-info\"><col><mnemonic>counter-id</mnemonic></col>"
                    "<col><mnemonic>name</mnemonic></col><col><mnemonic>type</mnemonic></col></schema>"
                    "<row><uint32 id=\"1\" fmt=\"0\">0</uint32><string id=\"2\" fmt=\"ALU Limiter\">ALU Limiter</string><string id=\"3\" fmt=\"Percentage\">Percentage</string></row>\n"
                    "<row><uint32 id=\"4\" fmt=\"1\">1</uint32><string id=\"5\" fmt=\"Cache Limiter\">Cache Limiter</string><string ref=\"3\"/></row>\n"
                    "<row><uint32 id=\"6\" fmt=\"2\">2</uint32><string id=\"7\" fmt=\"GPU Read Bandwidth\">GPU Read Bandwidth</string><string id=\"8\" fmt=\"Value\">Value</string></row>\n"
                    "</node></trace-query-result>\n")
    values = tmp_path / "values.xml"
    values.write_text("<?xml version=\"1.0\"?>\n<trace-query-result>\n<node xpath='x'><schema name=\"gpu-counter-value\"></schema>"
                      "<row><event-time id=\"1\" fmt=\"a\">100000000</event-time><uint32 id=\"2\" fmt=\"0\">0</uint32><fixed-decimal id=\"3\" fmt=\"10\">10.0</fixed-decimal><uint64 id=\"4\" fmt=\"7\">7</uint64></row>\n"
                      "<row><event-time ref=\"1\"/><uint32 id=\"5\" fmt=\"1\">1</uint32><fixed-decimal id=\"6\" fmt=\"50\">50.0</fixed-decimal><uint64 ref=\"4\"/></row>\n"
                      "<row><event-time ref=\"1\"/><uint32 id=\"7\" fmt=\"2\">2</uint32><fixed-decimal id=\"8\" fmt=\"99\">99.0</fixed-decimal><uint64 ref=\"4\"/></row>\n"
                      "<row><event-time id=\"9\" fmt=\"b\">200000000</event-time><uint32 ref=\"2\"/><fixed-decimal id=\"10\" fmt=\"80\">80.0</fixed-decimal><uint64 ref=\"4\"/></row>\n"
                      "<row><event-time ref=\"9\"/><uint32 ref=\"5\"/><fixed-decimal id=\"11\" fmt=\"20\">20.0</fixed-decimal><uint64 ref=\"4\"/></row>\n"
                      "</node></trace-query-result>\n")
    got = perf_report.counter_stats(info, values)
    series = got.pop("_series")
    assert series["bins"][10]["ALU Limiter"] == [10.0, 1] and "GPU Read Bandwidth" not in series["bins"][10], series
    assert perf_report.limiter_in(series, 90, 110) == {"name": "Cache Limiter", "mean": 50.0}
    assert perf_report.limiter_in(series, 190, 210) == {"name": "ALU Limiter", "mean": 80.0}
    assert perf_report.limiter_in(series, 90, 210) == {"name": "ALU Limiter", "mean": 45.0}, "mean of 10 and 80 against 35 of 50 and 20"
    assert perf_report.limiter_in(series, 500, 600) is None
    edge = {"bin_ms": 10, "bins": {9: {"A": [100.0, 10]}, 10: {"B": [900.0, 10]}}}
    assert perf_report.limiter_in(edge, 0, 100.0) == {"name": "A", "mean": 10.0}, "a window ending on a bin edge leaves that bin out"
    assert perf_report.limiter_in(edge, 0, 99.999) == {"name": "A", "mean": 10.0}
    assert perf_report.limiter_in(edge, 0, 100.001) == {"name": "B", "mean": 90.0}, "a hair past the edge reads the next bin"
    assert perf_report.limiter_in(edge, 95, 95) == {"name": "A", "mean": 10.0}, "a window of zero width reads the bin that holds it"
    worst = [{"window_ms": [90, 110]}, {"window_ms": [500, 600]}]
    perf_report.attach_limiters(worst, series)
    assert worst[0]["top_limiter"] == {"name": "Cache Limiter", "mean": 50.0} and worst[1]["top_limiter"] is None, worst
    odd = tmp_path / "odd.xml"
    info.write_text(info.read_text() if info.exists() else "")
    odd.write_text("<?xml version=\"1.0\"?>\n<trace-query-result>\n<node xpath='x'><schema name=\"gpu-counter-value\"></schema>"
                   "<row><event-time id=\"1\" fmt=\"empty\"/><uint32 id=\"2\" fmt=\"0\">0</uint32><fixed-decimal id=\"3\" fmt=\"10\">10.0</fixed-decimal><uint64 id=\"4\" fmt=\"7\">7</uint64></row>\n"
                   "<row><event-time ref=\"1\"/><uint32 id=\"5\" fmt=\"1\">1</uint32><fixed-decimal id=\"6\" fmt=\"50\">50.0</fixed-decimal><uint64 ref=\"4\"/></row>\n"
                   "</node></trace-query-result>\n")
    info.write_text("<trace-query-result><node xpath='x'><schema name=\"gpu-counter-info\"><col><mnemonic>counter-id</mnemonic></col>"
                    "<col><mnemonic>name</mnemonic></col><col><mnemonic>type</mnemonic></col></schema>"
                    "<row><uint32 id=\"1\" fmt=\"0\">0</uint32><string id=\"2\" fmt=\"ALU Limiter\">ALU Limiter</string><string id=\"3\" fmt=\"Percentage\">Percentage</string></row>\n"
                    "<row><uint32 id=\"4\" fmt=\"1\">1</uint32><string id=\"5\" fmt=\"Cache Limiter\">Cache Limiter</string><string ref=\"3\"/></row>\n"
                    "</node></trace-query-result>\n")
    got = perf_report.counter_stats(info, odd)
    assert got["samples"] == 2 and got["_series"]["bins"] == {}, "a time cell with no value keeps the counters and leaves the series empty"
    starts = [0.0, 16.0, 32.0, 100.0, 116.0]
    found = perf_report.attribute_hitches([1, 2, 3, 4, 5], starts, [4.0] * 5, [], [], [])
    assert found["worst"][0]["window_ms"] == [32.0, 100.0] and found["worst"][0]["interval_ms"] == 68.0, found

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

def test_memory_trend(tmp_path):
    """memory_trend is the MiB-per-minute slope of the second half of the samples, and None with too few or too close."""
    from metal_gpu_trace import perf_report
    mib = 2**20
    flat_then_growing = [(t * 1000.0, (100 if t < 10 else 100 + (t - 10) * 2) * mib) for t in range(21)]
    assert perf_report.memory_trend(flat_then_growing) == 120.0, perf_report.memory_trend(flat_then_growing)
    assert perf_report.memory_trend([(t * 1000.0, 50 * mib) for t in range(21)]) == 0.0
    assert perf_report.memory_trend([(t * 1000.0, 50 * mib) for t in range(6)]) is None
    assert perf_report.memory_trend([(t * 100.0, 50 * mib) for t in range(40)]) is None
    assert perf_report.memory_trend([]) is None
    burst = [(i * 5.0, (100 + i) * mib) for i in range(1000)] + [(5000.0 + t * 1000.0, 1100 * mib) for t in range(1, 36)]
    assert perf_report.memory_trend(burst) == 0.0, perf_report.memory_trend(burst)

def test_validation(tmp_path):
    """validation_summary counts the shader and API validation messages of a program's output by kind, whatever the offset."""
    from metal_gpu_trace import perf_report
    lines = ["Metal GPU Validation Enabled", "",
             "Invalid Metal usage: Invalid store in 'device' or 'constant' address space at offset 4000000, executing compute function: \"k\" ",
             "Invalid Metal usage: Invalid store in 'device' or 'constant' address space at offset 8, executing compute function: \"k\"",
             "Invalid Metal usage: Invalid load in 'constant' address space at offset 12, executing fragment function: \"f\"",
             "-[MTLDebugComputeCommandEncoder dispatch]:1: failed assertion `Dispatch Threads Validation'"]
    found = perf_report.validation_summary(lines)
    assert found["messages"] == 4 and found["by_kind"]["Invalid store in 'device' or 'constant' address space"] == 2, found
    assert "Dispatch Threads Validation'" in " ".join(found["by_kind"]), found
    assert len(found["examples"]) == 3, found
    assert perf_report.validation_summary(["Metal API Validation Enabled"]) is None
    assert perf_report.validation_summary(["my failed assertion: foo", "/Users/bob/a.c:12: failed assertion `x'"]) is None
    leak = perf_report.validation_summary(["Invalid Metal usage: bad store at 0x10 in /Users/bob/x/y.metal"])
    assert "/Users" not in json.dumps(leak) and "<path>" in json.dumps(leak), leak
    many = perf_report.validation_summary(f"Invalid Metal usage: kind {i}" for i in range(100))
    assert len(many["by_kind"]) == perf_report.VALIDATION_KINDS + 1 and many["by_kind"]["other"] == 80, many
    assert len(many["examples"]) == 5
    stubs, out = tmp_path / "stubs", tmp_path / "runs"
    stubs.mkdir()
    out.mkdir()
    xcrun = stubs / "xcrun"  # an xctrace that records its arguments and fails
    xcrun.write_text(f'#!/bin/zsh\nprint -r -- "$@" > {stubs}/args\nexit 1\n')
    xcrun.chmod(0o755)
    program = tmp_path / "prog"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)

    def launched(perf_env):
        env = dict(os.environ, PERF_OUT=str(out), PERF_MIN_FREE_GB="0", PERF_ENV=perf_env, PATH=f"{stubs}:{os.environ['PATH']}")
        proc = subprocess.run(["zsh", str(PKG / "perf_record.sh"), "f", "2", "native", "-", str(tmp_path), str(program)],
                              capture_output=True, text=True, env=env, timeout=60)
        return (stubs / "args").read_text(), proc.stderr
    for on in ("MTL_SHADER_VALIDATION=1", "A=1 MTL_DEBUG_LAYER=2"):
        assert "--target-stdout" in launched(on)[0], on
    for off in ("", "MTL_SHADER_VALIDATION=0", "MY_MTL_DEBUG_LAYER=1", "NOT_MTL_SHADER_VALIDATION=1", "MTL_DEBUG_LAYER="):
        assert "--target-stdout" not in launched(off)[0], off
    args, warning = launched("MTL_SHADER_VALIDATION=1 DYLD_LIBRARY_PATH=/x")
    assert "--target-stdout" not in args and "DYLD_" in warning, (args, warning)
    assert not list(out.iterdir())

def test_skip_start_up(tmp_path):
    """skip_s recomputes FPS, lows, hitches and Metal memory from the per-frame files without the first seconds, keeps
    the whole-run numbers it cannot recompute, reaches perf_compare, perf_gate and the panel, and refuses a bad value."""
    from metal_gpu_trace import metal_trace_mcp as mcp

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
    from metal_gpu_trace import metal_trace_mcp as mcp

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

def test_golden_metrics(tmp_path):
    """The numbers perf_report and perf_record_windows compute from fixed inputs stay as recorded in
    tests/golden/metrics.json: proof that a refactor leaves the measurements alone."""
    from metal_gpu_trace import perf_record_windows
    spans = [(0, 0, 10_000, 1, 1), (0, 12_000, 8_000, 2, 1), (1, 40_000, 1_000, 3, 2)]
    labels = {1: "[0] Shadow 1", 2: "[1] Main", 3: "[2] Shadow 2"}
    shared = {}
    for side, module in (("mac", perf_report), ("windows", perf_record_windows)):
        shared[side] = {
            "stats": module.stats([1.0, 2.0, 3.0, 10.0]),
            "encoder_stats_empty": module.encoder_stats([], {}),
            "encoder_stats": module.encoder_stats(spans, labels),
            "idle_gaps_empty": module.idle_gaps([]),
            "idle_gaps": module.idle_gaps(spans),
            "label_name": module.label_name("[3] Shadow 12"),
            "public_arguments": module.public_arguments("/opt/x/game.exe -w 1"),
        }
    gaps = [10.0] * 98 + [30.0, 10.0]
    starts = [0, 10, 20, 50, 60, 100, 110, 150, 160, 200, 250, 260]
    totals = [5] * len(starts)
    totals[8] = 39
    shared["mac_only"] = {
        "frame_pacing": perf_report.frame_pacing(gaps, [5.0] * 100),
        "attribute_hitches": perf_report.attribute_hitches(list(range(len(starts))), starts, totals, [(25, 30)],
                                                           [(70, 80)], [(0, 0), (200, 0), (250, 20 * 2**20)]),
    }
    golden("metrics", shared)
