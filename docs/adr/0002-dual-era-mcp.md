# ADR-0002: Speak both MCP eras, initialize and 2026-07-28

**Reader:** people

- **Status:** accepted
- **Date:** 2026-11-11
- **Decided by:** the maintainer

## Context
MCP 2026-07-28 made the protocol stateless: there is no `initialize`, every request carries its protocol version and
client capabilities in `_meta`, `server/discover` is required, results say `resultType`, `ttlMs` and `cacheScope`, and
`ping` is gone ([basic](https://modelcontextprotocol.io/specification/2026-07-28/basic/index),
[Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)).
Clients in use today still open with `initialize` (2025-11-25 and older), and new clients open with `server/discover`.

## Decision
The server answers both. A request is modern when it is `server/discover` or its `_meta` holds the version or the
client capabilities; anything else, and always `initialize`, is handled the old way. `protocol.py` holds the rule
(`era`, `check_modern`, `decorate`). The official MCP Python SDK checks both eras over stdio and the modern era over
Streamable HTTP in CI (`tests/conformance/`); it is a test dependency only, so the server stays standard library.

## Alternatives considered
| Option | For | Against | Why yes / no |
|---|---|---|---|
| Both eras (chosen) | Old and new clients work | Two code paths in `protocol.py` | Yes: the modern path is one method, one `_meta` check, three result fields and one error code |
| Old era only | No change | New clients cannot connect | No |
| Modern era only | One path | Breaks every client that opens with `initialize` | No, not while those clients are the common case |
| Rewrite on the official SDK | The SDK tracks the spec | Adds dependencies to a tool that installs with nothing but Python | No: the SDK examines the server instead |

## Known deviations
- **Cancellation over HTTP, old era:** `notifications/cancelled` still cancels by request id, so two old-era HTTP
  clients that reuse an id can cancel each other's call. In the modern era closing the connection cancels that exact
  request, and a `notifications/cancelled` under the modern header is ignored.
- **Notifications over HTTP:** a notification POST gets 202 whatever era its headers name. The 2026-07-28 spec defines
  no client notification over Streamable HTTP and leaves their headers undefined.
- **Rate limit:** the worker queue holds at most `MAX_QUEUE` calls; past that a call returns an error result at once.

## Consequences
- **Positive:** every client in use today can connect; a client move to 2026-07-28 needs nothing from the user.
- **Negative / cost:** the replies of both eras are pinned in `tests/golden/protocol.json`, so a change shows twice.
- **Harder:** a later MCP revision has to say which era it extends.

## Revisit when
The common MCP clients no longer send `initialize`: then drop the old era and its error code `-32002`.
