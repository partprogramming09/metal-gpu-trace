"""The Streamable HTTP transport on 127.0.0.1: POST /mcp and the panel pages."""
import json
import os
import sys
import threading

from metal_gpu_trace import analysis, config, logs, panel, paths, protocol, worker


def local_host(value):
    """Returns whether a Host or Origin header names this machine's loopback: localhost or 127.0.0.1, with any port."""
    host = (value or "").split("://", 1)[-1].split("/", 1)[0]
    return host.partition(":")[0] in ("localhost", "127.0.0.1")


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
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

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
            length = int(self.headers.get("Content-Length") or 0) if (self.headers.get("Content-Length") or "0").isdigit() else -1
            if not 0 <= length <= config.MAX_BODY:
                return self.reply(413)
            try:
                message = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            if isinstance(message, dict) and message.get("method") == "notifications/cancelled":
                worker.cancel_call(protocol.request_id_of(message))
                return self.reply(202)
            if isinstance(message, dict) and message.get("method") == "tools/call" and \
                    isinstance(message.get("id"), (str, int)):
                # progress goes out as notifications, which this endpoint does not stream: no progressToken
                if isinstance(message.get("params"), dict):
                    message["params"].pop("_meta", None)
                worker.CALLS[message["id"]] = threading.Event()
                done, box = threading.Event(), []
                worker.submit(message, lambda reply: (box.append(reply), done.set()))
                done.wait()
                return self.reply(200, box[0])
            try:
                reply = protocol.handle(message)
            except Exception as error:  # a malformed request must not stop the server
                logs.log(f"internal error {type(error).__name__}")
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "internal error"}}
            self.reply(202 if reply is None else 200, reply)

        def do_GET(self):
            from urllib.parse import parse_qs, urlsplit
            url = urlsplit(self.path)
            if url.path not in ("/panel", "/panel/data"):
                return self.reply(405)
            if self.foreign():
                return self.reply(403)
            if url.path == "/panel":
                # the page holds no data and reads the token from the URL fragment, which never reaches the server
                page_html = panel.panel_html()
                return self.reply(200, page_html.replace("default-src 'none'", "default-src 'none'; connect-src 'self'"),
                                  "text/html; charset=utf-8")
            if self.unauthorized():
                return self.reply(401)
            query = parse_qs(url.query)
            runs = [r for r in (query.get("runs") or [""])[0].split(",") if r]
            skip = (query.get("skip_s") or [0])[0]
            try:
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
