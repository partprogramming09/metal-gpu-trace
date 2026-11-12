"""Tests of the MCP server: protocol, queue, HTTP, cancellation and the protocol golden file."""
import contextlib
import json
import os
import subprocess
import sys

from support import ROOT, PKG, write_capture, hang_stubs, golden, wait_until  # also puts src/ on sys.path


def test_readme_lists_every_tool(tmp_path):
    """Both READMEs hold a table row for every tool the server offers, and name the words the 0.17.0 additions need."""
    import re
    from metal_gpu_trace import registry
    for name in ("README.md", "es/README.md"):
        rows = set(re.findall(r"^\| `([a-z_]+)` \|", (ROOT / name).read_text(encoding="utf-8"), re.M))
        missing = sorted(set(registry.TOOLS) - rows)
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
    assert replies[14]["result"]["protocolVersion"] == "2025-11-25"
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
    from metal_gpu_trace import config, paths, recording, registry, worker
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    stubs, out, program = hang_stubs(tmp_path)
    seen, cancel = [], threading.Event()
    saved = config.OUT, config.PROGRESS_TICKS, os.environ["PATH"]
    config.OUT, config.PROGRESS_TICKS = out, 1
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    recording.RUN.cancel, recording.RUN.progress = cancel, lambda *a: seen.append(a) or (len(seen) == 2 and cancel.set())
    try:
        recording.tool_perf_record("hang", str(program), seconds=1, wine="native")
        raise AssertionError("a cancelled recording must fail")
    except paths.ToolError as error:
        assert "cancelled" in str(error), error
    finally:
        config.OUT, config.PROGRESS_TICKS, os.environ["PATH"] = saved
        recording.RUN.cancel = recording.RUN.progress = None
    assert (tmp_path / "pkill.log").read_text().split() == ["-x", "hang-4242"], "the launched program must be killed"
    assert len(seen) == 2 and seen[1][0] > seen[0][0] and seen[0][1] == recording.deadline(1), seen
    assert not list(out.iterdir()), list(out.iterdir())
    import io
    real, sys.stdout = sys.stdout, io.StringIO()
    registry.TOOLS["t"] = (lambda: recording.progress(1, 2, "half") or {}, {"type": "object"}, None)
    try:
        worker.call("t", {}, 7, "tok")
        line = sys.stdout.getvalue()
    finally:
        sys.stdout = real
        del registry.TOOLS["t"]
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
        wait_until(lambda: list(out.glob("*.trace")), timeout=30)  # the recording is under way: xctrace has started
        say({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        assert json.loads(proc.stdout.readline())["id"] == 2, "ping must be answered during a recording"
        say({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}})
        say({"jsonrpc": "2.0", "id": 3, "method": "ping"})
        assert json.loads(proc.stdout.readline())["id"] == 3, "a cancelled call is not answered (test_cancel_sends_nothing)"
        wait_until(lambda: not list(out.iterdir()))  # the recording stopped and left no files
    finally:
        proc.kill()
        proc.wait()
    assert not list(out.iterdir()), list(out.iterdir())

def test_check_cli(tmp_path):
    """`metal-gpu-trace check` exits 0 for same or improved, 1 for regressed, 2 for a run that cannot be judged, and
    prints one JSON line without the full comparison."""
    from metal_gpu_trace import analysis, config

    def summary(fps, frames=300):
        return {"gpu": {"frames": frames, "fps_estimate": fps, "frame_gpu_ms": {"mean": 4.3, "p95": 8.0},
                        "frame_interval_ms": {"p95": 20.0}},
                "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5},
                             "short_share": {"25": 0.5}, "by_label": []},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}}
    for name, s in {"r1": summary(60.0), "r2": summary(62.0), "ok": summary(61.0), "bad": summary(40.0),
                    "short": summary(61.0, frames=50)}.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(s))
    saved, (config.OUT, config.BASELINES) = (config.OUT, config.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        analysis.tool_perf_baseline("ds", ["r1", "r2"])
    finally:
        config.OUT, config.BASELINES = saved

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
        wait_until(lambda: list(out.glob("*.trace")), timeout=30)  # the recording is under way: xctrace has started
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
    from metal_gpu_trace import config, registry, worker
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    gate, replies, log = threading.Event(), {}, os.environ.get("METAL_TRACE_LOG")
    os.environ["METAL_TRACE_LOG"] = "off"
    registry.TOOLS["slow"] = (lambda: gate.wait(20) and {}, {"type": "object"}, {})

    def submit(i):
        worker.CALLS[i] = threading.Event()
        worker.submit({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "slow", "arguments": {}}},
                   lambda r: replies.__setitem__(i, r))
    try:
        submit(0)
        wait_until(lambda: not worker.QUEUE)  # the worker has taken call 0 and waits on the gate
        for i in range(1, config.MAX_QUEUE + 1):
            submit(i)
        submit(999)
        assert "waiting" in replies[999]["result"]["content"][0]["text"] and 999 not in worker.CALLS, replies.get(999)
        worker.cancel_call(5)
        assert 5 in replies and "cancelled" in replies[5]["result"]["content"][0]["text"], "a queued cancel answers at once"
        worker.cancel_call([1])  # an unhashable id is ignored
        worker.cancel_call(123456)
    finally:
        gate.set()
        worker.stop_worker()
        worker.WORKER.clear()
        del registry.TOOLS["slow"]
        os.environ.pop("METAL_TRACE_LOG") if log is None else os.environ.__setitem__("METAL_TRACE_LOG", log)
    assert sorted(replies) == sorted(set(range(config.MAX_QUEUE + 1)) | {999}), sorted(replies)
    assert not worker.CALLS, worker.CALLS

