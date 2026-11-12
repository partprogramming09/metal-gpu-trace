"""The project file: a metal-gpu-trace.json in a repository names the project and the folder its recordings go to.

The folder is checked before use, because KEEP_RUNS removes the older .json files in it: only a folder that does not
exist, is empty or carries RUNS_MARK (left there when the server adopts it) is accepted."""
import json
import os
import pathlib

from metal_gpu_trace import config, paths

FILE_NAME = "metal-gpu-trace.json"
RUNS_MARK = ".metal-gpu-trace-runs"
PROFILES = ("translation-layer", "native", "generic")
FORMATS = ("metal-gpu-trace",)
KEYS = ("name", "runs", "profile", "baseline", "format")
# files a desktop leaves in a folder on its own: a folder holding only these counts as empty
LITTER = {".DS_Store", "desktop.ini", "Thumbs.db"}


def unique_keys(pairs):
    """Builds a JSON object, refusing a key written twice: the second would silently win."""
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise paths.ToolError(f"{FILE_NAME}: \"{key[:40]}\" is written twice")
        seen[key] = value
    return seen


def load(path, home=None):
    """Reads the project file at `path` and returns {"name", "profile", "baseline", "format", "runs", "root"}, with
    "runs" resolved and "root" the file's folder; raises ToolError naming the field when the file is wrong."""
    path = pathlib.Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)
    except json.JSONDecodeError as error:
        raise paths.ToolError(f"{FILE_NAME} is not valid JSON: {error.msg} at line {error.lineno}, column "
                              f"{error.colno}") from None
    except (OSError, UnicodeDecodeError, RecursionError) as error:
        raise paths.ToolError(f"{FILE_NAME} cannot be read as JSON ({type(error).__name__}); fix it or remove it") from None
    if not isinstance(data, dict):
        raise paths.ToolError(f"{FILE_NAME} must hold one JSON object with \"name\" and \"runs\"")
    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        shown = ", ".join(repr(key[:40]) for key in unknown[:5])
        raise paths.ToolError(f"{FILE_NAME}: unknown key {shown}; the keys are {', '.join(KEYS)}")
    for key in ("name", "runs"):
        if key not in data:
            raise paths.ToolError(f"{FILE_NAME}: \"{key}\" is required")
    name, profile = data["name"], data.get("profile", "generic")
    baseline, fmt = data.get("baseline"), data.get("format", "metal-gpu-trace")
    if not isinstance(name, str) or not paths.name_ok(name):
        raise paths.ToolError(f"{FILE_NAME}: \"name\" holds only letters, digits, '.', '_' and '-'")
    if profile not in PROFILES:
        raise paths.ToolError(f"{FILE_NAME}: \"profile\" is one of {', '.join(PROFILES)}")
    if baseline is not None and (not isinstance(baseline, str) or not paths.name_ok(baseline)):
        raise paths.ToolError(f"{FILE_NAME}: \"baseline\" is a baseline name as perf_baseline saved it")
    if fmt not in FORMATS:
        raise paths.ToolError(f"{FILE_NAME}: \"format\" is one of {', '.join(FORMATS)}; other formats come with their reader")
    root = path.resolve().parent
    return {"name": name, "profile": profile, "baseline": baseline, "format": fmt,
            "runs": runs_folder(data["runs"], root, pathlib.Path(home) if home else pathlib.Path.home()),
            "root": root}


def runs_folder(runs, root, home):
    """Returns the recordings folder `runs` (relative to `root`, or under `home` with ~) resolved, or raises
    ToolError when it is not a folder of its own."""
    if not isinstance(runs, str) or not runs.strip():
        raise paths.ToolError(f"{FILE_NAME}: \"runs\" is the folder of the project's recordings, such as \"perf-runs\"")
    try:
        return checked(runs, root, home)
    except (OSError, RuntimeError, ValueError):  # a link loop (RuntimeError before 3.13), a NUL byte, no permission
        raise paths.ToolError(f"{FILE_NAME}: \"runs\" cannot be used as a folder; name a plain folder") from None


