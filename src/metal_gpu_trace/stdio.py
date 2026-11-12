"""The stdio transport: newline-delimited JSON-RPC on stdin and stdout."""
import json
import sys
import threading

from metal_gpu_trace import logs, protocol, worker


OUT_LOCK = threading.Lock()


def send(message):
    """Writes one JSON-RPC message to stdout; the lock keeps lines from different threads whole."""
    with OUT_LOCK:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def serve_stdio():
    """Serves newline-delimited JSON-RPC on stdin and stdout until stdin closes."""
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if isinstance(message, dict) and message.get("method") == "notifications/cancelled":
                worker.cancel_call(protocol.request_id_of(message))
                continue
            if isinstance(message, dict) and message.get("method") == "tools/call" and \
                    isinstance(message.get("id"), (str, int)):
                # a tool call runs on the worker thread so ping and notifications/cancelled are read meanwhile; calls
                # still run one at a time, as only one recording may run at once
                worker.CALLS[message["id"]] = threading.Event()
                worker.submit(message, send)
                continue
            reply = protocol.handle(message)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        except Exception as error:  # a malformed request must not stop the server
            logs.log(f"internal error {type(error).__name__}")
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "internal error"}}
        if reply is not None:
            send(reply)
    worker.stop_worker()
