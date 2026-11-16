# Server and transport

**Reader:** people who change how the server starts, listens and answers (`metal_trace_mcp.py`, `stdio.py`, `http_transport.py`, `worker.py`, `registry.py`, `logs.py`), who add or rename a tool, or who need to know why a client got a given error, status or silence. Reviewed 2026-11-16.

Español: [Servidor y transporte](../es/guides/servidor-y-transporte.md)

This page follows one tool call from the moment a client sends it to the moment the reply is written, over stdio and over
HTTP, and says what each piece does and what happens when it fails. It does not repeat [How it works](./how-it-works.md)
(the layer table, the two rules that keep it testable, the path of one request in five lines) or
[ADR-0002](../adr/0002-dual-era-mcp.md) (why the server speaks two eras of MCP); it links to them and goes deeper where
they stop. Reading the recordings is in [Recording](./recording.md) and [Summarizing and analyzing](./summarizing.md): this
page stops where a tool function starts.

How to read the labels: every technical claim is **confirmed** (with `file:line`, checked with `rg` or `sed` on
2026-11-16 against the working tree, which is 0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`), **probable**
(read from the code but not run here) or **speculation** (a guess about why). **Not verified** marks an outside fact
that was not checked against its source. Lines move when the code changes: search the name, not only the number. Every
number comes with the command that produced it, in [Evidence](#evidence-the-commands-and-their-real-output). **Not
reproduced** means the behaviour could not be run for this page: the session that wrote it could run read-only commands
only, so the server was not started, no request was sent and no test was run; the tests that pin each behaviour are named
instead, and they were **not run** for this page.

## One example first

Suppose an agent asks the server, over stdio, to record a program for 30 seconds, and changes its mind half way:

```text
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"perf_record","arguments":{"label":"mygame","program":"/path/to/mygame.exe","wine":"/path/to/wine","seconds":30}}}
```

What happens, in the order it happens:

1. The stdio loop reads the line, sees a `tools/call` with an id and does not run it (`stdio.py:30-44`). It makes a cancel
   flag for id 7 and puts the message in the worker's queue, then goes back to reading the next line at once.
2. The worker thread, started at the first call and kept for the life of the server, takes the message out of the queue
   (`worker.py:60-72`) and asks the protocol to answer it. The protocol checks the tool name exists in the registry
   (`protocol.py:167-169`) and hands the call back to `worker.call` (`:170`).
3. `worker.call` checks the project file, then that the arguments fit the tool's schema, then runs the function the
   registry holds for `perf_record` (`worker.py:155-158`). This is where the 30 seconds go.
4. Meanwhile the agent sends `{"id":8,"method":"ping"}`. The stdio loop is free, and it answers `ping` itself, in the same
   thread that reads, without touching the queue (`stdio.py:45`, `:51-52`).
5. The agent sends `{"method":"notifications/cancelled","params":{"requestId":7}}`. The loop sets the flag of call 7
   (`stdio.py:35-37`, `worker.py:93-115`). The recording looks at that flag every second and kills itself
   ([Recording, the kill sequence](./recording.md#the-kill-sequence)); the function raises `the recording was cancelled;
   nothing was saved`, and the worker turns it into an error result. Because the client cancelled, stdio writes **nothing**
   for id 7 (`stdio.py:19-22`): the spec says a cancelled call gets no reply.
6. If the agent had not cancelled, the function would have returned a dictionary, the worker would have written it as
   JSON text (40 000 characters at most), and the loop would have written it as one line on stdout. Either way the worker
   writes one line on stderr when the call ends: `metal-trace: perf_record error in <seconds> s` or `... ok in <seconds> s`
   (`worker.py:171`).

The same call over HTTP has the same middle (steps 2, 3 and 6) and a different beginning and end: see
[HTTP in detail](#http-in-detail).

## Why the server is shaped this way

| Choice | Why | Alternatives that were left out |
|---|---|---|
| One worker thread, one call at a time | Only one recording may run at once, because two programs sharing the GPU spoil both measurements (`stdio.py:40-41`, the comment at the place that submits). A queue of 64 served by one thread replaced one thread per call in an earlier version (`CHANGELOG.md`, the entry that says "one queue of 64") | A thread per call: it lets several recordings start and then refuse all but one; the queue refuses at once instead |
| The transport keeps reading while a call runs | A recording takes 30 s or more. The same loop must answer `ping` and `tools/list` and hear `notifications/cancelled` meanwhile (`stdio.py:40-44`) | Running the tool in the reading loop: a cancel could never be heard until the call ended |
| Transports never run tools; they queue them | One place (the worker) holds the cancel flags, the queue and the one-at-a-time rule, so stdio and HTTP cannot drift apart ([How it works](./how-it-works.md#two-rules-that-keep-it-testable), "the worker is the only place tool calls run") | Each transport running its own calls |
| `protocol` and `worker` get what they need through `configure()` | `protocol` needs the entry point's text and version, and `worker` needs the transport's `send` and the protocol's `answer`; both sit below what they need, so `metal_trace_mcp.py` passes them in (`metal_trace_mcp.py:49-50`). Both raise a clear error if used before that (`worker.py:11-12`, `protocol.py:35-37`). See [How it works](./how-it-works.md#two-rules-that-keep-it-testable) | Importing upward: the architecture test forbids it |
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
| The protocol | `protocol.py` (`handle` `:86`, `answer` `:191`, `era` `:40`) | One JSON-RPC request in, one reply out; see [Two eras](#the-two-eras-as-a-reference) |
| The worker | `worker.py` (`submit` `:41`, `work` `:60`, `call` `:143`, `cancel_call` `:93`, `cancel_item` `:118`) | The queue, the thread, the cancel flags, the checks before a tool runs |
| The registry | `registry.py` (`TOOLS` `:69`, `RESOURCES` `:12`, `PROMPTS` `:193`) | What clients can ask for: tools with their schemas, resources, prompts |
| Logs | `logs.py` (9 lines) | The one function that writes to stderr |
| Settings | `config.py` (`MAX_QUEUE` `:52`, `MIN_TOKEN` `:55`, `MAX_BODY` `:56`, `HTTP_TIMEOUT` `:57`, `MAX_TEXT` `:45`) | The limits below; the numbers are in [E3](#e3-the-limits-the-server-applies) |

The layer of each module (7 for the entry point, 6 for the transports, 5 protocol, 4 worker, 3 registry, 0 logs) is in
[How it works](./how-it-works.md#layers) and in `LAYERS` in `tests/test_architecture.py:15-23`.

## How the server starts

`main()` (`metal_trace_mcp.py:79-95`) reads the command line in this order and stops at the first that matches:

| Command line | What happens | Line |
|---|---|---|
| `--version` | Prints `metal-gpu-trace <version>` and returns; the project file is not read | `:82-84` |
| anything else | Applies the project file once ([How it works](./how-it-works.md#where-recordings-live-and-what-reads-them): which folder holds the recordings) | `:85` |
| `check RUN BASELINE [--margin-pct N]` | Judges a run for CI and exits 0, 1 or 2; no server | `:86-87`, `:53-76` |
| `--http [--port N]` | Serves HTTP; port 8765 when `--port` does not follow, a usage line and exit 2 when the number is missing or not an integer | `:88-94` |
| nothing else matches | Serves stdio until stdin closes | `:95` |

There is no `--stdio` flag: stdio is what is left when nothing else matched (see [limit 4](#known-limits)).

### stdio

`serve_stdio` (`stdio.py:25-53`) is the whole transport:

- It switches stdin and stdout to UTF-8 (`:27-29`), so the encoding does not depend on the language settings of whoever
  launched it.
- It reads `sys.stdin` line by line until the client closes it (`:30`). Empty lines are skipped (`:31-32`).
- Each line is JSON. Three kinds of message are told apart before anything else:
  - `notifications/cancelled` goes to `worker.cancel_call` with the request id it names (`:35-37`);
  - a `tools/call` with a text or number id is registered (`worker.CALLS[id] = Event()`) and queued (`:38-44`);
  - everything else is answered on the spot by `protocol.handle` (`:45`), in the reading thread.
- A line that is not JSON is answered with `-32700 parse error` and `id: null` (`:46-47`). Any other exception from
  `protocol.handle` is logged as `internal error <ExceptionName>` and answered `-32603 internal error` (`:48-50`), so one
  bad message cannot stop the server.
- When stdin closes, `worker.stop_worker()` runs (`:53`): the calls already queued are finished, then the thread ends
  ([limit 3](#known-limits)).
- `send` writes a message as one line of JSON under a lock, so two threads (the reader answering a `ping` and the worker
  sending a progress notification) never interleave their bytes (`:9`, `:12-16`).

### HTTP

`serve_http(port)` (`http_transport.py:182-196`) does four things, in this order:

1. Reads `METAL_TRACE_TOKEN`. Shorter than `config.MIN_TOKEN` (16 characters) or missing: prints
   `metal-gpu-trace: set METAL_TRACE_TOKEN to a secret of at least 16 characters` on stderr and returns 2, so the process
   exits with status 2 (`:186-189`). The server never starts without a token.
2. Builds a `ThreadingHTTPServer` bound to `("127.0.0.1", port)` (`:190`): one thread per connection, loopback only, IPv4
   only. Port 0 lets the system choose.
3. Logs `metal-trace: serving http://127.0.0.1:<port>/mcp` with the port it really got (`:191`).
4. Serves until `KeyboardInterrupt` (`:192-195`) and returns 0.

