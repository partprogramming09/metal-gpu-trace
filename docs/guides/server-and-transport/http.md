# HTTP in detail

**Reader:** people who change what the HTTP endpoint accepts, refuses or answers. Reviewed 2026-11-16.

Español: [HTTP](../../es/guides/servidor-y-transporte/http.md) · [Index](./index.md)

**In short:** over HTTP the server works like a building with a doorman. It checks, in a fixed order, that you came to the right door, from the right street, with the right key and a sensible package, and only then reads what you brought. Refusals say as little as possible. Start-up is in [Startup](./startup.md).

A client that cannot start a stdio server sends `POST http://127.0.0.1:8765/mcp` with `Authorization: Bearer <token>` and one JSON message as the body. The token is the one in `METAL_TRACE_TOKEN`; the examples write `<token>`, never a real one.

## The checks, in order

![Seven boxes in a row, left to right: path, host and origin, token, size, JSON, headers and run. Under each of the first six, the status it answers with: 404, 403, 401, 413, 400 with a parse error, and 400 or 404 with a JSON-RPC error. If all pass, the request runs.](./img/server-http-checks.png)
*Figure 2. What `do_POST` checks before anything runs. Source: `img/server-http-checks.html`.*

The order matters: a client with no token never gets its body read. Statuses 404, 403, 401 and 413 have an **empty** body on purpose (`reply(code)` with no body, `http_transport.py:99-101`, lines `:119-129`): a refusal tells the client nothing it did not know. [E1](./evidence.md#e1-every-status-the-http-handler-answers-with-its-line) lists every `self.reply` with its line.

| # | Check | Status | The reply | Pinned by |
|---|---|---|---|---|
| 0 | The method is POST (`do_GET`, `do_DELETE`) | 405 | Empty; before any other check. `PUT`, `HEAD` and the rest are answered by the standard library (**probable**: 501; not run) | `tests/test_server.py:321`, `:893` |
| 1 | `self.path == "/mcp"` | 404 | Empty | `:322` |
| 2 | Host is `localhost` or `127.0.0.1`, and an Origin, when sent, is too | 403 | Empty | `:317-320` |
| 3 | `Authorization` carries the token | 401 | Empty | `:315-316` |
| 4 | `Content-Length` is digits, at most 12, between 0 and `MAX_BODY` (1 000 000) | 413 | Empty | `tests/test_adversarial.py:225` |
| 5 | The body is UTF-8 JSON not nested beyond what the parser accepts | 400 | `-32700 parse error`, `id: null` | `:1031` |
| 6 | `check_headers` | 400 or 404 | A JSON-RPC error (codes below) | `:838`, `:847` |

| Check | Detail |
|---|---|
| **Host and Origin** (`foreign`, `:108-111`; `local_host`, `:17-20`) | Removes a leading `scheme://` and anything after `/`, takes what precedes the first `:`, accepts only `localhost` or `127.0.0.1`; the port does not matter. An `Origin` is checked only when sent; a missing `Host` is not local. Tests: `http://evil.example`, `http://localhost.evil.example` and `Host: evil.example` give 403, `http://localhost:<port>` gives 200 (`tests/test_server.py:317-320`). Why both: a page on `evil.example` whose name resolves to `127.0.0.1` sends `Host: evil.example` (Host check stops it); a browser sends an `Origin` on a cross-site POST, which stops a page that needs no rebinding |
| **The token** (`unauthorized`, `:113-116`) | `Bearer ` is removed if present and the rest compared with `hmac.compare_digest` (same time whatever the first wrong byte). Read once at start (`:186`), never logged, printed or replied; the only message is the refusal to start ([E5](./evidence.md#e5-how-the-command-line-is-read), `:188`). Missing, empty and wrong are all 401 (`tests/test_server.py:315-316`) |
| **Size** (`:125-129`) | A `Content-Length` that is not ASCII digits (`²` passes `str.isdigit()` and fails `int()`), has more than 12 characters or exceeds 1 000 000 is 413 without reading the body; a test uses `0xB2` and 5 000 nines (`tests/test_adversarial.py:225-232`). No `Content-Length` counts as 0: a body without it, or with `Transfer-Encoding: chunked`, is read as empty and answered 400 `-32700` ([limit 8](./limits.md)) |

## `check_headers`: when the headers do not match the body

`check_headers(headers, message, era)` (`:46-82`) returns `(status, body)` for a POST the spec rejects, or `None`. The era comes from `protocol.era(message)` (`:134`).

| Era | Condition | Status and code | Line |
|---|---|---|---|
| Old | A notification and the version header is the modern one | Let through | `:60-61` |
| Old | `MCP-Protocol-Version` sent and not an old version | 400, `-32600` `unsupported MCP-Protocol-Version <v>` | `:62-63` |
| Modern | A notification | Let through, with or without `_meta` (the spec defines no header rules for it) | `:65-66` |
| Modern | `MCP-Protocol-Version` or `Mcp-Method` missing | 400, `-32020` `Header mismatch: ... are required` | `:70-71` |
| Modern | `Mcp-Method` is not the body's `method` | 400, `-32020` | `:72-73` |
| Modern | The version header is not the `_meta` version | 400, `-32020` | `:74-75` |
| Modern | The version is not `2026-07-28` | 400, `-32022 Unsupported protocol version`, `data` lists supported and requested | `:76-77`, `protocol.py:52-55` |
| Modern | The method is not a modern one (`ping` is not) | 404, `-32601 unknown method` | `:78-79`, `protocol.py:28-29` |
| Modern | `tools/call`, `prompts/get` or `resources/read` and `Mcp-Name` is not `params.name` (or `params.uri`) | 400, `-32020` | `:80-81` |

The reply's `id` is the request's when text or number, else `null` (`:56`). `Mcp-Name` may be `=?base64?<utf-8 in base64>?=` for non-ASCII names (`header_text`, `:31-43`); bad Base64, extra padding and non-UTF-8 give "no value", a mismatch. Pinned by `test_http_modern_headers` (`tests/test_server.py:847`) and `test_http_legacy_headers` (`:838`).

A request that passes `check_headers` can still fail, but not as an HTTP error: a JSON-RPC error such as `unknown tool x` or an `isError` result is a `200` with the error in the body (`:162`, `:168`). Only the checks above are 4xx.

## After the checks

1. **`notifications/cancelled`** (`:137-142`): `202`, empty body. Old era: cancels the call by id (`worker.cancel_call`). Modern era: accepted and **ignored**, because a modern client cancels by closing the connection and an id may be shared by another client (`tests/test_server.py:1165`).
2. **`tools/call` with an id** (`:143-162`):
   - Strips what the endpoint cannot stream: modern era removes `progressToken` from `_meta` and keeps the version; old era removes `_meta` (`:147-151`).
   - Makes its own cancel flag, registers it under the id and queues the message with a callback that stores the reply and wakes the handler thread (`:152-154`).
   - Waits. **Modern:** every `POLL_S` (0.5 s) `client_gone` peeks at the socket for an end-of-file (`:23-28`); if closed, it calls `cancel_item` and writes nothing (`:155-159`; `test_http_close_cancels`, `tests/test_server.py:817`: "within a second or two, and nothing back"). **Old:** waits for the result, even a cancelled one, as that era has no such signal (`:160-161`; `test_http_legacy_cancel_keeps_reply`, `:799`).
   - Writes `200` with the stored reply (`:162`).
3. **Everything else** (`:163-168`): `protocol.handle` runs in the handler thread, not the worker's. An exception is logged as `internal error <ExceptionName>` and answered `200` with `-32603 internal error`. A `None` reply (a notification) is `202`, otherwise `200`.

## The reply helper and a client that left

`reply` (`:95-106`) writes the status, a `Content-Type` only with a body, a `Content-Length` always, and the body. A `ConnectionError` while writing sets `close_connection` and logs `client closed the connection` instead of raising (`:104-106`; `test_http_reply_broken_pipe`, `tests/test_server.py:1067`). `timeout = config.HTTP_TIMEOUT` (15 s, `:93`) drops a client that stalls before finishing its request, so it cannot hold a thread for ever (`test_http_timeout`, `:473`). `log_message` is empty (`:176-177`): the standard library's per-request access log is off.
