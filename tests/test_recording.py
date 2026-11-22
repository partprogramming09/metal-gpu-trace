"""Tests of recording: perf_record.sh, perf_record and its levers, layers and workloads."""
import json
import os
import pathlib
import secrets
import shutil
import subprocess
import sys

from support import ROOT, PKG, macos_only, hang_stubs, unique_program  # also puts src/ on sys.path


def test_memory_param(tmp_path):
    """perf_record passes memory=false on to the recording, which sets PERF_MEMORY=0, and offers it in its schema."""
    from metal_gpu_trace import recording, registry
    seen = []
    saved = recording.record
    recording.record = lambda *args, **kw: seen.append(args[-1]) or {}
    program = tmp_path / "prog"
    program.write_text("")
    try:
        recording.tool_perf_record("m", str(program), wine="native")
        recording.tool_perf_record("m", str(program), wine="native", memory=False)
    finally:
        recording.record = saved
    assert seen == [True, False], seen
    assert registry.RECORD_PROPS["memory"]["type"] == "boolean"

@macos_only
def test_disk_guard(tmp_path):
    """perf_record.sh refuses to start, before locking or recording, when the disk lacks the space Instruments needs."""
    script = PKG / "perf_record.sh"
    env = {**os.environ, "PERF_OUT": str(tmp_path), "PERF_LOCK": str(tmp_path / ".recording"), "PERF_MIN_FREE_GB": "99999999"}
    proc = subprocess.run(["zsh", str(script), "g", "30", "native", "-", "-", sys.executable], env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 4 and "not enough free disk" in proc.stderr and "99999999 GB needed" in proc.stderr, proc
    assert not (tmp_path / ".recording").exists(), "no lock is left behind"
    default = subprocess.run(["zsh", str(script), "g", "60", "native", "-", "-", sys.executable],
                             env={**os.environ, "PERF_OUT": str(tmp_path), "TMPDIR": "/nonexistent"},
                             capture_output=True, text=True, timeout=60)
    assert default.returncode != 0, "a missing TMPDIR volume must not pass the guard"

@macos_only
def test_attach_by_name_never_picks_the_process_that_called_it(tmp_path):
    """The caller's own command line may hold the program's name (python -c "...Game.exe..."): the script must not attach to it."""
    # the name is unique per run: a second suite's caller holds this same sentence in its command line, and the script
    # matches the newest process whose command line holds the name, so a shared name would attach to that other suite
    token = f"NoSuchGame-{os.getpid()}-{secrets.token_hex(4)}.exe"
    # the command line must hold the name but none of the words the script already skips (zsh, perf_record, awk, xctrace)
    code = ("import os, subprocess; e = os.environ; env = dict(e, PERF_PARENT_PID=str(os.getpid()), PERF_LOCK=e['T'] + '/.l', "
            "PERF_OUT=e['T'], PERF_MIN_FREE_GB='99999999'); sh = 'z' + 'sh'; "
            "p = subprocess.run([sh, e['S'], 'a', '5', 'attach', '-', '-', '" + token + "'], env=env, capture_output=True, text=True); "
            "print(p.returncode); print(p.stderr)")
    proc = subprocess.run([sys.executable, "-c", code], env={**os.environ, "S": str(PKG / "perf_record.sh"), "T": str(tmp_path)},
                          capture_output=True, text=True, timeout=60)
    assert proc.stdout.splitlines()[0] == "2" and f"no running process matches {token}" in proc.stdout, proc

def test_levers(tmp_path):
    """memory_free_pct holds memory_pressure around a recording and stops it even when the recording fails;
    background sets PERF_PREFIX for perf_record.sh; out-of-range or Windows use is refused before anything starts."""
    from metal_gpu_trace import config, paths, preflight, recording, registry
    stable = tmp_path / "stable.sh"
    stable.write_text("#!/bin/sh\necho 'Stable at percent free: 40.'\nsleep 300\n")
    never = tmp_path / "never.sh"
    never.write_text("#!/bin/sh\nsleep 300\n")
    for script in (stable, never):
        script.chmod(0o755)
    assert recording.BACKGROUND_PREFIX.startswith("/") and recording.BACKGROUND_PREFIX.endswith(" -b"), recording.BACKGROUND_PREFIX
    if sys.platform == "darwin":
        assert os.access(recording.BACKGROUND_PREFIX.split()[0], os.X_OK), "taskpolicy must exist"
    saved = config.MEMORY_PRESSURE, recording.record_run
    try:
        config.MEMORY_PRESSURE = [str(stable)]
        proc = recording.hold_memory_pressure(40, 60)
        assert proc.poll() is None
        proc.terminate()
        proc.wait()
        config.MEMORY_PRESSURE = [str(never)]
        try:
            recording.hold_memory_pressure(40, 60, wait_s=1)
            raise AssertionError("a pressure that is never reached must fail")
        except paths.ToolError as error:
            assert "did not reach" in str(error), error
        started = []
        config.MEMORY_PRESSURE = [str(stable)]
        original = recording.hold_memory_pressure

        def spy(*args, **kwargs):
            started.append(original(*args, **kwargs))
            return started[-1]
        recording.hold_memory_pressure = spy
        seen = {}

        def fake_run(*args, **kwargs):
            seen.update(kwargs, held=started[0].poll() is None)
            raise RuntimeError("boom")
        recording.record_run = fake_run
        real_check, preflight.check = preflight.check, lambda **kw: None  # this test is about memory_pressure, not preflight
        try:
            recording.record("x", 5, "native", "-", ".", ["p"], memory_free_pct=40, background=True)
            raise AssertionError("the failure must come out")
        except RuntimeError:
            pass
        assert seen["held"] and seen["background"] is True, seen
        started[0].wait(timeout=10)
        assert started[0].poll() is not None, "memory_pressure must be stopped after the recording"
        recording.hold_memory_pressure = original
        for kwargs in ({"memory_free_pct": 10}, {"memory_free_pct": 61}, {"memory_free_pct": "x"}):
            try:
                recording.check_levers(**kwargs)
                raise AssertionError(kwargs)
            except paths.ToolError as error:
                assert "memory_free_pct" in str(error), error
        recording.check_levers(memory_free_pct=20, background=True)
    finally:
        config.MEMORY_PRESSURE, recording.record_run = saved
        recording.hold_memory_pressure = original
        preflight.check = real_check
    assert registry.RECORD_PROPS["memory_free_pct"]["type"] == "integer" and registry.RECORD_PROPS["background"]["type"] == "boolean"

def test_rosetta_layer(tmp_path):
    """An api marked rosetta in data/workloads.json is named as such in the run's layer, so perf_compare against native
    Metal says it compares two layers."""
    from metal_gpu_trace import config, recording, workloads
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/x.tar.gz", "bytes": 1,
             "sha256": "0" * 64, "dir": "demo", "dim_variable": "DIM",
             "apis": {"mtl": {"program": "demo", "args": "--mtl", "wine": False},
                      "mtl-x64": {"program": "demo-x64", "args": "--mtl", "wine": False, "rosetta": True}}}
    saved = config.WORKLOADS
    config.WORKLOADS = {"demo": entry}
    try:
        assert workloads.workload_layer("demo", "mtl", 20) is None
        layer = workloads.workload_layer("demo", "mtl-x64", 20)
        assert "rosetta" in layer and layer["program_env"] == "DIM=20", layer
        assert recording.layer_label(layer) == "rosetta"
        native = {"none": "native Metal, no translation layer", "program_env": "DIM=20"}
        ma = {"layer": native, "gpu": {"frames": 300}}
        mb = {"layer": layer, "gpu": {"frames": 300}}
        got = recording.layer_change(ma, mb, "a", "b")
        assert got["same"] is False and got["b"] == "rosetta" and "two layers" in got["note"], got
    finally:
        config.WORKLOADS = saved
    shipped = json.loads((PKG / "data" / "workloads.json").read_text())["workloads"]["drawstress"]
    assert shipped["apis"]["mtl-x64"]["rosetta"] is True and shipped["size_variables"] == ["DRAWSTRESS_WIDTH", "DRAWSTRESS_HEIGHT"]
    assert "workloads-3" in shipped["url"] and len(shipped["sha256"]) == 64

def test_size(tmp_path):
    """size ("WxH") becomes the workload's two size variables, is refused for a workload without them or when badly
    written, and perf_sweep can sweep it."""
    from metal_gpu_trace import config, experiments, paths, recording, registry, workloads
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/x.tar.gz", "bytes": 1,
             "sha256": "0" * 64, "dir": "demo", "dim_variable": "DIM", "size_variables": ["DEMO_W", "DEMO_H"],
             "apis": {"mtl": {"program": "demo", "args": "--mtl", "wine": False}}}
    plain = {k: v for k, v in entry.items() if k != "size_variables"}
    saved, cache = config.WORKLOADS, config.CACHE
    config.CACHE = tmp_path
    try:
        config.WORKLOADS = {"demo": entry, "plain": plain}
        for name in ("demo", "plain"):
            (tmp_path / f"{name}-{'0' * 12}").mkdir()
        got = workloads.workload_command("demo", "mtl", 20, None, "", size="1280x720")
        assert got[3] == "DIM=20 DEMO_W=1280 DEMO_H=720", got
        assert workloads.workload_command("demo", "mtl", None, None, "")[3] == ""
        for name, size, words in (("plain", "1280x720", "size does not apply to plain"),
                                  ("demo", "big", "size is WIDTHxHEIGHT"), ("demo", "100x100", "size is WIDTHxHEIGHT"),
                                  ("demo", "9000x720", "size is WIDTHxHEIGHT")):
            try:
                workloads.workload_command(name, "mtl", None, None, "", size=size)
                raise AssertionError((name, size))
            except paths.ToolError as error:
                assert words in str(error), error
        made = []

        def fake_record(label, **kw):
            made.append((label, kw.get("size")))
            (tmp_path / f"{label}_20261018-000000.json").write_text(json.dumps(
                {"gpu": {"frames": 300, "fps_estimate": 100.0, "frame_gpu_ms": {"mean": 4.0}, "stutter_rate_pct": 0.0}}))
        saved_record, saved_out = recording.tool_perf_record, config.OUT
        recording.tool_perf_record, config.OUT = fake_record, tmp_path
        try:
            got = experiments.tool_perf_sweep("s", "size", ["640x360", "1280x720"], seconds=8)
            assert made == [("s-1-r1", "640x360"), ("s-2-r1", "1280x720")] and got["fit"] is None, (made, got)
            try:
                experiments.tool_perf_sweep("s", "size", ["640x360", "wide"])
                raise AssertionError("a bad size must fail before recording")
            except paths.ToolError as error:
                assert "WIDTHxHEIGHT" in str(error), error
        finally:
            recording.tool_perf_record, config.OUT = saved_record, saved_out
    finally:
        config.WORKLOADS, config.CACHE = saved, cache
    assert registry.RECORD_PROPS["size"]["type"] == "string"

