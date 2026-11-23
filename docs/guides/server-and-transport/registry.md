# The tool registry

**Reader:** people who add, rename or describe a tool. Reviewed 2026-11-16.

[Index](./index.md)

**In short:** the registry is the menu of what an agent can ask for: 26 tools, a few read-only data files and three ready-made prompts. It is plain data, one row per tool; the same row feeds the list the agent sees, the check of its arguments and the function that runs. Tests keep the menu and the README in agreement.

`registry.py` imports the domain modules (`analysis`, `experiments`, `recording`, `traces`, `workloads`, `project`) and puts their functions in three tables. It runs nothing.

## Tools

`TOOLS` (`registry.py:69-188`): a name maps to `(function, schema, hints)`.

| Part | What it is |
|---|---|
| `function` | The domain function, such as `recording.tool_perf_record`: keyword arguments in, dictionary out |
| `schema` | JSON Schema from `schema(properties, required)` (`:24-26`); the client sees it as `inputSchema`, `worker.check_arguments` checks a call against it |
| `hints` | From `hints(title, destructive, idempotent, open_world)` (`:29-34`), they become MCP annotations. Default read-only; `destructive=True` or `False` says the tool writes and whether its writes stop programs |

16 of the 26 tools are read-only and 10 write ([E4](./evidence.md#e4-how-many-tools-how-many-write-which-ask-the-person)); the five that record (`perf_record`, `perf_baseline_record`, `perf_sweep`, `perf_ab`, `perf_cold_warm`) carry `destructiveHint: true`, because they stop programs.

What `tools/list` builds from a row (`protocol.py::handle`):

| Field | Rule |
|---|---|
| Description | The function's docstring (`inspect.cleandoc`) |
| No properties | `additionalProperties: false` |
| Paged output | `perf_runs`, `trace_query`, `capture_records` (`PAGED_TOOLS` `:9`) get the paged schema (`PAGED` `:6-8`) |
| `META` | Adds `anthropic/requiresUserInteraction` to the two tools that download and install (`workload_fetch`, `presentmon_install`, `registry.py:190-191`), so a client that honours it asks the person each time (E4) |

## Resources and prompts

- **Resources** (`RESOURCES`, `registry.py:12-15`): one for all GPU families and one per family in `data/apple-gpu-families.json`, read-only JSON; five in the recorded `resources/list` ([E9](./evidence.md#e9-what-the-server-answers-as-the-tests-recorded-it)). Recordings are served differently: `metal-trace://runs/<run>` is a template (`resources/templates/list`) that `protocol.handle` serves by reading the summary (`protocol.py::handle`).
- **Prompts** (`PROMPTS`, `registry.py:193-216`): `compare-layer`, `diagnose-stutter`, `bisect-regression`. Each `render` builds text for the agent; the server runs nothing, and `prompts/list` leaves `render` out (`protocol.py::handle`). `prompts/get` drops every argument that is empty or fails `paths.name_ok` before `render` (`:159`).

## What pins the registry

- `test_tool_schemas_match_signatures` (`tests/test_server.py:1137`): every argument a function takes is in its schema, every one without a default is required, and an extra schema name is allowed only when the function forwards `**kwargs` (`tools/call` refuses names the schema lacks).
- `test_readme_lists_every_tool` (`tests/test_server.py::test_readme_lists_every_tool`): both READMEs hold a row per tool.
- The count 26 is in four places (`tests/test_server.py::test_perf_panel_is_gone`, `:139`, `:325`, `:666`) and `tests/golden/protocol.json` holds the full `tools/list`: adding a tool changes all on purpose ([Touching it](./touching.md)).
