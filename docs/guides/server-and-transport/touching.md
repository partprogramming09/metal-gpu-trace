# Touching it without breaking it

**Reader:** people who add a tool, a method, an HTTP check, a transport or a limit. Reviewed 2026-11-16.

Español: [Tocarlo sin romperlo](../../es/guides/servidor-y-transporte/tocarlo.md) · [Index](./index.md)

**In short:** a short checklist per kind of change. Most changes touch more than one file because tests and the README
count the tools on purpose; the list says which ones.

| To add... | Do this |
|---|---|
| **A new tool** | Write `tool_x(...)` in its domain module, returning a dictionary; its docstring becomes the description the client reads (first line first). Add the row in `registry.TOOLS` with a schema whose properties match the function's parameters, and hints that say whether it writes. A README row (`test_readme_lists_every_tool`), the count 26 in four places (`tests/test_server.py:14`, `:139`, `:325`, `:666`) and `tests/golden/protocol.json` change with it: re-record with `METAL_TRACE_GOLDEN=write python3 -I tests/run.py` and read the diff, as `tests/golden/README.md` says. See [Registry](./registry.md) |
| **A new method in `protocol.handle`** | Decide for each era whether it exists: the modern methods are listed in `MODERN_METHODS` (`protocol.py:28-29`), and `check_headers` refuses an HTTP request for any method not in it. Add it to `tests/golden/protocol.json` through `GOLDEN_MESSAGES` (`tests/test_server.py:496`, `:514`). See [Eras](./eras.md) |
| **A new check on HTTP** | Put it in `do_POST` before the body is read when it is cheap, answer with an **empty** body for a policy refusal and with a JSON-RPC error for a protocol one, and add its test next to the `test_http_*` ones with the `local_http` helper. See [HTTP](./http.md) |
| **Writing from the server** | Never `print` to stdout: it is the protocol. Use `logs.log` for stderr, and never put an argument, a path, a label or a token in the message; today every site writes only a name, a status, a duration or an exception type. See [Logs](./logs.md) |
| **A new transport** | It calls `worker.submit` for a `tools/call` and `protocol.handle` for the rest; it passes its own `send` to `worker.configure` through `metal_trace_mcp.py`; it never runs a tool. It lives in layer 6, so it may import `protocol` and `worker` but nothing above (`tests/test_architecture.py:15-23`). See [Worker](./worker.md) |
| **A new limit** | Put it in `config.py` and read it as `config.NAME` at the place it is used, so a test can patch one attribute (the rule in [How it works](../how-it-works.md#two-rules-that-keep-it-testable); `test_http_timeout` patches `config.HTTP_TIMEOUT` this way) |
| **The text clients read** | `INSTRUCTIONS` changes the reply to `initialize` and to `server/discover`, so `tests/golden/protocol.json` changes too; keep a space after every full stop (`tests/test_server.py:1090`). See [Startup](./startup.md) |