@macos_only
def test_layer(tmp_path):
    """A recording's layer fingerprint is stable, changes with any Direct3D DLL, carries the overrides and program
    variables, and perf_compare tells two layers from one."""
    from metal_gpu_trace import recording
    wine, prefix = tmp_path / "mullion-wine", tmp_path / "prefix"
    (wine / "bin").mkdir(parents=True)
    (wine / "bin" / "wine").write_text("#!/bin/sh\necho wine-11.0\n")
    (wine / "bin" / "wine").chmod(0o755)
    builtin, system32 = wine / "lib" / "wine" / "x86_64-windows", prefix / "drive_c" / "windows" / "system32"
    builtin.mkdir(parents=True)
    system32.mkdir(parents=True)
    for name in recording.LAYER_DLLS:
        (builtin / f"{name}.dll").write_bytes(name.encode())
    (system32 / "d3d12.dll").write_bytes(b"d3d12")
    (prefix / "user.reg").write_text('[Software\\\\Wine\\\\DllOverrides] 1\n"*d3d12"="native,builtin"\n"comctl32"="n"\n'
                                     '[Software\\\\Wine\\\\Other] 2\n"dxgi"="n"\n')
    saved = os.environ.get("WINEDLLOVERRIDES")
    os.environ["WINEDLLOVERRIDES"] = "d3d11=n"
    try:
        one = recording.layer_of(str(wine), str(prefix), "MULLION_DIAG=profile LOG=/tmp/x/log.txt")
        assert one == recording.layer_of(str(wine), str(prefix), "MULLION_DIAG=profile LOG=/tmp/x/log.txt")
    finally:
        os.environ.pop("WINEDLLOVERRIDES") if saved is None else os.environ.update(WINEDLLOVERRIDES=saved)
    assert one["wine"] == "mullion-wine" and one["wine_version"] == "wine-11.0", one
    assert one["overrides"] == {"environment": "d3d11=n;mscoree=;mshtml=", "registry": {"*d3d12": "native,builtin"}}
    assert one["dlls"]["d3d12"]["prefix"]["bytes"] == 5 and one["dlls"]["dxgi"]["prefix"] is None, one["dlls"]
    assert one["program_env"] == "MULLION_DIAG=profile LOG=log.txt" and str(tmp_path) not in json.dumps(one)
    (builtin / "d3d11.dll").write_bytes(b"other build")
    two = recording.layer_of(str(wine), str(prefix))
    assert two["fingerprint"] != one["fingerprint"]
    # Wine's first boot copies its own DLLs into the prefix: the same DLL, so nothing changes
    (system32 / "dxgi.dll").write_bytes(b"dxgi")
    assert recording.layer_of(str(wine), str(prefix))["fingerprint"] == two["fingerprint"]
    (system32 / "dxgi.dll").write_bytes(b"other dxgi")
    three = recording.layer_of(str(wine), str(prefix))
    assert three["fingerprint"] != two["fingerprint"]
    assert recording.layer_change({"layer": two}, {"layer": three}, "a", "b")["differs"] == ["dxgi"]
    (system32 / "dxgi.dll").unlink()
    assert recording.layer_of("native", "-") == {"none": "native Metal, no translation layer", "program_env": ""}
    runs = {"one": one, "one-again": one, "two": two, "native": recording.layer_of("native", "-"), "old": None}
    same = recording.layer_change({"layer": runs["one"]}, {"layer": runs["one-again"]}, "a", "b")
    assert same["same"] and same["differs"] == [] and "program_env" not in same, same
    other = recording.layer_change({"layer": runs["one"]}, {"layer": runs["two"]}, "a", "b")
    assert not other["same"] and other["differs"] == ["d3d11"] and "two layers" in other["note"], other
    assert other["program_env"] == {"a": "MULLION_DIAG=profile LOG=log.txt", "b": ""}
    assert not recording.layer_change({"layer": runs["native"]}, {"layer": runs["one"]}, "a", "b")["same"]
    assert recording.layer_change({}, {"layer": runs["one"]}, "old", "b")["missing_in"] == ["old"]
    assert recording.layer_label(runs["native"]) == "native" and recording.layer_label(one).endswith("mullion-wine wine-11.0")

def test_workloads(tmp_path):
    """workload_fetch keeps an archive whose SHA-256 matches and refuses one that does not or that would extract
    outside its directory; perf_record turns a fetched workload into its program, Wine and arguments."""
    import hashlib
    import tarfile
    from metal_gpu_trace import config, paths, workloads
    source = tmp_path / "src" / "demo"
    source.mkdir(parents=True)
    (source / "demo").write_text("#!/bin/sh\n")
    (source / "demo").chmod(0o755)
    good, evil = tmp_path / "good.tar.gz", tmp_path / "evil.tar.gz"
    with tarfile.open(good, "w:gz") as tar:
        tar.add(source, arcname="demo")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(source / "demo", arcname="../escape")
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/x.tar.gz", "bytes": 1 << 20,
             "dir": "demo", "dim_variable": "DIM", "apis": {"mtl": {"program": "demo", "args": "--mtl", "wine": False},
                                                         "d3d12": {"program": "demo", "args": "--d3d12", "wine": True}}}
    saved = config.WORKLOADS, config.CACHE, workloads.download
    served = {}
    config.CACHE, workloads.download = tmp_path / "cache", lambda url, path, max_bytes: shutil.copy(served["file"], path)
    try:
        for archive, sha, words in ((good, "0" * 64, "does not match"),
                                    (evil, hashlib.sha256(evil.read_bytes()).hexdigest(), "may not be extracted")):
            config.WORKLOADS, served["file"] = {"demo": {**entry, "sha256": sha}}, archive
            try:
                workloads.tool_workload_fetch("demo")
                raise AssertionError(f"{archive.name} must be refused")
            except paths.ToolError as error:
                assert words in str(error), error
            assert not any(p.name.startswith("demo-") for p in config.CACHE.iterdir()), list(config.CACHE.iterdir())
        assert not (tmp_path / "escape").exists()
        config.WORKLOADS, served["file"] = {"demo": {**entry, "sha256": hashlib.sha256(good.read_bytes()).hexdigest()}}, good
        assert workloads.tool_workload_list()["workloads"][0]["fetched"] is False
        try:
            workloads.workload_command("demo", "mtl", None, None, "")
            raise AssertionError("an unfetched workload must fail")
        except paths.ToolError as error:
            assert "workload_fetch" in str(error), error
        assert workloads.tool_workload_fetch("demo")["downloaded"] and not workloads.tool_workload_fetch("demo")["downloaded"]
        program, wine, args, env = workloads.workload_command("demo", "mtl", 20, "/opt/wine", "-x")
        assert program.is_file() and os.access(program, os.X_OK) and wine == "native", program
        assert (args, env) == ("--mtl -x", "DIM=20"), (args, env)
        layer_wine = "native" if sys.platform == "win32" else "/opt/wine"
        assert workloads.workload_command("demo", "d3d12", None, "/opt/wine", "")[1:] == (layer_wine, "--d3d12", "")
        for api in ("vulkan", None):
            try:
                workloads.workload_command("demo", api, None, None, "")
                raise AssertionError(f"api {api} must fail")
            except paths.ToolError as error:
                assert "api is one of mtl, d3d12" in str(error), error
    finally:
        config.WORKLOADS, config.CACHE, workloads.download = saved
    shipped = json.loads((PKG / "data" / "workloads.json").read_text())["workloads"]["drawstress"]
    assert len(shipped["sha256"]) == 64 and shipped["sha256"] != "0" * 64 and shipped["url"].startswith("https://")
    examples = json.loads((PKG / "data" / "workloads.json").read_text())["workloads"]["bgfx-examples"]
    assert "workloads-8" in examples["url"] and len(examples["sha256"]) == 64, "workloads-2's archive has no dxil shaders"

def test_workload_downloads(tmp_path):
    """A workload with `downloads` fetches each zip from its publisher, checks its SHA-512, unzips it with its file modes into
    the workload's folder, refuses a wrong hash, a link or a path outside, and substitutes {dir} in the api's arguments."""
    import hashlib
    import tarfile
    import zipfile
    from metal_gpu_trace import config, paths, recording, workloads
    project = tmp_path / "src" / "godot" / "project"
    project.mkdir(parents=True)
    (project / "project.godot").write_text("x")
    base = tmp_path / "base.tar.gz"
    with tarfile.open(base, "w:gz") as tar:
        tar.add(tmp_path / "src" / "godot", arcname="godot")

    def make_zip(name, members):
        path = tmp_path / name
        with zipfile.ZipFile(path, "w") as zf:
            for member, mode, link in members:
                info = zipfile.ZipInfo(member)
                info.external_attr = ((0o120000 if link else 0o100000) | mode) << 16
                zf.writestr(info, "bin")
        return path
    good = make_zip("good.zip", [("Godot.app/Contents/MacOS/Godot", 0o755, False)])
    sha512 = lambda p: hashlib.sha512(p.read_bytes()).hexdigest()
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/base.tar.gz",
             "sha256": hashlib.sha256(base.read_bytes()).hexdigest(), "bytes": base.stat().st_size, "dir": "godot",
             "downloads": [{"url": "https://example.invalid/g.zip", "sha512": sha512(good), "bytes": good.stat().st_size, "into": "bin"}],
             "apis": {"mtl": {"program": "bin/Godot.app/Contents/MacOS/Godot", "args": "--path {dir}/project", "wine": False}}}
    saved = config.WORKLOADS, config.CACHE, workloads.download
    served = {"https://example.invalid/base.tar.gz": base, "https://example.invalid/g.zip": good}
    config.CACHE, workloads.download = tmp_path / "cache", lambda url, path, max_bytes: shutil.copy(served[url], path)
    try:
        for archive, words in ((make_zip("link.zip", [("a", 0o777, True)]), "may not be extracted"),
                               (make_zip("up.zip", [("../escape", 0o644, False)]), "may not be extracted"),
                               (good, "does not match the SHA-512")):
            served["https://example.invalid/g.zip"] = archive
            config.WORKLOADS = {"demo": {**entry, "downloads": [{**entry["downloads"][0], "sha512": sha512(good) if words.startswith("may") else "0" * 128}]}}
            if words.startswith("may"):
                config.WORKLOADS["demo"]["downloads"][0]["sha512"] = sha512(archive)
            try:
                workloads.tool_workload_fetch("demo")
                raise AssertionError(f"{archive.name} must be refused")
            except paths.ToolError as error:
                assert words in str(error), error
            assert not any(p.name.startswith("demo-") for p in config.CACHE.iterdir()), list(config.CACHE.iterdir())
        assert not (tmp_path / "escape").exists()
        served["https://example.invalid/g.zip"] = good
        config.WORKLOADS = {"demo": entry}
        assert workloads.tool_workload_fetch("demo")["bytes"] == entry["bytes"] + good.stat().st_size
        assert workloads.tool_workload_list()["workloads"][0]["bytes"] == entry["bytes"] + good.stat().st_size
        program, wine, args, env = workloads.workload_command("demo", "mtl", None, None, "")
        assert program.is_file() and os.access(program, os.X_OK), "the zip's file mode must survive"
        assert recording.split_args(args) == ["--path", f"{program.parents[4]}/project"], (args, program)
        config.CACHE = tmp_path / "a cache with spaces"
        assert workloads.tool_workload_fetch("demo")["downloaded"]
        spaced = recording.split_args(workloads.workload_command("demo", "mtl", None, None, "")[2])
        assert len(spaced) == 2 and "a cache with spaces" in spaced[1], spaced
    finally:
        config.WORKLOADS, config.CACHE, workloads.download = saved

def test_example_traits(tmp_path):
    """Every shipped example has a class and the native encoder count measured for it, and workload_list shows them."""
    from metal_gpu_trace import workloads
    listed = {w["name"]: w for w in workloads.tool_workload_list()["workloads"]}["bgfx-examples"]
    assert set(listed["example_traits"]) == set(listed["examples"]), listed
    for name, traits in listed["example_traits"].items():
        assert traits["class"] in {"cpu_submit", "textured", "postprocess", "gpu_bandwidth", "compute", "gpu_alu",
                                   "streaming", "indirect", "ui_text", "shadows", "overdraw", "readback", "upscale",
                                   "format_coverage", "geometry", "multi_surface", "occlusion", "offscreen"}, name
        assert traits["native_encoders_per_frame"] > 0 and traits["d3d12_encoders_per_frame"] > 0, name

@macos_only
def test_overrun(tmp_path):
    """A recording that overruns its deadline is stopped, leaves no files and no lock behind and names the likely
    cause (a hidden window: the program renders unpaced and Instruments takes minutes to close the data), and the deadline
    covers a 30 s Wine D3D12 recording (more than 407 s in all on an M1 Pro) and reading back a 60 s one."""
    from metal_gpu_trace import config, paths, recording
    assert recording.deadline(30) > 407 and recording.deadline(60) > 87 * 6
    stubs, out = tmp_path / "stubs", tmp_path / "overrun"
    stubs.mkdir()
    out.mkdir()
    # an xctrace that starts its .trace and never finishes
    xcrun = stubs / "xcrun"
    xcrun.write_text("#!/bin/zsh\nwhile [[ $1 != --output ]]; do shift; done\nmkdir -p $2\nsleep 60\n")
    xcrun.chmod(0o755)
    program = unique_program(tmp_path, "hang")
    saved = config.OUT, recording.deadline, os.environ["PATH"]
    config.OUT, recording.deadline = out, lambda seconds: 3
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    try:
        recording.tool_perf_record("hang", str(program), seconds=1, wine="native")
        raise AssertionError("an overrunning recording must fail")
    except paths.ToolError as error:
        assert "stopped" in str(error) and "window visible" in str(error), error
    finally:
        config.OUT, recording.deadline, os.environ["PATH"] = saved
    assert not list(out.iterdir()), list(out.iterdir())

