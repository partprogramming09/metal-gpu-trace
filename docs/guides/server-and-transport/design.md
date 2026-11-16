# Design: why the server has this shape

**Reader:** people who change the structure of the server or wonder why a choice was made. Reviewed 2026-11-16.

Español: [Diseño](../../es/guides/servidor-y-transporte/diseno.md) · [Index](./index.md)

**In short:** the server does one job at a time on purpose: two recordings at once would spoil both measurements. The
"doors" (stdio and HTTP) only receive and queue requests; one worker does the work. That keeps the doors simple and the
rules in one place. Labels (confirmed, probable, speculation) are explained in the [index](./index.md#how-to-read-the-labels).

## The choices

| Choice | Why | Alternatives that were left out |
|---|---|---|
| One worker thread, one call at a time | Only one recording may run at once, because two programs sharing the GPU spoil both measurements (`stdio.py:40-41`, the comment at the place that submits). A queue of 64 served by one thread replaced one thread per call in an earlier version (`CHANGELOG.md`, the entry that says "one queue of 64") | A thread per call: it lets several recordings start and then refuse all but one; the queue refuses at once instead |
| The transport keeps reading while a call runs | A recording takes 30 s or more. The same loop must answer `ping` and `tools/list` and hear `notifications/cancelled` meanwhile (`stdio.py:40-44`) | Running the tool in the reading loop: a cancel could never be heard until the call ended |
| Transports never run tools; they queue them | One place (the worker) holds the cancel flags, the queue and the one-at-a-time rule, so stdio and HTTP cannot drift apart ([How it works](../how-it-works.md#two-rules-that-keep-it-testable), "the worker is the only place tool calls run") | Each transport running its own calls |
| `protocol` and `worker` get what they need through `configure()` | `protocol` needs the entry point's text and version, and `worker` needs the transport's `send` and the protocol's `answer`; both sit below what they need, so `metal_trace_mcp.py` passes them in (`metal_trace_mcp.py:49-50`). Both raise a clear error if used before that (`worker.py:11-12`, `protocol.py:35-37`). See [How it works](../how-it-works.md#two-rules-that-keep-it-testable) | Importing upward: the architecture test forbids it |
| The tool list is one dictionary, `registry.TOOLS` | The list the client sees (`tools/list`), the check of the arguments and the function that runs all read the same row, so they cannot disagree (`protocol.py:146-150`, `worker.py:156-158`) | A decorator on each function: **speculation** that a plain table was left because the schemas are long and the table is easy to test as a whole; no ADR records the choice |
| HTTP on 127.0.0.1 only, with a token, a local Host and no foreign Origin | A web page open in a browser on the same Mac can send requests to `127.0.0.1`, and a hostile name can be made to point there (DNS rebinding); the docstring says the Host and Origin checks stop that (`http_transport.py:86-88`) | Listening on other addresses or with TLS: not offered; the README says to reach another Mac through an SSH tunnel (`README.md`, section "HTTP") |
| One POST, one JSON reply, no event stream | Progress goes out as notifications, "which this endpoint does not stream" (`http_transport.py:145-146`); the README says there is no progress stream over HTTP | Server-sent events: not implemented |
| The token comes from an environment variable | `serve_http` reads `METAL_TRACE_TOKEN` (`http_transport.py:186`). **Speculation:** a command-line argument would show in the process list; no ADR records the choice | A flag such as `--token`: not offered |
| Logs go to stderr, one short line | Over stdio, stdout is the protocol: anything else printed there breaks the client (`logs.py:7`, "the only log channel a stdio server may use") | A log file: nothing in the code writes one |

## The pieces and where they live

| Piece | File | What it does |
|---|---|---|
| Entry point | `metal_trace_mcp.py` (`INSTRUCTIONS` `:23-47`, `main` `:79-95`, `check_cli` `:53-76`) | Holds the text clients read, configures `protocol` and `worker`, applies the project file, and picks the transport from the command line |
| `python -m` | `__main__.py` (4 lines) | Calls `main()` so `python -m metal_gpu_trace` and the `metal-gpu-trace` command (`pyproject.toml:30-31`) start the same server |
| stdio transport | `stdio.py` (`serve_stdio` `:25`, `send` `:12`) | Reads one JSON message per line on stdin, writes one per line on stdout |
| HTTP transport | `http_transport.py` (`http_handler` `:85`, `check_headers` `:46`, `serve_http` `:182`) | `POST /mcp` on 127.0.0.1 with a token |
| The protocol | `protocol.py` (`handle` `:86`, `answer` `:191`, `era` `:40`) | One JSON-RPC request in, one reply out; see [Eras](./eras.md) |
| The worker | `worker.py` (`submit` `:41`, `work` `:60`, `call` `:143`, `cancel_call` `:93`, `cancel_item` `:118`) | The queue, the thread, the cancel flags, the checks before a tool runs |
| The registry | `registry.py` (`TOOLS` `:69`, `RESOURCES` `:12`, `PROMPTS` `:193`) | What clients can ask for: tools with their schemas, resources, prompts |
| Logs | `logs.py` (9 lines) | The one function that writes to stderr |
| Settings | `config.py` (`MAX_QUEUE` `:52`, `MIN_TOKEN` `:55`, `MAX_BODY` `:56`, `HTTP_TIMEOUT` `:57`, `MAX_TEXT` `:45`) | The limits used across the pages; the numbers are in [E3](./evidence.md#e3-the-limits-the-server-applies) |

The layer of each module (7 for the entry point, 6 for the transports, 5 protocol, 4 worker, 3 registry, 0 logs) is in
[How it works](../how-it-works.md#layers) and in `LAYERS` in `tests/test_architecture.py:15-23`.