def test_worker_replies_in_the_era_of_the_request(tmp_path):
    """The replies the worker builds itself (queue full, cancelled before it started) say resultType complete when the
    request is modern, and do not when it is old; CANCELLED is empty once they are out."""
    import threading
    from metal_gpu_trace import config, registry, worker
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    gate, replies = threading.Event(), {}
    registry.TOOLS["slow"] = (lambda: gate.wait(20) and {}, {"type": "object"}, {})

    def submit(i, mid):
        message = modern("tools/call", {"name": "slow", "arguments": {}}, mid=mid) if i % 2 else {
            "jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": "slow", "arguments": {}}}
        worker.CALLS[mid] = threading.Event()
        worker.submit(message, lambda r: replies.__setitem__(mid, r))
    try:
        submit(0, "first")
        wait_until(lambda: not worker.QUEUE)  # the worker took the first call and waits on the gate
        for i in range(1, config.MAX_QUEUE + 1):
            submit(i, f"q{i}")
        submit(1, "full-modern")
        submit(2, "full-legacy")
        worker.cancel_call("q1")
        worker.cancel_call("q2")
        wait_until(lambda: not worker.CANCELLED)  # emptied just after the reply is out
    finally:
        gate.set()
        worker.stop_worker()
        worker.WORKER.clear()
        del registry.TOOLS["slow"]
    for mid, modern_era in (("full-modern", True), ("q1", True), ("full-legacy", False), ("q2", False)):
        assert ("resultType" in replies[mid]["result"]) is modern_era, (mid, replies[mid])
    assert not worker.CALLS and not worker.CANCELLED, (worker.CALLS, worker.CANCELLED)

def test_http_timeout(tmp_path):
    """A client that stalls in the middle of its request is dropped after HTTP_TIMEOUT instead of holding a thread."""
    import socket
    import threading
    from http.server import ThreadingHTTPServer
    from metal_gpu_trace import config, http_transport
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    saved, config.HTTP_TIMEOUT = config.HTTP_TIMEOUT, 1
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), http_transport.http_handler("t" * 32))
    finally:
        config.HTTP_TIMEOUT = saved
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
MODERN_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
               "io.modelcontextprotocol/clientCapabilities": {}}
GOLDEN_MESSAGES += [  # the 2026-07-28 era: the version and capabilities travel in each request's _meta
    {"method": "server/discover", "params": {"_meta": MODERN_META}},
    {"method": "tools/list", "params": {"_meta": MODERN_META}},
    {"method": "tools/call", "params": {"name": "gpu_family", "arguments": {"name": "M3"}, "_meta": MODERN_META}},
    {"method": "resources/read", "params": {"uri": "metal-trace://gpu-families", "_meta": MODERN_META}},
    {"method": "resources/read", "params": {"uri": "metal-trace://runs/none_such", "_meta": MODERN_META}},
    {"method": "ping", "params": {"_meta": MODERN_META}},
    {"method": "tools/list", "params": {"_meta": {**MODERN_META, "io.modelcontextprotocol/protocolVersion": "2099-01-01"}}},
    {"method": "tools/list", "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}},
]

def test_golden_protocol(tmp_path):
    """The server answers a fixed set of messages exactly as recorded in tests/golden/protocol.json."""
    from metal_gpu_trace import config, protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    saved = config.OUT
    config.OUT = tmp_path
    try:
        replies = [protocol.handle({"jsonrpc": "2.0", "id": i, **m}) for i, m in enumerate(GOLDEN_MESSAGES)]
    finally:
        config.OUT = saved
    for reply in replies:
        result = reply.get("result") or {}
        for info in (result.get("serverInfo"), (result.get("_meta") or {}).get("io.modelcontextprotocol/serverInfo")):
            if info:
                info["version"] = "<version>"
    golden("protocol", replies)

def initialize(version):
    """Returns protocol.handle's answer to an initialize that asks for `version`."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    return protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": version}})

def test_legacy_versions(tmp_path):
    """initialize answers a listed old version with itself and any other with the newest old one, 2025-11-25."""
    assert initialize("2025-11-25")["result"]["protocolVersion"] == "2025-11-25"
    assert initialize("1999-01-01")["result"]["protocolVersion"] == "2025-11-25"

ALLOWED_SCHEMA_KEYS = {"type", "properties", "required", "additionalProperties", "description", "items", "enum",
                       "minimum", "maximum", "default", "anyOf", "minItems", "maxItems"}

def test_schemas_are_2020_12_objects(tmp_path):
    """Every inputSchema and outputSchema is an object schema that uses only the basic keywords of JSON Schema 2020-12
    (the default dialect of MCP 2025-11-25), at every depth, and names no other dialect."""
    from metal_gpu_trace import registry
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    from metal_gpu_trace import protocol

    def check(name, schema):
        assert isinstance(schema, dict), name
        unknown = set(schema) - ALLOWED_SCHEMA_KEYS
        assert not unknown, (name, unknown)
        assert "$schema" not in schema, name
        for key, sub in schema.get("properties", {}).items():
            check(f"{name}.{key}", sub)
        if isinstance(schema.get("items"), dict):
            check(f"{name}[]", schema["items"])
        for i, sub in enumerate(schema.get("anyOf", [])):
            check(f"{name}|{i}", sub)
    for tool in protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]:
        for kind in ("inputSchema", "outputSchema"):
            assert tool[kind].get("type") == "object", (tool["name"], kind)
            check(f"{tool['name']}.{kind}", tool[kind])
    assert registry.TOOLS

MODERN_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}

def modern(method, params=None, mid="m", meta=MODERN_META):
    """Returns a request of the 2026-07-28 era: its _meta carries the version and the client capabilities."""
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": {**(params or {}), "_meta": meta}}

def test_discover(tmp_path):
    """server/discover answers with the supported versions, capabilities, instructions and server info, cacheable."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp
    result = protocol.handle(modern("server/discover", mid="d"))["result"]
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == ["2026-07-28"]
    assert result["capabilities"] == {"tools": {}, "resources": {}, "prompts": {}}
    assert result["instructions"] == metal_trace_mcp.INSTRUCTIONS
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"] == {"name": "metal-trace",
                                                                       "version": metal_trace_mcp.__version__}
    assert result["ttlMs"] == 3600000 and result["cacheScope"] == "public"