@macos_only
def test_overrun_removes_lock_with_pid(tmp_path):
    """The server's one lock for every recordings folder (config.LOCK, given to perf_record.sh as PERF_LOCK, its folder
    created) is taken during a recording, and removed with its pid file when the recording overruns."""
    from metal_gpu_trace import config, paths, recording
    stubs, out, program = hang_stubs(tmp_path)
    (stubs / "xcrun").write_text("#!/bin/zsh\ntest -s $PERF_LOCK/pid || exit 9\n"
                                 "while [[ $1 != --output ]]; do shift; done\nmkdir -p $2\nsleep 60\n")
    saved = config.OUT, recording.deadline, os.environ["PATH"], config.LOCK
    config.OUT, recording.deadline, config.LOCK = out, lambda seconds: 3, tmp_path / "cache" / "recording.lock"
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    try:
        recording.tool_perf_record("hang", str(program), seconds=1, wine="native")
        raise AssertionError("an overrunning recording must fail")
    except paths.ToolError as error:
        assert "stopped" in str(error), error
    finally:
        config.OUT, recording.deadline, os.environ["PATH"], config.LOCK = saved
    assert not list(out.iterdir()), list(out.iterdir())
    assert (tmp_path / "cache").is_dir() and not (tmp_path / "cache" / "recording.lock").exists()

@macos_only
def test_stale_lock_macos(tmp_path):
    """A .recording lock whose pid is dead is taken over by the next recording; one whose pid is alive still refuses."""
    stubs, out = tmp_path / "stubs", tmp_path / "runs"
    stubs.mkdir()
    out.mkdir()
    (stubs / "xcrun").write_text(f"#!/bin/zsh\ntouch {tmp_path}/xctrace-ran\n"
                                 "while [[ $1 != --output ]]; do shift; done\nmkdir -p $2\n")
    (stubs / "pkill").write_text("#!/bin/zsh\nexit 1\n")
    program = unique_program(tmp_path, "stale")
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    env = dict(os.environ, PERF_OUT=str(out), PERF_LOCK=str(out / ".recording"), PERF_MIN_FREE_GB="0",
               PATH=f"{stubs}:{os.environ['PATH']}")

    def record():
        return subprocess.run(["zsh", str(PKG / "perf_record.sh"), "stale", "1", "native", "-", str(tmp_path), str(program)],
                              env=env, capture_output=True, text=True, timeout=60)
    dead = subprocess.Popen(["true"])
    dead.wait()
    lock = out / ".recording"
    lock.mkdir()
    (lock / "pid").write_text(f"{dead.pid}\n")
    proc = record()
    assert (tmp_path / "xctrace-ran").exists() and "another recording" not in proc.stderr, proc
    assert not lock.exists(), "the recording that took the lock frees it"
    lock.mkdir()
    (lock / "pid").write_text(f"{os.getpid()}\n")  # alive: this test's own process
    proc = record()
    assert proc.returncode == 3 and "another recording is running" in proc.stderr, proc
    assert (lock / "pid").read_text().strip() == str(os.getpid()), "a live owner's lock is left alone"
    (lock / "pid").write_text(f"{dead.pid}\n")
    (out / ".recording.takeover").mkdir()  # another recording is taking the dead lock over right now
    proc = record()
    assert proc.returncode == 3 and "another recording is running" in proc.stderr, proc
    assert (lock / "pid").read_text().strip() == str(dead.pid), "only one recording takes a dead lock over"
    assert ".recording.takeover" in proc.stderr, "a takeover lock left by a killed recording is named, to remove"

def test_dir_in_args_quotes_the_folder_and_the_path_after_it_as_one_argument():
    """On Windows "C:\\a b"/project split in two (the folder and /project): the quotes must cover the whole path."""
    from metal_gpu_trace import recording, workloads
    saved = sys.platform
    try:
        sys.platform = "win32"
        text = workloads.dir_in_args("--path {dir}/project --x 1", "C:\\Users\\a b\\godot")
        assert text == '--path "C:\\Users\\a b\\godot/project" --x 1', text
        assert recording.split_args(text) == ["--path", "C:\\Users\\a b\\godot/project", "--x", "1"]
        sys.platform = "linux"
        text = workloads.dir_in_args("--path {dir}/project --x 1", "/tmp/a b/godot")
        assert recording.split_args(text) == ["--path", "/tmp/a b/godot/project", "--x", "1"], text
        assert workloads.dir_in_args("{dir}", "/tmp/g") == "/tmp/g" and workloads.dir_in_args("--no-dir", "/x") == "--no-dir"
        two = workloads.dir_in_args("--a {dir}/x,{dir}/y", "/tmp/a b")  # each {dir} and its path, none left over
        assert "{dir}" not in two and recording.split_args(two) == ["--a", "/tmp/a b/x,/tmp/a b/y"], two
    finally:
        sys.platform = saved


def test_a_windows_recording_reaches_the_windows_engine_whatever_was_imported_first(tmp_path):
    """recording imported its Windows engine only when it was first imported on Windows; a module first imported under
    another platform (as a test run does) then failed with a NameError on the first Windows recording."""
    from metal_gpu_trace import config, paths, perf_record_windows, recording
    saved = sys.platform, config.OUT, perf_record_windows.record_windows
    asked = []

    def engine(*args, **kwargs):
        asked.append(args[0])
        raise RuntimeError("engine reached")
    try:
        sys.platform, config.OUT, perf_record_windows.record_windows = "win32", tmp_path, engine
        recording.__dict__.pop("perf_record_windows", None)  # as if the module had been imported on another platform
        try:
            recording.record_run("w", 1, "native", "-", str(tmp_path), ["prog"])
            raise AssertionError("the engine's error must reach the caller")
        except paths.ToolError as error:
            assert "engine reached" in str(error), error
    finally:
        sys.platform, config.OUT, perf_record_windows.record_windows = saved
    assert asked == ["w"]


def stubborn_pair(tmp_path):
    """Returns (program, bystander): a built program that ignores SIGTERM, under a name only this test uses (8 random
    hex digits keep it within the 15 characters a process name keeps), and another process of that name already
    running, which no stop may touch."""
    from support import pids_named, stubborn_program, wait_until
    program = stubborn_program(tmp_path / f"ig-{secrets.token_hex(4)}")
    bystander = subprocess.Popen([str(program)], start_new_session=True)
    wait_until(lambda: pids_named(program.name) == [bystander.pid])
    return program, bystander


def stop_all(program, *procs):
    """Kills every process left of `program` (the test's own name) and reaps `procs`."""
    subprocess.run(["pkill", "-KILL", "-x", program.name], capture_output=True)
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def test_kill_program_and_watchdog(tmp_path):
    """kill_program ends a process group that ignores SIGTERM, and is harmless on one that is gone; perf_record.sh
    stops its recording, frees its lock and stops the program it launched (with its child), and no other process of
    that name, when the server named in PERF_PARENT_PID dies."""
    import time
    from metal_gpu_trace import recording
    from support import pids_named, wait_until
    stubs, out, _ = hang_stubs(tmp_path)
    program, bystander = stubborn_pair(tmp_path)
    target = subprocess.Popen([str(program)], start_new_session=True)  # leads its own group, as xctrace's launch
    wait_until(lambda: len(pids_named(program.name)) == 2)
    recording.kill_program(target.pid)
    assert target.wait(timeout=15) is not None, "kill_program must escalate to SIGKILL"
    recording.kill_program(target.pid)  # gone: a repeated stop raises nothing
    assert bystander.poll() is None, "kill_program must stop its group only"
    # the recording's parent dies: the script must exit, free its lock and stop the program it launched
    parent = subprocess.Popen(["sleep", "60"])
    # PERF_MIN_FREE_GB=0: the disk check needs 26 GB for 30 s, and a CI runner's free space varies
    env = dict(os.environ, PERF_OUT=str(out), PERF_LOCK=str(out / ".recording"), PERF_PARENT_PID=str(parent.pid),
               PERF_MIN_FREE_GB="0",
               PATH=f"{stubs}:{os.environ['PATH']}")
    logfile = tmp_path / "script.log"  # a file, not a pipe: the stub's orphaned sleep would hold a pipe open
    script = subprocess.Popen(["zsh", str(PKG / "perf_record.sh"), "orphan", "30", "native", "-", str(tmp_path),
                               str(program), "fork"], env=env, stdout=open(logfile, "w"), stderr=subprocess.STDOUT,
                              start_new_session=True)
    try:
        deadline = time.time() + 40
        while not (out / ".recording" / "program").is_file() and time.time() < deadline:
            time.sleep(0.2)
        assert (out / ".recording" / "program").is_file(), (
            f"the launched program was never found; the script's exit code is {script.poll()} "
            f"and its output {logfile.read_text()[-600:]!r}")
        wait_until(lambda: len(pids_named(program.name)) == 3)  # the bystander, the program and its child
        parent.kill()
        parent.wait()
        script.wait(timeout=30)
        wait_until(lambda: pids_named(program.name) == [bystander.pid], timeout=15)
    finally:
        stop_all(program, script, bystander)
        subprocess.run(["pkill", "-f", str(PKG / "perf_record.sh")], capture_output=True)
    assert not list(out.iterdir()), f"the lock and the partial files must go: {list(out.iterdir())} {logfile.read_text()[-400:]!r}"


def test_cancel_stops_only_the_launched_program(tmp_path):
    """A cancelled native recording stops the program it launched and that program's child, even though they ignore
    SIGTERM, and leaves alone another process with the same name (pkill -x killed it too)."""
    import threading
    from metal_gpu_trace import config, paths, recording
    from support import pids_named
    stubs, out, _ = hang_stubs(tmp_path)
    program, bystander = stubborn_pair(tmp_path)
    cancel = threading.Event()
    saved = config.OUT, config.PROGRESS_TICKS, os.environ["PATH"]
    config.OUT, config.PROGRESS_TICKS = out, 1
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    ticks = []

    def tick(*_):
        """Cancels once the launched program and its child run beside the bystander and the script has found them
        (or 10 s on, should it never find them)."""
        ticks.append(1)
        if len(pids_named(program.name)) == 3 and ((config.LOCK / "program").is_file() or len(ticks) > 10):
            cancel.set()
    recording.RUN.cancel, recording.RUN.progress = cancel, tick
    try:
        recording.tool_perf_record("cancel", str(program), seconds=20, wine="native", args="fork")
        raise AssertionError("a cancelled recording must fail")
    except paths.ToolError as error:
        assert "cancelled" in str(error), error
        assert bystander.poll() is None, "another process with the program's name must keep running"
        assert pids_named(program.name) == [bystander.pid], "the launched program and its child must be stopped"
    finally:
        config.OUT, config.PROGRESS_TICKS, os.environ["PATH"] = saved
        recording.RUN.cancel = recording.RUN.progress = None
        stop_all(program, bystander)
    assert not list(out.iterdir()), list(out.iterdir())


def test_recording_end_stops_only_the_launched_program(tmp_path):
    """When xctrace returns, perf_record.sh stops what is left of the program it launched (its child here) and
    nothing else of that name."""
    from support import pids_named
    stubs, out, _ = hang_stubs(tmp_path)
    xcrun = stubs / "xcrun"  # an xctrace that ends after 3 s, its program still running, with an empty trace
    xcrun.write_text(xcrun.read_text().replace("sleep 60", "sleep 3"))
    program, bystander = stubborn_pair(tmp_path)
    env = dict(os.environ, PERF_OUT=str(out), PERF_LOCK=str(out / ".recording"), PERF_MIN_FREE_GB="0",
               PATH=f"{stubs}:{os.environ['PATH']}")
    try:
        proc = subprocess.run(["zsh", str(PKG / "perf_record.sh"), "end", "1", "native", "-", str(tmp_path),
                               str(program), "fork"], env=env, capture_output=True, text=True, timeout=60)
        assert proc.returncode, proc  # the empty trace has nothing to read back
        assert bystander.poll() is None, "another process with the program's name must keep running"
        assert pids_named(program.name) == [bystander.pid], "the launched program and its child must be stopped"
    finally:
        stop_all(program, bystander)


def test_cancelled_attach_leaves_the_program_running(tmp_path):
    """Cancelling perf_attach stops the recording only: the program it attached to keeps running."""
    import threading
    from metal_gpu_trace import config, paths, recording
    stubs, out, _ = hang_stubs(tmp_path)
    program, running = stubborn_pair(tmp_path)
    cancel = threading.Event()
    saved = config.OUT, config.PROGRESS_TICKS, os.environ["PATH"]
    config.OUT, config.PROGRESS_TICKS = out, 1
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    recording.RUN.cancel, recording.RUN.progress = cancel, lambda done, *a: done > 0 and cancel.set()
    try:
        recording.tool_perf_attach("attach", running.pid, seconds=20)
        raise AssertionError("a cancelled recording must fail")
    except paths.ToolError as error:
        assert "cancelled" in str(error), error
        assert running.poll() is None, "the attached program must keep running"
    finally:
        config.OUT, config.PROGRESS_TICKS, os.environ["PATH"] = saved
        recording.RUN.cancel = recording.RUN.progress = None
        stop_all(program, running)