Every connection is handled by the `Handler` class that `http_handler(token)` builds (`:85-179`). Two facts from the
standard library matter: `ThreadingHTTPServer` starts daemon threads (`daemon_threads = True`, E7) and the base handler
speaks HTTP/1.0 by default (`protocol_version = "HTTP/1.0"`, E7), which this handler does not change. So each request is
its own connection, closed after the reply, and a handler thread never outlives its request. Both facts are from the
Python 3.9 standard library read for this page; for another Python version they are **probable**.

### The other half of start-up: what is configured, and when

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

## The tool registry

`registry.py` is data: it imports the domain modules (`analysis`, `experiments`, `recording`, `traces`, `workloads`,
`project`) and puts their functions in three tables. It runs nothing.

**Tools** (`TOOLS`, `registry.py:69-188`): a name maps to a tuple of three things, `(function, schema, hints)`.

- `function` is the domain function, such as `recording.tool_perf_record`. It takes keyword arguments and returns a
  dictionary.
- `schema` is a JSON Schema object built by `schema(properties, required)` (`:24-26`). It is what the client sees as
  `inputSchema`, and what `worker.check_arguments` checks a call against.
- `hints` come from `hints(title, destructive, idempotent, open_world)` (`:29-34`) and become the tool's MCP annotations.
  The default is read-only; passing `destructive=True` or `False` says the tool writes and whether its writes stop
  programs. Today 16 of the 26 tools are read-only and 10 write (E4); the five that record (`perf_record`,
  `perf_baseline_record`, `perf_sweep`, `perf_ab`, `perf_cold_warm`) are the ones with `destructiveHint: true`, because
  they stop programs.

What `tools/list` builds from a row is in `protocol.py:146-150`: the description is the function's docstring
(`inspect.cleandoc`, so indentation is removed), a tool without properties gets `additionalProperties: false`, three tools
(`perf_runs`, `trace_query`, `capture_records`, `PAGED_TOOLS` `:9`) get the paged output schema (`PAGED` `:6-8`), and
`META` adds `anthropic/requiresUserInteraction` to the two tools that download and install things (`workload_fetch`,
`presentmon_install`, `registry.py:190-191`), so a client that honours it asks the person before each call (E4).

**Resources** (`RESOURCES`, `registry.py:12-15`): one for all the GPU families and one per family in
`data/apple-gpu-families.json`, read-only JSON: five in the recorded `resources/list` (E9). The recordings are a resource
too, but not from this table: `metal-trace://runs/<run>` is a template (`resources/templates/list`) that `protocol.handle`
serves by reading the summary (`protocol.py:118-145`).

