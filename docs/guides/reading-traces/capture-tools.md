# The capture tools

**Reader:** people who read or compare `.gputrace` captures through the server, or who change `tool_capture_*`. Reviewed 2026-11-16.

Español: [Las herramientas de captura](../../es/guides/leer-trazas/herramientas-captura.md)

> **In short:** three tools read a Metal capture. `capture_summary` counts what is in one (how many draws, which named groups).
> `capture_diff` compares two and says what was added or removed, such as "5 draws now, 3 before", matching groups by their
> name. `capture_records` shows the raw entries, to check the other two. None tells how long anything took.

The format and the call ids are in [the `.gputrace` format](./gputrace-format.md); read its first section before trusting
any number here.

## `capture_summary`

`tool_capture_summary(capture)` (`traces.py:151-157`) resolves the path with `paths.allowed` (readable folders only) and calls
`gputrace_read.summarize` (`:72-97`), which reads every record once and returns:

| Key | What it is |
|---|---|
| `capture` | the bundle's name, never its path |
| `records` | how many records the stream has |
| `command_buffers` | records with id -16343 (`commandBuffer`) |
| `render_encoders` | records with id -16353 (`renderCommandEncoder`) |
| `draw_primitives` | records with id -16218; indexed, mesh and indirect draws have other ids and are **not** counted (`:88-89`) |
| `debug_groups` | the labels of the `pushDebugGroup` records, in order (first printable string of each; no cut here) |
| `signposts` | the same for `insertDebugSignpost` |
| `pops` | how many `popDebugGroup` records |
| `calls` | every distinct `(id, signature)` with its `count`, `name` and `certainty`, most frequent first |

The tool adds `calls_total` (how many distinct `(id, signature)` pairs; **not** the number of records, that is `records`) and
keeps only the first 100 of `calls` (`traces.py:155-156`). `command_buffers` and `render_encoders` come from ids the table
calls `probable`, and the answer does not say so next to those two numbers (only the entries of `calls` carry `certainty`):
read them as probable (finding F3, [limits](./limits.md)).

## `capture_diff`

`tool_capture_diff(a, b)` (`traces.py:160-166`) calls `gputrace_read.diff` (`:124-141`), which calls `counts` (`:100-121`) for
each capture. `counts` walks the records with a stack of open debug groups:

| Record | Effect | Line |
|---|---|---|
| `pushDebugGroup` | opens a group named by its label: the first printable string, **cut at 200 characters**; a push with no string of 3 or more characters is `(unnamed)`, so all such groups merge | `:110-113` |
| `popDebugGroup` | closes the innermost group; a pop with nothing open is ignored | `:114-116` |
| any other record whose name is **confirmed** and is not a signpost | adds 1 to the capture's total for that name and to the innermost open group, if any. Records with `probable` ids, unknown ids, signposts and the three debug markers are **not counted** | `:117-120` |
| groups with the same label | add up; a group never popped runs to the end of the stream (pinned by `tests/test_capture.py:156-161`, not run) | `:100-105` |

`diff` returns:

```text
{"captures": {"a": <name>, "b": <name>},
 "aligned_by": "debug_group" | "whole_capture",
 "totals": {<call>: {"a": n, "b": n, "delta": b - a}, ...},
 "groups": [{"name": <label>, "a": {<call>: n, ...}, "b": {<call>: n, ...}}, ...]}
```

| Field | Rule | Line |
|---|---|---|
| `totals` | one entry per confirmed call that **either** capture makes, including those with delta 0 | `:130`, `:141` |
| `groups` | only groups where **some call differs**, with the counts of only the calls that differ; a group in one capture only is listed with `{}` on the other side; sorted by the size of the total change, largest first, then by name; the tool keeps 100 and adds `groups_total` | `:132-138`, `traces.py:164-165` |
| `aligned_by` | `"whole_capture"` when neither capture has a debug group: then `groups` is empty and only `totals` says anything | `:140` |

The published example (synthetic streams, [proof of 0.26.0](../../evidence/v0.26.0.md#capture_diff-compares-two-captures)):

```text
aligned_by: debug_group
totals: drawPrimitives {a: 3, b: 5, delta: 2}, setRenderPipelineState {a: 1, b: 1, delta: 0}
groups: [{name: main, a: {drawPrimitives: 2}, b: {drawPrimitives: 4}}]
```

`shadow` is not listed because it did not change, and it does not matter that it came first in one capture and second in the
other. The test that builds this exact pair is `tests/test_capture.py:146-153` (not run).

## `capture_records`

`tool_capture_records(capture, offset=0, limit=100)` (`traces.py:169-174`) returns one page of the raw records, each as
`{"offset", "size", "id", "signature", "name", "strings"}` with at most the first 3 strings; `name` is `None` when the id is not
in `CALLS`. It is for looking at what the reader sees when a summary looks wrong. The page is built from **all** the records
and then sliced (`:171-174`), so each page reads the whole stream again. The default limit is 100 against 50 for
`trace_query`; the schema's text says "default 50" (`registry.py:19`), which is wrong for this tool (limit 8).

The same reader is also a script: `python3 -I src/metal_gpu_trace/gputrace_read.py <capture.gputrace> [--records]` prints the
summary as JSON, or with `--records` one line per record (`gputrace_read.py:3`, `:144-155`). It was **not run**.

## What the reader cannot tell you

All of these follow from what the code returns (**confirmed**), not from a test of a real capture:

| Cannot | Why |
|---|---|
| **Time** | The output has names, ids, counts and labels: what was drawn, not how long it took. GPU time comes from a `.trace` and its summary |
| **Resources and shaders** | Arguments are not decoded: buffers, textures and shader code are not in the output, only the printable strings of a record |
| **Draws other than the one overload** | A scene drawn with indexed, instanced, indirect or mesh draws can show `draw_primitives: 0` and still have draw calls (their ids are `probable` or absent) |
| **Sure structure counts** | `command_buffers` and `render_encoders` come from the `probable` ids |
| **Changes in unconfirmed calls** | `diff` ignores everything unconfirmed: a change that only touches `probable` or unknown calls shows no difference |
| **Memory is the file's size** | `records` reads the whole `capture` file into memory (`read_bytes`, `gputrace_read.py:50`) and `diff` reads two. The size of a real `capture` file was never seen; **not measured** |

Back to the [index](./index.md).
