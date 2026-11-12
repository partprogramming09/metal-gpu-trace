"""Adversarial tests of panel.py: summaries, frames and memory files, baselines.json, panel.json and neighbour recordings
that arrive broken, truncated, mistyped or hostile; run names, skip_s and layout arguments; what the page shows against
what the summary says. The contract: panel_data raises paths.ToolError or nothing, never another exception; no value
carries an absolute path; a broken reference says why instead of stopping the panel.

Tests named test_bug_* reproduce a failure found while attacking the module (each lists every minimal input that
failed, as `label: ExceptionType: message`); test_spec_* fail on a point where the specification is ambiguous (see
their docstrings); the others pass and cover what no test covered."""
import contextlib
import copy
import json
import os
import random
import sys
import tempfile

from support import ROOT  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import analysis, config, panel, paths

HEADER = "frame,start_ms,gpu_ms_total\n"
FRAMES = HEADER + "".join(f"{i + 1},{i * 16.0},4.0\n" for i in range(200))
MEMORY = "time_ms,metal_allocated_bytes\n0,1048576\n16,2097152\n"
WINE = {"fingerprint": "dxmt", "wine": "wine-9", "wine_version": "9.0"}
DEEP = "[" * 1_000_000  # RecursionError in json.loads on every supported Python
GOOD = {"gpu": {"frames": 400, "fps_estimate": 60.0, "fps_1pct_low": 50.0,
                "frame_gpu_ms": {"mean": 4.0, "p50": 4.0, "p95": 5.0}, "frame_interval_ms": {"p95": 20.0}},
        "encoders": {"per_frame": {"p50": 7}, "command_buffers_per_frame": {"p50": 5}, "short_share": {"25": 0.5},
                     "by_label": [{"label": "x", "per_frame": 1.0, "total_ms": 5.0}]},
        "gpu_idle": {"idle_share": 0.4, "idle_ms_per_frame": {"p50": 4}}, "duration_s": 60.0, "layer": {"none": "native"},
        "hitches": {"count": 1, "threshold_ms": 30.0, "worst": [{"frame": 3, "cause": "x", "cpu_pct": 1.0}]},
        "cpu": {"mean": 20.0}, "thermal_state_share": {"Nominal": 1.0}, "metal_memory_mib": {"peak": 90.0},
        "process": {"arguments": "game.exe"}, "device": {"platform": "macOS"}}


def summary(**changes):
    """Returns a copy of GOOD with each dotted key of `changes` ("gpu.frames") set to its value."""
    s = copy.deepcopy(GOOD)
    for dotted, value in changes.items():
        *path, last = dotted.split(".")
        node = s
        for key in path:
            node = node[key]
        node[last] = value
    return s


def reference(*summaries, runs=("r1",), **extra):
    """Returns a baselines.json holding the reference `ref`."""
    return {"ref": {"runs": list(runs), "summaries": list(summaries) or [GOOD], **extra}}


def dump(content):
    if isinstance(content, bytes):
        return content
    return (content if isinstance(content, str) else json.dumps(content)).encode("utf-8")


@contextlib.contextmanager
def workspace(tmp_path, files, baseline=None, points=None):
    """Points config at a new runs folder holding `files` ({name: str, bytes or JSON-able}); `baseline` makes the
    project use that reference. Yields the folder."""
    folder = type(tmp_path)(tempfile.mkdtemp(dir=tmp_path))
    for name, content in files.items():
        (folder / name).write_bytes(dump(content))
    saved = config.OUT, config.BASELINES, config.PROJECT, config.PANEL_POINTS
    config.OUT, config.BASELINES = folder, folder / "baselines.json"
    config.PROJECT = None if baseline is None else {"name": "p", "profile": "generic", "baseline": baseline,
                                                    "format": "metal-gpu-trace", "runs": folder}
    if points:
        config.PANEL_POINTS = points
    try:
        yield folder
    finally:
        config.OUT, config.BASELINES, config.PROJECT, config.PANEL_POINTS = saved


def crashes(tmp_path, cases, call, baseline=None):
    """Runs call() once per (label, files) case in its own folder and returns a line for each that raised anything but
    ToolError: the contract is a ToolError or a payload, nothing else."""
    found = []
    for label, files in cases:
        with workspace(tmp_path, files, baseline):
            try:
                call()
            except paths.ToolError:
                pass
            except BaseException as error:  # a RecursionError or MemoryError must show up too
                found.append(f"{label}: {type(error).__name__}: {str(error)[:70]}")
    return found


def open_panel(*runs, **kwargs):
    return lambda: panel.panel_data(list(runs), **kwargs)


def one_run(s, frames=FRAMES, **others):
    return {"a.json": s, "a.frames.csv": frames, **others}


def readable_by_others():
    """Returns whether a chmod 000 file is still unreadable for this process (not on Windows, not as root)."""
    return sys.platform != "win32" and os.geteuid() != 0


# --- a summary with a section of the wrong type -------------------------------------------------------------------------

def test_bug_a_section_of_the_wrong_type_crashes_panel_data(tmp_path):
    """`"gpu": "x"`, `"hitches": 5`... in a summary: panel_data must answer or say ToolError, not AttributeError."""
    cases = [(f"{key}={bad!r}", one_run(summary(**{key: bad})))
             for key in ("gpu", "hitches", "encoders", "cpu", "device", "gpu_idle", "metal_memory_mib", "process_rss_mib")
             for bad in ("x", 5, [1], True)]
    assert not (found := crashes(tmp_path, cases, open_panel("a"))), "\n".join(found)


def test_bug_a_null_section_crashes_a_two_run_panel(tmp_path):
    """The comparison reads s.get("metal_memory_mib", {}).get(...), which a null defeats: with two runs, one with
    `"metal_memory_mib": null` (or process_rss_mib, or gpu) raises AttributeError."""
    cases = [(f"{key}=null", {**one_run(summary(**{key: None})), "b.json": GOOD, "b.frames.csv": FRAMES})
             for key in ("metal_memory_mib", "process_rss_mib", "gpu", "gpu_idle")]
    cases += [("encoders.per_frame=null", {**one_run(summary(**{"encoders.per_frame": None})), "b.json": GOOD, "b.frames.csv": FRAMES}),
              ("gpu.frame_gpu_ms=null", {**one_run(summary(**{"gpu.frame_gpu_ms": None})), "b.json": GOOD, "b.frames.csv": FRAMES})]
    assert not (found := crashes(tmp_path, cases, open_panel("b", "a"))), "\n".join(found)


