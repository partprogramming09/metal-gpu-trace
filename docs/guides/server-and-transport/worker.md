# The worker

**Reader:** people who change how tool calls are queued, checked, cancelled or reported. Reviewed 2026-11-16.

Español: [Worker](../../es/guides/servidor-y-transporte/worker.md) · [Index](./index.md)

**In short:** the worker is the one employee who does the work. Requests wait in a line of at most 64; the worker takes
them one at a time, checks each, runs it and hands back the answer. A "stop" from the client is a flag the running tool
looks at. Because there is one worker, two recordings can never run together.

`worker.py` runs the tool calls. Its state is five module-level objects (`:30-33`):

| Name | What it holds |
|---|---|
| `QUEUE`, with `WAKE` (a `Condition`) | The calls waiting for the thread: `(message, reply, event)` tuples |
| `WORKER` | A list that is empty until the first call, then holds the one thread (**speculation:** a list so the module can test and set it without `global`) |
| `CALLS` | Request id to cancel flag, for the calls in flight |
| `CANCELLED` | Ids the client cancelled whose reply is not out yet |
| `CURRENT` | A thread-local that holds the flag of the call the thread is running, when its transport gave one |

## Putting a call in the queue (`submit`, `:41-57`)

A call is added under the lock if fewer than `MAX_QUEUE` (64) are waiting. The first call starts the thread (`daemon=True`,
`:49-51`): a server that has never been asked for a tool has no worker. If 64 are already waiting, the call is **not**
queued: its id leaves `CALLS` and the transport's `reply` callback receives at once an error result that says
`64 calls are already waiting; try again when one finishes` (`:53-57`), worded in the era of the request through
`protocol.finish` (`worker.configure`'s `finish`). The tests that pin it are `test_queue` (`tests/test_server.py:354`) and
the three that check the entry is left clean (`:421`, `:453`).

## Running one (`work`, `:60-80`)

The thread waits for the queue to have something, takes the first item and runs `reply(_answer(message))`: `_answer` is
`protocol.answer`, which is `protocol.handle` with a safety net (`protocol.py:191-198`), and `reply` is the callback the
transport gave. A `None` item is the stop sign (`:67-68`). If the reply fails (a client that left in the middle of the write)
the exception is caught and logged as `reply to <id> failed: <ExceptionName>`, and the thread goes on with the next call
(`:73-74`): without that catch, one broken pipe would end the thread and every later call would wait for ever
(`test_worker_survives_a_failing_reply`, `tests/test_server.py:951`). In the `finally`, under the lock, the call's entry is
removed from `CALLS` (only if it is still this call's own) and its id from `CANCELLED` (`:75-80`).

## Checks before a tool runs (`call`, `:143-172`)

`protocol.handle` calls `worker.call` for a `tools/call` (`protocol.py:170`). Its steps, with what the client gets when each fails:

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
label, no path, no result. See [Logs](./logs.md).

## Cancel

There are two cancels, because stdio and HTTP know different things about their clients.

| Cancel | Key | What it does |
|---|---|---|
| `cancel_call(request_id)` (`:93-115`) | **id** | A call still in the queue is taken out and answered at once with `the call was cancelled before it started` (`:101-111`); a running one gets its flag set (`:112-115`) and the tool stops at its next look. Either way the id goes into `CANCELLED` until the reply is out, so a transport that can stay silent (stdio) writes nothing (`stdio.py:19-22`). An id that cannot be a dictionary key is ignored (`:96-99`) |
| `cancel_item(message, event)` (`:118-127`) | **identity** | Used by HTTP when a modern client closes its connection: two HTTP clients can send the same id, so it matches the very message and the very flag, takes a queued message out without answering (its client is gone) and sets the flag (`test_http_close_spares_another_client_with_the_same_id`, `tests/test_server.py:1107`) |

How the recording notices the flag is in [Recording](../recording/index.md): `recording.cancelled()` reads a thread-local
(`recording.py:224-230`) that `worker.call` fills at its start with the call's own flag (`worker.py:147-148`).

## Progress

Only a call whose request carries a `progressToken` has progress. `worker.call` sets `recording.RUN.progress` to a function
that sends `notifications/progress` (`worker.py:149-151`), unless the id has already been cancelled. `recording.progress`
calls it every `config.PROGRESS_TICKS` (5) seconds while a recording runs. The notification goes out through `_send`, which
`metal_trace_mcp.py:50` set to `stdio.send`. That is right for stdio and wrong for HTTP, which is why the HTTP handler
removes `progressToken` before it queues a call (`http_transport.py:145-151`; [limit 11](./limits.md)).
