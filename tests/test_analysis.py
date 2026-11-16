"""Tests of the analysis tools: compare, baseline, gate, history, diagnose, A/B, sweep and cold/warm."""
import json
import os
import pathlib

import support  # noqa: F401  (puts src/ on sys.path)


def test_diagnose(tmp_path):
    """perf_diagnose gives a verdict from a summary's encoder numbers and asks to record again an older summary."""
    from metal_gpu_trace import analysis, config, paths
    saved, config.OUT = config.OUT, tmp_path
    try:
        encoders = {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5},
                    "short_share": {"25": 0.497, "50": 0.572}, "by_label": []}
        (tmp_path / "new.json").write_text(json.dumps({"gpu": {"frames": 1378}, "encoders": encoders}))
        (tmp_path / "old.json").write_text(json.dumps({"gpu": {"frames": 1378}}))
        got = analysis.tool_perf_diagnose("new")
        assert got["too_many_short_encoders"] and not got["too_short"], got
        assert got["bottleneck"] == "UNKNOWN" and got["stutter_analysis"]["verdict"] == "UNKNOWN", got
        no_spans = {"gpu": {"frames": 500, "frame_gpu_ms": {"count": 500, "mean": 14.5},
                            "frame_interval_ms": {"count": 499, "mean": 16.7, "p50": 16.6, "p95": 17.0},
                            "stutter_rate_pct": 0.0, "frame_jitter_ms": 0.4},
                    "encoders": {"per_frame": {"count": 0}, "command_buffers_per_frame": {"count": 0},
                                 "short_share": {"25": 0.0}, "by_label": []},
                    "gpu_idle": {"idle_ms_per_frame": {"count": 0}, "gaps_over_1ms": 0, "idle_share": None}}
        (tmp_path / "pm.json").write_text(json.dumps(no_spans))
        got = analysis.tool_perf_diagnose("pm")
        assert got["bottleneck"] == "UNKNOWN" and got["stutter_analysis"]["verdict"] == "SMOOTH", got
        busy = {**no_spans, "gpu_idle": {"idle_ms_per_frame": {"count": 1}, "gaps_over_1ms": 0, "idle_share": 0.4},
                "hitches": {"count": 3, "causes": {"shader_compile": 3}, "worst": []}}
        (tmp_path / "cpu.json").write_text(json.dumps(busy))
        got = analysis.tool_perf_diagnose("cpu")
        assert got["bottleneck"] == "CPU_SUBMISSION_BOUND" and got["hitches"]["count"] == 3, got
        assert any("compilador gráfico" in r for r in got["recommendations"]), got
        assert not any("FlipQueueSize" in r for r in got["recommendations"]), got
        for fps, p50, p95, synced in ((119.9, 8.33, 8.9, 120), (60.1, 16.6, 17.2, 60), (119.9, 8.3, 14.0, None),
                                      (97.0, 10.3, 10.6, None), (None, None, None, None),
                                      (118.9, 8.41, 9.824, 120)):
            sync = {**no_spans, "gpu": {**no_spans["gpu"], "fps_estimate": fps,
                                        "frame_interval_ms": {"count": 499, "mean": 16.7, "p50": p50, "p95": p95}}}
            (tmp_path / "sync.json").write_text(json.dumps(sync))
            got = analysis.tool_perf_diagnose("sync")
            assert got["display_synced_hz"] == synced, (fps, got["display_synced_hz"])
            assert any("sincronización vertical" in r for r in got["recommendations"]) == bool(synced), got
        hung = {**no_spans, "gpu_activity": {"samples": 9, "device_pct": {"mean": 50}, "split_scenes": 12, "recoveries": 1,
                                             "gpu_recovered": True}}
        (tmp_path / "hung.json").write_text(json.dumps(hung))
        got = analysis.tool_perf_diagnose("hung")
        assert got["gpu_activity"]["gpu_recovered"] is True, got
        assert any("se recuperó 1 vez" in r for r in got["recommendations"]), got
        assert any("dividió 12 escenas" in r for r in got["recommendations"]), got
        calm = {**no_spans, "gpu_activity": {"samples": 9, "split_scenes": 0, "recoveries": 0, "gpu_recovered": False}}
        (tmp_path / "calm.json").write_text(json.dumps(calm))
        got = analysis.tool_perf_diagnose("calm")
        assert not any("recuper" in r or "dividió" in r for r in got["recommendations"]), got
        (tmp_path / "winbusy.json").write_text(json.dumps({**busy, "template": "Windows Native Trace"}))
        assert any("FlipQueueSize" in r for r in analysis.tool_perf_diagnose("winbusy")["recommendations"])
        assert not analysis.tool_perf_diagnose("new", min_encoders=8)["too_many_short_encoders"]
        for run, kwargs, words in (("old", {}, "record it again"), ("new", {"short_us": 30}, "short_us is one of")):
            try:
                analysis.tool_perf_diagnose(run, **kwargs)
                raise AssertionError(f"{run} {kwargs} must fail")
            except paths.ToolError as error:
                assert words in str(error), error
    finally:
        config.OUT = saved

def test_compare(tmp_path):
    """perf_compare reports encoder and idle changes and each label's change in GPU ms per frame, largest first,
    and names a run summarized before encoders existed instead of returning nothing for it."""
    from metal_gpu_trace import analysis, config, paths

    def summary(frames, encoders, buffers, short, idle, labels):
        return {"gpu": {"frames": frames, "fps_estimate": 100.0},
                "encoders": {"per_frame": {"p50": encoders}, "command_buffers_per_frame": {"p50": buffers},
                             "short_share": {"25": short, "50": short},
                             "by_label": [{"label": n, "per_frame": c, "total_ms": t} for n, c, t in labels]},
                "gpu_idle": {"idle_share": idle, "idle_ms_per_frame": {"p50": idle * 10}}}
    saved, config.OUT = config.OUT, tmp_path
    try:
        # a: 100 frames; b: 200 frames, so Blit's total doubles while its ms per frame stays
        (tmp_path / "a.json").write_text(json.dumps(summary(100, 2, 1, 0.02, 0.4, [
            ("Render Command", 1.0, 500.0), ("Blit Command", 1.0, 10.0), ("Old Pass", 1.0, 50.0)])))
        (tmp_path / "b.json").write_text(json.dumps(summary(200, 7, 5, 0.5, 0.75, [
            ("Render Command", 3.0, 800.0), ("Blit Command", 4.0, 20.0), ("New Pass", 1.0, 400.0)])))
        (tmp_path / "old.json").write_text(json.dumps({"gpu": {"frames": 300, "fps_estimate": 90.0}}))
        got = analysis.tool_perf_compare("a", "b")
        assert got["encoders"]["encoders_per_frame_p50"] == {"a": 2, "b": 7, "change": 5, "change_pct": 250.0}
        assert got["encoders"]["short_encoder_share"] == {"a": 0.02, "b": 0.5, "change": 0.48, "change_pct": None}
        assert got["encoders"]["gpu_idle_share"]["change"] == 0.35, got["encoders"]
        assert [(r["label"], r["state"], r["ms_per_frame_change"]) for r in got["labels"]] == [
            ("New Pass", "new", 2.0), ("Render Command", "changed", -1.0), ("Old Pass", "gone", -0.5),
            ("Blit Command", "changed", 0.0)], got["labels"]
        assert got["metrics"]["fps"]["change"] == 0.0 and got["too_short"] == []
        old = analysis.tool_perf_compare("old", "b")
        assert old["encoders"]["missing_in"] == ["old"] and "labels" not in old, old
        assert old["metrics"]["fps"] == {"a": 90.0, "b": 100.0, "change": 10.0, "change_pct": 11.1}, old["metrics"]
        try:
            analysis.tool_perf_compare("a", "b", short_us=30)
            raise AssertionError("short_us 30 must fail")
        except paths.ToolError as error:
            assert "short_us is one of" in str(error), error
    finally:
        config.OUT = saved