def test_bug_a_layer_that_is_not_an_object_crashes_panel_data(tmp_path):
    """layer_label indexes the layer as a dict: a string, number or list raises TypeError, `{"a": 1}` raises KeyError."""
    cases = [(f"layer={bad!r}", one_run(summary(layer=bad))) for bad in ("x", 5, [1], True, {"a": 1})]
    assert not (found := crashes(tmp_path, cases, open_panel("a"))), "\n".join(found)


def test_bug_a_number_of_the_wrong_type_crashes_panel_data(tmp_path):
    """Numbers written as text (`"frames": "400"`), a null where a list goes (`"worst": null`) and the like."""
    wine = lambda **c: summary(layer=WINE, **c)  # noqa: E731  (short_wine reads duration_s only for a Wine layer)
    cases = [("gpu.frames='400'", one_run(summary(**{"gpu.frames": "400"}))),
             ("gpu.frames=[1]", one_run(summary(**{"gpu.frames": [1]}))),
             ("duration_s='60' on wine", one_run(wine(duration_s="60"))),
             ("hitches.threshold_ms='30'", one_run(summary(**{"hitches.threshold_ms": "30"}))),
             ("hitches.worst=null", one_run(summary(**{"hitches.worst": None}))),
             ("hitches.worst=[{}]", one_run(summary(**{"hitches.worst": [{}]}))),
             ("hitches.worst=[null]", one_run(summary(**{"hitches.worst": [None]}))),
             ("hitches.worst=[{'frame': [1]}]", one_run(summary(**{"hitches.worst": [{"frame": [1]}]}))),
             ("encoders.by_label=null", one_run(summary(**{"encoders.by_label": None}))),
             ("encoders.by_label={}", one_run(summary(**{"encoders.by_label": {"a": 1}})))]
    assert not (found := crashes(tmp_path, cases, open_panel("a"))), "\n".join(found)


def test_bug_a_summary_file_that_is_not_a_summary_crashes_panel_data(tmp_path):
    """A summary file cut by a crash, empty, not UTF-8, or valid JSON that is not an object."""
    cases = [(label, one_run(text)) for label, text in (
        ("empty", ""), ("truncated", '{"gpu": {"frames": 4'), ("list", "[]"), ("null", "null"), ("string", '"x"'),
        ("number", "5"), ("not utf-8", b"\xff\xfe\x00"), ("BOM", b"\xef\xbb\xbf{}"),
        ("5000-digit integer", '{"gpu": {"frames": ' + "9" * 5000 + "}}"))]
    assert not (found := crashes(tmp_path, cases, open_panel("a"))), "\n".join(found)


def test_bug_deeply_nested_json_in_a_summary_raises_recursionerror(tmp_path):
    found = crashes(tmp_path, [("a.json is 1 000 000 '['", one_run(DEEP))], open_panel("a"))
    assert not found, "\n".join(found)


# --- frames.csv and metal_memory.csv that arrive broken ------------------------------------------------------------------

def test_bug_a_frames_csv_cut_in_its_last_row_crashes_panel_data(tmp_path):
    """The recorder killed while writing leaves "2,16.0" with no third field: DictReader gives None and float(None)
    raises TypeError. The smallest reproducer of the whole family below."""
    found = crashes(tmp_path, [("last row cut", one_run(GOOD, HEADER + "1,0.0,4.0\n2,16.0"))], open_panel("a"))
    assert not found, "\n".join(found)


def test_bug_a_malformed_frames_csv_crashes_panel_data(tmp_path):
    cases = [(label, one_run(GOOD, text)) for label, text in (
        ("frame is not an int", HEADER + "x,0.0,4.0\n"), ("start is text", HEADER + "1,abc,4.0\n"),
        ("empty field", HEADER + "1,,4.0\n"), ("frame is 1.5", HEADER + "1.5,0.0,4.0\n"),
        ("BOM before the header", "﻿" + HEADER + "1,0.0,4.0\n2,16.0,4.0\n"), ("other header", "a,b,c\n1,2,3\n"),
        ("NUL in a field", HEADER + "1,0.0,4.0\x00\n"), ("not UTF-8", b"\xff\xfe\x00\x01"),
        ("5000-digit frame", HEADER + "1" * 5000 + ",0.0,4.0\n"), ("field over 131072 characters", HEADER + "1,0.0," + "9" * 200000 + "\n"),
        ("quote never closed", HEADER + '"1,0.0,4.0\n'))]
    assert not (found := crashes(tmp_path, cases, open_panel("a"))), "\n".join(found)
    assert not (found := crashes(tmp_path, [(f"skip_s=0.5 {l}", f) for l, f in cases], open_panel("a", skip_s=0.5))), "\n".join(found)


def test_bug_a_malformed_metal_memory_csv_crashes_panel_data(tmp_path):
    head = "time_ms,metal_allocated_bytes\n"
    cases = [(label, one_run(GOOD, FRAMES, **{"a.metal_memory.csv": text})) for label, text in (
        ("last row cut", MEMORY + "32,"), ("bytes as 1.5e6", head + "0,1.5e6\n"), ("bytes as 1048576.0", head + "0,1048576.0\n"),
        ("BOM before the header", "﻿" + MEMORY), ("other header", "x,y\n1,2\n"),
        ("400-digit bytes", head + "0," + "9" * 400 + "\n"), ("5000-digit bytes", head + "0," + "9" * 5000 + "\n"))]
    assert not (found := crashes(tmp_path, cases, open_panel("a"))), "\n".join(found)


