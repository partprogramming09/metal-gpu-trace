"""Keeping the runs folder under a size limit (METAL_TRACE_MAX_DISK_MB): removes the heavy files of old recordings."""
import os
import shutil
import stat

# what may go, lightest loss first: the raw .trace, then an exported Chrome trace (perf_export_trace rebuilds it from the
# per-frame table), then the tables file (only trace_query reads it), then the per-frame and memory tables (perf_compare
# with skip_s and perf_export_trace need them); summaries (.json), baselines.json, panel.json and the .rss.csv / .agx.csv
# samplers are never removed
TRACE, CHROME, TABLES_DB, TABLE = 0, 1, 2, 3
CURRENT_TRACE = 4  # the run just recorded keeps its .trace until nothing else is left to remove
TABLES_DB_SUFFIX = ".tables.sqlite"
TABLE_SUFFIXES = (".frames.csv", ".frames.csv.gz", ".metal_memory.csv", ".metal_memory.csv.gz")


def size_of(path):
    """Returns the bytes a file or folder takes, counting a link as a file of its own size and never following one."""
    try:
        info = os.lstat(path)
    except OSError:
        return 0
    total = info.st_size
    if stat.S_ISDIR(info.st_mode):
        for root, dirs, files in os.walk(path, followlinks=False):
            for name in dirs + files:
                try:
                    total += os.lstat(os.path.join(root, name)).st_size
                except OSError:
                    pass
    return total


def kind_of(name, current):
    """Returns what a top-level name in the runs folder is for pruning (TRACE, CHROME, TABLES_DB, TABLE, CURRENT_TRACE), or None
    when it must stay."""
    if name == current + ".trace":
        return CURRENT_TRACE
    if name == current + ".chrome-trace" or name in (current + s for s in (*TABLE_SUFFIXES, TABLES_DB_SUFFIX, TABLES_DB_SUFFIX + ".part")):
        return None  # the current run's tables and export stay
    if name.endswith(".trace"):
        return TRACE
    if name.endswith(".chrome-trace"):
        return CHROME
    if name.endswith((TABLES_DB_SUFFIX, TABLES_DB_SUFFIX + ".part")):  # a .part left by a killed recording
        return TABLES_DB
    if name.endswith(TABLE_SUFFIXES):
        return TABLE
    return None


def prune_to_quota(out, max_mb, current):
    """Removes files from the runs folder `out`, oldest first within each kind (see `kind_of`), until the folder takes at
    most `max_mb` MiB; `current` is the run just recorded. Returns {"freed_mb", "removed", "trace_dropped"}, the last true
    only when the current run's own .trace had to go; a folder that already fits is not touched."""
    limit = max_mb * 2**20
    entries = []
    for entry in os.scandir(out):
        try:
            mtime = entry.stat(follow_symlinks=False).st_mtime
        except OSError:
            continue
        entries.append((entry.name, mtime, size_of(entry.path)))
    total = sum(size for _, _, size in entries)
    result = {"freed_mb": 0.0, "removed": 0, "trace_dropped": False}
    if total <= limit:
        return result
    candidates = sorted((kind_of(name, current), mtime, name, size) for name, mtime, size in entries
                        if kind_of(name, current) is not None)
    freed = 0
    for kind, _, name, size in candidates:
        if total - freed <= limit:
            break
        path = os.path.join(out, name)
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)  # a child that vanishes meanwhile is no reason to stop
                if os.path.lexists(path):
                    continue
            else:
                os.unlink(path)  # a link is removed itself, never what it points at
        except OSError:
            continue
        freed += size
        result["removed"] += 1
        result["trace_dropped"] |= kind == CURRENT_TRACE
    result["freed_mb"] = round(freed / 2**20, 2)
    return result