def test_baseline(tmp_path):
    """perf_baseline saves copies of several runs as a reference with their range, perf_runs leaves the reference
    file out, and perf_check judges a run against that range: same inside it, regressed when FPS falls below it by
    more than the margin or an encoder per frame is added, improved when FPS rises above it, and still usable once
    the reference's runs are deleted."""
    from metal_gpu_trace import analysis, config, paths

    def summary(fps, gpu_ms, encoders, frames=300):
        return {"gpu": {"frames": frames, "fps_estimate": fps, "frame_gpu_ms": {"mean": gpu_ms, "p95": gpu_ms * 2},
                        "frame_interval_ms": {"p95": 20.0}},
                "encoders": {"per_frame": {"p50": encoders}, "command_buffers_per_frame": {"p50": 5},
                             "short_share": {"25": 0.5}, "by_label": [{"label": "Render", "per_frame": 1.0, "total_ms": 1.0}]},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}}
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        for tick, (name, fps) in enumerate((("r1", 60.0), ("r2", 62.0), ("r3", 61.0))):
            path = tmp_path / f"{name}.json"
            path.write_text(json.dumps(summary(fps, 4.3, 7)))
            os.utime(path, (1_000_000 + tick, 1_000_000 + tick))  # distinct times: file clocks can tie on Windows
        got = analysis.tool_perf_baseline("ds", ["r1", "r2", "r3"])
        assert got["range"]["fps"] == {"min": 60.0, "max": 62.0} and got["runs"] == ["r1", "r2", "r3"], got
        assert [r["run"] for r in analysis.tool_perf_runs()["rows"]] == ["r3", "r2", "r1"]
        assert analysis.tool_perf_baseline()["baselines"][0]["name"] == "ds"
        cases = {"same": summary(59.0, 4.4, 7), "regressed_fps": summary(55.0, 4.3, 7),
                 "regressed_enc": summary(61.0, 4.3, 8), "improved": summary(65.0, 4.3, 7),
                 "short": summary(61.0, 4.3, 7, frames=50), "old": {"gpu": {"frames": 300, "fps_estimate": 61.0}}}
        for name, s in cases.items():
            (tmp_path / f"{name}.json").write_text(json.dumps(s))
        assert analysis.tool_perf_check("same", "ds")["verdict"] == "same"
        fps = analysis.tool_perf_check("regressed_fps", "ds")
        assert fps["verdict"] == "regressed" and fps["regressed"][0]["metric"] == "fps", fps
        enc = analysis.tool_perf_check("regressed_enc", "ds")
        assert [r["metric"] for r in enc["regressed"]] == ["encoders_per_frame_p50"], enc
        assert enc["comparison"]["encoders"]["encoders_per_frame_p50"]["b"] == 8
        assert analysis.tool_perf_check("improved", "ds")["verdict"] == "improved"
        assert "hint" in analysis.tool_perf_check("short", "ds")
        old = analysis.tool_perf_check("old", "ds")
        assert old["verdict"] == "same" and "encoders_per_frame_p50" in old["unchecked"], old
        for name in ("r1", "r2", "r3"):
            (tmp_path / f"{name}.json").unlink()
        assert analysis.tool_perf_check("same", "ds")["verdict"] == "same", "a reference outlives its runs"
        for bad in (("bad name!", ["same"]), ("nope", None), (None, ["same"])):
            try:
                analysis.tool_perf_baseline(*bad)
                raise AssertionError(bad)
            except paths.ToolError:
                pass
        try:
            analysis.tool_perf_check("same", "nope")
            raise AssertionError("missing reference must fail")
        except paths.ToolError as error:
            assert "no reference" in str(error)
    finally:
        config.OUT, config.BASELINES = saved

