"""Native Windows recording engine for metal-gpu-trace.

Records Windows programs, workloads (such as bgfx 17-drawstress with D3D11 / D3D12),
and attached processes, producing telemetry CSVs and a summary JSON matching the schema
expected by perf_report.py and perf_compare.
"""
import collections
import csv
import ctypes
from ctypes import wintypes
import json
import os
import pathlib
import platform
import re
import shlex
import statistics
import subprocess
import threading
import time


SHORT_US = (10, 25, 50, 100, 250, 500, 1000)

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001


class UNSIGNED_RATIO(ctypes.Structure):
    _fields_ = [
        ("uiNumerator", wintypes.UINT),
        ("uiDenominator", wintypes.UINT),
    ]


class DWM_TIMING_INFO(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("rateRefresh", UNSIGNED_RATIO),
        ("qpcRefreshPeriod", ctypes.c_uint64),
        ("rateCompose", UNSIGNED_RATIO),
        ("qpcVBlank", ctypes.c_uint64),
        ("cRefresh", ctypes.c_uint64),
        ("cDXRefresh", wintypes.UINT),
        ("qpcCompose", ctypes.c_uint64),
        ("cFrame", ctypes.c_uint64),
        ("cDXPresent", wintypes.UINT),
        ("cRefreshFrame", ctypes.c_uint64),
        ("cFrameSubmitted", ctypes.c_uint64),
        ("cDXPresentSubmitted", wintypes.UINT),
        ("cFrameConfirmed", ctypes.c_uint64),
        ("cDXPresentConfirmed", wintypes.UINT),
        ("cRefreshConfirmed", ctypes.c_uint64),
        ("cDXRefreshConfirmed", wintypes.UINT),
        ("cFramesLate", ctypes.c_uint64),
        ("cFramesOutstanding", wintypes.UINT),
        ("cFrameDisplayed", ctypes.c_uint64),
        ("qpcFrameDisplayed", ctypes.c_uint64),
        ("cRefreshFrameDisplayed", ctypes.c_uint64),
        ("cFrameComplete", ctypes.c_uint64),
        ("qpcFrameComplete", ctypes.c_uint64),
        ("cFramePending", ctypes.c_uint64),
        ("qpcFramePending", ctypes.c_uint64),
        ("cFramesDropped", ctypes.c_uint64),
        ("cFramesMissed", ctypes.c_uint64),
        ("cRefreshAdjustment", ctypes.c_uint64),
        ("cDXPresentDisplayed", wintypes.UINT),
        ("cDXRefreshDisplayed", wintypes.UINT),
        ("cDXPresentComplete", wintypes.UINT),
        ("cDXRefreshComplete", wintypes.UINT),
        ("cDXPresentDropped", wintypes.UINT),
        ("cDXRefreshDropped", wintypes.UINT),
        ("cFramesInvalid", ctypes.c_uint64),
        ("cFullFrame", ctypes.c_uint64),
        ("cFramesFetched", ctypes.c_uint64),
        ("cFramesRendered", ctypes.c_uint64),
        ("cFramesDisplayed_Unused", ctypes.c_uint64),
        ("cFramesComplete_Unused", ctypes.c_uint64),
        ("cLockCount", wintypes.UINT),
        ("extra_reserved", ctypes.c_byte * 12),
    ]


class DWM_TIMING_INFO_LEGACY(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("rateRefresh", UNSIGNED_RATIO),
        ("qpcRefreshPeriod", ctypes.c_uint64),
        ("rateCompose", UNSIGNED_RATIO),
        ("qpcVBlank", ctypes.c_uint64),
        ("cFrame", ctypes.c_uint64),
        ("cDXRefresh", wintypes.UINT),
        ("qpcCompose", ctypes.c_uint64),
        ("cFrameSubmitted", ctypes.c_uint64),
        ("cDXPresentSubmitted", wintypes.UINT),
        ("cFrameConfirmed", ctypes.c_uint64),
        ("cDXPresentConfirmed", wintypes.UINT),
        ("cRefreshConfirmed", ctypes.c_uint64),
        ("cDXRefreshConfirmed", wintypes.UINT),
        ("cFramesLate", ctypes.c_uint64),
        ("cFramesOutstanding", wintypes.UINT),
        ("cFrameDisplayed", ctypes.c_uint64),
        ("qpcFrameDisplayed", ctypes.c_uint64),
        ("cRefreshFrameDisplayed", ctypes.c_uint64),
        ("cFrameComplete", ctypes.c_uint64),
        ("qpcFrameComplete", ctypes.c_uint64),
        ("cFramePending", ctypes.c_uint64),
        ("qpcFramePending", ctypes.c_uint64),
        ("cFramesDropped", ctypes.c_uint64),
        ("cFramesMissed", ctypes.c_uint64),
        ("cRefreshAdjustment", ctypes.c_uint64),
    ]