def test_script_failure_cleanup(tmp_path):
    """perf_record.sh frees its lock and deletes its partial files when a recording fails, and refuses a program that
    is not an executable file before it starts Instruments."""
    stubs, out = tmp_path / "stubs", tmp_path / "runs"
    stubs.mkdir()
    out.mkdir()
    xcrun = stubs / "xcrun"  # an xctrace that fails at once
    xcrun.write_text("#!/bin/zsh\nexit 1\n")
    xcrun.chmod(0o755)
    program, text = unique_program(tmp_path), tmp_path / "notes.txt"
    text.write_text("x")
    env = dict(os.environ, PERF_OUT=str(out), PERF_LOCK=str(out / ".recording"), PERF_MIN_FREE_GB="0",
               PATH=f"{stubs}:{os.environ['PATH']}")

    def run(path):
        return subprocess.run(["zsh", str(PKG / "perf_record.sh"), "f", "2", "native", "-", str(tmp_path), str(path)],
                              capture_output=True, text=True, env=env, timeout=60)
    failed = run(program)
    assert failed.returncode == 1 and "no recording" in failed.stderr, failed
    assert not list(out.iterdir()), f"a failed recording left {list(out.iterdir())}"
    empty = tmp_path / "empty"  # the execute bit, but no program inside
    empty.touch()
    empty.chmod(0o755)
    refused = run(empty)
    assert refused.returncode == 2 and "not a program the system can run" in refused.stderr, refused
    assert not list(out.iterdir())
    for bad in (text, tmp_path, tmp_path / "missing"):
        refused = run(bad)
        assert refused.returncode == 2 and "not an executable file" in refused.stderr, (bad, refused)
        assert str(tmp_path) not in refused.stderr, "the error must not carry a local path"
    assert not list(out.iterdir())

def test_moltenvk(tmp_path):
    """api vk needs METAL_TRACE_MOLTENVK (a directory with libMoltenVK.dylib and no spaces), runs the program with
    DYLD_LIBRARY_PATH set to it, and names MoltenVK as the layer without a local path, so perf_compare tells a
    MoltenVK run from a native Metal run."""
    from metal_gpu_trace import config, paths, recording, workloads
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/x.tar.gz", "bytes": 1,
             "sha256": "0" * 64, "dir": "demo", "dim_variable": "DIM",
             "apis": {"mtl": {"program": "demo", "args": "--mtl", "wine": False},
                      "vk": {"program": "demo", "args": "--vk", "wine": False, "moltenvk": True}}}
    cache = tmp_path / "cache"
    (cache / ("demo-" + "0" * 12) / "demo").mkdir(parents=True)
    (cache / ("demo-" + "0" * 12) / "demo" / "demo").write_text("#!/bin/sh\n")
    lib, spaced = tmp_path / "mvk", tmp_path / "with space"
    lib.mkdir()
    spaced.mkdir()
    (lib / "libMoltenVK.dylib").write_bytes(b"fake")
    (spaced / "libMoltenVK.dylib").write_bytes(b"fake")
    saved = config.WORKLOADS, config.CACHE, recording.record, os.environ.get("METAL_TRACE_MOLTENVK")
    config.WORKLOADS, config.CACHE = {"demo": entry}, cache
    seen = {}
    recording.record = lambda *args, **kw: seen.update(args=args, kw=kw) or {}

    def refused(path, words):
        os.environ.pop("METAL_TRACE_MOLTENVK", None) if path is None else os.environ.__setitem__("METAL_TRACE_MOLTENVK", str(path))
        try:
            workloads.workload_command("demo", "vk", None, None, "")
            raise AssertionError(f"{path} must be refused")
        except paths.ToolError as error:
            assert words in str(error) and str(tmp_path) not in str(error), error
    try:
        refused(None, "set METAL_TRACE_MOLTENVK")
        refused(tmp_path, "holds no libMoltenVK.dylib")
        refused(spaced, "spaces")
        os.environ["METAL_TRACE_MOLTENVK"] = str(lib)
        program, wine, args, env = workloads.workload_command("demo", "vk", 20, None, "-x")
        assert wine == "native" and args == "--vk -x" and env == f"DIM=20 DYLD_LIBRARY_PATH={lib.resolve()}", (wine, args, env)
        layer = workloads.workload_layer("demo", "vk", 20)
        assert layer["moltenvk"] and len(layer["dylib"]["sha256"]) == 64 and layer["program_env"] == "DIM=20", layer
        assert str(tmp_path) not in json.dumps(layer), "the layer must not carry a local path"
        assert workloads.workload_layer("demo", "mtl", 20) is None
        recording.tool_perf_record("v", workload="demo", api="vk", seconds=5)
        assert seen["kw"]["layer"]["moltenvk"] and "DYLD_LIBRARY_PATH=" in seen["args"][6], seen
        recording.tool_perf_record("m", workload="demo", api="mtl", seconds=5)
        assert seen["kw"]["layer"] is None
    finally:
        config.WORKLOADS, config.CACHE, recording.record = saved[:3]
        os.environ.pop("METAL_TRACE_MOLTENVK", None) if saved[3] is None else os.environ.__setitem__("METAL_TRACE_MOLTENVK", saved[3])
    vk, vk2 = {"layer": layer}, {"layer": {**layer}}
    native = {"layer": {"none": "native Metal, no translation layer", "program_env": "DIM=20"}}
    assert recording.layer_label(layer).startswith("moltenvk ") and len(recording.layer_label(layer)) == 21
    assert recording.layer_change(native, vk, "a", "b")["same"] is False
    assert recording.layer_change(vk, vk2, "a", "b")["same"] is True
    assert "vk" in json.loads((PKG / "data" / "workloads.json").read_text())["workloads"]["drawstress"]["apis"]

