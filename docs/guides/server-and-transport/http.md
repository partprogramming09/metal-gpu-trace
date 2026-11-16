# HTTP in detail

**Reader:** people who change what the HTTP endpoint accepts, refuses or answers. Reviewed 2026-11-16.

Español: [HTTP](../../es/guides/servidor-y-transporte/http.md) · [Index](./index.md)

**In short:** over HTTP the server works like a building with a doorman. It checks, in a fixed order, that you came to
the right door, from the right street, with the right key and a sensible package, and only then reads what you brought.
Refusals say as little as possible. Start-up of this transport is in [Startup](./startup.md).

A client that cannot start a stdio server sends `POST http://127.0.0.1:8765/mcp` with an `Authorization: Bearer <token>`
header and one JSON message as the body. The token is the one in `METAL_TRACE_TOKEN`; the examples write `<token>` and
never a real one.

## The checks, in order

![Seven boxes in a row, left to right: path, host and origin, token, size, JSON, headers and run. Under each of the first six, the status it answers with: 404, 403, 401, 413, 400 with a parse error, and 400 or 404 with a JSON-RPC error. If all pass, the request runs.](./img/server-http-checks.png)
*Figure 2. What `do_POST` checks before anything runs. Source: `img/server-http-checks.html`.*

The first question is whether you came to the right door (the path), the second whether you come from the street outside
or from somewhere pretending to be it (Host and Origin), the third whether you hold the key (the token), and only then
does anyone look at what you carry (the body). The order matters: a client with no token never gets its body read.

| # | Check | Status | The reply | Pinned by |
|---|---|---|---|---|
| 0 | The method is POST (`do_GET`, `do_DELETE`) | 405 | Empty; any GET or DELETE, before any other check. `PUT`, `HEAD` and the rest are not defined here: the standard library answers them (**probable**: 501; not run) | `tests/test_server.py:321`, `:893` |
| 1 | `self.path == "/mcp"` | 404 | Empty body | `:322` |
| 2 | Host is `localhost` or `127.0.0.1`, and an Origin, when sent, is too | 403 | Empty body | `:317-320` |
| 3 | `Authorization` carries the token | 401 | Empty body | `:315-316` |
| 4 | `Content-Length` is digits, at most 12 of them, and between 0 and `MAX_BODY` (1 000 000) | 413 | Empty body | `tests/test_adversarial.py:225` |
| 5 | The body is UTF-8 JSON that is not nested beyond what the parser accepts | 400 | A JSON-RPC error, `-32700 parse error`, `id: null` | `:1031` |
| 6 | `check_headers` | 400 or 404 | A JSON-RPC error with the codes in the table below | `:838`, `:847` |