def test_bug_files_that_are_directories_or_unreadable_crash_panel_data(tmp_path):
    """A recordings folder with a directory named a.json or a.frames.csv, or files the user cannot read."""
    cases = []
    for name, make in (("a.json", {"a.frames.csv": FRAMES}), ("a.frames.csv", {"a.json": GOOD}),
                       ("a.metal_memory.csv", {"a.json": GOOD, "a.frames.csv": FRAMES})):
        cases.append((f"{name} is a directory", make))
    found = []
    for name, files in cases:
        with workspace(tmp_path, files) as folder:
            (folder / name.split(" ")[0]).mkdir()
            try:
                panel.panel_data(["a"])
            except paths.ToolError:
                pass
            except Exception as error:
                found.append(f"{name}: {type(error).__name__}: {str(error)[:60].replace(str(folder), '<dir>')}")
    if readable_by_others():
        for name in ("a.json", "a.frames.csv", "a.metal_memory.csv"):
            with workspace(tmp_path, one_run(GOOD, FRAMES, **{"a.metal_memory.csv": MEMORY})) as folder:
                (folder / name).chmod(0)
                try:
                    panel.panel_data(["a"])
                except paths.ToolError:
                    pass
                except Exception as error:
                    found.append(f"{name} mode 000: {type(error).__name__}")
                finally:
                    (folder / name).chmod(0o644)
    assert not found, "\n".join(found)


# --- run names, runs, skip_s and presets ----------------------------------------------------------------------------------

def test_bug_a_run_named_panel_reads_the_layout_as_a_summary(tmp_path):
    """run_path refuses baselines.json but not panel.json, which holds a list: panel_data(["panel"]) raises
    AttributeError once a layout is saved (and "Panel", where the disk ignores case)."""
    cases = [("run 'panel'", {**one_run(GOOD), "panel.json": [{"id": "tests", "on": True}]})]
    assert not (found := crashes(tmp_path, cases, open_panel("panel"))), "\n".join(found)


def test_bug_runs_that_are_not_names_crash_panel_data(tmp_path):
    """A caller that is not the HTTP endpoint (a library call, a client with a loose schema) passes numbers or null."""
    found = []
    for runs in (None, 5, [None], [5], [["a"]], [{"a": 1}]):
        found += crashes(tmp_path, [(f"runs={runs!r}", one_run(GOOD))], lambda runs=runs: panel.panel_data(runs))
    assert not found, "\n".join(found)


def test_bug_skip_s_too_big_for_a_float_raises_overflowerror(tmp_path):
    """check_skip turns TypeError and ValueError into ToolError but float(10**400) raises OverflowError."""
    found = crashes(tmp_path, [("skip_s=10**400", one_run(GOOD))], open_panel("a", skip_s=10 ** 400))
    assert not found, "\n".join(found)


def test_names_that_could_leave_the_folder_are_refused_without_a_path(tmp_path):
    names = ("..", ".", "", "a/b", "../a", "a\\b", "a\x00b", "a b", "~", "a\n", "a‮", "/etc/passwd", "a:b", "é/a")
    with workspace(tmp_path, one_run(GOOD)) as folder:
        for name in names:
            try:
                panel.panel_data([name])
                raise AssertionError(f"{name!r} must be refused")
            except paths.ToolError as error:
                assert str(folder) not in str(error), (name, error)
        for name in ("é", "٣", "a.json", "a.frames", "baselines", "Baselines"):
            try:
                panel.panel_data([name])
                raise AssertionError(f"{name!r} is no run")
            except paths.ToolError as error:
                assert str(folder) not in str(error), (name, error)


def test_bug_a_long_run_name_raises_oserror_on_python_3_9(tmp_path):
    """run_path calls Path.exists() on `<run>.json`: before Python 3.12 a name over the file system's limit (255 bytes)
    raises OSError ENAMETOOLONG instead of answering False, so panel_data(["x" * 300]) fails with OSError, not ToolError.
    Passes on 3.15; run it with the project's minimum Python (3.9) to see it fail."""
    found = []
    for length in (250, 300, 5000):
        found += crashes(tmp_path, [(f"run of {length} characters", one_run(GOOD))], lambda n=length: panel.panel_data(["x" * n]))
    assert not found, "\n".join(found)


def test_runs_with_unicode_names_open_and_nothing_else_does(tmp_path):
    with workspace(tmp_path, {"é.json": GOOD, "é.frames.csv": FRAMES, "٣.json": GOOD}):
        got = panel.panel_data(["é"])
        assert got["runs"][0]["name"] == "é" and got["runs"][0]["has"]["frames"]
        assert panel.panel_data(["٣"])["runs"][0]["name"] == "٣"
        assert [w["id"] for w in panel.panel_data(["é", "٣"])["warnings"]].count("single_run_each") == 1


def test_skip_s_extremes_and_presets_are_refused_with_a_toolerror(tmp_path):
    with workspace(tmp_path, {**one_run(GOOD), "b.json": GOOD, "b.frames.csv": FRAMES}):
        for skip in (-1, 601, "x", "nan", "inf", float("nan"), float("inf"), -float("inf"), [1], "1e3", "0x10", 600):
            try:
                panel.panel_data(["a"], skip_s=skip)
                raise AssertionError(f"skip_s={skip!r} must be refused")
            except paths.ToolError:
                pass
        for skip in (None, "", 0, "0", False, [], 1e-320, "0.5", True):
            panel.panel_data(["a"], skip_s=skip)  # tolerated: no cut or a cut shorter than a frame
        for preset, runs in (("x", ["a"]), ("FPS", ["a"]), (5, ["a"]), (["fps"], ["a"]), ("compare", ["a"]), ("fps", []),
                             ("fps", ["a", "b", "a"]), (None, [])):
            try:
                panel.panel_data(runs, preset)
                raise AssertionError(f"{preset!r} with {runs} must be refused")
            except paths.ToolError:
                pass
        assert panel.panel_data(["a", "b"])["preset"] == "compare" and panel.panel_data(["a"], "")["preset"] == "fps"


# --- baselines.json (the reference) -------------------------------------------------------------------------------------

