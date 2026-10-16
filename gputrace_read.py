"""Reads the command stream of a Metal .gputrace bundle directly, without Xcode, and summarizes it as JSON.

Usage: python3 -I tools/gputrace_read.py <capture.gputrace> [--records]
The `capture` file is "MTSP": a 4-byte magic and a 4-byte word, then records of
[u32 size][i32 call id][...][u32 at +0x20][signature at +0x24, NUL-padded][arguments].
The record layout follows tmc/gputrace (MIT, https://github.com/tmc/gputrace); the 8-byte header, the call ids
and their names below were worked out here against a capture whose command list Xcode showed (macOS 27.0.1).
"""
import argparse
import collections
import json
import pathlib
import re
import struct
import sys

# call id -> (Metal call, certainty): "confirmado" matched one by one against Xcode's command list
CALLS = {
    -16244: ("pushDebugGroup", "confirmado"),
    -16245: ("insertDebugSignpost", "confirmado"),
    -16243: ("popDebugGroup", "confirmado"),
    -16218: ("drawPrimitives", "confirmado"),
    -16279: ("setRenderPipelineState", "confirmado"),
    -16254: ("setDepthStencilState", "confirmado"),
    -16253: ("setStencilReferenceValue", "confirmado"),
    -16264: ("setTriangleFillMode", "confirmado"),
    -16268: ("setCullMode", "confirmado"),
    -16267: ("setDepthClipMode", "confirmado"),
    -16266: ("setDepthBias", "confirmado"),
    -16269: ("setFrontFacingWinding", "confirmado"),
    -16255: ("setBlendColor", "confirmado"),
    -16077: ("setViewports", "confirmado"),
    -16076: ("setScissorRects", "confirmado"),
    -16224: ("setVertexBufferOffset", "confirmado"),
    -15819: ("useResource", "confirmado"),
    -16353: ("renderCommandEncoder", "probable"),
    -16246: ("endEncoding", "probable"),
    -16343: ("commandBuffer", "probable"),
    -10240: ("buffer contents", "probable"),
    -15416: ("drawMeshThreadgroups", "probable"),
    -15415: ("drawMeshThreadgroupsWithIndirectBuffer", "probable"),
    -16327: ("dispatchThreadgroups", "probable"),
}


def records(path):
    """Yields (offset, size, call id, signature, printable strings) for each record of an MTSP file."""
    data = pathlib.Path(path).read_bytes()
    off = 8 if data[:4] == b"MTSP" else 0
    while off + 8 <= len(data):
        size, call = struct.unpack_from("<Ii", data, off)
        if size < 8 or off + size > len(data):
            raise ValueError(f"{path}: record at 0x{off:x} has size {size}; the stream is not MTSP as expected")
        rec = data[off:off + size]
        signature = rec[0x24:].split(b"\0", 1)[0].decode("latin1") if size > 0x24 else ""
        tail = rec[0x24 + len(signature) + 1:]
        strings = [s.decode("latin1") for s in re.findall(rb"[ -~]{3,}", tail)]
        yield off, size, call, signature, strings
        off += size


def summarize(capture):
    """Returns counts of encoders, draws and debug markers, and every call id seen, for a .gputrace bundle."""
    capture = pathlib.Path(capture)
    stream = capture / "capture"
    if not stream.exists():
        raise FileNotFoundError(f"{capture} has no capture file")
    calls, labels = collections.Counter(), collections.defaultdict(list)
    count = 0
    for _, _, call, signature, strings in records(stream):
        calls[(call, signature)] += 1
        count += 1
        if call in (-16244, -16245) and strings:
            labels[CALLS[call][0]].append(strings[0])
    named = lambda call: sum(n for (c, _), n in calls.items() if c == call)
    return {
        "capture": capture.name,
        "records": count,
        "command_buffers": named(-16343),
        "render_encoders": named(-16353),
        # only the drawPrimitives overload seen so far; indexed, mesh and indirect draws have other ids
        "draw_primitives": named(-16218),
        "debug_groups": labels.get("pushDebugGroup", []),
        "signposts": labels.get("insertDebugSignpost", []),
        "pops": named(-16243),
        "calls": [
            {"id": c, "signature": s, "count": n, "name": CALLS.get(c, (None, None))[0], "certainty": CALLS.get(c, (None, None))[1]}
            for (c, s), n in sorted(calls.items(), key=lambda kv: -kv[1])
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture", type=pathlib.Path)
    parser.add_argument("--records", action="store_true", help="print every record instead of the summary")
    args = parser.parse_args()
    if args.records:
        for off, size, call, signature, strings in records(args.capture / "capture"):
            name = CALLS.get(call, ("?", ""))[0]
            print(f"0x{off:06x} {size:5d} {call:7d} {signature:14s} {name:26s} {strings[:3]}")
        return
    json.dump(summarize(args.capture), sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