def test_pack_examples(tmp_path):
    """pack-examples.sh puts both binaries and only the named assets in one flat folder, and fails when one is missing."""
    bgfx, out = tmp_path / "bgfx", tmp_path / "out"
    runtime = bgfx / "examples" / "runtime"
    for folder in ("shaders/metal", "shaders/dxbc", "shaders/dxil", "shaders/glsl", "textures", "meshes", "font", "images", "text"):
        (runtime / folder).mkdir(parents=True)
    for asset in ("shaders/metal/vs.bin", "shaders/dxbc/vs.bin", "shaders/dxil/vs.bin", "shaders/glsl/vs.bin", "textures/uffizi.ktx",
                  "textures/other.dds", "meshes/bunny.bin", "meshes/other.bin"):
        (runtime / asset).write_text("x")
    for path in ("osx-arm64/bin/examples.app/Contents/MacOS/examplesRelease",
                 "win64_mingw-gcc/bin/examples.app/Contents/MacOS/examplesRelease.exe"):
        (bgfx / ".build" / path).parent.mkdir(parents=True)
        (bgfx / ".build" / path).write_text("bin")
    script = str(ROOT / "workloads" / "pack-examples.sh")
    result = subprocess.run(["sh", script, str(bgfx), str(out)], capture_output=True, text=True)
    assert result.returncode, "a missing asset (fieldstone, meshes) must fail the script"
    for asset in ("textures/fieldstone-n.dds", "textures/fieldstone-rgba.dds", "meshes/column.bin", "meshes/cube.bin",
                  "meshes/hollowcube.bin", "meshes/orb.bin", "meshes/tree.bin", "meshes/unit_sphere.bin",
                  "textures/8k_mars.jpg", "textures/particle.ktx", "textures/figure-rgba.dds", "textures/flare.dds",
                  "textures/pf_alpha_test.dds", "textures/pf_uv_filtering_test.dds", "images/blender_icons16.png",
                  "textures/texture_compression_bc1.ktx", "textures/texture_compression_astc_4x4.dds", "font/droidsans.ttf",
                  "font/five_minutes.otf", "images/image1.jpg", "images/image12.jpg", "meshes/bunny_decimated.bin",
                  "textures/parallax-d.ktx", "textures/parallax-h.ktx", "textures/parallax-n.ktx", "textures/dmap.png",
                  "text/sherlock_holmes_a_scandal_in_bohemia_arthur_conan_doyle.txt"):
        (runtime / asset).write_text("x")
    shutil.rmtree(out)
    result = subprocess.run(["sh", script, str(bgfx), str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    packed = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    assert "examples" in packed and "examples.exe" in packed and "shaders/metal/vs.bin" in packed, packed
    assert "shaders/dxbc/vs.bin" in packed and "shaders/dxil/vs.bin" in packed, "Direct3D 11 reads dxbc and 12 reads dxil"
    assert "shaders/glsl/vs.bin" not in packed and "textures/other.dds" not in packed and "meshes/other.bin" not in packed, packed
    assert (out / "temp").is_dir(), "40-svt crashes without a temp folder"
    for kept in ("textures/8k_mars.jpg", "textures/texture_compression_bc1.ktx", "textures/texture_compression_astc_4x4.dds",
                 "font/droidsans.ttf", "font/five_minutes.otf", "images/blender_icons16.png", "images/image1.jpg",
                 "images/image12.jpg", "textures/dmap.png", "meshes/bunny_decimated.bin",
                 "text/sherlock_holmes_a_scandal_in_bohemia_arthur_conan_doyle.txt"):
        assert kept in packed, kept

def test_workload_example(tmp_path):
    """A workload with `examples` needs one named, and its argument follows the api's arguments."""
    from metal_gpu_trace import config, paths, registry, workloads
    entry = {"title": "t", "about": "a", "license": "l", "url": "https://example.invalid/x.tar.gz", "bytes": 1,
             "sha256": "0" * 64, "dir": "demo", "dim_variable": "DIM",
             "examples": {"21-deferred": "21-", "01-cubes": "01-"},
             "apis": {"mtl": {"program": "demo", "args": "--mtl", "wine": False}}}
    plain = {k: v for k, v in entry.items() if k != "examples"}
    saved = config.WORKLOADS, config.CACHE
    config.CACHE = tmp_path
    try:
        config.WORKLOADS = {"demo": entry, "plain": plain}
        for name in ("demo", "plain"):
            (tmp_path / f"{name}-{'0' * 12}").mkdir()
        assert workloads.workload_command("demo", "mtl", None, None, "-x", example="21-deferred")[2] == "--mtl 21- -x"
        for name, example, words in (("demo", None, "example is one of 21-deferred, 01-cubes"),
                                     ("demo", "nope", "example is one of 21-deferred, 01-cubes"),
                                     ("plain", "21-deferred", "takes no example")):
            try:
                workloads.workload_command(name, "mtl", None, None, "", example=example)
                raise AssertionError(f"{name} with example {example} must fail")
            except paths.ToolError as error:
                assert words in str(error), error
        assert workloads.workload_command("plain", "mtl", None, None, "")[2] == "--mtl"
        no_dim = {k: v for k, v in entry.items() if k != "dim_variable"}
        config.WORKLOADS = {"demo": no_dim}
        try:
            workloads.workload_command("demo", "mtl", 20, None, "", example="01-cubes")
            raise AssertionError("dim on a workload without dim_variable must fail")
        except paths.ToolError as error:
            assert "dim does not apply to demo" in str(error), error
        assert workloads.workload_command("demo", "mtl", None, None, "", example="01-cubes")[3] == ""
        config.WORKLOADS = {"demo": entry, "plain": plain}
        assert workloads.tool_workload_list()["workloads"][0]["examples"] == ["21-deferred", "01-cubes"]
    finally:
        config.WORKLOADS, config.CACHE = saved
    assert registry.RECORD_PROPS["example"]["type"] == "string"


def test_daemon_candidates():
    """The Windows recorder looks for vegaflow_daemon.exe in build/ beside the clone and beside its parent, wherever
    the server was started from (the paths it used before the code moved into src/)."""
    from metal_gpu_trace import perf_record_windows as prw
    exe = "vegaflow_daemon.exe"
    expected = [pathlib.Path("..") / "build" / exe, pathlib.Path("build") / exe, ROOT.parent / "build" / exe,
                ROOT / "build" / exe]
    saved = os.environ.pop("METAL_TRACE_DAEMON_NAMES", None)  # a name set in the environment would add candidates
    try:
        assert prw.daemon_candidates() == expected, prw.daemon_candidates()
        assert prw.daemon_candidates("x.exe")[0] == pathlib.Path("x.exe")
    finally:
        if saved is not None:
            os.environ["METAL_TRACE_DAEMON_NAMES"] = saved


def test_record_new_summary(tmp_path):
    """record_new_summary records with perf_record and returns the name and the summary of the run that recording
    wrote, not of an older run with the same label."""
    from metal_gpu_trace import config, paths, recording
    (tmp_path / "x_old.json").write_text('{"old": true}')

    def fake_record(label, **record):
        (tmp_path / f"{label}_new.json").write_text(json.dumps({"seen": record}))
    saved = recording.tool_perf_record, config.OUT
    recording.tool_perf_record, config.OUT = fake_record, tmp_path
    try:
        assert recording.record_new_summary("x", seconds=3) == ("x_new", {"seen": {"seconds": 3}})
        recording.tool_perf_record = lambda label, **record: None
        try:
            recording.record_new_summary("x")
            raise AssertionError("a recording that wrote no summary must fail")
        except paths.ToolError as error:
            assert "no summary" in str(error), error
    finally:
        recording.tool_perf_record, config.OUT = saved


def test_free_lock_only_frees_its_own(tmp_path):
    """A stopped recording frees the .recording lock only when the lock holds its own pid: another recording's lock,
    or one whose owner did not write its pid yet, is left alone."""
    from metal_gpu_trace import config, recording
    saved, config.LOCK = config.LOCK, tmp_path / "recording.lock"
    try:
        lock = tmp_path / "recording.lock"
        lock.mkdir()
        (lock / "pid").write_text("111\n")
        recording.free_lock(222)
        assert (lock / "pid").read_text() == "111\n", "another recording's lock stays"
        recording.free_lock(111)
        assert not lock.exists()
        lock.mkdir()
        recording.free_lock(111)
        assert lock.exists(), "a lock without a pid file may belong to a recording that is starting"
        recording.free_lock(111)  # no error when there is nothing to free
    finally:
        config.LOCK = saved


@macos_only
def test_takeover_rechecks_the_owner(tmp_path):
    """The takeover reads the owner again once it holds .recording.takeover: an owner seen dead before and alive after
    (another recording took the lock in between) keeps its lock, and this recording refuses with exit 3."""
    stubs, out = tmp_path / "stubs", tmp_path / "runs"
    stubs.mkdir()
    out.mkdir()
    (stubs / "xcrun").write_text(f"#!/bin/zsh\ntouch {tmp_path}/xctrace-ran\n")
    (stubs / "ps").write_text(f"#!/bin/zsh\nn=$(cat {tmp_path}/ps-calls 2>/dev/null || echo 0)\n"
                              f"echo $((n + 1)) > {tmp_path}/ps-calls\n(( n >= 1 ))\n")  # dead first, alive after
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    lock = out / ".recording"
    lock.mkdir()
    (lock / "pid").write_text("4242\n")
    env = dict(os.environ, PERF_OUT=str(out), PERF_LOCK=str(out / ".recording"), PERF_MIN_FREE_GB="0",
               PATH=f"{stubs}:{os.environ['PATH']}")
    program = unique_program(tmp_path, "recheck")
    proc = subprocess.run(["zsh", str(PKG / "perf_record.sh"), "recheck", "1", "native", "-", str(tmp_path), str(program)],
                          env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 3 and "another recording is running" in proc.stderr, proc
    assert (lock / "pid").read_text() == "4242\n" and not (tmp_path / "xctrace-ran").exists()
    assert not (out / ".recording.takeover").exists(), "the takeover lock is released"


def prune_folder(tmp_path):
    """Writes two recordings plus baselines.json and panel.json, the last two the oldest, and returns the folder."""
    out = tmp_path / "runs"
    out.mkdir()
    for age, name in enumerate(("baselines.json", "panel.json", "old.json", "old.frames.csv.gz", "new.json")):
        (out / name).write_text("{}")
        os.utime(out / name, (1_000_000 + age * 100, 1_000_000 + age * 100))
    return out


@macos_only
def test_prune_keeps_baselines_and_panel_layout(tmp_path):
    out = prune_folder(tmp_path)
    subprocess.run(["zsh", str(PKG / "prune_runs.sh"), str(out), "1"], check=True)
    assert sorted(p.name for p in out.iterdir()) == ["baselines.json", "new.json", "panel.json"]


def test_windows_prune_never_removes_a_trace(tmp_path):
    from metal_gpu_trace import perf_record_windows
    out = prune_folder(tmp_path)
    (out / "old.trace").write_text("x")
    perf_record_windows.clean_runs(out, 1)
    assert (out / "old.trace").exists() and not (out / "old.json").exists()


def test_windows_prune_keeps_baselines_and_panel_layout(tmp_path):
    from metal_gpu_trace import perf_record_windows
    out = prune_folder(tmp_path)
    perf_record_windows.clean_runs(out, 1)
    assert sorted(p.name for p in out.iterdir()) == ["baselines.json", "new.json", "panel.json"]


@macos_only
def test_prune_refuses_a_keep_that_is_not_a_whole_number(tmp_path):
    out = prune_folder(tmp_path)
    for keep in ("0", "abc", ""):
        proc = subprocess.run(["zsh", str(PKG / "prune_runs.sh"), str(out), keep], capture_output=True, text=True)
        assert proc.returncode == 2 and "keep" in proc.stderr, keep
    assert len(list(out.iterdir())) == 5


@macos_only
def test_keep_runs_after_a_recording_keeps_baselines_and_panel_layout(tmp_path):
    """perf_record.sh prunes through prune_runs.sh once its summary is written: KEEP_RUNS=1 leaves the new recording,
    baselines.json and panel.json."""
    out = prune_folder(tmp_path)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "xcrun").write_text("#!/bin/zsh\nwhile [[ $1 != --output ]]; do shift; done\nmkdir -p $2\n")
    (stubs / "python3").write_text('#!/bin/zsh\nwhile [[ $1 != --label ]]; do shift; done\necho "{}" > $4/$2.json\n')
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    program = unique_program(tmp_path, "kept")
    env = dict(os.environ, PERF_OUT=str(out), PERF_MIN_FREE_GB="0", KEEP_RUNS="1",
               PATH=f"{stubs}:{os.environ['PATH']}")
    proc = subprocess.run(["zsh", str(PKG / "perf_record.sh"), "kept", "1", "native", "-", str(tmp_path), str(program)],
                          env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc
    left = {p.name for p in out.iterdir()}
    assert {"baselines.json", "panel.json"} <= left and not any(n.startswith("old.") for n in left), left
    assert len([n for n in left if n.startswith("kept_") and n.endswith(".json")]) == 1, left


def test_tests_never_take_the_users_recording_lock():
    from metal_gpu_trace import config
    assert config.LOCK.parent != config.CACHE and "metal-gpu-trace-tests-" in str(config.LOCK), config.LOCK


@macos_only
def test_script_takes_the_shared_lock_by_default(tmp_path):
    """Run by hand, without PERF_LOCK, perf_record.sh takes the same lock in the user's cache as the MCP server, so a
    recording by hand and one by the server exclude each other whatever their folders."""
    stubs, out, home = tmp_path / "stubs", tmp_path / "runs", tmp_path / "home"
    stubs.mkdir()
    lock = home / "Library" / "Caches" / "metal-gpu-trace" / "recording.lock"
    (stubs / "xcrun").write_text(f"#!/bin/zsh\ntest -s {lock}/pid && touch {tmp_path}/locked\nexit 1\n")
    (stubs / "xcrun").chmod(0o755)
    program = unique_program(tmp_path, "byhand")
    env = {k: v for k, v in os.environ.items() if k != "PERF_LOCK"}
    env.update(PERF_OUT=str(out), PERF_MIN_FREE_GB="0", HOME=str(home), PATH=f"{stubs}:{os.environ['PATH']}")
    subprocess.run(["zsh", str(PKG / "perf_record.sh"), "byhand", "1", "native", "-", str(tmp_path), str(program)],
                   env=env, capture_output=True, text=True, timeout=60)
    assert (tmp_path / "locked").exists() and not lock.exists() and not (out / ".recording").exists()


@macos_only
def test_recordings_into_two_folders_run_one_at_a_time(tmp_path):
    from metal_gpu_trace import config, paths, recording
    stubs, out, program = hang_stubs(tmp_path)
    lock = tmp_path / "cache" / "recording.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(f"{os.getpid()}\n")  # another project's recording, alive
    saved = config.OUT, config.LOCK, os.environ["PATH"]
    config.OUT, config.LOCK = out, lock
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    try:
        recording.tool_perf_record("second", str(program), seconds=1, wine="native")
        raise AssertionError("a second recording must wait for the first")
    except paths.ToolError as error:
        assert "another recording is running" in str(error), error
    finally:
        config.OUT, config.LOCK, os.environ["PATH"] = saved
    assert (lock / "pid").exists() and not list(out.glob("second_*"))


def test_lock_path_is_absolute(tmp_path):
    code = "from metal_gpu_trace import config; print(config.LOCK)"
    for given in ("rel/recording.lock", "~/x/recording.lock"):
        env = dict(os.environ, METAL_TRACE_LOCK=given, HOME=str(tmp_path), PYTHONPATH=str(ROOT / "src"))
        got = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True).stdout
        assert pathlib.Path(got.strip()).is_absolute() and "~" not in got, (given, got)


@macos_only
def test_no_gpu_work_is_an_error(tmp_path):
    """A program that ends without any GPU work (Wine failing to start it) is an error that says how it ended and
    after how long, and its empty run is not saved; a run with GPU work is returned as before."""
    from metal_gpu_trace import config, paths, recording
    package, out = tmp_path / "package", tmp_path / "runs"
    package.mkdir()
    out.mkdir()
    script = package / "perf_record.sh"  # writes the summary the real script would, from SUMMARY
    script.write_text('#!/bin/zsh\nprint -r -- "$SUMMARY" > "$PERF_OUT/${1}_1.json"\ntouch "$PERF_OUT/${1}_1.frames.csv"\n')
    empty = {"process": {"name": "wine", "termination-reason": "exit(1)"}, "duration_s": 2.027,
             "gpu": {"intervals": 0, "frames": 0}}
    working = {"process": {"name": "x"}, "duration_s": 20.0, "gpu": {"intervals": 900, "frames": 300}}
    saved = config.PACKAGE_DIR, config.OUT, os.environ.get("SUMMARY")
    config.PACKAGE_DIR, config.OUT = package, out
    try:
        os.environ["SUMMARY"] = json.dumps(empty)
        try:
            recording.record_run("w", 30, "native", "-", str(tmp_path), [str(script)], layer={"none": "x"})
            raise AssertionError("a run without GPU work must fail")
        except paths.ToolError as error:
            assert "exit(1)" in str(error) and "2.0 s" in str(error) and "no GPU work" in str(error), error
        assert not list(out.iterdir()), f"the empty run was kept: {list(out.iterdir())}"
        neighbour = out / "w_1_20261112-101010.json"  # another run whose label starts like this one's file name
        neighbour.write_text("{}")
        (out / "w_1.trace").mkdir()  # the .trace a KEEP_TRACE=1 recording leaves
        os.environ["KEEP_TRACE"] = "1"
        try:
            recording.record_run("w", 30, "native", "-", str(tmp_path), [str(script)], layer={"none": "x"})
            raise AssertionError("a run without GPU work must fail")
        except paths.ToolError as error:
            assert "w_1.trace is kept" in str(error), error
        finally:
            os.environ.pop("KEEP_TRACE")
        assert sorted(p.name for p in out.iterdir()) == ["w_1.trace", "w_1_20261112-101010.json"], list(out.iterdir())
        shutil.rmtree(out / "w_1.trace")
        neighbour.unlink()
        os.environ["SUMMARY"] = json.dumps(working)
        got = recording.record_run("ok", 20, "native", "-", str(tmp_path), [str(script)], layer={"none": "x"})
        assert got["gpu"]["frames"] == 300 and (out / "ok_1.json").exists()
        saved_context = json.loads((out / "ok_1.json").read_text())["context"]
        assert set(saved_context) == {"git", "instruments"} and saved_context == got["context"], saved_context
    finally:
        config.PACKAGE_DIR, config.OUT = saved[0], saved[1]
        os.environ.pop("SUMMARY") if saved[2] is None else os.environ.update(SUMMARY=saved[2])


def test_crossover_version(tmp_path):
    """CrossOver's wine --version prints several "Key: Value" lines: the layer keeps its product name and public
    version on one line; a plain Wine keeps its one line."""
    from metal_gpu_trace import recording
    for printed, expected in (("wine-11.0", "wine-11.0"),
                              ("Product Name: CrossOver\nPublic Version: 26.3.0\nProduct Version: 26.3.0.39832\n"
                               "Build Tag: cxoffice-26.3.0rc2\nBuild Timestamp: 20260715T103801Z", "CrossOver 26.3.0"),
                              ("", None)):
        wine = tmp_path / printed[:4].strip() / "wine-dir"
        (wine / "bin").mkdir(parents=True, exist_ok=True)
        (wine / "bin" / "wine").write_text(f"#!/bin/sh\nprintf '%s\\n' '{printed}'\n" if printed else "#!/bin/sh\n")
        (wine / "bin" / "wine").chmod(0o755)
        assert recording.layer_of(str(wine), str(tmp_path / "prefix"))["wine_version"] == expected, printed


# --- context: where a run came from ---------------------------------------------------------------------------------

def context_with(tmp_path, answers, project=True):
    """Runs recording.run_context with `answers` {first argv word: output or exception} and returns (context, argvs)."""
    from metal_gpu_trace import config, recording
    argvs, envs = [], []

    def read(argv, env=None):
        argvs.append(tuple(argv))
        envs.append(env)
        subcommand = next((w for w in argv if w in ("rev-parse", "status")), None) if argv[0] == "git" else argv[-2]
        answer = answers.get(subcommand, "")
        if isinstance(answer, Exception):
            raise answer
        return answer
    saved = config.PROJECT
    config.PROJECT = {"name": "p", "root": tmp_path} if project else None
    try:
        context_with.envs = envs
        return recording.run_context(read), argvs
    finally:
        config.PROJECT = saved


def test_context_has_the_short_commit_the_dirty_flag_and_instruments(tmp_path):
    answers = {"rev-parse": "abc1234\n", "status": "", "xctrace": "xctrace version 27.2 (27B52)\n"}
    got, _ = context_with(tmp_path, answers)
    assert got == {"git": {"commit": "abc1234", "dirty": False}, "instruments": "27.2 (27B52)"}, got
    answers["status"] = " M src/x.py\n"
    assert context_with(tmp_path, answers)[0]["git"]["dirty"] is True


def test_context_reads_the_project_repo_not_the_working_directory(tmp_path):
    _, argvs = context_with(tmp_path, {"rev-parse": "abc1234", "status": ""})
    git = [a for a in argvs if a[0] == "git"]
    assert git and all(a[:4] == ("git", "--no-optional-locks", "-C", str(tmp_path)) for a in git), argvs
    assert all("--short=12" in a for a in git if "rev-parse" in a), argvs


def test_context_drops_the_git_variables_of_the_environment(tmp_path):
    os.environ["GIT_DIR"], os.environ["GIT_INDEX_FILE"] = "/elsewhere/.git", "/elsewhere/index"
    try:
        context_with(tmp_path, {"rev-parse": "abc1234", "status": ""})
    finally:
        os.environ.pop("GIT_DIR"), os.environ.pop("GIT_INDEX_FILE")
    assert context_with.envs and all(not any(k.startswith("GIT_") for k in env) for env in context_with.envs), context_with.envs


def test_context_without_a_project_file_or_a_repo_has_no_git(tmp_path):
    from subprocess import CalledProcessError
    assert context_with(tmp_path, {}, project=False)[0]["git"] is None
    failing = {"rev-parse": CalledProcessError(128, "git"), "xctrace": OSError("no xctrace")}
    assert context_with(tmp_path, failing)[0] == {"git": None, "instruments": None}


def test_context_names_no_branch_path_or_person(tmp_path):
    answers = {"rev-parse": "abc1234", "status": "", "xctrace": "xctrace version 27.2 (27B52)"}
    got, argvs = context_with(tmp_path, answers)
    text = json.dumps(got)
    assert set(got) == {"git", "instruments"} and set(got["git"]) == {"commit", "dirty"}, got
    assert str(tmp_path) not in text and "branch" not in text and "/" not in text, text
    # the folder under test is named after this test (pytest) and says "branch": only the words git was given count
    assert not any("branch" in word or "--abbrev-ref" in word for argv in argvs for word in argv
                   if str(tmp_path) not in word), argvs


def test_context_change_says_whether_two_runs_share_a_context():
    from metal_gpu_trace import recording
    one = {"context": {"git": {"commit": "abc1234", "dirty": False}, "instruments": "27.2 (27B52)"}}
    two = {"context": {"git": {"commit": "def5678", "dirty": False}, "instruments": "27.2 (27B52)"}}
    assert recording.context_change(one, dict(one), "a", "b") == {"same": True}
    got = recording.context_change(one, two, "a", "b")
    assert got["same"] is False and got["a"] == one["context"] and got["b"] == two["context"], got
    old = recording.context_change(one, {}, "a", "b")
    assert old["missing_in"] == ["b"], old
    nogit = {"context": {"git": None, "instruments": "27.2 (27B52)"}}
    assert recording.context_change(nogit, dict(nogit), "a", "b") == {"same": None, "unknown_in": ["a", "b"]}
    mixed = recording.context_change(one, nogit, "a", "b")
    assert mixed["same"] is False and mixed["unknown_in"] == ["b"], mixed


def test_perf_compare_carries_the_context_change(tmp_path):
    from metal_gpu_trace import analysis, config
    base = {"gpu": {"frames": 300, "fps_estimate": 60.0}}
    git = lambda commit: {"git": {"commit": commit, "dirty": False}, "instruments": None}
    (tmp_path / "a.json").write_text(json.dumps({**base, "context": git("abc1234")}))
    (tmp_path / "b.json").write_text(json.dumps({**base, "context": git("def5678")}))
    (tmp_path / "old.json").write_text(json.dumps(base))
    saved, config.OUT = config.OUT, tmp_path
    try:
        assert analysis.tool_perf_compare("a", "b")["context"]["same"] is False
        assert analysis.tool_perf_compare("a", "a")["context"] == {"same": True}
        assert analysis.tool_perf_compare("a", "old")["context"]["missing_in"] == ["old"]
    finally:
        config.OUT = saved


@macos_only
def test_record_run_prunes_and_notes_it(tmp_path):
    """With METAL_TRACE_MAX_DISK_MB set, record_run removes an older run's .trace to fit, writes what it did into the
    summary (also in the JSON on disk), and leaves the new run's tables; without the limit nothing is removed."""
    from metal_gpu_trace import config, recording
    package, out = tmp_path / "package", tmp_path / "runs"
    package.mkdir()
    out.mkdir()
    script = package / "perf_record.sh"
    script.write_text('#!/bin/zsh\nprint -r -- "$SUMMARY" > "$PERF_OUT/${1}_1.json"\n'
                      'head -c 1048576 /dev/zero > "$PERF_OUT/${1}_1.frames.csv.gz"\n')
    (out / "old_1.trace").write_bytes(b"x" * (2 * 2**20))
    os.utime(out / "old_1.trace", (1_000_000, 1_000_000))
    summary = {"process": {"name": "x"}, "duration_s": 20.0, "gpu": {"intervals": 900, "frames": 300}}
    saved = config.PACKAGE_DIR, config.OUT, config.MAX_DISK_MB, os.environ.get("SUMMARY"), config.LOCK
    config.PACKAGE_DIR, config.OUT, config.LOCK = package, out, tmp_path / "lock"  # a recording running here must not matter
    os.environ["SUMMARY"] = json.dumps(summary)
    try:
        config.MAX_DISK_MB = None
        got = recording.record_run("r", 20, "native", "-", str(tmp_path), [str(script)], layer={"none": "x"})
        assert "retention" not in got and (out / "old_1.trace").exists()
        (out / "r_1.json").unlink()
        config.MAX_DISK_MB = 2
        got = recording.record_run("r", 20, "native", "-", str(tmp_path), [str(script)], layer={"none": "x"})
        assert got["retention"]["removed"] == 1 and got["retention"]["trace_dropped"] is False, got.get("retention")
        assert json.loads((out / "r_1.json").read_text())["retention"] == got["retention"]
        assert not (out / "old_1.trace").exists() and (out / "r_1.frames.csv.gz").exists()
    finally:
        config.PACKAGE_DIR, config.OUT, config.MAX_DISK_MB = saved[:3]
        config.LOCK = saved[4]
        os.environ.pop("SUMMARY") if saved[3] is None else os.environ.update(SUMMARY=saved[3])


def test_windows_branch_prunes_too(tmp_path):
    """The Windows branch of record_run returns early; the quota still applies there and its note reaches the JSON."""
    from metal_gpu_trace import config, perf_record_windows, recording
    out = tmp_path / "runs"
    out.mkdir()
    (out / "old_1.trace").write_bytes(b"x" * (2 * 2**20))
    os.utime(out / "old_1.trace", (1_000_000, 1_000_000))

    def record_windows(label, *args, **kwargs):
        path = out / f"{label}_1.json"
        path.write_text("{}")
        return {"gpu": {"intervals": 5}}, path
    saved = config.OUT, config.MAX_DISK_MB, sys.platform, perf_record_windows.record_windows, config.LOCK
    config.OUT, config.MAX_DISK_MB, config.LOCK = out, 1, tmp_path / "lock"
    perf_record_windows.record_windows = record_windows
    sys.platform = "win32"
    try:
        got = recording.record_run("w", 5, "native", "-", str(tmp_path), ["prog"], layer={"none": "x"})
    finally:
        sys.platform = saved[2]
        config.OUT, config.MAX_DISK_MB = saved[:2]
        perf_record_windows.record_windows = saved[3]
        config.LOCK = saved[4]
    assert got["retention"]["removed"] == 1, got
    assert json.loads((out / "w_1.json").read_text())["retention"]["removed"] == 1
    assert not (out / "old_1.trace").exists()


@macos_only
def test_keep_runs_still_removes_old_tables(tmp_path):
    """KEEP_RUNS removes every file of an older run, the compressed tables included (prune_runs.sh's `${old:r}.*`)."""
    out = tmp_path / "runs"
    out.mkdir()
    for age, name in enumerate(("old.json", "old.frames.csv.gz", "old.metal_memory.csv.gz", "new.json")):
        (out / name).write_text("{}")
        os.utime(out / name, (1_000_000 + age * 100, 1_000_000 + age * 100))
    subprocess.run(["zsh", str(PKG / "prune_runs.sh"), str(out), "1"], check=True)
    assert sorted(p.name for p in out.iterdir()) == ["new.json"]


@macos_only
def test_keep_runs_never_removes_a_trace(tmp_path):
    """ADR-0006: KEEP_RUNS never prunes a .trace (only the disk quota frees it); the rest of the older run goes."""
    out = tmp_path / "runs"
    out.mkdir()
    for age, name in enumerate(("baselines.json", "old.json", "old.frames.csv.gz", "old.chrome-trace", "old.trace", "new.json", "new.trace")):
        if name.endswith(".trace"):
            (out / name).mkdir()
            (out / name / "form.template").write_text("x")
        else:
            (out / name).write_text("{}")
        os.utime(out / name, (1_000_000 + age * 100, 1_000_000 + age * 100))
    subprocess.run(["zsh", str(PKG / "prune_runs.sh"), str(out), "1"], check=True)
    assert sorted(p.name for p in out.iterdir()) == ["baselines.json", "new.json", "new.trace", "old.trace"]


@macos_only
def test_keep_trace_argument_keeps_the_trace_of_an_empty_run(tmp_path):
    """A deep recording (keep_trace) whose program did no GPU work keeps its .trace and says so, like KEEP_TRACE=1 does."""
    from metal_gpu_trace import config, paths, recording
    package, out = tmp_path / "package", tmp_path / "runs"
    package.mkdir()
    out.mkdir()
    (package / "perf_record.sh").write_text('#!/bin/zsh\nprint -r -- \'{"gpu": {"intervals": 0}}\' > "$PERF_OUT/${1}_1.json"\n'
                                            'mkdir "$PERF_OUT/${1}_1.trace"\n')
    saved = config.PACKAGE_DIR, config.OUT, os.environ.pop("KEEP_TRACE", None)
    config.PACKAGE_DIR, config.OUT = package, out
    try:
        try:
            recording.record_run("k", 5, "native", "-", str(tmp_path), ["prog"], layer={"none": "x"}, keep_trace=True)
            raise AssertionError("a run without GPU work must fail")
        except paths.ToolError as error:
            assert "k_1.trace is kept" in str(error), error
        assert [p.name for p in out.iterdir()] == ["k_1.trace"]
    finally:
        config.PACKAGE_DIR, config.OUT = saved[:2]
        if saved[2] is not None:
            os.environ["KEEP_TRACE"] = saved[2]


def test_resolve_tier_table():
    """A tier sets memory, counters and whether the .trace is kept; a memory or counters given on its own wins."""
    from metal_gpu_trace import recording
    resolve = recording.resolve_tier
    assert recording.TIERS == ("light", "standard", "deep")
    assert resolve("light", None, None) == (False, False, False)
    assert resolve("standard", None, None) == (True, False, False)
    assert resolve("deep", None, None) == (True, True, True)
    assert resolve("deep", False, None) == (False, True, True)
    assert resolve("light", True, None) == (True, False, False)
    assert resolve("standard", None, True) == (True, True, False)
    assert resolve("deep", None, False) == (True, False, True)


def test_unknown_tier_is_tool_error(tmp_path):
    from metal_gpu_trace import paths, recording
    program = tmp_path / "prog"
    program.write_text("")
    for bad in ("fast", "", "Deep", None, 3, ["light"]):
        for call in (lambda bad=bad: recording.resolve_tier(bad, None, None),
                     lambda bad=bad: recording.tool_perf_record("t", str(program), wine="native", tier=bad)):
            try:
                call()
            except paths.ToolError as error:
                assert "tier is one of light, standard, deep" in str(error), error
            else:
                raise AssertionError(f"{bad!r} must be refused")


def capture_record(tmp_path, **options):
    """Calls tool_perf_record with `recording.record` stubbed and returns what it was given: (positional, keyword)."""
    from metal_gpu_trace import recording
    program = tmp_path / "prog"
    program.write_text("")
    seen = {}
    saved = recording.record
    recording.record = lambda *args, **kw: seen.update(args=args, kw=kw) or {}
    try:
        recording.tool_perf_record("t", str(program), wine="native", **options)
    finally:
        recording.record = saved
    return seen["args"], seen["kw"]


def test_default_is_unchanged(tmp_path):
    """With no tier, memory and counters, a recording is what it was before tiers existed."""
    args, kw = capture_record(tmp_path)
    assert args[7] is True and kw["counters"] is False and kw["keep_trace"] is False and kw["tier"] == "standard", (args, kw)
    args, kw = capture_record(tmp_path, memory=False, counters=True)
    assert args[7] is False and kw["counters"] is True and kw["keep_trace"] is False, (args, kw)


def test_tiers_reach_the_recording(tmp_path):
    args, kw = capture_record(tmp_path, tier="light")
    assert args[7] is False and kw["counters"] is False and kw["keep_trace"] is False and kw["tier"] == "light"
    args, kw = capture_record(tmp_path, tier="deep")
    assert args[7] is True and kw["counters"] is True and kw["keep_trace"] is True and kw["tier"] == "deep"
    args, kw = capture_record(tmp_path, tier="deep", memory=False)
    assert args[7] is False and kw["counters"] is True, (args, kw)


def run_stub_recording(tmp_path, **record_options):
    """Runs record_run against a script that reports the environment it was given, and returns that report."""
    from metal_gpu_trace import config, recording
    package, out = tmp_path / "package", tmp_path / "runs"
    package.mkdir()
    out.mkdir()
    (package / "perf_record.sh").write_text(
        '#!/bin/zsh\nprint -r -- \'{"gpu": {"intervals": 1}, "seen": {"memory": "\'${PERF_MEMORY-unset}\'", '
        '"instruments": "\'${PERF_INSTRUMENTS-unset}\'", "keep": "\'${KEEP_TRACE-unset}\'"}}\' > "$PERF_OUT/${1}_1.json"\n')
    saved_env = {k: os.environ.pop(k, None) for k in ("PERF_MEMORY", "PERF_INSTRUMENTS", "KEEP_TRACE")}
    saved = config.PACKAGE_DIR, config.OUT, config.MAX_DISK_MB
    config.PACKAGE_DIR, config.OUT, config.MAX_DISK_MB = package, out, None
    try:
        return recording.record_run("t", 5, "native", "-", str(tmp_path), ["prog"], layer={"none": "x"},
                                    **record_options)
    finally:
        config.PACKAGE_DIR, config.OUT, config.MAX_DISK_MB = saved
        os.environ.update({k: v for k, v in saved_env.items() if v is not None})


@macos_only
def test_light_sets_no_memory_env(tmp_path):
    summary = run_stub_recording(tmp_path, memory=False, counters=False, keep_trace=False, tier="light")
    assert summary["seen"] == {"memory": "0", "instruments": "unset", "keep": "unset"}, summary["seen"]
    assert summary["tier"] == "light"


@macos_only
def test_deep_sets_counters_and_keep_trace(tmp_path):
    summary = run_stub_recording(tmp_path, memory=True, counters=True, keep_trace=True, tier="deep")
    assert summary["seen"] == {"memory": "unset", "instruments": "Metal GPU Counters", "keep": "1"}, summary["seen"]
    assert summary["tier"] == "deep"


@macos_only
def test_standard_sets_nothing_extra(tmp_path):
    summary = run_stub_recording(tmp_path, tier="standard")
    assert summary["seen"] == {"memory": "unset", "instruments": "unset", "keep": "unset"} and summary["tier"] == "standard"


def test_baseline_record_passes_tier(tmp_path):
    from metal_gpu_trace import analysis, config, experiments, recording
    seen = []
    saved = recording.tool_perf_record, analysis.tool_perf_baseline, config.OUT
    config.OUT = tmp_path

    def fake(label, **kw):
        seen.append(kw.get("tier"))
        (tmp_path / f"{label}_x.json").write_text("{}")
    recording.tool_perf_record = fake
    analysis.tool_perf_baseline = lambda name, runs, skip_s=0: {}
    try:
        experiments.tool_perf_baseline_record("tb", count=2, tier="light")
    finally:
        recording.tool_perf_record, analysis.tool_perf_baseline, config.OUT = saved
    assert seen == ["light", "light"], seen


def test_deep_refused_on_windows(tmp_path):
    from metal_gpu_trace import paths
    saved = sys.platform
    sys.platform = "win32"
    try:
        try:
            capture_record(tmp_path, tier="deep")
        except paths.ToolError as error:
            assert "deep needs Metal GPU counters: macOS only" in str(error), error
        else:
            raise AssertionError("deep must be refused under Windows")
        capture_record(tmp_path, tier="light")
        capture_record(tmp_path, tier="standard")
    finally:
        sys.platform = saved


def test_tier_is_in_the_record_schemas():
    from metal_gpu_trace import registry
    assert registry.RECORD_PROPS["tier"]["enum"] == ["light", "standard", "deep"]
    for tool in ("perf_record", "perf_baseline_record", "perf_sweep", "perf_ab", "perf_cold_warm"):
        assert "tier" in registry.TOOLS[tool][1]["properties"], tool
    for tool in ("perf_compare", "perf_gate", "perf_history"):
        assert "tier" not in registry.TOOLS[tool][1]["properties"], tool


def test_check_cooldown_bounds():
    from metal_gpu_trace import paths
    assert paths.check_cooldown(None) == 0 and paths.check_cooldown(0) == 0 and paths.check_cooldown("30") == 30.0
    assert paths.check_cooldown(600) == 600.0 and paths.check_cooldown(0.5) == 0.5
    for bad in (-1, 601, "x", float("nan"), float("inf"), True, [5]):
        try:
            paths.check_cooldown(bad)
        except paths.ToolError as error:
            assert "cooldown_s is 0 to 600 seconds" in str(error), error
        else:
            raise AssertionError(f"{bad!r} must be refused")


def test_cooldown_sleeps_total_in_short_slices():
    import time
    from metal_gpu_trace import recording
    slept, said = [], []
    saved = time.sleep, recording.progress
    time.sleep = slept.append
    recording.progress = lambda done, total, message: said.append((done, total, message))
    try:
        recording.cooldown(3.5)
    finally:
        time.sleep, recording.progress = saved
    assert abs(sum(slept) - 3.5) < 1e-9 and max(slept) <= 1 and len(slept) == 4, slept
    assert said[0][2] == "cooling down: 4 s left" and said[-1][2] == "cooling down: 1 s left", said
    assert all(total == 3.5 for _, total, _ in said)


def test_cooldown_cancel_raises_and_stops():
    import threading
    import time
    from metal_gpu_trace import paths, recording
    slept = []
    event = threading.Event()
    event.set()
    saved = time.sleep, getattr(recording.RUN, "cancel", None)
    time.sleep = slept.append
    recording.RUN.cancel = event
    try:
        try:
            recording.cooldown(30)
        except paths.ToolError as error:
            assert "cancelled while cooling down" in str(error), error
        else:
            raise AssertionError("a cancelled cooldown must raise")
    finally:
        time.sleep, recording.RUN.cancel = saved
    assert slept == [], "no slice is slept once cancelled"


def test_cooldown_cancelled_in_the_middle():
    import threading
    import time
    from metal_gpu_trace import paths, recording
    event, slept = threading.Event(), []

    def sleep(seconds):
        slept.append(seconds)
        if len(slept) == 2:
            event.set()
    saved = time.sleep, getattr(recording.RUN, "cancel", None)
    time.sleep = sleep
    recording.RUN.cancel = event
    try:
        try:
            recording.cooldown(10)
        except paths.ToolError as error:
            assert "cancelled while cooling down" in str(error)
        else:
            raise AssertionError("must raise")
    finally:
        time.sleep, recording.RUN.cancel = saved
    assert len(slept) == 2, slept


def test_zero_cooldown_never_sleeps():
    import time
    from metal_gpu_trace import recording
    saved = time.sleep
    time.sleep = lambda s: (_ for _ in ()).throw(AssertionError("slept"))
    try:
        recording.cooldown(0)
    finally:
        time.sleep = saved


def run_experiment(tmp_path, call, events=None):
    """Runs `call(experiments)` with recordings and cooldowns stubbed; returns the order of events, "rec" and "cool N"
    (`events`, when given, is the list they go to, so a call that raises still shows them)."""
    from metal_gpu_trace import analysis, config, experiments, recording
    events = [] if events is None else events
    saved = recording.record_new_summary, recording.cooldown, analysis.steady_summary, config.OUT
    config.OUT = tmp_path

    def record(label, **kw):
        events.append("rec")
        return label, {"gpu": {"frames": 300, "fps_estimate": 60.0}}
    recording.record_new_summary = record
    recording.cooldown = lambda seconds: events.append(f"cool {seconds:g}")
    analysis.steady_summary = lambda run, skip_s=0: {"gpu": {"frames": 300, "fps_estimate": 60.0, "frame_gpu_ms": {"mean": 4.0},
                                                             "stutter_rate_pct": 0.0, "fps_1pct_low": 50.0}}
    saved_baseline = analysis.tool_perf_baseline
    analysis.tool_perf_baseline = lambda name, runs, skip_s=0: {}
    try:
        call(experiments)
    finally:
        recording.record_new_summary, recording.cooldown, analysis.steady_summary, config.OUT = saved
        analysis.tool_perf_baseline = saved_baseline
    return events


def test_baseline_record_cooldown_between_runs_only(tmp_path):
    events = run_experiment(tmp_path, lambda e: e.tool_perf_baseline_record("b", count=3, cooldown_s=5))
    assert events == ["rec", "cool 5", "rec", "cool 5", "rec"], events


def test_ab_cooldown_between_every_pair(tmp_path):
    one = run_experiment(tmp_path, lambda e: e.tool_perf_ab("x", "A=1", "A=2", rounds=1, cooldown_s=7))
    assert one.count("rec") == 4 and one.count("cool 7") == 3 and one[0] == "rec" and one[-1] == "rec", one
    two = run_experiment(tmp_path, lambda e: e.tool_perf_ab("x", "A=1", "A=2", rounds=2, cooldown_s=7))
    assert two.count("rec") == 8 and two.count("cool 7") == 7, two
    assert all(a != b for a, b in zip(two, two[1:])), "a pause between any two recordings, never two in a row"


def test_sweep_cooldown(tmp_path):
    events = run_experiment(tmp_path, lambda e: e.tool_perf_sweep("s", "dim", [10, 20, 30], rounds=2, cooldown_s=2))
    assert events.count("rec") == 6 and events.count("cool 2") == 5 and events[0] == "rec" and events[-1] == "rec", events


def test_zero_cooldown_pauses_never(tmp_path):
    events = run_experiment(tmp_path, lambda e: e.tool_perf_baseline_record("b", count=3))
    assert events == ["rec", "rec", "rec"], events
    events = run_experiment(tmp_path, lambda e: e.tool_perf_ab("x", "A=1", "A=2", cooldown_s=0))
    assert not any(x.startswith("cool") for x in events), events


def test_bad_cooldown_is_refused_before_recording(tmp_path):
    from metal_gpu_trace import paths
    seen = []
    for call in (lambda e: e.tool_perf_baseline_record("b", cooldown_s=601), lambda e: e.tool_perf_ab("x", "", "", cooldown_s="x"),
                 lambda e: e.tool_perf_sweep("s", "dim", [1, 2], cooldown_s=-1)):
        try:
            seen.append(run_experiment(tmp_path, call))
        except paths.ToolError as error:
            assert "cooldown_s" in str(error)
        else:
            raise AssertionError("must be refused")
    assert seen == []


def test_cooldown_in_schema():
    from metal_gpu_trace import registry
    for tool in ("perf_baseline_record", "perf_ab", "perf_sweep"):
        assert "cooldown_s" in registry.TOOLS[tool][1]["properties"], tool
    for tool in registry.TOOLS:
        if tool not in ("perf_baseline_record", "perf_ab", "perf_sweep"):
            assert "cooldown_s" not in registry.TOOLS[tool][1].get("properties", {}), tool


def test_cancelled_cooldown_starts_no_next_recording(tmp_path):
    """A cancel during the rest ends the experiment with the pause's error: the next recording never starts."""
    from metal_gpu_trace import paths, recording
    for call in (lambda e: e.tool_perf_baseline_record("b", count=3, cooldown_s=5), lambda e: e.tool_perf_ab("x", "", "", cooldown_s=5),
                 lambda e: e.tool_perf_sweep("s", "dim", [1, 2, 3], cooldown_s=5)):
        events = []

        def cancelled(seconds):
            raise paths.ToolError("cancelled while cooling down")
        try:
            run_experiment(tmp_path, lambda e, call=call: (recording.__dict__.update(cooldown=cancelled), call(e)), events)
        except paths.ToolError as error:
            assert "cancelled while cooling down" in str(error)
        else:
            raise AssertionError("must end with the cancel")
        assert events == ["rec"], f"no recording starts after the cancel: {events}"


def test_one_recording_has_no_pause(tmp_path):
    events = run_experiment(tmp_path, lambda e: e.tool_perf_baseline_record("b", count=1, cooldown_s=60))
    assert events == ["rec"], events


def test_finish_leaves_the_runs_folder_alone_while_another_recording_runs(tmp_path):
    """Another recording's .trace is written into the runs folder as it goes: pruning then could delete it."""
    from metal_gpu_trace import config, recording
    out = tmp_path / "runs"
    out.mkdir()
    saved = config.OUT, config.LOCK, config.MAX_DISK_MB
    config.OUT, config.LOCK, config.MAX_DISK_MB = out, tmp_path / "lock", 1
    try:
        (out / "live.trace").write_bytes(b"x" * (2 * 2**20))
        config.LOCK.mkdir()
        (config.LOCK / "pid").write_text(str(os.getpid()))  # a live process holds the recording lock
        got = recording.finish({}, out / "cur.json", None, None)
        assert (out / "live.trace").exists() and "retention" not in got, got
        (config.LOCK / "pid").unlink()
        got = recording.finish({}, out / "cur.json", None, None)
        assert not (out / "live.trace").exists() and got["retention"]["removed"] == 1, got
    finally:
        config.OUT, config.LOCK, config.MAX_DISK_MB = saved


def test_finish_refreshes_the_common_block_with_the_layer(tmp_path):
    """`common` is built before the layer is known; finish adds the layer and rebuilds it, so it names the layer."""
    from metal_gpu_trace import metrics, recording
    summary = {"schema_version": 3, "gpu": {}}
    summary["common"] = metrics.common_block(summary)
    assert summary["common"]["api"]["translation_layer"] == "unknown"
    got = recording.finish(summary, tmp_path / "r.json", {"none": "native Windows"}, None)
    assert got["common"]["api"]["translation_layer"] == "native"
    assert json.loads((tmp_path / "r.json").read_text())["common"]["api"]["translation_layer"] == "native"


def test_finish_does_not_add_common_to_an_older_summary(tmp_path):
    from metal_gpu_trace import recording
    assert "common" not in recording.finish({"schema_version": 2, "gpu": {}}, tmp_path / "old.json", None, None)


def test_readme_states_the_deadline_the_code_uses():
    """The README's deadline for a recording through the server is the one `deadline` computes (limit 2)."""
    from metal_gpu_trace import recording
    assert (recording.deadline(1), recording.deadline(1, True)) == (15 + 180, 55 + 180)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "15 s per recorded second plus 180" in readme and "10 s per recorded second" not in readme


def test_first_progress_message_says_read_back_only_off_windows():
    """Windows has no read-back, so its first progress line does not promise one (limit 8)."""
    from metal_gpu_trace import recording
    assert recording.worst_case_message(630, windows=False) == "recording: up to 630 s including read-back"
    assert recording.worst_case_message(630, windows=True) == "recording: up to 630 s"


def test_daemon_architecture_empty_or_null_is_an_absent_key():
    """A daemon that answers with null, empty or blank architectures, or a block that is not an object, adds no key:
    never the text "None" and never an error."""
    from metal_gpu_trace import perf_record_windows as prw
    for payload in ({"cpu_architecture": None, "gpu_architecture": None}, {"cpu_architecture": "", "gpu_architecture": " "},
                    {"cpu": None, "gpu": None, "ram": None}, {"cpu": [], "gpu": "x", "ram": 3},
                    {"cpu_architecture": 5, "gpu_architecture": {"a": 1}}, {}):
        device = {"platform": "Windows"}
        prw._enrich_device_with_vegaflow(device, payload)
        assert device == {"platform": "Windows"}, (payload, device)
    device = {}
    prw._enrich_device_with_vegaflow(device, {"cpu_architecture": " Zen 2 ", "gpu_architecture": None,
                                              "gpu": {"adapter_name": "AMD (Vega 6 / GCN 5.0)"}})
    assert device == {"cpu_architecture": "Zen 2", "gpu_architecture": "Vega 6 / GCN 5.0"}, device


def test_graphics_api_comes_from_the_loaded_modules():
    """graphics_api() names the runtime from the graphics DLLs a process holds (d3d12 beats d3d11, d3d9, vulkan and OpenGL)
    and the translation layer from where they were loaded from; an empty or unreadable list is `unknown`, never a guess."""
    from metal_gpu_trace import perf_record_windows as prw
    sysdir = {"d3d11.dll": True, "dxgi.dll": True}
    assert prw.graphics_api([("d3d11.dll", True), ("dxgi.dll", True)]) == {"runtime": "d3d11", "translation_layer": None}
    assert prw.graphics_api([("d3d11.dll", True), ("d3d12.dll", True)])["runtime"] == "d3d12"  # 11on12 loads both
    assert prw.graphics_api([("D3D9.DLL", True)])["runtime"] == "d3d9"
    assert prw.graphics_api([("vulkan-1.dll", True)])["runtime"] == "vulkan"
    assert prw.graphics_api([("opengl32.dll", True)])["runtime"] == "opengl"
    assert prw.graphics_api([("vulkan-1.dll", True), ("d3d11.dll", False), ("dxgi.dll", False)]) == {"runtime": "d3d11", "translation_layer": "dxvk"}
    assert prw.graphics_api([("d3d12.dll", False), ("dxgi.dll", False), ("vulkan-1.dll", True)]) == {"runtime": "d3d12", "translation_layer": "vkd3d-proton"}
    assert prw.graphics_api([("kernel32.dll", True)]) == {"runtime": "unknown", "translation_layer": None}
    assert prw.graphics_api([]) == {"runtime": "unknown", "translation_layer": None}
    assert prw.graphics_api(None) == {"runtime": "unknown", "translation_layer": None}  # the list could not be read
    assert sysdir  # the names are lower-cased before they are compared


def test_gpu_engine_counters_give_the_program_and_the_others():
    """parse_gpu_engines() sums typeperf's `GPU Engine` utilization by pid; gpu_noise() flags a recording when the other
    processes used NOISY_EXTERNAL_PCT points or more of the GPU; no sample, or a header without rows, gives None."""
    from metal_gpu_trace import perf_record_windows as prw
    header = ('"(PDH-CSV 4.0)","\\\\PC\\GPU Engine(pid_10_luid_0x0_0x1_phys_0_eng_0_engtype_3D)\\Utilization Percentage",'
              '"\\\\PC\\GPU Engine(pid_10_luid_0x0_0x1_phys_0_eng_1_engtype_Copy)\\Utilization Percentage",'
              '"\\\\PC\\GPU Engine(pid_20_luid_0x0_0x1_phys_0_eng_0_engtype_3D)\\Utilization Percentage"')
    text = "\n" + header + '\n"11/17/2026 22:27:58.556","40.5","2.0","30.0"\n\nExiting, please wait...   The command completed successfully.\n'
    assert prw.parse_gpu_engines(text) == {10: 42.5, 20: 30.0}, prw.parse_gpu_engines(text)
    assert prw.parse_gpu_engines("") == {} and prw.parse_gpu_engines(header) == {} and prw.parse_gpu_engines("garbage") == {}
    noisy = prw.gpu_noise([{10: 50.0, 20: 30.0}, {10: 60.0, 20: 20.0}], 10)
    assert noisy == {"flag": True, "process_busy_pct": 55.0, "external_pct": 25.0, "samples": 2}, noisy
    assert prw.gpu_noise([{10: 50.0, 20: 5.0}], 10)["flag"] is False
    assert prw.gpu_noise([{10: 50.0}], 10)["external_pct"] == 0.0  # alone on the GPU
    assert prw.gpu_noise([], 10) is None


def test_daemon_bus_width_must_be_a_positive_number():
    """A bus width that is a bool, text, blank, an object or not positive is absent: no `bus True-bit`."""
    from metal_gpu_trace import perf_record_windows as prw
    for bad in (True, "   ", "None", {"a": 1}, 0, -64, None):
        device = {}
        prw._enrich_device_with_vegaflow(device, {"ram": {"memory_bus_width_bits": bad}})
        assert device == {}, (bad, device)
    device = {}
    prw._enrich_device_with_vegaflow(device, {"ram": {"memory_bus_width_bits": 128}})
    assert device == {"gpu_architecture": "bus 128-bit"}, device


def test_daemon_output_that_is_not_utf8_is_invalid_json_not_missing(tmp_path):
    """Bytes that are not text come back as `invalid_json` (the daemon answered, badly), not `missing`."""
    if sys.platform == "win32":
        return  # the fake daemon is a shell script
    from metal_gpu_trace import perf_record_windows as prw
    exe = tmp_path / "daemon.sh"
    exe.write_text("#!/bin/sh\nprintf '\\377\\376'\n")
    exe.chmod(0o755)
    assert prw.daemon_info(exe) == (None, "invalid_json")


def test_daemon_that_does_not_answer_says_why_without_its_path(tmp_path):
    """`--system-info` that times out, prints no JSON, a JSON that is not an object, nothing, or exits non-zero says
    a short reason in the device block; the daemon's path is never in it."""
    from metal_gpu_trace import perf_record_windows as prw
    exe = tmp_path / "secret-dir" / "vegaflow_daemon.exe"
    exe.parent.mkdir()
    exe.write_text("x")

    def answer(stdout="", code=0, error=None):
        def run(*args, **kwargs):
            if args[0][1:] != ["--system-info"]:  # platform and ctypes may spawn their own commands
                return real_run(*args, **kwargs)
            if error:
                raise error
            return subprocess.CompletedProcess(args[0], code, stdout, "")
        return run

    cases = [(answer(error=subprocess.TimeoutExpired("d", 1)), "timeout"), (answer("{broken"), "invalid_json"),
             (answer("[1]"), "invalid_json"), (answer(""), "missing"), (answer("{}", code=3), "missing"),
             (answer(error=OSError("no")), "missing")]
    saved = real_run = prw.subprocess.run
    try:
        for run, reason in cases:
            prw.subprocess.run = run
            device = prw.collect_device_info(daemon_path=exe)
            assert device["daemon_info_error"] == reason, (reason, device)
            assert "secret-dir" not in json.dumps(device), device
        prw.subprocess.run = answer('{"cpu_architecture": "Zen 2"}')
        device = prw.collect_device_info(daemon_path=exe)
        assert device["cpu_architecture"] == "Zen 2" and "daemon_info_error" not in device, device
    finally:
        prw.subprocess.run = saved
    assert "daemon_info_error" not in prw.collect_device_info(daemon_path=tmp_path / "none.exe")  # no daemon: not an error


def test_daemon_names_are_configurable():
    """METAL_TRACE_DAEMON_NAMES lists other file names to look for; a name with a path in it is ignored."""
    from metal_gpu_trace import perf_record_windows as prw
    saved = os.environ.get("METAL_TRACE_DAEMON_NAMES")
    os.environ["METAL_TRACE_DAEMON_NAMES"] = "other.exe, ../evil.exe,,sub/x.exe, .., ., a\\b.exe"
    try:
        names = {c.name for c in prw.daemon_candidates()}
    finally:
        if saved is None:
            os.environ.pop("METAL_TRACE_DAEMON_NAMES")
        else:
            os.environ["METAL_TRACE_DAEMON_NAMES"] = saved
    assert names == {"vegaflow_daemon.exe", "other.exe"}, names
