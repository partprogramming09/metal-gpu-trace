# Logs

**Reader:** people who add or read the server's log lines. Reviewed 2026-11-16.

Español: [Logs](../../es/guides/servidor-y-transporte/logs.md) · [Index](./index.md)

**In short:** the server writes a short line to the error channel (stderr) when a tool finishes or something breaks. It
never writes what you asked for, a file path or the secret token: only names, results and durations. The normal channel
(stdout) is reserved for the conversation with the client.

`logs.py` is one function (`:6-9`): it prints `metal-trace: <message>` to stderr and flushes, unless `METAL_TRACE_LOG` is
exactly `off`. Nothing else in the package writes to stderr or stdout on its own: `send` (`stdio.py:12`) is the only
writer of stdout, and `serve_http` prints one more line directly (`http_transport.py:188`, the token message, which
`METAL_TRACE_LOG=off` does **not** silence).

The module's own docstring says "the one stderr line per tool call", and the README too. In the code there are seven
callers ([E6](./evidence.md#e6-every-place-that-writes-a-log-line)), which are the whole log:

| Message | When | Line |
|---|---|---|
| `metal-trace: <tool> ok in <s> s` or `... error in <s> s` | A tool call ended (`error` means an `isError` result) | `worker.py:171` |
| `metal-trace: serving http://127.0.0.1:<port>/mcp` | HTTP started | `http_transport.py:191` |
| `metal-trace: internal error <ExceptionName>` | An exception in `protocol.handle`, in stdio (the reader), in HTTP (the handler) or in `protocol.answer` (the worker) | `stdio.py:49`, `http_transport.py:166`, `protocol.py:196` |
| `metal-trace: reply to <id> failed: <ExceptionName>` | The worker could not write a reply | `worker.py:74` |
| `metal-trace: client closed the connection` | HTTP: the client left during the write | `http_transport.py:106` |

No line holds an argument, a label, a path, a token or a result: only the tool's name, its status, a duration, the type of
an exception (never its text) and, in one line, a request id the client chose. This is **confirmed** for today's seven
sites; nothing enforces it, so a new `logs.log(f"... {value}")` would break it silently ([Touching it](./touching.md)).
Where stderr ends up (a file, a pane, nowhere) depends on the client that launched the server: **not verified** here.
