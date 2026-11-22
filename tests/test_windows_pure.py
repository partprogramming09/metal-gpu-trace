"""Tests of the Windows engine's pure parts (no ctypes, no Windows, no pytest): they run on every system through
tests/run.py. What needs Windows stays in test_perf_record_windows.py."""
from metal_gpu_trace import perf_record_windows as prw


def test_precision_telemetry_calculation():
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
    totals_60 = [10.0] * 1000
    res = prw.compute_precision_telemetry([16.666] * 1000, totals_60)
    assert res["fps_estimate"] == 60.0
    assert res["fps_1pct_low"] == 60.0
    assert res["fps_01pct_low"] == 60.0
    assert res["stutter_rate_pct"] == 0.0
    assert res["frame_jitter_ms"] == 0.0
    assert res["throttling_analysis"]["thermal_throttling_detected"] is False
    assert res["throttling_analysis"]["fps_drift_pct"] == 0.0

    # 2. Injected stutters (40 frames of 40 ms > 1.5 * 16.666 = 25 ms)
    res_stutter = prw.compute_precision_telemetry([16.666] * 960 + [40.0] * 40, totals_60)
    assert res_stutter["stutter_rate_pct"] == 4.0
    assert res_stutter["frame_jitter_ms"] > 0.0
    assert res_stutter["fps_1pct_low"] == round(1000.0 / 40.0, 1)
    assert res_stutter["fps_01pct_low"] == round(1000.0 / 40.0, 1)

    # 3. Thermal throttling drift: first 20 frames 60 FPS / 10 ms GPU, last 20 frames 40 FPS / 18 ms GPU
    gaps_throttle = [16.666] * 20 + [20.0] * 60 + [25.0] * 20
    totals_throttle = [10.0] * 20 + [14.0] * 60 + [18.0] * 20
    res_throttle = prw.compute_precision_telemetry(gaps_throttle, totals_throttle)
    assert res_throttle["throttling_analysis"]["thermal_throttling_detected"] is True
    assert res_throttle["throttling_analysis"]["fps_initial"] == 60.0
    assert res_throttle["throttling_analysis"]["fps_final"] == 40.0
    assert res_throttle["throttling_analysis"]["fps_drift_pct"] == round(((60.0 - 40.0) / 60.0) * 100, 1)


def test_read_presentmon_csv_keeps_valid_frames_and_marks_missing_gpu_time(tmp_path):
    """A row with no usable MsBetweenPresents is dropped; MsGPUTime that is missing or not positive is None."""
    csv_path = tmp_path / "pm.csv"
    csv_path.write_text("\ufeffApplication,MsBetweenPresents,MsGPUTime\r\n"
                        "a.exe,16.0,9.5\r\na.exe,0,5\r\na.exe,x,5\r\na.exe,17.5,\r\na.exe,33.0,-1\r\n"
                        "a.exe,20.0,n/a\r\n", encoding="utf-8")  # a GPU time that is not a number keeps the frame
    assert prw.read_presentmon_csv(csv_path) == ([16.0, 17.5, 33.0, 20.0], [9.5, None, None, None])
    csv_path.write_text("Application,MsGPUTime\r\na.exe,3\r\n")
    assert prw.read_presentmon_csv(csv_path) == ([], [])
    assert prw.read_presentmon_csv(tmp_path / "missing.csv") == ([], [])
