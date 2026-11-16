# Evidence: the commands and their real output

**Reader:** people who want to check a number or a line of this guide, or see what was not reproduced. Reviewed 2026-11-16.

Español: [Evidencia](../../es/guides/servidor-y-transporte/evidencia.md) · [Index](./index.md)

**In short:** every number in this guide comes from a command listed here, with its real output. All were read-only searches over the code and the recorded test replies; the server was never started, and the last section lists what was not reproduced.

Collected on 2026-11-16 on an Apple silicon Mac. The session could run only read-only commands (`rg`, `sed`, `jq`), not Python or the server: the replies in E9 are the ones `tests/golden/protocol.json` holds, which `test_golden_protocol` records by calling `protocol.handle` and compares on every run.

## E1 Every status the HTTP handler answers, with its line

```text
$ rg -n "self\.reply\((404|403|401|413|405|202)|self\.reply\(400" src/metal_gpu_trace/http_transport.py | cut -c1-130
120:                return self.reply(404)
122:                return self.reply(403)
124:                return self.reply(401)
129:                return self.reply(413)
133:                return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
142:                return self.reply(202)
168:            self.reply(202 if reply is None else 200, reply)
171:            self.reply(405)  # this server has no sessions to end
174:            self.reply(405)  # no event stream: this endpoint only answers POST
```

The line order (120, 122, 124, 129, 133) is the order of the checks in [Figure 2](./http.md). The 200 of a call is at `:162`, `reply` at `:95`. Sending a request to see each status was **not reproduced**; `tests/test_server.py:315-323` asserts 401, 403, 405, 404 and 202 (E8).

## E2 What `check_headers` refuses, and with which code

```text
$ rg -n "refuse\(|return 400" src/metal_gpu_trace/http_transport.py | rg -v "def refuse" | cut -c1-135
63:            return refuse(400, -32600, f"unsupported MCP-Protocol-Version {version}")
71:        return refuse(400, -32020, "Header mismatch: MCP-Protocol-Version and Mcp-Method are required")
73:        return refuse(400, -32020, "Header mismatch: Mcp-Method does not match the method")
75:        return refuse(400, -32020, "Header mismatch: MCP-Protocol-Version does not match _meta")
77:        return 400, protocol.version_error(mid, version)
79:        return refuse(404, -32601, f"unknown method {method}")
81:        return refuse(400, -32020, f"Header mismatch: Mcp-Name does not match params.{NAMED[method]}")
```

Seven refusals, one per refusing row of the `check_headers` table in [HTTP](./http.md) (the let-through rows return `None`). Line 77 is the `-32022` of `protocol.version_error` (`protocol.py:52-55`).

## E3 The limits the server applies

```text
$ rg -n "^(MAX_QUEUE|MIN_TOKEN|MAX_BODY|HTTP_TIMEOUT|MAX_TEXT) " src/metal_gpu_trace/config.py
45:MAX_TEXT = 40_000
52:MAX_QUEUE = 64
55:MIN_TOKEN = 16
56:MAX_BODY = 1_000_000
57:HTTP_TIMEOUT = 15  # seconds a client may take to send its request

$ rg -n "^POLL_S" src/metal_gpu_trace/http_transport.py | cut -c1-40
13:POLL_S = 0.5  # how often a modern PO
```

The second line is cut at 40 characters by `cut`. Numbers used: 40 000 characters per result, 64 calls waiting, a token of at least 16, a body of at most 1 000 000 bytes, 15 s to send a request, 0.5 s between looks for a client that left.

## E4 How many tools, how many write, which ask the person

