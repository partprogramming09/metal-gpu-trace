"""preflight: what a recording needs, checked in milliseconds before any process starts."""
import collections
import os
import shutil
import sys

import support  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import config, paths, perf_record_windows, preflight, recording

Usage = collections.namedtuple("Usage", "total used free")
GB = 2**30


def refused(words, **kw):
    """Calls preflight.check(**kw) and returns the ToolError text, after checking it holds each of `words`."""
    try:
        preflight.check(**kw)
    except paths.ToolError as error:
        for word in words:
            assert word in str(error), (word, str(error))
        return str(error)
    raise AssertionError(f"preflight must refuse {words}")


def setup(tmp_path, free_gb=500):
    """A Wine directory, a native program, an `xcrun` on PATH and a runs folder; returns the keyword arguments of a
    check that passes, with the screen readable and unlocked, the disk roomy and no lock."""
    wine = tmp_path / "wine"
    (wine / "bin").mkdir(parents=True)
    (wine / "bin" / "wine").write_text("#!/bin/sh\n")
    (wine / "bin" / "wine").chmod(0o755)
    program = tmp_path / "prog"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "xcrun").write_text("#!/bin/sh\n")
    (stubs / "xcrun").chmod(0o755)
    config.OUT = tmp_path / "runs"
    config.OUT.mkdir()
    config.LOCK = tmp_path / "lock"
    return {"wine": str(wine), "command": [str(program)], "seconds": 30,
            "environ": {"PATH": str(stubs), "TMPDIR": str(tmp_path)}, "read": lambda argv: "no lock here",
            "alive": lambda pid: False}


class Saved:
    """Restores what a test changed: config.OUT, config.LOCK, shutil.disk_usage and sys.platform."""
    def __enter__(self):
        self.state = config.OUT, config.LOCK, shutil.disk_usage, sys.platform, os.kill, shutil.which
        sys.platform = "darwin"  # these tests describe the macOS shape; the Windows ones set win32 themselves
        return self

    def __exit__(self, *exc):
        config.OUT, config.LOCK, shutil.disk_usage, sys.platform, os.kill, shutil.which = self.state


