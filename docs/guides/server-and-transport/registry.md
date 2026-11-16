# The tool registry

**Reader:** people who add, rename or describe a tool. Reviewed 2026-11-16.

Español: [Registro](../../es/guides/servidor-y-transporte/registro.md) · [Index](./index.md)

**In short:** the registry is the menu of what an agent can ask for: 26 tools, a few read-only data files and three
ready-made prompts. It is plain data, one row per tool, and the same row feeds the list the agent sees, the check of its
arguments and the function that runs. Tests make sure the menu and the README never disagree.

`registry.py` is data: it imports the domain modules (`analysis`, `experiments`, `recording`, `traces`, `workloads`,
`project`) and puts their functions in three tables. It runs nothing.

## Tools

`TOOLS` (`registry.py:69-188`): a name maps to a tuple `(function, schema, hints)`.

| Part | What it is |
|---|---|
| `function` | The domain function, such as `recording.tool_perf_record`. Takes keyword arguments, returns a dictionary |
| `schema` | A JSON Schema object built by `schema(properties, required)` (`:24-26`). The client sees it as `inputSchema`; `worker.check_arguments` checks a call against it |
| `hints` | From `hints(title, destructive, idempotent, open_world)` (`:29-34`); they become the tool's MCP annotations. Default is read-only; `destructive=True` or `False` says the tool writes and whether its writes stop programs |

Today 16 of the 26 tools are read-only and 10 write ([E4](./evidence.md#e4-how-many-tools-how-many-write-which-ask-the-person)); the five that record (`perf_record`, `perf_baseline_record`, `perf_sweep`, `perf_ab`,
`perf_cold_warm`) carry `destructiveHint: true`, because they stop programs.

What `tools/list` builds from a row (`protocol.py:146-150`):

| Field | Rule |
|---|---|
| Description | The function's docstring (`inspect.cleandoc`, so indentation is removed) |
| No properties | The tool gets `additionalProperties: false` |
| Paged output | Three tools (`perf_runs`, `trace_query`, `capture_records`, `PAGED_TOOLS` `:9`) get the paged output schema (`PAGED` `:6-8`) |
| `META` | Adds `anthropic/requiresUserInteraction` to the two tools that download and install things (`workload_fetch`, `presentmon_install`, `registry.py:190-191`), so a client that honours it asks the person before each call (E4) |

## Resources and prompts

- **Resources** (`RESOURCES`, `registry.py:12-15`): one for all the GPU families and one per family in
  `data/apple-gpu-families.json`, read-only JSON: five in the recorded `resources/list` ([E9](./evidence.md#e9-what-the-server-answers-as-the-tests-recorded-it)). The recordings are a resource
  too, but not from this table: `metal-trace://runs/<run>` is a template (`resources/templates/list`) that
  `protocol.handle` serves by reading the summary (`protocol.py:118-145`).
- **Prompts** (`PROMPTS`, `registry.py:193-216`): `compare-layer`, `diagnose-stutter` and `bisect-regression`. Each has a
  `render` function that builds text for the agent; the server runs nothing, and `prompts/list` leaves `render` out
  (`protocol.py:152-153`). `prompts/get` drops every argument whose value is empty or fails `paths.name_ok` before
  calling `render` (`:159`).

## What pins the registry

- `test_tool_schemas_match_signatures` (`tests/test_server.py:1137`): every argument a function takes is in its schema,
  every argument without a default is required, and a schema name the function does not take is allowed only when the
  function forwards `**kwargs`. This matters because `tools/call` refuses names the schema lacks.
- `test_readme_lists_every_tool` (`tests/test_server.py:18`): both READMEs hold a table row for every tool.
- The count 26 appears in four places (`tests/test_server.py:14`, `:139`, `:325`, `:666`), and `tests/golden/protocol.json`
  holds the full `tools/list` reply. Adding a tool changes all of them on purpose ([Touching it](./touching.md)).
