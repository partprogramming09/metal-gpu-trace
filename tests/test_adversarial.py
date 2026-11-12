"""Adversarial tests: public_arguments must leave no folder name of an absolute path in a shared command line and never
raise, and the Streamable HTTP header checks must never raise nor let a modern request through with headers that do
not match its body. Tests that pass are a safety net; the ones at the end reproduce bugs found while attacking.

The runner stops at the first failure, so the reproducers come last."""
import base64
import email.message
import random
import socket

import support  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import http_transport, protocol  # noqa: E402
from metal_gpu_trace.metrics import public_arguments  # noqa: E402

MARK = "ZQXUSER"  # a user name that must never survive public_arguments
SEED = 20261111
MODERN_META = {protocol.META_VERSION: "2026-07-28", protocol.META_CAPABILITIES: {}}


# --- public_arguments: generators -------------------------------------------------------------------------------

def _user(r):
    return r.choice([MARK, f"Ann {MARK}", f"{MARK}.dev", f"{MARK} Lee", f"{MARK}_1", f"{MARK}-x"])


def _path(r, unc=True):
    """An absolute path with MARK as a folder (never as the final name)."""
    user, tail = _user(r), r.choice(["save.dat", "game.exe", "a b.cfg", "x", "inc/y.h"])
    middle = r.choice(["", "My Games/", "Documents/", "a/b/"])
    kind = r.randrange(5 if unc else 4)
    if kind == 0:
        return f"/Users/{user}/{middle}{tail}"
    if kind == 1:
        return f"/home/{user}/{middle}{tail}"
    if kind == 2:
        return "C:\\Users\\" + user + "\\" + (middle + tail).replace("/", "\\")
    if kind == 3:
        return f"D:/Users/{user}/{middle}{tail}"
    return "\\\\server\\" + user + "\\share\\" + (middle + tail).replace("/", "\\")


def _argument(r):
    """A path in one of the forms the docstring promises to cut. A UNC path inside a word is left out here: it is the
    bug test_public_arguments_cuts_unc_path_inside_word reproduces."""
    kind = r.randrange(10)
    path = _path(r, unc=kind < 5 or kind == 8)
    return [path, f'"{path}"', f"'{path}'", f"--save={path}", f'--save="{path}"', f"-I{path}", f"savedir={path}",
            f"cfg:{path}", f'-exec "load {path}"', "file://" + ("" if path.startswith("/") else "/") + path.replace(" ", "%20")][kind]


def _plain(r):
    return r.choice(["-w", "1", "--fast", "-x 2", "--name=Ann", "level1", "-windowed", "+set r 1"])


# --- public_arguments: safety net -------------------------------------------------------------------------------

def test_public_arguments_property_no_user_folder_in_documented_forms():
    """Property (fixed seed, 20 000 lines): a command line made of absolute POSIX, drive and UNC paths in the documented
    forms (bare, quoted, --opt=, --opt="", -I, name=, name:, a quoted value, file:///), with a flag between arguments,
    never keeps the user folder MARK."""
    r = random.Random(SEED)
    for _ in range(20000):
        parts = [r.choice([_argument, _plain])(r) for _ in range(r.randint(1, 5))]
        line = " ".join(p if i == 0 else "-w " + p for i, p in enumerate(parts))  # a plain word after a path joins it
        out = public_arguments(line)
        assert MARK not in out, (line, out)


def test_public_arguments_never_raises():
    """Fuzz (fixed seed, 100 000 inputs): whatever the text (quotes, separators, NUL, lone surrogates, Unicode spaces),
    public_arguments returns a string and raises nothing."""
    r = random.Random(SEED)
    alphabet = list("/\\\"' =:-C:aZ.~@,\t\n\x00\u00a0\u2028\udc80é") + ["C:\\", "\\\\", "--x=", "file://", "//", '"/', "'C:\\"]
    for _ in range(100000):
        text = "".join(r.choice(alphabet) for _ in range(r.randint(0, 30)))
        try:
            out = public_arguments(text)
        except Exception as error:  # noqa: BLE001  (any exception is the failure)
            raise AssertionError(f"public_arguments({text!r}) raised {error!r}") from error
        assert isinstance(out, str), (text, out)