def reference_cases(entries):
    """Returns (label, files) cases: one run `a` and a baselines.json holding each entry as the reference `ref`."""
    return [(label, {**one_run(GOOD), "r1.json": GOOD, "r1.frames.csv": FRAMES, "baselines.json": {"ref": entry}})
            for label, entry in entries]


def test_bug_a_reference_that_is_empty_or_falsy_crashes_panel_data(tmp_path):
    """tests_mode asks `saved is None`, so {}, [], 0, false and "" pass as a found reference: spreads(None) or
    ref.get(...) then raises AttributeError."""
    cases = reference_cases([("{}", {}), ("[]", []), ("0", 0), ("false", False), ('""', "")])
    assert not (found := crashes(tmp_path, cases, open_panel("a"), baseline="ref")), "\n".join(found)


def test_bug_reference_summaries_that_are_not_objects_crash_panel_data(tmp_path):
    """ranges() swallows TypeError, so a list of strings passes it; then changes_against and perf_check call .get."""
    base = {"runs": ["r1"], "skip_s": 0}
    cases = reference_cases([(f"summaries={bad!r}", {**base, "summaries": bad})
                             for bad in (["junk"], [None], [5], [[]], "abc", {"a": 1}, [GOOD, "junk"])])
    assert not (found := crashes(tmp_path, cases, open_panel("a"), baseline="ref")), "\n".join(found)
    assert not (found := crashes(tmp_path, cases, open_panel("a", "a"), baseline="ref")), "\n".join(found)


def test_bug_reference_summaries_with_wrong_types_crash_panel_data(tmp_path):
    """A summary inside baselines.json with text where a number goes, null where an object goes, or a huge integer."""
    fps = lambda value: summary(**{"gpu.fps_estimate": value})  # noqa: E731
    entries = [("fps='60' (one summary)", [fps("60")]), ("fps='60' and '62'", [fps("60"), fps("62")]), ("fps=[60]", [fps([60])]),
               ("fps=10**400", [fps(10 ** 400)]), ("gpu='x'", [summary(gpu="x")]), ("gpu=null", [summary(gpu=None)]),
               ("device='x'", [summary(device="x")]), ("encoders='x'", [summary(encoders="x")]),
               ("metal_memory_mib=null", [summary(metal_memory_mib=None)]), ("metal_memory_mib='x'", [summary(metal_memory_mib="x")]),
               ("metal_memory_mib.peak='9'", [summary(**{"metal_memory_mib.peak": "9"})]), ("process='x'", [summary(process="x")]),
               ("gpu.frame_gpu_ms='x'", [summary(**{"gpu.frame_gpu_ms": "x"})])]
    cases = reference_cases([(label, {"runs": ["r1"], "summaries": s}) for label, s in entries])
    assert not (found := crashes(tmp_path, cases, open_panel("a"), baseline="ref")), "\n".join(found)


def test_bug_deeply_nested_json_in_baselines_json_raises_recursionerror(tmp_path):
    """load_baselines is guarded against ValueError, not RecursionError (json.loads raises it on nesting)."""
    cases = [("baselines.json is 1 000 000 '['", {**one_run(GOOD), "baselines.json": DEEP})]
    assert not (found := crashes(tmp_path, cases, open_panel("a"), baseline="ref")), "\n".join(found)


def test_a_reference_that_cannot_be_read_leaves_the_panel_open_and_says_why(tmp_path):
    base = {"runs": ["r1"], "summaries": [GOOD]}
    entries = [("skip_s='abc'", {**base, "skip_s": "abc"}), ("skip_s=-1", {**base, "skip_s": -1}), ("skip_s=1e9", {**base, "skip_s": 1e9}),
               ("skip_s=null", {**base, "skip_s": None}), ("skip_s=[1]", {**base, "skip_s": [1]}), ("skip_s=true", {**base, "skip_s": True}),
               ("summaries=[]", {**base, "summaries": []}), ("runs='r1'", {**base, "runs": "r1"}), ("runs=null", {**base, "runs": None}),
               ("runs=[1,null,[2]]", {**base, "runs": [1, None, [2]]}), ("runs missing", {"summaries": [GOOD]}),
               ("fps=nan", {**base, "summaries": [summary(**{"gpu.fps_estimate": float("nan")})]}),
               ("fps=inf", {**base, "summaries": [summary(**{"gpu.fps_estimate": float("inf")})]}),
               ("fps=0", {**base, "summaries": [summary(**{"gpu.fps_estimate": 0})]}),
               ("fps=true", {**base, "summaries": [summary(**{"gpu.fps_estimate": True})]}),
               ("null", None)]
    cases = [(label, {**one_run(GOOD), "r1.json": GOOD, "r1.frames.csv": FRAMES, "baselines.json": {"ref": entry}}) for label, entry in entries]
    cases += [(f"baselines.json {label}", {**one_run(GOOD), "baselines.json": text}) for label, text in (
        ("empty", ""), ("not JSON", "{x"), ("not UTF-8", b"\xff"), ("BOM", b"\xef\xbb\xbf{}"), ("list", "[]"), ("null", "null"),
        ("string", '"x"'), ("number", "5"), ("5000-digit integer", '{"ref": ' + "9" * 5000 + "}"))]
    for label, files in cases:
        for skip in (0, 0.5):
            with workspace(tmp_path, files, baseline="ref"):
                got = panel.panel_data(["a", "a"], skip_s=skip)  # any exception here is a failure of this test
                assert (got["tests"] is None) == (got["tests_hint"] is not None), (label, got["tests_hint"])
                assert got["changes"] is None or isinstance(got["changes"]["runs"], list), label
                json.dumps(got)
    with workspace(tmp_path, one_run(GOOD), baseline="ref") as folder:  # baselines.json that is a directory or unreadable
        (folder / "baselines.json").mkdir()
        assert panel.panel_data(["a"])["tests_hint"] == "baseline_not_found"