Statuses 404, 403, 401 and 413 have an **empty** body on purpose (`reply(code)` with no body, `http_transport.py:99-101`):
a refusal tells the client nothing it did not know. The lines are `:119-129`, and [E1](./evidence.md#e1-every-status-the-http-handler-answers-with-its-line) lists every `self.reply` of the file with its line.

| Check | Detail |
|---|---|
| **Host and Origin** (`foreign`, `:108-111`; `local_host`, `:17-20`) | Removes a leading `scheme://` and anything after a `/`, takes what comes before the first `:` and accepts only `localhost` or `127.0.0.1`. The port does not matter. An `Origin` is checked only when sent; a missing `Host` counts as not local. Tests pin `http://evil.example`, `http://localhost.evil.example` and `Host: evil.example` as 403 and `http://localhost:<port>` as 200 (`tests/test_server.py:317-320`). Why both: a page on `evil.example` whose name was made to resolve to `127.0.0.1` sends `Host: evil.example`, so the Host check stops it; a browser also sends an `Origin` on a cross-site POST, so the Origin check stops the page that does not even need rebinding |
| **The token** (`unauthorized`, `:113-116`) | `Bearer ` is removed if the header starts with it, and the rest is compared with `hmac.compare_digest`, which takes the same time whatever the first wrong byte is. The token is read once at start (`:186`), never logged, never printed, never part of a reply; the only message about it is the refusal to start ([E5](./evidence.md#e5-how-the-command-line-is-read), `:188`). A missing, an empty and a wrong header are all 401 (`tests/test_server.py:315-316`) |
| **Size** (`:125-129`) | A `Content-Length` that is not ASCII digits (`²` passes `str.isdigit()` and fails `int()`), has more than 12 characters, or is over 1 000 000 is 413 without reading the body; one test asks with `0xB2` and with 5 000 nines (`tests/test_adversarial.py:225-232`). No `Content-Length` counts as 0, so a body sent without it, or with `Transfer-Encoding: chunked`, is read as empty and answered 400 `-32700` ([limit 8](./limits.md)) |

## `check_headers`: when the headers do not match the body

`check_headers(headers, message, era)` (`:46-82`) returns `(status, body)` for a POST the spec rejects, or `None`. The era
comes from `protocol.era(message)` (`:134`).

| Era | Condition | Status and code | Line |
|---|---|---|---|
| Old | The message is a notification and the version header is the modern one | Let through | `:60-61` |
| Old | `MCP-Protocol-Version` is sent and is not an old version | 400, `-32600` `unsupported MCP-Protocol-Version <v>` | `:62-63` |
| Modern | A notification | Let through, with or without `_meta`: the spec defines no header rules for it | `:65-66` |
| Modern | `MCP-Protocol-Version` or `Mcp-Method` is missing | 400, `-32020` `Header mismatch: ... are required` | `:70-71` |
| Modern | `Mcp-Method` is not the body's `method` | 400, `-32020` | `:72-73` |
| Modern | The version header is not the `_meta` version | 400, `-32020` | `:74-75` |
| Modern | The version is not `2026-07-28` | 400, `-32022 Unsupported protocol version`, with `data` listing the supported and the requested | `:76-77`, `protocol.py:52-55` |
| Modern | The method is not one of the modern ones (`ping` is not) | 404, `-32601 unknown method` | `:78-79`, `protocol.py:28-29` |
| Modern | `tools/call`, `prompts/get` or `resources/read` and `Mcp-Name` is not `params.name` (or `params.uri`) | 400, `-32020` | `:80-81` |

The reply's `id` is the request's when it is a text or a number, else `null` (`:56`). `Mcp-Name` may be sent as
`=?base64?<utf-8 in base64>?=` for names that are not plain ASCII (`header_text`, `:31-43`); bad Base64, extra padding and
non-UTF-8 bytes all give "no value", which is then a mismatch. The statuses for each row are pinned by
`test_http_modern_headers` (`tests/test_server.py:847`) and `test_http_legacy_headers` (`:838`).

A request that passes `check_headers` can still be answered with an error, but then it is **not** an HTTP error: a
JSON-RPC error such as `unknown tool x` or an `isError` result is a `200` with the error in the body (`:162`, `:168`). Only
the header and body checks above are 4xx.

## After the checks

1. **`notifications/cancelled`** (`:137-142`): answered `202` with an empty body. Under the old era it cancels the call
   by id (`worker.cancel_call`); under the modern era it is accepted and **ignored**, because a modern client cancels by
   closing the connection and an id may be shared by another client (`tests/test_server.py:1165`).
2. **`tools/call` with an id** (`:143-162`):
   - Strips what the endpoint cannot stream. Modern era: `progressToken` is removed from `_meta` and the version stays;
     old era: `_meta` is removed (`:147-151`).
   - Makes its own cancel flag, registers it under the id and queues the message with a callback that stores the reply and
     wakes the handler thread (`:152-154`).
   - Waits. **Modern:** every `POLL_S` (0.5 s) it asks `client_gone`, which peeks at the socket for an end-of-file
     (`:23-28`); if the client closed, it calls `cancel_item` and returns without writing anything (`:155-159`;
     `test_http_close_cancels`, `tests/test_server.py:817`, pins "within a second or two, and nothing back"). **Old:** it
     waits for the result, even a cancelled one, because that era has no such signal (`:160-161`;
     `test_http_legacy_cancel_keeps_reply`, `:799`).
   - Writes `200` with the stored reply (`:162`).
3. **Everything else** (`:163-168`): `protocol.handle` runs in the handler thread, not the worker's. An exception is logged
   as `internal error <ExceptionName>` and answered `200` with `-32603 internal error`. A `None` reply (a notification) is
   `202`, otherwise `200`.

## The reply helper and a client that left

`reply` (`:95-106`) writes the status, a `Content-Type` only when there is a body, a `Content-Length` always, and the body.
A `ConnectionError` while writing (the client closed during a long call) sets `close_connection` and logs
`client closed the connection` instead of raising (`:104-106`; `test_http_reply_broken_pipe`, `tests/test_server.py:1067`).
`timeout = config.HTTP_TIMEOUT` (15 s, `:93`) drops a client that opens a connection and stalls before finishing its request
(`test_http_timeout`, `:473`), so it cannot hold a thread for ever. `log_message` is empty (`:176-177`): the standard
library's access log, which would print a line for every request, is off.