def test_modern_meta_errors(tmp_path):
    """A modern request needs its version and client capabilities in _meta; initialize always answers the old way."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    no_caps = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
    assert protocol.handle(modern("tools/list", meta=no_caps))["error"]["code"] == -32602
    future = {**MODERN_META, "io.modelcontextprotocol/protocolVersion": "2099-01-01"}
    error = protocol.handle(modern("tools/list", meta=future))["error"]
    assert error["code"] == -32022 and error["data"] == {"supported": ["2026-07-28"], "requested": "2099-01-01"}, error
    assert initialize("2026-07-28")["result"]["protocolVersion"] == "2025-11-25"
    assert protocol.era({"method": "initialize", "params": {"_meta": MODERN_META}}) == "legacy"
    assert protocol.check_modern(modern("tools/list")) is None
    for odd in ({"method": "tools/list", "params": [1]}, {"method": "tools/list", "params": {"_meta": 5}}, [1]):
        assert protocol.era(odd) == "legacy", odd

def test_modern_tools_call(tmp_path):
    """tools/call without initialize gives the same structuredContent as the old way."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    call = {"name": "gpu_family", "arguments": {"name": "M3"}}
    old = protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": call})["result"]
    new = protocol.handle(modern("tools/call", call))["result"]
    assert new["structuredContent"] == old["structuredContent"] and new["resultType"] == "complete"

def test_modern_ping_is_gone(tmp_path):
    """ping no longer exists in the 2026-07-28 era; without the modern _meta it still answers {}."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    assert protocol.handle(modern("ping"))["error"]["code"] == -32601
    assert protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "ping"})["result"] == {}

def test_modern_result_fields(tmp_path):
    """Every modern result says it is complete and names the server; lists and reads add how long they may be cached;
    a missing resource is -32602 there and still -32002 the old way."""
    from metal_gpu_trace import config, protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    info = {"name": "metal-trace", "version": metal_trace_mcp.__version__}
    saved, config.OUT = config.OUT, tmp_path
    (tmp_path / "r1_x.json").write_text("{}")
    try:
        cases = [("tools/list", {}, 3600000, "public"), ("prompts/list", {}, 3600000, "public"),
                 ("resources/list", {}, 3600000, "public"), ("resources/templates/list", {}, 3600000, "public"),
                 ("resources/read", {"uri": "metal-trace://runs/r1_x"}, 0, "private"),
                 ("resources/read", {"uri": "metal-trace://gpu-families"}, 3600000, "public")]
        for method, params, ttl, scope in cases:
            result = protocol.handle(modern(method, params))["result"]
            assert (result["ttlMs"], result["cacheScope"]) == (ttl, scope), (method, params, result.keys())
            assert result["resultType"] == "complete" and result["_meta"]["io.modelcontextprotocol/serverInfo"] == info
        for method, params in (("prompts/get", {"name": "compare-layer"}),
                               ("tools/call", {"name": "gpu_family", "arguments": {"name": "M3"}})):
            result = protocol.handle(modern(method, params))["result"]
            assert result["resultType"] == "complete" and "ttlMs" not in result, (method, result.keys())
        gone = {"uri": "metal-trace://runs/none"}
        assert protocol.handle(modern("resources/read", gone))["error"]["code"] == -32602
        assert protocol.handle(modern("resources/read", {"uri": "metal-trace://nope"}))["error"]["code"] == -32602
        old = protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": gone})
        assert old["error"]["code"] == -32002
        assert protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"].keys() == {"tools"}
    finally:
        config.OUT = saved

def test_tool_shape(tmp_path):
    """Each tool repeats its title at the top level, a tool without parameters says it takes none, and the texts Claude
    Code reads stay under its 4096-character cut."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp
    tools = protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    assert len(tools) == 24
    for tool in tools:
        assert tool["title"] == tool["annotations"]["title"], tool["name"]
        if not tool["inputSchema"].get("properties"):
            assert tool["inputSchema"].get("additionalProperties") is False, tool["name"]
        assert len(tool["description"]) < 4096, tool["name"]
    assert len(metal_trace_mcp.INSTRUCTIONS) < 4096