```text
$ rg -c '^    "[a-z_]+": \(' src/metal_gpu_trace/registry.py
26

$ jq -c '[.[2].result.tools[]|.annotations.readOnlyHint]|group_by(.)|map({readOnly:.[0],n:length})' tests/golden/protocol.json
[{"readOnly":false,"n":10},{"readOnly":true,"n":16}]

$ jq -r '[.[2].result.tools[]|select(.annotations.destructiveHint==true)|.name]|join(" ")' tests/golden/protocol.json
perf_record perf_baseline_record perf_sweep perf_ab perf_cold_warm

$ jq -c '.[2].result.tools|map(select(._meta))|map([.name,._meta])' tests/golden/protocol.json
[["workload_fetch",{"anthropic/requiresUserInteraction":true}],["presentmon_install",{"anthropic/requiresUserInteraction":true}]]
```

The first command counts the rows of `TOOLS` (26); the others read the `tools/list` reply the test recorded (third message), not a live server.

## E5 How the command line is read

```text
$ rg -n "sys\.argv" src/metal_gpu_trace/metal_trace_mcp.py | cut -c1-120
82:    if sys.argv[1:] == ["--version"]:
86:    if sys.argv[1:2] == ["check"]:
87:        sys.exit(check_cli(sys.argv[2:]))
88:    if sys.argv[1:2] == ["--http"]:
90:            port = int(sys.argv[3]) if sys.argv[2:3] == ["--port"] else 8765

$ rg -n "METAL_TRACE_TOKEN|MIN_TOKEN" src/metal_gpu_trace/http_transport.py | cut -c1-150
186:    token = os.environ.get("METAL_TRACE_TOKEN", "")
187:    if len(token) < config.MIN_TOKEN:
188:        print(f"metal-gpu-trace: set METAL_TRACE_TOKEN to a secret of at least {config.MIN_TOKEN} characters", file=sys.stderr)
```

Only `--port` is looked at after `--http` ([limit 4](./limits.md)). The variable's value is read, never printed. … recortado (line 183, the docstring).

## E6 Every place that writes a log line

At the time of the measurement, before 24490ec, so the `stdio.py` line numbers below are the old ones (the stdio internal-error line is `stdio.py:53` now, after c4b4a7c).

```text
$ rg -n "logs\.log" src/metal_gpu_trace | cut -c1-140
src/metal_gpu_trace/stdio.py:49:            logs.log(f"internal error {type(error).__name__}")
src/metal_gpu_trace/http_transport.py:106:                logs.log("client closed the connection")
src/metal_gpu_trace/http_transport.py:166:                logs.log(f"internal error {type(error).__name__}")
src/metal_gpu_trace/http_transport.py:191:    logs.log(f"serving http://127.0.0.1:{server.server_address[1]}/mcp")
src/metal_gpu_trace/protocol.py:196:        logs.log(f"internal error {type(error).__name__}")
src/metal_gpu_trace/worker.py:74:            logs.log(f"reply to {message.get('id')!r} failed: {type(error).__name__}")
src/metal_gpu_trace/worker.py:171:    logs.log(f"{name} {'error' if result.get('isError') else 'ok'} in {time.monotonic() - started:.1f} s")
```

Seven sites; none interpolates an argument, path, label or token (the only client text is the request id at `worker.py:74`). `logs.py:8` compares `METAL_TRACE_LOG` with `"off"` exactly.

## E7 What the standard library does under `ThreadingHTTPServer`

```text
$ rg -n "daemon_threads|protocol_version = \"" <Command Line Tools>/.../python3.9/http/server.py
145:    daemon_threads = True
623:    protocol_version = "HTTP/1.0"
```

Path shortened. It is the Python 3.9 of the macOS command line tools, the project's floor ([ADR-0003](../../adr/0003-python-3-9-floor.md)); other versions were not read.

## E8 The tests that pin the behaviour described here