def test_panel_data_writes_nothing_and_answers_the_same_twice(tmp_path):
    files = {**one_run(GOOD, FRAMES, **{"a.metal_memory.csv": MEMORY}), "r1.json": GOOD, "r1.frames.csv": FRAMES, "baselines.json": reference(GOOD),
             "panel.json": [{"id": "tests", "on": True}]}
    with workspace(tmp_path, files, baseline="ref") as folder:
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}
        first = panel.panel_data(["a"], skip_s=1)
        assert panel.panel_data(["a"], skip_s=1) == first
        assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()} == before


# --- changes_against: the neighbour recordings --------------------------------------------------------------------------

def neighbour_cases(tmp_path, bad_summaries):
    """Returns (label, files) cases: the reference r1 plus one recording of the same program holding `bad`."""
    return [(label, {"r1.json": GOOD, "r1.frames.csv": FRAMES, "x.json": bad, "x.frames.csv": FRAMES}) for label, bad in bad_summaries]


def test_bug_a_neighbour_with_a_text_or_huge_metric_breaks_changes_against(tmp_path):
    """Another recording of the program with `"fps_estimate": "60"` (or a list, or 10**400) raises TypeError or
    OverflowError in round(100 * (value - mean) / mean): the one bad file stops the panel for every run."""
    bad = [(f"{path}={value!r}"[:48], summary(**{path: value})) for path in ("gpu.fps_estimate", "gpu.frame_gpu_ms.mean",
                                                                              "encoders.per_frame.p50", "metal_memory_mib.peak")
           for value in ("60", [1], 10 ** 400)] + [("device='x'", summary(device="x"))]
    found = []
    for label, files in neighbour_cases(tmp_path, bad):
        with workspace(tmp_path, files, baseline="ref") as folder:
            (folder / "baselines.json").write_bytes(dump(reference()))
            for call in (lambda: panel.changes_against("ref"), open_panel("r1")):
                try:
                    call()
                except paths.ToolError:
                    pass
                except Exception as error:
                    found.append(f"{label}: {type(error).__name__}: {str(error)[:60]}")
    assert not found, "\n".join(sorted(set(found)))


def test_bug_a_deeply_nested_neighbour_raises_recursionerror(tmp_path):
    """changes_against reads every *.json of the folder and skips only ValueError and OSError."""
    files = {"r1.json": GOOD, "r1.frames.csv": FRAMES, "junk.json": DEEP, **one_run(GOOD)}
    with workspace(tmp_path, files, baseline="ref") as folder:
        (folder / "baselines.json").write_bytes(dump(reference()))
        found = []
        for call in (lambda: panel.changes_against("ref"), open_panel("a")):
            try:
                call()
            except paths.ToolError:
                pass
            except BaseException as error:
                found.append(type(error).__name__)
        assert not found, f"junk.json nested 1 000 000 levels: {found}"


def test_changes_against_skips_neighbours_it_cannot_read(tmp_path):
    other = summary(**{"process": {"arguments": "other.exe"}})
    files = {"r1.json": GOOD, "r1.frames.csv": FRAMES, "good.json": summary(**{"gpu.fps_estimate": 65.0}), "other.json": other,
             "empty.json": "", "list.json": "[]", "null.json": "null", "str.json": '"x"', "bin.json": b"\xff\xfe", "trunc.json": '{"process": {"arg',
             "noproc.json": {"gpu": {}}, "procstr.json": {"process": "game.exe"}, "proclist.json": {"process": [1]},
             "nan.json": '{"process": {"arguments": "game.exe"}, "gpu": {"fps_estimate": NaN}}', "has space.json": GOOD,
             "bad‮name.json": GOOD, "panel.json": [{"id": "tests", "on": True}], "r1.panel.json": GOOD}
    with workspace(tmp_path, files, baseline="ref") as folder:
        (folder / "baselines.json").write_bytes(dump(reference()))
        (folder / "dir.json").mkdir()
        os.symlink(folder / "nowhere.json", folder / "dangling.json")
        os.symlink(folder / "loop.json", folder / "loop.json")
        if readable_by_others():
            (folder / "noaccess.json").write_bytes(dump(GOOD))
            (folder / "noaccess.json").chmod(0)
        try:
            got = panel.changes_against("ref", limit=50)
        finally:
            if readable_by_others():
                (folder / "noaccess.json").chmod(0o644)
        names = [r["run"] for r in got["runs"]]
        assert "good" in names and "other" not in names and "r1" not in names, names
        assert not {"empty", "list", "null", "str", "bin", "trunc", "noproc", "procstr", "proclist", "panel", "baselines", "dir", "dangling",
                    "loop", "noaccess"} & set(names), names
        assert next(r for r in got["runs"] if r["run"] == "good")["values"]["fps"]["direction"] == "better"


def test_changes_against_matches_perf_check_and_keeps_the_newest_oldest_first(tmp_path):
    """Seeded property: for random FPS and GPU ms the panel's direction is perf_check's regressed/improved/same, the runs
    returned are the `limit` newest of the program in age order, and the reference's own runs never appear."""
    rng = random.Random(20260512)
    files = {"r1.json": summary(**{"gpu.fps_estimate": 62.4}), "r2.json": summary(**{"gpu.fps_estimate": 62.2}), "r3.json": summary(**{"gpu.fps_estimate": 62.4})}
    values = {}
    for i in range(14):
        values[f"x{i:02d}"] = (round(rng.uniform(40, 90), 1), round(rng.uniform(2, 8), 2))
        files[f"x{i:02d}.json"] = summary(**{"gpu.fps_estimate": values[f"x{i:02d}"][0], "gpu.frame_gpu_ms.mean": values[f"x{i:02d}"][1]})
    with workspace(tmp_path, files, baseline="ref") as folder:
        for r in ("r1", "r2", "r3"):
            (folder / f"{r}.frames.csv").write_text(FRAMES)
        analysis.tool_perf_baseline("ref", ["r1", "r2", "r3"])
        order = list(values)
        rng.shuffle(order)
        for age, name in enumerate(order):
            os.utime(folder / f"{name}.json", (1_700_000_000 + age, 1_700_000_000 + age))
        for limit in (1, 5, 8, 14, 40):
            got = panel.changes_against("ref", limit)
            assert [r["run"] for r in got["runs"]] == order[-limit:], (limit, [r["run"] for r in got["runs"]])
        for entry in panel.changes_against("ref", 14)["runs"]:
            (folder / f"{entry['run']}.frames.csv").write_text(FRAMES)
            check = analysis.tool_perf_check(entry["run"], "ref")
            for metric in ("fps", "gpu_ms_mean"):
                worse = metric in [r["metric"] for r in check["regressed"]]
                better = metric in [r["metric"] for r in check["improved"]]
                assert entry["values"][metric]["direction"] == ("worse" if worse else "better" if better else "same"), (entry["run"], metric)


