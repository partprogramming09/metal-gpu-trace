"""The Windows machine for the Windows recording engine: its RAM, description (VegaFlow daemon included), graphics API
and loaded graphics modules, and the GPU engine load of other processes. Part of perf_record_windows, which re-exports
these names."""
import csv
import ctypes
import json
import os
import pathlib
import platform
import re
import subprocess
from ctypes import wintypes

from metal_gpu_trace import metrics


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

    def text(value):
        """Returns the stripped text of a non-blank string, else None (null, blank, numbers and objects are absent)."""
        return value.strip() or None if isinstance(value, str) else None

    def block(name):
        value = vf_data.get(name)
        return value if isinstance(value, dict) else {}

    # 1. CPU Architecture / detailed model (e.g. Zen 2 Renoir 7nm)
    cpu_info = block("cpu")
    cpu_arch = (
        text(vf_data.get("cpu_architecture"))
        or text(cpu_info.get("microarchitecture"))
        or text(cpu_info.get("brand_string"))
    )
    if cpu_arch:
        device["cpu_architecture"] = cpu_arch

    # 2. GPU Architecture / UMA topology (e.g. Vega 6 / GCN 5.0, bus dual-channel 128-bit)
    if text(vf_data.get("gpu_architecture")):
        device["gpu_architecture"] = text(vf_data["gpu_architecture"])
    else:
        gpu_info = block("gpu")
        ram_info = block("ram")
        adapter_name = text(gpu_info.get("adapter_name")) or ""
        arch_desc = text(gpu_info.get("architecture")) or ""

        # Extract specific GPU silicon tag e.g. "Vega 6 / GCN 5.0"
        m_gpu = re.search(r"\(([^)]*(?:Vega|GCN|RDNA|Graphics)[^)]*)\)", adapter_name, re.IGNORECASE)
        gpu_tag = m_gpu.group(1).strip() if m_gpu else (adapter_name or arch_desc)

        # Extract bus and channel topology e.g. "bus dual-channel 128-bit"
        channel_top = text(ram_info.get("channel_topology")) or ""
        width = ram_info.get("memory_bus_width_bits")
        if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
            width = None  # a bool, text or object is not a width
        m_ram = re.search(r"([A-Za-z0-9\-]+-Channel)\s*\((?:.*?)?(\d+-bit)", channel_top, re.IGNORECASE)
        if m_ram:
            bus_tag = f"bus {m_ram.group(1).lower()} {m_ram.group(2).lower()}"
        elif "dual-channel" in channel_top.lower():
            bus_tag = "bus dual-channel 128-bit" if width == 128 else "bus dual-channel"
        elif "single-channel" in channel_top.lower():
            bus_tag = "bus single-channel 64-bit" if width == 64 else "bus single-channel"
        elif width:
            bus_tag = f"bus {width}-bit"
        else:
            bus_tag = ""

        if gpu_tag and bus_tag:
            device["gpu_architecture"] = f"{gpu_tag}, {bus_tag}"
        elif gpu_tag:
            device["gpu_architecture"] = gpu_tag
        elif bus_tag:
            device["gpu_architecture"] = bus_tag


def graphics_api(modules):
    """Returns {"runtime", "translation_layer"} from `modules`, the (file name, loaded from the system folder) pairs of
    the graphics DLLs a process holds: the runtime is the newest Direct3D present (d3d12, d3d11, d3d9), else vulkan, else
    opengl; the layer is `dxvk` (d3d9/d3d11/dxgi loaded from outside the system folder) or `vkd3d-proton` (d3d12 from
    outside it), None for a system copy. An empty list, or None (it could not be read), is `unknown`: never a guess."""
    names = {name.lower(): system for name, system in modules or ()}
    runtime = next((r for r, dll in (("d3d12", "d3d12.dll"), ("d3d11", "d3d11.dll"), ("d3d9", "d3d9.dll"),
                                     ("vulkan", "vulkan-1.dll"), ("opengl", "opengl32.dll")) if dll in names), "unknown")
    layer = None
    if runtime == "d3d12" and names["d3d12.dll"] is False:
        layer = "vkd3d-proton"
    elif runtime in ("d3d11", "d3d9") and names.get(f"{runtime}.dll") is False:
        layer = "dxvk"
    return {"runtime": runtime, "translation_layer": layer}


