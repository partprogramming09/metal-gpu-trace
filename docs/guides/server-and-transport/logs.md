# Logs

**Reader:** people who add or read the server's log lines. Reviewed 2026-11-16.

[Index](./index.md)

**In short:** the server writes a short line to stderr when a tool finishes or something breaks. Never what you asked for, a path or the token: only names, results and durations. stdout is reserved for the conversation with the client.

`logs.py` (`logs.py::log`) prints `metal-trace: <message>` to stderr and flushes, unless `METAL_TRACE_LOG` is exactly `off`. `send` (`stdio.py::send`) is the only writer of stdout; `serve_http` prints one more line directly (`http_transport.py::serve_http`, the token message), which `METAL_TRACE_LOG=off` does **not** silence.

The docstring and the README say "one stderr line per tool call"; the code has seven callers ([E6](./evidence.md#e6-every-place-that-writes-a-log-line)):

| Message | When | Line |
|---|---|---|
| `metal-trace: <tool> ok in <s> s` or `... error in <s> s` | A tool call ended (`error` = an `isError` result) | `worker.py::cut` |
| `metal-trace: serving http://127.0.0.1:<port>/mcp` | HTTP started | `http_transport.py::serve_http` |
| `metal-trace: internal error <ExceptionName>` | Exception in `protocol.handle` (stdio reader, HTTP handler) or `protocol.answer` (worker) | `stdio.py::serve_stdio`, `http_transport.py::do_POST`, `protocol.py::answer` |
| `metal-trace: reply to <id> failed: <ExceptionName>` | The worker could not write a reply | `worker.py::work` |
| `metal-trace: client closed the connection` | HTTP: the client left during the write | `http_transport.py::reply` |

No line holds an argument, label, path, token or result: only a tool name, status, duration, an exception type (never its text) and, once, a client-chosen request id. **Confirmed** for the seven sites; nothing enforces it, so a new `logs.log(f"... {value}")` would break it silently ([Touching it](./touching.md)). Where stderr ends up depends on the launching client: **not verified**.
