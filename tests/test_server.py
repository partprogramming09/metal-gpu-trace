"""Tests of the MCP server: protocol, queue, HTTP, cancellation and the protocol golden file."""
import json
import os
import subprocess
import sys

from support import ROOT, PKG, write_capture, hang_stubs, golden  # also puts src/ on sys.path


def test_readme_lists_every_tool(tmp_path):
    """Both READMEs hold a table row for every tool the server offers, and name the words the 0.17.0 additions need."""
    import re
    from metal_gpu_trace import metal_trace_mcp as mcp
    for name in ("README.md", "es/README.md"):
        rows = set(re.findall(r"^\| `([a-z_]+)` \|", (ROOT / name).read_text(encoding="utf-8"), re.M))
        missing = sorted(set(mcp.TOOLS) - rows)
        assert not missing, f"{name} lacks rows for {missing}"
        text = (ROOT / name).read_text(encoding="utf-8")
        for word in ("mtl-x64", "bgfx-examples", "memory_free_pct", "gpu_state", "screen_locked", "resource_allocations"):
            assert word in text, f"{name} does not mention {word}"

def test_server(tmp_path):
    """The server answers on stdout with JSON only, pages lists, refuses paths outside its directories and turns
    failures into isError results."""
    out = tmp_path / "runs"
    out.mkdir()
    for i in range(3):
        (out / f"run{i}_x.json").write_text(json.dumps({"gpu": {"frames": 100 * i}}))
    (out / "run3_x.json").write_text('{"gpu": {')
    (out / "run1_x.trace").mkdir()
    write_capture(out)
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
        {"jsonrpc": "2.0", "id": 14, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
        [1],
        {"jsonrpc": "2.0", "id": 15, "method": "ping"},
        {"jsonrpc": "2.0", "id": 16, "method": "tools/list", "params": [1]},
        {"jsonrpc": "2.0", "id": 17, "method": "resources/templates/list"},
        {"jsonrpc": "2.0", "id": 18, "method": "tools/call",
         "params": {"name": "perf_attach", "arguments": {"label": "a", "process": "no-such-program-4242.exe"}}},
        {"jsonrpc": "2.0", "id": 19, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 20, "method": "tools/call",
         "params": {"name": "trace_tables", "arguments": {"trace": "run0_x"}}},
        {"jsonrpc": "2.0", "id": 21, "method": "tools/call",
         "params": {"name": "capture_summary", "arguments": {"capture": str(out / "frame.gputrace")}}},
        {"jsonrpc": "2.0", "id": 22, "method": "prompts/list"},
        {"jsonrpc": "2.0", "id": 23, "method": "prompts/get",
         "params": {"name": "compare-layer", "arguments": {"workload": "drawstress", "api": "d3d11"}}},
        {"jsonrpc": "2.0", "id": 24, "method": "prompts/get",
         "params": {"name": "compare-layer", "arguments": {"api": "d3d12; rm -rf /"}}},
        {"jsonrpc": "2.0", "id": 25, "method": "prompts/get", "params": {"name": "nope"}},
        {"jsonrpc": "2.0", "id": 26, "method": "resources/read", "params": {"uri": "metal-trace://runs/run1_x"}},
        {"jsonrpc": "2.0", "id": 27, "method": "resources/read", "params": {"uri": "metal-trace://runs/../x"}},
        {"jsonrpc": "2.0", "id": 28, "method": "resources/read", "params": {"uri": "metal-trace://runs/gone"}},
    ]
    proc = subprocess.run([sys.executable, "-I", str(PKG / "metal_trace_mcp.py")], text=True, capture_output=True,
                          input="\n".join(json.dumps(r) for r in requests) + "\n", timeout=60,
                          env=dict(os.environ, METAL_TRACE_OUT=str(out), METAL_TRACE_LOG="info"))
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    replies = {r["id"]: r for r in lines if r["id"] is not None}
    assert sorted(replies) == list(range(1, 29)), (replies, proc.stderr)
    tools = {t["name"]: t for t in replies[2]["result"]["tools"]}
    assert all("outputSchema" in t for t in tools.values()), "every tool declares its output"
    paged = replies[3]["result"]["structuredContent"]
    assert set(tools["perf_runs"]["outputSchema"]["required"]) <= set(paged), paged
    assert [p["name"] for p in replies[22]["result"]["prompts"]] == ["compare-layer"]
    steps = replies[23]["result"]["messages"][0]["content"]["text"]
    assert all(w in steps for w in ("api=d3d11", "workload=drawstress", "perf_compare a=", "labels")), steps
    # an argument that is not a plain name is dropped, so the default api stays
    assert "rm -rf" not in replies[24]["result"]["messages"][0]["content"]["text"]
    assert replies[25]["error"]["code"] == -32602
    assert replies[1]["result"]["capabilities"]["prompts"] == {}
    assert [r["error"]["code"] for r in lines if r["id"] is None] == [-32600], lines
    assert replies[14]["result"]["protocolVersion"] == "2025-06-18"
    assert replies[15]["result"] == {} and replies[16]["error"]["code"] == -32600
    assert [x["uriTemplate"] for x in replies[17]["result"]["resourceTemplates"]] == ["metal-trace://runs/{run}"]
    assert json.loads(replies[26]["result"]["contents"][0]["text"]) == {"gpu": {"frames": 100}}
    assert replies[27]["error"]["code"] == replies[28]["error"]["code"] == -32002, "a bad run name is not found"
    assert len(replies[2]["result"]["tools"]) == 24
    assert replies[1]["result"]["capabilities"]["resources"] == {}
    assert "KEEP_TRACE=1" in replies[1]["result"]["instructions"]
    hints = {t["name"]: t["annotations"] for t in replies[2]["result"]["tools"]}
    asks = [t["name"] for t in replies[2]["result"]["tools"] if t.get("_meta", {}).get("anthropic/requiresUserInteraction")]
    assert asks == ["workload_fetch", "presentmon_install"] and hints["workload_fetch"]["openWorldHint"], (asks, hints)
    assert hints["perf_record"]["destructiveHint"] and not hints["perf_attach"]["destructiveHint"], hints
    assert hints["perf_runs"]["readOnlyHint"] and all(h["title"] for h in hints.values()), hints
    m1 = replies[9]["result"]["structuredContent"]
    assert m1["family"] == "Apple7" and m1["limits"]["mesh_grid_threadgroups"] == 1024, m1
    assert replies[10]["result"]["isError"] and "Apple7" in replies[10]["result"]["content"][0]["text"]
    assert len(replies[11]["result"]["resources"]) == 5
    apple9 = json.loads(replies[12]["result"]["contents"][0]["text"])
    assert apple9["family"] == "Apple9" and apple9["sources"]["feature_set_tables"].startswith("https://"), apple9
    assert replies[13]["error"]["code"] == -32002
    runs = replies[3]["result"]["structuredContent"]
    assert runs["total"] == 3 and len(runs["rows"]) == 2 and runs["next_offset"] == 2, runs
    kept = {r["run"]: r["trace_kept"] for r in replies[19]["result"]["structuredContent"]["rows"]}
    assert kept == {"run0_x": False, "run1_x": True, "run2_x": False}, kept
    capture = replies[21]["result"]["structuredContent"]
    assert capture["calls_total"] == 1 and len(capture["calls"]) == 1, capture
    for mid, words in ((4, "KEEP_TRACE"), (5, "outside"), (6, "only letters"), (7, "bad arguments"),
                       (18, "no running process matches"), (20, "KEEP_TRACE")):
        result = replies[mid]["result"]
        assert result.get("isError") and words in result["content"][0]["text"], (mid, result)
        assert str(tmp_path) not in result["content"][0]["text"], (mid, result)
    assert replies[8]["error"]["code"] == -32602
    assert proc.stderr.count("metal-trace:") == 11, proc.stderr

