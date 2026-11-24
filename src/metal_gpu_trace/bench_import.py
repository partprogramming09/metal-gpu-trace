"""`metal-gpu-trace import-bench FILE...`: turns the result `bench.ps1` (VegaFlow) leaves for a run into a schema 3
summary in the runs folder, so `perf_runs`, `perf_compare` and `perf_history` read it.

Only the frame-time jitter means the same in both tools (the same standard deviation of the same intervals). FPS, the
1 % and 0.1 % lows and the hitches use other formulas under the same names (VegaFlow averages the slowest 1 %, this
project takes the 99th percentile), so they stay null in `gpu` and `common` and keep their own names in
`vegaflow_bench`: a number is never invented to fill a shared key. The importer reads the file; it never records,
never calls git and never copies `system_info`, so the summary names no machine."""
import datetime
import json
import math
import os
import pathlib
import re
import sys
import time

from metal_gpu_trace import config, metrics, paths

FIRST_STAMP = 946684800  # 2000-01-01: no bench.ps1 result is older
MAX_BYTES = 1024 * 1024  # a real result is about 1.2 KB
RESERVED = {"baselines", "panel"}  # files of the runs folder that are not recordings (paths.name_ok accepts both)
NUMBERS = ("avg_fps", "fps_1pct_low", "fps_0_1pct_low", "hitches_2x_median", "hitches_per_min", "present_mode_share",
           "display_frames", "display_stddev_ms", "display_late_pct")
USAGE = "usage: metal-gpu-trace import-bench FILE.json [FILE.json ...]"


