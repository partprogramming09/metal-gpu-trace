"""Runs tool calls one at a time on a worker thread, with cancellation and progress."""
import collections
import json
import subprocess
import threading
import time

from metal_gpu_trace import config, logs, paths, recording, registry


def _not_configured(message):
    raise RuntimeError("worker.configure() was not called: import metal_gpu_trace.metal_trace_mcp first")


_send = _not_configured  # set by configure(): writes one JSON-RPC message to the client
_answer = _not_configured  # set by configure(): returns the reply to one tools/call
_finish = lambda message, reply: reply  # set by configure(): puts a reply built here in the era of its request


def configure(send, answer, finish=None):
    """Sets how call() sends progress notifications (`send(message)`), how the worker answers a tools/call
    (`answer(message)`) and how it words the replies it builds itself (`finish(message, reply)`). They come in from
    outside because this module sits below the protocol and the transports."""
    global _send, _answer, _finish
    _send, _answer = send, answer
    if finish is not None:
        _finish = finish


CALLS = {}  # request id -> cancel event, for the tool calls in flight
CANCELLED = set()  # ids of calls the client cancelled and whose reply is not out yet: stdio sends nothing for them
QUEUE, WAKE, WORKER = collections.deque(), threading.Condition(), []  # tool calls waiting for the one worker thread
CURRENT = threading.local()  # the cancel event of the call the worker thread runs, when its transport gave one


def error_result(request_id, text):
    """Returns a tools/call reply that failed with `text`."""
    return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}], "isError": True}}


def submit(message, reply, event=None):
    """Queues a tools/call for the worker thread, which runs calls one at a time; `reply` receives its JSON-RPC reply.
    A queue of MAX_QUEUE calls is answered at once with an error instead of growing without limit. `event`, when
    given, is this call's own cancel event: HTTP clients may share an id, so they cancel with cancel_item."""
    with WAKE:
        full = len(QUEUE) >= config.MAX_QUEUE
        if not full:
            QUEUE.append((message, reply, event))
            if not WORKER:
                WORKER.append(threading.Thread(target=work, daemon=True))
                WORKER[0].start()
            WAKE.notify()
        else:
            CALLS.pop(message["id"], None)
    if full:
        reply(_finish(message, error_result(message["id"],
                                            f"{config.MAX_QUEUE} calls are already waiting; try again when one finishes")))


def work():
    """Runs the queued tool calls in order until it takes the None that stop_worker queues."""
    while True:
        with WAKE:
            while not QUEUE:
                WAKE.wait()
            item = QUEUE.popleft()
        if item is None:
            return
        message, reply, CURRENT.event = item
        try:
            reply(_answer(message))
        except Exception as error:  # a client gone mid-write must not end the thread every later call waits on
            logs.log(f"reply to {message.get('id')!r} failed: {type(error).__name__}")
        finally:
            CURRENT.event = None
            with WAKE:  # under the lock cancel_call holds from its check of CALLS to its add: no id is left behind
                CANCELLED.discard(message["id"])


def stop_worker():
    """Lets the queued tool calls finish, then ends the worker thread."""
    with WAKE:
        if not WORKER:
            return
        QUEUE.append(None)
        WAKE.notify()
    WORKER[0].join()


def cancel_call(request_id):
    """Cancels the tool call `request_id`: one still queued is answered at once, a running one is told to stop. Either
    way the id goes into CANCELLED until its reply is out, and a transport that can stay silent sends nothing."""
    try:
        hash(request_id)
    except TypeError:
        return
    with WAKE:
        queued = next((item for item in QUEUE if item and item[0].get("id") == request_id), None)
        if queued:
            QUEUE.remove(queued)
        if queued or request_id in CALLS:
            CANCELLED.add(request_id)
    if queued:
        CALLS.pop(request_id, None)
        try:
            queued[1](_finish(queued[0], error_result(request_id, "the call was cancelled before it started")))
        finally:
            CANCELLED.discard(request_id)
    elif request_id in CANCELLED:
        event = CALLS.get(request_id)
        if event:
            event.set()


def cancel_item(message, event):
    """Cancels one call by identity, not by id: the queued `message` leaves the queue unanswered (its client is gone),
    and a running call sees its own `event` set. Used when an HTTP client closes its connection."""
    with WAKE:
        queued = next((item for item in QUEUE if item and item[0] is message), None)
        if queued:
            QUEUE.remove(queued)
            if CALLS.get(message.get("id")) is event:
                CALLS.pop(message.get("id"), None)
    event.set()


def check_arguments(schema, arguments):
    """Returns why `arguments` do not fit the tool `schema`, or None when they do: it checks only the `required` names
    and, when the schema lists `properties`, the names it does not know. Types stay with each tool."""
    if not isinstance(arguments, dict):
        return "arguments must be an object"
    unknown = sorted(k for k in arguments if k not in schema["properties"]) if "properties" in schema else []
    missing = [k for k in schema.get("required", ()) if k not in arguments]
    for word, names in (("unknown", unknown), ("missing", missing)):
        if names:
            return f"{word} argument{'s' if len(names) > 1 else ''} {', '.join(names)}"
    return None


def call(name, arguments, request_id=None, token=None):
    """Runs one tool and returns its MCP result, with failures as isError results that say what to do. A client's
    notifications/cancelled for `request_id` stops it; `token` is the client's progressToken, if it sent one."""
    started = time.monotonic()
    own = getattr(CURRENT, "event", None)
    recording.RUN.cancel = own or (CALLS.setdefault(request_id, threading.Event()) if request_id is not None else None)
    recording.RUN.progress = None if token is None else lambda done, total, message: request_id in CANCELLED or _send(
        {"jsonrpc": "2.0", "method": "notifications/progress",
         "params": {"progressToken": token, "progress": done, "total": total, "message": message}})
    try:
        if recording.cancelled():
            raise paths.ToolError("the call was cancelled before it started")
        if (problem := check_arguments(registry.TOOLS[name][1], arguments)) is not None:
            raise paths.ToolError(f"bad arguments: {problem}")
        value = registry.TOOLS[name][0](**arguments)
        if not isinstance(value, dict):
            raise RuntimeError(f"{name} returned {type(value).__name__}, not an object")
        text = json.dumps(value, ensure_ascii=False)
        if len(text) > config.MAX_TEXT:
            raise paths.ToolError(f"the result has {len(text)} characters; ask for a smaller page with limit")
        result = {"content": [{"type": "text", "text": text}], "structuredContent": value}
    except (paths.ToolError, FileNotFoundError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
    except Exception as error:  # an unexpected failure is reported to the client, not fatal to the server
        result = {"content": [{"type": "text", "text": f"internal error: {type(error).__name__}"}], "isError": True}
    if CALLS.get(request_id) is recording.RUN.cancel:  # another client's call with this id keeps its entry
        CALLS.pop(request_id, None)
    logs.log(f"{name} {'error' if result.get('isError') else 'ok'} in {time.monotonic() - started:.1f} s")
    return result
