# Touching it without breaking it

**Reader:** people who add a tool, a method, an HTTP check, a transport or a limit. Reviewed 2026-11-16.

Español: [Tocarlo sin romperlo](../../es/guides/servidor-y-transporte/tocarlo.md) · [Index](./index.md)

**In short:** a checklist per kind of change. Most touch several files because tests and the README count the tools on purpose.

| To add... | Do this |
|---|---|
| **A tool** | `tool_x(...)` in its domain module, returning a dictionary; its docstring is the description (first line first). Add the `registry.TOOLS` row with a schema matching the parameters and hints saying whether it writes. Also change: a README row (`test_readme_lists_every_tool`), the count 26 (`tests/test_server.py:14`, `:139`, `:325`, `:666`) and `tests/golden/protocol.json` (re-record with `METAL_TRACE_GOLDEN=write python3 -I tests/run.py`, read the diff, per `tests/golden/README.md`). See [Registry](./registry.md) |
| **A method in `protocol.handle`** | Decide per era whether it exists: modern ones are in `MODERN_METHODS` (`protocol.py:28-29`) and `check_headers` refuses any HTTP method not in it. Add it to `tests/golden/protocol.json` via `GOLDEN_MESSAGES` (`tests/test_server.py:496`, `:514`). See [Eras](./eras.md) |
| **An HTTP check** | In `do_POST` before the body is read when cheap; **empty** body for a policy refusal, JSON-RPC error for a protocol one; test next to the `test_http_*` ones with `local_http`. See [HTTP](./http.md) |
| **Writing from the server** | Never `print` to stdout (it is the protocol). Use `logs.log`, never with an argument, path, label or token: today every site writes a name, status, duration or exception type. See [Logs](./logs.md) |
| **A transport** | Calls `worker.submit` for `tools/call` and `protocol.handle` for the rest, passes its `send` to `worker.configure` through `metal_trace_mcp.py`, never runs a tool. Layer 6: may import `protocol` and `worker`, nothing above (`tests/test_architecture.py:15-23`). See [Worker](./worker.md) |
| **A limit** | In `config.py`, read as `config.NAME` where used so a test patches one attribute ([How it works](../how-it-works.md#two-rules-that-keep-it-testable); `test_http_timeout` patches `config.HTTP_TIMEOUT`) |
| **The text clients read** | `INSTRUCTIONS` changes the reply to `initialize` and `server/discover`, so `tests/golden/protocol.json` changes too; keep a space after every full stop (`tests/test_server.py:1090`). See [Startup](./startup.md) |