```text
$ rg -n "def test_http|def test_queue|def test_cancel|def test_progress|def test_golden|def test_discover" tests/test_server.py | cut -c1-90
178:def test_progress_and_cancel(tmp_path)
276:def test_http(tmp_path)
354:def test_queue(tmp_path)
473:def test_http_timeout(tmp_path)
525:def test_golden_protocol(tmp_path)
586:def test_discover(tmp_path)
718:def test_cancel_sends_nothing(tmp_path)
729:def test_cancel_running_sends_nothing(tmp_path)
… recortado: 799, 817, 838, 847, 893, 898, 914, 970, 1031, 1067, 1097, 1107 and 1165 (the same pattern; most cited with their line in HTTP and Worker)

$ sed -n 315,323p tests/test_server.py | cut -c1-110
        assert post(ping, {"Authorization": "Bearer nope"})[0] == 401
        assert post(ping, {"Authorization": ""})[0] == 401
        assert post(ping, {"Origin": "http://evil.example"})[0] == 403
        assert post(ping, {"Origin": "http://localhost.evil.example"})[0] == 403
        assert post(ping, {"Host": "evil.example"})[0] == 403
        assert post(ping, {"Origin": f"http://localhost:{port}"})[0] == 200
        assert post(None, method="GET")[0] == 405
        assert post(ping, path="/other")[0] == 404
        assert post({"jsonrpc": "2.0", "method": "notifications/initialized"}) == (202, None)
```

These are the assertions of `test_http` for 401, 403, 405, 404 and 202; **not run** for this guide. It also asserts that a start without a token, and with the token `short`, returns exit status 2 (`tests/test_server.py:289-291`).

## E9 What the server answers, as the tests recorded it

```text
$ jq -c '[.[0,1]|.result.protocolVersion]' tests/golden/protocol.json
["2025-06-18","2025-11-25"]

$ jq -c 'to_entries[] | select(.value.error) | [.key, .value.error.code, .value.error.message[0:44]]' tests/golden/protocol.json
[7,-32002,"Resource not found"]
[9,-32602,"unknown tool no_such_tool"]
[10,-32601,"unknown method no/such/method"]
[16,-32602,"Resource not found"]
[17,-32601,"unknown method ping"]
[18,-32022,"Unsupported protocol version"]
[19,-32602,"_meta must hold io.modelcontextprotocol/prot"]

$ jq -c 'to_entries[12:15][] | [.key, .value.result.resultType, .value.result.ttlMs, .value.result.cacheScope]' tests/golden/protocol.json
[12,"complete",3600000,"public"]
[13,"complete",3600000,"public"]
[14,"complete",null,null]

$ jq -c '[(.[3].result.resources|length), (.[4].result.resourceTemplates|length), (.[5].result.prompts|map(.name))]' tests/golden/protocol.json
[5,1,["compare-layer","diagnose-stutter","bisect-regression"]]
```

Message 0 asked for `2025-06-18` and got it; message 1 asked for `1999-01-01` and got the newest old version, `2025-11-25`. Errors: 7 is `resources/read` of a missing run in the old era (`-32002`), 16 the same in the modern era (`-32602`), 17 is modern `ping`, 18 an unsupported version, 19 a modern request whose `_meta` lacks the version and capabilities. Messages 12 to 14 are `server/discover`, `tools/list` and a `tools/call` in the modern era: the first two may be cached for an hour (3 600 000 ms, public); the call says nothing, as a result is not cacheable. Message 3 lists five resources, 4 one template (the recordings), 5 three prompts.

## What was not reproduced

- Starting the server, over stdio or HTTP, and any request to it: `initialize` and `tools/list` by stdio and by HTTP with `curl` and a test token, and the three refusals live (404, 403, 401). E1 and E8 give the lines and tests; E9 the recorded replies.
- That `tests/test_architecture.py` and the rest of the suite are green: no test was run.
- A cancel on a real recording, over stdio or HTTP (needs a recording, [Recording](../recording/index.md)).
- Invalid UTF-8 on stdin, a port in use or out of range, a chunked body, a `PUT` or `HEAD` (limits 2, 4 and 8, and the row 0 note in [HTTP](./http.md)): read, not run. The stdin case was read as it was at the time of the measurement, before 24490ec; it was fixed in c4b4a7c (limit 2), and its test was not run here.
- The official MCP SDK as a client (`tests/conformance/`): needs the SDK, not run.
- Where a client shows the server's stderr.
