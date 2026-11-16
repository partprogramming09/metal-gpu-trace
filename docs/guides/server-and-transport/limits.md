# Known limits

**Reader:** people who plan fixes or need to know what the server does not guard against. Reviewed 2026-11-16.

Español: [Límites conocidos](../../es/guides/servidor-y-transporte/limites.md) · [Index](./index.md)

**In short:** twelve places where today's behaviour is surprising or fragile: a docs page that orders two steps the
other way round, a few edge cases of the command line and of HTTP, and some couplings. None was fixed here; each is
written down with where it lives and how sure we are.

Each item is a limit of today's behaviour, written down, not fixed here.

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | [How it works](../how-it-works.md#one-request-end-to-end) lists "`protocol.handle` checks the era, the `_meta` and that the tool exists" (step 2) **before** "the call waits in the worker queue" (step 3). In the code, for a `tools/call` the transport queues the raw message first and `protocol.handle` runs on the worker thread (an exception: HTTP's `check_headers` runs before the queue). A request that fails the tool-name check therefore waits its turn in the queue before it is refused | `stdio.py:38-44`, `worker.py:72`, `protocol.py:167-169`, `http_transport.py:134-154` | Confirmed; which order the page should say is a decision for the owner |
| 2 | Invalid UTF-8 on stdin is not caught: the decode error is raised by the `for line in sys.stdin` iterator, which is outside the `try` that answers `-32700`. The HTTP transport has a test for the same input (`test_http_unreadable_body_is_a_parse_error`, `:1031`); no test was found for stdio | `stdio.py:30-34`, `:46-50` | Probable: read from the code; not run |
| 3 | Closing stdin does not cancel anything: `stop_worker` queues a stop sign **after** the calls already waiting and waits for the thread, so a running recording, and each queued one, finish before the server ends. By then nobody reads the replies (they fail and are logged). The script's own watcher stops the program if the server process dies ([Recording](../recording/failures.md#what-happens-if-instruments-dies-part-way)), but a server that stays alive with a closed stdin keeps recording | `stdio.py:53`, `worker.py:83-90` | Confirmed by the code; the effect on a real client is probable |
| 4 | An unknown first argument starts stdio silently, and after `--http` only `--port N` is read: `--http 9000` serves on 8765. A port the system refuses (out of range, in use) is not caught and ends in a Python traceback | `metal_trace_mcp.py:88-95`, `http_transport.py:190` | Confirmed for the arguments; the traceback is probable (not run) |
| 5 | The `Bearer ` prefix is optional and case-sensitive: a header that is just the token passes, and `bearer <token>` does not | `http_transport.py:115` | Confirmed by the code; not run. Whether other clients send the scheme in lower case: not verified |
| 6 | `local_host` takes what precedes the first `:`, so `localhost:1@evil.example` counts as local. A browser does not send user information in `Host` or `Origin`, so no way to use it from a web page is known; the tests cover the dotted-suffix trick only | `http_transport.py:17-20`, `tests/test_server.py:317-319` | Confirmed by reading the function; the browser claim is **not verified** |
| 7 | GET and DELETE answer 405 before the Host, Origin and token checks, so an unauthenticated client can tell the port is a server of this kind | `http_transport.py:170-174` | Confirmed (harmless, since it answers nothing else) |
| 8 | Only `Content-Length` is read: `Transfer-Encoding: chunked` is read as an empty body and answered 400 `-32700` | `http_transport.py:125-133` | Probable: not run |
| 9 | A call from an old-era HTTP client waits with no timeout of its own: the length of the call is the tool's. Only a recording has a deadline (15 s per recorded second plus 180, [Recording](../recording/index.md)); the other tools are short | `http_transport.py:160-161` | Probable |
| 10 | Three spellings of the same name: the startup refusal prints `metal-gpu-trace:` (`:188`, outside `logs` and not silenced by `METAL_TRACE_LOG=off`), the log lines print `metal-trace:` and the server's own name in `serverInfo` is `metal-trace`. `logs.py`'s docstring and the README say one line per call; the code writes seven kinds of line | `http_transport.py:188`, `logs.py:1`, `:9`, `protocol.py:78` | Confirmed (cosmetic) |
| 11 | `worker._send` is `stdio.send` also when the server runs as `--http` (`metal_trace_mcp.py:50`). Progress is safe only because the HTTP handler removes `progressToken` first; if that removal went away, progress would be written to the process's stdout, where no client reads it | `metal_trace_mcp.py:50`, `http_transport.py:145-151`, `worker.py:149-151` | Confirmed (a coupling, not a bug today) |
| 12 | `worker.call` turns `FileNotFoundError`, `ValueError` and `RuntimeError` into the client's text with `str(error)`. The "no path in an error" rule (README) is kept by each tool using `ToolError` with its own wording, not by the worker; a raw `FileNotFoundError` from a new tool would show its path | `worker.py:165-166` | Probable: read from the code; no tool was found to do it today |