**Prompts** (`PROMPTS`, `registry.py:193-216`): `compare-layer`, `diagnose-stutter` and `bisect-regression`. Each has a
`render` function that builds text for the agent; the server runs nothing, and `prompts/list` leaves `render` out
(`protocol.py:152-153`). `prompts/get` drops every argument whose value is empty or fails `paths.name_ok` before
calling `render` (`:159`).

### What pins the registry

- `test_tool_schemas_match_signatures` (`tests/test_server.py:1137`): every argument a function takes is in its schema,
  every argument without a default is required, and a schema name the function does not take is allowed only when the
  function forwards `**kwargs`. This matters because `tools/call` refuses names the schema lacks.
- `test_readme_lists_every_tool` (`tests/test_server.py:18`): both READMEs hold a table row for every tool.
- The count 26 appears in four places (`tests/test_server.py:14`, `:139`, `:325`, `:666`), and `tests/golden/protocol.json`
  holds the full `tools/list` reply. Adding a tool changes all of them on purpose.

## The worker

`worker.py` runs the tool calls. Its state is five module-level objects (`:30-33`):

| Name | What it holds |
|---|---|
| `QUEUE`, with `WAKE` (a `Condition`) | The calls waiting for the thread: `(message, reply, event)` tuples |
| `WORKER` | A list that is empty until the first call, then holds the one thread (**speculation:** a list so the module can test and set it without `global`) |
| `CALLS` | Request id to cancel flag, for the calls in flight |
| `CANCELLED` | Ids the client cancelled whose reply is not out yet |
| `CURRENT` | A thread-local that holds the flag of the call the thread is running, when its transport gave one |

### Putting a call in the queue (`submit`, `:41-57`)

