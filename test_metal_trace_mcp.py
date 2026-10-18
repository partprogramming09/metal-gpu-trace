"""Self-check of metal_trace_mcp.py, perf_report.py and gputrace_read.py without Instruments: run it with python3 -I,
or with pytest."""
import json
import os
import shutil
import pathlib
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import gputrace_read  # noqa: E402
import perf_report  # noqa: E402


def write_capture(directory):
    """Writes a .gputrace holding three drawPrimitives records into `directory` and returns its path."""
    record = struct.pack("<Ii", 0x30, -16218) + bytes(0x24 - 8) + b"Cuu\0" + bytes(8)
    capture = directory / "frame.gputrace"
    capture.mkdir()
    (capture / "capture").write_bytes(b"MTSP" + bytes(4) + record * 3)
    return capture


def test_report(tmp_path):
    """Exported rows resolve xctrace's refs, the export file goes once read, shared summaries hold no paths, and a
    trace without the GPU intervals table fails with a hint."""
    xml = tmp_path / "table.xml"
    for early in (False, True):
        xml.write_text('<trace-query-result><node><schema><col><mnemonic>process</mnemonic></col>'
                       '<col><mnemonic>duration</mnemonic></col></schema>'
                       '<row><process id="1"><pid>42</pid></process><duration>5</duration></row>'
                       '<row><process ref="1"/><duration>7</duration></row></node></trace-query-result>')
        got = perf_report.rows(str(xml))
        first = next(got)
        assert perf_report.pid_of(first["process"]) == 42
        rest = [] if early else list(got)
        got.close()
        assert early or perf_report.pid_of(rest[0]["process"]) == 42, rest
        assert not xml.exists(), "the exported XML must be deleted once read"
    assert perf_report.public_arguments("/opt/games/x/game.exe -w 1") == "game.exe -w 1"
    try:
        perf_report.export(tmp_path / "gone.trace", toc=True)
        raise AssertionError("a missing .trace must fail before xctrace runs")
    except FileNotFoundError as error:
        assert "KEEP_TRACE" in str(error) and str(tmp_path) not in str(error)
    # xctrace may write a table whole and then die with SIGTRAP: a complete file is kept, a cut one is an error
    import subprocess as sp

    def crash_after_writing(cmd, body):
        def run(c, **kw):
            pathlib.Path(c[c.index("--output") + 1]).write_text(body)
            return sp.CompletedProcess(c, 133, "", "")
        return run
    saved_run = perf_report.subprocess.run
    (tmp_path / "x.trace").mkdir()
    try:
        perf_report.subprocess.run = crash_after_writing(None, "<trace-query-result><node/></trace-query-result>")
        kept = perf_report.export(tmp_path / "x.trace", xpath="/x")
        assert pathlib.Path(kept).exists()
        os.unlink(kept)
        # cut right after the last row, as xctrace 27.1 leaves metal-resource-allocations: every row is read
        perf_report.subprocess.run = crash_after_writing(None, '<trace-query-result><node><schema><col><mnemonic>n'
                                                               '</mnemonic></col></schema><row><n>1</n></row>\n')
        cut_rows = list(perf_report.rows(perf_report.export(tmp_path / "x.trace", xpath="/x")))
        assert len(cut_rows) == 1 and cut_rows[0]["n"].text == "1", cut_rows
        perf_report.subprocess.run = crash_after_writing(None, "<trace-query-result><node>")
        try:
            perf_report.export(tmp_path / "x.trace", xpath="/x")
            raise AssertionError("a cut export must fail")
        except RuntimeError as error:
            assert "exit 133" in str(error), error
    finally:
        perf_report.subprocess.run = saved_run
    toc = ET.fromstring('<trace-toc><run><data><table schema="metal-gpu-intervals"/></data></run></trace-toc>')
    assert perf_report.missing_tables(toc) == ["gpu-performance-state-intervals", "metal-application-encoders-list",
                                               "metal-current-allocated-size"]
    try:
        perf_report.missing_tables(ET.fromstring("<trace-toc/>"))
        raise AssertionError("a trace without metal-gpu-intervals must fail")
    except ValueError as error:
        assert "trace_tables" in str(error), error