def test_public_arguments_extended_unc_and_nested_quotes():
    """An extended-length path (\\\\?\\C:\\...), a quoted value nested in another quote, a flag value that is itself a
    short flag with a path, and a PATH-like list after `name=` keep no user folder."""
    for line in ("\\\\?\\C:\\Users\\ZQXUSER\\x", """-exec "a '/Users/ZQXUSER/x'" -w""", "--opt=-I/Users/ZQXUSER/x",
                 "x=y:/Users/ZQXUSER/z", "--paths=/a/ZQXUSER/x:/b/ZQXUSER/y", "-o:/Users/ZQXUSER/x"):
        assert MARK not in public_arguments(line), (line, public_arguments(line))


# --- headers: safety net ----------------------------------------------------------------------------------------

_ODD = [None, 0, 1, True, False, 1.5, "x", "", [], [1], {}, {"a": 1}, "2026-07-28", "gpu_family", -0.0, 10 ** 30]


def _message(r):
    meta = {}
    if r.random() < .9:
        meta[protocol.META_VERSION] = r.choice(["2026-07-28"] * 6 + _ODD)
    if r.random() < .9:
        meta[protocol.META_CAPABILITIES] = r.choice([{}] * 6 + _ODD)
    params = {"_meta": r.choice([meta] * 8 + _ODD)}
    for key in ("name", "uri"):
        if r.random() < .6:
            params[key] = r.choice(["gpu_family", "metal-trace://gpu-families"] + _ODD)
    message = {"jsonrpc": "2.0", "id": r.choice([1, "a", 0, True, 1.5, [1], {}, "", None]),
               "method": r.choice(list(protocol.MODERN_METHODS) + ["ping", "initialize", None, 1, ["x"]]),
               "params": r.choice([params] * 8 + _ODD)}
    return r.choice([message] * 9 + _ODD)


def _header(r, value):
    """Mostly the matching value (as text or Base64), sometimes a wrong or malformed one."""
    if r.random() < .6:
        return value if isinstance(value, str) or value is None else str(value)
    if r.random() < .5 and isinstance(value, str):
        return "=?base64?" + base64.b64encode(value.encode()).decode() + "?="
    return r.choice([None, "x", "2026-07-28", "=?base64?!!?=", "=?base64?/w==?=", "=?base64??=", "=?base64?ZéE=?=", "é"])


def test_check_headers_never_raises_and_lets_no_mismatch_through():
    """Fuzz (fixed seed, 100 000 messages with odd types in id, method, params, _meta, name and uri; headers as a dict
    or an email.message.Message): era, check_headers and check_modern raise nothing, and a modern request that
    check_headers lets through has Mcp-Method equal to its method, MCP-Protocol-Version equal to its _meta version, a
    known method and, where the method has one, Mcp-Name equal to params.name or params.uri."""
    r = random.Random(SEED)
    for _ in range(100000):
        message = _message(r)
        params = message.get("params") if isinstance(message, dict) and isinstance(message.get("params"), dict) else {}
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        method = message.get("method") if isinstance(message, dict) else None
        named = http_transport.NAMED.get(method) if isinstance(method, str) else None
        headers = {"MCP-Protocol-Version": _header(r, meta.get(protocol.META_VERSION)),
                   "Mcp-Method": _header(r, method), "Mcp-Name": _header(r, params.get(named) if named else None)}
        headers = {k: v for k, v in headers.items() if v is not None}
        if r.random() < .5:
            mail = email.message.Message()
            for key, value in headers.items():
                mail[key] = value
            headers = mail
        try:
            era = protocol.era(message)
            refused = http_transport.check_headers(headers, message, era)
            if isinstance(message, dict):
                protocol.check_modern(message)
        except Exception as error:  # noqa: BLE001
            raise AssertionError(f"{message!r} {dict(headers)!r} raised {error!r}") from error
        if era == "modern" and refused is None and message.get("id") is not None:
            assert headers.get("Mcp-Method") == method and method in protocol.MODERN_METHODS, (message, dict(headers))
            assert headers.get("MCP-Protocol-Version") == meta.get(protocol.META_VERSION), (message, dict(headers))
            assert named is None or http_transport.header_text(headers.get("Mcp-Name")) == params.get(named), \
                (message, dict(headers))


