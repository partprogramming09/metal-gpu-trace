"""Reviewing screenshots of a run: black, one flat colour, frozen or flickering frames, read with a PNG decoder of the
standard library (8-bit RGB or RGBA, not interlaced) that refuses oversized or lying files."""
import math
import os
import re
import struct
import zlib

from metal_gpu_trace import paths

STEP = 4  # pixels sampled per axis step: the statistics need no full scan
FLAT_SHARE = 0.999  # share of samples within FLAT_SPREAD of the first one that makes a frame flat
FLAT_SPREAD = 4
BLACK_MEAN = 8  # a flat frame whose first sample averages under this is black
THRESHOLD = 32  # a channel differing by more than this makes two pixels different
CHANGED = 0.05  # share of samples that must differ for two frames to count as different
SAME = 0.005  # share of samples at or under which two frames count as the same picture
MAX_FRAMES = 100
MAX_RECTS = 8
MAX_PIXELS = 8_500_000  # a 4K frame; the pure-Python decoder takes seconds per frame at this size
MAX_FILE_BYTES = 64 * 2**20
SIGNATURE = b"\x89PNG\r\n\x1a\n"


def decode(data, name="image"):
    """Returns (width, height, channels, rows) of an 8-bit, non-interlaced RGB or RGBA PNG, `rows` being one bytearray
    per row. Refuses, naming `name`, a file that is not such a PNG, is cut short, fails its checksums, declares more
    than MAX_PIXELS or holds more pixel data than its header says."""
    bad = lambda why: paths.ToolError(f"{name}: {why}")
    if not data.startswith(SIGNATURE):
        raise bad("not a PNG file")
    pos, header, idat, ended = len(SIGNATURE), None, bytearray(), False
    while pos < len(data) and not ended:
        if pos + 12 > len(data):
            raise bad("the PNG is cut short")
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if pos + 12 + length > len(data):
            raise bad("the PNG is cut short")
        body = data[pos + 8:pos + 8 + length]
        if zlib.crc32(kind + body) != struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]:
            raise bad("the PNG fails its checksum")
        if kind == b"IHDR":
            if length != 13:
                raise bad("the PNG header is not 13 bytes")
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            if header is None:
                raise bad("the PNG has image data before its header")
            idat += body
        ended = kind == b"IEND"
        pos += 12 + length
    if header is None or not idat:
        raise bad("the PNG has no header or no image data")
    width, height, depth, color, _, _, interlace = header
    if depth != 8 or interlace or color not in (2, 6):
        raise bad(f"unsupported PNG (bit depth {depth}, colour type {color}, interlace {interlace}); "
                  "only 8-bit RGB or RGBA without interlacing")
    if not width or not height or width * height > MAX_PIXELS:
        raise bad(f"the PNG declares {width} x {height} pixels; at most {MAX_PIXELS} are read")
    channels = 3 if color == 2 else 4
    stride = width * channels
    expected = height * (stride + 1)
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(bytes(idat), expected + 1)
    except zlib.error:
        raise bad("the PNG's image data is corrupt") from None
    if len(raw) != expected or inflater.unconsumed_tail:
        raise bad("the PNG's image data is not the size its header says")
    rows, prev = [], bytearray(stride)
    for y in range(height):
        kind = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if kind > 4:
            raise bad(f"the PNG has an unknown row filter ({kind})")
        unfilter(kind, line, prev, channels)
        rows.append(line)
        prev = line
    return width, height, channels, rows


def unfilter(kind, line, prev, channels):
    """Undoes PNG row filter `kind` on `line` in place, given the row above (`prev`)."""
    if kind == 0:
        return
    if kind == 2:
        line[:] = bytes((x + y) & 255 for x, y in zip(line, prev))
        return
    for i in range(len(line)):
        a = line[i - channels] if i >= channels else 0
        if kind == 1:
            line[i] = (line[i] + a) & 255
            continue
        b, c = prev[i], prev[i - channels] if i >= channels else 0
        if kind == 3:
            line[i] = (line[i] + (a + b) // 2) & 255
        else:
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255


def check_rects(rects):
    """Returns `rects` as a list of (x0, y0, x1, y1) fractions of the width and height, or raises ToolError."""
    if rects is None:
        return []
    ok = isinstance(rects, list) and len(rects) <= MAX_RECTS
    out = []
    for rect in rects if ok else []:
        ok = (isinstance(rect, list) and len(rect) == 4
              and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1
                      for v in rect) and rect[0] < rect[2] and rect[1] < rect[3])
        if not ok:
            break
        out.append(tuple(float(v) for v in rect))
    if not ok:
        raise paths.ToolError(f"ignore_rects is up to {MAX_RECTS} rectangles [x0, y0, x1, y1], fractions from 0 to 1 "
                              "of the picture with x0 < x1 and y0 < y1")
    return out


