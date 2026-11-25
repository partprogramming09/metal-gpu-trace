"""Wine's debug log, summarised: what it says is missing or wrong (`fixme`, `err`, `warn`) by message, and the longest
silence between lines that carry a `+timestamp`. Only normalized messages leave this module, never a raw line."""
import collections
import os
import re

from metal_gpu_trace import paths

# [seconds.millis:][pid:]tid:class:channel:function message (WINEDEBUG=+timestamp,+pid adds the first two)
LINE = re.compile(r"^(?:(\d+\.\d{3}):)?(?:[0-9a-f]{4}:){1,2}(fixme|err|warn|trace):([\w-]+):([\w.:<>-]+)\s*(.*)$")
HRESULT = re.compile(r"\b0x8[0-9a-fA-F]{7}\b")
QUOTED = re.compile(r'L?"(?:[^"\\]|\\.)*"')
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
LEVELS = ("fixme", "err", "warn")
SUFFIXES = {".log", ".txt", ".stderr", ".err", ".out"}
MAX_FILES = 50
MAX_FILE_BYTES = 50 * 2**20
MAX_GROUPS = 5000  # distinct messages kept; the lines past it are still counted by level and channel
MAX_MESSAGE = 160
MAX_LINE = 2000  # a longer line is cut before it is read: quotes with no end would make the scan quadratic
MAX_TOP = 100


def parse(line):
    """Returns (class, channel, message, seconds) of a Wine log line (`seconds` None without +timestamp), or None for any
    other line (a program's own output, a blank, a class Wine does not print)."""
    found = LINE.match(line)
    if not found:
        return None
    stamp, kind, channel, func, rest = found.groups()
    return kind, channel, f"{func} {rest}".strip(), float(stamp) if stamp else None


def normalize(text):
    """Returns `text` with quoted strings, paths, GUIDs, hex values and numbers replaced (`"S"`, `<path>`, N), cut to
    MAX_MESSAGE characters: the same message groups however its numbers change, and no name of a folder, file or person
    that a log line quotes survives."""
    text = QUOTED.sub('"S"', text)
    text = " ".join("<path>" if "/" in word or "\\" in word else word for word in text.split(" "))
    text = GUID.sub("N", text)
    text = re.sub(r"0x[0-9a-fA-F]+", "N", text)
    return re.sub(r"(?<!\w)\d+", "N", text)[:MAX_MESSAGE]


def read_file(path):
    """Returns the text of a regular file of at most MAX_FILE_BYTES, never through a link, or None when it is bigger."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        raise paths.ToolError(f"{path.name} cannot be opened (missing, a link or no permission)") from None
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    return None if len(data) > MAX_FILE_BYTES else data.decode("utf-8", errors="replace")


def files_of(path):
    """Returns the log files `path` names (one file of any name, or the regular files of a folder with a log suffix, not
    looking into folders below or through links), or raises ToolError."""
    where = paths.allowed(path)
    if where.is_dir():
        found = sorted(p for p in where.iterdir() if p.suffix.lower() in SUFFIXES and p.is_file() and not p.is_symlink())
        if not found:
            raise paths.ToolError("no log files in that folder (.log, .txt, .stderr, .err, .out)")
        if len(found) > MAX_FILES:
            raise paths.ToolError(f"at most {MAX_FILES} log files are read at once")
        return found
    if not where.is_file():
        raise paths.ToolError("path is a log file or a folder of log files in a readable folder")
    return [where]


def largest_gap(lines):
    """Returns {"seconds", "before", "after"} for the longest silence between two consecutive stamped lines of one
    file (the normalized messages on each side), or None when fewer than two lines are stamped."""
    best, previous = None, None
    for stamp, message in lines:
        if previous and (best is None or stamp - previous[0] > best[0]):
            best = (stamp - previous[0], previous[1], message)
        previous = (stamp, message)
    return {"seconds": round(best[0], 3), "before": best[1], "after": best[2]} if best else None


def tool_wine_log_census(path, top=15):
    """Counts what a Wine debug log says is missing or wrong, by level, channel and message (numbers, paths and quoted
    text removed so repeats group), plus HRESULTs and the longest silence between +timestamp lines. No raw line leaves."""
    if not isinstance(top, int) or isinstance(top, bool) or not 1 <= top <= MAX_TOP:
        raise paths.ToolError(f"top is a whole number from 1 to {MAX_TOP}")
    files = files_of(path)
    levels, channels, hresults = collections.Counter(), collections.Counter(), collections.Counter()
    groups, truncated, read, skipped, gap = {}, False, 0, 0, None
    for file in files:
        text = read_file(file)
        if text is None:
            skipped += 1
            continue
        read += 1
        stamped = []
        for line in text.splitlines():
            parsed = parse(line[:MAX_LINE])
            if not parsed:
                continue
            kind, channel, message, stamp = parsed
            clean = normalize(message)
            if stamp is not None:
                stamped.append((stamp, f"{channel}:{clean}"))
            if kind not in LEVELS:
                continue
            levels[kind] += 1
            channels[channel] += 1
            hresults.update(HRESULT.findall(message))
            key = (kind, channel, clean)
            if key in groups:
                groups[key] += 1
            elif len(groups) < MAX_GROUPS:
                groups[key] = 1
            else:
                truncated = True
        found = largest_gap(stamped)
        if found and (gap is None or found["seconds"] > gap["seconds"]):
            gap = {**found, "file": file.name}
    ranked = sorted(groups.items(), key=lambda item: (-item[1], item[0]))[:top]
    gap = {"seconds": gap["seconds"], "file": gap["file"], "before": gap["before"], "after": gap["after"]} if gap else None
    return {"lines": sum(levels.values()), "by_level": dict(levels), "by_channel": dict(channels.most_common(10)),
            "top": [{"level": k[0], "channel": k[1], "message": k[2], "count": n} for k, n in ranked],
            "hresults": dict(hresults.most_common(10)), "groups_truncated": truncated,
            "files": {"read": read, "skipped": skipped}, "largest_gap": gap}
