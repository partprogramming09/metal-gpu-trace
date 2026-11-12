"""The official MCP Python SDK, as an independent client, talks to the server over stdio in both eras, and over
Streamable HTTP (--http) in the 2026-07-28 era.

Needs the SDK, so tests/run.py leaves it out. Run it with:
    uvx --python 3.13 --with mcp==2.3.0 --with pytest pytest -q -p no:cacheprovider tests/conformance
Client API used (mcp 2.3.0): mcp.client.stdio.stdio_client, mcp.ClientSession.discover() for 2026-07-28 and
ClientSession.initialize() for the initialize handshake, mcp.client.streamable_http.streamable_http_client with an
httpx2.AsyncClient that carries the bearer token."""
import os
import pathlib
import secrets
import socket
import subprocess
import sys
import time

import pytest

pytest.importorskip("mcp", reason="needs the official MCP SDK: see the module docstring")
import anyio  # noqa: E402  (installed with mcp)
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402
import httpx2  # noqa: E402  (installed with mcp)

ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVER = ROOT / "src" / "metal_gpu_trace" / "metal_trace_mcp.py"
sys.path.insert(0, str(ROOT / "src"))
from metal_gpu_trace import metal_trace_mcp, registry  # noqa: E402,F401  (metal_trace_mcp configures the registry)


def session_run(tmp_path, handshake):
    """Starts the server, runs `handshake` ("discover" or "initialize"), lists the tools and calls gpu_family."""
    async def main():
        params = StdioServerParameters(command=sys.executable, args=["-I", str(SERVER)],
                                       env={**os.environ, "METAL_TRACE_OUT": str(tmp_path), "METAL_TRACE_LOG": "off"})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await getattr(session, handshake)()
                tools = await session.list_tools()
                result = await session.call_tool("gpu_family", {"name": "M3"})
                return session.protocol_version, [t.name for t in tools.tools], result
    return anyio.run(main)


def test_official_client_modern(tmp_path):
    version, names, result = session_run(tmp_path, "discover")
    assert version == "2026-07-28", version
    assert sorted(names) == sorted(registry.TOOLS), names
    assert not result.is_error, result


def test_official_client_legacy(tmp_path):
    version, names, result = session_run(tmp_path, "initialize")
    assert version == "2025-11-25", version  # the newest initialize version both sides know
    assert sorted(names) == sorted(registry.TOOLS), names
    assert not result.is_error, result


def free_port():
    """Returns a loopback port nothing listens on right now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_official_client_http(tmp_path):
    """The SDK's Streamable HTTP client discovers, lists the tools and calls one over --http, with the bearer token."""
    port, token = free_port(), secrets.token_hex(16)
    server = subprocess.Popen([sys.executable, "-I", str(SERVER), "--http", "--port", str(port)],
                              env={**os.environ, "METAL_TRACE_OUT": str(tmp_path), "METAL_TRACE_LOG": "off",
                                   "METAL_TRACE_TOKEN": token}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                assert time.monotonic() < deadline and server.poll() is None, "the HTTP server did not start"
                time.sleep(0.1)

        async def main():
            async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
                async with streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=http) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.discover()
                        tools = await session.list_tools()
                        result = await session.call_tool("gpu_family", {"name": "M3"})
                        return session.protocol_version, [t.name for t in tools.tools], result
        version, names, result = anyio.run(main)
    finally:
        server.terminate()
        server.wait(timeout=10)
    assert version == "2026-07-28", version
    assert sorted(names) == sorted(registry.TOOLS), names
    assert not result.is_error, result