def hang_call(label, mid, program, token=None):
    """Returns a perf_record tools/call of `program` whose xctrace (hang_stubs) never finishes."""
    params = {"name": "perf_record", "arguments": {"label": label, "program": str(program), "seconds": 1,
                                                   "wine": "native"}}
    if token:
        params["_meta"] = {"progressToken": token}
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": params}

def stdio_cancel_run(tmp_path, cancel, token):
    """Starts the stdio server on a recording that hangs, runs `cancel(say)` to cancel calls, then stops the first
    call and closes stdin. Returns every message the server wrote, and those it wrote after a ping that follows
    the cancels (so after they were all handled)."""
    import threading
    stubs, out, program = hang_stubs(tmp_path)
    proc = subprocess.Popen([sys.executable, "-I", str(PKG / "metal_trace_mcp.py")], text=True, bufsize=1,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=dict(os.environ, METAL_TRACE_OUT=str(out), METAL_TRACE_LOG="off",
                                     PATH=f"{stubs}:{os.environ['PATH']}"))
    guard = threading.Timer(60, proc.kill)
    guard.start()

    def say(message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
    try:
        say(hang_call("hang", 1, program, token))
        wait_until(lambda: any(out.iterdir()))  # xctrace started: the worker is busy with call 1
        cancel(say)
        say({"jsonrpc": "2.0", "id": 99, "method": "ping"})
        before = []
        while (message := json.loads(proc.stdout.readline())).get("id") != 99:
            before.append(message)
        say({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}})
        proc.stdin.close()
        after = [json.loads(line) for line in proc.stdout.read().splitlines()]
        proc.wait(30)
    finally:
        guard.cancel()
        proc.kill()
        proc.wait()
    return before, after

def test_cancel_sends_nothing(tmp_path):
    """Cancelling a queued call writes nothing for it: no reply with its id and no progress for its token."""
    def cancel(say):
        say({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "perf_runs", "arguments": {}, "_meta": {"progressToken": "p2"}}})
        say({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 2}})
    before, after = stdio_cancel_run(tmp_path, cancel, "p1")
    for message in before + after:
        assert message.get("id") != 2, message
        assert message.get("params", {}).get("progressToken") != "p2", message

def test_cancel_running_sends_nothing(tmp_path):
    """Cancelling the running call writes no reply for it and no progress after the cancel."""
    def cancel(say):
        say({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}})
    before, after = stdio_cancel_run(tmp_path, cancel, "p1")
    for message in before + after:
        assert message.get("id") != 1, message
    assert not [m for m in after if m.get("method") == "notifications/progress"], after