def test_header_text_malformed_base64():
    """A Base64 Mcp-Name that is not Base64, not UTF-8, holds non-ASCII or is cut decodes to None, never raises; the
    shortest sentinel decodes to the empty name."""
    for value in ("=?base64?!!!?=", "=?base64?/w==?=", "=?base64?ZéE=?=", "=?base64?Zm9?=", "=?base64?Zm9v\r\n ?=",
                  "=?base64?Zm9v=?=", "=?base64? Zm9v?="):
        assert http_transport.header_text(value) is None, value
    assert http_transport.header_text("=?base64??=") == ""
    assert http_transport.header_text("=?base64?") == "=?base64?", "not a sentinel: kept as it is"


def _raw_post(server, head, body=b""):
    """Sends raw bytes to the local server and returns what it wrote back before closing."""
    with socket.create_connection(("127.0.0.1", server.port), timeout=10) as sock:
        sock.sendall(b"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer " + server.token.encode()
                     + b"\r\n" + head + b"Connection: close\r\n\r\n" + body)
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    return data


def test_http_odd_mcp_name_bytes_are_400(tmp_path):
    """End to end: a raw non-ASCII Mcp-Name (not Base64) or a malformed Base64 one is a 400, and no exception reaches
    the handler thread."""
    import json
    from test_server import local_http
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "gpu_family", "arguments": {"name": "M3"}, "_meta": MODERN_META}}).encode()
    with local_http(tmp_path) as server:
        for name in (b"\xc3\xa9", b"=?base64?\xff?=", b"=?base64?Z3B1X2ZhbWlseQ?=", b"\x00"):
            head = (b"MCP-Protocol-Version: 2026-07-28\r\nMcp-Method: tools/call\r\nMcp-Name: " + name
                    + b"\r\nContent-Length: " + str(len(body)).encode() + b"\r\n")
            reply = _raw_post(server, head, body)
            assert reply.split(b"\r\n", 1)[0].endswith(b"400 Bad Request"), (name, reply[:80])
        assert not server.errors, server.errors


# --- reproducers: these fail because of a bug ------------------------------------------------------------------

def test_public_arguments_cuts_unc_path_inside_word():
    """BUG: the docstring promises to cut UNC paths and paths inside a word after a short flag, `name=` or `name:`,
    but a UNC path in those places is kept whole, user folder included (_INNER_PATH looks only for / and C:\\)."""
    for line in ("-I\\\\server\\ZQXUSER\\x", "savedir=\\\\server\\ZQXUSER\\x", "cfg:\\\\server\\ZQXUSER\\x"):
        assert MARK not in public_arguments(line), (line, public_arguments(line))


def test_public_arguments_cuts_quoted_path_glued_to_a_word():
    """BUG: a quoted path glued to a flag or to `name=` (`-I"/x/y"`, `savedir="/x/y"`, `-out:"C:\\x\\y"`, common in
    Windows command lines) is kept whole: the word starts with `-` or a letter, so it is not a path, and _INNER_PATH
    wants the path right after the flag, not after a quote."""
    for line in ('-I"/Users/ZQXUSER/inc"', 'savedir="/Users/ZQXUSER/x"', '-out:"C:\\Users\\ZQXUSER\\x.log"',
                 "-c'/Users/ZQXUSER/x'"):
        assert MARK not in public_arguments(line), (line, public_arguments(line))


