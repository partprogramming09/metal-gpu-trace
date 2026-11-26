"""Wine's debug log, summarised: what it says is missing or wrong (`fixme`, `err`, `warn`) by message, and the longest
silence between lines that carry a `+timestamp`. Only normalized messages leave this module, never a raw line."""
import collections
import io
import math
import os
import re
import stat

from metal_gpu_trace import paths

# [seconds.millis:][pid:]tid:class:channel:function message (WINEDEBUG=+timestamp,+pid adds the first two)
LINE = re.compile(r"^(?:(\d+\.\d{3}):)?(?:[0-9a-f]{4}:){1,2}(fixme|err|warn|trace):([\w-]+):([\w.:<>-]+)\s*(.*)$")
HRESULT = re.compile(r"\b0x8[0-9a-fA-F]{7}\b")
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
LEVELS = ("fixme", "err", "warn")
SUFFIXES = {".log", ".txt", ".stderr", ".err", ".out"}
MAX_FILES = 50
MAX_FILE_BYTES = 50 * 2**20
MAX_GROUPS = 5000  # distinct messages kept; the lines past it are still counted by level and channel
MAX_MESSAGE = 160
MAX_LINE = 2000  # a longer line is cut before it is read: quotes with no end would make the scan quadratic
MAX_TOP = 100
MAX_KEYS = 200  # distinct channels and HRESULTs kept; past it they are counted in `other`


def parse(line):
    """Returns (class, channel, message, seconds) of a Wine log line (`seconds` None without +timestamp), or None for any
    other line (a program's own output, a blank, a class Wine does not print)."""
    found = LINE.match(line)
    if not found:
        return None
    stamp, kind, channel, func, rest = found.groups()
    seconds = float(stamp) if stamp else None
    if seconds is not None and not math.isfinite(seconds):
        return None
    return kind, channel, f"{func} {rest}".strip(), seconds


def unquote(text):
    """Returns `text` with each quoted string (an L prefix and backslash escapes allowed) replaced by "S" in one pass; a
    quote that never closes is left as it is. A regex backtracks from every unclosed quote, which made a line of them
    quadratic."""
    out, i, n = [], 0, len(text)
    while i < n:
        start = text.find('"', i)
        if start < 0:
            break
        j = start + 1
        while j < n and text[j] != '"':
            j += 2 if text[j] == "\\" else 1
        if j >= n:
            break
        cut = start - 1 if start > i and text[start - 1] == "L" else start
        out += [text[i:cut], '"S"']
        i = j + 1
    out.append(text[i:])
    return "".join(out)


def _squeeze(words):
    """Returns `words` with each run of `<path>` made one."""
    return [w for i, w in enumerate(words) if w != "<path>" or i == 0 or words[i - 1] != "<path>"]


def normalize(text):
    """Returns `text` with quoted strings, paths, GUIDs, hex values and numbers replaced (`"S"`, `<path>`, N), cut to
    MAX_MESSAGE characters: the same message groups however its numbers change, and no quoted text or path survives (a bare
    file or user name in free text, and a hex address without 0x, can: read the groups before sharing them)."""
    text = unquote(text)
    words, hidden = [], False  # a path may hold spaces ("/Users/Mary Ann"): once one starts, the rest of the line goes
    for word in text.split(" "):
        hidden = hidden or "/" in word or "\\" in word
        words.append(word if not hidden else "<path>")
    text = " ".join(_squeeze(words))
    text = GUID.sub("N", text)
    text = re.sub(r"0x[0-9a-fA-F]+", "N", text)
    return re.sub(r"(?<!\w)\d+", "N", text)[:MAX_MESSAGE]


def read_file(path):
    """Returns the text of a regular file of at most MAX_FILE_BYTES, never through a link, or None when it is bigger."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        raise paths.ToolError(f"{path.name} cannot be opened (missing, a link or no permission)") from None
    try:
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise paths.ToolError(f"{path.name} is not a regular file")
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise paths.ToolError(f"{path.name} cannot be read") from None
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


def tool_wine_log_census(path, top=15):
    """Counts what a Wine debug log says is missing or wrong, by level, channel and message (numbers, paths and quoted
    text removed so repeats group), plus HRESULTs and the longest silence between +timestamp lines. No raw line leaves."""
    if not isinstance(top, int) or isinstance(top, bool) or not 1 <= top <= MAX_TOP:
        raise paths.ToolError(f"top is a whole number from 1 to {MAX_TOP}")
    files = files_of(path)
    levels, channels, hresults = collections.Counter(), collections.Counter(), collections.Counter()
    groups, truncated, read, skipped, gap = {}, False, 0, 0, None
    for index, file in enumerate(files, 1):
        text = read_file(file)
        if text is None:
            skipped += 1
            continue
        read += 1
        previous = None  # (seconds, channel, raw message) of the last stamped line: the only one kept
        for line in io.StringIO(text):
            parsed = parse(line.rstrip("\r\n")[:MAX_LINE])
            if not parsed:
                continue
            kind, channel, message, stamp = parsed
            if stamp is not None:
                delta = stamp - previous[0] if previous else 0
                if delta > 0 and math.isfinite(delta) and (gap is None or delta > gap["seconds"]):
                    gap = {"seconds": delta, "file": index,
                           "before": f"{previous[1]}:{normalize(previous[2])}", "after": f"{channel}:{normalize(message)}"}
                previous = (stamp, channel, message)
            if kind not in LEVELS:
                continue
            clean = normalize(message)
            levels[kind] += 1
            channels[channel if channel in channels or len(channels) < MAX_KEYS else "other"] += 1
            for code in HRESULT.findall(message):
                hresults[code if code in hresults or len(hresults) < MAX_KEYS else "other"] += 1
            key = (kind, channel, clean)
            if key in groups:
                groups[key] += 1
            elif len(groups) < MAX_GROUPS:
                groups[key] = 1
            else:
                truncated = True
    ranked = sorted(groups.items(), key=lambda item: (-item[1], item[0]))[:top]
    gap = {**gap, "seconds": round(gap["seconds"], 3)} if gap else None
    return {"lines": sum(levels.values()), "by_level": dict(levels), "by_channel": dict(channels.most_common(10)),
            "top": [{"level": k[0], "channel": k[1], "message": k[2], "count": n} for k, n in ranked],
            "hresults": dict(hresults.most_common(10)), "groups_truncated": truncated,
            "files": {"read": read, "skipped": skipped}, "largest_gap": gap}
