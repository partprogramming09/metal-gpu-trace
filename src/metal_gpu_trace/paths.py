"""Names and paths the tools accept, and paging: what a caller may read and how it names a run."""
import errno
import json
import os
import pathlib
import secrets

from metal_gpu_trace import config


MALFORMED = (KeyError, TypeError, AttributeError, ValueError, OverflowError, RecursionError)  # what a file of the wrong shape raises
LAYOUT_FILE = "panel.json"  # left by 0.24.0 and older (the removed panel): not a recording; drop this in a later version


class ToolError(Exception):
    """A failure the caller can fix; its message says how."""


def allowed(path, roots=None):
    """Returns `path` resolved, or raises ToolError when it lies outside the readable directories."""
    if not isinstance(path, (str, os.PathLike)) or "\0" in str(path):
        raise ToolError("path is a text path with no null character")
    try:
        resolved = pathlib.Path(path).expanduser().resolve()
    except RuntimeError:
        raise ToolError("path names a home folder that does not exist") from None
    if not any(resolved.is_relative_to(root) for root in roots or config.READ):
        raise ToolError(f"{resolved.name} is outside the readable directories; add its directory to METAL_TRACE_READ")
    return resolved


def name_ok(name, limit=120):
    """Returns whether `name` is a string of at most `limit` bytes of letters, digits, '.', '_' and '-' (the files it
    names add a suffix, and a file name holds 255 bytes). A recording's label takes a lower limit: the run is named
    after it with the date and time added."""
    return (isinstance(name, str) and not name.startswith(".") and 0 < len(name.encode(errors="replace")) <= limit
            and name.replace("-", "").replace("_", "").replace(".", "").isalnum())


def run_path(run):
    """Returns the summary path of a recording named as perf_runs lists it."""
    if not name_ok(run):
        raise ToolError("a run name holds only letters, digits, '.', '_' and '-'; take it from perf_runs")
    path = config.OUT / f"{run}.json"
    if path.name.casefold() in (config.BASELINES.name.casefold(), LAYOUT_FILE) or path.is_symlink() or not path.exists():
        raise ToolError(f"no run {run}; perf_runs lists them")
    return path


def read_text(path):
    """Returns the UTF-8 text of a file in the runs folder, never through a link (opened with O_NOFOLLOW where the
    system has it, and refused first where it does not) and without waiting on a pipe. OSError and UnicodeDecodeError are
    the caller's."""
    if path.is_symlink():
        raise OSError("a link is not read")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "r", encoding="utf-8") as f:
        return f.read()


def read_object(path, what):
    """Returns the JSON object in a file the recorder or the user left in the runs folder, or raises ToolError naming
    `what` (never the path) when it cannot be read, is a link (a runs folder may come from a clone or a download: a
    link could point at any file), is not JSON, is nested too deep or is not an object."""
    try:
        data = json.loads(read_text(path))
    except (ValueError, RecursionError):  # also UnicodeDecodeError
        raise ToolError(f"{what} is not valid JSON; record it again") from None
    except OSError:
        raise ToolError(f"{what} cannot be read") from None
    if not isinstance(data, dict):
        raise ToolError(f"{what} is not a JSON object; record it again")
    return data


def _write_error(path, error):
    """Returns the ToolError for a write that failed, naming the reason (never the path) and the file."""
    reason = {errno.ENOSPC: "the disk is full", errno.EACCES: "permission denied", errno.EROFS: "the folder is read-only",
              errno.EISDIR: "it is a folder", errno.ENOTDIR: "not a folder"}.get(error.errno)
    return ToolError(f"{path.name} cannot be written in the runs folder ({reason or error.strerror or 'the write failed'})")


def write_file(path, text):
    """Writes `text` to `path` (UTF-8) through a unique temporary file beside it, flushed to disk and renamed over it:
    a crash or a full disk leaves the previous file or none, never half a file. Refuses a link instead of writing
    through it: a runs folder may come from a clone or a download."""
    if path.is_symlink():  # refused before the temporary file is made: a runs folder may be a clone
        raise ToolError(f"{path.name} cannot be written in the runs folder (is it a link?)")
    temp = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)  # 0o666 as before: the umask decides
    except OSError as error:  # no write permission, a folder that is not there
        raise _write_error(path, error) from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    except OSError as error:  # the disk filled, the rename was refused
        raise _write_error(path, error) from None
    finally:
        try:
            os.unlink(temp)  # the rename took it: nothing left to remove
        except OSError:
            pass


def trace_path(trace):
    """Returns the .trace of a run named as perf_runs lists it, or `trace` as a path inside the readable
    directories."""
    if name_ok(trace):
        path = config.OUT / f"{trace.removesuffix('.trace')}.trace"
        if path.is_symlink():  # a runs folder may come from a clone or a download
            raise ToolError(f"{path.name} cannot be read")
        return path
    return allowed(trace)


def page(items, offset, limit):
    """Returns one page of `items` with the total and the offset of the next page (None at the end)."""
    offset, limit = max(0, int(offset)), min(max(1, int(limit)), config.MAX_LIMIT)
    rows = items[offset:offset + limit]
    more = offset + len(rows) < len(items)
    return {"total": len(items), "offset": offset, "rows": rows, "next_offset": offset + len(rows) if more else None}


def check_cooldown(value):
    """Returns `value` (the seconds to rest between two recordings) as a number from 0 to 600, 0 when None, or raises
    ToolError."""
    if value is None:
        return 0.0
    try:
        if isinstance(value, bool):
            raise TypeError
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ToolError("cooldown_s is 0 to 600 seconds") from None
    if not 0 <= seconds <= 600:  # a NaN is false here too
        raise ToolError("cooldown_s is 0 to 600 seconds")
    return seconds


def check_skip(skip_s):
    """Returns `skip_s` as a number of seconds from 0 to 600, or raises ToolError."""
    try:
        skip = float(skip_s or 0)
    except (TypeError, ValueError, OverflowError):
        raise ToolError("skip_s is a number of seconds") from None
    if not 0 <= skip <= 600:
        raise ToolError("skip_s is 0 to 600 seconds")
    return skip
