"""JSON-RPC: answers one request. The server's INSTRUCTIONS and version come in through configure()."""
import inspect
import json

from metal_gpu_trace import logs, paths, registry, worker


_instructions = None  # set by configure(): the text clients read about how to use the server
_version = None  # set by configure(): the server version


def configure(instructions, version):
    """Sets the INSTRUCTIONS and the version that initialize answers with. They come in from outside because they live
    in metal_trace_mcp, which imports this module."""
    global _instructions, _version
    _instructions, _version = instructions, version


# newest first; initialize answers with the client's version when listed here, else the first
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def handle(message):
    """Answers one JSON-RPC request; returns None for notifications."""
    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    method, mid, params = message.get("method"), message.get("id"), message.get("params") or {}
    if mid is None:
        return None
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32600, "message": "params must be an object"}}
    if method == "initialize":
        if _version is None:
            raise RuntimeError("protocol.configure() was not called: import metal_gpu_trace.metal_trace_mcp first")
        asked = params.get("protocolVersion")
        result = {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                  "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                  "serverInfo": {"name": "metal-trace", "version": _version}, "instructions": _instructions}
    elif method == "ping":
        result = {}
    elif method == "resources/templates/list":
        result = {"resourceTemplates": [{"uriTemplate": "metal-trace://runs/{run}", "name": "Run summary",
                                         "description": "The saved summary of a recording named as perf_runs lists it",
                                         "mimeType": "application/json"}]}
    elif method == "resources/list":
        result = {"resources": [{"uri": uri, "name": name, "description": about, "mimeType": "application/json"}
                                for uri, (name, about, _) in registry.RESOURCES.items()]}
    elif method == "resources/read":
        uri = params.get("uri")
        if isinstance(uri, str) and uri.startswith("metal-trace://runs/"):
            try:
                text = paths.run_path(uri[len("metal-trace://runs/"):]).read_text(encoding="utf-8")
            except paths.ToolError:
                text = None
            if text is None:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32002, "message": "Resource not found",
                                                               "data": {"uri": uri}}}
            return {"jsonrpc": "2.0", "id": mid, "result": {"contents": [{"uri": uri, "mimeType": "application/json",
                                                                         "text": text}]}}
        if uri not in registry.RESOURCES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32002, "message": "Resource not found",
                                                           "data": {"uri": uri}}}
        result = {"contents": [{"uri": uri, "mimeType": "application/json",
                                "text": json.dumps(registry.RESOURCES[uri][2](), ensure_ascii=False)}]}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": inspect.cleandoc(f.__doc__), "inputSchema": s,
                             "outputSchema": registry.PAGED if n in registry.PAGED_TOOLS else registry.OBJECT, "annotations": hints}
                            | ({"_meta": registry.META[n]} if n in registry.META else {}) for n, (f, s, hints) in registry.TOOLS.items()]}
    elif method == "prompts/list":
        result = {"prompts": [{"name": name, **p} for name, p in registry.PROMPTS.items()]}
    elif method == "prompts/get":
        if params.get("name") not in registry.PROMPTS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown prompt"}}
        arguments = {k: v for k, v in (params.get("arguments") or {}).items() if v and paths.name_ok(str(v))}
        try:
            text = registry.prompt_compare_layer(**arguments)
        except TypeError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown prompt argument"}}
        result = {"description": registry.PROMPTS["compare-layer"]["description"],
                  "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    elif method == "tools/call":
        name = params.get("name")
        if name not in registry.TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        result = worker.call(name, params.get("arguments") or {}, mid if isinstance(mid, (str, int)) else None,
                      (params.get("_meta") or {}).get("progressToken"))
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def request_id_of(message):
    """Returns the requestId of a notifications/cancelled message, or None when its params are not an object."""
    params = message.get("params")
    return params.get("requestId") if isinstance(params, dict) else None


def answer(message):
    """Returns the reply to one tools/call."""
    try:
        return handle(message)
    except Exception as error:  # a malformed request must not stop the server
        logs.log(f"internal error {type(error).__name__}")
        worker.CALLS.pop(message.get("id"), None)
        return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": "internal error"}}