@contextlib.contextmanager
def local_http(tmp_path):
    """Serves POST /mcp in this process on a free port, with a recording that hangs (hang_stubs). Yields the server:
    .url_port, .token, .out, .program, .errors (exceptions its handler threads raised), .replies (what its handlers
    wrote, as (status, body)) and .finished (released once per connection the server is done with)."""
    import threading
    from http.server import ThreadingHTTPServer
    from metal_gpu_trace import config, http_transport, worker
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    stubs, out, program = hang_stubs(tmp_path)
    token = "t" * 32
    base = http_transport.http_handler(token)

    class Spy(base):
        def reply(self, code, body=None, kind="application/json"):
            self.server.replies.append((code, body))
            return super().reply(code, body, kind)

    class Server(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            self.errors.append(sys.exc_info()[1])

        def shutdown_request(self, request):
            super().shutdown_request(request)
            self.finished.release()

    server = Server(("127.0.0.1", 0), Spy)
    server.errors, server.replies, server.finished = [], [], threading.Semaphore(0)
    server.token, server.out, server.program, server.port = token, out, program, server.server_address[1]
    saved = config.OUT, os.environ["PATH"], os.environ.get("METAL_TRACE_LOG")
    config.OUT, os.environ["PATH"], os.environ["METAL_TRACE_LOG"] = out, f"{stubs}:{saved[1]}", "off"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        for call_id in list(worker.CALLS):
            worker.cancel_call(call_id)
            wait_until(lambda: not worker.CALLS, timeout=10)
        server.shutdown()
        server.server_close()
        config.OUT, os.environ["PATH"] = saved[:2]
        os.environ.pop("METAL_TRACE_LOG") if saved[2] is None else os.environ.__setitem__("METAL_TRACE_LOG", saved[2])

def http_post(server, body, headers=None, method="POST"):
    """Sends `body` to the server and returns (status, parsed body or None, response headers)."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
    conn.request(method, "/mcp", json.dumps(body) if body is not None else None,
                 {"Content-Type": "application/json", "Authorization": f"Bearer {server.token}", **(headers or {})})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    try:
        return response.status, json.loads(data) if data else None, response
    except ValueError:  # an error page that is not JSON
        return response.status, None, response

def modern_headers(method, name=None, version="2026-07-28"):
    """Returns the request headers the 2026-07-28 Streamable HTTP transport requires."""
    return {"MCP-Protocol-Version": version, "Mcp-Method": method, **({"Mcp-Name": name} if name else {})}

def test_http_legacy_cancel_keeps_reply(tmp_path):
    """Over HTTP the cancelled POST still gets an answer (the old era has no other way to end it): 200 with an isError
    result that says cancelled. This is the documented deviation from the SHOULD of not answering."""
    import threading
    from metal_gpu_trace import worker
    with local_http(tmp_path) as server:
        result = []
        call = hang_call("hang", 7, server.program)
        thread = threading.Thread(target=lambda: result.append(http_post(server, call)))
        thread.start()
        wait_until(lambda: any(server.out.iterdir()))
        cancel = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 7}}
        assert http_post(server, cancel)[:2] == (202, None)
        thread.join(30)
        code, reply, _ = result[0]
        assert code == 200 and reply["result"]["isError"] and "cancelled" in reply["result"]["content"][0]["text"], reply
        assert not worker.CALLS and not worker.CANCELLED, (worker.CALLS, worker.CANCELLED)

def test_http_close_cancels(tmp_path):
    """A modern client that closes its connection cancels the call within a second or two, and the server writes
    nothing back."""
    import socket
    from metal_gpu_trace import worker
    with local_http(tmp_path) as server:
        call = hang_call("hang", "c1", server.program)
        call["params"]["_meta"] = MODERN_META
        body = json.dumps(call).encode()
        head = (f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\nAuthorization: Bearer {server.token}\r\n"
                f"Content-Type: application/json\r\nMCP-Protocol-Version: 2026-07-28\r\nMcp-Method: tools/call\r\n"
                f"Mcp-Name: perf_record\r\nContent-Length: {len(body)}\r\n\r\n").encode()
        sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        sock.sendall(head + body)
        wait_until(lambda: any(server.out.iterdir()))  # the recording started
        sock.close()
        wait_until(lambda: "c1" not in worker.CALLS, timeout=10)  # poll, stop and clean-up, with room for a slow CI
        assert server.finished.acquire(timeout=5), "the handler thread must end"
        assert server.replies == [] and server.errors == [], (server.replies, server.errors)
        wait_until(lambda: not worker.CANCELLED)  # emptied just after the reply is out

def test_http_legacy_headers(tmp_path):
    """The old era checks MCP-Protocol-Version when it is sent: an unknown one is a 400, none is taken as 2025-03-26."""
    with local_http(tmp_path) as server:
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        assert http_post(server, ping, {"MCP-Protocol-Version": "1999-01-01"})[0] == 400
        assert http_post(server, ping)[:2] == (200, {"jsonrpc": "2.0", "id": 1, "result": {}})
        assert http_post(server, ping, {"MCP-Protocol-Version": "2025-11-25"})[0] == 200
        assert http_post(server, ping, {"MCP-Protocol-Version": "2026-07-28"})[0] == 400, "a modern version needs _meta"

def test_http_modern_headers(tmp_path):
    """A modern POST needs MCP-Protocol-Version and Mcp-Method that match its body, and Mcp-Name on tools/call,
    prompts/get and resources/read: a failure is 400 -32020, an unknown version 400 -32022, an unknown method 404."""
    import base64
    with local_http(tmp_path) as server:
        def post(method, params=None, headers=None, meta=MODERN_META):
            body = modern(method, params, meta=meta)
            return http_post(server, body, headers)
        ok = modern_headers("tools/list")
        assert post("tools/list", headers=ok)[0] == 200
        for missing in ("MCP-Protocol-Version", "Mcp-Method"):
            status, reply, _ = post("tools/list", headers={k: v for k, v in ok.items() if k != missing})
            assert (status, reply["error"]["code"]) == (400, -32020), missing
        for bad in ({"Mcp-Method": "tools/call"}, {"MCP-Protocol-Version": "2025-11-25"}):
            status, reply, _ = post("tools/list", headers={**ok, **bad})
            assert (status, reply["error"]["code"]) == (400, -32020), bad
        call = {"name": "gpu_family", "arguments": {"name": "M3"}}
        named = modern_headers("tools/call", "gpu_family")
        assert post("tools/call", call, named)[0] == 200
        assert post("tools/call", call, modern_headers("tools/call", "=?base64?" + base64.b64encode(b"gpu_family").decode() + "?="))[0] == 200, "Base64 sentinel"
        for headers in (modern_headers("tools/call"), modern_headers("tools/call", "other"),
                        modern_headers("tools/call", "=?base64?!!!?=")):
            status, reply, _ = post("tools/call", call, headers)
            assert (status, reply["error"]["code"]) == (400, -32020), headers
        prompt = {"name": "compare-layer"}
        assert post("prompts/get", prompt, modern_headers("prompts/get", "compare-layer"))[0] == 200
        for headers in (modern_headers("prompts/get"), modern_headers("prompts/get", "x")):
            assert post("prompts/get", prompt, headers)[1]["error"]["code"] == -32020
        read = {"uri": "metal-trace://gpu-families"}
        assert post("resources/read", read, modern_headers("resources/read", "metal-trace://gpu-families"))[0] == 200
        for headers in (modern_headers("resources/read"), modern_headers("resources/read", "metal-trace://x")):
            assert post("resources/read", read, headers)[1]["error"]["code"] == -32020
        future = {**MODERN_META, "io.modelcontextprotocol/protocolVersion": "2099-01-01"}
        status, reply, _ = post("tools/list", headers=modern_headers("tools/list", version="2099-01-01"), meta=future)
        assert status == 400 and reply["error"]["code"] == -32022, reply
        assert reply["error"]["data"] == {"supported": ["2026-07-28"], "requested": "2099-01-01"}
        for method in ("no/such/method", "ping"):
            status, reply, _ = post(method, headers=modern_headers(method))
            assert (status, reply["error"]["code"]) == (404, -32601), method
        discover = {"jsonrpc": "2.0", "id": 1, "method": "server/discover"}  # no params, so no _meta to match
        assert http_post(server, discover, modern_headers("server/discover"))[1]["error"]["code"] == -32020
        assert http_post(server, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, modern_headers("ping"))[0] == 400, \
            "an old-era body is held to the old versions, which 2026-07-28 is not"
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {"_meta": MODERN_META}}
        assert http_post(server, notification)[0] == 202, "the spec defines no header rules for a modern notification"

def test_http_delete_is_405(tmp_path):
    """DELETE (the old way to end a session) is 405 Method Not Allowed, not 501."""
    with local_http(tmp_path) as server:
        assert http_post(server, None, method="DELETE")[0] == 405

def test_http_notification_202_empty(tmp_path):
    """A notification is answered 202 with an empty body: Content-Length 0 and no Content-Type."""
    with local_http(tmp_path) as server:
        status, body, response = http_post(server, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert (status, body) == (202, None)
        assert response.getheader("Content-Length") == "0" and response.getheader("Content-Type") is None

def test_tool_descriptions_have_no_indent(tmp_path):
    """No line of a tool description starts with whitespace, whatever the Python (before 3.13 docstrings keep their
    indent)."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    for tool in protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]:
        assert not any(line[:1].isspace() for line in tool["description"].splitlines()), tool["name"]


def test_http_cancel_hits_its_own_call():
    """Two HTTP clients may send the same JSON-RPC id. Closing A's connection stops A's running call and leaves B's
    queued call with that id alone: cancellation follows the call, not its id."""
    import threading
    import time
    from metal_gpu_trace import metal_trace_mcp, recording, registry, worker  # noqa: F401  (configures worker)
    from support import wait_until
    runs = []

    def tool():
        runs.append(1)
        if len(runs) == 1:  # A: runs until cancelled
            deadline = time.monotonic() + 5
            while not recording.cancelled() and time.monotonic() < deadline:
                time.sleep(0.01)
        return {"cancelled": recording.cancelled()}

    registry.TOOLS["same_id"] = (tool, {"type": "object"}, {})
    replies = {}
    try:
        events = {}
        for side in ("a", "b"):
            message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "same_id", "arguments": {}}}
            events[side] = (message, threading.Event())
            worker.CALLS[1] = events[side][1]
            worker.submit(message, lambda reply, side=side: replies.__setitem__(side, reply), events[side][1])
            if side == "a":
                wait_until(lambda: runs)
        worker.cancel_item(*events["a"])
        wait_until(lambda: len(replies) == 2, timeout=10)
    finally:
        del registry.TOOLS["same_id"]
        worker.CALLS.pop(1, None)
    assert replies["a"]["result"]["structuredContent"] == {"cancelled": True}, replies
    assert replies["b"]["result"]["structuredContent"] == {"cancelled": False}, replies


