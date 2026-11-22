"""paths.write_file replaces a file whole or not at all: a reader, a second writer or a crash never sees half a
summary, and a failed write leaves no stray temporary file."""
import errno
import json
import os
import pathlib
import stat
import subprocess
import sys
import time

from support import PKG, ROOT

# a child that writes a big summary once and says when it starts; the parent crashes it mid-write
CRASHER = r'''
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from metal_gpu_trace import paths
dest = pathlib.Path(sys.argv[2])
payload = json.dumps({"run": "new", "pad": "x" * (32 * 1024 * 1024)})
print("ready", flush=True)
paths.write_file(dest, payload)
print("done", flush=True)
'''

# a child that rewrites the same destination many times; two of them run at once
WRITER = r'''
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from metal_gpu_trace import paths
dest, tag, rounds = pathlib.Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])
payload = json.dumps({"writer": tag, "pad": tag * 20000})
for _ in range(rounds):
    paths.write_file(dest, payload)
'''


def leftovers(directory, keep):
    """Returns the files in `directory` other than `keep` (a temporary one left behind would show here)."""
    return sorted(p.name for p in pathlib.Path(directory).iterdir() if p.name != keep)


def test_a_crash_mid_write_keeps_the_previous_summary(tmp_path):
    """A process killed while paths.write_file runs leaves the previous summary or the whole new one, never a truncated
    file."""
    from metal_gpu_trace import paths

    dest = tmp_path / "run.json"
    old = json.dumps({"run": "old", "pad": "o" * 64})
    paths.write_file(dest, old)
    child = subprocess.Popen([sys.executable, "-I", "-c", CRASHER, str(ROOT / "src"), str(dest)],
                             stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready", "the child did not reach the write"
        deadline = time.monotonic() + 10  # a truncating write shows here as a size that is neither the old one
        while child.poll() is None and time.monotonic() < deadline:
            if dest.stat().st_size != len(old):
                break
            time.sleep(0.001)
        child.kill()
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    try:
        summary = json.loads(dest.read_text(encoding="utf-8"))
    except ValueError as error:
        raise AssertionError(f"a crash left half a summary ({dest.stat().st_size} bytes): {error}") from None
    assert summary["run"] in ("old", "new"), summary["run"]
    if summary["run"] == "new":  # the write had committed: every byte must be there
        assert len(summary["pad"]) == 32 * 1024 * 1024


def test_two_writers_at_once_and_a_reader_see_whole_files(tmp_path):
    """Two processes rewrite one summary while a reader reopens it: each read is a complete version of one writer, and
    the last write is complete too."""
    dest = tmp_path / "run.json"
    children = [subprocess.Popen([sys.executable, "-I", "-c", WRITER, str(ROOT / "src"), str(dest), tag, "150"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True) for tag in ("a", "b")]
    seen = 0
    try:
        while any(child.poll() is None for child in children):
            try:
                text = dest.read_text(encoding="utf-8")
            except FileNotFoundError:  # not written yet
                continue
            if text:
                summary = json.loads(text)  # raises while a write is halfway: the bug this test is for
                assert summary["writer"] in ("a", "b") and len(summary["pad"]) == 20000
                seen += 1
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
    errors = [child.stderr.read() for child in children if child.returncode]
    assert not errors, errors
    assert seen > 0, "the reader never caught a write"
    summary = json.loads(dest.read_text(encoding="utf-8"))
    assert summary["writer"] in ("a", "b") and len(summary["pad"]) == 20000
    assert leftovers(tmp_path, "run.json") == [], "a writer left a temporary file behind"


def test_a_link_is_refused_and_leaves_no_temporary_file(tmp_path):
    """A destination that is a link is still refused before anything is written, and the file behind it is untouched."""
    from metal_gpu_trace import paths

    victim = tmp_path / "precious.txt"
    victim.write_text("PRECIOUS", encoding="utf-8")
    link = tmp_path / "run.json"
    link.symlink_to(victim)
    try:
        paths.write_file(link, '{"run": "new"}')
        raise AssertionError("a link must be refused")
    except paths.ToolError as error:
        assert "link" in str(error), error
    assert victim.read_text(encoding="utf-8") == "PRECIOUS"
    assert leftovers(tmp_path, "run.json") == ["precious.txt"]


def test_a_folder_without_permission_is_a_clear_error_without_a_temporary(tmp_path):
    """Where the folder cannot be written, the error names the reason and no temporary file is left in it."""
    from metal_gpu_trace import paths

    if sys.platform == "win32":  # no geteuid, and chmod does not keep a file from being created
        return None
    if os.geteuid() == 0:  # root writes anywhere
        return None
    folder = tmp_path / "runs"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        paths.write_file(folder / "run.json", '{"run": "new"}')
        raise AssertionError("a folder without write permission must be an error")
    except paths.ToolError as error:
        assert "permission" in str(error).lower(), error
        assert str(tmp_path) not in str(error), error
    finally:
        folder.chmod(0o700)
    assert list(folder.iterdir()) == []


def test_a_full_disk_keeps_the_previous_file_and_leaves_no_temporary(tmp_path):
    """A disk that fills before the rename is an error that keeps the previous summary and removes the temporary."""
    from metal_gpu_trace import paths

    dest = tmp_path / "run.json"
    paths.write_file(dest, '{"run": "old"}')
    real = os.fsync

    def full(fd):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    paths.os.fsync = full
    try:
        paths.write_file(dest, '{"run": "new"}')
        raise AssertionError("a full disk must be an error")
    except paths.ToolError as error:
        assert "full" in str(error).lower() or "space" in str(error).lower(), error
        assert str(tmp_path) not in str(error), error
    finally:
        paths.os.fsync = real
    assert json.loads(dest.read_text(encoding="utf-8")) == {"run": "old"}
    assert leftovers(tmp_path, "run.json") == []


def test_the_same_write_twice_gives_the_same_file(tmp_path):
    """Writing the same summary again replaces it with the same bytes and leaves no temporary file."""
    from metal_gpu_trace import paths

    dest = tmp_path / "run.json"
    text = json.dumps({"run": "a", "pad": "x" * 4096})
    paths.write_file(dest, text)
    first = dest.read_bytes()
    paths.write_file(dest, text)
    assert dest.read_bytes() == first
    assert leftovers(tmp_path, "run.json") == []


def test_a_new_summary_keeps_the_umask_mode(tmp_path):
    """A summary created through write_file gets the mode os.open(..., 0o666) gave before (0o644 under umask 022), not
    the 0o600 of the temporary file it is renamed from."""
    from metal_gpu_trace import paths

    if sys.platform == "win32":  # no POSIX permission bits
        return None
    old = os.umask(0o022)
    try:
        dest = tmp_path / "run.json"
        paths.write_file(dest, '{"run": "new"}')
        mode = stat.S_IMODE(dest.stat().st_mode)
        assert mode == 0o644, oct(mode)
    finally:
        os.umask(old)


def test_the_summary_writers_write_through_paths():
    """The two engines and the macOS summarizer write their summary with paths.write_file; the lock's pid file, which
    no tool reads as a result, stays a plain write."""
    for name in ("recording", "perf_report", "perf_record_windows"):
        source = (PKG / f"{name}.py").read_text(encoding="utf-8")
        assert "paths.write_file(" in source, name
        assert 'json_path.write_text(' not in source, name
        assert '"}.json").write_text(' not in source, name
    assert 'lock_path / "pid").write_text(' in (PKG / "perf_record_windows.py").read_text(encoding="utf-8")