class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def system_ram_bytes():
    """Returns the total physical RAM in bytes."""
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return stat.ullTotalPhys
    except Exception:
        pass
    return 0


def _enrich_device_with_vegaflow(device, vf_data):
    """Enriches device dict with VegaFlow low-level hardware telemetry."""
    if not isinstance(vf_data, dict):
        return

    # 1. CPU Architecture / detailed model (e.g. Zen 2 Renoir 7nm)
    cpu_info = vf_data.get("cpu", {})
    cpu_arch = (
        vf_data.get("cpu_architecture")
        or cpu_info.get("microarchitecture")
        or cpu_info.get("brand_string")
    )
    if cpu_arch:
        device["cpu_architecture"] = str(cpu_arch)

    # 2. GPU Architecture / UMA topology (e.g. Vega 6 / GCN 5.0, bus dual-channel 128-bit)
    if "gpu_architecture" in vf_data:
        device["gpu_architecture"] = str(vf_data["gpu_architecture"])
    else:
        gpu_info = vf_data.get("gpu", {})
        ram_info = vf_data.get("ram", {})
        adapter_name = gpu_info.get("adapter_name", "")
        arch_desc = gpu_info.get("architecture", "")

        # Extract specific GPU silicon tag e.g. "Vega 6 / GCN 5.0"
        m_gpu = re.search(r"\(([^)]*(?:Vega|GCN|RDNA|Graphics)[^)]*)\)", adapter_name, re.IGNORECASE)
        gpu_tag = m_gpu.group(1).strip() if m_gpu else (adapter_name or arch_desc)

        # Extract bus and channel topology e.g. "bus dual-channel 128-bit"
        channel_top = ram_info.get("channel_topology", "")
        m_ram = re.search(r"([A-Za-z0-9\-]+-Channel)\s*\((?:.*?)?(\d+-bit)", channel_top, re.IGNORECASE)
        if m_ram:
            bus_tag = f"bus {m_ram.group(1).lower()} {m_ram.group(2).lower()}"
        elif "dual-channel" in channel_top.lower():
            bus_tag = "bus dual-channel 128-bit" if ram_info.get("memory_bus_width_bits") == 128 else "bus dual-channel"
        elif "single-channel" in channel_top.lower():
            bus_tag = "bus single-channel 64-bit" if ram_info.get("memory_bus_width_bits") == 64 else "bus single-channel"
        elif ram_info.get("memory_bus_width_bits"):
            bus_tag = f"bus {ram_info.get('memory_bus_width_bits')}-bit"
        else:
            bus_tag = ""

        if gpu_tag and bus_tag:
            device["gpu_architecture"] = f"{gpu_tag}, {bus_tag}"
        elif gpu_tag:
            device["gpu_architecture"] = gpu_tag
        elif bus_tag:
            device["gpu_architecture"] = bus_tag


