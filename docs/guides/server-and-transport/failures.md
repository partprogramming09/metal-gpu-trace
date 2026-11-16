# When it fails

**Reader:** people who need to know why a client got a given error, status or silence. Reviewed 2026-11-16.

Español: [Cuando falla](../../es/guides/servidor-y-transporte/fallos.md) · [Index](./index.md)

**In short:** a bad request does not stop the server. Each kind of failure has a fixed answer: a protocol error for a
malformed request, an "error result" for a tool that failed, and sometimes silence when the client has already left or
cancelled. The table gives, per failure, what the client sees and what the server does.

The first column is what goes wrong; the second is what the client sees.

| What goes wrong | What the client gets | What the server does | Line |
|---|---|---|---|
| A line that is not JSON (stdio) | `-32700 parse error`, `id: null` | Goes on to the next line | `stdio.py:46-47` |
| JSON that is not an object (`[1]`) | `-32600 Invalid Request` | | `protocol.py:88-89` |
| A request without `jsonrpc: "2.0"` or a text `method` | `-32600 Invalid Request` | | `:94-95` |
| An unknown method | `-32601 unknown method <m>` | | `:173` |
| An unknown tool | `-32602 unknown tool <name>`: a JSON-RPC error, not an `isError` result | | `:167-169` |
| Wrong arguments to a known tool | An `isError` result `bad arguments: ...` | | `worker.py:156-157` |
| A tool raises something expected | An `isError` result with its text | One log line, `error` | `:165-166`, `:171` |
| A tool raises something else | An `isError` result `internal error: <ExceptionName>` | One log line, `error` | `:167-168` |
| 64 calls are waiting | An `isError` result at once | Nothing queued | `:53-57` |
| The call is cancelled while queued | stdio: nothing. HTTP: an `isError` result `the call was cancelled before it started` | The call leaves the queue | `:101-111` |
| The call is cancelled while running | stdio: nothing. HTTP, old era: an `isError` result. HTTP, modern: nothing, the connection is closed | The tool stops at its next look; a recording cleans up | `:112-115`; `http_transport.py:155-161` |
| The `metal-gpu-trace.json` is wrong | Every tool, and every `metal-trace://runs/...` read, answers with its message | The server keeps running; resources answer `-32603` | `worker.py:155`, `protocol.py:131-133` |
| An exception inside `protocol.handle` | `-32603 internal error` | One log line; stdio and HTTP go on | `stdio.py:48-50`, `http_transport.py:163-168`, `protocol.py:191-198` |
| The client left while the worker wrote (stdio) | Nobody to tell | One log line `reply to <id> failed`; the thread lives | `worker.py:73-74` |
| The client left while HTTP wrote | Nobody to tell | One log line `client closed the connection` | `http_transport.py:104-106` |
| A client stalls in the middle of an HTTP request | The connection is closed after 15 s | The thread ends | `:93` |
| `--http` without a token, or with one under 16 characters | A message on stderr and exit status 2 | The server does not start | `:186-189` |
| `--http --port` with no number, or text | `usage: metal-gpu-trace --http [--port N]` and exit status 2 | | `metal_trace_mcp.py:91-93` |
| stdin closes with calls waiting (stdio) | | They are all finished first, then the process ends | `stdio.py:53`, `worker.py:83-90` |

Everything in this table is **confirmed** from the lines named and **not reproduced** live: no request was sent. The tests
that pin each row are named in [Startup](./startup.md), [Worker](./worker.md) and [HTTP](./http.md) (`tests/test_server.py`
unless said otherwise), and they were not run for this guide. HTTP statuses (404, 403, 401, 413, 400) are in [HTTP](./http.md).
