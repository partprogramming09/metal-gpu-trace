"""The short command line: help answers instead of waiting on stdin, doctor prints preflight's report, runs lists the
recordings and compare compares two of them; with no command the MCP server still serves stdio."""
import json
import os
import subprocess
import sys

import support  # noqa: F401  (puts src/ on sys.path)
from support import PKG


def cli(*args, env=None, text=None):
    """Starts the command line with `args` and returns the finished process; stdin is closed unless `text` is given."""
    return subprocess.run([sys.executable, "-I", str(PKG / "metal_trace_mcp.py"), *args], text=True,
                          capture_output=True, timeout=60,
                          **({"input": text} if text is not None else {"stdin": subprocess.DEVNULL}),
                          env={**os.environ, "METAL_TRACE_LOG": "off", **(env or {})})


def summary(fps):
    """A recording's summary with the numbers perf_runs and perf_compare read."""
    return {"gpu": {"frames": 300, "fps_estimate": fps, "frame_gpu_ms": {"mean": 4.3, "p95": 8.0},
                    "frame_interval_ms": {"p95": 20.0}},
            "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5},
                         "short_share": {"25": 0.5}, "by_label": []},
            "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}}


def write_runs(folder, runs):
    """Writes one summary per (name, fps) into `folder`, oldest first."""
    folder.mkdir(parents=True, exist_ok=True)
    for i, (name, fps) in enumerate(runs):
        path = folder / f"{name}.json"
        path.write_text(json.dumps(summary(fps)))
        os.utime(path, (1_700_000_000 + i, 1_700_000_000 + i))


def test_help_lists_the_commands_and_exits_0(tmp_path):
    """`--help` and `-h` answer in the terminal with the commands, and do not fall through to the server that waits
    for a client on stdin."""
    for flag in ("--help", "-h"):
        proc = cli(flag)
        assert proc.returncode == 0, (flag, proc.stderr)
        for word in ("doctor", "runs", "compare", "init", "check", "--http", "--version"):
            assert word in proc.stdout, (flag, word, proc.stdout)
        assert str(tmp_path) not in proc.stdout


def test_an_unknown_command_says_usage_and_exits_2(tmp_path):
    proc = cli("bogus")
    assert proc.returncode == 2, proc
    assert "unknown command" in proc.stderr and "usage:" in proc.stderr, proc.stderr
    assert str(tmp_path) not in proc.stdout + proc.stderr
    assert not proc.stdout, "an unknown command must not answer on stdout"


def test_no_arguments_still_serves_mcp_stdio():
    """An MCP client starts `metal-gpu-trace` with no arguments: initialize is still answered, and the server exits
    when the client closes stdin instead of hanging."""
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    proc = cli(text=json.dumps(request) + "\n")
    reply = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert reply["id"] == 1 and reply["result"]["serverInfo"]["name"] == "metal-trace", reply
    assert "instructions" in reply["result"]


def test_a_closed_stdin_ends_the_server():
    proc = cli()
    assert proc.returncode == 0, proc.stderr
    assert not proc.stdout


def doctor_env(tmp_path, **more):
    """The environment of a Mac that can record: an xcrun stub on PATH and enough free disk for any machine."""
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    xcrun = stubs / "xcrun"
    xcrun.write_text('#!/bin/sh\n[ "$1" = --find ] && echo "$0"\n')
    xcrun.chmod(0o755)
    return {"METAL_TRACE_OUT": str(tmp_path / "runs"), "PERF_MIN_FREE_GB": "1",
            "PATH": str(stubs) + os.pathsep + os.environ.get("PATH", ""), **more}


def test_doctor_prints_preflight_report_without_paths(tmp_path):
    proc = cli("doctor", env=doctor_env(tmp_path))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "xctrace" in proc.stdout or sys.platform == "win32", proc.stdout
    assert "ok: a recording can start" in proc.stdout, proc.stdout
    assert str(tmp_path) not in proc.stdout + proc.stderr, "a report is shared: it names no path"


def test_doctor_exits_2_when_a_recording_could_not_start(tmp_path):
    proc = cli("doctor", env=doctor_env(tmp_path, PERF_MIN_FREE_GB="999999999"))
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "disk" in proc.stdout and "missing" in proc.stdout, proc.stdout
    assert str(tmp_path) not in proc.stdout + proc.stderr