def _number(value):
    """Returns `value` when it is a finite number (not a bool), else None."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:  # an integer too big for a float (isfinite converts it)
        return None


def _seconds(stamp):
    """Returns the Unix time of a PowerShell timestamp. `bench.ps1` writes 7 fraction digits, which Python 3.9's
    `fromisoformat` rejects (it takes exactly 3 or 6), so the fraction is padded or cut to 6; a trailing `Z` is UTC."""
    if not isinstance(stamp, str):
        raise ValueError
    text = re.sub(r"\.(\d+)", lambda m: "." + m.group(1).ljust(6, "0")[:6], stamp.strip(), count=1)
    text = text[:-1] + "+00:00" if text.endswith("Z") else text
    seconds = datetime.datetime.fromisoformat(text).timestamp()
    if not FIRST_STAMP <= seconds <= time.time() + 86400:  # os.utime clamps the extremes: they would top perf_runs
        raise ValueError
    return seconds


def _name(label):
    """Returns `label` when a run can be named after it, else raises ToolError."""
    if not paths.name_ok(label, 80) or label.casefold() in RESERVED:
        raise paths.ToolError("label must hold only letters, digits, '.', '_' and '-' (80 bytes at most) and not be a reserved name")
    return label


def from_json(text):
    """Returns the schema 3 summary of a `bench.ps1` result, or raises ToolError naming what is wrong (never a path)."""
    if not isinstance(text, str):
        raise paths.ToolError("the result must be text")
    try:
        value = json.loads(text.lstrip("\ufeff"))
    except (ValueError, RecursionError):
        raise paths.ToolError("not valid JSON (is it empty?)") from None
    if not isinstance(value, dict):
        raise paths.ToolError("not a JSON object: is it a result of bench.ps1?")
    label = _name(value.get("label"))
    frames = _number(value.get("frames"))
    if frames is None or frames <= 0 or frames != int(frames):
        raise paths.ToolError("frames must be a whole number above 0")
    seconds, warmup = _number(value.get("seconds")), _number(value.get("warmup_seconds", 0))
    if seconds is None or warmup is None or warmup < 0 or seconds - warmup <= 0:
        raise paths.ToolError("seconds must be above warmup_seconds, and neither negative")
    try:
        stamp = _seconds(value.get("timestamp"))
    except (ValueError, OverflowError, OSError):
        raise paths.ToolError("timestamp is missing or not an ISO 8601 date") from None
    process = value.get("process")
    exe = re.split(r"[\\/]", process)[-1] if isinstance(process, str) else ""
    if not exe:
        raise paths.ToolError("process must name the program")
    jitter, build, mode = _number(value.get("frametime_stddev_ms")), value.get("windows_build"), value.get("present_mode")
    errors = value.get("errors")
    summary = {
        "schema_version": metrics.SCHEMA_VERSION,
        "label": label,
        "process": {"name": exe, "arguments": None},
        "device": {"platform": "Windows", "os-version": build if isinstance(build, str) else None},
        "duration_s": seconds - warmup,
        "gpu": {"frames": int(frames), **{k: None for k in metrics.PACING_KEYS},
                "frame_jitter_ms": jitter if jitter is not None and jitter >= 0 else None, "source": "vegaflow-bench-json"},
        "vegaflow_bench": {
            **{k: _number(value.get(k)) for k in NUMBERS},
            "present_mode": mode if isinstance(mode, str) else None,
            "clean": value["clean"] if isinstance(value.get("clean"), bool) else None,
            "errors": [e for e in errors if isinstance(e, str)] if isinstance(errors, list) else None,
            "timestamp": value["timestamp"], "seconds": seconds, "warmup_seconds": warmup,
            "source": "vegaflow bench.ps1",
        },
    }
    summary["common"] = metrics.common_block(summary)
    summary["_stamp"] = stamp  # the caller dates the file with it; never written
    return summary


def _read(path):
    """Returns the text of the file, or raises ToolError: a link, a file over MAX_BYTES or one that cannot be read."""
    if path.is_symlink():
        raise paths.ToolError("a link is not imported")
    try:
        if path.stat().st_size > MAX_BYTES:
            raise paths.ToolError("the file is too large to be a bench.ps1 result (over 1 MiB)")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "r", encoding="utf-8-sig") as f:
            return f.read(MAX_BYTES + 1)
    except UnicodeDecodeError:
        raise paths.ToolError("the file is not UTF-8 text") from None
    except OSError:
        raise paths.ToolError("the file cannot be read") from None


def import_file(path):
    """Imports one result into the runs folder and returns ("imported" | "same", run name). Raises ToolError when the
    file is not a result, its name cannot name a run or another file already has that name."""
    name = path.name.removesuffix(".json") if path.name.endswith(".json") else None
    if name is None or not paths.name_ok(name) or name.casefold() in RESERVED:
        raise paths.ToolError("the file name must be NAME.json with only letters, digits, '.', '_' and '-'")
    summary = from_json(_read(path))
    stamp = summary.pop("_stamp")
    if summary["vegaflow_bench"]["clean"] is False:
        print(f"{name}: the present mode was not stable (clean: false); imported as it is", file=sys.stderr)
    text = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    target = config.OUT / f"{name}.json"
    if target.is_symlink():
        raise paths.ToolError(f"{target.name} cannot be written in the runs folder (is it a link?)")
    if target.exists():
        if paths.read_text(target) != text:
            raise paths.ToolError("a different run already has that name; rename the file")
        return "same", name
    config.OUT.mkdir(parents=True, exist_ok=True)
    paths.write_file(target, text)
    os.utime(target, (stamp, stamp))  # perf_history orders by the file's date: the date of the measurement
    return "imported", name


def main(args):
    """Runs `import-bench FILE...`: one JSON line per file (`imported`, `same` or `refused` with its reason); exits 0
    when every file is in the runs folder, 2 when one was refused or there is nothing to import."""
    files = [a for a in args if not a.startswith("--")]
    if not files or len(files) != len(args):
        print(USAGE, file=sys.stderr)
        return 2
    code = 0
    for arg in files:
        shown = os.path.basename(arg)
        try:
            status, run = import_file(pathlib.Path(arg))
            print(json.dumps({"status": status, "run": run}))
        except paths.ToolError as error:
            print(json.dumps({"status": "refused", "file": shown, "reason": str(error)}))
            code = 2
    return code
