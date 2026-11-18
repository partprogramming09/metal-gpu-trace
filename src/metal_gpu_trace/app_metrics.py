"""The optional telemetry file a recorded program writes: CSV, first column `t_ms`, then named numeric columns. The
recording gives its path in METAL_TRACE_APP_METRICS; read() turns it into the summary's `app_metrics` block."""
import math
import pathlib
import re
import shutil
import tempfile

from metal_gpu_trace import metrics

ENV = "METAL_TRACE_APP_METRICS"
MAX_BYTES = 8 * 2**20  # shortcut: the first 8 MiB only, when a program needs more, raise it or sample less
MAX_COLUMNS = 32
MAX_T_MS = 1e12  # about 31 years: a larger t_ms is a bug in the program, and 1e308 would overflow the duration
NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def path_for(bases=None):
    """Returns a new file path inside a private folder under the first of `bases` (default: the temp folder) whose
    path holds no whitespace (PERF_ENV is split on it), or None."""
    for base in bases or [tempfile.gettempdir()]:
        if not any(c.isspace() for c in str(base)):
            return pathlib.Path(tempfile.mkdtemp(prefix="mtm-app-", dir=base)) / "app_metrics.csv"
    return None


def discard(path):
    """Removes the file and its private folder, if they are there."""
    if path:
        shutil.rmtree(path.parent, ignore_errors=True)


def number(text):
    """Returns the finite float in `text`, or None."""
    try:
        value = float(text) if text.isascii() and "_" not in text else math.nan  # float() takes 1_0 and other scripts' digits
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def read(path):
    """Returns the `app_metrics` block for the file at `path`, or None when it is absent, a link or not a file."""
    if path.is_symlink() or not path.is_file():
        return None
    with open(path, "rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    truncated = len(data) > MAX_BYTES
    text = data[:MAX_BYTES].decode("utf-8-sig", errors="replace")
    if truncated:
        text = text.rsplit("\n", 1)[0]  # the last line may be cut
    # no csv module: a quote must not swallow the rows after it, and a huge cell must not raise
    rows = [line.split(",") for line in text.splitlines() if line.strip()]
    block = {"source": "app-file", "comparable": False,
             "reason": "the names and meaning of the columns belong to the program", "samples": 0}
    if truncated:
        block["truncated"] = True
    if not rows:
        return block
    issues = {}
    header = [cell.strip() for cell in rows[0]]
    if header[0] != "t_ms":
        block["issues"] = {"header": "first column must be t_ms"}
        return block
    keep, ignored = {}, []  # column index -> name
    for index, name in enumerate(header[1:], 1):
        if name in keep.values():
            ignored.append(name)
        elif NAME.fullmatch(name) and len(keep) < MAX_COLUMNS:
            keep[index] = name
    if ignored:
        issues["ignored_columns"] = ignored
    samples, dropped, bad = [], 0, 0
    for row in rows[1:]:
        t = number(row[0]) if len(row) == len(header) else None
        if t is None or abs(t) > MAX_T_MS:
            dropped += 1
            continue
        samples.append((t, row))
    unordered = sum(1 for a, b in zip(samples, samples[1:]) if b[0] < a[0])
    samples.sort(key=lambda item: item[0])
    values = {name: [] for name in keep.values()}
    for _, row in samples:
        for index, name in keep.items():
            value = number(row[index])
            if value is None:
                bad += 1
            else:
                values[name].append(value)
    for key, count in (("dropped_rows", dropped), ("bad_cells", bad), ("out_of_order_rows", unordered)):
        if count:
            issues[key] = count
    block["samples"] = len(samples)
    if samples:
        block["duration_ms"] = round(samples[-1][0] - samples[0][0], 3)
        block["columns"] = {name: dict(metrics.stats(v), min=round(min(v), 3), last=round(v[-1], 3))
                            for name, v in values.items() if v}
    if issues:
        block["issues"] = issues
    return block


def safe_read(path):
    """read(), but a failure to read the file gives None: the program's telemetry never aborts a recording."""
    try:
        return read(path)
    except (OSError, ValueError, MemoryError):
        return None
