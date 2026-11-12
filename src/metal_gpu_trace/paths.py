"""Names and paths the tools accept, and paging: what a caller may read and how it names a run."""
import pathlib

from metal_gpu_trace import config


class ToolError(Exception):
    """A failure the caller can fix; its message says how."""


def allowed(path, roots=None):
    """Returns `path` resolved, or raises ToolError when it lies outside the readable directories."""
    resolved = pathlib.Path(path).expanduser().resolve()
    if not any(resolved.is_relative_to(root) for root in roots or config.READ):
        raise ToolError(f"{resolved.name} is outside the readable directories; add its directory to METAL_TRACE_READ")
    return resolved


def name_ok(name):
    """Returns whether `name` holds only letters, digits, '.', '_' and '-'."""
    return name.replace("-", "").replace("_", "").replace(".", "").isalnum()


def run_path(run):
    """Returns the summary path of a recording named as perf_runs lists it."""
    if not name_ok(run):
        raise ToolError("a run name holds only letters, digits, '.', '_' and '-'; take it from perf_runs")
    path = config.OUT / f"{run}.json"
    if path == config.BASELINES or not path.exists():
        raise ToolError(f"no run {run}; perf_runs lists them")
    return path


def trace_path(trace):
    """Returns the .trace of a run named as perf_runs lists it, or `trace` as a path inside the readable
    directories."""
    if name_ok(trace):
        return config.OUT / f"{trace.removesuffix('.trace')}.trace"
    return allowed(trace)


def page(items, offset, limit):
    """Returns one page of `items` with the total and the offset of the next page (None at the end)."""
    offset, limit = max(0, int(offset)), min(max(1, int(limit)), config.MAX_LIMIT)
    rows = items[offset:offset + limit]
    more = offset + len(rows) < len(items)
    return {"total": len(items), "offset": offset, "rows": rows, "next_offset": offset + len(rows) if more else None}


def check_skip(skip_s):
    """Returns `skip_s` as a number of seconds from 0 to 600, or raises ToolError."""
    try:
        skip = float(skip_s or 0)
    except (TypeError, ValueError):
        raise ToolError("skip_s is a number of seconds") from None
    if not 0 <= skip <= 600:
        raise ToolError("skip_s is 0 to 600 seconds")
    return skip