def test_no_runs_directory(tmp_path):
    """A server that only lists recordings does not create the recordings directory."""
    out = tmp_path / "never"
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {}}}
    proc = subprocess.run([sys.executable, "-I", str(PKG / "metal_trace_mcp.py")], text=True, capture_output=True,
                          input=json.dumps(request) + "\n", timeout=60,
                          env=dict(os.environ, METAL_TRACE_OUT=str(out), METAL_TRACE_LOG="off"))
    assert json.loads(proc.stdout)["result"]["structuredContent"]["total"] == 0, proc.stdout
    assert not out.exists()

def test_progress_and_cancel(tmp_path):
    """A recording reports progress to a client that sent a progressToken and stops, leaving no files, when the client
    cancels it; ping is answered while it runs."""
    import threading
    import time
    from metal_gpu_trace import metal_trace_mcp as mcp
    stubs, out, program = hang_stubs(tmp_path)
    seen, cancel = [], threading.Event()
    saved = mcp.OUT, mcp.PROGRESS_TICKS, os.environ["PATH"]
    mcp.OUT, mcp.PROGRESS_TICKS = out, 1
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    mcp.RUN.cancel, mcp.RUN.progress = cancel, lambda *a: seen.append(a) or (len(seen) == 2 and cancel.set())
    try:
        mcp.tool_perf_record("hang", str(program), seconds=1, wine="native")
        raise AssertionError("a cancelled recording must fail")
    except mcp.ToolError as error:
        assert "cancelled" in str(error), error
    finally:
        mcp.OUT, mcp.PROGRESS_TICKS, os.environ["PATH"] = saved
        mcp.RUN.cancel = mcp.RUN.progress = None
    assert (tmp_path / "pkill.log").read_text().split() == ["-x", "hang-4242"], "the launched program must be killed"
    assert len(seen) == 2 and seen[1][0] > seen[0][0] and seen[0][1] == mcp.deadline(1), seen
    assert not list(out.iterdir()), list(out.iterdir())
    import io
    real, sys.stdout = sys.stdout, io.StringIO()
    mcp.TOOLS["t"] = (lambda: mcp.progress(1, 2, "half") or {}, None, None)
    try:
        mcp.call("t", {}, 7, "tok")
        line = sys.stdout.getvalue()
    finally:
        sys.stdout = real
        del mcp.TOOLS["t"]
    assert json.loads(line) == {"jsonrpc": "2.0", "method": "notifications/progress", "params": {
        "progressToken": "tok", "progress": 1, "total": 2, "message": "half"}}, line
    # over stdio: the cancel notification ends the call while the server still answers ping
    proc = subprocess.Popen([sys.executable, "-I", str(PKG / "metal_trace_mcp.py")], text=True, bufsize=1,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=dict(os.environ, METAL_TRACE_OUT=str(out), PATH=f"{stubs}:{os.environ['PATH']}"))
    def say(message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
    try:
        say({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "perf_record", "_meta": {"progressToken": "t"},
            "arguments": {"label": "hang", "program": str(program), "seconds": 1, "wine": "native"}}})
        time.sleep(2)
        say({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        assert json.loads(proc.stdout.readline())["id"] == 2, "ping must be answered during a recording"
        say({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}})
        reply = json.loads(proc.stdout.readline())
        assert reply["id"] == 1 and reply["result"]["isError"] and "cancelled" in reply["result"]["content"][0]["text"]
    finally:
        proc.kill()
        proc.wait()
    assert not list(out.iterdir()), list(out.iterdir())

def test_check_cli(tmp_path):
    """`metal-gpu-trace check` exits 0 for same or improved, 1 for regressed, 2 for a run that cannot be judged, and
    prints one JSON line without the full comparison."""
    from metal_gpu_trace import metal_trace_mcp as mcp

    def summary(fps, frames=300):
        return {"gpu": {"frames": frames, "fps_estimate": fps, "frame_gpu_ms": {"mean": 4.3, "p95": 8.0},
                        "frame_interval_ms": {"p95": 20.0}},
                "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5},
                             "short_share": {"25": 0.5}, "by_label": []},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}}
    for name, s in {"r1": summary(60.0), "r2": summary(62.0), "ok": summary(61.0), "bad": summary(40.0),
                    "short": summary(61.0, frames=50)}.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(s))
    saved, (mcp.OUT, mcp.BASELINES) = (mcp.OUT, mcp.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        mcp.tool_perf_baseline("ds", ["r1", "r2"])
    finally:
        mcp.OUT, mcp.BASELINES = saved

    def check(*args):
        proc = subprocess.run([sys.executable, "-I", str(PKG / "metal_trace_mcp.py"), "check", *args], text=True,
                              capture_output=True, env=dict(os.environ, METAL_TRACE_OUT=str(tmp_path)))
        return proc.returncode, proc.stdout, proc.stderr
    code, out, _ = check("ok", "ds")
    assert code == 0 and json.loads(out)["verdict"] == "same" and "comparison" not in out, (code, out)
    code, out, _ = check("bad", "ds")
    assert code == 1 and json.loads(out)["regressed"][0]["metric"] == "fps", (code, out)
    assert check("bad", "ds", "--margin-pct", "99")[0] == 0, "a wide margin lets it pass"
    assert check("short", "ds")[0] == 2, "a run under 100 frames cannot be judged"
    for bad in (("nope", "ds"), ("ok", "nope"), ("ok",), ("ok", "ds", "--margin-pct", "x")):
        assert check(*bad)[0] == 2, bad

def test_http(tmp_path):
    """`--http` serves POST /mcp on 127.0.0.1 only: it refuses to start without a token, answers 401 without the
    token, 403 for a foreign Host or Origin, 405 for GET and 202 for a notification, serves tools, and a cancel
    request from a second connection stops a running recording."""
    import http.client
    import socket
    import threading
    import time
    stubs, out, program = hang_stubs(tmp_path)
    script = [sys.executable, "-I", str(PKG / "metal_trace_mcp.py"), "--http", "--port"]
    env = dict(os.environ, METAL_TRACE_OUT=str(out), METAL_TRACE_LOG="off", PATH=f"{stubs}:{os.environ['PATH']}")
    without = subprocess.run([*script, "0"], capture_output=True, text=True, timeout=30,
                             env={k: v for k, v in env.items() if k != "METAL_TRACE_TOKEN"})
    assert without.returncode == 2 and "METAL_TRACE_TOKEN" in without.stderr, without
    assert subprocess.run([*script, "0"], capture_output=True, text=True, timeout=30,
                          env=dict(env, METAL_TRACE_TOKEN="short")).returncode == 2, "a short token is refused"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    token = "t" * 32
    proc = subprocess.Popen([*script, str(port)], env=dict(env, METAL_TRACE_TOKEN=token), stderr=subprocess.DEVNULL)

    def post(body, headers=None, path="/mcp", method="POST"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        h = {"Content-Type": "application/json", "Authorization": f"Bearer {token}", **(headers or {})}
        conn.request(method, path, json.dumps(body) if body is not None else None, h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, json.loads(data) if data else None
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        assert post(ping) == (200, {"jsonrpc": "2.0", "id": 1, "result": {}})
        assert post(ping, {"Authorization": "Bearer nope"})[0] == 401
        assert post(ping, {"Authorization": ""})[0] == 401
        assert post(ping, {"Origin": "http://evil.example"})[0] == 403
        assert post(ping, {"Origin": "http://localhost.evil.example"})[0] == 403
        assert post(ping, {"Host": "evil.example"})[0] == 403
        assert post(ping, {"Origin": f"http://localhost:{port}"})[0] == 200
        assert post(None, method="GET")[0] == 405
        assert post(ping, path="/other")[0] == 404
        assert post({"jsonrpc": "2.0", "method": "notifications/initialized"}) == (202, None)
        code, tools = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert code == 200 and len(tools["result"]["tools"]) == 24
        code, runs = post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                           "params": {"name": "perf_runs", "arguments": {}, "_meta": {"progressToken": "x"}}})
        assert code == 200 and runs["result"]["structuredContent"]["total"] == 0, runs

        def get(path, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            conn.request("GET", path, headers=headers or {})
            r = conn.getresponse()
            body = r.read().decode()
            conn.close()
            return r.status, r.getheader("Content-Type"), body
        auth = {"Authorization": f"Bearer {token}"}
        status, kind, page_html = get("/panel")
        assert status == 200 and kind.startswith("text/html") and "connect-src 'self'" in page_html, (status, kind)
        assert token not in page_html and get("/panel", {"Host": "evil.example"})[0] == 403
        assert get("/panel/data")[0] == 401 and get("/panel/data", {**auth, "Origin": "http://evil.example"})[0] == 403
        status, _, body = get("/panel/data", auth)
        assert status == 400 and "no recordings" in body, (status, body)
        (out / "a.json").write_text(json.dumps({"gpu": {"frames": 2, "fps_estimate": 60.0}, "hitches": {}}))
        (out / "a.frames.csv").write_text("frame,start_ms,gpu_ms_total\n1,0.0,4.0\n2,16.0,4.0\n")
        status, kind, body = get("/panel/data", auth)
        assert status == 200 and json.loads(body)["runs"][0]["name"] == "a" and json.loads(body)["preset"] == "fps", body
        assert get("/panel/data?runs=a,a&preset=compare", auth)[0] == 200
        assert get("/panel/data?runs=../x", auth)[0] == 400 and get("/panel/data?preset=nope", auth)[0] == 400
        (out / "a.json").unlink()
        (out / "a.frames.csv").unlink()
        result = []
        call = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "perf_record", "arguments": {"label": "hang", "program": str(program), "seconds": 1, "wine": "native"}}}
        thread = threading.Thread(target=lambda: result.append(post(call)))
        thread.start()
        time.sleep(2)
        assert post({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 7}})[0] == 202
        thread.join(30)
        code, reply = result[0]
        assert code == 200 and reply["result"]["isError"] and "cancelled" in reply["result"]["content"][0]["text"], reply
    finally:
        proc.kill()
        proc.wait()
    assert not list(out.iterdir()), list(out.iterdir())