def test_worker_survives_a_failing_reply():
    """A reply callback that raises (a client gone mid-write) is logged and the worker thread goes on with the next
    call instead of dying and leaving every later call queued for ever."""
    from metal_gpu_trace import metal_trace_mcp, registry, worker  # noqa: F401  (configures worker)
    from support import wait_until
    registry.TOOLS["quick"] = (lambda: {}, {"type": "object"}, {})
    got = []
    try:
        def broken(reply):
            raise BrokenPipeError("client gone")
        for i, reply in enumerate((broken, got.append)):
            worker.submit({"jsonrpc": "2.0", "id": f"r{i}", "method": "tools/call",
                           "params": {"name": "quick", "arguments": {}}}, reply)
        wait_until(lambda: got, timeout=10)
    finally:
        del registry.TOOLS["quick"]
    assert got[0]["id"] == "r1", got


def test_cancel_item_takes_a_queued_call_out():
    """cancel_item on a queued call takes it out of the queue unanswered (its HTTP client is gone) and leaves the
    CALLS entry of another client that uses the same id."""
    import threading
    from metal_gpu_trace import metal_trace_mcp, registry, worker  # noqa: F401  (configures worker)
    from support import wait_until
    gate, started = threading.Event(), threading.Event()
    registry.TOOLS["gate"] = (lambda: started.set() or gate.wait(10) and {}, {"type": "object"}, {})
    replies = []
    try:
        worker.submit({"jsonrpc": "2.0", "id": "g", "method": "tools/call", "params": {"name": "gate", "arguments": {}}},
                      replies.append)
        wait_until(started.is_set)
        queued = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "gate", "arguments": {}}}
        mine, other = threading.Event(), threading.Event()
        worker.submit(queued, replies.append, mine)
        worker.CALLS[7] = other  # a second client sent id 7 after this one
        worker.cancel_item(queued, mine)
        assert all(item is None or item[0] is not queued for item in worker.QUEUE), worker.QUEUE
        assert worker.CALLS.get(7) is other and mine.is_set() and not other.is_set()
        gate.set()
        wait_until(lambda: replies, timeout=10)
    finally:
        gate.set()
        del registry.TOOLS["gate"]
        worker.CALLS.pop(7, None)
    assert [r["id"] for r in replies] == ["g"], replies


