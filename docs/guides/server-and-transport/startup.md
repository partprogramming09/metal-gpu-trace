# How the server starts

**Reader:** people who change the command line, the transports' start-up or what gets configured on import. Reviewed 2026-11-23.

[Index](./index.md)

**In short:** one command starts the server. With no extra word it listens on stdin/stdout (how an agent usually launches it); with `--http` it listens on a local web address and refuses to start without a secret token. Before serving, two internal pieces are wired together once, on import.

## The command line

`main()` (`metal_trace_mcp.py::main`) hands the arguments to `cli.main` (`cli.py::main`), which reads them in this order and stops at the first match:

| Command line | What happens | Line |
|---|---|---|
| `--version` | Prints `metal-gpu-trace <version>`; the project file is not read | `cli.py::main` |
| `--help`, `-h` | Prints the commands and exits 0; no server | `cli.py::main` |
| `init` | Adds the server to the AI apps installed here; the project file is not read | `cli.py::main` |
| no command | Applies the project file once ([How it works](../how-it-works.md#where-recordings-live-and-what-reads-them)), then serves stdio until stdin closes | `cli.py::main` |
| `check RUN BASELINE [--margin-pct N]` | Judges a run for CI, exits 0, 1 or 2; no server | `cli.py::check_cli` |
| `--http [--port N]` | Serves HTTP; port 8765 without `--port`; usage line and exit 2 when the number is missing or not an integer | `cli.py::_http` |
| `doctor` | Prints what a recording needs here, one line per check with the exact fix; exits 0 when a recording could start, else 2 | `cli.py::doctor` |
| `runs [--limit N]` | Lists the recordings newest first, as `perf_runs` does | `cli.py::runs` |
| `compare A B [--markdown]` | Compares two recordings as `perf_compare` does, as a table or its Markdown report | `cli.py::compare` |
| anything else | Prints the usage on stderr and exits 2 instead of waiting for a client | `cli.py::main` |

`doctor`, `runs` and `compare` only read: they reuse the functions the MCP tools call, so a shell answer and an MCP answer carry the same numbers.

There is no `--stdio` flag: stdio is what is left when no command is given (see [limit 4](./limits.md)).

## stdio

`serve_stdio` (`stdio.py::serve_stdio`) is the whole transport:

- Switches stdout to UTF-8 (`stdio.py::serve_stdio`) and reads stdin as bytes, decoding each line as UTF-8 (`stdio.py::serve_stdio`), so encoding does not depend on the launcher's language settings. A line that is not UTF-8 gets `-32700` and the server keeps going.
- Reads stdin line by line until the client closes it (`stdio.py::serve_stdio`); empty lines are skipped (`stdio.py::serve_stdio`).
- Each line is JSON, sorted into three kinds: `notifications/cancelled` goes to `worker.cancel_call` with the request id (`stdio.py::serve_stdio`); a `tools/call` with a text or number id is registered (`worker.CALLS[id] = Event()`) and queued (`stdio.py::serve_stdio`); everything else is answered at once by `protocol.handle` (`stdio.py::serve_stdio`), in the reading thread.
- A line that is not JSON gets `-32700 parse error`, `id: null` (`stdio.py::serve_stdio`). Any other exception from `protocol.handle` is logged as `internal error <ExceptionName>` and answered `-32603 internal error` (`stdio.py::serve_stdio`): one bad message cannot stop the server.
- When stdin closes, `worker.stop_worker()` runs (`stdio.py::serve_stdio`): queued calls finish, then the thread ends ([limit 3](./limits.md)).
- `send` writes one JSON line under a lock, so the reader answering a `ping` and the worker sending progress never interleave bytes (`stdio.py::OUT_LOCK`, `stdio.py::send`).

## HTTP

`serve_http(port)` (`http_transport.py::serve_http`), in this order:

| # | Step | Line |
|---|---|---|
| 1 | Reads `METAL_TRACE_TOKEN`. Missing or shorter than `config.MIN_TOKEN` (16): prints `metal-gpu-trace: set METAL_TRACE_TOKEN to a secret of at least 16 characters` on stderr and returns 2 (exit status 2). Never starts without a token | `http_transport.py::serve_http` |
| 2 | Builds a `ThreadingHTTPServer` on `("127.0.0.1", port)`: one thread per connection, loopback and IPv4 only. Port 0 lets the system choose | `http_transport.py::serve_http` |
| 3 | Logs `metal-trace: serving http://127.0.0.1:<port>/mcp` with the real port | `http_transport.py::serve_http` |
| 4 | Serves until `KeyboardInterrupt`, returns 0 | `http_transport.py::serve_http` |

Each connection is handled by the `Handler` class that `http_handler(token)` builds (`:85-179`). Two standard-library facts: `ThreadingHTTPServer` starts daemon threads (`daemon_threads = True`, [E7](./evidence.md#e7-what-the-standard-library-does-under-threadinghttpserver)) and the base handler speaks HTTP/1.0 (`protocol_version = "HTTP/1.0"`, E7), unchanged here. So each request is its own connection, closed after the reply, and a handler thread never outlives its request. Both facts are from the Python 3.9 standard library read for this guide; for other versions they are **probable**. What a request goes through is in [HTTP](./http.md).

## What is configured, and when

Importing `metal_trace_mcp` has two side effects every transport and test relies on: `protocol.configure(instructions, version)` and `worker.configure(send=stdio.send, answer=protocol.answer, finish=protocol.finish)` (`:49-50`). That is why tests that build a handler or call `protocol.handle` first `import metal_trace_mcp  # noqa: F401  (configures protocol and worker)` (for example `tests/test_server.py::test_golden_protocol`). The architecture tests check that using `worker` or `protocol` before that fails with a message naming the fix (`tests/test_architecture.py::test_worker_needs_configure`, `tests/test_architecture.py::test_protocol_needs_configure`).

`INSTRUCTIONS` (`metal_trace_mcp.py::INSTRUCTIONS`) is the text a client reads on connecting, sent in the reply to `initialize` (`protocol.py::handle`) and `server/discover` (`protocol.py::handle`). The usage rules (one recording at a time, 30 s or more under Wine, compare recordings of 100 frames or more) travel with the server, not a README; a test checks each full stop is followed by a space (`tests/test_server.py::test_instructions_spacing`).
