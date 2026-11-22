"""The machine around a Metal System Trace recording: other GPU load, screen lock, power state and the machine's
description. Part of perf_report, which re-exports these names."""
import math
import re
import subprocess

from metal_gpu_trace import metrics


NOISY_EXTERNAL_PCT = metrics.NOISY_EXTERNAL_PCT  # one threshold, shared with the Windows engine


def noisy_environment(activity, idle):
    """Returns whether something else was loading the GPU while the program recorded, with the numbers behind it:
    `activity` is the AGX counters' summary (`device_pct` covers the whole GPU), `idle` the program's own gpu_idle
    (`idle_share` is the share of its busy window in which its work was absent). The program's share is 100 * (1 -
    idle_share); what the GPU used above that is external, and NOISY_EXTERNAL_PCT points or more is a flag. Returns
    {"flag", "gpu_device_pct_mean", "process_busy_pct", "external_pct"}, or None when an input is missing (no sampler
    file, a Windows run)."""
    try:
        device, share = activity["device_pct"]["mean"], idle["idle_share"]
    except (KeyError, TypeError):
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (device, share)):
        return None
    device, busy = round(device, 1), round(100 * (1 - share), 1)
    external = round(device - busy, 1)
    return {"flag": external >= NOISY_EXTERNAL_PCT, "gpu_device_pct_mean": device, "process_busy_pct": busy,
            "external_pct": external}


def other_processes(by_pid, own_ns):
    """Returns how many other processes used the GPU, their GPU ms and their `share` of all GPU time, the program's own
    `own_ns` included: {count, gpu_ms, share}. `by_pid` maps a pid to its GPU ns. No name is kept, so no program the
    person runs reaches a summary that is shared. As the channels run in parallel, the times can add up to more than
    the recording lasted."""
    other, total = sum(by_pid.values()), own_ns + sum(by_pid.values())
    return {"count": len(by_pid), "gpu_ms": round(other / 1e6, 3), "share": round(other / total, 3) if total else 0.0}


def read_command(argv, env=None):
    """Returns the standard output of one short system command, run with `env` (default: this process's)."""
    return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=10, env=env).stdout


def screen_locked(read=read_command):
    """Returns True when the login session's screen is locked (a locked session may leave windows unpaced by the display),
    False when it is not, None when the state cannot be read (no `ioreg`)."""
    try:
        return "CGSSessionScreenIsLocked" in read(("ioreg", "-n", "Root", "-d1", "-a"))
    except (KeyError, OSError, subprocess.SubprocessError):
        return None


def power_state(read=read_command):
    """Returns {"low_power_mode", "thermal_warning"} of this Mac from `pmset`: low power mode on or off, and whether the Mac
    has recorded a thermal or performance warning or limits its CPU speed (below 100). A fact `pmset` does not give (no
    `pmset`, a Mac with no such key, text this does not know) is None, never a guess."""
    state = {"low_power_mode": None, "thermal_warning": None}
    try:
        low = re.search(r"^\s*lowpowermode\s+(\d)\s*$", read(("pmset", "-g")), re.MULTILINE)
        therm = read(("pmset", "-g", "therm"))
    except (KeyError, OSError, subprocess.SubprocessError):
        return state
    if low:
        state["low_power_mode"] = low.group(1) == "1"
    speed = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", therm)
    warned = [line for line in therm.splitlines() if "warning level" in line.lower() and "no " not in line.lower()]
    if speed or warned or "warning level" in therm.lower():
        state["thermal_warning"] = bool(warned) or (speed is not None and int(speed.group(1)) < 100)
    return state


def power_block(start, end):
    """Returns the `power` block of `machine`: both readings, and `changed` true when a fact known at both ends differs
    (the run's conditions moved while it was recorded)."""
    return {"start": start, "end": end,
            "changed": any(None not in (start[k], end[k]) and start[k] != end[k] for k in start)}


def machine_info(device, read=read_command):
    """Returns the chip, CPU and GPU core counts, RAM, macOS and whether the screen is locked (a locked session may leave
    windows unpaced by the display) of this Mac, with no name or UUID, or None when its RAM
    or macOS differ from the trace's `device` (it is not the machine that recorded it) or a fact cannot be read."""
    try:
        sysctl = lambda key: read(("sysctl", "-n", key)).strip()
        gpu = read(("ioreg", "-c", "AGXAccelerator", "-r", "-d", "1"))
        ram, macos = int(sysctl("hw.memsize")), read(("sw_vers", "-productVersion")).strip()
        locked = screen_locked(read)
        if str(ram) != device.get("memory-size") or macos != (device.get("os-version") or "").split(" ")[0]:
            return None
        return {"chip": sysctl("machdep.cpu.brand_string"), "cpu_cores_p": int(sysctl("hw.perflevel0.logicalcpu")),
                "cpu_cores_e": int(sysctl("hw.perflevel1.logicalcpu")),
                "gpu_cores": int(re.search(r'"gpu-core-count" = (\d+)', gpu).group(1)),
                "gpu_class": re.search(r'"IOClass" = "(AGX\w+)"', gpu).group(1), "ram_gib": ram // 2 ** 30, "macos": macos,
                "screen_locked": locked}
    except (KeyError, ValueError, AttributeError, OSError, subprocess.SubprocessError):
        return None