def test_bad_arguments_vs_internal():
    """A call that breaks the tool's schema (an unknown or a missing argument) is `bad arguments`; a TypeError raised
    inside a tool is an internal error, not the client's fault."""
    from metal_gpu_trace import metal_trace_mcp, registry, worker  # noqa: F401  (configures worker)

    def text(result):
        assert result["isError"], result
        return result["content"][0]["text"]
    assert text(worker.call("gpu_family", {"nombre": "M3"})).startswith("bad arguments: unknown argument nombre")
    assert text(worker.call("gpu_family", {})).startswith("bad arguments: missing argument name")
    registry.TOOLS["broken"] = (lambda: None + 1, {"type": "object"}, {})
    try:
        assert text(worker.call("broken", {})) == "internal error: TypeError"
    finally:
        del registry.TOOLS["broken"]


def test_envelope():
    """Each message is classified before it is dispatched: a request needs jsonrpc 2.0 and a string method (else
    -32600), a response from the client is ignored without a reply."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    for bad in ({"jsonrpc": "2.0", "id": 1}, {"jsonrpc": "2.0", "id": 1, "method": 5}, {"id": 1, "method": "ping"},
                {"jsonrpc": "1.0", "id": 1, "method": "ping"}):
        reply = protocol.handle(bad)
        assert reply["error"]["code"] == -32600 and reply["id"] == 1, (bad, reply)
    assert protocol.handle({"jsonrpc": "2.0", "id": 1, "result": {}}) is None
    assert protocol.handle({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "x"}}) is None
    assert protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "ping"}) == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert protocol.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_http_unreadable_body_is_a_parse_error(tmp_path):
    """A body that is not UTF-8, or nests so deep that the parser gives up, is answered 400 with -32700, and no
    exception reaches the handler thread (which would print a traceback)."""
    import http.client
    with local_http(tmp_path) as server:
        for body in (b'{"jsonrpc": "2.0", "id": 1, "method": "\xff\xfe"}', b"[" * 100000 + b"]" * 100000):
            conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
            conn.request("POST", "/mcp", body, {"Authorization": f"Bearer {server.token}"})
            response = conn.getresponse()
            reply = json.loads(response.read())
            conn.close()
            # Python 3.15's parser reads any depth: its answer is then an ordinary -32600 for a message that is a list
            code = -32700 if response.status == 400 else -32600
            assert response.status in (200, 400) and reply["error"]["code"] == code and reply["id"] is None, (response.status, reply)
            assert response.status == 400 or body.startswith(b"["), "an unreadable body must not get past the parser"
        assert not server.errors, server.errors


def test_prompt_dispatch():
    """prompts/get renders the prompt it is asked for, not always compare-layer, and prompts/list does not show the
    render function."""
    from metal_gpu_trace import protocol, registry
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    registry.PROMPTS["t"] = {"description": "t", "arguments": [], "render": lambda: "T"}
    try:
        got = protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": {"name": "t"}})["result"]
        assert got["description"] == "t" and got["messages"][0]["content"]["text"] == "T", got
        listed = protocol.handle({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"})["result"]["prompts"]
        assert {p["name"] for p in listed} == {"compare-layer", "t"} and all("render" not in p for p in listed), listed
        assert "Compare drawstress" in protocol.handle(
            {"jsonrpc": "2.0", "id": 3, "method": "prompts/get", "params": {"name": "compare-layer"}}
        )["result"]["messages"][0]["content"]["text"]
    finally:
        del registry.PROMPTS["t"]


def test_http_reply_broken_pipe():
    """A client that closed its connection before the reply is written costs one log line, not an exception."""
    from metal_gpu_trace import http_transport, logs
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)

    class Gone:
        def write(self, data):
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self):
            pass
    handler_class = http_transport.http_handler("t" * 32)
    handler = handler_class.__new__(handler_class)  # no socket: only wfile is used
    handler.wfile, handler.request_version, handler.requestline, handler.command = Gone(), "HTTP/1.1", "POST /mcp HTTP/1.1", "POST"
    seen, real = [], logs.log
    logs.log = seen.append
    try:
        assert handler.reply(200, {}) is None
    finally:
        logs.log = real
    assert seen == ["client closed the connection"], seen


def test_instructions_spacing():
    """The text clients read on connecting has a space after each full stop: no `browser.trace_tables`."""
    import re
    from metal_gpu_trace import metal_trace_mcp
    assert not re.search(r"[a-z]\.(trace|perf|capture|gpu|workload)_", metal_trace_mcp.INSTRUCTIONS)


def test_panel_html_is_cached_and_patched_once():
    """panel_html(connect_self) returns the page, with the CSP that lets the live panel fetch its own data when
    connect_self is true, and reads the file once per variant."""
    from metal_gpu_trace import panel
    plain, live = panel.panel_html(False), panel.panel_html(True)
    assert "default-src 'none'" in plain and "connect-src" not in plain, "the saved panel loads nothing"
    assert live == plain.replace("default-src 'none'", "default-src 'none'; connect-src 'self'") != plain
    assert panel.panel_html(True) is live and panel.panel_html.cache_info().hits >= 1


def test_http_modern_notification_without_meta(tmp_path):
    """A notification under the 2026-07-28 header but without _meta gets 202: the spec puts _meta on requests only and
    defines no header rules for notifications. A request without _meta under that header is still refused (400)."""
    with local_http(tmp_path) as server:
        notification = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 99}}
        assert http_post(server, notification, {"MCP-Protocol-Version": "2026-07-28"})[:2] == (202, None)
        assert http_post(server, {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                         {"MCP-Protocol-Version": "2026-07-28"})[0] == 400


def test_http_close_spares_another_client_with_the_same_id(tmp_path):
    """Two clients over HTTP use the same id: A's recording runs, B's call waits in the queue. A closes its connection;
    A's call stops and B still gets 200 with its own result."""
    import socket
    import threading
    from metal_gpu_trace import worker
    with local_http(tmp_path) as server:
        call = hang_call("hang", "same", server.program)
        call["params"]["_meta"] = MODERN_META
        body = json.dumps(call).encode()
        head = (f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\nAuthorization: Bearer {server.token}\r\n"
                f"Content-Type: application/json\r\nMCP-Protocol-Version: 2026-07-28\r\nMcp-Method: tools/call\r\n"
                f"Mcp-Name: perf_record\r\nContent-Length: {len(body)}\r\n\r\n").encode()
        sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        sock.sendall(head + body)
        wait_until(lambda: any(server.out.iterdir()))  # A's recording started
        b_call = modern("tools/call", {"name": "gpu_family", "arguments": {"name": "M3"}})
        b_call["id"] = "same"
        result = []
        thread = threading.Thread(target=lambda: result.append(
            http_post(server, b_call, modern_headers("tools/call", "gpu_family"))))
        thread.start()
        wait_until(lambda: len(worker.QUEUE) > 0)  # B waits behind A
        sock.close()
        thread.join(30)
        status, reply, _ = result[0]
        assert status == 200 and not reply["result"].get("isError"), reply
        assert reply["result"]["structuredContent"]["family"] == "Apple9", reply