def test_queue(tmp_path):
    """Tool calls wait in a queue of MAX_QUEUE: one past it is refused at once, and cancelling a queued call answers
    it at once instead of after the call ahead of it."""
    import threading
    import time
    from metal_gpu_trace import metal_trace_mcp as mcp
    gate, replies, log = threading.Event(), {}, os.environ.get("METAL_TRACE_LOG")
    os.environ["METAL_TRACE_LOG"] = "off"
    mcp.TOOLS["slow"] = (lambda: gate.wait(20) and {}, {"type": "object"}, {})

    def submit(i):
        mcp.CALLS[i] = threading.Event()
        mcp.submit({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "slow", "arguments": {}}},
                   lambda r: replies.__setitem__(i, r))
    try:
        submit(0)
        time.sleep(0.3)  # the worker has taken call 0 and waits on the gate
        for i in range(1, mcp.MAX_QUEUE + 1):
            submit(i)
        submit(999)
        assert "waiting" in replies[999]["result"]["content"][0]["text"] and 999 not in mcp.CALLS, replies.get(999)
        mcp.cancel_call(5)
        assert 5 in replies and "cancelled" in replies[5]["result"]["content"][0]["text"], "a queued cancel answers at once"
        mcp.cancel_call([1])  # an unhashable id is ignored
        mcp.cancel_call(123456)
    finally:
        gate.set()
        mcp.stop_worker()
        mcp.WORKER.clear()
        del mcp.TOOLS["slow"]
        os.environ.pop("METAL_TRACE_LOG") if log is None else os.environ.__setitem__("METAL_TRACE_LOG", log)
    assert sorted(replies) == sorted(set(range(mcp.MAX_QUEUE + 1)) | {999}), sorted(replies)
    assert not mcp.CALLS, mcp.CALLS

