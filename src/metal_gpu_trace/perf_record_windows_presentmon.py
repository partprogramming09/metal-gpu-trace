"""PresentMon for the Windows recording engine: where it is installed, reading its CSV, and the pacing numbers from its
frame intervals. Part of perf_record_windows, which re-exports these names."""
import csv
import os
import pathlib
import shutil
import statistics

from metal_gpu_trace import perf_report


def presentmon_dir(environ=None):
    """Returns the directory presentmon_install saves PresentMon in: %LOCALAPPDATA%\\metal-gpu-trace, read from
    `environ` (the caller's environment) and not from the process's own."""
    environ = os.environ if environ is None else environ
    return pathlib.Path(environ.get("LOCALAPPDATA", "~")).expanduser() / "metal-gpu-trace"


def find_presentmon(environ=None, which=None):
    """Returns the path of Intel's PresentMon console application, or None: $PRESENTMON_EXE, then
    %LOCALAPPDATA%\\metal-gpu-trace\\PresentMon*.exe, then PATH. `environ` and `which` default to the process's own,
    so a caller that passes its own environment (preflight's report, a test) is obeyed."""
    environ = os.environ if environ is None else environ
    which = shutil.which if which is None else which
    explicit = environ.get("PRESENTMON_EXE")
    if explicit:
        return explicit if pathlib.Path(explicit).is_file() else None
    cache = presentmon_dir(environ)
    for candidate in sorted(cache.glob("PresentMon*.exe"), reverse=True):
        return str(candidate)
    return which("PresentMon") or which("PresentMon-x64")


def read_presentmon_csv(path):
    """Returns (intervals_ms, gpu_ms) from a PresentMon CSV: MsBetweenPresents per frame, and MsGPUTime when the
    column exists and is positive (None for a frame without it)."""
    intervals, gpu = [], []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    interval = float(row["MsBetweenPresents"])
                except (KeyError, TypeError, ValueError):
                    continue
                if interval <= 0:
                    continue
                intervals.append(interval)
                try:
                    value = float(row.get("MsGPUTime") or 0)
                except ValueError:
                    value = 0.0
                gpu.append(value if value > 0 else None)
    except OSError:
        pass
    return intervals, gpu


def compute_precision_telemetry(gaps, totals):
    """Returns FPS, 1% and 0.1% lows, stutter rate, jitter and throttling drift from frame intervals (ms, start to
    start) and GPU ms per frame, as perf_report.frame_pacing computes them, with None for what cannot be judged."""
    pacing = perf_report.frame_pacing(gaps, totals)
    med = statistics.median(gaps) if gaps else 0
    fps = round(1000.0 / med, 1) if med > 0 else None
    return {
        "fps_estimate": fps,
        "fps_1pct_low": pacing.get("fps_1pct_low"),
        "fps_01pct_low": pacing.get("fps_01pct_low"),
        "stutter_rate_pct": pacing.get("stutter_rate_pct"),
        "frame_jitter_ms": pacing.get("frame_jitter_ms"),
        "throttling_analysis": pacing.get("throttling_analysis") or {
            "thermal_throttling_detected": None, "fps_initial": fps, "fps_final": fps, "fps_drift_pct": None},
    }