def test_spec_changes_against_with_a_negative_limit_returns_nothing_or_refuses(tmp_path):
    """limit=-1 slices sorted(...)[:-1]: it returns every run but the oldest, the opposite of "the 1 newest". The spec does
    not say what a non-positive limit means; zero returning [] suggests none, and a ToolError is as good."""
    files = {"r1.json": GOOD, "r1.frames.csv": FRAMES, **{f"x{i}.json": GOOD for i in range(5)}}
    with workspace(tmp_path, files, baseline="ref") as folder:
        (folder / "baselines.json").write_bytes(dump(reference()))
        assert panel.changes_against("ref", 0)["runs"] == []
        try:
            got = [r["run"] for r in panel.changes_against("ref", -1)["runs"]]
        except paths.ToolError:
            return
        assert got == [], f"limit=-1 returned {got}"


def test_changes_against_with_many_recordings_of_one_program_stays_bounded(tmp_path):
    """1 500 other recordings of the same program: each is opened once to match its program, the answer holds the newest
    `limit` runs oldest first, and it stays far from the 10 s this allows (0.2 s for 3 000 files when this was written)."""
    import time
    files = {"r1.json": GOOD, "r1.frames.csv": FRAMES, **{f"x{i:04d}.json": GOOD for i in range(1500)}}
    with workspace(tmp_path, files, baseline="ref") as folder:
        (folder / "baselines.json").write_bytes(dump(reference()))
        for i in range(1500):
            os.utime(folder / f"x{i:04d}.json", (1_700_000_000 + i, 1_700_000_000 + i))
        started = time.monotonic()
        got = panel.changes_against("ref", 8)
        assert time.monotonic() - started < 10
        assert [r["run"] for r in got["runs"]] == [f"x{i:04d}" for i in range(1492, 1500)]


def test_symlinked_run_files_open_and_do_not_leak_the_target(tmp_path):
    with workspace(tmp_path, one_run(GOOD, FRAMES, **{"a.metal_memory.csv": MEMORY})) as folder:
        for suffix in (".json", ".frames.csv", ".metal_memory.csv"):
            os.symlink(folder / f"a{suffix}", folder / f"c{suffix}")
        os.symlink(folder / "nowhere.json", folder / "d.json")
        got = panel.panel_data(["c"])
        assert got["runs"][0]["has"]["frames"] and got["runs"][0]["memory"] and str(folder) not in json.dumps(got)
        try:
            panel.panel_data(["d"])
            raise AssertionError("a dangling link is no run")
        except paths.ToolError as error:
            assert str(folder) not in str(error)


# --- panel.json (the layout) --------------------------------------------------------------------------------------------

def test_bug_a_panel_json_that_is_a_directory_or_unreadable_crashes_read_layout(tmp_path):
    found = []
    with workspace(tmp_path, one_run(GOOD)) as folder:
        (folder / "panel.json").mkdir()
        try:
            panel.read_layout()
        except paths.ToolError:
            pass
        except Exception as error:
            found.append(f"panel.json is a directory: {type(error).__name__}")
    if readable_by_others():
        with workspace(tmp_path, {**one_run(GOOD), "panel.json": "[]"}) as folder:
            (folder / "panel.json").chmod(0)
            try:
                panel.read_layout()
            except paths.ToolError:
                pass
            except Exception as error:
                found.append(f"panel.json mode 000: {type(error).__name__}")
            finally:
                (folder / "panel.json").chmod(0o644)
    assert not found, "\n".join(found)


def test_deeply_nested_json_in_panel_json_is_refused_as_not_valid(tmp_path):
    """json.loads raises RecursionError on deep nesting; read_layout answers it like any other bad panel.json."""
    with workspace(tmp_path, {"panel.json": DEEP}):
        try:
            panel.read_layout()
            raise AssertionError("a layout nested a million levels deep must be refused")
        except paths.ToolError as error:
            assert "panel.json" in str(error)


def test_read_layout_refusals_name_panel_json_and_carry_no_path(tmp_path):
    bad = ("", "{x", "{}", "null", '"tests"', "5", '[{"id": "tests"}]', '[{"on": true}]', '[{"id": "zzz", "on": true}]', '[{"id": "Tests", "on": true}]',
           '[{"id": "tests", "on": 1}]', '[{"id": "tests", "on": null}]', '[{"id": ["tests"], "on": true}]', '[[{"id": "tests", "on": true}]]',
           '[{"id": "tests", "on": NaN}]', "[{}]", "[null]", b"\xff\xfe", b"\xef\xbb\xbf[]", '[{"id": "tests", "on": ' + "9" * 5000 + "}]")
    for text in bad:
        with workspace(tmp_path, {"panel.json": text}) as folder:
            try:
                panel.read_layout()
                raise AssertionError(f"{text[:60]!r} must be refused")
            except paths.ToolError as error:
                assert "panel.json" in str(error) and str(folder) not in str(error), (text[:60], error)
    with workspace(tmp_path, {"panel.json": '[{"id": "tests", "on": true, "extra": 1}, {"id": "data", "on": false}]'}):
        assert panel.read_layout() == [{"id": "tests", "on": True}, {"id": "data", "on": False}]
    with workspace(tmp_path, {}):
        assert panel.read_layout() is None
    with workspace(tmp_path, {"panel.json": "[]"}):
        assert panel.read_layout() == []