def test_passes_when_everything_is_in_place(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        preflight.check(**kw)
        preflight.check(**{**kw, "wine": "native"})
        preflight.check(**{**kw, "wine": "attach", "command": ["1234"]})


def test_missing_wine_binary(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        refused(["no Wine", "native"], **{**kw, "wine": str(tmp_path / "nowhere")})
        assert str(tmp_path) not in refused(["no Wine"], **{**kw, "wine": str(tmp_path / "nowhere")}), "no path in the message"


def test_native_program_not_executable(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        plain = tmp_path / "plain"
        plain.write_text("x")
        if os.name != "nt":  # on Windows every file passes the executable check
            refused(["not an executable file"], **{**kw, "wine": "native", "command": [str(plain)]})
        refused(["not an executable file"], **{**kw, "wine": "native", "command": [str(tmp_path / "missing")]})


def test_no_xcrun(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        kw["environ"]["PATH"] = str(tmp_path / "empty")
        shutil.which = lambda name, path=None: None
        refused(["xcrun"], **kw)


def test_not_enough_disk_names_the_override(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        shutil.disk_usage = lambda path: Usage(10 * GB, 9 * GB, 1 * GB)
        text = refused(["not enough free disk", "PERF_MIN_FREE_GB", "1 GB free", "26 GB needed"], **kw)
        assert str(tmp_path) not in text, text
        kw["environ"]["PERF_MIN_FREE_GB"] = "1"
        preflight.check(**kw)
        kw["environ"]["PERF_MIN_FREE_GB"] = "nonsense"  # not a number: the formula applies
        refused(["26 GB needed"], **kw)


def test_disk_formula_matches_the_shell():
    for seconds in (1, 10, 60):
        assert preflight.disk_needed(seconds, {}) == 2 + (seconds * 8 + 9) // 10, seconds
    assert preflight.disk_needed(30, {"PERF_MIN_FREE_GB": "7"}) == 7
    assert preflight.disk_needed(30, {"PERF_MIN_FREE_GB": "0"}) == 0


def test_runs_folder_that_does_not_exist_yet_uses_its_parent(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        config.OUT = tmp_path / "new" / "deeper"
        seen = []
        shutil.disk_usage = lambda path: seen.append(str(path)) or Usage(0, 0, 500 * GB)
        preflight.check(**kw)
        assert str(tmp_path) in seen and all(os.path.exists(p) for p in seen), seen


def test_locked_screen_refuses_and_names_the_override(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        kw["read"] = lambda argv: "... CGSSessionScreenIsLocked ..."
        refused(["screen is locked", "METAL_TRACE_ALLOW_LOCKED=1"], **kw)


def test_locked_screen_allowed_with_env(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        kw["read"] = lambda argv: "CGSSessionScreenIsLocked"
        kw["environ"]["METAL_TRACE_ALLOW_LOCKED"] = "1"
        preflight.check(**kw)
        kw["environ"]["METAL_TRACE_ALLOW_LOCKED"] = "yes"  # only 1 counts
        refused(["screen is locked"], **kw)


def test_unreadable_screen_state_passes(tmp_path):
    with Saved():
        kw = setup(tmp_path)

        def broken(argv):
            raise OSError("no ioreg")
        kw["read"] = broken
        preflight.check(**kw)
        assert preflight.perf_report.screen_locked(broken) is None


def make_lock(tmp_path, pid):
    config.LOCK.mkdir()
    if pid is not None:
        (config.LOCK / "pid").write_text(f"{pid}\n")


def test_live_lock_refuses(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        make_lock(tmp_path, 4242)
        asked = []
        kw["alive"] = lambda pid: asked.append(pid) or True
        text = refused(["another recording is running"], **kw)
        assert asked == [4242] and str(tmp_path) not in text, (asked, text)


def test_dead_lock_passes(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        make_lock(tmp_path, 4242)
        preflight.check(**kw)


def test_lock_without_pid_passes(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        make_lock(tmp_path, None)
        preflight.check(**kw)
        (config.LOCK / "pid").write_text("not a number")
        preflight.check(**kw)


def test_lock_that_is_a_file_or_link_is_not_followed(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        pidfile = tmp_path / "elsewhere"
        pidfile.write_text("4242\n")
        config.LOCK.symlink_to(tmp_path, target_is_directory=True)
        (tmp_path / "pid").write_text("4242\n")
        kw["alive"] = lambda pid: True
        preflight.check(**kw)  # a link in place of the lock folder is not a live owner
        config.LOCK.unlink()
        config.LOCK.write_text("a file where the folder should be")
        preflight.check(**kw)


def test_lock_check_never_signals_on_windows(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        make_lock(tmp_path, 4242)
        del kw["alive"]
        sys.platform = "win32"

        def never(pid, sig):
            raise AssertionError("os.kill must not be called on Windows: it terminates the process there")
        os.kill = never
        asked = []
        saved = perf_record_windows.is_process_alive
        perf_record_windows.is_process_alive = lambda pid: asked.append(pid) or True
        try:
            refused(["another recording is running"], **kw)
        finally:
            perf_record_windows.is_process_alive = saved
        assert asked == [4242]


def test_windows_skips_xcrun_and_the_screen_and_needs_little_disk(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        sys.platform = "win32"
        kw["environ"] = {"PATH": str(tmp_path / "empty")}
        kw["read"] = lambda argv: (_ for _ in ()).throw(AssertionError("the screen is not read on Windows"))
        shutil.disk_usage = lambda path: Usage(0, 0, 3 * GB)
        preflight.check(**{**kw, "wine": "native", "seconds": 60})  # the macOS formula would ask 50 GB
        refused(["not enough free disk"], **{**kw, "wine": "native", "environ": {"PERF_MIN_FREE_GB": "9"}})


def test_linux_ci_shape_passes(tmp_path):
    """No ioreg (read raises OSError), a stub xcrun on PATH: the CI's machine passes."""
    with Saved():
        kw = setup(tmp_path)

        def no_ioreg(argv):
            raise OSError("ioreg not found")
        kw["read"] = no_ioreg
        shutil.which = lambda name, path=None: str(tmp_path / "stubs" / name) if name == "xcrun" else None
        preflight.check(**kw)


def test_default_alive_uses_a_signal_zero_and_counts_permission_denied_as_alive():
    if os.name == "posix":  # a real signal 0: on Windows it would be CTRL_C_EVENT and interrupt the test run
        assert preflight.process_alive(os.getpid()) is True
        assert preflight.process_alive(2**22 + 12345) is False
    with Saved():
        sys.platform = "linux"  # the POSIX branch, whatever machine runs the test

        def fake(pid, sig):
            assert sig == 0
            if pid == 1:
                raise PermissionError
            if pid != 4242:
                raise ProcessLookupError
        os.kill = fake
        assert preflight.process_alive(4242) is True
        assert preflight.process_alive(1) is True  # another user's process refuses the signal: it exists
        assert preflight.process_alive(4243) is False


def test_process_alive_never_signals_on_windows_even_when_called_directly():
    """os.kill(pid, 0) on Windows is CTRL_C_EVENT: asking about the test's own pid interrupted the whole pytest run."""
    with Saved():
        sys.platform = "win32"

        def never(pid, sig):
            raise AssertionError("os.kill must not be called on Windows")
        os.kill = never
        asked = []
        saved = perf_record_windows.is_process_alive
        perf_record_windows.is_process_alive = lambda pid: asked.append(pid) or True
        try:
            assert preflight.process_alive(os.getpid()) is True
            assert preflight.process_alive(0) is False  # a bad pid is refused before any platform call
            perf_record_windows.is_process_alive = lambda pid: False
            assert preflight.process_alive(os.getpid()) is False  # the engine's answer is the answer
        finally:
            perf_record_windows.is_process_alive = saved
        assert asked == [os.getpid()]


def test_record_runs_preflight_before_memory_pressure(tmp_path):
    saved = recording.hold_memory_pressure, preflight.check
    called = []
    recording.hold_memory_pressure = lambda *a, **k: called.append("pressure")

    def failing(**kw):
        raise paths.ToolError("preflight said no")
    preflight.check = failing
    try:
        try:
            recording.record("p", 5, "native", "-", str(tmp_path), ["prog"], True, memory_free_pct=30)
        except paths.ToolError as error:
            assert "preflight said no" in str(error)
        else:
            raise AssertionError("record must raise")
    finally:
        recording.hold_memory_pressure, preflight.check = saved
    assert called == [], "memory_pressure must not start for a doomed run"


@support.macos_only
def test_preflight_failure_starts_no_process(tmp_path):
    stubs, out, program = support.hang_stubs(tmp_path)
    (stubs / "xcrun").write_text(f"#!/bin/zsh\ntouch {tmp_path}/xctrace-ran\n")
    saved = config.OUT, config.LOCK, os.environ.get("PATH"), os.environ.pop("PERF_MIN_FREE_GB", None)
    config.OUT = out
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    os.environ["PERF_MIN_FREE_GB"] = "99999999"
    try:
        try:
            recording.record("n", 5, "native", "-", str(tmp_path), [str(program)], "", True)
        except paths.ToolError as error:
            assert "not enough free disk" in str(error), error
        else:
            raise AssertionError("a doomed recording must be refused")
    finally:
        config.OUT, config.LOCK = saved[:2]
        os.environ["PATH"] = saved[2]
        os.environ.pop("PERF_MIN_FREE_GB")
        if saved[3] is not None:
            os.environ["PERF_MIN_FREE_GB"] = saved[3]
    assert not (tmp_path / "xctrace-ran").exists() and not list(out.iterdir())


def test_first_progress_says_the_worst_case(tmp_path):
    saved = recording.progress, config.PACKAGE_DIR, config.OUT
    seen = []
    recording.progress = lambda done, total, message: seen.append((done, total, message))
    config.OUT = tmp_path
    config.PACKAGE_DIR = tmp_path  # no perf_record.sh here: the run fails right after its first progress line
    try:
        try:
            recording.record_run("q", 20, "native", "-", str(tmp_path), ["prog"], layer={"none": "x"})
        except (paths.ToolError, OSError, FileNotFoundError):
            pass
    finally:
        recording.progress, config.PACKAGE_DIR, config.OUT = saved
    limit = recording.deadline(20)
    assert seen[0] == (0, limit, f"recording: up to {limit} s including read-back"), seen


def test_hostile_pid_files_are_not_a_live_owner(tmp_path):
    """A pid of 0 (a signal to a whole process group), a negative or huge one, text, or a link or FIFO in place of the pid
    file never counts as a live owner and never raises."""
    with Saved():
        kw = setup(tmp_path)
        kw["alive"] = preflight.process_alive
        config.LOCK.mkdir()
        for text in ("0", "-1", "9" * 40, "1e3", "", "12 34", "\x00", "4294967297"):
            (config.LOCK / "pid").write_text(text)
            preflight.check(**kw)
        (config.LOCK / "pid").unlink()
        (config.LOCK / "pid").symlink_to(tmp_path / "prog")
        preflight.check(**kw)
        (config.LOCK / "pid").unlink()
        os.mkfifo(config.LOCK / "pid")
        preflight.check(**kw)  # a FIFO would block a plain read
    assert [preflight.process_alive(p) for p in (0, -1, 2**31, 10**30, "1", None, True)] == [False] * 7
    assert preflight.process_alive(0) is False and preflight.process_alive(-1) is False
    assert preflight.process_alive(10**30) is False and preflight.process_alive(os.getpid()) is True


def test_seconds_are_checked_before_anything_else(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        for bad in (0, -5, "abc", 3601, None, True, [1], 1.5e400):
            refused(["seconds"], **{**kw, "seconds": bad})
        preflight.check(**{**kw, "seconds": "20"})
        kw["environ"]["PERF_MIN_FREE_GB"] = "1"  # 3600 s would ask for 2882 GB
        preflight.check(**{**kw, "seconds": 3600})


def test_record_checks_the_label_before_pressure_and_preflight(tmp_path):
    saved = recording.hold_memory_pressure, preflight.check
    called = []
    recording.hold_memory_pressure = lambda *a, **k: called.append("pressure")
    preflight.check = lambda **kw: called.append("preflight")
    try:
        try:
            recording.record("bad label!", 5, "native", "-", str(tmp_path), ["prog"], True, memory_free_pct=30)
        except paths.ToolError as error:
            assert "label holds" in str(error)
        else:
            raise AssertionError("an odd label must be refused")
    finally:
        recording.hold_memory_pressure, preflight.check = saved
    assert called == []


def test_attach_goes_through_preflight(tmp_path):
    saved = preflight.check, recording.record_run
    seen = []
    preflight.check = lambda **kw: seen.append(kw)
    recording.record_run = lambda *a, **k: {}
    try:
        recording.tool_perf_attach("at", "1234", seconds=7)
    finally:
        preflight.check, recording.record_run = saved
    assert seen[0]["wine"] == "attach" and seen[0]["command"] == ["1234"] and seen[0]["seconds"] == 7, seen


def test_what_worked_before_still_passes(tmp_path):
    """Hardening must not refuse the forms the package itself passes: seconds as digits or a whole float, Path objects."""
    import pathlib
    with Saved():
        kw = setup(tmp_path)
        kw["environ"]["PERF_MIN_FREE_GB"] = "1"
        for seconds in (20, "20", 20.0, " 20 "):
            preflight.check(**{**kw, "seconds": seconds})
        preflight.check(**{**kw, "wine": pathlib.Path(kw["wine"]), "command": [pathlib.Path(kw["command"][0])]})
        preflight.check(**{**kw, "wine": "native", "command": [pathlib.Path(kw["command"][0])]})
        for bad in ("10_0", 10.5, 3600.9, "２０", "1e1", float("nan"), float("inf")):
            refused(["seconds"], **{**kw, "seconds": bad})


def test_missing_path_in_environ_is_not_the_process_path(tmp_path):
    with Saved():
        kw = setup(tmp_path)
        kw["environ"] = {"TMPDIR": str(tmp_path), "PERF_MIN_FREE_GB": "1"}
        refused(["xcrun"], **kw)


def test_a_pid_beyond_what_the_system_gives_is_never_asked_about(tmp_path):
    """On Windows OpenProcess takes a 32-bit pid: a lock file with a larger one must not reach it (ctypes raises)."""
    with Saved():
        kw = setup(tmp_path)
        asked = []
        kw["alive"] = lambda pid: asked.append(pid) or True
        make_lock(tmp_path, 2**31)
        preflight.check(**kw)
        assert asked == [], asked
        (config.LOCK / "pid").write_text(str(2**31 - 1))
        refused(["another recording is running"], **kw)
        assert asked == [2**31 - 1], asked


def test_windows_is_process_alive_refuses_a_pid_outside_32_bits_before_the_api():
    """OpenProcess takes a 32-bit pid and a stale lock file can hold anything; on macOS reaching ctypes.windll raises."""
    for pid in (0, -1, 2**31, 2**32 + 1, 10**20):
        assert perf_record_windows.is_process_alive(pid) is False, pid