def sample(frame, rects):
    """Returns the sampled (r, g, b) pixels of a decoded frame, those inside an ignored rectangle left out."""
    width, height, channels, rows = frame
    return [tuple(rows[y][x * channels:x * channels + 3])
            for y in range(0, height, STEP) for x in range(0, width, STEP)
            if not any(x0 * width <= x < x1 * width and y0 * height <= y < y1 * height for x0, y0, x1, y1 in rects)]


def share_different(a, b):
    """Returns the share of sample pairs where any channel differs by more than THRESHOLD."""
    return sum(any(abs(p - q) > THRESHOLD for p, q in zip(x, y)) for x, y in zip(a, b)) / len(a)


def single(pixels):
    """Returns "black", "uniform" or None for one frame's samples."""
    first = pixels[0]
    flat = sum(all(abs(p - q) <= FLAT_SPREAD for p, q in zip(px, first)) for px in pixels) / len(pixels)
    if flat < FLAT_SHARE:
        return None
    return "black" if sum(first) / 3 < BLACK_MEAN else "uniform"


def natural(name):
    """Returns a sort key that puts shot-2 before shot-10."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def read_file(path):
    """Returns the bytes of a regular file of at most MAX_FILE_BYTES, never through a link, or raises ToolError."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        raise paths.ToolError(f"{path.name} cannot be opened (missing, a link or no permission)") from None
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise paths.ToolError(f"{path.name} is over {MAX_FILE_BYTES // 2**20} MiB")
    return data


def files_of(path):
    """Returns the PNG files `path` names (one file, or the PNGs of a folder, not looking into folders below), in
    natural order, or raises ToolError."""
    where = paths.allowed(path)
    if where.is_dir():
        found = sorted((p for p in where.iterdir() if p.suffix.lower() == ".png" and p.is_file() and not p.is_symlink()),
                       key=lambda p: natural(p.name))
        if not found:
            raise paths.ToolError("no PNG files in that folder")
        if len(found) > MAX_FRAMES:
            raise paths.ToolError(f"at most {MAX_FRAMES} screenshots are read at once")
        return found
    if where.suffix.lower() != ".png" or not where.is_file():
        raise paths.ToolError("path is a PNG file or a folder of PNG files in a readable folder")
    return [where]


def tool_screenshots_check(path, sequence=False, ignore_rects=None):
    """Flags screenshots that show nothing useful: black, uniform (one flat colour) and, with `sequence` (the folder's
    PNGs in name order are frames of one run), frozen (3 identical frames in a row) and flicker. `ignore_rects` leaves
    out areas that change alone, such as a clock. Returns {"frames", "ok", "findings": [{"file", "problem"}]}."""
    rects = check_rects(ignore_rects)
    if not isinstance(sequence, bool):
        raise paths.ToolError("sequence is true or false")
    files = files_of(path)
    frames, sizes = [], set()
    for file in files:
        decoded = decode(read_file(file), file.name)
        sizes.add(decoded[:2])
        frames.append(sample(decoded, rects))
    if sequence and len(sizes) > 1:
        raise paths.ToolError("the screenshots of a sequence share one size; these do not")
    findings = []
    for file, pixels in zip(files, frames):
        problem = single(pixels) if pixels else "nothing_to_check"
        if problem:
            findings.append({"file": file.name, "problem": problem})
    if sequence and all(frames) and len(frames) >= 3:
        diffs = [share_different(a, b) for a, b in zip(frames, frames[1:])]
        run = 0
        for i, d in enumerate(diffs):
            run = run + 1 if d <= SAME else 0
            if run == 2:
                findings.append({"file": files[i - 1].name, "problem": "frozen"})
        for i in range(1, len(frames) - 1):
            if diffs[i - 1] > CHANGED and diffs[i] > CHANGED and share_different(frames[i - 1], frames[i + 1]) <= SAME:
                findings.append({"file": files[i].name, "problem": "flicker"})
    return {"frames": len(files), "ok": not findings, "findings": findings}