A call is added under the lock if fewer than `MAX_QUEUE` (64) are waiting. The first call starts the thread (`daemon=True`,
`:49-51`): a server that has never been asked for a tool has no worker. If 64 are already waiting, the call is **not**
queued: its id leaves `CALLS` and the transport's `reply` callback receives at once an error result that says
`64 calls are already waiting; try again when one finishes` (`:53-57`), worded in the era of the request through
`protocol.finish` (`worker.configure`'s `finish`). The tests that pin it are `test_queue` (`tests/test_server.py:354`) and
the three that check the entry is left clean (`:421`, `:453`).

### Running one (`work`, `:60-80`)

The thread waits for the queue to have something, takes the first item and runs `reply(_answer(message))`: `_answer` is
`protocol.answer`, which is `protocol.handle` with a safety net (`protocol.py:191-198`), and `reply` is the callback the
transport gave. A `None` item is the stop sign (`:67-68`). If the reply fails (a client that left in the middle of the write)
the exception is caught and logged as `reply to <id> failed: <ExceptionName>`, and the thread goes on with the next call
(`:73-74`): without that catch, one broken pipe would end the thread and every later call would wait for ever
(`test_worker_survives_a_failing_reply`, `tests/test_server.py:951`). In the `finally`, under the lock, the call's entry is
removed from `CALLS` (only if it is still this call's own) and its id from `CANCELLED` (`:75-80`).

### Checks before a tool runs (`call`, `:143-172`)

`protocol.handle` calls `worker.call` for a `tools/call` (`protocol.py:170`). Its steps, with what the client gets when each
fails:

| Step | Fails when | The client gets | Line |
|---|---|---|---|
| Cancelled already | The flag was set before the function started | `the call was cancelled before it started` (error result) | `:153-154` |
| `project.check()` | The `metal-gpu-trace.json` is wrong | The project's own message (error result); the server keeps running | `:155` |
| `check_arguments` | `arguments` is not an object, or a name is missing, or a name is not in the schema | `bad arguments: unknown argument x`, `missing argument y`, or `arguments must be an object` | `:156-157`, `:130-140` |
| The function | It raises `ToolError`, `FileNotFoundError`, `ValueError`, `RuntimeError` or `TimeoutExpired` | The exception's text (error result) | `:158`, `:165-166` |
| The function | It raises anything else | `internal error: <ExceptionName>` and nothing more | `:167-168` |
| The result | It is not a dictionary | `<tool> returned <type>, not an object` | `:159-160` |
| The result | Its JSON is longer than `MAX_TEXT` (40 000 characters) | `the result has N characters; ask for a smaller page with limit` | `:161-163`, `config.py:45` |

`check_arguments` checks only the names (`required`, and the ones in `properties`); the types are checked by each tool
(`worker.py:130-132`, the docstring). A success returns `content` (the JSON as text) and `structuredContent` (the same
object), so a client can use either (`:164`). The 40 000 comes from a client limit: the comment in `config.py:44` says
results stay under Claude Code's 50 000-character limit, above which it saves them to a file.

Last, `call` writes the log line `<tool> ok|error in <seconds> s` (`:171`). Note what it does not hold: no argument, no
label, no path, no result. See [Logs](#logs).

### Cancel

There are two cancels, because stdio and HTTP know different things about their clients.

- `cancel_call(request_id)` (`:93-115`), by **id**. If the call is still in the queue it is taken out and answered at once
  with `the call was cancelled before it started` (`:101-111`); if it is running, its flag is set (`:112-115`) and the tool
  stops at its next look. Either way the id goes into `CANCELLED` until the reply is out, so a transport that can stay
  silent (stdio) writes nothing (`stdio.py:19-22`). An id that cannot be a dictionary key is ignored (`:96-99`).
- `cancel_item(message, event)` (`:118-127`), by **identity**. Used by HTTP when a modern client closes its connection:
  two HTTP clients can send the same id, so it matches the very message and the very flag, takes a queued message out
  without answering (its client is gone) and sets the flag (`test_http_close_spares_another_client_with_the_same_id`,
  `tests/test_server.py:1107`).

How the recording notices the flag is in [Recording](./recording.md): `recording.cancelled()` reads a thread-local
(`recording.py:224-230`) that `worker.call` fills at its start with the call's own flag (`worker.py:147-148`).

### Progress

Only a call whose request carries a `progressToken` has progress. `worker.call` sets `recording.RUN.progress` to a function
that sends `notifications/progress` (`worker.py:149-151`), unless the id has already been cancelled. `recording.progress`
calls it every `config.PROGRESS_TICKS` (5) seconds while a recording runs. The notification goes out through `_send`, which
`metal_trace_mcp.py:50` set to `stdio.send`. That is right for stdio and wrong for HTTP, which is why the HTTP handler
removes `progressToken` before it queues a call (`http_transport.py:145-151`; [limit 11](#known-limits)).

## One call through the server

![The MCP client, the transport, the worker, the protocol and the registry as five columns. Eight numbered arrows from top to bottom: the client sends a tools/call to the transport; the transport queues it in the worker; the worker asks the protocol to answer; the protocol checks the era, the _meta and the tool name and calls back into the worker; the worker checks the arguments and runs the function from the registry; the registry returns a dictionary or an error; the worker hands the reply to the transport; the transport writes a stdout line or an HTTP 200. A band marks the worker as busy from step 3 to step 7.](/diagrams/server-request-sequence.png)
*Figure 1. One `tools/call`. HTML source: `docs/diagrams/server-request-sequence.html`.*

Two things the figure shows that [How it works](./how-it-works.md#one-request-end-to-end) says in another order. The queue
comes **before** `protocol.handle` for a `tools/call`: the transport queues the raw message (`stdio.py:43`,
`http_transport.py:154`) and the worker thread is the one that calls `protocol.answer` (`worker.py:72`). `ping`,
`tools/list`, `resources/*` and `prompts/*` never touch the queue: the transport calls `protocol.handle` itself, so they
are answered even while a recording runs ([limit 1](#known-limits)).

## The two eras, as a reference

This page decides nothing about the two eras; [ADR-0002](../adr/0002-dual-era-mcp.md) does, and
[How it works](./how-it-works.md#why-it-is-shaped-this-way) says why. What a person who touches the transports needs is
where the line between them is drawn:

| | Old era (`initialize`) | Modern era (2026-07-28) | Where |
|---|---|---|---|
| How the server knows | Everything else, and always `initialize` | `server/discover`, or `params._meta` holds the version or the client capabilities | `protocol.py:40-49` |
| Versions | `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05` | `2026-07-28` | `:23-24` |
| First message | `initialize`: answered with the client's version when listed, else the newest | No handshake; `server/discover` answers the supported versions, the capabilities and `INSTRUCTIONS` | `:107-115` |
| `ping` | Answered `{}` | Not a method: `-32601 unknown method ping` | `:116-117`; `:28-29`, `:104-105` |
| A resource that is missing | `-32002` | `-32602` | `:106` |
| The result | As is | Adds `resultType: complete`, the server's name and version in `_meta`, and for lists, reads and discover `ttlMs` and `cacheScope` | `:71-83` |
| HTTP headers | `MCP-Protocol-Version` is optional, and when sent must be a listed old version | `MCP-Protocol-Version` and `Mcp-Method` required, and `Mcp-Name` for three methods | `http_transport.py:58-82` |
| Cancel over HTTP | `notifications/cancelled` by request id | Closing the connection | `http_transport.py:137-159` |

The recorded replies in `tests/golden/protocol.json` show the difference: the same `resources/read` of a missing run
answers `-32002` in the old era and `-32602` in the modern one, and `ping` is `-32601` in the modern one (E9).

## HTTP in detail

A client that cannot start a stdio server sends `POST http://127.0.0.1:8765/mcp` with an `Authorization: Bearer <token>`
header and one JSON message as the body. The token is the one in `METAL_TRACE_TOKEN`; the examples below write
`<token>` and never a real one.

### The checks, in order

![Seven boxes in a row, left to right: path, host and origin, token, size, JSON, headers and run. Under each of the first six, the status it answers with: 404, 403, 401, 413, 400 with a parse error, and 400 or 404 with a JSON-RPC error. If all pass, the request runs.](/diagrams/server-http-checks.png)
*Figure 2. What `do_POST` checks before anything runs. HTML source: `docs/diagrams/server-http-checks.html`.*

Think of a building with a doorman: the first question is whether you came to the right door (the path), the second whether
you come from the street outside or from somewhere pretending to be it (Host and Origin), the third whether you hold the
key (the token), and only then does anyone look at what you carry (the body). The order matters: a client with no token
never gets its body read.

| # | Check | Status | The reply | Pinned by |
|---|---|---|---|---|
| 0 | The method is POST (`do_GET`, `do_DELETE`) | 405 | Empty; any GET or DELETE, before any other check. `PUT`, `HEAD` and the rest are not defined here: the standard library answers them (**probable**: 501; not run) | `tests/test_server.py:321`, `:893` |
| 1 | `self.path == "/mcp"` | 404 | Empty body | `:322` |
| 2 | Host is `localhost` or `127.0.0.1`, and an Origin, when sent, is too | 403 | Empty body | `:317-320` |
| 3 | `Authorization` carries the token | 401 | Empty body | `:315-316` |
| 4 | `Content-Length` is digits, at most 12 of them, and between 0 and `MAX_BODY` (1 000 000) | 413 | Empty body | `tests/test_adversarial.py:225` |
| 5 | The body is UTF-8 JSON that is not nested beyond what the parser accepts | 400 | A JSON-RPC error, `-32700 parse error`, `id: null` | `:1031` |
| 6 | `check_headers` | 400 or 404 | A JSON-RPC error with the codes in the next table | `:838`, `:847` |

Statuses 404, 403, 401 and 413 have an **empty** body on purpose (`reply(code)` with no body, `http_transport.py:99-101`):
a refusal tells the client nothing it did not know. The lines are `:119-129`, and E1 lists every `self.reply` of the file
with its line.

**Host and Origin** (`foreign`, `:108-111`; `local_host`, `:17-20`). The function removes a leading `scheme://` and
anything after a `/`, takes what comes before the first `:` and accepts only `localhost` or `127.0.0.1`. The port does
not matter. An `Origin` is checked only when the client sent one; a `Host` that is missing counts as not local. The tests
pin `http://evil.example`, `http://localhost.evil.example` and `Host: evil.example` as 403 and `http://localhost:<port>` as 200
(`tests/test_server.py:317-320`). Why both: a page on `evil.example` whose name was made to resolve to `127.0.0.1` sends
`Host: evil.example`, so the Host check stops it; a browser also sends an `Origin` on a cross-site POST, so the Origin check
stops the page that does not even need rebinding.

**The token** (`unauthorized`, `:113-116`). The header has `Bearer ` removed if it starts with it, and the rest is compared
with `hmac.compare_digest`, which takes the same time whatever the first wrong byte is. The token itself is read once
at start (`:186`), never logged, never printed and never part of a reply; the only message about it is the refusal to start
(E5, `:188`). A missing header, an empty one and a wrong one are all 401 (`tests/test_server.py:315-316`).

**Size** (`:125-129`). A `Content-Length` that is not ASCII digits (`²` passes `str.isdigit()` and fails `int()`) or has more
than 12 characters, or is over 1 000 000, is 413 without reading the body; one test asks with `0xB2` and with 5 000 nines
(`tests/test_adversarial.py:225-232`). No `Content-Length` counts as 0, so a body sent without it, or with
`Transfer-Encoding: chunked`, is read as empty and answered 400 `-32700` ([limit 8](#known-limits)).

### `check_headers`: when the headers do not match the body

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

### After the checks

1. **`notifications/cancelled`** (`:137-142`): answered `202` with an empty body. Under the old era it cancels the call
   by id (`worker.cancel_call`); under the modern era it is accepted and **ignored**, because a modern client cancels by
   closing the connection and an id may be shared by another client (`tests/test_server.py:1165`).
2. **`tools/call` with an id** (`:143-162`):
   - Strips what the endpoint cannot stream. In the modern era `progressToken` is removed from `_meta` and the version
     stays; in the old era `_meta` is removed (`:147-151`).
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

### The reply helper and a client that left

`reply` (`:95-106`) writes the status, a `Content-Type` only when there is a body, a `Content-Length` always, and the body.
A `ConnectionError` while writing (the client closed during a long call) sets `close_connection` and logs
`client closed the connection` instead of raising (`:104-106`; `test_http_reply_broken_pipe`, `tests/test_server.py:1067`).
`timeout = config.HTTP_TIMEOUT` (15 s, `:93`) drops a client that opens a connection and stalls before finishing its request
(`test_http_timeout`, `:473`), so it cannot hold a thread for ever. `log_message` is empty (`:176-177`): the standard
library's access log, which would print a line for every request, is off.

## Logs

`logs.py` is one function (`:6-9`): it prints `metal-trace: <message>` to stderr and flushes, unless `METAL_TRACE_LOG` is
exactly `off`. Nothing else in the package writes to stderr or stdout on its own: `send` (`stdio.py:12`) is the only
writer of stdout, and `serve_http` prints one more line directly (`http_transport.py:188`, the token message, which
`METAL_TRACE_LOG=off` does **not** silence).

The module's own docstring says "the one stderr line per tool call", and the README too. In the code there are seven callers
(E6), which are the whole log:

| Message | When | Line |
|---|---|---|
| `metal-trace: <tool> ok in <s> s` or `... error in <s> s` | A tool call ended (`error` means an `isError` result) | `worker.py:171` |
| `metal-trace: serving http://127.0.0.1:<port>/mcp` | HTTP started | `http_transport.py:191` |
| `metal-trace: internal error <ExceptionName>` | An exception in `protocol.handle`, in stdio (the reader), in HTTP (the handler) or in `protocol.answer` (the worker) | `stdio.py:49`, `http_transport.py:166`, `protocol.py:196` |
| `metal-trace: reply to <id> failed: <ExceptionName>` | The worker could not write a reply | `worker.py:74` |
| `metal-trace: client closed the connection` | HTTP: the client left during the write | `http_transport.py:106` |

No line holds an argument, a label, a path, a token or a result: only the tool's name, its status, a duration, the type of
an exception (never its text) and, in one line, a request id the client chose. This is **confirmed** for today's seven sites;
nothing enforces it, so a new `logs.log(f"... {value}")` would break it silently ([Touching it](#touching-it-without-breaking-it)).
Where stderr ends up (a file, a pane, nowhere) depends on the client that launched the server: **not verified** here.

## When it fails

The first column is what the client sees.

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
that pin each row are named in the sections above (`tests/test_server.py` unless said otherwise), and they were not run for
this page.

## Known limits

Each item is a limit of today's behaviour, written down, not fixed here.

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | [How it works](./how-it-works.md#one-request-end-to-end) lists "`protocol.handle` checks the era, the `_meta` and that the tool exists" (step 2) **before** "the call waits in the worker queue" (step 3). In the code, for a `tools/call` the transport queues the raw message first and `protocol.handle` runs on the worker thread (an exception: HTTP's `check_headers` runs before the queue). A request that fails the tool-name check therefore waits its turn in the queue before it is refused | `stdio.py:38-44`, `worker.py:72`, `protocol.py:167-169`, `http_transport.py:134-154` | Confirmed; which order the page should say is a decision for the owner |
| 2 | Invalid UTF-8 on stdin is not caught: the decode error is raised by the `for line in sys.stdin` iterator, which is outside the `try` that answers `-32700`. The HTTP transport has a test for the same input (`test_http_unreadable_body_is_a_parse_error`, `:1031`); no test was found for stdio | `stdio.py:30-34`, `:46-50` | Probable: read from the code; not run |
| 3 | Closing stdin does not cancel anything: `stop_worker` queues a stop sign **after** the calls already waiting and waits for the thread, so a running recording, and each queued one, finish before the server ends. By then nobody reads the replies (they fail and are logged). The script's own watcher stops the program if the server process dies ([Recording](./recording.md#what-happens-if-instruments-dies-part-way)), but a server that stays alive with a closed stdin keeps recording | `stdio.py:53`, `worker.py:83-90` | Confirmed by the code; the effect on a real client is probable |
| 4 | An unknown first argument starts stdio silently, and after `--http` only `--port N` is read: `--http 9000` serves on 8765. A port the system refuses (out of range, in use) is not caught and ends in a Python traceback | `metal_trace_mcp.py:88-95`, `http_transport.py:190` | Confirmed for the arguments; the traceback is probable (not run) |
| 5 | The `Bearer ` prefix is optional and case-sensitive: a header that is just the token passes, and `bearer <token>` does not | `http_transport.py:115` | Confirmed by the code; not run. Whether other clients send the scheme in lower case: not verified |
| 6 | `local_host` takes what precedes the first `:`, so `localhost:1@evil.example` counts as local. A browser does not send user information in `Host` or `Origin`, so no way to use it from a web page is known; the tests cover the dotted-suffix trick only | `http_transport.py:17-20`, `tests/test_server.py:317-319` | Confirmed by reading the function; the browser claim is **not verified** |
| 7 | GET and DELETE answer 405 before the Host, Origin and token checks, so an unauthenticated client can tell the port is a server of this kind | `http_transport.py:170-174` | Confirmed (harmless, since it answers nothing else) |
| 8 | Only `Content-Length` is read: `Transfer-Encoding: chunked` is read as an empty body and answered 400 `-32700` | `http_transport.py:125-133` | Probable: not run |
| 9 | A call from an old-era HTTP client waits with no timeout of its own: the length of the call is the tool's. Only a recording has a deadline (15 s per recorded second plus 180, [Recording](./recording.md#one-example-first)); the other tools are short | `http_transport.py:160-161` | Probable |
| 10 | Three spellings of the same name: the startup refusal prints `metal-gpu-trace:` (`:188`, outside `logs` and not silenced by `METAL_TRACE_LOG=off`), the log lines print `metal-trace:` and the server's own name in `serverInfo` is `metal-trace`. `logs.py`'s docstring and the README say one line per call; the code writes seven kinds of line | `http_transport.py:188`, `logs.py:1`, `:9`, `protocol.py:78` | Confirmed (cosmetic) |
| 11 | `worker._send` is `stdio.send` also when the server runs as `--http` (`metal_trace_mcp.py:50`). Progress is safe only because the HTTP handler removes `progressToken` first; if that removal went away, progress would be written to the process's stdout, where no client reads it | `metal_trace_mcp.py:50`, `http_transport.py:145-151`, `worker.py:149-151` | Confirmed (a coupling, not a bug today) |
| 12 | `worker.call` turns `FileNotFoundError`, `ValueError` and `RuntimeError` into the client's text with `str(error)`. The "no path in an error" rule (README) is kept by each tool using `ToolError` with its own wording, not by the worker; a raw `FileNotFoundError` from a new tool would show its path | `worker.py:165-166` | Probable: read from the code; no tool was found to do it today |

## Touching it without breaking it

- **A new tool.** Write `tool_x(...)` in its domain module, returning a dictionary; its docstring becomes the description
  the client reads (first line first). Add the row in `registry.TOOLS` with a schema whose properties match the function's
  parameters, and hints that say whether it writes. A README row (`test_readme_lists_every_tool`), the count 26 in four
  places (`tests/test_server.py:14`, `:139`, `:325`, `:666`) and `tests/golden/protocol.json` change with it: re-record with
  `METAL_TRACE_GOLDEN=write python3 -I tests/run.py` and read the diff, as `tests/golden/README.md` says.
- **A new method in `protocol.handle`.** Decide for each era whether it exists: the modern methods are listed in
  `MODERN_METHODS` (`protocol.py:28-29`), and `check_headers` refuses an HTTP request for any method not in it. Add it to
  `tests/golden/protocol.json` through `GOLDEN_MESSAGES` (`tests/test_server.py:496`, `:514`).
- **A new check on HTTP.** Put it in `do_POST` before the body is read when it is cheap, answer with an **empty** body for a
  policy refusal and with a JSON-RPC error for a protocol one, and add its test next to the `test_http_*` ones with the
  `local_http` helper.
- **Writing from the server.** Never `print` to stdout: it is the protocol. Use `logs.log` for stderr, and never put an
  argument, a path, a label or a token in the message; today every site writes only a name, a status, a duration or an
  exception type.
- **A new transport.** It calls `worker.submit` for a `tools/call` and `protocol.handle` for the rest; it passes its own
  `send` to `worker.configure` through `metal_trace_mcp.py`; it never runs a tool. It lives in layer 6, so it may import
  `protocol` and `worker` but nothing above (`tests/test_architecture.py:15-23`).
- **A new limit.** Put it in `config.py` and read it as `config.NAME` at the place it is used, so a test can patch one
  attribute (the rule in [How it works](./how-it-works.md#two-rules-that-keep-it-testable); `test_http_timeout` patches
  `config.HTTP_TIMEOUT` this way).
- **The text clients read.** `INSTRUCTIONS` changes the reply to `initialize` and to `server/discover`, so
  `tests/golden/protocol.json` changes too; keep a space after every full stop (`tests/test_server.py:1090`).

## Evidence: the commands and their real output

Collected on 2026-11-16 on an Apple silicon Mac. All commands only read. The session that collected them could run
read-only commands (`rg`, `sed`, `jq`), not Python or the server, so nothing below is the output of a request sent to a
live server: the replies in E9 are the ones `tests/golden/protocol.json` holds, which `test_golden_protocol` records by
calling `protocol.handle` and compares on every run.

### E1 Every status the HTTP handler answers, with its line

```text
$ rg -n "self\.reply\((404|403|401|413|405|202)|self\.reply\(400" src/metal_gpu_trace/http_transport.py | cut -c1-130
120:                return self.reply(404)
122:                return self.reply(403)
124:                return self.reply(401)
129:                return self.reply(413)
133:                return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
142:                return self.reply(202)
168:            self.reply(202 if reply is None else 200, reply)
171:            self.reply(405)  # this server has no sessions to end
174:            self.reply(405)  # no event stream: this endpoint only answers POST
```

The order of the line numbers (120, 122, 124, 129, 133) is the order of the checks in Figure 2. The 200 of a call is at
`:162` and `reply` itself at `:95`. Sending a request to see each status was **not reproduced**; `tests/test_server.py:315-323`
asserts 401, 403, 405, 404 and 202 (see the E8 list).

### E2 What `check_headers` refuses, and with which code

```text
$ rg -n "refuse\(|return 400" src/metal_gpu_trace/http_transport.py | rg -v "def refuse" | cut -c1-135
63:            return refuse(400, -32600, f"unsupported MCP-Protocol-Version {version}")
71:        return refuse(400, -32020, "Header mismatch: MCP-Protocol-Version and Mcp-Method are required")
73:        return refuse(400, -32020, "Header mismatch: Mcp-Method does not match the method")
75:        return refuse(400, -32020, "Header mismatch: MCP-Protocol-Version does not match _meta")
77:        return 400, protocol.version_error(mid, version)
79:        return refuse(404, -32601, f"unknown method {method}")
81:        return refuse(400, -32020, f"Header mismatch: Mcp-Name does not match params.{NAMED[method]}")
```

Seven refusals, one per row of the `check_headers` table (the first Old-era row and the two let-through rows return
`None` and are not here). Line 77 is the `-32022` of `protocol.version_error` (`protocol.py:52-55`).

### E3 The limits the server applies

```text
$ rg -n "^(MAX_QUEUE|MIN_TOKEN|MAX_BODY|HTTP_TIMEOUT|MAX_TEXT) " src/metal_gpu_trace/config.py
45:MAX_TEXT = 40_000
52:MAX_QUEUE = 64
55:MIN_TOKEN = 16
56:MAX_BODY = 1_000_000
57:HTTP_TIMEOUT = 15  # seconds a client may take to send its request

$ rg -n "^POLL_S" src/metal_gpu_trace/http_transport.py | cut -c1-40
13:POLL_S = 0.5  # how often a modern PO
```

(The second command is cut at 40 characters by `cut`.) These are the numbers the page uses: 40 000 characters per result,
64 calls waiting, a token of at least 16, a body of at most 1 000 000 bytes, 15 s to send a request and 0.5 s between looks for
a client that left.

### E4 How many tools, how many write, which ask the person

```text
$ rg -c '^    "[a-z_]+": \(' src/metal_gpu_trace/registry.py
26

$ jq -c '[.[2].result.tools[]|.annotations.readOnlyHint]|group_by(.)|map({readOnly:.[0],n:length})' tests/golden/protocol.json
[{"readOnly":false,"n":10},{"readOnly":true,"n":16}]

$ jq -r '[.[2].result.tools[]|select(.annotations.destructiveHint==true)|.name]|join(" ")' tests/golden/protocol.json
perf_record perf_baseline_record perf_sweep perf_ab perf_cold_warm

$ jq -c '.[2].result.tools|map(select(._meta))|map([.name,._meta])' tests/golden/protocol.json
[["workload_fetch",{"anthropic/requiresUserInteraction":true}],["presentmon_install",{"anthropic/requiresUserInteraction":true}]]
```

The first command counts the rows of `TOOLS` by their shape (26); the other three read the `tools/list` reply that the test
recorded (`tests/golden/protocol.json`, third message), not a live server.

### E5 How the command line is read

```text
$ rg -n "sys\.argv" src/metal_gpu_trace/metal_trace_mcp.py | cut -c1-120
82:    if sys.argv[1:] == ["--version"]:
86:    if sys.argv[1:2] == ["check"]:
87:        sys.exit(check_cli(sys.argv[2:]))
88:    if sys.argv[1:2] == ["--http"]:
90:            port = int(sys.argv[3]) if sys.argv[2:3] == ["--port"] else 8765

$ rg -n "METAL_TRACE_TOKEN|MIN_TOKEN" src/metal_gpu_trace/http_transport.py | cut -c1-150
183:    """Serves the MCP endpoint over HTTP on 127.0.0.1 only, until interrupted. METAL_TRACE_TOKEN (at least MIN_TOKEN
186:    token = os.environ.get("METAL_TRACE_TOKEN", "")
187:    if len(token) < config.MIN_TOKEN:
188:        print(f"metal-gpu-trace: set METAL_TRACE_TOKEN to a secret of at least {config.MIN_TOKEN} characters", file=sys.stderr)
```

Only `--port` is looked at after `--http` (limit 4). The value of the variable is read, never printed: the token is not shown
anywhere on this page.

### E6 Every place that writes a log line

```text
$ rg -n "logs\.log" src/metal_gpu_trace | cut -c1-140
src/metal_gpu_trace/stdio.py:49:            logs.log(f"internal error {type(error).__name__}")
src/metal_gpu_trace/http_transport.py:106:                logs.log("client closed the connection")
src/metal_gpu_trace/http_transport.py:166:                logs.log(f"internal error {type(error).__name__}")
src/metal_gpu_trace/http_transport.py:191:    logs.log(f"serving http://127.0.0.1:{server.server_address[1]}/mcp")
src/metal_gpu_trace/protocol.py:196:        logs.log(f"internal error {type(error).__name__}")
src/metal_gpu_trace/worker.py:74:            logs.log(f"reply to {message.get('id')!r} failed: {type(error).__name__}")
src/metal_gpu_trace/worker.py:171:    logs.log(f"{name} {'error' if result.get('isError') else 'ok'} in {time.monotonic() - started:.1f} s")
```

Seven sites. None interpolates an argument, a path, a label or a token; the only client text is the request id at
`worker.py:74`. `logs.py:8` compares `METAL_TRACE_LOG` with `"off"` exactly.

### E7 What the standard library does under `ThreadingHTTPServer`

```text
$ rg -n "daemon_threads|protocol_version = \"" <Command Line Tools>/.../python3.9/http/server.py
145:    daemon_threads = True
623:    protocol_version = "HTTP/1.0"
```

The path is shortened. It is the Python 3.9 that the macOS command line tools ship, the floor the project supports
([ADR-0003](../adr/0003-python-3-9-floor.md)); the same lines in another Python version were not read.

### E8 The tests that pin the behaviour described here

```text
$ rg -n "def test_http|def test_queue|def test_cancel|def test_progress|def test_golden|def test_discover" tests/test_server.py | cut -c1-90
178:def test_progress_and_cancel(tmp_path):
276:def test_http(tmp_path):
354:def test_queue(tmp_path):
473:def test_http_timeout(tmp_path):
525:def test_golden_protocol(tmp_path):
586:def test_discover(tmp_path):
718:def test_cancel_sends_nothing(tmp_path):
729:def test_cancel_running_sends_nothing(tmp_path):
799:def test_http_legacy_cancel_keeps_reply(tmp_path):
817:def test_http_close_cancels(tmp_path):
838:def test_http_legacy_headers(tmp_path):
847:def test_http_modern_headers(tmp_path):
893:def test_http_delete_is_405(tmp_path):
898:def test_http_notification_202_empty(tmp_path):
914:def test_http_cancel_hits_its_own_call():
970:def test_cancel_item_takes_a_queued_call_out():
1031:def test_http_unreadable_body_is_a_parse_error(tmp_path):
1067:def test_http_reply_broken_pipe():
1097:def test_http_modern_notification_without_meta(tmp_path):
1107:def test_http_close_spares_another_client_with_the_same_id(tmp_path):
1165:def test_http_modern_cancel_notification_cancels_nothing(tmp_path):

$ sed -n 315,323p tests/test_server.py | cut -c1-110
        assert post(ping, {"Authorization": "Bearer nope"})[0] == 401
        assert post(ping, {"Authorization": ""})[0] == 401
        assert post(ping, {"Origin": "http://evil.example"})[0] == 403
        assert post(ping, {"Origin": "http://localhost.evil.example"})[0] == 403
        assert post(ping, {"Host": "evil.example"})[0] == 403
        assert post(ping, {"Origin": f"http://localhost:{port}"})[0] == 200
        assert post(None, method="GET")[0] == 405
        assert post(ping, path="/other")[0] == 404
        assert post({"jsonrpc": "2.0", "method": "notifications/initialized"}) == (202, None)
```

These are the assertions of `test_http` for 401, 403, 405, 404 and 202. They were **not run** for this page. The same
file's `test_http` also asserts that a start without a token, and with the token `short`, returns exit status 2
(`tests/test_server.py:289-291`).

### E9 What the server answers, as the tests recorded it

```text
$ jq -c '[.[0,1]|.result.protocolVersion]' tests/golden/protocol.json
["2025-06-18","2025-11-25"]

$ jq -c 'to_entries[] | select(.value.error) | [.key, .value.error.code, .value.error.message[0:44]]' tests/golden/protocol.json
[7,-32002,"Resource not found"]
[9,-32602,"unknown tool no_such_tool"]
[10,-32601,"unknown method no/such/method"]
[16,-32602,"Resource not found"]
[17,-32601,"unknown method ping"]
[18,-32022,"Unsupported protocol version"]
[19,-32602,"_meta must hold io.modelcontextprotocol/prot"]

$ jq -c 'to_entries[12:15][] | [.key, .value.result.resultType, .value.result.ttlMs, .value.result.cacheScope]' tests/golden/protocol.json
[12,"complete",3600000,"public"]
[13,"complete",3600000,"public"]
[14,"complete",null,null]

$ jq -c '[(.[3].result.resources|length), (.[4].result.resourceTemplates|length), (.[5].result.prompts|map(.name))]' tests/golden/protocol.json
[5,1,["compare-layer","diagnose-stutter","bisect-regression"]]
```

How to read it. The first reply (message 0) asked for `2025-06-18` and got it; the second (message 1) asked for `1999-01-01`
and got the newest old version, `2025-11-25`. In the list of errors, message 7 is `resources/read` of a missing run in the
old era (`-32002`) and message 16 is the same in the modern era (`-32602`); 17 is `ping` in the modern era; 18 an unsupported
version; 19 a modern request whose `_meta` lacks the version and capabilities. Messages 12 to 14 are `server/discover`,
`tools/list` and a `tools/call` in the modern era: the first two say they may be cached for an hour (3 600 000 ms, public); the
call says nothing, because a result is not cacheable. Message 3 lists five resources, message 4 one template (the recordings)
and message 5 three prompts.

### What was not reproduced

- Starting the server, over stdio or HTTP, and any request sent to it: `initialize` and `tools/list` by stdio with one JSON
  line, the same by HTTP with `curl` and a test token, and the three refusals live (404, 403, 401). E1 and E8 give the lines
  that produce them and the tests that pin them; E9 gives the replies as recorded by the tests.
- That `tests/test_architecture.py` and the rest of the suite are green: no test was run for this page.
- A cancel on a real recording, over stdio or HTTP (it needs a recording, [Recording](./recording.md)).
- Invalid UTF-8 on stdin, a port that is in use or out of range, a chunked body, and a `PUT` or `HEAD` (limits 2, 4 and 8, and the
  row 0 note): read from the code, not run.
- The official MCP SDK as a client (`tests/conformance/`): it needs the SDK and was not run.
- Where a client shows the server's stderr.

## See also

- [How it works](./how-it-works.md): the layer table, the two rules, and one request in five lines (see [limit 1](#known-limits) for the order).
- [ADR-0002](../adr/0002-dual-era-mcp.md): why the server speaks both eras, the alternatives and the known deviations.
- [Recording](./recording.md): what happens inside `perf_record` after the worker calls it, and how it notices a cancel.
- [Run from a clone](./run-from-a-clone.md): the commands that start the server from a clone.
- `README.md`, section "HTTP": the same endpoint from the user's side.
