"""Tests of recording: perf_record.sh, perf_record and its levers, layers and workloads."""
import json
import os
import pathlib
import shutil
import subprocess
import sys

from support import ROOT, PKG, macos_only, hang_stubs  # also puts src/ on sys.path


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
    env = {**os.environ, "PERF_OUT": str(tmp_path), "PERF_MIN_FREE_GB": "99999999"}
    proc = subprocess.run(["zsh", str(script), "g", "30", "native", "-", "-", sys.executable], env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 4 and "not enough free disk" in proc.stderr and "99999999 GB needed" in proc.stderr, proc
    assert not (tmp_path / ".recording").exists(), "no lock is left behind"
    default = subprocess.run(["zsh", str(script), "g", "60", "native", "-", "-", sys.executable],
                             env={**os.environ, "PERF_OUT": str(tmp_path), "TMPDIR": "/nonexistent"},
                             capture_output=True, text=True, timeout=60)
    assert default.returncode != 0, "a missing TMPDIR volume must not pass the guard"

def test_levers(tmp_path):
    """memory_free_pct holds memory_pressure around a recording and stops it even when the recording fails;
    background sets PERF_PREFIX for perf_record.sh; out-of-range or Windows use is refused before anything starts."""
    from metal_gpu_trace import config, paths, recording, registry
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
    """A recording that overruns its deadline is stopped and leaves no files and no lock behind, and the deadline
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
    program = tmp_path / "hang-4242"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    saved = config.OUT, recording.deadline, os.environ["PATH"]
    config.OUT, recording.deadline = out, lambda seconds: 3
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    try:
        recording.tool_perf_record("hang", str(program), seconds=1, wine="native")
        raise AssertionError("an overrunning recording must fail")
    except paths.ToolError as error:
        assert "stopped" in str(error), error
    finally:
        config.OUT, recording.deadline, os.environ["PATH"] = saved
    assert not list(out.iterdir()), list(out.iterdir())

@macos_only
def test_overrun_removes_lock_with_pid(tmp_path):
    """The lock of a recording that overruns is removed together with the pid file perf_record.sh wrote in it."""
    from metal_gpu_trace import config, paths, recording
    stubs, out, program = hang_stubs(tmp_path)
    (stubs / "xcrun").write_text("#!/bin/zsh\ntest -s $PERF_OUT/.recording/pid || exit 9\n"
                                 "while [[ $1 != --output ]]; do shift; done\nmkdir -p $2\nsleep 60\n")
    saved = config.OUT, recording.deadline, os.environ["PATH"]
    config.OUT, recording.deadline = out, lambda seconds: 3
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    try:
        recording.tool_perf_record("hang", str(program), seconds=1, wine="native")
        raise AssertionError("an overrunning recording must fail")
    except paths.ToolError as error:
        assert "stopped" in str(error), error
    finally:
        config.OUT, recording.deadline, os.environ["PATH"] = saved
    assert not list(out.iterdir()), list(out.iterdir())

@macos_only
def test_stale_lock_macos(tmp_path):
    """A .recording lock whose pid is dead is taken over by the next recording; one whose pid is alive still refuses."""
    stubs, out = tmp_path / "stubs", tmp_path / "runs"
    stubs.mkdir()
    out.mkdir()
    (stubs / "xcrun").write_text(f"#!/bin/zsh\ntouch {tmp_path}/xctrace-ran\n"
                                 "while [[ $1 != --output ]]; do shift; done\nmkdir -p $2\n")
    (stubs / "pkill").write_text("#!/bin/zsh\nexit 1\n")
    program = tmp_path / "stale-4242"
    program.write_text("#!/bin/sh\n")
    for stub in (*stubs.iterdir(), program):
        stub.chmod(0o755)
    env = dict(os.environ, PERF_OUT=str(out), PERF_MIN_FREE_GB="0", PATH=f"{stubs}:{os.environ['PATH']}")

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

def test_kill_program_and_watchdog(tmp_path):
    """kill_program ends a program that ignores SIGTERM, and perf_record.sh stops its recording, frees its lock and
    its program when the server named in PERF_PARENT_PID dies."""
    import secrets
    import shutil
    import time
    from metal_gpu_trace import recording
    from support import wait_until
    stubs, out, hung = hang_stubs(tmp_path)
    # the names pkill -x gets hold only this test's processes: a random token (8 hex digits, so that the name stays
    # within the 16 characters macOS keeps of a process name)
    token = secrets.token_hex(4)
    program = hung.rename(tmp_path / f"hang-{token}")
    # a program that ignores SIGTERM
    stubborn = tmp_path / f"ig-{token}"
    shutil.copy(shutil.which("sleep"), stubborn)
    proc = subprocess.Popen(["sh", "-c", f"trap '' TERM; exec {stubborn} 60"])
    wait_until(lambda: subprocess.run(["pgrep", "-x", stubborn.name], capture_output=True).returncode == 0)
    recording.kill_program(stubborn.name)
    assert proc.wait(timeout=15) is not None, "kill_program must escalate to SIGKILL"
    # the recording's parent dies: the script must exit and free its lock
    parent = subprocess.Popen(["sleep", "60"])
    (stubs / "pkill").unlink()  # the script needs the real pkill
    # PERF_MIN_FREE_GB=0: the disk check needs 26 GB for 30 s, and a CI runner's free space varies
    env = dict(os.environ, PERF_OUT=str(out), PERF_PARENT_PID=str(parent.pid), PERF_MIN_FREE_GB="0",
               PATH=f"{stubs}:{os.environ['PATH']}")
    logfile = tmp_path / "script.log"  # a file, not a pipe: the stub's orphaned sleep would hold a pipe open
    script = subprocess.Popen(["zsh", str(PKG / "perf_record.sh"), "orphan", "30", "native", "-", str(tmp_path),
                               str(program)], env=env, stdout=open(logfile, "w"), stderr=subprocess.STDOUT,
                              start_new_session=True)
    try:
        deadline = time.time() + 40
        while not (out / ".recording").is_dir() and time.time() < deadline:
            time.sleep(0.2)
        assert (out / ".recording").is_dir(), (f"the recording never started; the script's exit code is {script.poll()} "
                                               f"and its output {logfile.read_text()[-600:]!r}")
        parent.kill()
        parent.wait()
        script.wait(timeout=30)
    finally:
        if script.poll() is None:
            script.kill()
        subprocess.run(["pkill", "-f", str(program)], capture_output=True)  # the xcrun stub holds it in its arguments
    assert not list(out.iterdir()), f"the lock and the partial files must go: {list(out.iterdir())} {logfile.read_text()[-400:]!r}"

def test_script_failure_cleanup(tmp_path):
    """perf_record.sh frees its lock and deletes its partial files when a recording fails, and refuses a program that
    is not an executable file before it starts Instruments."""
    stubs, out = tmp_path / "stubs", tmp_path / "runs"
    stubs.mkdir()
    out.mkdir()
    xcrun = stubs / "xcrun"  # an xctrace that fails at once
    xcrun.write_text("#!/bin/zsh\nexit 1\n")
    xcrun.chmod(0o755)
    program, text = tmp_path / "prog", tmp_path / "notes.txt"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    text.write_text("x")
    env = dict(os.environ, PERF_OUT=str(out), PERF_MIN_FREE_GB="0", PATH=f"{stubs}:{os.environ['PATH']}")

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
    assert prw.daemon_candidates() == expected, prw.daemon_candidates()
    assert prw.daemon_candidates("x.exe")[0] == pathlib.Path("x.exe")


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
    saved, config.OUT = config.OUT, tmp_path
    try:
        lock = tmp_path / ".recording"
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
        config.OUT = saved