def loaded_graphics_modules(pid):
    """Returns the (file name, from the system folder) pairs of the graphics DLLs process `pid` has loaded, or None when
    they cannot be read (a protected process, a 32/64-bit mismatch, an exited process). Only the names and that flag
    leave this function, never a path."""
    import ctypes
    from ctypes import wintypes
    try:
        psapi, kernel32 = ctypes.WinDLL("psapi", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes, kernel32.OpenProcess.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                                               ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
        psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
        handle = kernel32.OpenProcess(0x0410, False, pid)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        if not handle:
            return None
        try:
            mods, needed = (wintypes.HMODULE * 2048)(), wintypes.DWORD()
            if not psapi.EnumProcessModulesEx(handle, mods, ctypes.sizeof(mods), ctypes.byref(needed), 0x03):  # LIST_MODULES_ALL
                return None
            system = os.environ.get("SystemRoot", r"C:\Windows").lower()
            found, buffer = [], ctypes.create_unicode_buffer(1024)
            for module in mods[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
                if psapi.GetModuleFileNameExW(handle, module, buffer, len(buffer)):
                    path = pathlib.PureWindowsPath(buffer.value)
                    if path.name.lower() in GRAPHICS_DLLS:
                        found.append((path.name, str(path.parent).lower().startswith(system)))
            return found
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError, ctypes.ArgumentError):
        return None


GRAPHICS_DLLS = frozenset(("d3d9.dll", "d3d11.dll", "d3d12.dll", "dxgi.dll", "vulkan-1.dll", "opengl32.dll"))
GPU_ENGINE_COUNTER = r"\GPU Engine(*)\Utilization Percentage"


def parse_gpu_engines(text):
    """Returns {pid: percent} from the output of `typeperf "<GPU Engine counter>" -sc 1`: each engine instance of a process
    adds its utilization. {} when the text has no header and a row of values."""
    lines = [line for line in text.splitlines() if line.strip()]
    start = next((i for i, line in enumerate(lines) if line.startswith('"(PDH-CSV')), None)
    if start is None or start + 1 >= len(lines):
        return {}
    heads, values = next(csv.reader([lines[start]])), next(csv.reader([lines[start + 1]]))
    by_pid = {}
    for head, value in zip(heads[1:], values[1:]):
        found = re.search(r"pid_(\d+)_", head)
        try:
            by_pid[int(found.group(1))] = by_pid.get(int(found.group(1)), 0.0) + float(value) if found else 0.0
        except ValueError:
            continue
    return {pid: round(pct, 3) for pid, pct in by_pid.items()}


def gpu_noise(samples, pid):
    """Returns {"flag", "process_busy_pct", "external_pct", "samples"} from `samples` ({pid: percent} per reading): the
    program's mean GPU use and the mean of every other process together; `flag` when the others used
    metrics.NOISY_EXTERNAL_PCT points or more. None without a sample."""
    if not samples:
        return None
    own = sum(s.get(pid, 0.0) for s in samples) / len(samples)
    other = sum(sum(v for k, v in s.items() if k != pid) for s in samples) / len(samples)
    return {"flag": round(other, 1) >= metrics.NOISY_EXTERNAL_PCT, "process_busy_pct": round(own, 1),
            "external_pct": round(other, 1), "samples": len(samples)}


def sample_gpu_engines(stop, samples, every=2.0):
    """Reads the `GPU Engine` counters with typeperf every `every` seconds until `stop` is set, appending one
    {pid: percent} per reading to `samples`. A reading that fails or times out is skipped: no noise value is better than
    a made-up one."""
    while not stop.is_set():
        try:
            out = subprocess.run(["typeperf", GPU_ENGINE_COUNTER, "-sc", "1"], capture_output=True, text=True,
                                 timeout=10, check=False).stdout
            reading = parse_gpu_engines(out)
            if reading:
                samples.append(reading)
        except (OSError, subprocess.SubprocessError):
            pass
        stop.wait(every)


def daemon_names():
    """Returns the file names to look for: vegaflow_daemon.exe and those in METAL_TRACE_DAEMON_NAMES (comma-separated;
    an entry with a path in it, `.` or `..` is ignored, so the variable cannot point outside build/)."""
    extra = [n.strip() for n in os.environ.get("METAL_TRACE_DAEMON_NAMES", "").split(",")]
    return ["vegaflow_daemon.exe"] + [n for n in extra if n and n not in (".", "..") and not set(n) & set("/\\")]


def daemon_candidates(daemon_path=None):
    """Returns where a daemon (see `daemon_names`) may be, in order: the given path, build/ under the working directory
    and its parent, then build/ in the clone root and its parent (the package lives in <clone>/src/metal_gpu_trace)."""
    clone = pathlib.Path(__file__).resolve().parents[2]
    candidates = [pathlib.Path(daemon_path)] if daemon_path is not None else []
    for build in (pathlib.Path("..") / "build", pathlib.Path("build"), clone.parent / "build", clone / "build"):
        candidates += [build / name for name in daemon_names()]
    return candidates


def daemon_info(exe):
    """Returns (data, None) from `exe --system-info`, or (None, reason) with reason `timeout`, `invalid_json` (not JSON,
    or JSON that is not an object) or `missing` (it would not run, exited non-zero or printed nothing)."""
    try:
        res = subprocess.run([str(exe), "--system-info"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=1.0, check=False)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception:
        return None, "missing"
    if res.returncode != 0 or not res.stdout.strip():
        return None, "missing"
    try:
        data = json.loads(res.stdout)
    except ValueError:
        return None, "invalid_json"
    return (data, None) if isinstance(data, dict) else (None, "invalid_json")


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

    candidates = daemon_candidates(daemon_path)

    daemon_exe = None
    for cand in candidates:
        try:
            if cand.is_file():
                daemon_exe = cand.resolve()
                break
        except Exception:
            continue

    if daemon_exe:
        vf_data, reason = daemon_info(daemon_exe)
        if reason:
            device["daemon_info_error"] = reason  # a short word, never the daemon's path
        else:
            _enrich_device_with_vegaflow(device, vf_data)

    return device
