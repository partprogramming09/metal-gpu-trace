"""What a recording needs, checked in milliseconds before any process starts: the program, the tools, the disk, the screen
and the recording lock. perf_record.sh repeats the program, disk and lock checks (defence in depth); the screen is only
checked here."""
import os
import pathlib
import shutil
import stat
import sys

from metal_gpu_trace import config, paths, perf_report


def process_alive(pid):
    """Returns True when process `pid` exists: a signal 0 (never sent on Windows, where it would end the process); a
    process of another user, which refuses the signal, is alive."""
    if not isinstance(pid, int) or isinstance(pid, bool) or not 1 <= pid < 2**31:  # signal 0 to pid 0 or -1 reaches a whole process group
        return False
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


def disk_needed(seconds, environ):
    """Returns the GB perf_record.sh asks for: PERF_MIN_FREE_GB, else 2 plus 0.8 GB per recorded second (Instruments'
    temporary files)."""
    given = (environ.get("PERF_MIN_FREE_GB") or "").strip()
    return int(given) if given.isascii() and given.isdigit() else 2 + (int(seconds) * 8 + 9) // 10


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
    return owner.isascii() and owner.isdigit() and len(owner) <= 10 and alive(int(owner))


def check(*, wine, command, seconds, environ=None, read=perf_report.read_command, alive=None):
    """Raises ToolError, with what to do, at the first thing that would make a recording fail: the Wine directory or the
    native program, `xcrun`, free disk (here and in the temporary folder), a locked screen (METAL_TRACE_ALLOW_LOCKED=1
    allows it) and a recording already running. Windows checks the program, the disk of the runs folder and the lock only."""
    environ = os.environ if environ is None else environ
    windows = sys.platform == "win32"
    if not 1 <= (whole_seconds(seconds) or 0) <= 3600:
        raise paths.ToolError("seconds is a whole number from 1 to 3600")
    if not hasattr(environ, "values") or not all(isinstance(v, str) for v in environ.values()):
        raise paths.ToolError("environ is a mapping of text")
    if not isinstance(wine, (str, os.PathLike)) or not isinstance(command, (list, tuple)) \
            or not all(isinstance(c, (str, os.PathLike)) for c in command):
        raise paths.ToolError("wine is a path or native or attach, and the command a list of strings")
    wine, command = os.fspath(wine), [os.fspath(c) for c in command]
    if wine not in ("native", "attach") and not executable(pathlib.Path(wine) / "bin" / "wine"):
        raise paths.ToolError("no Wine at bin/wine inside that Wine directory (pass native for a macOS program)")
    if wine == "native" and not (command and os.path.isfile(command[0]) and executable(command[0])):
        name = pathlib.Path(command[0]).name if command else "the program"
        raise paths.ToolError(f"{name} is not an executable file")
    if not windows and not shutil.which("xcrun", path=environ.get("PATH", "")):
        raise paths.ToolError("xcrun is not on PATH: install Xcode or the command line tools (xcode-select --install)")
    if windows:  # no Instruments here: only the runs folder takes the recording, so no 0.8 GB per second
        given = (environ.get("PERF_MIN_FREE_GB") or "").strip()
        need, places = (int(given) if given.isascii() and given.isdigit() else 1), [("the runs folder", config.OUT)]
    else:
        need = disk_needed(seconds, environ)
        places = [("the temporary folder (TMPDIR)", environ.get("TMPDIR") or "/tmp"), ("the runs folder", config.OUT)]
    for what, where in places:
        free = free_gb(where)
        if free < need:
            raise paths.ToolError(f"not enough free disk on {what}: {free} GB free, {need} GB needed "
                                  "(PERF_MIN_FREE_GB overrides)")
    if not windows and environ.get("METAL_TRACE_ALLOW_LOCKED") != "1" and perf_report.screen_locked(read) is True:
        raise paths.ToolError("the screen is locked: a locked session leaves the program's frames unpaced by the display, "
                              "so the numbers do not compare; unlock the Mac, or set METAL_TRACE_ALLOW_LOCKED=1 to record anyway")
    if alive is None:
        if windows:
            from metal_gpu_trace import perf_record_windows
            alive = perf_record_windows.is_process_alive
        else:
            alive = process_alive
    if lock_owner_alive(alive):
        raise paths.ToolError("another recording is running; one runs at a time. If none is, remove the lock folder "
                              "(METAL_TRACE_LOCK names it)")
