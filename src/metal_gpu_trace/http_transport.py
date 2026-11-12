"""The Streamable HTTP transport on 127.0.0.1: POST /mcp and the panel pages."""
import base64
import json
import os
import re
import select
import socket
import sys
import threading

from metal_gpu_trace import analysis, config, logs, panel, paths, project, protocol, worker

POLL_S = 0.5  # how often a modern POST that waits for its result looks for a client that closed the connection
NAMED = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}  # methods whose Mcp-Name mirrors a param


def local_host(value):
    """Returns whether a Host or Origin header names this machine's loopback: localhost or 127.0.0.1, with any port."""
    host = (value or "").split("://", 1)[-1].split("/", 1)[0]
    return host.partition(":")[0] in ("localhost", "127.0.0.1")


def client_gone(sock):
    """Returns whether the peer of `sock` closed its side: the socket is readable and a peek reads end-of-file."""
    try:
        return bool(select.select([sock], [], [], 0)[0]) and sock.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):  # a reset connection, or a socket that is already closed
        return True


def header_text(value):
    """Returns a header value as text, decoding the =?base64?...?= form the 2026-07-28 spec uses for values that are not
    plain ASCII; None for no header or for Base64 that is not UTF-8."""
    if value is not None and value.startswith("=?base64?") and value.endswith("?=") and len(value) >= 11:
        encoded = value[len("=?base64?"):-2]
        # strict Base64 on every Python: before 3.13 b64decode accepts excess padding such as "Zm9v="
        if len(encoded) % 4 or not re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", encoded):
            return None
        try:
            return base64.b64decode(encoded, validate=True).decode("utf-8")
        except ValueError:  # binascii.Error and UnicodeDecodeError are both ValueErrors
            return None
    return value


def check_headers(headers, message, era):
    """Returns (HTTP status, JSON-RPC error body) for a POST whose headers the spec rejects, or None when they are fine.
    Old era: MCP-Protocol-Version, when sent, is one of protocol.LEGACY_VERSIONS (400). Modern era, for a request: it
    names the _meta version, which is supported (400 -32022), Mcp-Method names the method, which exists (404 -32601),
    and Mcp-Name names params.name or params.uri where the method has one; a missing or different value is 400
    -32020. A notification under a modern version header is let through, with or without _meta: the spec defines no
    header rules for it."""
    mid = message.get("id") if isinstance(message, dict) else None

    def refuse(status, code, text):
        return status, {"jsonrpc": "2.0", "id": mid if isinstance(mid, (str, int)) else None,
                        "error": {"code": code, "message": text}}
    version = headers.get("MCP-Protocol-Version")
    if era == "legacy":
        if mid is None and version in protocol.MODERN_VERSIONS:
            return None  # a modern notification has no _meta (the spec puts it on requests only), so it looks legacy
        if version is not None and version not in protocol.LEGACY_VERSIONS:
            return refuse(400, -32600, f"unsupported MCP-Protocol-Version {version}")
        return None
    if mid is None:
        return None
    method, params = message.get("method"), message.get("params")
    params = params if isinstance(params, dict) else {}  # server/discover is modern even without params
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    if version is None or headers.get("Mcp-Method") is None:
        return refuse(400, -32020, "Header mismatch: MCP-Protocol-Version and Mcp-Method are required")
    if headers.get("Mcp-Method") != method:
        return refuse(400, -32020, "Header mismatch: Mcp-Method does not match the method")
    if version != meta.get(protocol.META_VERSION):
        return refuse(400, -32020, "Header mismatch: MCP-Protocol-Version does not match _meta")
    if version not in protocol.MODERN_VERSIONS:
        return 400, protocol.version_error(mid, version)
    if method not in protocol.MODERN_METHODS:
        return refuse(404, -32601, f"unknown method {method}")
    if method in NAMED and header_text(headers.get("Mcp-Name")) != params.get(NAMED[method]):
        return refuse(400, -32020, f"Header mismatch: Mcp-Name does not match params.{NAMED[method]}")
    return None


