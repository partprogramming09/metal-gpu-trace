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


def configure(send, answer):
    """Sets how call() sends progress notifications (`send(message)`) and how the worker answers a tools/call
    (`answer(message)`). They come in from outside because this module sits below the protocol and the transports."""
    global _send, _answer
    _send, _answer = send, answer


CALLS = {}  # request id -> cancel event, for the tool calls in flight
QUEUE, WAKE, WORKER = collections.deque(), threading.Condition(), []  # tool calls waiting for the one worker thread


def error_result(request_id, text):
    """Returns a tools/call reply that failed with `text`."""
    return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": text}], "isError": True}}


def submit(message, reply):
    """Queues a tools/call for the worker thread, which runs calls one at a time; `reply` receives its JSON-RPC reply.
    A queue of MAX_QUEUE calls is answered at once with an error instead of growing without limit."""
    with WAKE:
        full = len(QUEUE) >= config.MAX_QUEUE
        if not full:
            QUEUE.append((message, reply))
            if not WORKER:
                WORKER.append(threading.Thread(target=work, daemon=True))
                WORKER[0].start()
            WAKE.notify()
    if full:
        CALLS.pop(message["id"], None)
        reply(error_result(message["id"], f"{config.MAX_QUEUE} calls are already waiting; try again when one finishes"))


def work():
    """Runs the queued tool calls in order until it takes the None that stop_worker queues."""
    while True:
        with WAKE:
            while not QUEUE:
                WAKE.wait()
            item = QUEUE.popleft()
        if item is None:
            return
        reply = item[1]
        reply(_answer(item[0]))


def stop_worker():
    """Lets the queued tool calls finish, then ends the worker thread."""
    with WAKE:
        if not WORKER:
            return
        QUEUE.append(None)
        WAKE.notify()
    WORKER[0].join()


def cancel_call(request_id):
    """Cancels the tool call `request_id`: one still queued is answered at once, a running one is told to stop."""
    try:
        hash(request_id)
    except TypeError:
        return
    with WAKE:
        queued = next((item for item in QUEUE if item and item[0].get("id") == request_id), None)
        if queued:
            QUEUE.remove(queued)
    if queued:
        CALLS.pop(request_id, None)
        queued[1](error_result(request_id, "the call was cancelled before it started"))
    elif request_id in CALLS:
        CALLS[request_id].set()


def call(name, arguments, request_id=None, token=None):
    """Runs one tool and returns its MCP result, with failures as isError results that say what to do. A client's
    notifications/cancelled for `request_id` stops it; `token` is the client's progressToken, if it sent one."""
    started = time.monotonic()
    recording.RUN.cancel = CALLS.setdefault(request_id, threading.Event()) if request_id is not None else None
    recording.RUN.progress = None if token is None else lambda done, total, message: _send(
        {"jsonrpc": "2.0", "method": "notifications/progress",
         "params": {"progressToken": token, "progress": done, "total": total, "message": message}})
    try:
        if recording.cancelled():
            raise paths.ToolError("the call was cancelled before it started")
        value = registry.TOOLS[name][0](**arguments)
        if not isinstance(value, dict):
            raise RuntimeError(f"{name} returned {type(value).__name__}, not an object")
        text = json.dumps(value, ensure_ascii=False)
        if len(text) > config.MAX_TEXT:
            raise paths.ToolError(f"the result has {len(text)} characters; ask for a smaller page with limit")
        result = {"content": [{"type": "text", "text": text}], "structuredContent": value}
    except TypeError as error:
        result = {"content": [{"type": "text", "text": f"bad arguments: {error}"}], "isError": True}
    except (paths.ToolError, FileNotFoundError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
    except Exception as error:  # an unexpected failure is reported to the client, not fatal to the server
        result = {"content": [{"type": "text", "text": f"internal error: {type(error).__name__}"}], "isError": True}
    CALLS.pop(request_id, None)
    logs.log(f"{name} {'error' if result.get('isError') else 'ok'} in {time.monotonic() - started:.1f} s")
    return result
