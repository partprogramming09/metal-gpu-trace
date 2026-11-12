"""Shared helpers of the tests: paths, a sample capture, the macOS-only marker, stub programs and golden files.

Importing it puts src/ on sys.path, so the tests import the package from the checkout."""
import functools
import json
import os
import pathlib
import struct
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "metal_gpu_trace"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def wait_until(predicate, timeout=10.0, step=0.02):
    """Returns once predicate() is true; raises AssertionError when it is still false after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"condition not met within {timeout} s")
        time.sleep(step)


def write_capture(directory):
    """Writes a .gputrace holding three drawPrimitives records into `directory` and returns its path."""
    record = struct.pack("<Ii", 0x30, -16218) + bytes(0x24 - 8) + b"Cuu\0" + bytes(8)
    capture = directory / "frame.gputrace"
    capture.mkdir()
    (capture / "capture").write_bytes(b"MTSP" + bytes(4) + record * 3)
    return capture

def macos_only(test):
    """Skips a test that needs macOS tools (zsh, xctrace, a shell-script Wine) when run on Windows."""
    @functools.wraps(test)
    def wrapper(tmp_path):
        if sys.platform == "win32":
            try:
                import pytest
            except ImportError:
                return None
            pytest.skip("needs macOS tools")
        return test(tmp_path)
    return wrapper

def hang_stubs(tmp_path):
    """Returns (stubs directory, runs directory, program) for a recording whose xctrace starts and never finishes."""
    stubs, out = tmp_path / "stubs", tmp_path / "runs"
    stubs.mkdir()
    out.mkdir()
    xcrun = stubs / "xcrun"
    xcrun.write_text("#!/bin/zsh\nwhile [[ $1 != --output ]]; do shift; done\nmkdir -p $2\nsleep 60\n")
    xcrun.chmod(0o755)
    program = tmp_path / "hang-4242"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    pkill = stubs / "pkill"  # records which program the stop path kills
    pkill.write_text(f"#!/bin/zsh\necho $@ >> {tmp_path}/pkill.log\n")
    pkill.chmod(0o755)
    return stubs, out, program

GOLDEN = ROOT / "tests" / "golden"

def golden(name, value):
    """Compares `value` with tests/golden/<name>.json, the recorded behaviour a refactor must keep. With
    METAL_TRACE_GOLDEN=write it records `value` instead: do that only for an intended change, named in the CHANGELOG."""
    path = GOLDEN / f"{name}.json"
    text = json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("METAL_TRACE_GOLDEN") == "write":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.exists(), f"golden file missing: {path.name} (record it with METAL_TRACE_GOLDEN=write)"
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(text), f"{name} differs from its golden file"
