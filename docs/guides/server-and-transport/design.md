# Design: why the server has this shape

**Reader:** people who change the structure of the server or wonder why a choice was made. Reviewed 2026-11-16.

Español: [Diseño](../../es/guides/servidor-y-transporte/diseno.md) · [Index](./index.md)

**In short:** the server does one job at a time on purpose: two recordings at once would spoil both measurements. The
"doors" (stdio and HTTP) only receive and queue requests; one worker does the work, so the rules live in one place.
Labels (confirmed, probable, speculation) are in the [index](./index.md#how-to-read-the-labels).

## The choices

| Choice | Why | Left out |
|---|---|---|
| One worker thread, one call at a time; transports queue, never run tools | Two programs sharing the GPU spoil both measurements (`stdio.py:44-45`). The worker alone holds the cancel flags, the queue and the one-at-a-time rule, so stdio and HTTP cannot drift apart ([How it works](../how-it-works.md#two-rules-that-keep-it-testable)). A queue of 64 and one thread replaced one thread per call (`CHANGELOG.md`, "one queue of 64") | A thread per call (starts several recordings, refuses all but one; the queue refuses at once). Each transport running its own calls |
| The transport keeps reading while a call runs | A recording takes 30 s or more; the same loop must answer `ping` and `tools/list` and hear `notifications/cancelled` (`stdio.py:42-48`) | Running the tool in the reading loop: a cancel could not be heard until the call ended |
| `configure()` hands `protocol` and `worker` what they need | `protocol` needs the entry point's text and version, `worker` the transport's `send` and the protocol's `answer`; both sit below them, so `metal_trace_mcp.py` passes them in (`:49-50`). Both raise a clear error if used before (`worker.py:11-12`, `protocol.py:35-37`) | Importing upward: the architecture test forbids it |
| The tool list is one dictionary, `registry.TOOLS` | `tools/list`, the argument check and the function read the same row, so they cannot disagree (`protocol.py:146-150`, `worker.py:156-158`) | A decorator per function: **speculation** that a plain table is easier to test whole; no ADR records it |
| HTTP on 127.0.0.1 only, token, local Host, no foreign Origin; one POST, one JSON reply, no event stream | A web page on the same Mac can send requests to `127.0.0.1`, and a hostile name can point there (DNS rebinding); the Host and Origin checks stop it (`http_transport.py:86-88`). Progress notifications are not streamed (`:145-146`). `serve_http` reads the token from `METAL_TRACE_TOKEN` (`:186`); **speculation:** a command-line argument would show in the process list; no ADR records it | Other addresses or TLS (the README says to use an SSH tunnel, section "HTTP"); server-sent events; a `--token` flag |
| Logs go to stderr, one short line | Over stdio, stdout is the protocol: anything else printed there breaks the client (`logs.py:7`) | A log file: nothing writes one |

## The pieces and where they live

| Piece | File | What it does |
|---|---|---|
| Entry point | `metal_trace_mcp.py` (`INSTRUCTIONS` `:23-47`, `main` `:79-95`, `check_cli` `:53-76`); `__main__.py` (4 lines) calls `main()` so `python -m metal_gpu_trace` and the `metal-gpu-trace` command (`pyproject.toml:30-31`) start the same server | Holds the text clients read, configures `protocol` and `worker`, applies the project file, picks the transport |
| stdio | `stdio.py` (`serve_stdio` `:25`, `send` `:12`) | One JSON message per line on stdin and stdout |
| HTTP | `http_transport.py` (`http_handler` `:85`, `check_headers` `:46`, `serve_http` `:182`) | `POST /mcp` on 127.0.0.1 with a token |
| Protocol | `protocol.py` (`handle` `:86`, `answer` `:191`, `era` `:40`) | One JSON-RPC request in, one reply out ([Eras](./eras.md)) |
| Worker | `worker.py` (`submit` `:41`, `work` `:60`, `call` `:143`, `cancel_call` `:93`, `cancel_item` `:118`) | Queue, thread, cancel flags, checks before a tool runs |
| Registry | `registry.py` (`TOOLS` `:69`, `RESOURCES` `:12`, `PROMPTS` `:193`) | Tools with schemas, resources, prompts |
| Logs, settings | `logs.py` (9 lines); `config.py` (`MAX_QUEUE` `:52`, `MIN_TOKEN` `:55`, `MAX_BODY` `:56`, `HTTP_TIMEOUT` `:57`, `MAX_TEXT` `:45`) | The one stderr writer; the limits, with numbers in [E3](./evidence.md#e3-the-limits-the-server-applies) |

Layers: 7 entry point, 6 transports, 5 protocol, 4 worker, 3 registry, 0 logs ([How it works](../how-it-works.md#layers); `LAYERS`, `tests/test_architecture.py:15-23`).
