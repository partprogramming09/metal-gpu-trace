"""Settings the other modules read at the moment they use them (always as config.NAME, never copied):
where recordings go, what may be read, the data files and the limits."""
import json
import os
import pathlib
import sys


PACKAGE_DIR = pathlib.Path(__file__).resolve().parent

def reload(environ=None):
    """Reads METAL_TRACE_OUT and METAL_TRACE_READ again (from `environ`, os.environ by default) and recomputes OUT,
    READ and BASELINES. project.apply then points them at the project's folder, when there is a project file."""
    global OUT, READ, BASELINES
    environ = os.environ if environ is None else environ
    OUT = pathlib.Path(environ.get("METAL_TRACE_OUT", "perf-runs")).resolve()
    READ = [OUT] + [pathlib.Path(p).resolve() for p in environ.get("METAL_TRACE_READ", "").split(os.pathsep) if p]
    # named references for perf_check: copies of their runs' summaries, so KEEP_RUNS deleting a run does not break them
    BASELINES = OUT / "baselines.json"


reload()
# the metal-gpu-trace.json in use (project.load's dict) and, when that file is wrong, what is wrong with it
PROJECT = None
PROJECT_ERROR = None
FAMILIES = json.loads((PACKAGE_DIR / "data" / "apple-gpu-families.json").read_text(encoding="utf-8"))
WORKLOADS = json.loads((PACKAGE_DIR / "data" / "workloads.json").read_text(encoding="utf-8"))["workloads"]
if sys.platform == "win32":
    CACHE = pathlib.Path(os.environ.get("LOCALAPPDATA", "~/.cache")).expanduser() / "metal-gpu-trace"
else:
    CACHE = pathlib.Path("~/Library/Caches/metal-gpu-trace").expanduser()
# one recording at a time whatever folder it goes to (each project has its own): the lock every recording takes
LOCK = pathlib.Path(os.environ.get("METAL_TRACE_LOCK") or CACHE / "recording.lock").expanduser().resolve()
MAX_LIMIT = 500
# results stay under Claude Code's 50 000-character limit, above which it saves them to a file
MAX_TEXT = 40_000


PROGRESS_TICKS = 5  # seconds between progress notifications while a recording runs


MEMORY_PRESSURE = ["memory_pressure"]
PANEL_POINTS = 5000
MAX_QUEUE = 64


MIN_TOKEN = 16
MAX_BODY = 1_000_000
HTTP_TIMEOUT = 15  # seconds a client may take to send its request
