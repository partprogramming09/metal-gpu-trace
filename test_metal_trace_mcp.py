"""Self-check of metal_trace_mcp.py, perf_report.py and gputrace_read.py without Instruments: run it with python3 -I."""
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import gputrace_read  # noqa: E402
import perf_report  # noqa: E402


def check_report(tmp):
    """Exported rows resolve xctrace's refs, the export file goes once read, and shared summaries hold no paths."""
    xml = tmp / "table.xml"
    for early in (False, True):
        xml.write_text('<trace-query-result><node><schema><col><mnemonic>process</mnemonic></col>'
                       '<col><mnemonic>duration</mnemonic></col></schema>'
                       '<row><process id="1"><pid>42</pid></process><duration>5</duration></row>'
                       '<row><process ref="1"/><duration>7</duration></row></node></trace-query-result>')
        got = perf_report.rows(str(xml))
        first = next(got)
        assert perf_report.pid_of(first["process"]) == 42
        rest = [] if early else list(got)
        got.close()
        assert early or perf_report.pid_of(rest[0]["process"]) == 42, rest
        assert not xml.exists(), "the exported XML must be deleted once read"
    assert perf_report.public_arguments("/opt/games/x/game.exe -w 1") == "game.exe -w 1"
    try:
        perf_report.export(tmp / "gone.trace", toc=True)
        raise AssertionError("a missing .trace must fail before xctrace runs")
    except FileNotFoundError as error:
        assert "KEEP_TRACE" in str(error) and str(tmp) not in str(error)


def check_capture(tmp):
    """A small MTSP stream is read record by record, and the summary names the capture without its path."""
    record = struct.pack("<Ii", 0x30, -16218) + bytes(0x24 - 8) + b"Cuu\0" + bytes(8)
    capture = tmp / "frame.gputrace"
    capture.mkdir()
    (capture / "capture").write_bytes(b"MTSP" + bytes(4) + record * 3)
    summary = gputrace_read.summarize(capture)
    assert summary["capture"] == "frame.gputrace" and summary["draw_primitives"] == 3, summary


def check_server(tmp):
    """The server answers on stdout with JSON only, pages lists, refuses paths outside its directories and turns
    failures into isError results."""
    out = tmp / "runs"
    out.mkdir()
    for i in range(3):
        (out / f"run{i}_x.json").write_text(json.dumps({"gpu": {"frames": 100 * i}}))
    (out / "run3_x.json").write_text('{"gpu": {')
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {"limit": 2}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "trace_tables", "arguments": {"trace": str(out / "gone.trace")}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "trace_tables", "arguments": {"trace": "/etc/hosts"}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "perf_compare", "arguments": {"a": "run0_x", "b": "../x"}}},
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {"bad": 1}}},
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "nope"}},
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
         "params": {"name": "gpu_family", "arguments": {"name": "M1 Pro"}}},
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
         "params": {"name": "gpu_family", "arguments": {"name": "Z80"}}},
        {"jsonrpc": "2.0", "id": 11, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 12, "method": "resources/read", "params": {"uri": "metal-trace://gpu-families/apple9"}},
        {"jsonrpc": "2.0", "id": 13, "method": "resources/read", "params": {"uri": "metal-trace://nope"}},
    ]
    proc = subprocess.run([sys.executable, "-I", str(TOOLS / "metal_trace_mcp.py")], text=True, capture_output=True,
                          input="\n".join(json.dumps(r) for r in requests) + "\n", timeout=60,
                          env=dict(os.environ, METAL_TRACE_OUT=str(out), METAL_TRACE_LOG="info"))
    replies = {r["id"]: r for r in map(json.loads, proc.stdout.splitlines())}
    assert sorted(replies) == list(range(1, 14)), replies
    assert len(replies[2]["result"]["tools"]) == 8
    assert replies[1]["result"]["capabilities"]["resources"] == {}
    m1 = replies[9]["result"]["structuredContent"]
    assert m1["family"] == "Apple7" and m1["limits"]["mesh_grid_threadgroups"] == 1024, m1
    assert replies[10]["result"]["isError"] and "Apple7" in replies[10]["result"]["content"][0]["text"]
    assert len(replies[11]["result"]["resources"]) == 5
    apple9 = json.loads(replies[12]["result"]["contents"][0]["text"])
    assert apple9["family"] == "Apple9" and apple9["sources"]["feature_set_tables"].startswith("https://"), apple9
    assert replies[13]["error"]["code"] == -32002
    runs = replies[3]["result"]["structuredContent"]
    assert runs["total"] == 3 and len(runs["rows"]) == 2 and runs["next_offset"] == 2, runs
    for mid, words in ((4, "KEEP_TRACE"), (5, "outside"), (6, "only letters"), (7, "bad arguments")):
        result = replies[mid]["result"]
        assert result.get("isError") and words in result["content"][0]["text"], (mid, result)
        assert str(tmp) not in result["content"][0]["text"], (mid, result)
    assert replies[8]["error"]["code"] == -32602
    assert proc.stderr.count("metal-trace:") == 7, proc.stderr


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp).resolve()
        check_report(tmp)
        check_capture(tmp)
        check_server(tmp)
    print("ok")


if __name__ == "__main__":
    main()
