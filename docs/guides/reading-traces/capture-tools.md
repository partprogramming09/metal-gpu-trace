# The capture tools

**Reader:** people who read or compare `.gputrace` captures through the server, or who change `tool_capture_*`. Reviewed 2026-11-16.

> **In short:** three tools read a Metal capture. `capture_summary` counts what is in one (how many draws, which named groups).
> `capture_diff` compares two ("5 draws now, 3 before"), matching groups by name. `capture_records` shows the raw entries, to
> check the other two. None tells how long anything took. Read [the format](./gputrace-format.md) first: ids and trust are there.

## `capture_summary`

`tool_capture_summary(capture)` (`traces.py::tool_trace_query`) resolves the path with `paths.allowed` and calls `gputrace_read.summarize`
(`:72-97`), which reads every record once and returns:

| Key | What it is |
|---|---|
| `capture` | the bundle's name, never its path |
| `records` | how many records the stream has |
| `command_buffers` | records with id -16343 (`commandBuffer`) |
| `render_encoders` | records with id -16353 (`renderCommandEncoder`) |
| `draw_primitives` | records with id -16218; indexed, instanced, indirect and mesh draws have other ids and are **not** counted (`:88-89`), so a scene can show `0` and still draw |
| `debug_groups`, `signposts` | the labels of the `pushDebugGroup` / `insertDebugSignpost` records, in order (first printable string; no cut here) |
| `pops` | how many `popDebugGroup` records |
| `calls` | every distinct `(id, signature)` with `count`, `name` and `certainty`, most frequent first |

The tool adds `calls_total` (distinct pairs; **not** `records`) and keeps the first 100 of `calls` (`traces.py::tool_trace_query`).
`command_buffers` and `render_encoders` come from `probable` ids and the answer does not say so (only `calls` entries carry
`certainty`): read them as probable (F3, [limits](./limits.md)).

## `capture_diff`

`tool_capture_diff(a, b)` (`traces.py::tool_trace_query`) calls `gputrace_read.diff` (`:124-141`), which runs `counts` (`:100-121`) on
each capture, walking the records with a stack of open debug groups:

| Record | Effect | Line |
|---|---|---|
| `pushDebugGroup` | opens a group named by its label: first printable string, **cut at 200 characters**; no string of 3 or more characters is `(unnamed)`, so all such groups merge | `:110-113` |
| `popDebugGroup` | closes the innermost group; a pop with nothing open is ignored | `:114-116` |
| any other record with a **confirmed** name that is not a signpost | adds 1 to the capture's total for that name and to the innermost open group. `probable` ids, unknown ids, signposts and the three markers are **not counted**: a change touching only those shows no difference | `:117-120` |
| groups with the same label | add up; a group never popped runs to the end of the stream (`tests/test_capture.py::test_groups_with_the_same_label_add_up_and_an_unpopped_group_runs_to_the_end`, not run) | `:100-105` |

| `diff` field | Rule | Line |
|---|---|---|
| `captures` | `{"a": <name>, "b": <name>}` | |
| `totals` | `{<call>: {"a": n, "b": n, "delta": b - a}}`: one entry per confirmed call that **either** capture makes, delta 0 included | `:130`, `:141` |
| `groups` | `[{"name": <label>, "a": {<call>: n}, "b": {...}}]`: only groups where **some call differs**, with only the differing calls; a group in one capture only has `{}` on the other side; largest total change first, then by name; the tool keeps 100 and adds `groups_total` | `:132-138`, `traces.py::tool_trace_query` |
| `aligned_by` | `"debug_group"` or `"whole_capture"` (neither capture has a group: `groups` is empty, only `totals` says anything) | `:140` |

Published example (synthetic streams, [proof of 0.26.0](../../evidence/v0.26.0.md#capture_diff-compares-two-captures)):

```text
aligned_by: debug_group
totals: drawPrimitives {a: 3, b: 5, delta: 2}, setRenderPipelineState {a: 1, b: 1, delta: 0}
groups: [{name: main, a: {drawPrimitives: 2}, b: {drawPrimitives: 4}}]
```

`shadow` is absent because it did not change, whatever its order in each capture. The test building this pair is
`tests/test_capture.py::test_diff_of_the_example_in_the_evidence` (not run).

## `capture_records`

`tool_capture_records(capture, offset=0, limit=100)` (`traces.py::tool_trace_query`) returns one page of raw records, each
`{"offset", "size", "id", "signature", "name", "strings"}` with at most 3 strings; `name` is `None` when the id is not in `CALLS`.
It is for checking what the reader sees when a summary looks wrong. The page is cut from **all** the records (`:171-174`), so
each page reads the whole stream again. The default limit is 100 against 50 for `trace_query`; the schema says "default 50"
(`registry.py:19`), wrong for this tool (limit 8). The same reader is a script: `python3 -I src/metal_gpu_trace/gputrace_read.py
<capture.gputrace> [--records]` prints the summary as JSON, or one line per record (`gputrace_read.py:3`, `:144-155`); **not run**.

## What the reader cannot tell you

All of this follows from what the code returns (**confirmed**), not from a real capture:

| Cannot | Why |
|---|---|
| **Time** | The output is names, ids, counts and labels: what was drawn, not how long it took. GPU time comes from a `.trace` and its summary |
| **Resources and shaders** | Arguments are not decoded: buffers, textures and shader code are not in the output, only a record's printable strings |
| **Memory is the file's size** | `records` reads the whole `capture` file into memory (`read_bytes`, `gputrace_read.py::records`) and `diff` reads two. The size of a real `capture` file was never seen; **not measured** |

Back to the [index](./index.md).
