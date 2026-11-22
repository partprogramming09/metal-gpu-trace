"""What a recording needs, checked in milliseconds before any process starts: the program, the tools, the disk, the screen
and the recording lock. perf_record.sh repeats the program, disk and lock checks (defence in depth); the screen is only
checked here. `environment_report` says each of them, ok or missing with the exact fix, for the early refusal, `init`
and `doctor`."""
import os
import pathlib
import shutil
import stat
import subprocess
import sys

from metal_gpu_trace import config, paths, perf_report

WINE_MISSING = "no Wine at bin/wine inside that Wine directory (pass native for a macOS program)"
# the Command Line Tools give xcrun but not xctrace: `xcode-select --install` alone does not fix a missing xctrace
XTRACE_MISSING = ("xctrace is missing: install Xcode from the App Store, open it once and point xcode-select at it "
                  "(`sudo xcode-select --switch /Applications/Xcode.app`; the Command Line Tools alone do not bring "
                  "xctrace); `xcrun xctrace version` should then print a version")
PRESENTMON_MISSING = ("PresentMon is not installed: run the presentmon_install tool (Windows only), or install PresentMon "
                      "and put it on PATH; without it the recording falls back to the desktop compositor's frame times")
PERMISSIONS_MISSING = ("not elevated: PresentMon needs administrator rights or membership of the Performance Log Users "
                       "group; if your user is in that group, ignore this note")
SCREEN_LOCKED = ("the screen is locked: a locked session leaves the program's frames unpaced by the display, "
                 "so the numbers do not compare; unlock the Mac, or set METAL_TRACE_ALLOW_LOCKED=1 to record anyway")
LOCK_RUNNING = ("another recording is running; one runs at a time. If none is, remove the lock folder "
                "(METAL_TRACE_LOCK names it)")


