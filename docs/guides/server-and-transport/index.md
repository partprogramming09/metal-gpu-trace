# Server and transport

**Reader:** people who change how the server starts, listens and answers (`metal_trace_mcp.py`, `stdio.py`, `http_transport.py`, `worker.py`, `registry.py`, `logs.py`), who add or rename a tool, or who need to know why a client got a given error, status or silence. Reviewed 2026-11-16.

**In short:** the server is the program an AI agent talks to. The agent sends a request ("record this game for 30
seconds"); the server checks it and runs it on one worker, so two recordings never fight over the GPU. It is reached
through a pipe (stdio) or a local web address (HTTP) that needs a secret token. This guide follows one request and says
what happens when it fails.

It does not repeat [How it works](../how-it-works.md) (layers, the two rules, a request in five lines) or
[ADR-0002](../../adr/0002-dual-era-mcp.md) (why two eras of MCP). Reading recordings is in [Recording](../recording/index.md)
and [Summarizing and analyzing](../summarizing/index.md): this guide stops where a tool function starts.

## The pages

| Page | What it answers |
|---|---|
| [Design](./design.md) | Why the server has this shape; the pieces and the file of each |
| [Configuration](./configuration.md) | Environment variables and project files |
| [Startup](./startup.md) | The command line, stdio, HTTP start, what is configured and when |
| [Registry](./registry.md) | Tools, resources, prompts, and what pins them |
| [Worker](./worker.md) | The queue, the checks before a tool runs, cancel, progress |
| [Eras](./eras.md) | Where the old and the modern MCP era differ |
| [HTTP](./http.md) | The seven checks, `check_headers`, what happens after, a client that left |
| [Logs](./logs.md) | The one line on stderr and the seven places that write it |
| [When it fails](./failures.md) | What the client gets and what the server does, per failure |
| [Known limits](./limits.md) | Twelve limits of today's behaviour: eleven open, one fixed (row 2) |
| [Touching it](./touching.md) | How to add a tool, method, check, transport or limit |
| [Evidence](./evidence.md) | Every command that was run (E1 to E9) and what was not reproduced |

## How to read the labels

Every claim is **confirmed** (`file:line`, checked with `rg` or `sed` on 2026-11-16 against the working tree: 0.27.3), **probable** (read from the code, not run) or **speculation** (a guess at
why). **Not verified** marks an outside fact not checked at its source. Lines move: search the name, not only the number.
Every number has its command in [Evidence](./evidence.md). **Not reproduced** means not run: the session that wrote this
could only read, so no server was started, no request sent, no test run; the tests that pin each behaviour are named and
were **not run**.

## One example first

An agent asks, over stdio, to record a program for 30 seconds, and changes its mind half way:

```text
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"perf_record","arguments":{"label":"mygame","program":"/path/to/mygame.exe","wine":"/path/to/wine","seconds":30}}}
```

| # | What happens | Where |
|---|---|---|
| 1 | The stdio loop sees a `tools/call` with an id and does **not** run it: it makes a cancel flag for id 7, queues the message and goes back to reading | `stdio.py:42-48` |
| 2 | The worker thread (started at the first call, kept for the life of the server) takes it and asks the protocol to answer; the protocol checks the tool name is in the registry and hands the call to `worker.call` | `worker.py:60-72`, `protocol.py:167-169`, `:170` |
| 3 | `worker.call` checks the project file, then the arguments against the schema, then runs the registry's function. The 30 seconds go here | `worker.py:155-158` |
| 4 | Meanwhile `{"id":8,"method":"ping"}` arrives. The loop is free and answers `ping` itself, in the reading thread, without the queue | `stdio.py:49`, `:55-56` |
| 5 | `{"method":"notifications/cancelled","params":{"requestId":7}}` sets the flag of call 7. The recording looks at it every second and kills itself ([Recording, the kill sequence](../recording/macos-journey.md#the-kill-sequence)); the function raises `the recording was cancelled; nothing was saved` and the worker turns it into an error result. stdio writes **nothing** for id 7: the spec says a cancelled call gets no reply | `stdio.py:35-37`, `worker.py:93-115`, `stdio.py:19-22` |
| 6 | Without a cancel, the function returns a dictionary, written as JSON text (40 000 characters at most) and as one stdout line. Either way the worker writes one stderr line: `metal-trace: perf_record error in <seconds> s` or `... ok in <seconds> s` | `worker.py:171` |

Over HTTP the middle (steps 2, 3, 6) is the same; the beginning and end differ: see [HTTP](./http.md).

![The MCP client, the transport, the worker, the protocol and the registry as five columns. Eight numbered arrows from top to bottom: the client sends a tools/call to the transport; the transport queues it in the worker; the worker asks the protocol to answer; the protocol checks the era, the _meta and the tool name and calls back into the worker; the worker checks the arguments and runs the function from the registry; the registry returns a dictionary or an error; the worker hands the reply to the transport; the transport writes a stdout line or an HTTP 200. A band marks the worker as busy from step 3 to step 7.](./img/server-request-sequence.png)
*Figure 1. One `tools/call`. Source: `img/server-request-sequence.html`.*

The figure differs from [How it works](../how-it-works.md#one-request-end-to-end) in one order: the queue comes **before**
`protocol.handle` for a `tools/call` (`stdio.py:47`, `http_transport.py:154`; the worker calls `protocol.answer`,
`worker.py:72`). `ping`, `tools/list`, `resources/*` and `prompts/*` skip the queue and are answered even while a
recording runs ([limit 1](./limits.md)).

## See also

[Run from a clone](../run-from-a-clone.md) (the commands that start the server) and `README.md`, section "HTTP" (the same endpoint from the user's side).