def test_encoders(tmp_path):
    """Encoders, command buffers, short encoders, labels and idle gaps come out exact for two hand-made frames."""
    spans = [(1, 0, 5000, "a", "x"), (1, 5000, 5000, "b", "x"), (1, 20000, 100000, "c", "x"),
             (2, 2_000_000, 5000, "d", "y"), (2, 2_005_000, 1_000_000, "e", "z")]
    labels = {"a": "[0] Blit Command 0", "b": "[1] Blit Command 1", "c": "[2] Render Command 2",
              "d": "[0] Blit Command 0", "e": "[1] Render Command 1"}
    got = perf_report.encoder_stats(spans, labels)
    assert got["per_frame"]["p50"] == 3 and got["command_buffers_per_frame"]["p50"] == 2, got
    assert got["short_share"] == {"10": 0.6, "25": 0.6, "50": 0.6, "100": 0.6, "250": 0.8, "500": 0.8, "1000": 0.8}
    assert [(g["label"], g["per_frame"], g["total_ms"]) for g in got["by_label"]] == [
        ("Render Command", 1.0, 1.1), ("Blit Command", 1.5, 0.015)], got["by_label"]
    idle = perf_report.idle_gaps(spans)
    assert idle["idle_ms_per_frame"]["max"] == 1.88 and idle["gaps_over_1ms"] == 1, idle
    assert idle["idle_share"] == round(1.89 / 3.005, 3), idle


def test_diagnose(tmp_path):
    """perf_diagnose gives a verdict from a summary's encoder numbers and asks to record again an older summary."""
    import metal_trace_mcp as mcp
    saved, mcp.OUT = mcp.OUT, tmp_path
    try:
        encoders = {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5},
                    "short_share": {"25": 0.497, "50": 0.572}, "by_label": []}
        (tmp_path / "new.json").write_text(json.dumps({"gpu": {"frames": 1378}, "encoders": encoders}))
        (tmp_path / "old.json").write_text(json.dumps({"gpu": {"frames": 1378}}))
        got = mcp.tool_perf_diagnose("new")
        assert got["too_many_short_encoders"] and not got["too_short"], got
        assert not mcp.tool_perf_diagnose("new", min_encoders=8)["too_many_short_encoders"]
        for run, kwargs, words in (("old", {}, "record it again"), ("new", {"short_us": 30}, "short_us is one of")):
            try:
                mcp.tool_perf_diagnose(run, **kwargs)
                raise AssertionError(f"{run} {kwargs} must fail")
            except mcp.ToolError as error:
                assert words in str(error), error
    finally:
        mcp.OUT = saved