def http_handler(token):
    """Returns the request handler class of the Streamable HTTP endpoint POST /mcp: one JSON-RPC message in, one JSON
    reply out (202 for a notification). A request needs the bearer `token`, a loopback Host and no foreign Origin,
    which also stops a web page from reaching the server through DNS rebinding. GET /panel serves the panel page
    (no data) and GET /panel/data?runs=a,b&preset=fps its data, with the same checks; without runs it is the newest."""
    import hmac
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        timeout = config.HTTP_TIMEOUT  # a client that stalls mid-request is dropped, not kept as a thread forever

        def reply(self, code, body=None, kind="application/json"):
            data = b"" if body is None else body.encode() if isinstance(body, str) else json.dumps(body).encode()
            try:
                self.send_response(code)
                if body is not None:  # an empty body (202, 404, 405) has no type
                    self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except ConnectionError:  # BrokenPipeError and ConnectionResetError: the client left during a long call
                self.close_connection = True  # the socket is dead: do not wait for another request on it
                logs.log("client closed the connection")

        def foreign(self):
            """Returns whether the request names a Host or an Origin that is not this machine."""
            return not local_host(self.headers.get("Host")) or bool(self.headers.get("Origin") and
                                                                   not local_host(self.headers.get("Origin")))

        def unauthorized(self):
            """Returns whether the request lacks the bearer token."""
            given = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
            return not hmac.compare_digest(given.encode(), token.encode())

        def do_POST(self):
            if self.path != "/mcp":
                return self.reply(404)
            if self.foreign():
                return self.reply(403)
            if self.unauthorized():
                return self.reply(401)
            text = self.headers.get("Content-Length") or "0"
            # ASCII digits only and a bounded count: "²".isdigit() is true and int() refuses it, as it refuses 5000 digits
            length = int(text) if text.isascii() and text.isdigit() and len(text) <= 12 else -1
            if not 0 <= length <= config.MAX_BODY:
                return self.reply(413)
            try:
                message = json.loads(self.rfile.read(length))
            except (ValueError, RecursionError):  # not JSON, not UTF-8 (UnicodeDecodeError), or nested too deep
                return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            era = protocol.era(message)
            if (failure := check_headers(self.headers, message, era)) is not None:
                return self.reply(*failure)
            if isinstance(message, dict) and message.get("method") == "notifications/cancelled":
                # a modern client cancels by closing its connection; its notification would cancel by id, which
                # another client may share, so it is accepted and ignored
                if self.headers.get("MCP-Protocol-Version") not in protocol.MODERN_VERSIONS:
                    worker.cancel_call(protocol.request_id_of(message))
                return self.reply(202)
            if isinstance(message, dict) and message.get("method") == "tools/call" and \
                    isinstance(message.get("id"), (str, int)):
                # progress goes out as notifications, which this endpoint does not stream: no progressToken. A modern
                # request keeps the rest of its _meta, which holds its version
                if isinstance(message.get("params"), dict):
                    if era == "modern":
                        message["params"]["_meta"].pop("progressToken", None)
                    else:
                        message["params"].pop("_meta", None)
                event = worker.CALLS[message["id"]] = threading.Event()
                done, box = threading.Event(), []
                worker.submit(message, lambda reply: (box.append(reply), done.set()), event)
                if era == "modern":  # closing the connection cancels the request, and nothing is written back
                    while not done.wait(POLL_S):
                        if client_gone(self.connection):
                            worker.cancel_item(message, event)  # by identity: another client may share the id
                            return None
                else:  # the old era has no such signal: it waits for the result, even a cancelled one
                    done.wait()
                return self.reply(200, box[0])
            try:
                reply = protocol.handle(message)
            except Exception as error:  # a malformed request must not stop the server
                logs.log(f"internal error {type(error).__name__}")
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "internal error"}}
            self.reply(202 if reply is None else 200, reply)

        def do_DELETE(self):
            self.reply(405)  # this server has no sessions to end

        def do_GET(self):
            from urllib.parse import parse_qs, urlsplit
            url = urlsplit(self.path)
            if url.path not in ("/panel", "/panel/data"):
                return self.reply(405)
            if self.foreign():
                return self.reply(403)
            if url.path == "/panel":
                # the page holds no data and reads the token from the URL fragment, which never reaches the server
                return self.reply(200, panel.panel_html(True), "text/html; charset=utf-8")
            if self.unauthorized():
                return self.reply(401)
            query = parse_qs(url.query)
            runs = [r for r in (query.get("runs") or [""])[0].split(",") if r]
            skip = (query.get("skip_s") or [0])[0]
            try:
                project.check()
                if not runs:
                    runs = [analysis.tool_perf_runs(0, 1)["rows"][0]["run"]]
                self.reply(200, panel.panel_data(runs, (query.get("preset") or [None])[0], skip))
            except (paths.ToolError, IndexError) as error:
                self.reply(400, {"error": str(error) if isinstance(error, paths.ToolError) else "no recordings yet"})
            except Exception as error:  # a damaged summary must not stop the server
                logs.log(f"internal error {type(error).__name__}")
                self.reply(500, {"error": "internal error"})

        def log_message(self, *args):
            pass

    return Handler


def serve_http(port):
    """Serves the MCP endpoint over HTTP on 127.0.0.1 only, until interrupted. METAL_TRACE_TOKEN (at least MIN_TOKEN
    characters) is the bearer token every request must carry; without it the server refuses to start."""
    from http.server import ThreadingHTTPServer
    token = os.environ.get("METAL_TRACE_TOKEN", "")
    if len(token) < config.MIN_TOKEN:
        print(f"metal-gpu-trace: set METAL_TRACE_TOKEN to a secret of at least {config.MIN_TOKEN} characters", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", port), http_handler(token))
    logs.log(f"serving http://127.0.0.1:{server.server_address[1]}/mcp")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
