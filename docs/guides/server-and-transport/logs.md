# Logs

**Reader:** people who add or read the server's log lines. Reviewed 2026-11-16.

Español: [Logs](../../es/guides/servidor-y-transporte/logs.md) · [Index](./index.md)

**In short:** the server writes a short line to stderr when a tool finishes or something breaks. Never what you asked for, a path or the token: only names, results and durations. stdout is reserved for the conversation with the client.

`logs.py` (`:6-9`) prints `metal-trace: <message>` to stderr and flushes, unless `METAL_TRACE_LOG` is exactly `off`. `send` (`stdio.py:12`) is the only writer of stdout; `serve_http` prints one more line directly (`http_transport.py:188`, the token message), which `METAL_TRACE_LOG=off` does **not** silence.

The docstring and the README say "one stderr line per tool call"; the code has seven callers ([E6](./evidence.md#e6-every-place-that-writes-a-log-line)):

| Message | When | Line |
|---|---|---|
| `metal-trace: <tool> ok in <s> s` or `... error in <s> s` | A tool call ended (`error` = an `isError` result) | `worker.py:171` |
| `metal-trace: serving http://127.0.0.1:<port>/mcp` | HTTP started | `http_transport.py:191` |
| `metal-trace: internal error <ExceptionName>` | Exception in `protocol.handle` (stdio reader, HTTP handler) or `protocol.answer` (worker) | `stdio.py:53`, `http_transport.py:166`, `protocol.py:196` |
| `metal-trace: reply to <id> failed: <ExceptionName>` | The worker could not write a reply | `worker.py:74` |
| `metal-trace: client closed the connection` | HTTP: the client left during the write | `http_transport.py:106` |

No line holds an argument, label, path, token or result: only a tool name, status, duration, an exception type (never its text) and, once, a client-chosen request id. **Confirmed** for the seven sites; nothing enforces it, so a new `logs.log(f"... {value}")` would break it silently ([Touching it](./touching.md)). Where stderr ends up depends on the launching client: **not verified**.
