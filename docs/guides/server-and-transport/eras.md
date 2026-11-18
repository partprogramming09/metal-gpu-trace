# The two eras, as a reference

**Reader:** people who touch the transports or the protocol and need to know where the old and the modern MCP behaviour part. Reviewed 2026-11-16.

[Index](./index.md)

**In short:** MCP, the language agents and servers speak, has an older and a newer form ("eras"). This server understands both and tells them apart from the first message. [ADR-0002](../../adr/0002-dual-era-mcp.md) decides; this is a lookup.

| | Old era (`initialize`) | Modern era (2026-07-28) | Where |
|---|---|---|---|
| How the server knows | Everything else, and always `initialize` | `server/discover`, or `params._meta` holds the version or the client capabilities | `protocol.py:40-49` |
| Versions | `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05` | `2026-07-28` | `:23-24` |
| First message | `initialize`: answered with the client's version when listed, else the newest | No handshake; `server/discover` answers the versions, capabilities and `INSTRUCTIONS` | `:107-115` |
| `ping` | Answered `{}` | Not a method: `-32601 unknown method ping` | `:116-117`; `:28-29`, `:104-105` |
| A missing resource | `-32002` | `-32602` | `:106` |
| The result | As is | Adds `resultType: complete`, name and version in `_meta`, and for lists, reads and discover `ttlMs` and `cacheScope` | `:71-83` |
| HTTP headers | `MCP-Protocol-Version` optional, and when sent must be a listed old version | `MCP-Protocol-Version` and `Mcp-Method` required, `Mcp-Name` for three methods | `http_transport.py:58-82` |
| Cancel over HTTP | `notifications/cancelled` by request id | Closing the connection | `http_transport.py:137-159` |

`tests/golden/protocol.json` shows it: the same `resources/read` of a missing run is `-32002` in the old era and `-32602` in the modern one, and `ping` is `-32601` in the modern one ([E9](./evidence.md#e9-what-the-server-answers-as-the-tests-recorded-it)). Why two eras: [How it works](../how-it-works.md#why-it-is-shaped-this-way).