def test_spec_read_layout_with_a_tab_twice(tmp_path):
    """`[{"id": "tests", "on": true}, {"id": "tests", "on": false}]` is accepted and returned as is: the page gets the tab
    twice, once shown and once hidden. tool_perf_panel writes each tab once (dict.fromkeys), so a file with a repeat was
    not written by the tool. The spec says "a list of {id, on}" only: refuse, or keep the first, or return as is?"""
    with workspace(tmp_path, {"panel.json": [{"id": "tests", "on": True}, {"id": "tests", "on": False}]}):
        try:
            got = panel.read_layout()
        except paths.ToolError:
            return
        ids = [w["id"] for w in got]
        assert len(ids) == len(set(ids)), got


# --- tool_perf_panel ------------------------------------------------------------------------------------------------------

def test_bug_saving_a_layout_makes_perf_runs_crash(tmp_path):
    """tool_perf_panel(layout=...) writes panel.json into the runs folder; tool_perf_runs lists every *.json but
    baselines.json, reads the layout list as a summary and raises AttributeError: perf_runs (and the live panel's default
    run, which calls it) is broken from then on. panel.py writes the file, analysis.py reads it."""
    with workspace(tmp_path, one_run(GOOD)):
        panel.tool_perf_panel("p", ["a"], layout=["summary"])
        rows = analysis.tool_perf_runs()["rows"]
        assert [r["run"] for r in rows] == ["a"], rows


def test_bug_a_failed_perf_panel_still_rewrites_panel_json(tmp_path):
    """The layout is written before the runs, preset and skip_s are checked: a call that fails with a ToolError has
    already changed the default layout of every panel."""
    old = [{"id": "tests", "on": True}]
    found = []
    for label, kwargs in (("unknown run", {"runs": ["nope"]}), ("bad preset", {"runs": ["a"], "preset": "zzz"}),
                          ("bad skip_s", {"runs": ["a"], "skip_s": -5}), ("compare with one run", {"runs": ["a"], "preset": "compare"})):
        with workspace(tmp_path, {**one_run(GOOD), "panel.json": old}) as folder:
            try:
                panel.tool_perf_panel("p", layout=["summary"], **kwargs)
            except paths.ToolError:
                pass
            if json.loads((folder / "panel.json").read_text()) != old:
                found.append(label)
    assert not found, f"panel.json rewritten by a call that failed: {found}"


def test_bug_a_layout_that_is_not_a_list_raises_typeerror(tmp_path):
    """The schema says an array, but a library call with `layout=5` gets TypeError ('int' object is not iterable)."""
    found = []
    for bad in (5, 5.5, True, 10 ** 30):
        with workspace(tmp_path, one_run(GOOD)):
            try:
                panel.tool_perf_panel("p", ["a"], layout=bad)
            except paths.ToolError:
                pass
            except Exception as error:
                found.append(f"layout={bad!r}: {type(error).__name__}: {error}")
    assert not found, "\n".join(found)


def test_bug_a_long_panel_name_raises_oserror(tmp_path):
    """name_ok accepts any length; `<name>.panel.html` over the file system's limit raises OSError, not ToolError."""
    found = []
    for length in (250, 300):
        with workspace(tmp_path, one_run(GOOD)):
            try:
                panel.tool_perf_panel("x" * length, ["a"])
            except paths.ToolError:
                pass
            except Exception as error:
                found.append(f"name of {length} characters: {type(error).__name__}")
    assert not found, "\n".join(found)


def test_bug_perf_panel_writes_through_a_symlink_to_a_file_outside_the_runs_folder(tmp_path):
    """panel.json or <name>.panel.html planted as a symlink in the runs folder: write_text follows it and overwrites the
    file it points at. The runs folder is data from outside (it may be a clone or a download)."""
    outside = type(tmp_path)(tempfile.mkdtemp(dir=tmp_path))
    victims = {"layout": outside / "precious-layout.txt", "page": outside / "precious-page.txt"}
    for victim in victims.values():
        victim.write_text("PRECIOUS")
    with workspace(tmp_path, one_run(GOOD)) as folder:
        os.symlink(victims["layout"], folder / "panel.json")
        os.symlink(victims["page"], folder / "p.panel.html")
        try:
            panel.tool_perf_panel("p", ["a"], layout=["summary"])
        except paths.ToolError:
            pass
    clobbered = [label for label, victim in victims.items() if victim.read_text() != "PRECIOUS"]
    assert not clobbered, f"files outside the runs folder overwritten through a symlink: {clobbered}"


def test_perf_panel_page_survives_hostile_strings(tmp_path):
    """Labels and causes from the summary reach the page: no raw `<`, no U+2028 or U+2029, a label that holds the
    payload placeholder does not make the page replace it twice, and the payload reads back as it went in."""
    evil = "</script><!--<script>\u2028\u2029'\"\\ /*PAYLOAD*/null"
    s = summary(**{"encoders.by_label": [{"label": evil, "per_frame": 1.0, "total_ms": 5.0}],
                   "hitches": {"count": 1, "threshold_ms": 30.0, "worst": [{"frame": 3, "cause": evil, "cpu_pct": 1.0}]}})
    with workspace(tmp_path, one_run(s, HEADER + "1,0.0,4.0\n2,16.0,4.0\n3,100.0,4.0\n")) as folder:
        got = panel.tool_perf_panel("p", ["a"])
        page = (folder / got["file"]).read_text(encoding="utf-8")
        assert page.count("<script") == 1 and "\u2028" not in page and "\u2029" not in page and str(folder) not in page
        data = json.loads(page.split("let DATA = ", 1)[1].split(";\nconst COLORS", 1)[0].replace("\\u003c", "<"))
        assert data["runs"][0]["encoders"][0]["label"] == evil and data["runs"][0]["marks"][0][3] == evil
        assert got["bytes"] == len(page.encode("utf-8"))


# --- what the page shows against what the summary says ------------------------------------------------------------------

