# When it fails

**Reader:** people who need to know why a client got a given error, status or silence. Reviewed 2026-11-16.

[Index](./index.md)

**In short:** a bad request does not stop the server. A malformed request gets a protocol error, a failed tool gets an "error result", and sometimes the answer is silence because the client left or cancelled.

| What goes wrong | What the client gets | What the server does | Line |
|---|---|---|---|
| A line that is not JSON, or not UTF-8 (stdio) | `-32700 parse error`, `id: null` | Goes on to the next line | `stdio.py::serve_stdio`, `:50-51` |
| JSON that is not an object (`[1]`); no `jsonrpc: "2.0"` or text `method` | `-32600 Invalid Request` | | `protocol.py::handle`, `:94-95` |
| An unknown method | `-32601 unknown method <m>` | | `:173` |
| An unknown tool | `-32602 unknown tool <name>`: a JSON-RPC error, not an `isError` result | | `:167-169` |
| Wrong arguments to a known tool | An `isError` result `bad arguments: ...` | | `worker.py::_take` |
| A tool raises something expected / something else | An `isError` result with its text / `internal error: <ExceptionName>` | One log line, `error` | `:165-168`, `:171` |
| 64 calls are waiting | An `isError` result at once | Nothing queued | `:53-57` |
| Cancelled while queued | stdio: nothing. HTTP: an `isError` result `the call was cancelled before it started` | Leaves the queue | `:101-111` |
| Cancelled while running | stdio: nothing. HTTP old era: an `isError` result; modern: nothing, connection closed | The tool stops at its next look; a recording cleans up | `:112-115`; `http_transport.py::do_POST` |
| The `metal-gpu-trace.json` is wrong | Every tool, and every `metal-trace://runs/...` read, answers with its message | Keeps running; resources answer `-32603` | `worker.py::_take`, `protocol.py::handle` |
| An exception inside `protocol.handle` | `-32603 internal error` | One log line; stdio and HTTP go on | `stdio.py::serve_stdio`, `http_transport.py::do_POST`, `protocol.py:191-198` |
| Client left while the worker wrote (stdio) | Nobody to tell | Log `reply to <id> failed`; the thread lives | `worker.py::work` |
| Client left while HTTP wrote | Nobody to tell | Log `client closed the connection` | `http_transport.py::reply` |
| A client stalls mid-request (HTTP) | Connection closed after 15 s | The thread ends | `:93` |
| `--http` without a token, or under 16 characters | A message on stderr, exit status 2 | Does not start | `:186-189` |
| `--http --port` with no number, or text | `usage: metal-gpu-trace --http [--port N]`, exit status 2 | | `metal_trace_mcp.py::main` |
| stdin closes with calls waiting (stdio) | | All finish first, then the process ends | `stdio.py::serve_stdio`, `worker.py::stop_worker` |

All **confirmed** from the lines named, **not reproduced** live (no request sent). The tests per row are named in [Startup](./startup.md), [Worker](./worker.md) and [HTTP](./http.md) (`tests/test_server.py` unless said otherwise) and were not run. HTTP statuses (404, 403, 401, 413, 400) are in [HTTP](./http.md).