def collect_device_info(daemon_path=None):
    """Collects system and hardware device info, optionally enriched via VegaFlow telemetry.

    Queries VegaFlow low-level hardware telemetry if vegaflow_daemon.exe is available,
    enriching the device block with detailed CPU/GPU architecture while preserving
    standard schema fields. Gracefully falls back to native Win32 on any failure.
    """
    device = {
        "platform": "Windows",
        "model": platform.processor(),
        "memory-size": str(system_ram_bytes()),
        "os-version": platform.version(),
    }

    candidates = []
    if daemon_path is not None:
        candidates.append(pathlib.Path(daemon_path))
    candidates.append(pathlib.Path("../build/vegaflow_daemon.exe"))
    candidates.append(pathlib.Path("build/vegaflow_daemon.exe"))
    try:
        script_dir = pathlib.Path(__file__).resolve().parent
        candidates.append(script_dir.parent / "build" / "vegaflow_daemon.exe")
        candidates.append(script_dir / "build" / "vegaflow_daemon.exe")
    except Exception:
        pass

    daemon_exe = None
    for cand in candidates:
        try:
            if cand.is_file():
                daemon_exe = cand.resolve()
                break
        except Exception:
            continue

    if daemon_exe:
        try:
            res = subprocess.run(
                [str(daemon_exe), "--system-info"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                vf_data = json.loads(res.stdout)
                _enrich_device_with_vegaflow(device, vf_data)
        except Exception:
            # Fall back transparently to native Win32 device info on any error or timeout
            pass

    return device


def list_running_processes():
    """Returns a list of (pid, exe_name) for running processes on Windows."""
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (-1, 0):
        return []
    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
    procs = []
    try:
        if kernel32.Process32First(snapshot, ctypes.byref(pe)):
            while True:
                exe = pe.szExeFile.decode("mbcs", errors="ignore")
                procs.append((pe.th32ProcessID, exe))
                if not kernel32.Process32Next(snapshot, ctypes.byref(pe)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return procs


def get_process_rss_kib(pid):
    """Returns working set memory of process `pid` in KiB (bytes // 1024)."""
    if pid <= 0:
        return 0
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return 0
    try:
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        fn = getattr(kernel32, "K32GetProcessMemoryInfo", None)
        if not fn:
            fn = ctypes.windll.psapi.GetProcessMemoryInfo
        if fn(handle, ctypes.byref(pmc), pmc.cb):
            return int(pmc.WorkingSetSize // 1024)
    except Exception:
        pass
    finally:
        kernel32.CloseHandle(handle)
    return 0


def is_process_alive(pid):
    """Returns True if process `pid` is currently running."""
    if pid <= 0:
        return False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == 259  # STILL_ACTIVE
        return True
    except Exception:
        return False
    finally:
        kernel32.CloseHandle(handle)


def sample_dwm_frame_times(pid, stop_event, frame_samples):
    """High-frequency (1ms interval) sampler monitoring Windows DWM composition and QPC.

    Monitors dti.cFrame increment and QueryPerformanceCounter (QPC):
      dt_ms = (cur_qpc - last_qpc) * 1000.0 / qpc_freq
      frame_dt = dt_ms / (dti.cFrame - last_cFrame)
    and collects real empirical presentation intervals while the attached process is active.
    """
    try:
        kernel32 = ctypes.windll.kernel32
        dwmapi = getattr(ctypes.windll, "dwmapi", None)
        if not dwmapi or not hasattr(dwmapi, "DwmGetCompositionTimingInfo"):
            return

        freq = ctypes.c_int64()
        if not kernel32.QueryPerformanceFrequency(ctypes.byref(freq)) or freq.value <= 0:
            return
        qpc_freq = float(freq.value)

        # Baseline query
        dti = DWM_TIMING_INFO()
        dti.cbSize = ctypes.sizeof(DWM_TIMING_INFO)
        hr = dwmapi.DwmGetCompositionTimingInfo(0, ctypes.byref(dti))
        if hr != 0:
            dti = DWM_TIMING_INFO_LEGACY()
            dti.cbSize = ctypes.sizeof(DWM_TIMING_INFO_LEGACY)
            hr = dwmapi.DwmGetCompositionTimingInfo(0, ctypes.byref(dti))
            if hr != 0:
                return

        last_cFrame = dti.cFrame
        last_vblank = getattr(dti, "qpcVBlank", 0)
        cur_qpc = ctypes.c_int64()
        kernel32.QueryPerformanceCounter(ctypes.byref(cur_qpc))
        last_qpc = cur_qpc.value
        alive_check_tick = 0

        while not stop_event.is_set():
            time.sleep(0.001)

            alive_check_tick += 1
            if alive_check_tick >= 100:
                alive_check_tick = 0
                if pid and not is_process_alive(pid):
                    break

            kernel32.QueryPerformanceCounter(ctypes.byref(cur_qpc))
            hr = dwmapi.DwmGetCompositionTimingInfo(0, ctypes.byref(dti))
            if hr == 0 and dti.cFrame > last_cFrame:
                cur_vblank = getattr(dti, "qpcVBlank", 0)
                if cur_vblank > 0 and cur_vblank == last_vblank:
                    continue
                delta_frames = max(1, dti.cFrame - last_cFrame) if cur_vblank == 0 else 1
                dt_ms = (cur_qpc.value - last_qpc) * 1000.0 / qpc_freq
                if dt_ms > 0:
                    frame_dt = dt_ms / delta_frames
                    for _ in range(delta_frames):
                        frame_samples.append(frame_dt)
                last_cFrame = dti.cFrame
                last_vblank = cur_vblank
                last_qpc = cur_qpc.value
    except Exception:
        pass



def find_attached_process(target):
    """Finds a running process by numerical PID or executable name substring.

    Raises RuntimeError with 'no running process matches <target>' if not found.
    """
    target_str = str(target).strip()
    running = list_running_processes()
    if target_str.isdigit():
        pid = int(target_str)
        match = next((p for p in running if p[0] == pid), None)
        if match:
            return match[0], match[1]
        # Check if handle can be opened directly
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return pid, f"pid_{pid}"
        raise RuntimeError(f"no running process matches {target_str}")

    current_pid = os.getpid()
    matches = [p for p in running if target_str.lower() in p[1].lower() and p[0] != current_pid]
    if not matches:
        raise RuntimeError(f"no running process matches {target_str}")
    # Pick the newest / highest PID
    matches.sort(key=lambda p: p[0])
    return matches[-1][0], matches[-1][1]


def public_arguments(arguments):
    """Returns a command line with each absolute path cut to its file name, so summaries can be shared."""
    def clean(arg):
        if arg.startswith("/") or re.match(r"^[a-zA-Z]:[\\/]", arg):
            return pathlib.Path(arg).name
        return arg
    return " ".join(clean(a) for a in (arguments or "").split())


def stats(values):
    """Returns count, mean, median, 95th percentile and maximum of `values`, rounded to microseconds when in ms."""
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": round(statistics.fmean(ordered), 3),
        "p50": round(ordered[len(ordered) // 2], 3),
        "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "max": round(ordered[-1], 3),
    }


def compute_precision_telemetry(gaps, totals):
    """Computes professional telemetry metrics: 1% Low, 0.1% Low, stutter rate, jitter, and throttling drift.

    Args:
        gaps: List of frame interval durations in milliseconds (from start-to-start delta).
        totals: List of GPU execution durations in milliseconds per frame.
    """
    if not gaps:
        return {
            "fps_estimate": None,
            "fps_1pct_low": None,
            "fps_01pct_low": None,
            "stutter_rate_pct": 0.0,
            "frame_jitter_ms": 0.0,
            "throttling_analysis": {
                "thermal_throttling_detected": False,
                "fps_initial": None,
                "fps_final": None,
                "fps_drift_pct": 0.0,
            },
        }

    med = statistics.median(gaps)
    fps_estimate = round(1000.0 / med, 1) if med > 0 else None

    ordered = sorted(gaps)
    p99_idx = min(len(ordered) - 1, int(len(ordered) * 0.99))
    p99 = ordered[p99_idx]
    fps_1pct_low = round(1000.0 / p99, 1) if p99 > 0 else None

    p999_idx = min(len(ordered) - 1, int(len(ordered) * 0.999))
    p999 = ordered[p999_idx]
    fps_01pct_low = round(1000.0 / p999, 1) if p999 > 0 else None

    stutter_count = sum(1 for g in gaps if g > 1.5 * med) if med > 0 else 0
    stutter_rate_pct = round((stutter_count / len(gaps)) * 100.0, 2)

    frame_jitter_ms = round(statistics.pstdev(gaps), 3) if len(gaps) > 1 else 0.0

    if len(gaps) >= 5:
        k = max(1, int(len(gaps) * 0.20))
        med_init = statistics.median(gaps[:k])
        med_final = statistics.median(gaps[-k:])
        fps_init = round(1000.0 / med_init, 1) if med_init > 0 else None
        fps_fin = round(1000.0 / med_final, 1) if med_final > 0 else None
        drift = round(((fps_init - fps_fin) / fps_init) * 100.0, 1) if (fps_init and fps_fin and fps_init > 0) else 0.0

        k_tot = max(1, int(len(totals) * 0.20)) if totals else 0
        gpu_init = statistics.mean(totals[:k_tot]) if k_tot else 0.0
        gpu_final = statistics.mean(totals[-k_tot:]) if k_tot else 0.0
        throttling = bool(drift > 10.0 and gpu_final > gpu_init)
        throttling_analysis = {
            "thermal_throttling_detected": throttling,
            "fps_initial": fps_init,
            "fps_final": fps_fin,
            "fps_drift_pct": drift,
        }
    else:
        throttling_analysis = {
            "thermal_throttling_detected": False,
            "fps_initial": fps_estimate,
            "fps_final": fps_estimate,
            "fps_drift_pct": 0.0,
        }

    return {
        "fps_estimate": fps_estimate,
        "fps_1pct_low": fps_1pct_low,
        "fps_01pct_low": fps_01pct_low,
        "stutter_rate_pct": stutter_rate_pct,
        "frame_jitter_ms": frame_jitter_ms,
        "throttling_analysis": throttling_analysis,
    }


def label_name(label):
    """Returns an encoder label without prefix and trailing index."""
    return re.sub(r" \d+$", "", re.sub(r"^\[\d+\] ", "", label)) or "?"


def encoder_stats(spans, labels):
    """Returns encoder statistics matching perf_report.py schema."""
    encoders, buffers, busy = collections.defaultdict(set), collections.defaultdict(set), collections.Counter()
    for frame, _, duration, encoder, buffer in spans:
        if encoder:
            encoders[frame].add(encoder)
            busy[encoder] += duration
        if buffer:
            buffers[frame].add(buffer)
    us = [ns / 1000 for ns in busy.values()]
    grouped = collections.defaultdict(list)
    for encoder, ns in busy.items():
        grouped[label_name(labels.get(encoder, ""))].append(ns / 1000)
    frames = len({s[0] for s in spans}) or 1
    top = sorted(grouped.items(), key=lambda kv: -sum(kv[1]))[:20]
    return {
        "per_frame": stats([len(e) for e in encoders.values()]),
        "command_buffers_per_frame": stats([len(b) for b in buffers.values()]),
        "encoder_us": stats(us),
        "short_share": {str(cut): (round(sum(u < cut for u in us) / len(us), 3) if us else 0.0) for cut in SHORT_US},
        "by_label": [
            {
                "label": name,
                "per_frame": round(len(v) / frames, 2),
                "total_ms": round(sum(v) / 1000, 3),
                "mean_us": round(statistics.fmean(v), 1),
                "stdev_us": round(statistics.pstdev(v) if len(v) > 1 else 0.0, 1),
            }
            for name, v in top
        ],
    }


def idle_gaps(spans):
    """Returns the time the GPU ran none of the process's work between its first and last interval."""
    ordered = sorted((start, start + duration, frame) for frame, start, duration, _, _ in spans)
    if not ordered:
        return {"idle_ms_per_frame": {"count": 0}, "gaps_over_1ms": 0, "idle_share": 0.0}
    idle = collections.Counter({frame: 0.0 for _, _, frame in ordered})
    gaps = []
    end = ordered[0][1]
    for start, stop, frame in ordered[1:]:
        if start > end:
            gap_ms = (start - end) / 1e6
            gaps.append(gap_ms)
            idle[frame] += gap_ms
        end = max(end, stop)
    whole = (end - ordered[0][0]) / 1e6
    return {
        "idle_ms_per_frame": stats(list(idle.values())),
        "gaps_over_1ms": sum(g > 1 for g in gaps),
        "idle_share": round(sum(gaps) / whole, 3) if whole else 0.0,
    }


def clean_runs(out_dir, keep_runs):
    """Keeps the newest `keep_runs` recordings in `out_dir`."""
    if keep_runs is None or keep_runs < 1:
        return
    json_files = sorted(
        [p for p in out_dir.glob("*.json") if p.name != "baselines.json"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in json_files[keep_runs:]:
        stem = old.stem
        for related in out_dir.glob(f"{stem}.*"):
            try:
                related.unlink()
            except OSError:
                pass


def kill_process_tree(pid):
    """Terminates process `pid` and all its descendants forcibly."""
    if pid <= 0:
        return
    children = []
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot not in (-1, 0):
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        try:
            if kernel32.Process32First(snapshot, ctypes.byref(pe)):
                while True:
                    if pe.th32ParentProcessID == pid:
                        children.append(pe.th32ProcessID)
                    if not kernel32.Process32Next(snapshot, ctypes.byref(pe)):
                        break
        finally:
            kernel32.CloseHandle(snapshot)
    for cpid in children:
        kill_process_tree(cpid)
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if handle:
        try:
            kernel32.TerminateProcess(handle, 1)
        finally:
            kernel32.CloseHandle(handle)
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=0.5)
    except Exception:
        pass


def record_windows(label, seconds, wine, prefix, workdir, command, program_env="", out_dir=None, timeout=None):
    """Records a native Windows program, drawstress workload, or attached process.

    Returns (summary_dict, json_path).
    """
    if not re.match(r"^[A-Za-z0-9._-]+$", label):
        raise ValueError("label may hold only letters, digits, '.', '_' and '-'")
    seconds = int(seconds)
    if seconds < 1 or seconds > 3600:
        raise ValueError("seconds must be 1 to 3600")

    if out_dir is None:
        out_str = os.environ.get("PERF_OUT") or os.environ.get("METAL_TRACE_OUT") or "perf-runs"
        out_dir = pathlib.Path(out_str).resolve()
    else:
        out_dir = pathlib.Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Concurrency lock
    lock_path = out_dir / ".recording"
    lock_acquired = False
    try:
        lock_path.mkdir(exist_ok=False)
        lock_acquired = True
    except FileExistsError:
        raise RuntimeError(f"another recording is running ({lock_path}); remove it if none is")

    name = f"{label}_{time.strftime('%Y%m%d-%H%M%S')}"
    deadline_limit = timeout if timeout is not None else seconds * 10 + 120

    proc = None
    pid = None
    proc_name = ""
    args_str = ""
    is_attach = (wine == "attach")

    try:
        if is_attach:
            target = command[0] if isinstance(command, (list, tuple)) else str(command)
            pid, proc_name = find_attached_process(target)
            args_str = str(target)
        else:
            # Launch program
            env = os.environ.copy()
            # Parse program_env and PERF_ENV
            for pair in (program_env or "").split():
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    env[k] = v
            if "PERF_ENV" in os.environ:
                for pair in os.environ["PERF_ENV"].split():
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        env[k] = v

            # Workload drawstress integration: pass DRAWSTRESS_LOG
            drawstress_log = out_dir / f"{name}.drawstress.log"
            env["DRAWSTRESS_LOG"] = str(drawstress_log)

            if isinstance(command, (list, tuple)):
                cmd_list = [str(c) for c in command]
            else:
                cmd_list = shlex.split(str(command), posix=False)

            cwd = str(workdir) if workdir and str(workdir) != "-" else None
            proc = subprocess.Popen(cmd_list, cwd=cwd, env=env)
            pid = proc.pid
            proc_name = pathlib.Path(cmd_list[0]).name
            args_str = " ".join(cmd_list)

        # High-frequency presentation & frame timing sampler for attached processes
        dwm_samples = []
        dwm_stop_event = threading.Event()
        dwm_thread = None

        dwm_thread = threading.Thread(
            target=sample_dwm_frame_times,
            args=(pid, dwm_stop_event, dwm_samples),
            daemon=True,
        )
        dwm_thread.start()

        # RSS Sampling
        rss_csv_path = out_dir / f"{name}.rss.csv"
        with open(rss_csv_path, "w", newline="", encoding="utf-8") as f_rss:
            f_rss.write("time_s,rss_kib\n")

        start_mono = time.monotonic()
        t = 0
        rss_samples = []
        timed_out = False

        while t <= seconds:
            now_mono = time.monotonic()
            if (now_mono - start_mono) > deadline_limit:
                timed_out = True
                break

            rss_kib = get_process_rss_kib(pid)
            rss_samples.append(rss_kib)
            with open(rss_csv_path, "a", newline="", encoding="utf-8") as f_rss:
                f_rss.write(f"{t},{rss_kib}\n")

            if not is_attach and proc.poll() is not None:
                # Process exited naturally before duration expired
                break

            t += 1
            if t > seconds:
                break

            target_time = start_mono + t
            sleep_sec = target_time - time.monotonic()
            if sleep_sec > 0:
                time.sleep(sleep_sec)

        if dwm_thread is not None:
            dwm_stop_event.set()
            dwm_thread.join(timeout=1.0)


        # Check deadline overrun
        if timed_out or (time.monotonic() - start_mono) > deadline_limit:
            # Terminate tree forcibly
            kill_process_tree(pid)
            if proc:
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    pass
            # Clean partial files
            for p in out_dir.glob(f"{name}*"):
                try:
                    p.unlink()
                except OSError:
                    pass
            raise RuntimeError(f"the recording took over {deadline_limit} s and was stopped; nothing was saved")

        # Duration complete: if launched, terminate process
        if not is_attach and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                kill_process_tree(pid)
                proc.kill()
                proc.wait()
            kill_process_tree(pid)

        elapsed_duration = max(0.001, time.monotonic() - start_mono)

        # Data generation
        drawstress_log_path = out_dir / f"{name}.drawstress.log"
        entries = []
        if drawstress_log_path.exists():
            try:
                content = drawstress_log_path.read_text(encoding="utf-8", errors="replace")
                pattern = re.compile(r"dim\s+(\d+)\s+draws\s+(\d+)\s+frame_us\s+(\d+)\s+frames\s+(\d+)")
                for line in content.splitlines():
                    m = pattern.search(line)
                    if m:
                        entries.append({
                            "dim": int(m.group(1)),
                            "draws": int(m.group(2)),
                            "frame_us": int(m.group(3)),
                            "frames": int(m.group(4)),
                        })
            except OSError:
                pass

        frames_data = []
        spans = []
        labels = {}
        frame_idx = 0
        current_time_ms = 0.0

        if entries:
            for entry in entries:
                f_us = entry["frame_us"]
                gpu_ms = f_us / 1e6 if f_us > 1_000_000 else f_us / 1000.0
                if gpu_ms <= 0:
                    gpu_ms = 0.001
                num_frames = entry["frames"]
                for _ in range(num_frames):
                    frame_idx += 1
                    start_ms = current_time_ms
                    current_time_ms += gpu_ms
                    frames_data.append({
                        "frame": frame_idx,
                        "start_ms": start_ms,
                        "gpu_ms_draw": gpu_ms,
                        "gpu_ms_total": gpu_ms,
                    })
                    enc_id = f"enc_{frame_idx}"
                    cmd_id = f"cmd_{frame_idx}"
                    spans.append((frame_idx, int(start_ms * 1e6), int(gpu_ms * 1e6), enc_id, cmd_id))
                    labels[enc_id] = "draw"
        elif dwm_samples:
            # DWM composition intervals of the whole desktop; GPU time per frame is not measured
            for dt in dwm_samples:
                frame_idx += 1
                frames_data.append({
                    "frame": frame_idx,
                    "start_ms": current_time_ms,
                    "gpu_ms_draw": None,
                    "gpu_ms_total": None,
                })
                current_time_ms += dt
        else:
            rss_csv_path.unlink(missing_ok=True)
            raise RuntimeError(
                "no frame data: the program wrote no DRAWSTRESS_LOG and DWM gave no samples "
                "(DwmGetCompositionTimingInfo needs the interactive desktop session, not SSH or a service)"
            )

        # Write frames.csv
        frames_csv_path = out_dir / f"{name}.frames.csv"
        with open(frames_csv_path, "w", newline="", encoding="utf-8") as f_frames:
            writer = csv.writer(f_frames)
            writer.writerow(["frame", "start_ms", "gpu_ms_draw", "gpu_ms_total"])
            for row in frames_data:
                writer.writerow([row["frame"], round(row["start_ms"], 3),
                                 "" if row["gpu_ms_draw"] is None else round(row["gpu_ms_draw"], 4),
                                 "" if row["gpu_ms_total"] is None else round(row["gpu_ms_total"], 4)])

        # Statistics computation
        totals = [f["gpu_ms_total"] for f in frames_data if f["gpu_ms_total"] is not None]
        starts = [f["start_ms"] for f in frames_data]
        gaps = [round(b - a, 4) for a, b in zip(starts, starts[1:]) if b > a]


        pacing = compute_precision_telemetry(gaps, totals)

        gpu_stats = {
            "intervals": len(frames_data),
            "frames": len(frames_data),
            "frame_gpu_ms": stats(totals),
            "per_channel_ms": {"draw": stats(totals)},
            "frame_interval_ms": stats(gaps),
            "fps_estimate": pacing["fps_estimate"],
            "fps_1pct_low": pacing["fps_1pct_low"],
            "fps_01pct_low": pacing["fps_01pct_low"],
            "stutter_rate_pct": pacing["stutter_rate_pct"],
            "frame_jitter_ms": pacing["frame_jitter_ms"],
            "throttling_analysis": pacing["throttling_analysis"],
            "source": "drawstress-log" if entries else "dwm-composition",
        }

        enc_stats = encoder_stats(spans, labels)
        idle_stats = idle_gaps(spans)

        rss_mib = [k / 1024.0 for k in rss_samples if k > 0]
        process_rss_mib = stats(rss_mib) if rss_mib else {"count": 0}

        summary = {
            "label": label,
            "trace": f"{name}.trace",
            "process": {
                "name": proc_name,
                "pid": pid,
                "arguments": public_arguments(args_str),
                "termination-reason": "exit" if not is_attach else "running",
            },
            "device": collect_device_info(),
            "template": "Windows Native Trace",
            "duration_s": round(elapsed_duration, 3),
            "missing_tables": [
                "metal-current-allocated-size",
                "metal-application-encoders-list",
                "gpu-performance-state-intervals",
            ],
            "gpu": gpu_stats,
            "encoders": enc_stats,
            "gpu_idle": idle_stats,
            "metal_memory_mib": {"samples": 0},
            "process_rss_mib": process_rss_mib,
            "layer": (
                {"unknown": "an attached process's Wine and prefix are not known", "program_env": program_env}
                if is_attach
                else {"none": "native Metal, no translation layer", "program_env": program_env}
            ),
        }

        json_path = out_dir / f"{name}.json"
        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        # Retention check
        keep_runs_env = os.environ.get("KEEP_RUNS")
        if keep_runs_env and keep_runs_env.isdigit():
            clean_runs(out_dir, int(keep_runs_env))

        return summary, json_path

    finally:
        if lock_acquired and lock_path.exists():
            try:
                lock_path.rmdir()
            except OSError:
                pass


def main():
    import sys
    if len(sys.argv) < 7:
        sys.exit("Usage: python perf_record_windows.py <label> <seconds> <wine|native|attach> <prefix> <workdir> <command...>")
    label = sys.argv[1]
    seconds = int(sys.argv[2])
    wine = sys.argv[3]
    prefix = sys.argv[4]
    workdir = sys.argv[5]
    command = sys.argv[6:]
    summary, path = record_windows(label, seconds, wine, prefix, workdir, command)
    print(f"Saved recording to {path}")
    print(json.dumps({k: summary.get(k) for k in ("gpu", "process_rss_mib")}, indent=2))


if __name__ == "__main__":
    main()
