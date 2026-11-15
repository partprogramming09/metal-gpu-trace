"""Reads the command stream of a Metal .gputrace bundle directly, without Xcode, and summarizes it as JSON.

Usage: python3 -I src/metal_gpu_trace/gputrace_read.py <capture.gputrace> [--records]
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
            raise ValueError(f"{pathlib.Path(path).parent.name}: record at 0x{off:x} has size {size}; the stream is not MTSP as expected")
        rec = data[off:off + size]
        signature = rec[0x24:].split(b"\0", 1)[0].decode("latin1") if size > 0x24 else ""
        tail = rec[0x24 + len(signature) + 1:]
        strings = [s.decode("latin1") for s in re.findall(rb"[ -~]{3,}", tail)]
        yield off, size, call, signature, strings
        off += size


def stream_of(capture):
    """Returns (bundle path, its `capture` file), or raises FileNotFoundError naming the bundle without its folder."""
    capture = pathlib.Path(capture)
    if not (capture / "capture").exists():
        raise FileNotFoundError(f"{capture.name} has no capture file")
    return capture, capture / "capture"


def summarize(capture):
    """Returns counts of encoders, draws and debug markers, and every call id seen, for a .gputrace bundle."""
    capture, stream = stream_of(capture)
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


def counts(capture):
    """Returns (totals, groups) of a capture: how many times each confirmed call was made, overall and inside each debug
    group (a call counts for the innermost group it is in; groups with the same label add up; a group never popped runs
    to the end). Debug markers (push, pop, signpost) are not counted. A label is the first run of 3 or more printable
    ASCII characters after the call, cut at 200: a shorter or empty one is "(unnamed)", so such groups merge. Calls
    outside every group are only in the totals."""
    _, stream = stream_of(capture)
    totals, groups, open_groups = collections.Counter(), {}, []
    for _, _, call, _, strings in records(stream):
        name, certainty = CALLS.get(call, (None, None))
        if call == -16244:
            label = strings[0][:200] if strings else "(unnamed)"
            open_groups.append(label)
            groups.setdefault(label, collections.Counter())
        elif call == -16243:
            if open_groups:
                open_groups.pop()
        elif certainty == "confirmado" and call != -16245:
            totals[name] += 1
            if open_groups:
                groups[open_groups[-1]][name] += 1
    return totals, groups


def diff(a, b):
    """Compares two .gputrace bundles by the confirmed Metal calls in them: `totals` has {a, b, delta} for each call
    either one makes, and `groups` the debug groups whose calls differ (a group is matched by its label, so their
    order does not matter), each with the counts of only the calls that differ. A capture with no debug group is
    compared as a whole (`aligned_by` is "whole_capture" and `groups` is empty)."""
    (ta, ga), (tb, gb) = counts(a), counts(b)
    names = sorted(set(ta) | set(tb))
    changed = []
    for label in set(ga) | set(gb):
        ca, cb = ga.get(label, collections.Counter()), gb.get(label, collections.Counter())
        differ = [n for n in set(ca) | set(cb) if ca[n] != cb[n]]
        if differ:
            changed.append({"name": label, "a": {n: ca[n] for n in sorted(differ) if ca[n]},
                            "b": {n: cb[n] for n in sorted(differ) if cb[n]}})
    changed.sort(key=lambda g: (-sum(abs(g["b"].get(n, 0) - g["a"].get(n, 0)) for n in set(g["a"]) | set(g["b"])), g["name"]))
    return {"captures": {"a": pathlib.Path(a).name, "b": pathlib.Path(b).name},
            "aligned_by": "debug_group" if ga or gb else "whole_capture",
            "totals": {n: {"a": ta[n], "b": tb[n], "delta": tb[n] - ta[n]} for n in names}, "groups": changed}


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
