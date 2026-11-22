"""Shared helpers of the tests: paths, a sample capture, the macOS-only marker, stub programs and golden files.

Importing it puts src/ on sys.path, so the tests import the package from the checkout."""
import functools
import json
import os
import pathlib
import secrets
import struct
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "metal_gpu_trace"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
# a project file named by the environment would point the servers the tests start at a real recordings folder
os.environ.pop("METAL_TRACE_PROJECT", None)
# the servers, recordings and scripts the tests start take a lock of their own, never the user's
os.environ["METAL_TRACE_LOCK"] = os.environ["PERF_LOCK"] = os.path.join(
    tempfile.mkdtemp(prefix="metal-gpu-trace-tests-"), "recording.lock")
# the recording tests must not depend on whether the developer's screen is locked (preflight refuses a locked one)
os.environ["METAL_TRACE_ALLOW_LOCKED"] = "1"


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

def unique_program(directory, prefix="prog"):
    """Writes an executable shell script whose name only this run uses and returns its path.

    perf_record.sh used to end the recorded program by name (pkill -x), so a name another suite's process could hold,
    such as /bin/sh, ended that suite's process. macOS keeps 16 characters of a process name, so the name stays short
    enough for that match."""
    program = directory / f"{prefix}-{os.getpid() % 10000:x}{secrets.token_hex(2)}"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    return program

def hang_stubs(tmp_path):
    """Returns (stubs directory, runs directory, program) for a recording whose xctrace starts and never finishes."""
    stubs, out = tmp_path / "stubs", tmp_path / "runs"
    stubs.mkdir()
    out.mkdir()
    xcrun = stubs / "xcrun"
    # like xctrace, it launches what follows -- as the leader of a process group of its own
    xcrun.write_text("#!/bin/zsh\nargs=(\"$@\")\nwhile [[ $1 != --output ]]; do shift; done\nmkdir -p $2\n"
                     "i=${args[(i)--]}\n(( i <= $#args )) && python3 -I -c "
                     "'import os, sys; os.setpgrp(); os.execv(sys.argv[1], sys.argv[1:])' \"${(@)args[i+1,-1]}\" &\n"
                     "sleep 60\n")
    xcrun.chmod(0o755)
    program = unique_program(tmp_path, "hang")
    return stubs, out, program


def stubborn_program(path):
    """Builds at `path` a program that ignores SIGTERM and sleeps 60 s; given an argument, it first starts a child of
    the same name. Built, not a copy of /bin/sleep: macOS kills a copied system binary with SIGKILL as it starts."""
    source = path.with_suffix(".c")
    source.write_text("#include <signal.h>\n#include <unistd.h>\nint main(int argc, char **argv) {\n  (void)argv;\n"
                      "  signal(SIGTERM, SIG_IGN);\n  if (argc > 1) fork();\n  sleep(60);\n  return 0;\n}\n")
    subprocess.run(["cc", "-o", str(path), str(source)], check=True)
    return path


def pids_named(name):
    """Returns the sorted pids of the processes named exactly `name`."""
    found = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True).stdout
    return sorted(int(pid) for pid in found.split())

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