def test_compare(tmp_path):
    """perf_compare reports encoder and idle changes and each label's change in GPU ms per frame, largest first,
    and names a run summarized before encoders existed instead of returning nothing for it."""
    import metal_trace_mcp as mcp

    def summary(frames, encoders, buffers, short, idle, labels):
        return {"gpu": {"frames": frames, "fps_estimate": 100.0},
                "encoders": {"per_frame": {"p50": encoders}, "command_buffers_per_frame": {"p50": buffers},
                             "short_share": {"25": short, "50": short},
                             "by_label": [{"label": n, "per_frame": c, "total_ms": t} for n, c, t in labels]},
                "gpu_idle": {"idle_share": idle, "idle_ms_per_frame": {"p50": idle * 10}}}
    saved, mcp.OUT = mcp.OUT, tmp_path
    try:
        # a: 100 frames; b: 200 frames, so Blit's total doubles while its ms per frame stays
        (tmp_path / "a.json").write_text(json.dumps(summary(100, 2, 1, 0.02, 0.4, [
            ("Render Command", 1.0, 500.0), ("Blit Command", 1.0, 10.0), ("Old Pass", 1.0, 50.0)])))
        (tmp_path / "b.json").write_text(json.dumps(summary(200, 7, 5, 0.5, 0.75, [
            ("Render Command", 3.0, 800.0), ("Blit Command", 4.0, 20.0), ("New Pass", 1.0, 400.0)])))
        (tmp_path / "old.json").write_text(json.dumps({"gpu": {"frames": 300, "fps_estimate": 90.0}}))
        got = mcp.tool_perf_compare("a", "b")
        assert got["encoders"]["encoders_per_frame_p50"] == {"a": 2, "b": 7, "change": 5, "change_pct": 250.0}
        assert got["encoders"]["short_encoder_share"] == {"a": 0.02, "b": 0.5, "change": 0.48, "change_pct": None}
        assert got["encoders"]["gpu_idle_share"]["change"] == 0.35, got["encoders"]
        assert [(r["label"], r["state"], r["ms_per_frame_change"]) for r in got["labels"]] == [
            ("New Pass", "new", 2.0), ("Render Command", "changed", -1.0), ("Old Pass", "gone", -0.5),
            ("Blit Command", "changed", 0.0)], got["labels"]
        assert got["metrics"]["fps"]["change"] == 0.0 and got["too_short"] == []
        old = mcp.tool_perf_compare("old", "b")
        assert old["encoders"]["missing_in"] == ["old"] and "labels" not in old, old
        assert old["metrics"]["fps"] == {"a": 90.0, "b": 100.0, "change": 10.0, "change_pct": 11.1}, old["metrics"]
        try:
            mcp.tool_perf_compare("a", "b", short_us=30)
            raise AssertionError("short_us 30 must fail")
        except mcp.ToolError as error:
            assert "short_us is one of" in str(error), error
    finally:
        mcp.OUT = saved