def test_baseline_record(tmp_path):
    """perf_baseline_record records count runs named name-1.. with perf_record's arguments and saves them as the
    reference; count outside 1 to 10 fails before recording."""
    from metal_gpu_trace import config, experiments, paths, recording
    made = []

    def fake_record(label, **kw):
        made.append((label, kw))
        (tmp_path / f"{label}_20261018-000000.json").write_text(json.dumps(
            {"gpu": {"frames": 300, "fps_estimate": 60.0 + len(made), "frame_gpu_ms": {"mean": 4.0}},
             "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5}}}))
    saved = recording.tool_perf_record, config.OUT, config.BASELINES
    recording.tool_perf_record, config.OUT, config.BASELINES = fake_record, tmp_path, tmp_path / "baselines.json"
    try:
        got = experiments.tool_perf_baseline_record("ds", count=2, workload="drawstress", api="d3d12", seconds=30)
        assert [m[0] for m in made] == ["ds-1", "ds-2"] and made[0][1] == {"workload": "drawstress", "api": "d3d12", "seconds": 30}
        assert got["runs"] == ["ds-1_20261018-000000", "ds-2_20261018-000000"], got
        assert got["range"]["fps"] == {"min": 61.0, "max": 62.0}, got
        for bad in (0, 11):
            try:
                experiments.tool_perf_baseline_record("ds", count=bad)
                raise AssertionError(bad)
            except paths.ToolError:
                pass
        assert len(made) == 2
    finally:
        recording.tool_perf_record, config.OUT, config.BASELINES = saved

def test_perf_sweep(tmp_path):
    """perf_sweep records one run per value of one variable, alternating the order each round, takes each metric's
    median per value, fits GPU ms per frame on draws (dim^3) and refuses bad input before recording."""
    from metal_gpu_trace import config, experiments, paths, recording
    made = []

    def fake_record(label, **kw):
        made.append((label, kw.get("dim"), kw.get("env", "")))
        dim = kw.get("dim") or 10
        (tmp_path / f"{label}_20261018-000000.json").write_text(json.dumps(
            {"gpu": {"frames": 300, "fps_estimate": 1000 / (0.5 + 0.001 * dim ** 3), "frame_gpu_ms": {"mean": 0.5 + 0.001 * dim ** 3},
                     "stutter_rate_pct": 1.0}}))
    saved = recording.tool_perf_record, config.OUT
    recording.tool_perf_record, config.OUT = fake_record, tmp_path
    try:
        got = experiments.tool_perf_sweep("t", "dim", [10, 20, 30], rounds=2, seconds=30)
        assert [m[0] for m in made] == ["t-1-r1", "t-2-r1", "t-3-r1", "t-3-r2", "t-2-r2", "t-1-r2"], made
        assert [m[1] for m in made] == [10, 20, 30, 30, 20, 10], made
        assert [r["value"] for r in got["rows"]] == [10, 20, 30] and len(got["rows"][0]["runs"]) == 2, got
        assert got["rows"][2]["metrics"]["frame_gpu_ms_mean"] == 27.5, got
        fit = got["fit"]
        assert fit["x"] == "dim^3" and abs(fit["ms_per_unit"] - 0.001) < 1e-9 and abs(fit["ms_fixed"] - 0.5) < 1e-9, fit
        assert fit["r2"] == 1.0 and not got["too_short"], got
        made.clear()
        env = experiments.tool_perf_sweep("e", "env:MULLION_X", ["0", "1"], env="A=1")
        assert [m[2] for m in made] == ["A=1 MULLION_X=0", "A=1 MULLION_X=1"] and env["fit"] is None, (made, env)
        made.clear()
        for variable, values, rounds in (("fps", [1, 2], 1), ("dim", [10], 1), ("dim", list(range(2, 11)), 1),
                                         ("dim", [2, 3, 4, 5, 6, 7, 8], 4), ("dim", [10, "x"], 1), ("env:bad name", [1, 2], 1),
                                         ("dim", [10, 20], 0)):
            try:
                experiments.tool_perf_sweep("t", variable, values, rounds=rounds)
                raise AssertionError((variable, values, rounds))
            except paths.ToolError:
                pass
        assert not made
    finally:
        recording.tool_perf_record, config.OUT = saved

def test_perf_ab(tmp_path):
    """perf_ab records A B B A, passes each side's env on, and calls a metric better or worse only when every B value
    lies outside A's range; a bad env or rounds fails before recording."""
    from metal_gpu_trace import config, experiments, paths, recording
    made = []

    def fake_record(label, **kw):
        made.append((label, kw["env"]))
        fps = 100.0 if label.split("-")[-1][0] == "a" else 150.0
        (tmp_path / f"{label}_20261018-000000.json").write_text(json.dumps(
            {"gpu": {"frames": 300, "fps_estimate": fps + len(made) / 10, "frame_gpu_ms": {"mean": 4.0},
                     "stutter_rate_pct": 2.0}}))
    saved = recording.tool_perf_record, config.OUT
    recording.tool_perf_record, config.OUT = fake_record, tmp_path
    try:
        got = experiments.tool_perf_ab("t", "", "MULLION_X=1", seconds=30)
        assert made == [("t-a1", ""), ("t-b1", "MULLION_X=1"), ("t-b2", "MULLION_X=1"), ("t-a2", "")], made
        assert got["metrics"]["fps_estimate"]["verdict"] == "better", got
        assert got["metrics"]["frame_gpu_ms_mean"]["verdict"] == "same", got
        assert got["metrics"]["fps_1pct_low"]["verdict"] == "unknown" and not got["too_short"], got
        for kwargs in ({"env_b": "NOT A PAIR"}, {"rounds": 0}, {"rounds": 6}):
            try:
                experiments.tool_perf_ab("t", **({"env_a": "", "env_b": ""} | kwargs))
                raise AssertionError(kwargs)
            except paths.ToolError:
                pass
        assert len(made) == 4
    finally:
        recording.tool_perf_record, config.OUT = saved
    assert experiments.ab_verdict([10, 12], [11, 20], True) == "same"
    assert experiments.ab_verdict([10, 12], [5, 9], True) == "worse" and experiments.ab_verdict([10, 12], [5, 9], False) == "better"

def test_cold_warm(tmp_path):
    """perf_report counts hitches per minute, and cold_warm_report counts the shader_compile hitches only the first run has."""
    from metal_gpu_trace import config, experiments, paths, recording
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
    report = experiments.cold_warm_report("g", ("g-first_1", summary(5, 120.0)), ("g-second_1", summary(1, 8.0)))
    assert report["first_seen_hitches"] == 4 and report["first"]["compiler_busy_ms"] == 120.0, report
    assert report["extra_hitches_in_first"] == 4, report
    assert experiments.cold_warm_report("g", ("a", summary(0, 0.0)), ("b", summary(2, 3.0)))["first_seen_hitches"] == 0
    single = perf_report.attribute_hitches([0, 1], [0.0, 10.0], [1.0, 1.0], [], [], [])
    assert single["per_minute"] == 0.0 and perf_report.attribute_hitches([0], [0.0], [1.0], [], [], [])["per_minute"] is None
    original_out, original_record = config.OUT, recording.tool_perf_record
    config.OUT = tmp_path
    made = []

    def fake_record(label, **kwargs):  # writes the summary a real recording would
        made.append((label, kwargs))
        (tmp_path / f"{label}_20260101-000000.json").write_text(json.dumps(summary(5 if label.endswith("first") else 1, 9.0)))
    recording.tool_perf_record = fake_record
    try:
        real = experiments.tool_perf_cold_warm("w", program="x", seconds=5)
    finally:
        config.OUT, recording.tool_perf_record = original_out, original_record
    assert [m[0] for m in made] == ["w-first", "w-second"] and made[0][1] == {"program": "x", "seconds": 5}, made
    assert real["first_seen_hitches"] == 4 and real["first"]["run"] == "w-first_20260101-000000", real
    try:
        experiments.tool_perf_cold_warm("bad name", program="x")
        raise AssertionError("a name with a space must be refused")
    except paths.ToolError:
        pass

def test_markdown_and_export(tmp_path):
    """perf_compare markdown=true adds tables with the headline numbers and the labels that changed most, and
    perf_export_trace writes one Chrome trace slice per GPU frame without making a new run."""
    from metal_gpu_trace import analysis, config, paths, traces

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
    saved, config.OUT = config.OUT, tmp_path
    try:
        assert "markdown" not in analysis.tool_perf_compare("a", "b")
        md = analysis.tool_perf_compare("a", "b", markdown=True)["markdown"]
        assert "| fps | 60.0 | 50.0 | -10.0 | -16.7 |" in md and "| Render |" in md, md
        got = traces.tool_perf_export_trace("a")
        assert got == {"file": "a.chrome-trace", "frames": 2}, got
        events = json.loads((tmp_path / got["file"]).read_text())["traceEvents"]
        assert events[0]["ts"] == 10500.0 and events[0]["dur"] == 600.0 and events[0]["args"]["fragment"] == 0.2, events
        assert sorted(r["run"] for r in analysis.tool_perf_runs()["rows"]) == ["a", "b"], "the export is not a run"
        try:
            traces.tool_perf_export_trace("b")
            raise AssertionError("a run without frames.csv must fail")
        except paths.ToolError as error:
            assert "per-frame" in str(error)
    finally:
        config.OUT = saved

def test_judge_matches_perf_check(tmp_path):
    """analysis.judge is perf_check's rule: it says worse for exactly the metrics perf_check lists as regressed and
    better for those it lists as improved."""
    from metal_gpu_trace import analysis, config

    for name, fps in (("r1", 62.4), ("r2", 62.4), ("r3", 62.2)):
        (tmp_path / f"{name}.json").write_text(json.dumps(_change_summary("g", fps)))
    saved = config.OUT, config.BASELINES
    config.OUT, config.BASELINES = tmp_path, tmp_path / "baselines.json"
    try:
        analysis.tool_perf_baseline("ref", ["r1", "r2", "r3"])
        span = analysis.ranges(analysis.load_baselines()["ref"]["summaries"])
        for i, (fps, gpu, enc, buf) in enumerate(((70.0, 4.0, 7, 5), (50.0, 5.0, 8, 6), (62.3, 3.0, 6, 4), (64.2, 4.1, 7, 5), (60.4, 4.1, 7, 5))):
            (tmp_path / f"x{i}.json").write_text(json.dumps(_change_summary("g", fps, gpu, enc, buf)))
            check = analysis.tool_perf_check(f"x{i}", "ref")
            s = json.loads((tmp_path / f"x{i}.json").read_text())
            for metric, (get, _) in analysis.CHECKED.items():
                got = analysis.judge(metric, get(s), span[metric], 3)
                assert (got == "worse") == (metric in [r["metric"] for r in check["regressed"]]), (i, metric, got)
                assert (got == "better") == (metric in [r["metric"] for r in check["improved"]]), (i, metric, got)
        assert analysis.judge("fps", None, span["fps"], 3) is None and analysis.judge("fps", 60.0, None, 3) is None
    finally:
        config.OUT, config.BASELINES = saved

def _warn_summary(fps, gpu_ms, frames, duration, layer):
    return {"gpu": {"frames": frames, "fps_estimate": fps, "frame_gpu_ms": {"mean": gpu_ms, "p50": gpu_ms, "p95": gpu_ms},
                    "frame_interval_ms": {"p95": 20.0}},
            "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5}, "short_share": {"25": 0.5}, "by_label": []},
            "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}, "duration_s": duration, "layer": layer}


def _change_summary(program, fps, gpu_ms=4.0, encoders=7, buffers=5, peak=90.0):
    s = _warn_summary(fps, gpu_ms, 400, 60.0, {"none": "native"})
    s["encoders"].update(per_frame={"p50": encoders}, command_buffers_per_frame={"p50": buffers})
    return {**s, "process": {"arguments": program}, "metal_memory_mib": {"peak": peak}}


def test_windows_against_metal(tmp_path):
    """A Windows run against a Metal run says which numbers do not compare and skips the encoders, in perf_compare, its
    Markdown; two runs from one side compare as before."""
    from metal_gpu_trace import analysis, config

    def summary(platform, fps):
        return {"device": {"platform": platform},
                "gpu": {"frames": 300, "fps_estimate": fps, "frame_gpu_ms": {"mean": 4.0, "p95": 6.0}, "frame_interval_ms": {"p95": 20.0}},
                "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5}, "short_share": {"25": 0.5},
                             "by_label": []},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}}
    for run, platform in (("mac", "macOS"), ("mac2", "macOS"), ("win", "Windows")):
        (tmp_path / f"{run}.json").write_text(json.dumps(summary(platform, 60.0)))
        (tmp_path / f"{run}.frames.csv").write_text("frame,start_ms,gpu_ms_total\n1,0.0,4.0\n2,16.0,4.0\n")
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        cross = analysis.tool_perf_compare("mac", "win", markdown=True)
        assert cross["measure"]["a"] == "metal" and cross["measure"]["b"] == "windows", cross.get("measure")
        assert cross["measure"]["not_comparable"] == ["gpu_ms_mean", "gpu_ms_p95", "metal_mib_peak"]
        assert "not_comparable" in cross["encoders"] and "labels" not in cross
        assert "Not comparable between a Windows and a Metal run" in cross["markdown"]
        assert "measure" not in analysis.tool_perf_compare("mac", "mac2")
        for run, locked in (("mac", True), ("mac2", False)):
            locked_summary = summary("macOS", 60.0)
            locked_summary["machine"] = {"screen_locked": locked}
            (tmp_path / f"{run}.json").write_text(json.dumps(locked_summary))
        screen = analysis.tool_perf_compare("mac", "mac2")["screen"]
        assert screen["a"] is True and screen["b"] is False and "GPU ms" in screen["note"] and "unlocked" in screen["note"], screen
        for run, share in (("mac", {"Minimum": 0.65, "Medium": 0.35, "Maximum": 0.0}), ("mac2", {"Minimum": 1.0})):
            state_summary = summary("macOS", 60.0)
            state_summary["gpu_performance_state_share"] = share
            (tmp_path / f"{run}.json").write_text(json.dumps(state_summary))
        state = analysis.tool_perf_compare("mac", "mac2")["gpu_state"]
        assert state["a"] == 0.35 and state["b"] == 0.0 and "GPU ms" in state["note"] and "performance state" in state["note"], state
        for share_b in ({"Minimum": 0.8, "Medium": 0.2}, None):
            near = summary("macOS", 60.0)
            if share_b:
                near["gpu_performance_state_share"] = share_b
            (tmp_path / "mac2.json").write_text(json.dumps(near))
            assert "gpu_state" not in analysis.tool_perf_compare("mac", "mac2"), share_b
        locked_summary["machine"] = {"screen_locked": True}
        (tmp_path / "mac2.json").write_text(json.dumps(locked_summary))
        assert "screen" not in analysis.tool_perf_compare("mac", "mac2")
        (tmp_path / "mac.json").write_text(json.dumps(summary("macOS", 60.0)))
        (tmp_path / "mac2.json").write_text(json.dumps(summary("macOS", 60.0)))
        assert "screen" not in analysis.tool_perf_compare("mac", "mac2")
        slow = summary("Windows", 60.0)
        slow["gpu"]["frame_gpu_ms"]["mean"] = 9.0
        (tmp_path / "win-slow.json").write_text(json.dumps(slow))
        analysis.tool_perf_baseline("ref", ["mac", "mac2"])
        check = analysis.tool_perf_check("win-slow", "ref")
        assert check["verdict"] == "same" and "gpu_ms_mean" in check["unchecked"] and "hint_measure" in check, check
        assert analysis.tool_perf_check("mac2", "ref")["verdict"] == "same" and "hint_measure" not in analysis.tool_perf_check("mac2", "ref")
    finally:
        config.OUT, config.BASELINES = saved

def test_gate_and_spread(tmp_path):
    """perf_gate passes only when every budget holds and fails on a missing number; perf_baseline reports the spread of
    its runs as a % of the midpoint."""
    from metal_gpu_trace import analysis, config, paths

    def summary(fps):
        return {"gpu": {"frames": 300, "fps_estimate": fps, "fps_1pct_low": 40.0, "stutter_rate_pct": 0.5,
                        "frame_gpu_ms": {"mean": 4.0, "p95": 6.0}}, "hitches": {"count": 2}, "metal_memory_mib": {"peak": 120.0},
                "encoders": {"per_frame": {"p50": 3}, "command_buffers_per_frame": {"p50": 2}}}
    for run, fps in (("g1", 60.0), ("g2", 66.0)):
        (tmp_path / f"{run}.json").write_text(json.dumps(summary(fps)))
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        ok = analysis.tool_perf_gate("g1", fps_min=55, hitches_max=2, metal_mib_max=150)
        assert ok["pass"] and [c["ok"] for c in ok["checks"]] == [True, True, True], ok
        bad = analysis.tool_perf_gate("g1", fps_min=61, gpu_ms_p95_max=6.0)
        assert not bad["pass"] and [c["ok"] for c in bad["checks"]] == [False, True], bad
        (tmp_path / "g3.json").write_text(json.dumps({"gpu": {"frames": 300}}))
        missing = analysis.tool_perf_gate("g3", fps_1pct_low_min=30)
        assert not missing["pass"] and missing["checks"][0]["value"] is None, missing
        for kwargs in ({}, {"run": "nope", "fps_min": 1}):
            try:
                analysis.tool_perf_gate(**({"run": "g1"} | kwargs))
                raise AssertionError(f"{kwargs} must fail")
            except paths.ToolError:
                pass
        got = analysis.tool_perf_baseline("ref", ["g1", "g2"])
        assert got["spread_pct"]["fps"] == 9.5 and got["range"]["fps"] == {"min": 60.0, "max": 66.0}, got
    finally:
        config.OUT, config.BASELINES = saved

def test_history(tmp_path):
    """perf_history lists the runs of a prefix oldest first with the change from first to last, flags a series that
    mixes Windows and Metal or has under 3 runs, and refuses an unknown prefix."""
    from metal_gpu_trace import analysis, config, paths

    def summary(platform, fps, hitches):
        return {"device": {"platform": platform}, "gpu": {"frames": 300, "fps_estimate": fps, "frame_gpu_ms": {"mean": 4.0}},
                "hitches": {"count": hitches}}
    for i, (platform, fps, hitches) in enumerate((("macOS", 60.0, 1), ("macOS", 57.0, 3), ("macOS", 54.0, 4))):
        path = tmp_path / f"v{i}.json"
        path.write_text(json.dumps(summary(platform, fps, hitches)))
        os.utime(path, (1000 + i, 1000 + i))
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        got = analysis.tool_perf_history("v")
        assert [r["run"] for r in got["runs"]] == ["v0", "v1", "v2"] and got["change"]["fps"]["change"] == -6.0, got
        assert got["change"]["hitches"]["change"] == 3 and "hint" not in got, got
        assert analysis.tool_perf_history("v", limit=2)["runs"][0]["run"] == "v1"
        assert "under 3 runs" in analysis.tool_perf_history("v0")["hint"]
        (tmp_path / "w0.json").write_text(json.dumps(summary("Windows", 50.0, 0)))
        (tmp_path / "v9.json").write_text(json.dumps(summary("Windows", 50.0, 0)))
        assert "mixes Windows and Metal" in analysis.tool_perf_history("v")["hint"]
        for prefix in ("zzz", "../v"):
            try:
                analysis.tool_perf_history(prefix)
                raise AssertionError(f"{prefix} must fail")
            except paths.ToolError:
                pass
    finally:
        config.OUT, config.BASELINES = saved

def test_listings_survive_hostile_files(tmp_path):
    """perf_runs and perf_history skip a link to nothing, a file of the wrong type and a summary cut short, and never take
    panel.json for a recording; read_frames leaves out a frame number too big for a float; names fit the files they make."""
    from metal_gpu_trace import analysis, config, paths

    good = {"gpu": {"frames": 300, "fps_estimate": 60.0, "frame_gpu_ms": {"mean": 4.0}}, "hitches": {"count": 1}}
    for name in ("v0", "v1"):
        (tmp_path / f"{name}.json").write_text(json.dumps(good))
    os.symlink(tmp_path / "nowhere.json", tmp_path / "v2.json")
    (tmp_path / "v3.json").write_text('{"gpu": {"frames": 3')
    for name, hostile in (("v4", {"gpu": "x", "process": "x"}), ("v5", {"metal_memory_mib": "x"}), ("v6", {"layer": 5}),
                          ("v7", {"layer": {"a": 1}}), ("v8", {"process_rss_mib": "x"})):
        (tmp_path / f"{name}.json").write_text(json.dumps(hostile))
    (tmp_path / "panel.json").write_text(json.dumps([{"id": "tests", "on": True}]))
    (tmp_path / "v0.frames.csv").write_text("frame,start_ms,gpu_ms_total\n" + "9" * 400 + ",1.0,1.0\n1," + "9" * 400 + ",1.0\n2,5.0,1.0\n")
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        runs = {r["run"] for r in analysis.tool_perf_runs()["rows"]}
        assert {"v0", "v1"} <= runs and not runs & {"v2", "v3", "panel"}, runs
        assert [r["run"] for r in analysis.tool_perf_history("v")["runs"]][:2] == ["v0", "v1"]
        try:
            analysis.tool_perf_history("p")
            raise AssertionError("panel.json is not a recording")
        except paths.ToolError as error:
            assert "no run starts with p" in str(error), error
        assert analysis.read_frames("v0") == [(2, 5.0, 1.0)]
    finally:
        config.OUT, config.BASELINES = saved
    (tmp_path / "baselines.json").write_text("{}")
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        for spelling in ("Baselines", "BASELINES", "Panel", "panel"):  # a volume that ignores case opens the same file
            try:
                paths.run_path(spelling)
                raise AssertionError(f"{spelling} is not a recording")
            except paths.ToolError:
                pass
    finally:
        config.OUT, config.BASELINES = saved
    assert paths.name_ok("a" * 120) and not paths.name_ok("a" * 121) and not paths.name_ok("\u00e9" * 61)


def test_tools_answer_a_summary_of_the_wrong_type_with_a_tool_error(tmp_path):
    """perf_compare, perf_check, perf_gate, perf_diagnose and perf_baseline say a recording or a reference is not in the
    form the recorder writes with a ToolError, never with a stray exception, whichever section has the wrong type."""
    from metal_gpu_trace import analysis, config, paths

    def write(name, summary):
        (tmp_path / f"{name}.json").write_text(json.dumps(summary))
    for name in ("r1", "r2", "r3", "good"):
        write(name, _change_summary("g", 60.0))
    hostile = {"s1": {"gpu": "x"}, "s2": {"gpu": {"fps_estimate": "fast", "frame_gpu_ms": "x", "frames": "many"}},
               "s3": {"encoders": "x", "gpu": {"fps_estimate": 60.0}}, "s4": {"encoders": {"per_frame": "x", "short_share": 3}},
               "s5": {"hitches": 5, "metal_memory_mib": [1], "gpu": {"fps_estimate": [60]}}, "s6": {"encoders": {"per_frame": {"p50": "x"}, "short_share": {"25": "x"}}}}
    for name, summary in hostile.items():
        write(name, summary)
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        analysis.tool_perf_baseline("ref", ["r1", "r2", "r3"])
        evil = {"summaries": [{"gpu": "x"}, {"gpu": {"fps_estimate": "x"}}], "runs": ["r1", "r2"], "skip_s": 0}
        (tmp_path / "baselines.json").write_text(json.dumps({"ref": json.loads((tmp_path / "baselines.json").read_text())["ref"], "evil": evil}))
        calls = []
        for bad in hostile:
            calls += [(f"compare {bad}", lambda bad=bad: analysis.tool_perf_compare("good", bad)),
                      (f"compare {bad} first", lambda bad=bad: analysis.tool_perf_compare(bad, "good")),
                      (f"check {bad}", lambda bad=bad: analysis.tool_perf_check(bad, "ref")),
                      (f"gate {bad}", lambda bad=bad: analysis.tool_perf_gate(bad, fps_min=30.0, hitches_max=3, metal_mib_max=100.0)),
                      (f"diagnose {bad}", lambda bad=bad: analysis.tool_perf_diagnose(bad)),
                      (f"baseline {bad}", lambda bad=bad: analysis.tool_perf_baseline("n_" + bad, [bad, "r1", "r2"]))]
        calls += [("check against evil", lambda: analysis.tool_perf_check("good", "evil")),
                  ("list references", lambda: analysis.tool_perf_baseline())]
        refused = 0
        for label, call in calls:
            try:
                call()
            except paths.ToolError as error:
                refused += 1
                assert str(tmp_path) not in str(error), (label, error)
            except Exception as error:  # noqa: BLE001 (the point of the test)
                raise AssertionError(f"{label}: {type(error).__name__} escaped: {error}") from None
        assert refused >= len(hostile), f"only {refused} of {len(calls)} calls were refused"
    finally:
        config.OUT, config.BASELINES = saved

def test_write_file_does_not_follow_a_link(tmp_path):
    """paths.write_file writes a file, replacing one, and refuses a link instead of writing through it."""
    from metal_gpu_trace import paths

    target = tmp_path / "page.html"
    paths.write_file(target, "one")
    paths.write_file(target, "two")
    assert target.read_text() == "two"
    victim = tmp_path / "precious.txt"
    victim.write_text("PRECIOUS")
    link = tmp_path / "link.html"
    os.symlink(victim, link)
    try:
        paths.write_file(link, "overwritten")
        raise AssertionError("a link must be refused")
    except paths.ToolError as error:
        assert "link" in str(error) and str(tmp_path) not in str(error), error
    assert victim.read_text() == "PRECIOUS"
    (tmp_path / "folder").mkdir()
    try:
        paths.write_file(tmp_path / "folder", "x")
        raise AssertionError("a folder is not a file")
    except paths.ToolError:
        pass


def test_the_tools_that_write_into_the_runs_folder_do_not_follow_a_link(tmp_path):
    """perf_baseline and trace_chrome (the files they write) refuse a link planted in the runs folder."""
    from metal_gpu_trace import analysis, config, paths, traces

    victim = tmp_path / "precious.txt"
    victim.write_text("{}")
    runs = tmp_path / "runs"
    runs.mkdir()
    for name in ("r1", "r2", "r3"):
        (runs / f"{name}.json").write_text(json.dumps(_change_summary("g", 60.0)))
    (runs / "r1.frames.csv").write_text("frame,start_ms,gpu_ms_total\n1,0.0,4.0\n")
    os.symlink(victim, runs / "baselines.json")
    os.symlink(victim, runs / "r1.chrome-trace")
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (runs, runs / "baselines.json")
    try:
        for call in (lambda: analysis.tool_perf_baseline("ref", ["r1", "r2", "r3"]),
                     lambda: traces.tool_perf_export_trace("r1")):
            try:
                call()
                raise AssertionError("a link must be refused")
            except paths.ToolError:
                pass
        (runs / "baselines.json").unlink()
        (runs / "baselines.json").write_text("not json")
        try:
            analysis.tool_perf_baseline()
            raise AssertionError("a baselines.json that is not JSON must be refused")
        except paths.ToolError as error:
            assert "baselines.json" in str(error) and str(tmp_path) not in str(error), error
    finally:
        config.OUT, config.BASELINES = saved
    assert victim.read_text() == "{}"


def test_importing_the_server_survives_an_unusable_metal_trace_out(tmp_path):
    """A METAL_TRACE_OUT that cannot be resolved (a link loop raises on Python before 3.13) does not stop the import:
    project.apply reports it in every tool call instead."""
    import subprocess
    import sys

    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    src = pathlib.Path(__file__).resolve().parent.parent / "src"
    code = (f"import sys; sys.path.insert(0, {str(src)!r}); from metal_gpu_trace import config, project; "
            "project.apply(None, {'METAL_TRACE_OUT': " + repr(str(loop)) + "}); print('ok', bool(config.PROJECT_ERROR) or sys.version_info >= (3, 13))")
    got = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=tmp_path,
                         env={"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "METAL_TRACE_OUT": str(loop)})
    assert got.returncode == 0 and got.stdout.strip() == "ok True", got.stderr[-300:]


def test_read_frames_parses_a_file_once_and_follows_its_changes(tmp_path):
    """Reading the same unchanged frames.csv again does not parse it again (a tool reads it several times per
    request); a file that changed, in size or in time, is read afresh; the caller may change what it gets."""
    import os
    from metal_gpu_trace import analysis, config

    csv_path = tmp_path / "r.frames.csv"
    csv_path.write_text("frame,start_ms,gpu_ms_total\n1,0.0,4.0\n2,16.0,4.0\n")
    parsed = []
    real = analysis._csv_rows
    analysis._csv_rows = lambda *a, **k: (parsed.append(1), real(*a, **k))[1]
    saved, config.OUT = config.OUT, tmp_path
    try:
        first = analysis.read_frames("r")
        assert first == [(1, 0.0, 4.0), (2, 16.0, 4.0)] and len(parsed) == 1
        first.append("changed by the caller")
        assert analysis.read_frames("r") == [(1, 0.0, 4.0), (2, 16.0, 4.0)] and len(parsed) == 1, "the cache is not shared"
        csv_path.write_text("frame,start_ms,gpu_ms_total\n1,0.0,4.0\n2,16.0,4.0\n3,32.0,5.0\n")
        assert len(analysis.read_frames("r")) == 3 and len(parsed) == 2
        csv_path.write_text("frame,start_ms,gpu_ms_total\n1,0.0,9.0\n2,16.0,9.0\n3,32.0,9.0\n")  # same size, same second
        os.utime(csv_path, ns=(csv_path.stat().st_atime_ns, csv_path.stat().st_mtime_ns + 1))
        assert analysis.read_frames("r")[0] == (1, 0.0, 9.0) and len(parsed) == 3
    finally:
        analysis._csv_rows, config.OUT = real, saved


def test_windows_runs_without_encoders(tmp_path):
    """Two Windows runs recorded with PresentMon or DWM have no encoder spans: comparing them and diagnosing one gives
    no encoder verdict instead of the misleading "short_us is one of ..." error, also against a summary written
    before 0.23.0 (every cut at 0.0)."""
    from metal_gpu_trace import analysis, config, metrics, paths
    empty = {"device": {"platform": "Windows"}, "gpu": {"frames": 200},
             "encoders": metrics.encoder_stats([], {}), "gpu_idle": metrics.idle_gaps([])}
    old = {**empty, "encoders": {**empty["encoders"], "short_share": {str(c): 0.0 for c in metrics.SHORT_US}}}
    for sa, expected in ((empty, None), (old, 0.0)):
        result = analysis.compare_summaries(sa, empty, "a", "b")
        assert result["encoders"]["short_encoder_share"]["a"] == expected, result["encoders"]
        assert result["encoders"]["short_encoder_share"]["b"] is None, result["encoders"]
    try:
        analysis.compare_summaries(empty, empty, "a", "b", short_us=33)
    except paths.ToolError as error:
        assert "short_us is one of" in str(error)
    else:
        raise AssertionError("an unknown short_us must still be refused")
    saved = config.OUT
    config.OUT = tmp_path
    try:
        (tmp_path / "w.json").write_text(json.dumps(empty), encoding="utf-8")
        verdict = analysis.tool_perf_diagnose("w")
        try:
            analysis.tool_perf_diagnose("w", short_us=33)
        except paths.ToolError as error:
            assert "short_us is one of" in str(error)
        else:
            raise AssertionError("diagnose must refuse an unknown short_us")
    finally:
        config.OUT = saved
    assert verdict["too_many_short_encoders"] is False, verdict


def test_perf_runs_names_the_project(tmp_path):
    """perf_runs says which project's recordings it lists, and null without a project file."""
    from metal_gpu_trace import analysis, config
    saved = config.OUT, config.BASELINES, config.PROJECT
    config.OUT, config.BASELINES = tmp_path, tmp_path / "baselines.json"
    try:
        config.PROJECT = None
        assert analysis.tool_perf_runs()["project"] is None
        config.PROJECT = {"name": "mullion"}
        assert analysis.tool_perf_runs()["project"] == "mullion"
    finally:
        config.OUT, config.BASELINES, config.PROJECT = saved


def test_unpresented_is_surfaced(tmp_path):
    """A run whose program stopped presenting carries gpu.unpresented: perf_compare, perf_check, perf_baseline and
    perf_diagnose say so with a note, and perf_gate fails it, since its frame numbers cover only part of the run."""
    from metal_gpu_trace import analysis, config
    stall = {"frames": [252], "from_s": 3.363, "span_s": 17.4, "command_buffers": 4141, "gpu_ms": 10977.0,
             "share_of_gpu_time": 0.91}

    def summary(unpresented=None):
        gpu = {"frames": 300, "fps_estimate": 230.0, "frame_gpu_ms": {"mean": 2.6, "p95": 3.4}, "frame_interval_ms": {"p95": 7.0}}
        if unpresented:
            gpu["unpresented"] = unpresented
        return {"gpu": gpu, "encoders": {"per_frame": {"p50": 2}, "command_buffers_per_frame": {"p50": 1},
                                         "short_share": {"25": 0.01}, "by_label": []},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 1.6}}}
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        (tmp_path / "good.json").write_text(json.dumps(summary()))
        (tmp_path / "bad.json").write_text(json.dumps(summary(stall)))
        compared = analysis.tool_perf_compare("good", "bad")
        assert compared["unpresented"]["runs"] == {"bad": stall} and "window" in compared["unpresented"]["note"], compared
        assert "unpresented" not in analysis.tool_perf_compare("good", "good")
        assert analysis.tool_perf_baseline("ref", ["good", "bad"])["unpresented"]["runs"] == {"bad": stall}
        assert "unpresented" not in analysis.tool_perf_baseline("clean", ["good"])
        assert analysis.tool_perf_check("bad", "clean")["unpresented"]["runs"] == {"bad": stall}
        gate = analysis.tool_perf_gate("bad", fps_min=1)
        assert not gate["pass"] and gate["unpresented"]["runs"] == {"bad": stall}, gate
        assert analysis.tool_perf_gate("good", fps_min=1)["pass"]
        diagnosis = analysis.tool_perf_diagnose("bad")
        assert diagnosis["unpresented"]["runs"] == {"bad": stall} and "3.363" in diagnosis["recommendations"][0], diagnosis
        assert "unpresented" not in analysis.tool_perf_diagnose("good")
        frames = "frame,start_ms,gpu_ms_total\n" + "".join(f"{i},{1000 + i * 10},2.0\n" for i in range(300))
        early = dict(stall, from_s=0.2, span_s=1.5)
        (tmp_path / "load.json").write_text(json.dumps(summary(early)))
        (tmp_path / "load.frames.csv").write_text(frames)
        assert not analysis.tool_perf_gate("load", fps_min=1)["pass"], "the whole run holds the stall"
        assert analysis.tool_perf_gate("load", fps_min=1, skip_s=1)["pass"], "skip_s past the stall leaves it out"
        (tmp_path / "late.json").write_text(json.dumps(summary(stall)))
        (tmp_path / "late.frames.csv").write_text(frames)
        assert not analysis.tool_perf_gate("late", fps_min=1, skip_s=1)["pass"], "a stall after the cut stays"
        assert "presentados" in diagnosis["recommendations"][0], diagnosis["recommendations"][0]
    finally:
        config.OUT, config.BASELINES = saved


def _put_table_run(out, run, gz):
    """Writes a summary and a 400-frame table (10 ms frames, a 40 ms hitch at frames 21 and 301) for `run`, as `.csv.gz`
    (a recording made now) or as plain `.csv` (one made before the gzip change), with a Metal memory table likewise."""
    from metal_gpu_trace import tables
    t, starts = 0.0, []
    for i in range(400):
        t += 40.0 if i in (20, 300) else 10.0
        starts.append(round(t, 3))
    worst = [{"frame": f, "interval_ms": 40.0, "cause": "shader_compile", "cpu_pct": 100.0} for f in (21, 301)]
    summary = {"gpu": {"frames": 400, "fps_estimate": 90.0, "frame_gpu_ms": {"mean": 4.0, "p50": 4.0, "p95": 4.0, "max": 4.0},
                       "frame_interval_ms": {"p95": 10.0}},
               "hitches": {"count": 2, "threshold_ms": 15.0, "causes": {"shader_compile": 2}, "worst": worst},
               "metal_memory_mib": {"peak": 90.0},
               "encoders": {"per_frame": {"p50": 2}, "command_buffers_per_frame": {"p50": 1}, "short_share": {"25": 0.1},
                            "by_label": []},
               "gpu_idle": {"idle_share": 0.1, "idle_ms_per_frame": {"p50": 1}}}
    (out / f"{run}.json").write_text(json.dumps(summary))
    frames = [(i + 1, s, 4.0) for i, s in enumerate(starts)]
    memory = [(s, (90 if s < 1500 else 60) * 2**20) for s in starts[::10]]
    tables.write(out, f"{run}.frames", ["frame", "start_ms", "gpu_ms_total"], frames, compress=gz)
    tables.write(out, f"{run}.metal_memory", ["time_ms", "metal_allocated_bytes"], memory, compress=gz)


def test_old_csv_and_new_csv_gz_read_the_same_in_every_tool(tmp_path):
    """A recording whose tables are plain `.csv` (made before 0.26.0) answers perf_compare, perf_history, perf_gate and
    perf_export_trace with the same numbers as one whose tables are `.csv.gz`."""
    from metal_gpu_trace import analysis, config, traces
    for run, gz in (("old1", False), ("old2", False), ("new1", True), ("new2", True)):
        _put_table_run(tmp_path, run, gz)
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        assert (tmp_path / "old1.frames.csv").exists() and (tmp_path / "new1.frames.csv.gz").exists()
        old = analysis.tool_perf_compare("old1", "old2", skip_s=1.5)
        new = analysis.tool_perf_compare("new1", "new2", skip_s=1.5)
        assert old["metrics"] == new["metrics"] and old["skipped_s"] == new["skipped_s"] == 1.5, (old, new)
        assert new["metrics"]["metal_mib_peak"]["a"] == 60.0, "memory comes from the gz table too"
        hist = {p: [{k: v for k, v in r.items() if k != "run"} for r in analysis.tool_perf_history(p, skip_s=1.5)["runs"]]
                for p in ("old", "new")}
        assert hist["old"] == hist["new"] and len(hist["new"]) == 2, hist
        assert analysis.tool_perf_gate("old1", hitches_max=1, skip_s=1.5) == dict(
            analysis.tool_perf_gate("new1", hitches_max=1, skip_s=1.5), run="old1")
        a, b = traces.tool_perf_export_trace("old1"), traces.tool_perf_export_trace("new1")
        assert a["frames"] == b["frames"] == 400, (a, b)
        assert (tmp_path / "old1.chrome-trace").read_text() == (tmp_path / "new1.chrome-trace").read_text()
    finally:
        config.OUT, config.BASELINES = saved


def test_truncated_gz_gives_tool_error(tmp_path):
    """A `.csv.gz` that is cut short, damaged or not gzip at all is a ToolError that says to record again, in every
    reader, never a gzip or zlib exception."""
    from metal_gpu_trace import analysis, config, paths, traces
    _put_table_run(tmp_path, "cut", True)
    for name in ("frames", "metal_memory"):
        path = tmp_path / f"cut.{name}.csv.gz"
        data = path.read_bytes()
        path.write_bytes(data[: len(data) // 2])
    (tmp_path / "bad.json").write_text("{}")
    (tmp_path / "bad.frames.csv.gz").write_text("not gzip at all")
    saved, config.OUT = config.OUT, tmp_path
    try:
        for call in (lambda: analysis.read_frames("cut"), lambda: analysis.read_memory("cut"),
                     lambda: analysis.read_frames("bad"), lambda: traces.tool_perf_export_trace("cut"),
                     lambda: traces.tool_perf_export_trace("bad")):
            try:
                call()
            except paths.ToolError as error:
                assert "cannot be read; record it again" in str(error), error
            else:
                raise AssertionError("an unreadable table must raise ToolError")
    finally:
        config.OUT = saved


def test_schema_of_defaults_to_one():
    """A summary says which generation it is in `schema_version`; one without it, or with a value that is not a whole
    number of 1 or more, is generation 1."""
    from metal_gpu_trace import metrics
    assert metrics.SCHEMA_VERSION == 2
    for value in (None, "2", 0, -1, True, 2.0, [2]):
        assert metrics.schema_of({"schema_version": value}) == 1, value
    assert metrics.schema_of({}) == 1 and metrics.schema_of({"schema_version": 2}) == 2
    assert metrics.schema_of({"schema_version": 3}) == 3
    for hostile in (None, [], "x", 7):
        assert metrics.schema_of(hostile) == 1, hostile


def test_old_summaries_read_in_every_tool(tmp_path):
    """A summary recorded before schema_version existed (generation 1, plain `.frames.csv`, no `tier`, no `retention`)
    goes through every tool that reads recordings without error; perf_runs lists its generation."""
    from metal_gpu_trace import analysis, config
    for run, gz in (("v1a", False), ("v1b", False), ("v2a", True)):
        _put_table_run(tmp_path, run, gz)
    s = json.loads((tmp_path / "v2a.json").read_text())
    (tmp_path / "v2a.json").write_text(json.dumps({"schema_version": 2, **s}))
    assert "schema_version" not in json.loads((tmp_path / "v1a.json").read_text())
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        rows = {r["run"]: r["schema_version"] for r in analysis.tool_perf_runs()["rows"]}
        assert rows == {"v1a": 1, "v1b": 1, "v2a": 2}, rows
        analysis.tool_perf_compare("v1a", "v1b")
        analysis.tool_perf_compare("v1a", "v2a", skip_s=1.5)
        analysis.tool_perf_baseline("v1ref", ["v1a", "v1b"])
        assert analysis.tool_perf_history("v1")["runs"], "history"
        analysis.tool_perf_diagnose("v1a")
        analysis.tool_perf_gate("v1a", fps_min=1)
        assert analysis.tool_perf_check("v1a", "v1ref")["verdict"] in ("same", "better", "worse", "different")
    finally:
        config.OUT, config.BASELINES = saved


def test_compare_notes_tier_difference(tmp_path):
    """perf_compare says so when the two recordings were made at different tiers; same tier or an older recording
    without one says nothing."""
    from metal_gpu_trace import analysis, config
    for run, tier in (("l", "light"), ("s", "standard"), ("s2", "standard"), ("old", None)):
        _put_table_run(tmp_path, run, True)
        if tier:
            data = json.loads((tmp_path / f"{run}.json").read_text())
            (tmp_path / f"{run}.json").write_text(json.dumps({**data, "tier": tier}))
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        got = analysis.tool_perf_compare("l", "s")
        assert got["tier"]["a"] == "light" and got["tier"]["b"] == "standard", got.get("tier")
        assert "memory only between recordings of the same tier" in got["tier"]["note"]
        assert "tier" not in analysis.tool_perf_compare("s", "s2")
        assert "tier" not in analysis.tool_perf_compare("old", "s")
    finally:
        config.OUT, config.BASELINES = saved


def _actions_summary(**changes):
    """A clean 20 s run of 300 frames with no hitches; `changes` replace whole top-level keys."""
    base = {"label": "game", "duration_s": 20.0, "gpu": {"frames": 300, "fps_estimate": 60.0},
            "hitches": {"count": 0, "causes": {}, "worst": []}}
    return {**base, **changes}


def _shader_hitches(end_ms, cause="shader_compile"):
    return {"count": 2, "causes": {cause: 2},
            "worst": [{"frame": 5, "cause": cause, "window_ms": [50.0, 100.0]},
                      {"frame": 9, "cause": cause, "window_ms": [150.0, end_ms]}]}


FRAMES = [(i, i * 10.0, 4.0) for i in range(300)]


def _tools(actions):
    return [a["tool"] for a in actions]


def test_actions_cold_warm_on_shader_hitches():
    from metal_gpu_trace import analysis
    got = analysis.suggested_actions(_actions_summary(hitches=_shader_hitches(200.0)), "game_1")
    assert got[0] == {"tool": "perf_cold_warm", "arguments": {"name": "game-cw"}, "reason": got[0]["reason"]}, got
    assert "game_1" in got[0]["reason"] and "same program arguments" in got[0]["reason"]
    assert _tools(got) == ["perf_cold_warm"], "no frames file: no skip_s rule"


def test_actions_skip_s_from_startup_compile():
    from metal_gpu_trace import analysis
    got = analysis.suggested_actions(_actions_summary(hitches=_shader_hitches(1400.0)), "game_1", rows=FRAMES)
    assert _tools(got) == ["perf_cold_warm", "perf_compare"], got
    assert got[1]["arguments"] == {"skip_s": 2} and "20 longest" in got[1]["reason"], got[1]  # 1.4 s, rounded up


def test_actions_skip_s_not_suggested_when_late_or_already_skipped():
    from metal_gpu_trace import analysis
    late = analysis.suggested_actions(_actions_summary(hitches=_shader_hitches(9000.0)), "r", rows=FRAMES)  # 9 s > 25 % of 20 s
    assert _tools(late) == ["perf_cold_warm"], late
    early = _actions_summary(hitches=_shader_hitches(1400.0))
    assert "perf_compare" not in _tools(analysis.suggested_actions(early, "r", skip_s=2, rows=FRAMES)), "already skipped"
    assert "perf_compare" in _tools(analysis.suggested_actions(early, "r", skip_s=1, rows=FRAMES))
    other = _actions_summary(hitches=_shader_hitches(1400.0, cause="memory_growth"))
    assert analysis.suggested_actions(other, "r", rows=FRAMES) == [], "only shader compilation asks for skip_s"


def test_actions_without_frames_file_skips_rule_2():
    from metal_gpu_trace import analysis
    got = analysis.suggested_actions(_actions_summary(hitches=_shader_hitches(1400.0)), "r", rows=None)
    assert "perf_compare" not in _tools(got) and "perf_cold_warm" in _tools(got)
    assert "perf_compare" not in _tools(analysis.suggested_actions(_actions_summary(hitches=_shader_hitches(1400.0)), "r", rows=[]))


def test_actions_short_run():
    from metal_gpu_trace import analysis
    got = analysis.suggested_actions(_actions_summary(gpu={"frames": 60}), "r")
    assert got[0]["tool"] == "perf_record" and got[0]["arguments"] == {"seconds": 30}, got
    assert analysis.suggested_actions(_actions_summary(gpu={"frames": 100}), "r") == []


def test_actions_noisy():
    from metal_gpu_trace import analysis
    got = analysis.suggested_actions(_actions_summary(noisy_environment=True), "r")
    assert got[0]["tool"] == "perf_record" and got[0]["arguments"] == {} and "GPU" in got[0]["reason"], got
    assert analysis.suggested_actions(_actions_summary(noisy_environment=False), "r") == []


def test_actions_unpresented():
    from metal_gpu_trace import analysis
    got = analysis.suggested_actions(_actions_summary(gpu={"frames": 300, "unpresented": {"frames": [200], "from_s": 9.0}}), "r")
    assert got[0]["tool"] == "perf_record" and "visible" in got[0]["reason"], got


def test_actions_thermal():
    from metal_gpu_trace import analysis
    drift = _actions_summary(gpu={"frames": 300, "throttling_analysis": {"thermal_throttling_detected": True}})
    got = analysis.suggested_actions(drift, "r")
    assert got[0]["tool"] == "perf_ab" and got[0]["arguments"] == {"cooldown_s": 60}, got
    assert "starting value, not a measurement" in got[0]["reason"]
    by_cause = analysis.suggested_actions(_actions_summary(hitches=_shader_hitches(200.0, cause="thermal")), "r")
    assert _tools(by_cause) == ["perf_ab"], by_cause


def test_actions_empty_for_clean_run():
    from metal_gpu_trace import analysis
    assert analysis.suggested_actions(_actions_summary(), "r", rows=FRAMES) == []


def test_actions_survive_hostile_summaries():
    from metal_gpu_trace import analysis
    for hostile in ({}, {"gpu": "x"}, {"gpu": {"frames": "many"}}, {"hitches": []}, {"hitches": {"causes": []}},
                    {"hitches": {"causes": {"shader_compile": 1}, "worst": ["x", {"cause": "shader_compile", "window_ms": "?"},
                                                                           {"cause": "shader_compile", "window_ms": [1]}]},
                     "duration_s": "long"},
                    {"hitches": {"causes": {"shader_compile": 1}, "worst": [{"cause": "shader_compile", "window_ms": [0, float("nan")]}]},
                     "duration_s": 20}, {"label": 5, "hitches": {"causes": {"shader_compile": 1}}}):
        assert isinstance(analysis.suggested_actions(hostile, "r", rows=FRAMES), list), hostile


def test_every_suggested_tool_exists():
    from metal_gpu_trace import analysis, registry
    every = {"hitches": _shader_hitches(1400.0), "gpu": {"frames": 10, "unpresented": {"frames": [1]},
                                                         "throttling_analysis": {"thermal_throttling_detected": True}},
             "noisy_environment": True, "label": "g", "duration_s": 20.0}
    got = analysis.suggested_actions(every, "r", rows=FRAMES)
    assert len(got) >= 6, _tools(got)
    for action in got:
        assert action["tool"] in registry.TOOLS, action
        assert set(action) == {"tool", "arguments", "reason"} and isinstance(action["arguments"], dict)
        properties = registry.TOOLS[action["tool"]][1]["properties"]
        assert set(action["arguments"]) <= set(properties), (action, sorted(properties))


def test_diagnose_and_compare_have_the_field(tmp_path):
    from metal_gpu_trace import analysis, config
    for run in ("a", "b"):
        _put_table_run(tmp_path, run, True)
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        s = json.loads((tmp_path / "a.json").read_text())
        (tmp_path / "a.json").write_text(json.dumps({**s, "label": "a", "duration_s": 4.0}))
        diagnosed = analysis.tool_perf_diagnose("a")
        assert "recommendations" in diagnosed and _tools(diagnosed["suggested_actions"]) == ["perf_cold_warm"], diagnosed["suggested_actions"]
        compared = analysis.tool_perf_compare("a", "b")
        assert [(x["tool"]) for x in compared["suggested_actions"]].count("perf_cold_warm") == 2, compared["suggested_actions"]
        assert any("a:" in x["reason"] for x in compared["suggested_actions"]) and any("b:" in x["reason"] for x in compared["suggested_actions"])
        clean = {k: v for k, v in s.items() if k != "hitches"}
        (tmp_path / "b.json").write_text(json.dumps(clean))
        assert analysis.tool_perf_diagnose("b")["suggested_actions"] == []
    finally:
        config.OUT, config.BASELINES = saved


def _noisy_run(tmp_path, run, noisy):
    _put_table_run(tmp_path, run, True)
    data = json.loads((tmp_path / f"{run}.json").read_text())
    if noisy is not None:
        data["noisy_environment"] = noisy
        if noisy:
            data["noisy_basis"] = {"gpu_device_pct_mean": 90.0, "process_busy_pct": 50.0, "external_pct": 40.0}
    (tmp_path / f"{run}.json").write_text(json.dumps(data))


def test_compare_warns_with_the_runs(tmp_path):
    from metal_gpu_trace import analysis, config
    for run, noisy in (("q1", False), ("q2", False), ("n1", True), ("old", None)):
        _noisy_run(tmp_path, run, noisy)
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        got = analysis.tool_perf_compare("q1", "n1")["noisy_environment"]
        assert got["runs"] == ["n1"] and "another process" in got["note"] and "repeat" in got["note"], got
        assert analysis.tool_perf_compare("n1", "n1")["noisy_environment"]["runs"] == ["n1"]
        assert "noisy_environment" not in analysis.tool_perf_compare("q1", "q2")
        assert "noisy_environment" not in analysis.tool_perf_compare("q1", "old"), "an old summary has no flag"
    finally:
        config.OUT, config.BASELINES = saved


def test_baseline_warns(tmp_path):
    from metal_gpu_trace import analysis, config
    for run, noisy in (("q1", False), ("q2", False), ("n1", True)):
        _noisy_run(tmp_path, run, noisy)
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        quiet = analysis.tool_perf_baseline("quiet", ["q1", "q2"])
        assert "noisy_environment" not in quiet, quiet
        noisy = analysis.tool_perf_baseline("loud", ["q1", "n1"])
        assert noisy["noisy_environment"]["runs"] == ["n1"], noisy.get("noisy_environment")
    finally:
        config.OUT, config.BASELINES = saved


def test_old_summary_without_flag_is_fine(tmp_path):
    from metal_gpu_trace import analysis, config
    _noisy_run(tmp_path, "old1", None)
    _noisy_run(tmp_path, "old2", None)
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        assert "noisy_environment" not in analysis.tool_perf_compare("old1", "old2")
        assert "noisy_environment" not in analysis.tool_perf_baseline("oldref", ["old1", "old2"])
        assert analysis.tool_perf_diagnose("old1")["suggested_actions"] is not None
    finally:
        config.OUT, config.BASELINES = saved


def test_actions_label_and_rows_edge_cases():
    from metal_gpu_trace import analysis
    hitches = _shader_hitches(1400.0)
    long_label = "x" * 95  # <label>-cw-second would pass 100 characters: the name is cut so it stays valid
    for label, expected in (("", "r_1-cw"), (long_label, "x" * 90 + "-cw"), ("g" * 90, "g" * 90 + "-cw"), (7, "r_1-cw"),
                            ("bad label!", "r_1-cw")):
        got = analysis.suggested_actions(_actions_summary(label=label, hitches=hitches), "r_1")
        assert got[0]["arguments"] == {"name": expected}, (label, got[0])
    for rows in ([()], [[]], [None], [("a", "b")], lambda: None, lambda: [()]):
        assert _tools(analysis.suggested_actions(_actions_summary(hitches=hitches), "r", rows=rows)) == ["perf_cold_warm"], rows


def test_frames_are_read_only_when_a_rule_needs_them(tmp_path):
    from metal_gpu_trace import analysis, config
    _put_table_run(tmp_path, "m", True)
    data = json.loads((tmp_path / "m.json").read_text())
    data["hitches"] = {"count": 1, "causes": {"memory_growth": 1}, "worst": []}
    (tmp_path / "m.json").write_text(json.dumps({**data, "label": "m"}))
    reads = []
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    real = analysis._frames_or_none
    analysis._frames_or_none = lambda run: reads.append(run) or real(run)
    try:
        analysis.tool_perf_diagnose("m")
        analysis.tool_perf_compare("m", "m")
        assert reads == [], "no shader_compile cause: the frames table stays closed"
        _put_table_run(tmp_path, "s", True)
        analysis.tool_perf_diagnose("s")
        assert reads == ["s"], reads
    finally:
        analysis._frames_or_none = real
        config.OUT, config.BASELINES = saved


def test_compare_accepts_skip_s_as_none_or_text(tmp_path):
    """skip_s as steady_summary takes it (None, a numeric string) must not break the suggestions."""
    from metal_gpu_trace import analysis, config
    for run in ("a", "b"):
        _put_table_run(tmp_path, run, True)
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        for skip in (None, "2", 0, "0", 1.5):
            got = analysis.tool_perf_compare("a", "b", skip_s=skip)
            assert isinstance(got["suggested_actions"], list), skip
    finally:
        config.OUT, config.BASELINES = saved
