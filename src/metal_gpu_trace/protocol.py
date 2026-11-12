"""JSON-RPC: answers one request, in the old era (initialize first) or the 2026-07-28 era (the version in each request's
_meta). The server's INSTRUCTIONS and version come in through configure()."""
from __future__ import annotations

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
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MODERN_VERSIONS = ("2026-07-28",)
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER = "io.modelcontextprotocol/serverInfo"
MODERN_METHODS = ("server/discover", "tools/list", "tools/call", "resources/list", "resources/read",
                  "resources/templates/list", "prompts/list", "prompts/get")  # no initialize, no ping
CACHE_HOUR_MS = 3600000
CACHED = ("server/discover", "tools/list", "prompts/list", "resources/list", "resources/templates/list")
RUNS_URI = "metal-trace://runs/"


def era(message: dict) -> str:
    """Returns "modern" for a server/discover or a request whose params._meta holds the protocol version or the client
    capabilities, else "legacy". initialize is always legacy."""
    if not isinstance(message, dict) or message.get("method") == "initialize":
        return "legacy"
    if message.get("method") == "server/discover":
        return "modern"
    params = message.get("params")
    meta = params.get("_meta") if isinstance(params, dict) else None
    return "modern" if isinstance(meta, dict) and (META_VERSION in meta or META_CAPABILITIES in meta) else "legacy"


def version_error(mid, requested) -> dict:
    """Returns the -32022 error for a protocol version this server does not speak."""
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32022, "message": "Unsupported protocol version",
                                                   "data": {"supported": list(MODERN_VERSIONS), "requested": requested}}}


def check_modern(message: dict) -> dict | None:
    """Returns the JSON-RPC error for a modern request whose _meta lacks the version or the client capabilities
    (-32602) or names a version this server does not speak (-32022); None when it is fine."""
    mid, params = message.get("id"), message.get("params")
    meta = params.get("_meta") if isinstance(params, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    version = meta.get(META_VERSION)
    if not isinstance(version, str) or not isinstance(meta.get(META_CAPABILITIES), dict):
        return {"jsonrpc": "2.0", "id": mid, "error": {
            "code": -32602, "message": f"_meta must hold {META_VERSION} (a string) and {META_CAPABILITIES} (an object)"}}
    return None if version in MODERN_VERSIONS else version_error(mid, version)


def decorate(result: dict, method: str, era: str, uri: str | None) -> dict:
    """Returns the result of `method` as its era wants it: a modern result says it is complete and names the server,
    and a list, a read or a discover adds how long a client may cache it; a legacy result is returned as it is."""
    if era != "modern":
        return result
    if _version is None:
        raise RuntimeError("protocol.configure() was not called: import metal_gpu_trace.metal_trace_mcp first")
    decorated = {**result, "resultType": "complete",
                 "_meta": {**(result.get("_meta") or {}), META_SERVER: {"name": "metal-trace", "version": _version}}}
    if method in CACHED or (method == "resources/read" and not str(uri).startswith(RUNS_URI)):
        decorated.update(ttlMs=CACHE_HOUR_MS, cacheScope="public")
    elif method == "resources/read":  # a recording's summary can be rewritten
        decorated.update(ttlMs=0, cacheScope="private")
    return decorated


def handle(message):
    """Answers one JSON-RPC request; returns None for notifications."""
    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    method, mid, params = message.get("method"), message.get("id"), message.get("params") or {}
    if "method" not in message and mid is not None and ("result" in message or "error" in message):
        return None  # a response to a request this server never sends
    bad_id = mid if isinstance(mid, (str, int)) else None
    if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return {"jsonrpc": "2.0", "id": bad_id, "error": {"code": -32600, "message": "Invalid Request"}}
    if mid is None:
        return None
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32600, "message": "params must be an object"}}
    kind = era(message)
    if kind == "modern":
        if (error := check_modern(message)) is not None:
            return error
        if method not in MODERN_METHODS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    missing = -32602 if kind == "modern" else -32002  # the 2026-07-28 spec dropped -32002
    if method == "initialize":
        if _version is None:
            raise RuntimeError("protocol.configure() was not called: import metal_gpu_trace.metal_trace_mcp first")
        asked = params.get("protocolVersion")
        result = {"protocolVersion": asked if asked in LEGACY_VERSIONS else LEGACY_VERSIONS[0],
                  "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                  "serverInfo": {"name": "metal-trace", "version": _version}, "instructions": _instructions}
    elif method == "server/discover":
        result = {"supportedVersions": list(MODERN_VERSIONS), "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                  "instructions": _instructions}
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
        if isinstance(uri, str) and uri.startswith(RUNS_URI):
            try:
                text = paths.run_path(uri[len(RUNS_URI):]).read_text(encoding="utf-8")
            except paths.ToolError:
                text = None
            if text is None:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": missing, "message": "Resource not found",
                                                               "data": {"uri": uri}}}
            result = {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        elif uri not in registry.RESOURCES:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": missing, "message": "Resource not found",
                                                           "data": {"uri": uri}}}
        else:
            result = {"contents": [{"uri": uri, "mimeType": "application/json",
                                    "text": json.dumps(registry.RESOURCES[uri][2](), ensure_ascii=False)}]}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "title": hints["title"], "description": inspect.cleandoc(f.__doc__),
                             "inputSchema": s if s.get("properties") else {**s, "additionalProperties": False},
                             "outputSchema": registry.PAGED if n in registry.PAGED_TOOLS else registry.OBJECT, "annotations": hints}
                            | ({"_meta": registry.META[n]} if n in registry.META else {}) for n, (f, s, hints) in registry.TOOLS.items()]}
    elif method == "prompts/list":
        result = {"prompts": [{"name": name, **{k: v for k, v in p.items() if k != "render"}}
                               for name, p in registry.PROMPTS.items()]}
    elif method == "prompts/get":
        if params.get("name") not in registry.PROMPTS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown prompt"}}
        arguments = {k: v for k, v in (params.get("arguments") or {}).items() if v and paths.name_ok(str(v))}
        try:
            text = registry.PROMPTS[params["name"]]["render"](**arguments)
        except TypeError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown prompt argument"}}
        result = {"description": registry.PROMPTS[params["name"]]["description"],
                  "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
    elif method == "tools/call":
        name = params.get("name")
        if name not in registry.TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        result = worker.call(name, params.get("arguments") or {}, mid if isinstance(mid, (str, int)) else None,
                      (params.get("_meta") or {}).get("progressToken"))
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": decorate(result, method, kind, params.get("uri"))}


def finish(message: dict, reply: dict) -> dict:
    """Returns `reply`, a tools/call result the worker built itself (queue full, cancelled), as the era of `message`
    wants it."""
    if era(message) == "modern" and isinstance(reply.get("result"), dict):
        return {**reply, "result": decorate(reply["result"], "tools/call", "modern", None)}
    return reply


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