def test_baseline(tmp_path):
    """perf_baseline saves copies of several runs as a reference with their range, perf_runs leaves the reference
    file out, and perf_check judges a run against that range: same inside it, regressed when FPS falls below it by
    more than the margin or an encoder per frame is added, improved when FPS rises above it, and still usable once
    the reference's runs are deleted."""
    import metal_trace_mcp as mcp

    def summary(fps, gpu_ms, encoders, frames=300):
        return {"gpu": {"frames": frames, "fps_estimate": fps, "frame_gpu_ms": {"mean": gpu_ms, "p95": gpu_ms * 2},
                        "frame_interval_ms": {"p95": 20.0}},
                "encoders": {"per_frame": {"p50": encoders}, "command_buffers_per_frame": {"p50": 5},
                             "short_share": {"25": 0.5}, "by_label": [{"label": "Render", "per_frame": 1.0, "total_ms": 1.0}]},
                "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}}
    saved, (mcp.OUT, mcp.BASELINES) = (mcp.OUT, mcp.BASELINES), (tmp_path, tmp_path / "baselines.json")
    try:
        for name, fps in (("r1", 60.0), ("r2", 62.0), ("r3", 61.0)):
            (tmp_path / f"{name}.json").write_text(json.dumps(summary(fps, 4.3, 7)))
        got = mcp.tool_perf_baseline("ds", ["r1", "r2", "r3"])
        assert got["range"]["fps"] == {"min": 60.0, "max": 62.0} and got["runs"] == ["r1", "r2", "r3"], got
        assert [r["run"] for r in mcp.tool_perf_runs()["rows"]] == ["r3", "r2", "r1"]
        assert mcp.tool_perf_baseline()["baselines"][0]["name"] == "ds"
        cases = {"same": summary(59.0, 4.4, 7), "regressed_fps": summary(55.0, 4.3, 7),
                 "regressed_enc": summary(61.0, 4.3, 8), "improved": summary(65.0, 4.3, 7),
                 "short": summary(61.0, 4.3, 7, frames=50), "old": {"gpu": {"frames": 300, "fps_estimate": 61.0}}}
        for name, s in cases.items():
            (tmp_path / f"{name}.json").write_text(json.dumps(s))
        assert mcp.tool_perf_check("same", "ds")["verdict"] == "same"
        fps = mcp.tool_perf_check("regressed_fps", "ds")
        assert fps["verdict"] == "regressed" and fps["regressed"][0]["metric"] == "fps", fps
        enc = mcp.tool_perf_check("regressed_enc", "ds")
        assert [r["metric"] for r in enc["regressed"]] == ["encoders_per_frame_p50"], enc
        assert enc["comparison"]["encoders"]["encoders_per_frame_p50"]["b"] == 8
        assert mcp.tool_perf_check("improved", "ds")["verdict"] == "improved"
        assert "hint" in mcp.tool_perf_check("short", "ds")
        old = mcp.tool_perf_check("old", "ds")
        assert old["verdict"] == "same" and "encoders_per_frame_p50" in old["unchecked"], old
        for name in ("r1", "r2", "r3"):
            (tmp_path / f"{name}.json").unlink()
        assert mcp.tool_perf_check("same", "ds")["verdict"] == "same", "a reference outlives its runs"
        for bad in (("bad name!", ["same"]), ("nope", None), (None, ["same"])):
            try:
                mcp.tool_perf_baseline(*bad)
                raise AssertionError(bad)
            except mcp.ToolError:
                pass
        try:
            mcp.tool_perf_check("same", "nope")
            raise AssertionError("missing reference must fail")
        except mcp.ToolError as error:
            assert "no reference" in str(error)
    finally:
        mcp.OUT, mcp.BASELINES = saved


def test_trace_count(tmp_path):
    """trace_count counts a table's rows in all and per process, names tables the trace lacks, and refuses odd names."""
    import metal_trace_mcp as mcp
    table = ('<trace-query-result><node><schema><col><mnemonic>process</mnemonic></col><col><mnemonic>n</mnemonic></col>'
             '</schema><row><process id="1" fmt="wine (42)"><pid>42</pid></process><n>1</n></row>'
             '<row><process ref="1"/><n>2</n></row><row><process id="2" fmt="WindowServer (7)"><pid>7</pid></process>'
             '<n>3</n></row></node></trace-query-result>')
    calls = []

    def export(trace, xpath=None, **_):
        calls.append(xpath)
        path = tmp_path / f"t{len(calls)}.xml"
        path.write_text(table)
        return str(path)
    saved = mcp.perf_report.export, mcp.tool_trace_tables, mcp.OUT
    mcp.perf_report.export, mcp.tool_trace_tables, mcp.OUT = export, lambda t: {"tables": ["spill-events"]}, tmp_path
    try:
        (tmp_path / "r1.trace").mkdir()
        got = mcp.tool_trace_count("r1", ["spill-events", "time-profile"])
        assert got["tables"]["spill-events"] == {"rows": 3, "by_process": {"wine (42)": 2, "WindowServer (7)": 1}}, got
        assert got["tables"]["time-profile"]["rows"] is None and len(calls) == 1, got
        try:
            mcp.tool_trace_count("r1", ["x;y"])
            raise AssertionError("an odd table name must fail")
        except mcp.ToolError:
            pass
    finally:
        mcp.perf_report.export, mcp.tool_trace_tables, mcp.OUT = saved


def test_baseline_record(tmp_path):
    """perf_baseline_record records count runs named name-1.. with perf_record's arguments and saves them as the
    reference; count outside 1 to 10 fails before recording."""
    import metal_trace_mcp as mcp
    made = []

    def fake_record(label, **kw):
        made.append((label, kw))
        (tmp_path / f"{label}_20261018-000000.json").write_text(json.dumps(
            {"gpu": {"frames": 300, "fps_estimate": 60.0 + len(made), "frame_gpu_ms": {"mean": 4.0}},
             "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5}}}))
    saved = mcp.tool_perf_record, mcp.OUT, mcp.BASELINES
    mcp.tool_perf_record, mcp.OUT, mcp.BASELINES = fake_record, tmp_path, tmp_path / "baselines.json"
    try:
        got = mcp.tool_perf_baseline_record("ds", count=2, workload="drawstress", api="d3d12", seconds=30)
        assert [m[0] for m in made] == ["ds-1", "ds-2"] and made[0][1] == {"workload": "drawstress", "api": "d3d12", "seconds": 30}
        assert got["runs"] == ["ds-1_20261018-000000", "ds-2_20261018-000000"], got
        assert got["range"]["fps"] == {"min": 61.0, "max": 62.0}, got
        for bad in (0, 11):
            try:
                mcp.tool_perf_baseline_record("ds", count=bad)
                raise AssertionError(bad)
            except mcp.ToolError:
                pass
        assert len(made) == 2
    finally:
        mcp.tool_perf_record, mcp.OUT, mcp.BASELINES = saved


def test_layer(tmp_path):
    """A recording's layer fingerprint is stable, changes with any Direct3D DLL, carries the overrides and program
    variables, and perf_compare tells two layers from one."""
    import metal_trace_mcp as mcp
    wine, prefix = tmp_path / "mullion-wine", tmp_path / "prefix"
    (wine / "bin").mkdir(parents=True)
    (wine / "bin" / "wine").write_text("#!/bin/sh\necho wine-11.0\n")
    (wine / "bin" / "wine").chmod(0o755)
    builtin, system32 = wine / "lib" / "wine" / "x86_64-windows", prefix / "drive_c" / "windows" / "system32"
    builtin.mkdir(parents=True)
    system32.mkdir(parents=True)
    for name in mcp.LAYER_DLLS:
        (builtin / f"{name}.dll").write_bytes(name.encode())
    (system32 / "d3d12.dll").write_bytes(b"d3d12")
    (prefix / "user.reg").write_text('[Software\\\\Wine\\\\DllOverrides] 1\n"*d3d12"="native,builtin"\n"comctl32"="n"\n'
                                     '[Software\\\\Wine\\\\Other] 2\n"dxgi"="n"\n')
    saved = os.environ.get("WINEDLLOVERRIDES")
    os.environ["WINEDLLOVERRIDES"] = "d3d11=n"
    try:
        one = mcp.layer_of(str(wine), str(prefix), "MULLION_DIAG=profile LOG=/tmp/x/log.txt")
        assert one == mcp.layer_of(str(wine), str(prefix), "MULLION_DIAG=profile LOG=/tmp/x/log.txt")
    finally:
        os.environ.pop("WINEDLLOVERRIDES") if saved is None else os.environ.update(WINEDLLOVERRIDES=saved)
    assert one["wine"] == "mullion-wine" and one["wine_version"] == "wine-11.0", one
    assert one["overrides"] == {"environment": "d3d11=n;mscoree=;mshtml=", "registry": {"*d3d12": "native,builtin"}}
    assert one["dlls"]["d3d12"]["prefix"]["bytes"] == 5 and one["dlls"]["dxgi"]["prefix"] is None, one["dlls"]
    assert one["program_env"] == "MULLION_DIAG=profile LOG=log.txt" and str(tmp_path) not in json.dumps(one)
    (builtin / "d3d11.dll").write_bytes(b"other build")
    two = mcp.layer_of(str(wine), str(prefix))
    assert two["fingerprint"] != one["fingerprint"]
    # Wine's first boot copies its own DLLs into the prefix: the same DLL, so nothing changes
    (system32 / "dxgi.dll").write_bytes(b"dxgi")
    assert mcp.layer_of(str(wine), str(prefix))["fingerprint"] == two["fingerprint"]
    (system32 / "dxgi.dll").write_bytes(b"other dxgi")
    three = mcp.layer_of(str(wine), str(prefix))
    assert three["fingerprint"] != two["fingerprint"]
    assert mcp.layer_change({"layer": two}, {"layer": three}, "a", "b")["differs"] == ["dxgi"]
    (system32 / "dxgi.dll").unlink()
    assert mcp.layer_of("native", "-") == {"none": "native Metal, no translation layer", "program_env": ""}
    runs = {"one": one, "one-again": one, "two": two, "native": mcp.layer_of("native", "-"), "old": None}
    same = mcp.layer_change({"layer": runs["one"]}, {"layer": runs["one-again"]}, "a", "b")
    assert same["same"] and same["differs"] == [] and "program_env" not in same, same
    other = mcp.layer_change({"layer": runs["one"]}, {"layer": runs["two"]}, "a", "b")
    assert not other["same"] and other["differs"] == ["d3d11"] and "two layers" in other["note"], other
    assert other["program_env"] == {"a": "MULLION_DIAG=profile LOG=log.txt", "b": ""}
    assert not mcp.layer_change({"layer": runs["native"]}, {"layer": runs["one"]}, "a", "b")["same"]
    assert mcp.layer_change({}, {"layer": runs["one"]}, "old", "b")["missing_in"] == ["old"]
    assert mcp.layer_label(runs["native"]) == "native" and mcp.layer_label(one).endswith("mullion-wine wine-11.0")


def test_workloads(tmp_path):
    """workload_fetch keeps an archive whose SHA-256 matches and refuses one that does not or that would extract
    outside its directory; perf_record turns a fetched workload into its program, Wine and arguments."""
    import hashlib
    import tarfile
    import metal_trace_mcp as mcp
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
    saved = mcp.WORKLOADS, mcp.CACHE, mcp.download
    served = {}
    mcp.CACHE, mcp.download = tmp_path / "cache", lambda url, path, max_bytes: shutil.copy(served["file"], path)
    try:
        for archive, sha, words in ((good, "0" * 64, "does not match"),
                                    (evil, hashlib.sha256(evil.read_bytes()).hexdigest(), "may not be extracted")):
            mcp.WORKLOADS, served["file"] = {"demo": {**entry, "sha256": sha}}, archive
            try:
                mcp.tool_workload_fetch("demo")
                raise AssertionError(f"{archive.name} must be refused")
            except mcp.ToolError as error:
                assert words in str(error), error
            assert not any(p.name.startswith("demo-") for p in mcp.CACHE.iterdir()), list(mcp.CACHE.iterdir())
        assert not (tmp_path / "escape").exists()
        mcp.WORKLOADS, served["file"] = {"demo": {**entry, "sha256": hashlib.sha256(good.read_bytes()).hexdigest()}}, good
        assert mcp.tool_workload_list()["workloads"][0]["fetched"] is False
        try:
            mcp.workload_command("demo", "mtl", None, None, "")
            raise AssertionError("an unfetched workload must fail")
        except mcp.ToolError as error:
            assert "workload_fetch" in str(error), error
        assert mcp.tool_workload_fetch("demo")["downloaded"] and not mcp.tool_workload_fetch("demo")["downloaded"]
        program, wine, args, env = mcp.workload_command("demo", "mtl", 20, "/opt/wine", "-x")
        assert program.is_file() and os.access(program, os.X_OK) and wine == "native", program
        assert (args, env) == ("--mtl -x", "DIM=20"), (args, env)
        assert mcp.workload_command("demo", "d3d12", None, "/opt/wine", "")[1:] == ("/opt/wine", "--d3d12", "")
        for api in ("vulkan", None):
            try:
                mcp.workload_command("demo", api, None, None, "")
                raise AssertionError(f"api {api} must fail")
            except mcp.ToolError as error:
                assert "api is one of mtl, d3d12" in str(error), error
    finally:
        mcp.WORKLOADS, mcp.CACHE, mcp.download = saved
    shipped = json.loads((TOOLS / "data" / "workloads.json").read_text())["workloads"]["drawstress"]
    assert len(shipped["sha256"]) == 64 and shipped["sha256"] != "0" * 64 and shipped["url"].startswith("https://")


def test_capture(tmp_path):
    """A small MTSP stream is read record by record, and the summary names the capture without its path."""
    summary = gputrace_read.summarize(write_capture(tmp_path))
    assert summary["capture"] == "frame.gputrace" and summary["draw_primitives"] == 3, summary


def test_server(tmp_path):
    """The server answers on stdout with JSON only, pages lists, refuses paths outside its directories and turns
    failures into isError results."""
    out = tmp_path / "runs"
    out.mkdir()
    for i in range(3):
        (out / f"run{i}_x.json").write_text(json.dumps({"gpu": {"frames": 100 * i}}))
    (out / "run3_x.json").write_text('{"gpu": {')
    (out / "run1_x.trace").mkdir()
    write_capture(out)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {"limit": 2}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "trace_tables", "arguments": {"trace": str(out / "gone.trace")}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "trace_tables", "arguments": {"trace": "/etc/hosts"}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "perf_compare", "arguments": {"a": "run0_x", "b": "../x"}}},
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {"bad": 1}}},
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "nope"}},
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
         "params": {"name": "gpu_family", "arguments": {"name": "M1 Pro"}}},
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
         "params": {"name": "gpu_family", "arguments": {"name": "Z80"}}},
        {"jsonrpc": "2.0", "id": 11, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 12, "method": "resources/read", "params": {"uri": "metal-trace://gpu-families/apple9"}},
        {"jsonrpc": "2.0", "id": 13, "method": "resources/read", "params": {"uri": "metal-trace://nope"}},
        {"jsonrpc": "2.0", "id": 14, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
        [1],
        {"jsonrpc": "2.0", "id": 15, "method": "ping"},
        {"jsonrpc": "2.0", "id": 16, "method": "tools/list", "params": [1]},
        {"jsonrpc": "2.0", "id": 17, "method": "resources/templates/list"},
        {"jsonrpc": "2.0", "id": 18, "method": "tools/call",
         "params": {"name": "perf_attach", "arguments": {"label": "a", "process": "no-such-program-4242.exe"}}},
        {"jsonrpc": "2.0", "id": 19, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 20, "method": "tools/call",
         "params": {"name": "trace_tables", "arguments": {"trace": "run0_x"}}},
        {"jsonrpc": "2.0", "id": 21, "method": "tools/call",
         "params": {"name": "capture_summary", "arguments": {"capture": str(out / "frame.gputrace")}}},
        {"jsonrpc": "2.0", "id": 22, "method": "prompts/list"},
        {"jsonrpc": "2.0", "id": 23, "method": "prompts/get",
         "params": {"name": "compare-layer", "arguments": {"workload": "drawstress", "api": "d3d11"}}},
        {"jsonrpc": "2.0", "id": 24, "method": "prompts/get",
         "params": {"name": "compare-layer", "arguments": {"api": "d3d12; rm -rf /"}}},
        {"jsonrpc": "2.0", "id": 25, "method": "prompts/get", "params": {"name": "nope"}},
    ]
    proc = subprocess.run([sys.executable, "-I", str(TOOLS / "metal_trace_mcp.py")], text=True, capture_output=True,
                          input="\n".join(json.dumps(r) for r in requests) + "\n", timeout=60,
                          env=dict(os.environ, METAL_TRACE_OUT=str(out), METAL_TRACE_LOG="info"))
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    replies = {r["id"]: r for r in lines if r["id"] is not None}
    assert sorted(replies) == list(range(1, 26)), (replies, proc.stderr)
    assert [p["name"] for p in replies[22]["result"]["prompts"]] == ["compare-layer"]
    steps = replies[23]["result"]["messages"][0]["content"]["text"]
    assert all(w in steps for w in ("api=d3d11", "workload=drawstress", "perf_compare a=", "labels")), steps
    # an argument that is not a plain name is dropped, so the default api stays
    assert "rm -rf" not in replies[24]["result"]["messages"][0]["content"]["text"]
    assert replies[25]["error"]["code"] == -32602
    assert replies[1]["result"]["capabilities"]["prompts"] == {}
    assert [r["error"]["code"] for r in lines if r["id"] is None] == [-32600], lines
    assert replies[14]["result"]["protocolVersion"] == "2025-06-18"
    assert replies[15]["result"] == {} and replies[16]["error"]["code"] == -32600
    assert replies[17]["result"] == {"resourceTemplates": []}
    assert len(replies[2]["result"]["tools"]) == 16
    assert replies[1]["result"]["capabilities"]["resources"] == {}
    assert "KEEP_TRACE=1" in replies[1]["result"]["instructions"]
    hints = {t["name"]: t["annotations"] for t in replies[2]["result"]["tools"]}
    asks = [t["name"] for t in replies[2]["result"]["tools"] if t.get("_meta", {}).get("anthropic/requiresUserInteraction")]
    assert asks == ["workload_fetch"] and hints["workload_fetch"]["openWorldHint"], (asks, hints)
    assert hints["perf_record"]["destructiveHint"] and not hints["perf_attach"]["destructiveHint"], hints
    assert hints["perf_runs"]["readOnlyHint"] and all(h["title"] for h in hints.values()), hints
    m1 = replies[9]["result"]["structuredContent"]
    assert m1["family"] == "Apple7" and m1["limits"]["mesh_grid_threadgroups"] == 1024, m1
    assert replies[10]["result"]["isError"] and "Apple7" in replies[10]["result"]["content"][0]["text"]
    assert len(replies[11]["result"]["resources"]) == 5
    apple9 = json.loads(replies[12]["result"]["contents"][0]["text"])
    assert apple9["family"] == "Apple9" and apple9["sources"]["feature_set_tables"].startswith("https://"), apple9
    assert replies[13]["error"]["code"] == -32002
    runs = replies[3]["result"]["structuredContent"]
    assert runs["total"] == 3 and len(runs["rows"]) == 2 and runs["next_offset"] == 2, runs
    kept = {r["run"]: r["trace_kept"] for r in replies[19]["result"]["structuredContent"]["rows"]}
    assert kept == {"run0_x": False, "run1_x": True, "run2_x": False}, kept
    capture = replies[21]["result"]["structuredContent"]
    assert capture["calls_total"] == 1 and len(capture["calls"]) == 1, capture
    for mid, words in ((4, "KEEP_TRACE"), (5, "outside"), (6, "only letters"), (7, "bad arguments"),
                       (18, "no running process matches"), (20, "KEEP_TRACE")):
        result = replies[mid]["result"]
        assert result.get("isError") and words in result["content"][0]["text"], (mid, result)
        assert str(tmp_path) not in result["content"][0]["text"], (mid, result)
    assert replies[8]["error"]["code"] == -32602
    assert proc.stderr.count("metal-trace:") == 11, proc.stderr


