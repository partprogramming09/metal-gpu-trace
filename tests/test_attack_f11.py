"""Adversarial tests of the stop path: the group perf_record.sh keeps in its lock, and the kill it feeds the server.

Each test builds its own temp folder, its own program and, for the script, its own lock: nothing here touches a real
recording or a process of the machine it runs on."""
import os
import secrets
import signal
import subprocess
import sys
import time

from support import PKG, hang_stubs, pids_named, stubborn_program, wait_until


def temp_lock(tmp_path, owner):
    """Returns a lock folder owned by `owner`, as a recording leaves it."""
    lock = tmp_path / "lock"
    lock.mkdir()
    (lock / "pid").write_text(f"{owner}\n")
    return lock


def test_a_huge_group_number_in_the_lock_is_not_a_group(tmp_path):
    """The lock is a file the run reads, not a group it trusts: a 5000-digit number there must be ignored like "0" or
    "text", not raise out of the cancel path (int() refuses over 4300 digits)."""
    from metal_gpu_trace import recording
    lock = temp_lock(tmp_path, os.getpid())
    saved = recording.config.LOCK
    recording.config.LOCK = lock
    try:
        for text in ("", "0", "1", "-5", "text", "12 3", "9" * 5000):
            (lock / "program").write_text(text)
            assert recording.launched_group(os.getpid()) is None, f"lock/program {text[:16]!r} must name no group"
    finally:
        recording.config.LOCK = saved


def test_a_child_that_detaches_is_out_of_reach_by_design(tmp_path):
    """Documented limit: a program that forks a child into its own session (setsid) gives it a new group, which the
    stop does not follow; the launched program itself still dies. (The attacker's test asked for the child too;
    reaching it needs tracking every descendant, which the stop does not do.)"""
    from metal_gpu_trace import recording
    name = f"dt-{secrets.token_hex(4)}"
    program = tmp_path / name
    source = tmp_path / "detach.c"
    source.write_text(
        "#include <signal.h>\n#include <unistd.h>\n"
        "int main(void) {\n  signal(SIGTERM, SIG_IGN);\n"
        "  if (fork() == 0) { setsid(); sleep(60); return 0; }\n"
        "  sleep(60);\n  return 0;\n}\n")
    subprocess.run(["cc", "-o", str(program), str(source)], check=True)
    leader = subprocess.Popen([str(program)], start_new_session=True)
    try:
        wait_until(lambda: len(pids_named(name)) == 2, timeout=10)
        recording.kill_program(leader.pid, name)
        assert leader.wait(timeout=10) == -signal.SIGKILL, "the launched program ignores SIGTERM and must be killed"
        time.sleep(0.5)
        assert len(pids_named(name)) == 1, f"the detached child is left running: {pids_named(name)}"
    finally:
        subprocess.run(["pkill", "-KILL", "-x", name], capture_output=True)
        if leader.poll() is None:
            leader.kill()
            leader.wait()


def test_the_script_does_not_stop_a_group_another_process_owns(tmp_path):
    """Only the program the recording launched may die: when the lock names another, live process group (anything can
    write that file), that group must survive the end of the recording."""
    stubs, out, _ = hang_stubs(tmp_path)
    (stubs / "xcrun").write_text((stubs / "xcrun").read_text().replace("sleep 60", "sleep 3"))
    name = f"px-{secrets.token_hex(4)}"
    program = stubborn_program(tmp_path / name)
    outsider = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"], start_new_session=True)
    env = dict(os.environ, PERF_OUT=str(out), PERF_LOCK=str(out / ".recording"), PERF_MIN_FREE_GB="0",
               PATH=f"{stubs}:{os.environ['PATH']}")
    script = subprocess.Popen(["zsh", str(PKG / "perf_record.sh"), "own", "1", "native", "-", str(tmp_path),
                               str(program)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True)
    try:
        lock = out / ".recording"
        wait_until(lambda: (lock / "program").is_file(), timeout=20)
        (lock / "program").write_text(f"{outsider.pid}\n")  # a hostile (or stale) group, not the program's
        script.wait(timeout=60)
        assert outsider.poll() is None, "a group the recording did not launch must keep running"
    finally:
        subprocess.run(["pkill", "-KILL", "-x", name], capture_output=True)
        for proc in (script, outsider):
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_the_script_does_not_signal_its_own_group(tmp_path):
    """The script is never the program: a lock that names the script's own group must not end the script (its TERM
    trap exits 143), whatever runs before the stop."""
    stubs, out, _ = hang_stubs(tmp_path)
    (stubs / "xcrun").write_text((stubs / "xcrun").read_text().replace("sleep 60", "sleep 3"))
    name = f"sw-{secrets.token_hex(4)}"
    program = stubborn_program(tmp_path / name)
    env = dict(os.environ, PERF_OUT=str(out), PERF_LOCK=str(out / ".recording"), PERF_MIN_FREE_GB="0",
               PATH=f"{stubs}:{os.environ['PATH']}")
    script = subprocess.Popen(["zsh", str(PKG / "perf_record.sh"), "self", "1", "native", "-", str(tmp_path),
                               str(program)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              start_new_session=True)
    try:
        lock = out / ".recording"
        wait_until(lambda: (lock / "program").is_file(), timeout=20)
        (lock / "program").write_text(f"{script.pid}\n")
        assert script.wait(timeout=60) != 143, "stop_program must refuse to signal the recording's own group"
    finally:
        subprocess.run(["pkill", "-KILL", "-x", name], capture_output=True)
        if script.poll() is None:
            script.kill()
            script.wait()
