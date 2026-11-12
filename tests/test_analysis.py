"""Tests of the analysis tools: compare, baseline, gate, history, panel, diagnose, A/B, sweep and cold/warm."""
import json
import os

import support  # noqa: F401  (puts src/ on sys.path)


def test_diagnose(tmp_path):
    """perf_diagnose gives a verdict from a summary's encoder numbers and asks to record again an older summary."""
    from metal_gpu_trace import metal_trace_mcp as mcp
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
    from metal_gpu_trace import metal_trace_mcp as mcp

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
    from metal_gpu_trace import metal_trace_mcp as mcp

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

def test_baseline_record(tmp_path):
    """perf_baseline_record records count runs named name-1.. with perf_record's arguments and saves them as the
    reference; count outside 1 to 10 fails before recording."""
    from metal_gpu_trace import metal_trace_mcp as mcp
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

def test_perf_sweep(tmp_path):
    """perf_sweep records one run per value of one variable, alternating the order each round, takes each metric's
    median per value, fits GPU ms per frame on draws (dim^3) and refuses bad input before recording."""
    from metal_gpu_trace import metal_trace_mcp as mcp
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
    from metal_gpu_trace import metal_trace_mcp as mcp
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

def test_cold_warm(tmp_path):
    """perf_report counts hitches per minute, and cold_warm_report counts the shader_compile hitches only the first run has."""
    from metal_gpu_trace import metal_trace_mcp as mcp
    from metal_gpu_trace import perf_report
    starts = [i * 10.0 for i in range(100)]
    starts[50:] = [t + 100 for t in starts[50:]]
    found = perf_report.attribute_hitches(list(range(100)), starts, [1.0] * 100, [(500, 560)], [], [])
    assert found["count"] == 1 and found["per_minute"] == round(1 / ((starts[-1] - starts[0]) / 60000), 2), found
    assert perf_report.attribute_hitches([0], [0.0], [1.0], [], [], [])["count"] == 0

    def summary(compiles, busy):
        return {"gpu": {"frames": 900}, "hitches": {"count": compiles + 1, "per_minute": 3.0,
                                                    "causes": {"shader_compile": compiles, "cpu_or_wait": 1}},
                "graphics_compiler": {"busy_ms": busy}}
    report = mcp.cold_warm_report("g", ("g-first_1", summary(5, 120.0)), ("g-second_1", summary(1, 8.0)))
    assert report["first_seen_hitches"] == 4 and report["first"]["compiler_busy_ms"] == 120.0, report
    assert report["extra_hitches_in_first"] == 4, report
    assert mcp.cold_warm_report("g", ("a", summary(0, 0.0)), ("b", summary(2, 3.0)))["first_seen_hitches"] == 0
    single = perf_report.attribute_hitches([0, 1], [0.0, 10.0], [1.0, 1.0], [], [], [])
    assert single["per_minute"] == 0.0 and perf_report.attribute_hitches([0], [0.0], [1.0], [], [], [])["per_minute"] is None
    original_out, original_record = mcp.OUT, mcp.tool_perf_record
    mcp.OUT = tmp_path
    made = []

    def fake_record(label, **kwargs):  # writes the summary a real recording would
        made.append((label, kwargs))
        (tmp_path / f"{label}_20260101-000000.json").write_text(json.dumps(summary(5 if label.endswith("first") else 1, 9.0)))
    mcp.tool_perf_record = fake_record
    try:
        real = mcp.tool_perf_cold_warm("w", program="x", seconds=5)
    finally:
        mcp.OUT, mcp.tool_perf_record = original_out, original_record
    assert [m[0] for m in made] == ["w-first", "w-second"] and made[0][1] == {"program": "x", "seconds": 5}, made
    assert real["first_seen_hitches"] == 4 and real["first"]["run"] == "w-first_20260101-000000", real
    try:
        mcp.tool_perf_cold_warm("bad name", program="x")
        raise AssertionError("a name with a space must be refused")
    except mcp.ToolError:
        pass

def test_markdown_and_export(tmp_path):
    """perf_compare markdown=true adds tables with the headline numbers and the labels that changed most, and
    perf_export_trace writes one Chrome trace slice per GPU frame without making a new run."""
    from metal_gpu_trace import metal_trace_mcp as mcp

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

def test_panel(tmp_path):
    """perf_panel writes one self-contained page: no path, no raw </script> from a label, every hitch kept when the
    frames are cut, and an error for a run without frames, a bad preset or the wrong number of runs."""
    from metal_gpu_trace import metal_trace_mcp as mcp

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
    from metal_gpu_trace import metal_trace_mcp as mcp

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
    from metal_gpu_trace import metal_trace_mcp as mcp

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
    from metal_gpu_trace import metal_trace_mcp as mcp

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

def test_layout(tmp_path):
    """perf_panel(layout=...) saves panel.json (the listed tabs on, in order, the rest off), every panel carries it, and a
    panel.json that is not a list of tabs, or a layout with an unknown tab, is refused."""
    from metal_gpu_trace import metal_trace_mcp as mcp

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
