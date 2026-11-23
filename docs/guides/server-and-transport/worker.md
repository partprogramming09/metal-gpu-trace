# The worker

**Reader:** people who change how tool calls are queued, checked, cancelled or reported. Reviewed 2026-11-16.

[Index](./index.md)

**In short:** the worker is the one employee who does the work. Requests wait in a line of at most 64; it takes them one at a time, checks each, runs it and hands back the answer. A client's "stop" is a flag the running tool looks at. With one worker, two recordings never run together.

`worker.py` state is five module-level objects (`:30-33`):

| Name | What it holds |
|---|---|
| `QUEUE`, with `WAKE` (a `Condition`) | Waiting calls: `(message, reply, event)` tuples |
| `WORKER` | A list, empty until the first call, then the one thread (**speculation:** a list so the module can test and set it without `global`) |
| `CALLS` | Request id to cancel flag, for calls in flight |
| `CANCELLED` | Ids the client cancelled whose reply is not out yet |
| `CURRENT` | A thread-local with the flag of the call the thread runs, when its transport gave one |

## Putting a call in the queue (`worker.py::submit`)

Under the lock, a call is added if fewer than `MAX_QUEUE` (64) wait. The first call starts the thread (`daemon=True`, `worker.py::submit`): a server never asked for a tool has no worker. If 64 wait, the call is **not** queued: its id leaves `CALLS` and the transport's `reply` gets at once an error result `64 calls are already waiting; try again when one finishes` (`worker.py::submit`), worded for the request's era by `protocol.finish` (`worker.configure`'s `finish`). Pinned by `test_queue` (`tests/test_server.py::test_queue`) and three checking the entry is left clean (`tests/test_server.py::test_rejected_call_leaves_no_entry`, `tests/test_server.py::test_rejected_call_spares_another_clients_entry`).

## Running one (`worker.py::work`)

The thread takes the first item and runs `reply(_answer(message))`: `_answer` is `protocol.answer` (`protocol.handle` with a safety net, `protocol.py::answer`), `reply` the transport's callback. A `None` item is the stop sign (`worker.py::work`). If the reply fails (client left mid-write) the exception is caught, logged as `reply to <id> failed: <ExceptionName>`, and the thread goes on (`worker.py::work`); without it one broken pipe would end the thread and every later call wait for ever (`test_worker_survives_a_failing_reply`, `tests/test_server.py::test_worker_survives_a_failing_reply`). In the `finally`, under the lock, the entry leaves `CALLS` (only if still its own) and the id leaves `CANCELLED` (`worker.py::CANCELLED`).

## Checks before a tool runs (`worker.py::call`)

`protocol.handle` calls `worker.call` for a `tools/call` (`protocol.py::handle`):

| Step | Fails when | The client gets | Line |
|---|---|---|---|
| Cancelled already | The flag was set before the function started | `the call was cancelled before it started` (error result) | `worker.py::call` |
| `project.check()` | The `metal-gpu-trace.json` is wrong | The project's message (error result); the server keeps running | `worker.py::call` |
| `check_arguments` | `arguments` is not an object, a name is missing or not in the schema | `bad arguments: unknown argument x`, `missing argument y`, or `arguments must be an object` | `worker.py::call`, `worker.py::check_arguments` |
| The function | Raises `ToolError`, `FileNotFoundError`, `ValueError`, `RuntimeError` or `TimeoutExpired` | The exception's text (error result) | `worker.py::call` |
| The function | Raises anything else | `internal error: <ExceptionName>` only | `worker.py::call` |
| The result | Is not a dictionary | `<tool> returned <type>, not an object` | `worker.py::call` |
| The result | JSON longer than `MAX_TEXT` (40 000 characters) | `the result has N characters; ask for a smaller page with limit` | `worker.py::call`, `config.py::MAX_TEXT` |

`check_arguments` checks only names (`required`, `properties`); types are each tool's job (`worker.py::check_arguments`). A success returns `content` (JSON as text) and `structuredContent` (the same object) (`worker.py::call`). The 40 000 comes from a client limit: `config.py::MAX_TEXT` says results stay under Claude Code's 50 000-character limit, above which it saves them to a file. `fields` is the one argument every tool takes: a list of dotted paths (`common.frame_pacing.fps_1pct_low`) that cuts the result before it is sized and sent. `tools/list` adds it to each tool's `inputSchema`, and `call` removes it before `check_arguments`, so no tool sees it. A path to an object keeps the whole object; a path through a list applies to each item. On the paged tools (`perf_runs`, `trace_query`, `capture_records`) the paths apply to each row, and `total`, `offset`, `rows` and `next_offset` stay. A path that matches nothing is not invented: the body stays as is and `_meta.fields_missing` lists it. An object left empty stays `{}`. The cut comes before the `MAX_TEXT` check, so an answer that would be refused as too large can fit with `fields`; `structuredContent` and the text hold the same cut value, and `schema_version` does not change because the saved summary is untouched. An empty list means no cut; a value that is not a list of non-empty strings is a `bad arguments` error.

Last, `call` logs `<tool> ok|error in <seconds> s` (`worker.py::call`): no argument, label, path or result ([Logs](./logs.md)).

## Cancel

Two cancels, because stdio and HTTP know different things about their clients.

| Cancel | Key | What it does |
|---|---|---|
| `cancel_call(request_id)` (`worker.py::cancel_call`) | **id** | A queued call is taken out and answered at once with `the call was cancelled before it started` (`worker.py::cancel_call`); a running one gets its flag set (`worker.py::cancel_call`) and stops at its next look. Either way the id stays in `CANCELLED` until the reply is out, so a transport that can stay silent (stdio) writes nothing (`stdio.py::reply_unless_cancelled`). An id that cannot be a dictionary key is ignored (`worker.py::cancel_call`) |
| `cancel_item(message, event)` (`worker.py::cancel_item`) | **identity** | Used by HTTP when a modern client closes its connection: two HTTP clients can send the same id, so it matches the very message and flag, takes a queued message out without answering (its client is gone) and sets the flag (`test_http_close_spares_another_client_with_the_same_id`, `tests/test_server.py::test_http_close_spares_another_client_with_the_same_id`) |

The recording notices the flag through `recording.cancelled()`, a thread-local (`recording.py::cancelled`) that `worker.call` fills with the call's flag at its start (`worker.py::_take`); see [Recording](../recording/index.md).

## Progress

Only a request with a `progressToken` has progress. `worker.call` sets `recording.RUN.progress` to a function sending `notifications/progress` (`worker.py::_take`), unless the id is already cancelled; `recording.progress` calls it every `config.PROGRESS_TICKS` (5) seconds while recording. It goes out through `_send`, which `metal_trace_mcp.py:50` set to `stdio.send`: right for stdio, wrong for HTTP, which is why the HTTP handler removes `progressToken` before queueing (`http_transport.py::do_POST`; [limit 11](./limits.md)).
