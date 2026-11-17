# ADR-0008: Lift the standard-library-only rule

**Reader:** people

- **Status:** accepted
- **Date:** 2026-11-16
- **Decided by:** the maintainer

## Context
The project began as a way to learn how an MCP server works, so it wrote the protocol, both transports and the JSON-RPC
loop itself and used only the standard library. That reason is gone: the code is published and the rule now costs work
without protecting anyone.

## Decision
- Prefer dependencies that already exist when they save work, saying what each one costs (install size, supply chain, a
  higher Python floor).
- The Python 3.9 floor ([ADR-0003](0003-python-3-9-floor.md)) and `python3 -I` stay. SQLite (`sqlite3`) is part of the
  standard library, so [ADR-0007](0007-sqlite-tables-beside-the-compressed-tables.md) needs nothing new.
- The official `mcp` SDK is not adopted: the project's own transport already passes the conformance tests against it as a
  client, and the SDK would bring `pydantic` and `anyio` and a higher Python floor.

## Alternatives considered
| Option | For | Against | Why yes / no |
|---|---|---|---|
| Lift the rule, keep the floor (chosen) | free to use a library when it saves work; nothing forced | each dependency is a cost to weigh | Yes |
| Keep the rule | no dependencies at all | rewrites what a library does | No |
| Adopt the `mcp` SDK | less protocol code | `pydantic`, `anyio`, a higher floor, a rewrite of a transport that already conforms | No, not now |

## Consequences
- **Positive:** a feature can use a library instead of a copy of it.
- **Negative / cost:** the install is no longer dependency-free once one is added; `CLAUDE.md` says so.

## Revisit when
A dependency is proposed: weigh it against the standard library then.