def test_bug_the_memory_curve_under_skip_s_drops_samples_the_peak_counts(tmp_path):
    """steady_summary keeps memory samples from the cut (first frame + skip_s); panel_run keeps those from the first
    kept frame's start, so a sample between the cut and that frame is in metal_memory_mib.peak but not on the curve."""
    memory = "time_ms,metal_allocated_bytes\n0,10485760\n1002,524288000\n2000,10485760\n"  # frames every 16 ms: the first from 1000 is at 1008
    with workspace(tmp_path, one_run(GOOD, FRAMES, **{"a.metal_memory.csv": memory})):
        run = panel.panel_data(["a"], skip_s=1)["runs"][0]
        peak = run["metal_memory_mib"]["peak"]
        assert peak == 500.0
        assert max(mib for _, mib in run["memory"]) == peak, f"summary peak {peak} MiB, curve {run['memory']}"


def test_bug_a_windows_run_with_no_rss_samples_claims_to_have_memory(tmp_path):
    """The recorder writes process_rss_mib {"count": 0} when it sampled nothing: a non-empty dict, so `bool(...)` says the
    run has memory data, and the section shows nothing."""
    s = summary(device={"platform": "Windows"}, process_rss_mib={"count": 0}, metal_memory_mib={"samples": 0})
    with workspace(tmp_path, {"w.json": s, "w.frames.csv": FRAMES}):
        run = panel.panel_data(["w"])["runs"][0]
        assert not run["has"]["memory"], run["has"]
        assert any(m["id"] == "memory" for m in run["missing"]), run["missing"]


def test_spec_the_frames_cut_holds_up_to_twice_panel_points(tmp_path):
    """panel_run documents "cut to PANEL_POINTS points that keep every hitch", but stride = len // PANEL_POINTS rounds
    down: 99 rows with PANEL_POINTS 50 give stride 1 and 99 points; the same for the memory samples. With no hitch the
    limit of 50 is exceeded by 98 %. (If "about PANEL_POINTS" is the intent, the docstring should say so.)"""
    rows = HEADER + "".join(f"{i + 1},{i * 16.0},4.0\n" for i in range(99))
    memory = "time_ms,metal_allocated_bytes\n" + "".join(f"{i},1048576\n" for i in range(99))
    with workspace(tmp_path, one_run(GOOD, rows, **{"a.metal_memory.csv": memory}), points=50):
        run = panel.panel_data(["a"])["runs"][0]
        assert run["marks"] == [] and len(run["frames"]) <= 50 and len(run["memory"]) <= 50, (len(run["frames"]), len(run["memory"]))


def test_spec_nan_and_infinity_make_the_payload_invalid_json(tmp_path):
    """A frames.csv with "nan" or "inf" (float() accepts both) and a summary with 1e999 reach the payload; the live panel
    sends it with json.dumps, whose NaN and Infinity the browser's JSON parser refuses, so the page stays empty. The spec
    does not say whether the payload must be strict JSON."""
    found = []
    for label, files in (("frames.csv gpu_ms nan", one_run(GOOD, HEADER + "1,0.0,nan\n2,16.0,4.0\n")),
                         ("frames.csv start inf", one_run(GOOD, HEADER + "1,0.0,4.0\n2,inf,4.0\n3,32.0,4.0\n")),
                         ("summary fps 1e999", one_run('{"gpu": {"fps_estimate": 1e999, "frames": 400}}')),
                         ("memory time nan", one_run(GOOD, FRAMES, **{"a.metal_memory.csv": "time_ms,metal_allocated_bytes\nnan,5\n0,5\n"}))):
        with workspace(tmp_path, files):
            try:
                json.dumps(panel.panel_data(["a"]), allow_nan=False)
            except ValueError as error:
                found.append(f"{label}: {error}")
    assert not found, "\n".join(found)


def test_every_hitch_survives_the_cut_in_random_recordings(tmp_path):
    """Seeded property: whatever the gaps and PANEL_POINTS, every gap over the threshold is a mark, its frame is on the
    curve, the curve is a subsequence of the file's frames, and with PANEL_POINTS rows or fewer nothing is cut."""
    rng = random.Random(7)
    for trial in range(30):
        count = rng.randint(2, 400)
        t, starts = 0.0, []
        for _ in range(count):
            starts.append(round(t, 3))
            t += rng.choice((16.0, 16.0, 16.0, 16.7, 40.0, 95.0))
        text = HEADER + "".join(f"{i + 1},{s},4.0\n" for i, s in enumerate(starts))
        points = rng.randint(1, 60)
        with workspace(tmp_path, one_run(summary(**{"hitches.threshold_ms": 33.0}), text), points=points):
            run = panel.panel_data(["a"])["runs"][0]
            expected = [[b, 4.0, round(b - a, 3)] for a, b in zip(starts, starts[1:]) if b - a > 33.0 - analysis.CSV_TOL_MS]
            assert [m[:3] for m in run["marks"]] == expected, (trial, points)
            shown = [f[0] for f in run["frames"]]
            assert all(m[0] in shown for m in run["marks"]), (trial, points)
            assert shown == sorted(shown) and set(shown) <= set(starts), trial
            if count <= points:
                assert shown == starts, (trial, points)


def test_no_value_of_the_payload_carries_the_runs_folder_path(tmp_path):
    """The paths of the folder, of a run and of the reference never travel, even through the error texts of a reference
    that cannot judge a run."""
    s = summary(**{"process": {"arguments": "game.exe"}})
    files = {**one_run(s), "b.json": s, "r1.json": s, "r1.frames.csv": FRAMES, "baselines.json": reference(s, skip_s=2),
             "nofr.json": s, "bare.json": {"gpu": {"frames": 400}}, "panel.json": [{"id": "tests", "on": True}]}
    with workspace(tmp_path, files, baseline="ref") as folder:
        for runs, skip in ((["a"], 0), (["a", "b"], 0), (["nofr"], 0), (["bare"], 0), (["a"], 1)):
            try:
                got = panel.panel_data(runs, skip_s=skip)
            except paths.ToolError as error:
                assert str(folder) not in str(error), error
                continue
            text = json.dumps(got)
            assert str(folder) not in text and str(tmp_path) not in text, (runs, skip)
        page = (folder / panel.tool_perf_panel("p", ["a", "b"])["file"]).read_text()
        assert str(folder) not in page
