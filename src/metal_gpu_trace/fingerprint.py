"""What a run was made with: a short hash of declared files and the names (never the values) of its variables."""
import hashlib
import os
import pathlib

from metal_gpu_trace import paths

MAX_FILES = 32
CHUNK = 1 << 20


def fingerprint_paths(files):
    """Returns [{"name", "sha256", "size"}] for each declared file: its base name, the first 16 hex digits of its
    SHA-256 and its size in bytes. No folder is kept, so the result is safe in a shared summary. Raises ToolError for
    something that is not a list of paths, more than MAX_FILES, a missing file or a folder."""
    if not isinstance(files, (list, tuple)):
        raise paths.ToolError("fingerprint_paths is a list of file paths")
    if len(files) > MAX_FILES:
        raise paths.ToolError(f"fingerprint_paths holds at most {MAX_FILES} files")
    out = []
    for item in files:
        if not isinstance(item, (str, os.PathLike)) or "\0" in str(item):
            raise paths.ToolError("fingerprint_paths holds file paths")
        path = pathlib.Path(item).expanduser()
        if path.is_dir():
            raise paths.ToolError(f"{path.name} is a folder; name the files to fingerprint")
        digest, size = hashlib.sha256(), 0
        try:
            with open(path, "rb") as handle:
                while block := handle.read(CHUNK):
                    digest.update(block)
                    size += len(block)
        except OSError:
            raise paths.ToolError(f"no readable file named {path.name} for fingerprint_paths") from None
        out.append({"name": path.name, "sha256": digest.hexdigest()[:16], "size": size})
    return out


def env_keys(env):
    """Returns the sorted, unique variable names of `env` (NAME=VALUE pairs separated by spaces); values are dropped."""
    return sorted({pair.split("=", 1)[0] for pair in env.split() if "=" in pair})


def compare(a, b):
    """Returns {"same": True}, or {"same": False, "changed": [names]} when the two fingerprints differ (a name whose
    hash changed, or that only one has), or None when either run has none."""
    if not a or not b:
        return None
    left, right = {(f["name"], f["sha256"]) for f in a}, {(f["name"], f["sha256"]) for f in b}
    if left == right:
        return {"same": True}
    return {"same": False, "changed": sorted({name for name, _ in left ^ right})}
