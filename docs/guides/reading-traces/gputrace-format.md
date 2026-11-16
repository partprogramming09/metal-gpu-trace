# The `.gputrace` format, as far as the code knows it

**Reader:** people who change `gputrace_read.py` or wonder how much to trust what the capture tools say. Reviewed 2026-11-16.

Español: [El formato `.gputrace`](../../es/guides/leer-trazas/formato-gputrace.md)

> **In short:** a `.gputrace` is the capture Xcode saves of a program's Metal drawing commands. This project reads its main
> file like a list of numbered entries, each entry being one Metal call. It does not decode them fully: it keeps the call
> number and the readable text inside. **Important:** nobody here has examined a real capture, so everything below is what
> the code assumes, not something checked against Xcode.

## Read this first: no real capture was examined

The module's docstring says the 8-byte header, the call ids and their names "were worked out here against a capture whose
command list Xcode showed (macOS 27.0.1)" (`gputrace_read.py:7-8`). But the research of 2026-11-15 that was meant to study the
format records that it was **not done**, because it "needs two real captures made in Xcode" and there was none on that Mac;
and the proof of `capture_diff` (0.26.0) lists as **not tested** "two real captures made by Xcode (none was on this Mac)".
The two statements are not reconciled anywhere in the repository (finding F5, [limits](./limits.md)). So this guide can
only say what the code does and what its tests construct. The record layout follows the public project
[tmc/gputrace](https://github.com/tmc/gputrace) (MIT; the module says so at `gputrace_read.py:6`, and no code is copied,
README "Credits"); **not verified here** against that project's source.

## What the code assumes

Confirmed as assumptions (`gputrace_read.py:1-8`, `:48-69`):

| Element | Assumption | Line |
|---|---|---|
| A `.gputrace` | a **folder** (bundle) saved from Xcode; the reader opens **one file** in it, `capture`; any other file is not read, and what else a real bundle holds was not examined | `:64-69` |
| `capture` | a stream called **MTSP**: the first 4 bytes are ASCII `MTSP`, the next 4 are a word the reader skips (`off = 8`). Without the magic the reader starts at 0 instead of failing | `:51` |
| Records | one after the other; each starts with `[u32 size][i32 call id]`, little-endian (`struct.unpack_from("<Ii", ...)`); `size` is the length of the **whole** record, those 8 bytes included, so the next one starts `size` bytes later | `:53`, `:56`, `:61` |
| Signature | at offset `0x24` (36) of a record: a short ASCII string ended by a zero byte. The synthetic records of the tests use `Cuu` (`tests/test_capture.py:20`). **Speculation:** it names the types of the call's arguments | `:57-58` |
| Arguments | not decoded: the reader takes the **printable ASCII runs of 3 or more characters** after the signature (`re.findall(rb"[ -~]{3,}", tail)`) and calls them `strings`. For a `pushDebugGroup` the first is the **label** the program gave the group: the only argument anything depends on | `:59` |
| A `u32` at `+0x20` | listed in the docstring (`:5`); the code never reads it | `:5` |

```text
 the file:   [MTSP][word][record 1][record 2] ... to the end of the file
             bytes 0-3  4-7   from byte 8, one after the other

 one record: [u32 size][i32 call id][ ... ][signature, NUL][arguments ...]
             the signature starts at offset 0x24 of the record
             size counts the whole record, these 8 bytes included
```

**Bad data.** A record that cannot be parsed stops the whole read. If `size` is under 8, or the record would run past the end
of the file, the reader raises `ValueError`: `<bundle name>: record at 0x<offset> has size <n>; the stream is not MTSP as
expected` (`:54-55`; only the bundle's folder name, never its path; pinned by `tests/test_capture.py:86-97`, not run). Fewer
than 8 bytes left at the end are ignored without a word (`while off + 8 <= len(data)`, `:52`, finding F9).

## The call ids

`CALLS` (`gputrace_read.py:20-45`) maps 24 call ids to a Metal call name and a certainty (17 + 7, E2). Ids are negative
numbers; the code gives no reason for the numbering (**not verified**). The names are Metal's API names:

| Group | Calls | Certainty |
|---|---|---|
| Debug markers (3) | `pushDebugGroup` -16244, `insertDebugSignpost` -16245, `popDebugGroup` -16243 | `confirmado` |
| Drawing (1) | `drawPrimitives` -16218 (one overload only, `:88`) | `confirmado` |
| State a draw depends on (13) | `setRenderPipelineState`, `setDepthStencilState`, `setStencilReferenceValue`, `setTriangleFillMode`, `setCullMode`, `setDepthClipMode`, `setDepthBias`, `setFrontFacingWinding`, `setBlendColor`, `setViewports`, `setScissorRects`, `setVertexBufferOffset`, `useResource` | `confirmado` |
| Structure (3) | `renderCommandEncoder` -16353, `endEncoding` -16246, `commandBuffer` -16343 | `probable` |
| Other (4) | `buffer contents` -10240, `drawMeshThreadgroups` -15416, `drawMeshThreadgroupsWithIndirectBuffer` -15415, `dispatchThreadgroups` -16327 | `probable` |

The two words are Spanish in the code (`"confirmado"`, `"probable"`) and are returned as written in the `certainty` field of
`capture_summary`. `confirmado` means "matched one by one against Xcode's command list" (`:19`); `probable` is a name that
fits but was not matched. A record whose id is not in the table has `name: None`: it is counted, shown by id and signature,
and never named. Whether a real capture uses ids that are not here (indexed, instanced, indirect and mesh draws have their
own, per the comment at `:88`) is **unknown**.

Next: [the capture tools](./capture-tools.md). Back to the [index](./index.md).
