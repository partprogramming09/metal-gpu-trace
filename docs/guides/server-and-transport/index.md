# Server and transport

**Reader:** people who change how the server starts, listens and answers (`metal_trace_mcp.py`, `stdio.py`, `http_transport.py`, `worker.py`, `registry.py`, `logs.py`), who add or rename a tool, or who need to know why a client got a given error, status or silence. Reviewed 2026-11-16.

Español: [Servidor y transporte](../../es/guides/servidor-y-transporte/index.md)

**In short:** the server is the program an AI agent talks to. The agent sends a request ("record this game for 30
seconds"); the server checks it, runs it on one worker so two recordings never fight over the GPU, and writes back the
answer. It can be reached two ways: through a pipe (stdio) or through a local web address (HTTP) that needs a secret
token. This guide follows one request from start to finish and says what happens when something goes wrong.

It does not repeat [How it works](../how-it-works.md) (layer table, the two rules that keep it testable, one request in
five lines) or [ADR-0002](../../adr/0002-dual-era-mcp.md) (why the server speaks two eras of MCP). Reading the recordings is in
[Recording](../recording/index.md) and [Summarizing and analyzing](../summarizing/index.md): this guide stops where a tool function starts.

## The pages

| Page | What it answers |
|---|---|
| [Design](./design.md) | Why the server has this shape; the pieces and the file of each |
| [Startup](./startup.md) | The command line, stdio, HTTP start, what is configured and when |
| [Registry](./registry.md) | Tools, resources, prompts, and what pins them |
| [Worker](./worker.md) | The queue, the checks before a tool runs, cancel, progress |
| [Eras](./eras.md) | Where the old and the modern MCP era differ |
| [HTTP](./http.md) | The seven checks, `check_headers`, what happens after, a client that left |
| [Logs](./logs.md) | The one line on stderr and the seven places that write it |
| [When it fails](./failures.md) | What the client gets and what the server does, per failure |
| [Known limits](./limits.md) | Twelve limits of today's behaviour, not fixed |
| [Touching it](./touching.md) | How to add a tool, method, check, transport or limit |
| [Evidence](./evidence.md) | Every command that was run (E1 to E9) and what was not reproduced |

## How to read the labels

Every technical claim is **confirmed** (with `file:line`, checked with `rg` or `sed` on 2026-11-16 against the working
tree, which is 0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`), **probable** (read from the code but not run
here) or **speculation** (a guess about why). **Not verified** marks an outside fact not checked against its source. Lines
move when the code changes: search the name, not only the number. Every number comes with the command that produced it,
in [Evidence](./evidence.md). **Not reproduced** means the behaviour could not be run for this guide: the session that
wrote it could run read-only commands only, so the server was not started, no request was sent and no test was run; the
tests that pin each behaviour are named instead, and they were **not run** for this guide.

## One example first

Suppose an agent asks the server, over stdio, to record a program for 30 seconds, and changes its mind half way:

```text
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"perf_record","arguments":{"label":"mygame","program":"/path/to/mygame.exe","wine":"/path/to/wine","seconds":30}}}
```

| # | What happens | Where |
|---|---|---|
| 1 | The stdio loop reads the line, sees a `tools/call` with an id and does **not** run it. It makes a cancel flag for id 7, queues the message and goes back to reading at once | `stdio.py:30-44` |
| 2 | The worker thread (started at the first call, kept for the life of the server) takes the message from the queue and asks the protocol to answer it. The protocol checks the tool name is in the registry and hands the call back to `worker.call` | `worker.py:60-72`, `protocol.py:167-169`, `:170` |
| 3 | `worker.call` checks the project file, then that the arguments fit the tool's schema, then runs the function the registry holds for `perf_record`. The 30 seconds go here | `worker.py:155-158` |
| 4 | Meanwhile the agent sends `{"id":8,"method":"ping"}`. The loop is free and answers `ping` itself, in the reading thread, without the queue | `stdio.py:45`, `:51-52` |
| 5 | The agent sends `{"method":"notifications/cancelled","params":{"requestId":7}}`. The loop sets the flag of call 7. The recording looks at it every second and kills itself ([Recording, the kill sequence](../recording/macos-journey.md#the-kill-sequence)); the function raises `the recording was cancelled; nothing was saved` and the worker turns it into an error result. The client cancelled, so stdio writes **nothing** for id 7: the spec says a cancelled call gets no reply | `stdio.py:35-37`, `worker.py:93-115`, `stdio.py:19-22` |
| 6 | Had the agent not cancelled, the function would have returned a dictionary, the worker would have written it as JSON text (40 000 characters at most) and the loop as one line on stdout. Either way the worker writes one stderr line when the call ends: `metal-trace: perf_record error in <seconds> s` or `... ok in <seconds> s` | `worker.py:171` |

The same call over HTTP has the same middle (steps 2, 3 and 6) and a different beginning and end: see [HTTP](./http.md).

![The MCP client, the transport, the worker, the protocol and the registry as five columns. Eight numbered arrows from top to bottom: the client sends a tools/call to the transport; the transport queues it in the worker; the worker asks the protocol to answer; the protocol checks the era, the _meta and the tool name and calls back into the worker; the worker checks the arguments and runs the function from the registry; the registry returns a dictionary or an error; the worker hands the reply to the transport; the transport writes a stdout line or an HTTP 200. A band marks the worker as busy from step 3 to step 7.](./img/server-request-sequence.png)
*Figure 1. One `tools/call`. Source: `img/server-request-sequence.html`.*

Two things the figure shows that [How it works](../how-it-works.md#one-request-end-to-end) says in another order. The queue
comes **before** `protocol.handle` for a `tools/call`: the transport queues the raw message (`stdio.py:43`,
`http_transport.py:154`) and the worker thread is the one that calls `protocol.answer` (`worker.py:72`). `ping`,
`tools/list`, `resources/*` and `prompts/*` never touch the queue: the transport calls `protocol.handle` itself, so they
are answered even while a recording runs ([limit 1](./limits.md)).

## See also

- [How it works](../how-it-works.md): the layer table, the two rules, and one request in five lines (see [limit 1](./limits.md) for the order).
- [ADR-0002](../../adr/0002-dual-era-mcp.md): why the server speaks both eras, the alternatives and the known deviations.
- [Recording](../recording/index.md): what happens inside `perf_record` after the worker calls it, and how it notices a cancel.
- [Run from a clone](../run-from-a-clone.md): the commands that start the server from a clone.
- `README.md`, section "HTTP": the same endpoint from the user's side.
