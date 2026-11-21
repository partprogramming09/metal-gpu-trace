"""Windows processes for the Windows recording engine: listing them, their resident memory, finding the one to attach
to and ending a process tree. Part of perf_record_windows, which re-exports these names."""
import ctypes
import os
import subprocess
from ctypes import wintypes


TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001


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
