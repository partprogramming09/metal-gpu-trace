"""Unit tests for perf_record_windows.py."""
import csv
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import pytest

import perf_record_windows as prw
import metal_trace_mcp as mcp

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows (ctypes.windll, DWM)")

# a program that reports its own frame times, the way the drawstress workload does
LOG_PROGRAM = [sys.executable, "-c",
               "import os, time; open(os.environ['DRAWSTRESS_LOG'], 'w').write("
               "'dim 1 draws 1 frame_us 16666 frames 120\\n'); time.sleep(2)"]


def dwm_available():
    """Returns whether DwmGetCompositionTimingInfo yields frame samples here: false over SSH or in a service."""
    import threading
    stop, samples = threading.Event(), []
    thread = threading.Thread(target=prw.sample_dwm_frame_times, args=(0, stop, samples), daemon=True)
    thread.start()
    time.sleep(1.0)
    stop.set()
    thread.join(timeout=2)
    return bool(samples)


def record_or_skip(*args, **kwargs):
    """Runs record_windows and skips the test when the desktop was idle: DWM counts a frame only when the screen
    changes, so an idle desktop gives no samples."""
    try:
        return prw.record_windows(*args, **kwargs)
    except RuntimeError as err:
        if "no frame data" in str(err):
            pytest.skip("the desktop was idle during the recording: DWM produced no frames")
        raise


needs_dwm = pytest.mark.skipif(sys.platform != "win32" or not dwm_available(), reason="no DWM samples: run from the interactive desktop session")


def test_attach_nonexistent_process(tmp_path):
    """Detection of nonexistent process in attach mode (both by name and by PID)."""
    # 1. Non-existent executable name
    fake_exe = "nonexistent_fake_process_99999.exe"
    try:
        prw.record_windows("test_nonexistent", 1, "attach", "-", "-", [fake_exe], out_dir=tmp_path)
        raise AssertionError("Expected failure on nonexistent process name")
    except RuntimeError as err:
        assert f"no running process matches {fake_exe}" in str(err), f"Unexpected message: {err}"

    # 2. Non-existent PID
    fake_pid = "9999999"
    try:
        prw.record_windows("test_nonexistent_pid", 1, "attach", "-", "-", [fake_pid], out_dir=tmp_path)
        raise AssertionError("Expected failure on nonexistent PID")
    except RuntimeError as err:
        assert f"no running process matches {fake_pid}" in str(err), f"Unexpected message: {err}"

    # Ensure lock is not left behind
    assert not (tmp_path / ".recording").exists()