def test_runs_lists_the_recordings_newest_first(tmp_path):
    out = tmp_path / "runs"
    write_runs(out, [("r1", 60.0), ("r2", 61.5)])
    proc = cli("runs", env={"METAL_TRACE_OUT": str(out)})
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert proc.stdout.index("r2") < proc.stdout.index("r1"), "newest first"
    assert "61.5" in proc.stdout and "300" in proc.stdout, proc.stdout
    assert str(tmp_path) not in proc.stdout
    one = cli("runs", "--limit", "1", env={"METAL_TRACE_OUT": str(out)})
    assert one.returncode == 0 and "r2" in one.stdout and "r1" not in one.stdout, one.stdout
    assert "more" in one.stdout, "the limit hides a run and the command says so"


def test_runs_refuses_a_bad_limit_or_option(tmp_path):
    for args in (("runs", "--limit"), ("runs", "--limit", "x"), ("runs", "--limit", "0"), ("runs", "--nope"),
                 ("runs", "extra")):
        proc = cli(*args, env={"METAL_TRACE_OUT": str(tmp_path)})
        assert proc.returncode == 2, (args, proc.returncode, proc.stdout, proc.stderr)
        assert "usage: metal-gpu-trace runs" in proc.stderr, (args, proc.stderr)


def test_runs_says_when_there_are_none(tmp_path):
    proc = cli("runs", env={"METAL_TRACE_OUT": str(tmp_path / "never")})
    assert proc.returncode == 0 and proc.stdout.strip() == "no recordings", proc.stdout
    assert not (tmp_path / "never").exists(), "listing recordings must not create the folder"


def test_compare_prints_a_table_or_its_markdown(tmp_path):
    out = tmp_path / "runs"
    write_runs(out, [("before", 60.0), ("after", 62.0)])
    table = cli("compare", "before", "after", env={"METAL_TRACE_OUT": str(out)})
    assert table.returncode == 0, (table.stdout, table.stderr)
    assert "before (a) vs after (b)" in table.stdout
    assert "fps" in table.stdout and "gpu_ms_mean" in table.stdout, table.stdout
    assert str(tmp_path) not in table.stdout
    markdown = cli("compare", "before", "after", "--markdown", env={"METAL_TRACE_OUT": str(out)})
    assert markdown.returncode == 0, (markdown.stdout, markdown.stderr)
    assert "| metric | a | b | change | % |" in markdown.stdout, markdown.stdout
    assert str(tmp_path) not in markdown.stdout


def test_compare_refuses_bad_arguments_and_unknown_runs(tmp_path):
    out = tmp_path / "runs"
    write_runs(out, [("before", 60.0), ("after", 62.0)])
    for args in (("compare",), ("compare", "before"), ("compare", "before", "after", "extra")):
        proc = cli(*args, env={"METAL_TRACE_OUT": str(out)})
        assert proc.returncode == 2, (args, proc.returncode)
        assert "usage: metal-gpu-trace compare" in proc.stderr, (args, proc.stderr)
    missing = cli("compare", "before", "nope", env={"METAL_TRACE_OUT": str(out)})
    assert missing.returncode == 2 and "no run" in missing.stderr, missing.stderr
    assert str(tmp_path) not in missing.stderr


def test_version_still_prints_the_installed_one():
    from metal_gpu_trace import metal_trace_mcp

    proc = cli("--version")
    assert proc.returncode == 0 and proc.stdout.strip() == f"metal-gpu-trace {metal_trace_mcp.__version__}", proc.stdout


def test_doctor_rejects_extra_arguments_and_every_command_answers_help(tmp_path):
    """`doctor --bogus` is a usage error like the other commands'; `COMMAND --help` prints the usage and exits 0."""
    bad = cli("doctor", "--bogus")
    assert bad.returncode == 2 and "usage: metal-gpu-trace doctor" in bad.stderr
    for command in ("doctor", "runs", "compare", "check"):
        for flag in ("--help", "-h"):
            done = cli(command, flag)
            assert done.returncode == 0 and "usage: metal-gpu-trace [COMMAND]" in done.stdout, (command, flag)


def test_a_usage_error_names_the_program_once():
    """The message already starts with `usage:`: it is not prefixed with `metal-gpu-trace:` a second time."""
    bad = cli("doctor", "--bogus")
    assert bad.stderr.startswith("usage: metal-gpu-trace doctor"), bad.stderr
    unknown = cli("bogus")
    assert unknown.stderr.startswith("metal-gpu-trace: unknown command 'bogus'"), unknown.stderr
