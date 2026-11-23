# The `.gputrace` format, as far as the code knows it

**Reader:** people who change `gputrace_read.py` or wonder how much to trust what the capture tools say. Reviewed 2026-11-16.

> **In short:** a `.gputrace` is the capture Xcode saves of a program's Metal drawing commands. This project reads its main
> file as a list of numbered entries, one Metal call each, keeping the call number and the readable text inside. **Important:**
> nobody here has examined a real capture, so everything below is what the code assumes, not checked against Xcode.

## Read this first: no real capture was examined

The module's docstring says the 8-byte header, the call ids and their names "were worked out here against a capture whose
command list Xcode showed (macOS 27.0.1)" (`gputrace_read.py:7-8`). But the research of 2026-11-15 recorded that the format study
was **not done** ("needs two real captures made in Xcode", none on that Mac), and the 0.26.0 `capture_diff` proof lists as
**not tested** "two real captures made by Xcode (none was on this Mac)". Nothing reconciles them (F5, [limits](./limits.md)), so
this guide says only what the code does and its tests construct. The record layout follows the public project
[tmc/gputrace](https://github.com/tmc/gputrace) (MIT; `gputrace_read.py:6`; no code copied, README "Credits"); **not verified here**.

## What the code assumes

Confirmed as assumptions (`gputrace_read.py:1-8`, `:48-69`):

| Element | Assumption | Line |
|---|---|---|
| A `.gputrace` | a **folder** (bundle) saved from Xcode; the reader opens **one file**, `capture`; what else a real bundle holds was not examined | `gputrace_read.py::stream_of` |
| `capture` | a stream called **MTSP**: 4 bytes of ASCII `MTSP`, then a 4-byte word the reader skips (`off = 8`). Without the magic the reader starts at 0 instead of failing | `gputrace_read.py::records` |
| Records | one after the other, each `[u32 size][i32 call id]`, little-endian (`struct.unpack_from("<Ii", ...)`); `size` is the **whole** record, those 8 bytes included, so the next starts `size` bytes later | `gputrace_read.py::records` |
| Signature | at offset `0x24` (36) of a record: a short ASCII string ended by a zero byte (`Cuu` in the tests, `tests/test_capture.py::record`). **Speculation:** it names the argument types | `gputrace_read.py::records` |
| Arguments | not decoded: the **printable ASCII runs of 3 or more characters** after the signature (`re.findall(rb"[ -~]{3,}", tail)`) are `strings`. In a `pushDebugGroup` the first is the **label** the program gave the group: the only argument anything depends on | `gputrace_read.py::records` |
| A `u32` at `+0x20` | listed in the docstring; the code never reads it | `:5` |

**Bad data.** A record that cannot be parsed stops the read: if `size` is under 8 or the record runs past the end, `ValueError`:
`<bundle name>: record at 0x<offset> has size <n>; the stream is not MTSP as expected` (`gputrace_read.py::records`; bundle name only, never its
path; `tests/test_capture.py::test_malformed_record_raises_valueerror`, not run). Fewer than 8 bytes left at the end are ignored silently
(`while off + 8 <= len(data)`, `gputrace_read.py::records`, F9).

## The call ids

`CALLS` (`gputrace_read.py::CALLS`) maps 24 ids to a Metal call name and a certainty (17 + 7, E2). Ids are negative; the code
gives no reason for the numbering (**not verified**). Names are Metal's API names:

| Group | Calls | Certainty |
|---|---|---|
| Debug markers (3) | `pushDebugGroup` -16244, `insertDebugSignpost` -16245, `popDebugGroup` -16243 | `confirmado` |
| Drawing (1) | `drawPrimitives` -16218 (one overload only, `gputrace_read.py::summarize`) | `confirmado` |
| State a draw depends on (13) | `setRenderPipelineState`, `setDepthStencilState`, `setStencilReferenceValue`, `setTriangleFillMode`, `setCullMode`, `setDepthClipMode`, `setDepthBias`, `setFrontFacingWinding`, `setBlendColor`, `setViewports`, `setScissorRects`, `setVertexBufferOffset`, `useResource` | `confirmado` |
| Structure (3) | `renderCommandEncoder` -16353, `endEncoding` -16246, `commandBuffer` -16343 | `probable` |
| Other (4) | `buffer contents` -10240, `drawMeshThreadgroups` -15416, `drawMeshThreadgroupsWithIndirectBuffer` -15415, `dispatchThreadgroups` -16327 | `probable` |

The two words are Spanish in the code and returned as written in the `certainty` field of `capture_summary`. `confirmado` means
"matched one by one against Xcode's command list" (`gputrace_read.py::CALLS`); `probable` fits but was not matched. A record whose id is not in the
table has `name: None`: counted, shown by id and signature, never named. Whether a real capture uses ids not here (indexed,
instanced, indirect and mesh draws have their own, per `gputrace_read.py::summarize`) is **unknown**.

Next: [the capture tools](./capture-tools.md). Back to the [index](./index.md).