def process_alive(pid):
    """Returns True when process `pid` exists: a signal 0 (on Windows, where it is CTRL_C_EVENT, OpenProcess asks
    instead); a process of another user, which refuses the signal, is alive."""
    if not isinstance(pid, int) or isinstance(pid, bool) or not 1 <= pid < 2**31:  # signal 0 to pid 0 or -1 reaches a whole process group
        return False
    if sys.platform == "win32":
        from metal_gpu_trace import perf_record_windows
        return perf_record_windows.is_process_alive(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def whole_seconds(seconds):
    """Returns `seconds` as an int when it is one (a float with no fraction, or plain digits), else None: nothing is
    truncated or read in a form int() accepts but the shell script would not ("1_0", 10.5)."""
    if isinstance(seconds, bool):
        return None
    if isinstance(seconds, int):
        return seconds
    if isinstance(seconds, float) and seconds.is_integer():
        return int(seconds)
    if isinstance(seconds, str) and seconds.isascii() and seconds.strip().isdigit():
        return int(seconds)
    return None


def disk_needed(seconds, environ, windows=False):
    """Returns the GB perf_record.sh asks for: PERF_MIN_FREE_GB, else 2 plus 0.8 GB per recorded second (Instruments'
    temporary files); under Windows, with no Instruments, 1."""
    given = (environ.get("PERF_MIN_FREE_GB") or "").strip()
    if given.isascii() and given.isdigit():
        return int(given)
    return 1 if windows else 2 + (int(seconds) * 8 + 9) // 10


def executable(path):
    """Returns True when `path` is a file the user may run (a name with a null byte is not one)."""
    try:
        return os.access(path, os.X_OK)
    except (ValueError, OSError):
        return False


def free_gb(directory):
    """Returns the whole GB free where `directory` is (or would be: the nearest folder that exists)."""
    try:
        if "\x00" in str(directory):
            raise ValueError
        path = pathlib.Path(directory)
        while not path.exists() and path != path.parent:
            path = path.parent
        return shutil.disk_usage(path).free // 2**30
    except (ValueError, OSError):
        raise paths.ToolError("the free disk space cannot be read for the runs or the temporary folder") from None


def wine_problem(wine):
    """Returns the refusal text when `wine` is a directory without an executable bin/wine, else None: native and attach
    need no Wine."""
    if wine in ("native", "attach") or executable(pathlib.Path(wine) / "bin" / "wine"):
        return None
    return WINE_MISSING


def xctrace_problem(environ, which):
    """Returns the sentence that says how to get xctrace, or None when `xcrun --find xctrace` finds it: xcrun exists with
    the Command Line Tools, which do not bring xctrace, so asking for xcrun alone was not the real check."""
    xcrun = which("xcrun", path=environ.get("PATH", ""))
    if not xcrun:
        return XTRACE_MISSING
    try:
        found = subprocess.run([xcrun, "--find", "xctrace"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return XTRACE_MISSING
    return None if found.returncode == 0 else XTRACE_MISSING


def elevated():
    """Returns True when this process runs elevated on Windows, False when it does not, None when it cannot be told."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return None


def environment_report(*, wine=None, seconds=None, environ=None, read=perf_report.read_command, alive=None,
                       platform=None, which=None):
    """Returns what a recording needs, one entry per check: {"ok": bool, "checks": [{"name", "status", "fatal",
    "solution"?}]}, where status is "ok", "missing" or (when it cannot be told) "unknown". `solution` is the exact fix
    and holds no path, machine name or UUID: a report is shared. `seconds` None leaves out the checks of one run (disk,
    screen, lock), which `init` does not need; `wine` None leaves out the Wine check."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    which = shutil.which if which is None else which
    windows = platform == "win32"
    checks = []

    def add(name, status, fatal, solution=None):
        item = {"name": name, "status": status, "fatal": fatal}
        if solution is not None:
            item["solution"] = solution
        checks.append(item)

    if wine is not None:
        problem = wine_problem(wine)
        add("wine", "missing" if problem else "ok", True, problem)
    if windows:
        from metal_gpu_trace import perf_record_windows_presentmon
        try:  # the engine's own lookup; a test that fakes the platform may not have shutil.which's Windows branch
            presentmon = perf_record_windows_presentmon.find_presentmon()
        except (AttributeError, OSError):
            presentmon = None
        add("presentmon", "ok" if presentmon else "missing", False, None if presentmon else PRESENTMON_MISSING)
        admin = elevated()
        add("permissions", "unknown" if admin is None else ("ok" if admin else "missing"), False,
            None if admin is not False else PERMISSIONS_MISSING)
    else:
        problem = xctrace_problem(environ, which)
        add("xctrace", "missing" if problem else "ok", True, problem)
    if seconds is not None:
        need = disk_needed(seconds, environ, windows)
        places = [("disk (runs folder)", "the runs folder", config.OUT)]
        if not windows:
            places.insert(0, ("disk (temporary folder)", "the temporary folder (TMPDIR)",
                              environ.get("TMPDIR") or "/tmp"))
        for name, where, folder in places:
            try:
                free = free_gb(folder)
            except paths.ToolError as error:
                add(name, "missing", True, str(error))
                continue
            add(name, "ok" if free >= need else "missing", True,
                None if free >= need else f"not enough free disk on {where}: {free} GB free, {need} GB needed "
                                           "(PERF_MIN_FREE_GB overrides)")
        if not windows:
            locked = environ.get("METAL_TRACE_ALLOW_LOCKED") != "1" and perf_report.screen_locked(read) is True
            add("screen", "missing" if locked else "ok", True, SCREEN_LOCKED if locked else None)
        running = recording_running(alive)
        add("lock", "missing" if running else "ok", True, LOCK_RUNNING if running else None)
    return {"ok": all(item["status"] == "ok" or not item["fatal"] for item in checks), "checks": checks}


def lock_owner_alive(alive):
    """Returns True when the recording lock names a live process; a missing, odd or dead owner is not one, and a link or
    a file in place of the lock's folder is not followed (the script's own check decides what to do with it)."""
    lock = config.LOCK
    if lock.is_symlink() or not lock.is_dir():
        return False
    try:  # the pid file is read without following a link, never blocking, at most 32 bytes
        descriptor = os.open(lock / "pid", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return False
        owner = os.read(descriptor, 32).decode("ascii", "replace").strip()
    except OSError:
        return False
    finally:
        os.close(descriptor)
    return owner.isascii() and owner.isdigit() and len(owner) <= 10 \
        and 1 <= int(owner) < 2**31 and alive(int(owner))  # OpenProcess takes a 32-bit pid


def recording_running(alive=None):
    """Returns True when the recording lock names a live process; `alive` (a test seam) replaces the platform's check."""
    return lock_owner_alive(process_alive if alive is None else alive)


def check(*, wine, command, seconds, environ=None, read=perf_report.read_command, alive=None):
    """Raises ToolError, with what to do, at the first thing that would make a recording fail: the Wine directory or the
    native program, `xctrace`, free disk (here and in the temporary folder), a locked screen (METAL_TRACE_ALLOW_LOCKED=1
    allows it) and a recording already running. Windows checks the program, the disk of the runs folder and the lock
    only; a missing PresentMon is reported by `environment_report`, not refused: the engine still records."""
    environ = os.environ if environ is None else environ
    if not 1 <= (whole_seconds(seconds) or 0) <= 3600:
        raise paths.ToolError("seconds is a whole number from 1 to 3600")
    if not hasattr(environ, "values") or not all(isinstance(v, str) for v in environ.values()):
        raise paths.ToolError("environ is a mapping of text")
    if not isinstance(wine, (str, os.PathLike)) or not isinstance(command, (list, tuple)) \
            or not all(isinstance(c, (str, os.PathLike)) for c in command):
        raise paths.ToolError("wine is a path or native or attach, and the command a list of strings")
    wine, command = os.fspath(wine), [os.fspath(c) for c in command]
    problem = wine_problem(wine)
    if problem:
        raise paths.ToolError(problem)
    if wine == "native" and not (command and os.path.isfile(command[0]) and executable(command[0])):
        name = pathlib.Path(command[0]).name if command else "the program"
        raise paths.ToolError(f"{name} is not an executable file")
    report = environment_report(wine=wine, seconds=seconds, environ=environ, read=read, alive=alive)
    for item in report["checks"]:
        if item["status"] != "ok" and item["fatal"]:
            raise paths.ToolError(item["solution"])