def test_tool_schemas_match_signatures(tmp_path):
    """Every argument a tool function names is in its inputSchema (tools/call refuses names the schema lacks, so a
    missing one would break calls that used to work), every argument without a default is required, and a schema
    name the function does not take only appears when the function forwards **kwargs."""
    import inspect
    from metal_gpu_trace import registry
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    for name, (function, schema, _) in registry.TOOLS.items():
        parameters = inspect.signature(function).parameters.values()
        named = {p.name: p for p in parameters if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
        forwards = any(p.kind == p.VAR_KEYWORD for p in parameters)
        properties, required = set(schema.get("properties", {})), set(schema.get("required", []))
        assert set(named) <= properties, (name, set(named) - properties)
        assert {n for n, p in named.items() if p.default is p.empty} <= required, name
        assert forwards or properties <= set(named), (name, properties - set(named))


def test_arguments_must_be_an_object(tmp_path):
    """tools/call with arguments that are not an object is a bad call, not a server fault."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    for arguments in (5, ["name"], "M3"):
        reply = protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": "gpu_family", "arguments": arguments}})
        assert reply["result"]["isError"], arguments
        assert "bad arguments: arguments must be an object" in reply["result"]["content"][0]["text"], reply


def test_http_modern_cancel_notification_cancels_nothing(tmp_path):
    """Under the 2026-07-28 header a client cancels by closing its connection, so a notifications/cancelled is
    accepted (202) and ignored: it cannot stop another client's call that shares the id."""
    import threading
    with local_http(tmp_path) as server:
        result = []
        call = hang_call("hang", 8, server.program)
        thread = threading.Thread(target=lambda: result.append(http_post(server, call)))
        thread.start()
        wait_until(lambda: any(server.out.iterdir()))
        cancel = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 8}}
        assert http_post(server, cancel, {"MCP-Protocol-Version": "2026-07-28"})[:2] == (202, None)
        from metal_gpu_trace import worker
        assert 8 not in worker.CANCELLED and not worker.CALLS[8].is_set(), "the old-era call goes on"
        worker.cancel_call(8)
        thread.join(30)


def test_experiments_refuse_label(tmp_path):
    """perf_ab, perf_cold_warm and perf_sweep name their runs themselves: a label they used to drop silently is now an
    unknown argument, refused before anything records."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    for tool, arguments in (("perf_ab", {"name": "t", "env_a": "", "env_b": "X=1"}), ("perf_cold_warm", {"name": "t"}),
                            ("perf_sweep", {"name": "t", "variable": "dim", "values": [1, 2]})):
        reply = protocol.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": tool, "arguments": {**arguments, "label": "x"}}})
        assert "bad arguments: unknown argument label" in reply["result"]["content"][0]["text"], (tool, reply)