def test_public_arguments_cuts_response_file_and_lists():
    """BUG: a path after `@` (a response file), after a comma (`-Wl,-rpath,/x`, `a.dat,/x`) or glued to a long single
    dash flag (`-isystem/x`) is kept whole."""
    for line in ("@/Users/ZQXUSER/args.rsp", "-Wl,-rpath,/Users/ZQXUSER/lib", "--files a.dat,/Users/ZQXUSER/b.dat",
                 "-isystem/Users/ZQXUSER/inc"):
        assert MARK not in public_arguments(line), (line, public_arguments(line))


def test_public_arguments_cuts_unclosed_quote_and_rooted_windows_path():
    """BUG: a path after a quote that never closes (a cut command line) and a Windows path rooted without a drive
    (`\\users\\name\\...`, valid under Wine) are kept whole."""
    for line in ('"/Users/ZQXUSER/x', "\\users\\ZQXUSER\\save.dat", "-w 1 '/home/ZQXUSER/a b"):
        assert MARK not in public_arguments(line), (line, public_arguments(line))


def test_http_content_length_unicode_digit_or_huge_is_answered(tmp_path):
    """BUG: a Content-Length that str.isdigit() accepts but int() refuses (U+00B2 '²', which a Latin-1 header byte
    0xB2 becomes, or more than 4300 digits) raises ValueError in do_POST: the client gets no reply at all and the
    exception reaches the handler thread. It must be answered (413 or 400) like any other bad length."""
    from test_server import local_http
    with local_http(tmp_path) as server:
        for length in (b"\xb2", b"9" * 5000):
            reply = _raw_post(server, b"Content-Length: " + length + b"\r\n")
            assert reply.startswith(b"HTTP/1.0 4"), (length[:5], reply[:80])
        assert not server.errors, server.errors


def test_http_odd_param_types_keep_the_request_id(tmp_path):
    """BUG: prompts/get or resources/read whose name or uri is a list or an object makes protocol.handle raise
    TypeError (unhashable dict key); do_POST answers -32603 with id null, although the request had id 1. JSON-RPC
    wants the request's id back, and these are invalid params (-32602)."""
    from test_server import local_http, http_post
    with local_http(tmp_path) as server:
        for method, params in (("prompts/get", {"name": ["x"]}), ("resources/read", {"uri": {"a": 1}}),
                               ("prompts/get", {"name": "compare-layer", "arguments": [1]})):
            status, reply, _ = http_post(server, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            assert reply["id"] == 1 and reply["error"]["code"] == -32602, (method, params, status, reply)


def test_tools_call_odd_param_types_are_invalid_params():
    """tools/call whose name is not a string is -32602 with the request's id, and a _meta that is not an object is
    read as none instead of failing the call."""
    from metal_gpu_trace import protocol
    from metal_gpu_trace import metal_trace_mcp  # noqa: F401  (configures protocol and worker)
    for name in (["x"], {"a": 1}, 5):
        reply = protocol.answer({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name}})
        assert reply["id"] == 1 and reply["error"]["code"] == -32602, (name, reply)
    reply = protocol.answer({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                             "params": {"name": "gpu_family", "arguments": {"name": "M3"}, "_meta": [1]}})
    assert "result" in reply and not reply["result"].get("isError"), reply


def test_public_arguments_keeps_ordinary_arguments():
    """Ordinary arguments stay as they are, and a multi-letter flag before `:/path` keeps its name: only the path is cut."""
    for line in ("-res:1920x1080", "-DFOO=1", "--level=a,b", "http://host/a", "key:value", "C:", "-o-",
                 "me@mail.com", "\\n", "\\t \\d+", "-w 1"):
        assert public_arguments(line) == line, (line, public_arguments(line))
    assert public_arguments("-out:/Users/ZQXUSER/y.log") == "-out:y.log"
    assert public_arguments("-log:C:\\Users\\ZQXUSER\\y.log") == "-log:y.log"