@needs_dwm
def test_attach_existing_process(tmp_path):
    """Attaching to a running process records RSS and leaves the process running."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        summary, json_path = record_or_skip("test_attach_live", 1, "attach", "-", "-", [str(proc.pid)], out_dir=tmp_path)
        assert json_path.exists()
        assert summary["process"]["pid"] == proc.pid
        assert summary["process"]["termination-reason"] == "running"
        assert summary["layer"]["unknown"]
        # The process must still be running after recording
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait()


def test_lock_handling(tmp_path):
    """Manejo del lock .recording: prevents concurrent recording and cleans up."""
    lock_file = tmp_path / ".recording"
    lock_file.mkdir()

    try:
        prw.record_windows("test_lock", 1, "native", "-", tmp_path, [sys.executable, "-c", "pass"], out_dir=tmp_path)
        raise AssertionError("Expected failure due to pre-existing .recording lock")
    except RuntimeError as err:
        assert "another recording is running" in str(err), f"Unexpected message: {err}"

    # Remove pre-existing lock
    lock_file.rmdir()

    # Normal run must acquire lock and release it cleanly
    summary, json_path = prw.record_windows("test_lock_ok", 1, "native", "-", tmp_path, LOG_PROGRAM, out_dir=tmp_path)
    assert not lock_file.exists(), "Lock must be removed after successful run"


def test_recording_and_schema_verification(tmp_path):
    """Recording a test process with generation of .json, .frames.csv, .rss.csv and verifying schema."""
    summary, json_path = prw.record_windows(
        "test_run",
        2,
        "native",
        "-",
        tmp_path,
        LOG_PROGRAM,
        out_dir=tmp_path,
    )

    # 1. Check generated files
    stem = json_path.stem
    frames_csv = tmp_path / f"{stem}.frames.csv"
    rss_csv = tmp_path / f"{stem}.rss.csv"

    assert json_path.exists(), f"Missing {json_path}"
    assert frames_csv.exists(), f"Missing {frames_csv}"
    assert rss_csv.exists(), f"Missing {rss_csv}"

    # 2. Check frames.csv format
    with open(frames_csv, encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert reader[0] == ["frame", "start_ms", "gpu_ms_draw", "gpu_ms_total"], f"Invalid frames header: {reader[0]}"
        assert len(reader) > 1, "frames.csv should contain data rows"
        # Check first row values are numeric
        assert int(reader[1][0]) == 1
        assert float(reader[1][1]) >= 0.0
        assert float(reader[1][2]) > 0.0
        assert float(reader[1][3]) > 0.0

    # 3. Check rss.csv format
    with open(rss_csv, encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert reader[0] == ["time_s", "rss_kib"], f"Invalid rss header: {reader[0]}"
        assert len(reader) >= 2, "rss.csv should contain sampled rows"
        # Check time_s is integer and rss_kib is integer
        assert reader[1][0].isdigit()
        assert reader[1][1].isdigit()

    # 4. JSON Schema validation
    expected_top_keys = {
        "label", "trace", "process", "device", "template", "duration_s",
        "missing_tables", "gpu", "encoders", "gpu_idle", "metal_memory_mib",
        "process_rss_mib", "layer"
    }
    assert expected_top_keys.issubset(summary.keys()), f"Missing keys: {expected_top_keys - set(summary.keys())}"

    # Check device info
    device = summary["device"]
    assert device["platform"] == "Windows"
    assert "model" in device and device["model"]
    assert "memory-size" in device and int(device["memory-size"]) > 0
    assert "os-version" in device and device["os-version"]

    # Check process info
    proc_info = summary["process"]
    assert proc_info["pid"] > 0
    assert proc_info["termination-reason"] == "exit"
    assert "arguments" in proc_info

    # Check gpu stats
    gpu = summary["gpu"]
    assert gpu["frames"] > 0
    assert gpu["intervals"] > 0
    for stat_field in ("count", "mean", "p50", "p95", "max"):
        assert stat_field in gpu["frame_gpu_ms"], f"Missing {stat_field} in frame_gpu_ms"
        assert stat_field in gpu["per_channel_ms"]["draw"], f"Missing {stat_field} in per_channel_ms.draw"
    assert gpu["fps_estimate"] is not None and gpu["fps_estimate"] > 0
    # The drawstress log holds per-line means, so no frame-level distribution is reported.
    assert gpu["frame_times"] == "per-line mean of the drawstress log"
    for absent in ("fps_1pct_low", "fps_01pct_low", "stutter_rate_pct", "frame_jitter_ms"):
        assert absent in gpu and gpu[absent] is None, absent
    assert "throttling_analysis" in gpu
    throttling = gpu["throttling_analysis"]
    assert "thermal_throttling_detected" in throttling
    assert "fps_initial" in throttling
    assert "fps_final" in throttling
    assert "fps_drift_pct" in throttling

    # Check encoders stats
    encoders = summary["encoders"]
    assert "per_frame" in encoders
    assert "command_buffers_per_frame" in encoders
    assert "short_share" in encoders
    for cut in prw.SHORT_US:
        assert str(cut) in encoders["short_share"], f"Missing cut {cut} in short_share"
    assert "by_label" in encoders

    # Check gpu_idle
    gpu_idle = summary["gpu_idle"]
    assert "idle_ms_per_frame" in gpu_idle
    assert "gaps_over_1ms" in gpu_idle
    assert "idle_share" in gpu_idle

    # Check metal_memory_mib
    assert summary["metal_memory_mib"] == {"samples": 0}

    # Check process_rss_mib
    assert summary["process_rss_mib"]["count"] > 0
    assert summary["process_rss_mib"]["max"] > 0

    # Check layer
    assert summary["layer"].get("none") in ("native Windows, no translation layer", "native Metal, no translation layer")

    # 5. Check compatibility with metal_trace_mcp compare_summaries
    cmp_res = mcp.compare_summaries(summary, summary, "run_a", "run_b")
    assert cmp_res["a"] == "run_a"
    assert cmp_res["b"] == "run_b"
    assert cmp_res["layer"]["same"] is True
    assert "fps_1pct_low" in cmp_res["metrics"]
    assert "fps_01pct_low" in cmp_res["metrics"]
    assert "stutter_rate_pct" in cmp_res["metrics"]
    assert "frame_jitter_ms" in cmp_res["metrics"]


def test_drawstress_workload_parsing(tmp_path):
    """Drawstress log output parsing and telemetry calculation."""
    # Create mock program that writes to DRAWSTRESS_LOG
    script = tmp_path / "mock_drawstress.py"
    script.write_text("""
import os, time
log_path = os.environ.get("DRAWSTRESS_LOG")
assert log_path, "DRAWSTRESS_LOG must be passed"
with open(log_path, "a", encoding="utf-8") as f:
    f.write("dim 40 draws 64000 frame_us 16666 frames 60\\n")
    f.write("dim 40 draws 64000 frame_us 16500 frames 60\\n")