def test_http_timeout(tmp_path):
    """A client that stalls in the middle of its request is dropped after HTTP_TIMEOUT instead of holding a thread."""
    import socket
    import threading
    from http.server import ThreadingHTTPServer
    from metal_gpu_trace import metal_trace_mcp as mcp
    saved, mcp.HTTP_TIMEOUT = mcp.HTTP_TIMEOUT, 1
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), mcp.http_handler("t" * 32))
    finally:
        mcp.HTTP_TIMEOUT = saved
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        stalled = socket.create_connection(server.server_address, timeout=3)
        stalled.sendall(b"POST /mcp HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\n")
        stalled.settimeout(10)
        assert stalled.recv(10) == b"", "the server must close a stalled connection"
        stalled.close()
    finally:
        server.shutdown()
        server.server_close()

GOLDEN_MESSAGES = [
    {"method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "t", "version": "0"}}},
    {"method": "initialize", "params": {"protocolVersion": "1999-01-01", "capabilities": {},
                                        "clientInfo": {"name": "t", "version": "0"}}},
    {"method": "tools/list"},
    {"method": "resources/list"},
    {"method": "resources/templates/list"},
    {"method": "prompts/list"},
    {"method": "prompts/get", "params": {"name": "compare-layer", "arguments": {"workload": "drawstress"}}},
    {"method": "resources/read", "params": {"uri": "metal-trace://runs/none_such"}},
    {"method": "tools/call", "params": {"name": "gpu_family", "arguments": {"name": "M3"}}},
    {"method": "tools/call", "params": {"name": "no_such_tool", "arguments": {}}},
    {"method": "no/such/method"},
    {"method": "ping"},
]

def test_golden_protocol(tmp_path):
    """The server answers a fixed set of messages exactly as recorded in tests/golden/protocol.json."""
    from metal_gpu_trace import metal_trace_mcp as mcp
    saved = mcp.OUT
    mcp.OUT = tmp_path
    try:
        replies = [mcp.handle({"jsonrpc": "2.0", "id": i, **m}) for i, m in enumerate(GOLDEN_MESSAGES)]
    finally:
        mcp.OUT = saved
    for reply in replies:
        info = (reply.get("result") or {}).get("serverInfo")
        if info:
            info["version"] = "<version>"
    golden("protocol", replies)

def test_tool_descriptions_have_no_indent(tmp_path):
    """No line of a tool description starts with whitespace, whatever the Python (before 3.13 docstrings keep their
    indent)."""
    from metal_gpu_trace import metal_trace_mcp as mcp
    for tool in mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]:
        assert not any(line[:1].isspace() for line in tool["description"].splitlines()), tool["name"]