def test_no_runs_directory(tmp_path):
    """A server that only lists recordings does not create the recordings directory."""
    out = tmp_path / "never"
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "perf_runs", "arguments": {}}}
    proc = subprocess.run([sys.executable, "-I", str(TOOLS / "metal_trace_mcp.py")], text=True, capture_output=True,
                          input=json.dumps(request) + "\n", timeout=60,
                          env=dict(os.environ, METAL_TRACE_OUT=str(out), METAL_TRACE_LOG="off"))
    assert json.loads(proc.stdout)["result"]["structuredContent"]["total"] == 0, proc.stdout
    assert not out.exists()


def test_overrun(tmp_path):
    """A recording that overruns its deadline is stopped and leaves no files and no lock behind, and the deadline
    covers reading back a 60 s recording (87 s per 10 s on an M1 Pro)."""
    import metal_trace_mcp as mcp
    assert mcp.deadline(60) > 87 * 6
    stubs, out = tmp_path / "stubs", tmp_path / "overrun"
    stubs.mkdir()
    out.mkdir()
    # an xctrace that starts its .trace and never finishes
    xcrun = stubs / "xcrun"
    xcrun.write_text("#!/bin/zsh\nwhile [[ $1 != --output ]]; do shift; done\nmkdir -p $2\nsleep 60\n")
    xcrun.chmod(0o755)
    program = tmp_path / "hang-4242"
    program.touch()
    saved = mcp.OUT, mcp.deadline, os.environ["PATH"]
    mcp.OUT, mcp.deadline = out, lambda seconds: 3
    os.environ["PATH"] = f"{stubs}:{saved[2]}"
    try:
        mcp.tool_perf_record("hang", str(program), seconds=1, wine="native")
        raise AssertionError("an overrunning recording must fail")
    except mcp.ToolError as error:
        assert "stopped" in str(error), error
    finally:
        mcp.OUT, mcp.deadline, os.environ["PATH"] = saved
    assert not list(out.iterdir()), list(out.iterdir())


def main():
    tests = [test_report, test_encoders, test_diagnose, test_compare, test_baseline, test_trace_count, test_baseline_record, test_layer, test_workloads, test_capture, test_server, test_no_runs_directory, test_overrun]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(pathlib.Path(tmp).resolve())
    print("ok")


if __name__ == "__main__":
    main()