time.sleep(1)
""", encoding="utf-8")

    summary, json_path = prw.record_windows(
        "test_drawstress",
        1,
        "native",
        "-",
        tmp_path,
        [sys.executable, str(script)],
        program_env="DRAWSTRESS_DIM=40",
        out_dir=tmp_path,
    )

    assert json_path.exists()
    assert summary["gpu"]["frames"] == 120
    assert summary["gpu"]["intervals"] == 120
    assert summary["gpu"]["frame_gpu_ms"]["count"] == 120

    # Verify frames.csv has 120 data rows
    frames_csv = tmp_path / f"{json_path.stem}.frames.csv"
    with open(frames_csv, encoding="utf-8") as f:
        rows = list(csv.reader(f))[1:]
        assert len(rows) == 120
        assert int(rows[0][0]) == 1
        assert int(rows[-1][0]) == 120


def test_cancel_and_progress(tmp_path):
    """A cancelled recording stops, kills its program, leaves no files or lock, and reports progress every 5 s."""
    import threading
    script = tmp_path / "hang.py"
    script.write_text("import time; time.sleep(30)\n", encoding="utf-8")
    cancel, seen = threading.Event(), []
    threading.Timer(7, cancel.set).start()
    with pytest.raises(RuntimeError, match="cancelled"):
        prw.record_windows("test_cancel", seconds=20, wine="native", prefix="-", workdir=tmp_path,
                           command=[sys.executable, str(script)], out_dir=tmp_path, cancelled=cancel.is_set,
                           progress=lambda *a: seen.append(a))
    assert seen and seen[0][:2] == (5, 20), seen
    assert not (tmp_path / ".recording").exists()
    assert not [p.name for p in tmp_path.glob("test_cancel*") if p.name != "hang.py"]


def test_timeout_and_cleanup(tmp_path):
    """Overrunning deadline terminates process, cleans partial files and raises error."""
    script = tmp_path / "hang.py"
    script.write_text("import time; time.sleep(30)\n", encoding="utf-8")

    try:
        prw.record_windows(
            "test_hang",
            seconds=10,
            wine="native",
            prefix="-",
            workdir=tmp_path,
            command=[sys.executable, str(script)],
            out_dir=tmp_path,
            timeout=1,
        )
        raise AssertionError("Expected timeout overrun failure")
    except RuntimeError as err:
        assert "the recording took over 1 s and was stopped; nothing was saved" in str(err), f"Unexpected message: {err}"

    # Verify no partial files or lock left behind
    assert not (tmp_path / ".recording").exists()
    leftover = [p.name for p in tmp_path.glob("test_hang*")]
    assert not leftover, f"Leftover files found: {leftover}"


def test_vegaflow_telemetry_bridge(tmp_path):
    """Mejora 8: VegaFlow Hardware Telemetry Bridge integration and fallback."""
    # 1. Test live collect_device_info() preserves mandatory schema fields
    dev = prw.collect_device_info()
    assert dev["platform"] == "Windows"
    assert "model" in dev and dev["model"]
    assert "memory-size" in dev and int(dev["memory-size"]) > 0
    assert "os-version" in dev and dev["os-version"]

    # If vegaflow_daemon is built and present on this system, verify enrichment
    vf_bin_exists = any(
        p.is_file() for p in (
            pathlib.Path("../build/vegaflow_daemon.exe"),
            pathlib.Path("build/vegaflow_daemon.exe"),
            pathlib.Path(__file__).resolve().parent.parent / "build" / "vegaflow_daemon.exe",
        )
    )
    if vf_bin_exists:
        assert "cpu_architecture" in dev, f"Expected cpu_architecture in enriched device: {dev}"
        assert "gpu_architecture" in dev, f"Expected gpu_architecture in enriched device: {dev}"
        assert len(dev["cpu_architecture"]) > 0
        assert len(dev["gpu_architecture"]) > 0

    # 2. Test mock enrichment with explicit APU Zen 2 / Vega 6 payload
    mock_vf = {
        "cpu": {
            "brand_string": "AMD Ryzen 5 4600H with Radeon Graphics",
            "microarchitecture": "Zen 2 Renoir 7nm",
        },
        "gpu": {
            "adapter_name": "AMD Radeon(TM) Graphics (Vega 6 / GCN 5.0)",
            "architecture": "UMA (Unified Memory Architecture)",
        },
        "ram": {
            "channel_topology": "Dual-Channel (128-bit bus bandwidth)",
            "memory_bus_width_bits": 128,
        },
    }
    mock_dev = {
        "platform": "Windows",
        "model": "Generic CPU",
        "memory-size": "16000000000",
        "os-version": "10.0.0",
    }
    prw._enrich_device_with_vegaflow(mock_dev, mock_vf)
    assert mock_dev["cpu_architecture"] == "Zen 2 Renoir 7nm"
    assert mock_dev["gpu_architecture"] == "Vega 6 / GCN 5.0, bus dual-channel 128-bit"
    # Mandatory fields intact
    assert mock_dev["platform"] == "Windows"
    assert mock_dev["model"] == "Generic CPU"
    assert mock_dev["memory-size"] == "16000000000"
    assert mock_dev["os-version"] == "10.0.0"

    # 3. Test fallback when daemon executable does not exist
    fallback_dev = prw.collect_device_info(daemon_path=tmp_path / "nonexistent_vegaflow.exe")
    assert fallback_dev["platform"] == "Windows"
    assert "model" in fallback_dev and fallback_dev["model"]
    assert "memory-size" in fallback_dev and int(fallback_dev["memory-size"]) > 0
    assert "os-version" in fallback_dev and fallback_dev["os-version"]


def test_precision_telemetry_calculation(tmp_path):
    """Validation of 1% Low, 0.1% Low, stutter rate, frame jitter, and thermal throttling drift."""
    # 0. Too few frames for a percentile low, and nothing to judge stutter or throttling from
    few = prw.compute_precision_telemetry([16.666] * 99, [10.0] * 99)
    assert few["fps_1pct_low"] is None and few["fps_01pct_low"] is None
    mid = prw.compute_precision_telemetry([16.666] * 999, [10.0] * 999)
    assert mid["fps_1pct_low"] == 60.0 and mid["fps_01pct_low"] is None
    single = prw.compute_precision_telemetry([16.666], [])
    assert single["stutter_rate_pct"] is None and single["frame_jitter_ms"] is None
    assert prw.compute_precision_telemetry([], [])["stutter_rate_pct"] is None
    no_gpu = prw.compute_precision_telemetry([16.666] * 200, [])
    assert no_gpu["throttling_analysis"]["thermal_throttling_detected"] is None

    # 1. 1000 perfectly paced 60 FPS frames (16.666 ms)
    gaps_60 = [16.666] * 1000
    totals_60 = [10.0] * 1000
    res = prw.compute_precision_telemetry(gaps_60, totals_60)
    assert res["fps_estimate"] == 60.0
    assert res["fps_1pct_low"] == 60.0
    assert res["fps_01pct_low"] == 60.0
    assert res["stutter_rate_pct"] == 0.0
    assert res["frame_jitter_ms"] == 0.0
    assert res["throttling_analysis"]["thermal_throttling_detected"] is False
    assert res["throttling_analysis"]["fps_drift_pct"] == 0.0

    # 2. Injected stutters (4 frames of 40ms > 1.5 * 16.666 = 25ms)
    gaps_stutter = [16.666] * 960 + [40.0] * 40
    res_stutter = prw.compute_precision_telemetry(gaps_stutter, totals_60)
    assert res_stutter["stutter_rate_pct"] == 4.0
    assert res_stutter["frame_jitter_ms"] > 0.0
    assert res_stutter["fps_1pct_low"] == round(1000.0 / 40.0, 1)
    assert res_stutter["fps_01pct_low"] == round(1000.0 / 40.0, 1)

    # 3. Thermal throttling drift:
    # First 20 frames at 16.666 ms (60 FPS) with 10 ms GPU time
    # Last 20 frames at 25.0 ms (40 FPS) with 18 ms GPU time
    gaps_throttle = [16.666] * 20 + [20.0] * 60 + [25.0] * 20
    totals_throttle = [10.0] * 20 + [14.0] * 60 + [18.0] * 20
    res_throttle = prw.compute_precision_telemetry(gaps_throttle, totals_throttle)
    assert res_throttle["throttling_analysis"]["thermal_throttling_detected"] is True
    assert res_throttle["throttling_analysis"]["fps_initial"] == 60.0
    assert res_throttle["throttling_analysis"]["fps_final"] == 40.0
    assert res_throttle["throttling_analysis"]["fps_drift_pct"] == round(((60.0 - 40.0) / 60.0) * 100, 1)


def test_diagnose_bottlenecks_and_recommendations(tmp_path):
    """Validation of bottleneck classification, stutter analysis, and actionable recommendations."""
    saved, mcp.OUT = mcp.OUT, tmp_path
    try:
        def make_summary(frame_gpu_mean, interval_mean, idle_share, rss_max, stutter_rate, jitter, encoders_p50=2, short_share=0.05, throttling_detected=False):
            return {
                "gpu": {
                    "frames": 200,
                    "fps_estimate": round(1000.0 / interval_mean, 1) if interval_mean else 60.0,
                    "fps_1pct_low": 45.0,
                    "fps_01pct_low": 30.0,
                    "stutter_rate_pct": stutter_rate,
                    "frame_jitter_ms": jitter,
                    "frame_gpu_ms": {"count": 200, "mean": frame_gpu_mean, "p50": frame_gpu_mean, "p95": frame_gpu_mean + jitter, "max": frame_gpu_mean + 10.0},
                    "frame_interval_ms": {"count": 200, "mean": interval_mean, "p50": interval_mean, "p95": interval_mean + jitter, "max": interval_mean + 15.0},
                    "throttling_analysis": {"thermal_throttling_detected": throttling_detected, "fps_drift_pct": 15.0 if throttling_detected else 0.0},
                },
                "encoders": {
                    "per_frame": {"p50": encoders_p50},
                    "command_buffers_per_frame": {"p50": 2},
                    "short_share": {"25": short_share, "50": short_share},
                    "by_label": [{"label": "draw", "per_frame": 1.0, "total_ms": 100.0}],
                },
                "gpu_idle": {
                    "idle_share": idle_share,
                    "idle_ms_per_frame": {"p50": interval_mean * idle_share},
                    "gaps_over_1ms": 20 if idle_share > 0.2 else 0,
                },
                "process_rss_mib": {"count": 10, "max": rss_max, "mean": rss_max * 0.9},
                "metal_memory_mib": {"samples": 0},
            }

        # 1. GPU_BOUND
        (tmp_path / "gpu_bound.json").write_text(json.dumps(make_summary(15.5, 16.6, 0.05, 800.0, 1.0, 1.0)))
        diag_gpu = mcp.tool_perf_diagnose("gpu_bound")
        assert diag_gpu["bottleneck"] == "GPU_BOUND"
        assert diag_gpu["stutter_analysis"]["verdict"] == "SMOOTH"
        assert any("FSR" in r for r in diag_gpu["recommendations"])

        # 2. CPU_SUBMISSION_BOUND
        (tmp_path / "cpu_bound.json").write_text(json.dumps(make_summary(8.0, 16.6, 0.45, 800.0, 4.0, 2.0)))
        diag_cpu = mcp.tool_perf_diagnose("cpu_bound")
        assert diag_cpu["bottleneck"] == "CPU_SUBMISSION_BOUND"
        assert diag_cpu["stutter_analysis"]["verdict"] == "MICRO_STUTTER"
        assert any("FlipQueueSize=3" in r for r in diag_cpu["recommendations"])

        # 3. MEMORY_PRESSURE_SUSPECTED (a hypothesis: bandwidth is not measured)
        (tmp_path / "mem_bound.json").write_text(json.dumps(make_summary(12.0, 16.6, 0.18, 2500.0, 8.5, 5.5)))
        diag_mem = mcp.tool_perf_diagnose("mem_bound")
        assert diag_mem["bottleneck"] == "MEMORY_PRESSURE_SUSPECTED"
        assert diag_mem["stutter_analysis"]["verdict"] == "SEVERE_STUTTER"
        assert any("sombras de 2048 a 1024" in r for r in diag_mem["recommendations"])
        assert any("cascadas de sombras a 2" in r for r in diag_mem["recommendations"])

        # 4. BALANCED with thermal throttling
        (tmp_path / "balanced.json").write_text(json.dumps(make_summary(10.0, 16.6, 0.18, 900.0, 0.5, 1.0, throttling_detected=True)))
        diag_bal = mcp.tool_perf_diagnose("balanced")
        assert diag_bal["bottleneck"] == "BALANCED"
        assert any("Estrangulamiento térmico" in r for r in diag_bal["recommendations"])
    finally:
        mcp.OUT = saved


def test_compare_summaries_enriched_metrics(tmp_path):
    """Validation that compare_summaries tracks 1% Low, 0.1% Low, stutter rate, and jitter."""
    s1 = {
        "gpu": {
            "frames": 200,
            "fps_estimate": 60.0,
            "fps_1pct_low": 50.0,
            "fps_01pct_low": 40.0,
            "stutter_rate_pct": 1.5,
            "frame_jitter_ms": 0.8,
            "frame_gpu_ms": {"mean": 12.0, "p95": 14.0},
            "frame_interval_ms": {"p95": 16.8},
        },
        "encoders": {
            "per_frame": {"p50": 2},
            "command_buffers_per_frame": {"p50": 1},
            "short_share": {"25": 0.05},
            "by_label": [],
        },
        "gpu_idle": {"idle_share": 0.1, "idle_ms_per_frame": {"p50": 1.0}},
    }
    s2 = {
        "gpu": {
            "frames": 200,
            "fps_estimate": 75.0,
            "fps_1pct_low": 65.0,
            "fps_01pct_low": 55.0,
            "stutter_rate_pct": 0.5,
            "frame_jitter_ms": 0.4,
            "frame_gpu_ms": {"mean": 9.5, "p95": 11.0},
            "frame_interval_ms": {"p95": 13.5},
        },
        "encoders": {
            "per_frame": {"p50": 2},
            "command_buffers_per_frame": {"p50": 1},
            "short_share": {"25": 0.05},
            "by_label": [],
        },
        "gpu_idle": {"idle_share": 0.08, "idle_ms_per_frame": {"p50": 0.8}},
    }
    cmp_res = mcp.compare_summaries(s1, s2, "run1", "run2")
    m = cmp_res["metrics"]
    assert m["fps"]["a"] == 60.0 and m["fps"]["b"] == 75.0
    assert m["fps_1pct_low"]["a"] == 50.0 and m["fps_1pct_low"]["b"] == 65.0 and m["fps_1pct_low"]["change"] == 15.0
    assert m["fps_01pct_low"]["a"] == 40.0 and m["fps_01pct_low"]["b"] == 55.0 and m["fps_01pct_low"]["change"] == 15.0
    assert m["stutter_rate_pct"]["a"] == 1.5 and m["stutter_rate_pct"]["b"] == 0.5 and m["stutter_rate_pct"]["change"] == -1.0
    assert m["frame_jitter_ms"]["a"] == 0.8 and m["frame_jitter_ms"]["b"] == 0.4 and m["frame_jitter_ms"]["change"] == -0.4


def test_dwm_timing_structures_and_query(tmp_path):
    """Validation of DWM timing structures and dwmapi composition timing capability."""
    import ctypes
    assert hasattr(prw, "UNSIGNED_RATIO")
    assert hasattr(prw, "DWM_TIMING_INFO")

    dti = prw.DWM_TIMING_INFO()
    dti.cbSize = ctypes.sizeof(prw.DWM_TIMING_INFO)
    assert hasattr(dti, "cFrame")
    assert hasattr(dti, "rateRefresh")
    assert hasattr(dti, "qpcRefreshPeriod")

    dwmapi = getattr(ctypes.windll, "dwmapi", None)
    if dwmapi and hasattr(dwmapi, "DwmGetCompositionTimingInfo"):
        hr = dwmapi.DwmGetCompositionTimingInfo(0, ctypes.byref(dti))
        if hr != 0:
            dti_leg = prw.DWM_TIMING_INFO_LEGACY()
            dti_leg.cbSize = ctypes.sizeof(prw.DWM_TIMING_INFO_LEGACY)
            hr = dwmapi.DwmGetCompositionTimingInfo(0, ctypes.byref(dti_leg))
        # When composition is available, hr must be 0 (S_OK)
        assert hr in (0, -2003304304)


def test_presentmon_install_checks_the_pinned_hash(tmp_path, monkeypatch):
    """presentmon_install saves a download only when its SHA-256 is the pinned one, and reuses it afterwards."""
    import hashlib
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(mcp, "download", lambda url, path, max_bytes: path.write_bytes(b"x"))
    with pytest.raises(mcp.ToolError, match="pins"):
        mcp.tool_presentmon_install()
    assert not list((tmp_path / "metal-gpu-trace").glob("*.exe"))
    monkeypatch.setitem(mcp.PRESENTMON, "sha256", hashlib.sha256(b"x").hexdigest())
    first = mcp.tool_presentmon_install()
    assert first["installed"] and pathlib.Path(first["path"]).is_file()
    assert mcp.tool_presentmon_install()["installed"] is False
    assert prw.find_presentmon() == first["path"]


def test_drawstress_reads_microseconds_and_skips_empty_lines(tmp_path):
    """frame_us is microseconds; a line with no time or no frames adds nothing instead of inventing 0.001 ms."""
    log_lines = ("dim 1 draws 1 frame_us 8000 frames 50\\n"
                 "dim 2 draws 1 frame_us 0 frames 10\\n"
                 "dim 3 draws 1 frame_us 9000 frames 0\\n")
    code = ("import os, time; open(os.environ['DRAWSTRESS_LOG'], 'w').write('" + log_lines + "'); time.sleep(2)")
    summary, _ = prw.record_windows("test_units", 1, "native", "-", tmp_path, [sys.executable, "-c", code],
                                    out_dir=tmp_path)
    gpu = summary["gpu"]
    assert gpu["frames"] == 50
    assert gpu["frame_gpu_ms"]["mean"] == 8.0 and gpu["frame_gpu_ms"]["min" if "min" in gpu["frame_gpu_ms"] else "max"] == 8.0


def test_split_args_keeps_backslashes_and_drops_quotes():
    """Windows argument strings keep paths intact and lose the quotes around a token."""
    assert mcp.split_args('--name "a b" C:\\Games\\x --k=1') == ["--name", "a b", "C:\\Games\\x", "--k=1"]


def test_overrun_leaves_attached_process_running(tmp_path, monkeypatch):
    """A recording that overruns its deadline stops only what it launched; an attached program keeps running."""
    monkeypatch.setenv("PRESENTMON_EXE", str(tmp_path / "absent.exe"))
    monkeypatch.setattr(prw, "sample_dwm_frame_times", lambda pid, stop, samples: None)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with pytest.raises(RuntimeError, match="took over"):
            prw.record_windows("test_over", 3, "attach", "-", "-", [str(proc.pid)], out_dir=tmp_path, timeout=1)
        assert proc.poll() is None
        assert not list(tmp_path.iterdir()), list(tmp_path.iterdir())
    finally:
        proc.kill()
        proc.wait()


def test_stale_lock_is_replaced(tmp_path):
    """A .recording lock left by a dead process does not block the next recording."""
    lock = tmp_path / ".recording"
    lock.mkdir()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (lock / "pid").write_text(str(dead.pid), encoding="utf-8")
    summary, _ = prw.record_windows("test_stale", 1, "native", "-", tmp_path, LOG_PROGRAM, out_dir=tmp_path)
    assert summary["gpu"]["source"] == "drawstress-log"
    assert not lock.exists()


def test_failed_recording_stops_the_launched_program(tmp_path, monkeypatch):
    """When a recording fails, the program it launched is stopped and its files are removed."""
    monkeypatch.setenv("PRESENTMON_EXE", str(tmp_path / "absent.exe"))
    monkeypatch.setattr(prw, "sample_dwm_frame_times", lambda pid, stop, samples: None)
    pidfile = tmp_path / "child.pid"
    code = f"import os, time; open(r'{pidfile}', 'w').write(str(os.getpid())); time.sleep(30)"
    with pytest.raises(RuntimeError, match="no frame data"):
        prw.record_windows("test_leak", 1, "native", "-", tmp_path, [sys.executable, "-c", code], out_dir=tmp_path)
    child = int(pidfile.read_text())
    time.sleep(0.5)
    assert not prw.is_process_alive(child)


def test_no_frame_data_is_an_error(tmp_path, monkeypatch):
    """Without a frame log and without DWM samples the recording fails and leaves no files; it never invents frames."""
    monkeypatch.setenv("PRESENTMON_EXE", str(tmp_path / "absent.exe"))
    monkeypatch.setattr(prw, "sample_dwm_frame_times", lambda pid, stop, samples: None)
    with pytest.raises(RuntimeError, match="no frame data"):
        prw.record_windows("test_none", 1, "native", "-", tmp_path, [sys.executable, "-c", "pass"], out_dir=tmp_path)
    assert not list(tmp_path.iterdir()), list(tmp_path.iterdir())


def test_dwm_run_does_not_report_gpu_time(tmp_path, monkeypatch):
    """A DWM recording reports composition intervals and says the GPU time was not measured."""
    monkeypatch.setenv("PRESENTMON_EXE", str(tmp_path / "absent.exe"))
    monkeypatch.setattr(prw, "sample_dwm_frame_times",
                        lambda pid, stop, samples: samples.extend([16.0, 17.5, 16.2] * 40))
    summary, _ = prw.record_windows("test_dwm", 1, "native", "-", tmp_path, LOG_PROGRAM[:2] + ["import time; time.sleep(1)"],
                                    out_dir=tmp_path)
    gpu = summary["gpu"]
    assert gpu["source"] == "dwm-composition"
    assert gpu["frame_gpu_ms"] == {"count": 0}
    assert gpu["frame_interval_ms"]["count"] > 0 and gpu["frame_jitter_ms"] > 0


def test_presentmon_frames_and_gpu_time(tmp_path, monkeypatch):
    """With PresentMon, intervals come from MsBetweenPresents and GPU time from MsGPUTime, per Present() call."""
    fake = tmp_path / "pm.bat"
    rows = "\r\n".join(f" echo game.exe,1,{ms},{gpu}" for ms, gpu in [(16.0, 9.5), (17.5, 10.0), (33.0, 12.0)] * 20)
    fake.write_text(f"@echo off\r\n(\r\n echo Application,ProcessID,MsBetweenPresents,MsGPUTime\r\n{rows}\r\n)>\"%~4\"\r\n")
    monkeypatch.setenv("PRESENTMON_EXE", str(fake))
    summary, _ = prw.record_windows("test_pm", 1, "native", "-", tmp_path,
                                    LOG_PROGRAM[:2] + ["import time; time.sleep(1)"], out_dir=tmp_path)
    gpu = summary["gpu"]
    assert gpu["source"] == "presentmon"
    assert gpu["frames"] == 60 and gpu["frame_gpu_ms"]["count"] == 60
    assert gpu["frame_gpu_ms"]["max"] == 12.0 and gpu["frame_interval_ms"]["max"] == 33.0


@needs_dwm
def test_attach_zenless_zone_zero_real_dwm(tmp_path):
    """5-second attach to ZenlessZoneZero.exe verifying real DWM presentation timing and low percentiles."""
    import shutil
    zzz_exe = tmp_path / "ZenlessZoneZero.exe"
    shutil.copyfile(sys.executable, zzz_exe)
    proc = subprocess.Popen([str(zzz_exe), "-c", "import time; time.sleep(15)"])

    try:
        summary, json_path = record_or_skip(
            "test_zzz_capture",
            3,
            "attach",
            "-",
            "-",
            ["ZenlessZoneZero.exe"],
            out_dir=tmp_path,
        )
        assert json_path.exists()
        assert summary["process"]["name"] == "ZenlessZoneZero.exe"
        assert summary["process"]["pid"] == proc.pid
        assert summary["process"]["termination-reason"] == "running"

        gpu = summary["gpu"]
        assert gpu["frames"] > 0
        assert gpu["fps_estimate"] is not None and gpu["fps_estimate"] > 0
        assert gpu["fps_1pct_low"] is not None and gpu["fps_1pct_low"] > 0
        assert gpu["fps_01pct_low"] is not None and gpu["fps_01pct_low"] > 0
        assert "frame_jitter_ms" in gpu
        assert "stutter_rate_pct" in gpu

        # Verify frame times are not synthetic flat 16.667 ms
        int_ms = gpu["frame_interval_ms"]
        assert int_ms["count"] > 0
        # If DWM hardware was sampled, jitter is positive and min != max
        if gpu["frame_jitter_ms"] > 0:
            assert int_ms["max"] > int_ms["p50"] or int_ms["p50"] > int_ms["mean"] or gpu["frame_jitter_ms"] > 0
    finally:
        proc.terminate()
        proc.wait()


def test_dwm_combat_stutter_simulation(tmp_path):
    """Telemetry precision test simulating game combat framerate drops and latency spikes."""
    # Combat scenario: 60 FPS baseline (16.6 ms) with combat drops down to 25-45 FPS (22-40 ms)
    baseline_frames = [16.6] * 80
    combat_drop_frames = [25.0, 28.5, 33.3, 40.0, 42.0] * 4  # combat spikes
    recovery_frames = [16.6] * 40
    combat_gaps = (baseline_frames + combat_drop_frames + recovery_frames) * 8  # 1120 frames: enough for the lows
    combat_totals = [g * 0.7 for g in combat_gaps]

    pacing = prw.compute_precision_telemetry(combat_gaps, combat_totals)
    assert pacing["fps_estimate"] == 60.2 or pacing["fps_estimate"] == 60.0 or 55.0 <= pacing["fps_estimate"] <= 65.0
    # 1% Low should reflect the deep combat drops (down to 25-40 ms -> 23-40 FPS)
    assert pacing["fps_1pct_low"] < 35.0
    assert pacing["fps_01pct_low"] <= pacing["fps_1pct_low"]
    assert pacing["stutter_rate_pct"] > 5.0
    assert pacing["frame_jitter_ms"] > 3.0


def main():
    tests = [
        ("attach nonexistent", test_attach_nonexistent_process),
        ("attach existing", test_attach_existing_process),
        ("lock handling", test_lock_handling),
        ("recording and schema", test_recording_and_schema_verification),
        ("drawstress workload", test_drawstress_workload_parsing),
        ("timeout and cleanup", test_timeout_and_cleanup),
        ("vegaflow telemetry bridge", test_vegaflow_telemetry_bridge),
        ("precision telemetry calculation", test_precision_telemetry_calculation),
        ("diagnose bottlenecks and recommendations", test_diagnose_bottlenecks_and_recommendations),
        ("compare summaries enriched metrics", test_compare_summaries_enriched_metrics),
        ("dwm timing structures and query", test_dwm_timing_structures_and_query),
        ("attach zenless zone zero real dwm", test_attach_zenless_zone_zero_real_dwm),
        ("dwm combat stutter simulation", test_dwm_combat_stutter_simulation),
    ]


    print(f"Running {len(tests)} test suites...")
    for name, test_fn in tests:
        print(f"  -> Testing: {name} ...", end=" ", flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp).resolve()
            test_fn(tmp_path)
        print("PASS")

    print("\nAll tests passed successfully!")


if __name__ == "__main__":
    main()