def checked(runs, root, home):
    """runs_folder's checks; the filesystem errors they may raise are runs_folder's to translate."""
    if runs.startswith("~") and runs != "~" and runs[1] not in "/\\":
        raise paths.ToolError(f"{FILE_NAME}: \"runs\" may start with ~/ (the home folder) but not with ~name")
    folder = (home / runs[2:] if runs.startswith("~") else root / runs).resolve()
    home = home.resolve()
    if folder.is_symlink():
        raise paths.ToolError(f"{FILE_NAME}: \"runs\" is a broken or looping link; name a plain folder")
    if folder in (root, home, pathlib.Path(folder.anchor)) or folder in root.parents:
        raise paths.ToolError(f"{FILE_NAME}: \"runs\" must be a folder of its own, not the project's folder, one above it, "
                        "the home folder or the disk's root")
    if not folder.exists():
        return folder
    if not folder.is_dir():
        raise paths.ToolError(f"{FILE_NAME}: \"runs\" names a file; it must be a folder")
    for inside in (FILE_NAME, ".git"):
        if (folder / inside).exists():
            raise paths.ToolError(f"{FILE_NAME}: \"runs\" holds {inside}; give the recordings a folder of their own")
    entries = {p.name for p in folder.iterdir()} - LITTER
    if entries and RUNS_MARK not in entries:
        raise paths.ToolError(f"{FILE_NAME}: \"runs\" names a folder that already holds other files; use a new or empty "
                        f"folder, or put an empty {RUNS_MARK} file in it if it holds only recordings")
    return folder


def find(start, environ):
    """Returns the project file that applies in `start`: the one METAL_TRACE_PROJECT names (a file, or a folder holding
    one), else the nearest one in `start` or a folder above it, below the home folder and the disk's root; None when
    there is none."""
    given = environ.get("METAL_TRACE_PROJECT")
    if given:
        given = pathlib.Path(given).expanduser()
        return given / FILE_NAME if given.is_dir() else given
    home = (pathlib.Path(environ["HOME"]) if environ.get("HOME") else pathlib.Path.home()).resolve()
    start = pathlib.Path(start).resolve()
    for folder in (start, *start.parents):
        # a file in the home folder, above it or at the disk's root would apply to every program
        if folder == home or folder == pathlib.Path(folder.anchor):
            return None
        if (folder / FILE_NAME).is_file():
            return folder / FILE_NAME
    return None


def apply(start=None, environ=None):
    """Points config.OUT, config.READ[0] and config.BASELINES at the folder of the project file that applies in
    `start` (the working directory by default), and adopts that folder (creates it and leaves RUNS_MARK in it).
    Without a project file the settings stay as METAL_TRACE_OUT gives them; a wrong file is kept in
    config.PROJECT_ERROR for check() to report, so the server still starts and says what to fix."""
    environ = os.environ if environ is None else environ
    config.reload(environ)
    config.PROJECT, config.PROJECT_ERROR = None, None
    try:
        path = find(pathlib.Path.cwd() if start is None else start, environ)
        if path is None:
            return
        found = load(path, home=environ.get("HOME"))
        adopt(found["runs"])
    except OSError as error:  # METAL_TRACE_PROJECT names a place that cannot be looked at
        config.PROJECT_ERROR = f"{FILE_NAME} cannot be looked for ({type(error).__name__}); check METAL_TRACE_PROJECT"
        return
    except paths.ToolError as error:
        config.PROJECT_ERROR = str(error)
        return
    runs = found["runs"]
    config.OUT, config.READ, config.BASELINES = runs, [runs] + config.READ[1:], runs / "baselines.json"
    config.PROJECT = found


def adopt(runs):
    """Creates the recordings folder `runs` when it is missing and marks it as the project's own."""
    try:
        runs.mkdir(parents=True, exist_ok=True)
        (runs / RUNS_MARK).touch()
    except OSError as error:
        raise paths.ToolError(f"{FILE_NAME}: the \"runs\" folder cannot be created or marked "
                              f"({type(error).__name__})") from None


def check():
    """Raises ToolError with what is wrong in the project file, when it is wrong."""
    if config.PROJECT_ERROR:
        raise paths.ToolError(config.PROJECT_ERROR)
