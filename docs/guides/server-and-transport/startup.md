# How the server starts

**Reader:** people who change the command line, the transports' start-up or what gets configured on import. Reviewed 2026-11-16.

Español: [Arranque](../../es/guides/servidor-y-transporte/arranque.md) · [Index](./index.md)

**In short:** you start the server with one command. With no extra word it listens on stdin/stdout (the way an agent
usually launches it); with `--http` it listens on a local web address and refuses to start without a secret token. Before
anything is served, two internal pieces are wired together once, on import.

## The command line

`main()` (`metal_trace_mcp.py:79-95`) reads the command line in this order and stops at the first that matches:

| Command line | What happens | Line |
|---|---|---|
| `--version` | Prints `metal-gpu-trace <version>` and returns; the project file is not read | `:82-84` |
| anything else | Applies the project file once ([How it works](../how-it-works.md#where-recordings-live-and-what-reads-them): which folder holds the recordings) | `:85` |
| `check RUN BASELINE [--margin-pct N]` | Judges a run for CI and exits 0, 1 or 2; no server | `:86-87`, `:53-76` |
| `--http [--port N]` | Serves HTTP; port 8765 when `--port` does not follow, a usage line and exit 2 when the number is missing or not an integer | `:88-94` |
| nothing else matches | Serves stdio until stdin closes | `:95` |

There is no `--stdio` flag: stdio is what is left when nothing else matched (see [limit 4](./limits.md)).

## stdio

`serve_stdio` (`stdio.py:25-53`) is the whole transport:

- Switches stdin and stdout to UTF-8 (`:27-29`), so the encoding does not depend on the language settings of whoever launched it.
- Reads `sys.stdin` line by line until the client closes it (`:30`). Empty lines are skipped (`:31-32`).
- Each line is JSON. Three kinds of message are told apart before anything else:
  - `notifications/cancelled` goes to `worker.cancel_call` with the request id it names (`:35-37`);
  - a `tools/call` with a text or number id is registered (`worker.CALLS[id] = Event()`) and queued (`:38-44`);
  - everything else is answered on the spot by `protocol.handle` (`:45`), in the reading thread.
- A line that is not JSON gets `-32700 parse error` and `id: null` (`:46-47`). Any other exception from `protocol.handle`
  is logged as `internal error <ExceptionName>` and answered `-32603 internal error` (`:48-50`): one bad message cannot stop the server.
- When stdin closes, `worker.stop_worker()` runs (`:53`): the calls already queued are finished, then the thread ends ([limit 3](./limits.md)).
- `send` writes a message as one line of JSON under a lock, so two threads (the reader answering a `ping` and the worker
  sending a progress notification) never interleave their bytes (`:9`, `:12-16`).

## HTTP

`serve_http(port)` (`http_transport.py:182-196`) does four things, in this order:

| # | Step | Line |
|---|---|---|
| 1 | Reads `METAL_TRACE_TOKEN`. Shorter than `config.MIN_TOKEN` (16 characters) or missing: prints `metal-gpu-trace: set METAL_TRACE_TOKEN to a secret of at least 16 characters` on stderr and returns 2, so the process exits with status 2. The server never starts without a token | `:186-189` |
| 2 | Builds a `ThreadingHTTPServer` bound to `("127.0.0.1", port)`: one thread per connection, loopback only, IPv4 only. Port 0 lets the system choose | `:190` |
| 3 | Logs `metal-trace: serving http://127.0.0.1:<port>/mcp` with the port it really got | `:191` |
| 4 | Serves until `KeyboardInterrupt` and returns 0 | `:192-195` |

Every connection is handled by the `Handler` class that `http_handler(token)` builds (`:85-179`). Two facts from the
standard library matter: `ThreadingHTTPServer` starts daemon threads (`daemon_threads = True`, [E7](./evidence.md#e7-what-the-standard-library-does-under-threadinghttpserver)) and the base handler
speaks HTTP/1.0 by default (`protocol_version = "HTTP/1.0"`, E7), which this handler does not change. So each request is
its own connection, closed after the reply, and a handler thread never outlives its request. Both facts are from the
Python 3.9 standard library read for this guide; for another Python version they are **probable**. What each request
goes through is in [HTTP](./http.md).

## What is configured, and when

Importing `metal_trace_mcp` has two side effects that every transport and every test relies on: it calls
`protocol.configure(instructions, version)` and `worker.configure(send=stdio.send, answer=protocol.answer,
finish=protocol.finish)` (`:49-50`). That is why the tests that build a handler or call `protocol.handle` directly first
`import metal_trace_mcp  # noqa: F401  (configures protocol and worker)` (for example `tests/test_server.py:525-529`). The
architecture tests check that using `worker` or `protocol` before that fails with a message that names the fix
(`tests/test_architecture.py:147`, `:201`).

`INSTRUCTIONS` (`:23-47`) is the text a client reads when it connects. It is sent in the reply to `initialize`
(`protocol.py:112`) and to `server/discover` (`:115`). The project's usage rules live there (one recording at a time, 30 s
or more under Wine, compare recordings of 100 frames or more) so they travel with the server and not with a README; a
test checks that each full stop is followed by a space (`tests/test_server.py:1090`).
