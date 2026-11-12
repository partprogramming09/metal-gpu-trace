"""Adversarial tests of project.py: hostile project files, runs folders that would let KEEP_RUNS delete user data,
odd environments and path leaks. Tests named test_bug_* reproduce a failure found while attacking the module; tests
named test_spec_* fail on a point where the specification is ambiguous (see their docstrings)."""
import json
import os
import pathlib

from support import ROOT  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import config, paths, project


def write(folder, data):
    """Writes `data` (a dict, or text as is) as the project file of `folder` and returns its path."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / project.FILE_NAME
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def outcome(path, **kwargs):
    """Returns ("ok", dict) or ("refused", text) for project.load; any other exception propagates."""
    try:
        return "ok", project.load(path, **kwargs)
    except paths.ToolError as error:
        return "refused", str(error)


def refused(path, **kwargs):
    kind, got = outcome(path, **kwargs)
    assert kind == "refused", f"{path.read_text()[:200]} must be refused, got {got}"
    return got


def saved_config():
    saved = config.OUT, list(config.READ), config.BASELINES, config.PROJECT, config.PROJECT_ERROR

    def restore():
        config.OUT, config.READ, config.BASELINES, config.PROJECT, config.PROJECT_ERROR = saved
    return restore


def case_insensitive(folder):
    """Returns whether the filesystem holding `folder` ignores case (APFS by default on macOS)."""
    probe = folder / "CaseProbe"
    probe.mkdir()
    try:
        return (folder / "caseprobe").exists()
    finally:
        probe.rmdir()


# --- hostile JSON: only ToolError may come out of load -------------------------------------------------------------

def test_bug_load_huge_integer_raises_valueerror_not_toolerror(tmp_path):
    """Python 3.11+ limits int parsing to 4300 digits and raises a plain ValueError, which load does not translate."""
    refused(write(tmp_path, '{"name": "m", "runs": "r", "profile": ' + "1" * 5000 + "}"))


def test_load_survives_deep_object_nesting(tmp_path):
    text = refused(write(tmp_path, '{"a":' * 100_000))
    assert project.FILE_NAME in text, text


def test_load_refuses_nan_infinity_and_null_values(tmp_path):
    for field, raw in (("name", "NaN"), ("runs", "Infinity"), ("profile", "NaN"), ("format", "-Infinity"),
                       ("baseline", "NaN"), ("name", "null"), ("runs", "null"), ("profile", "null"),
                       ("profile", '["generic"]'), ("format", '{"metal-gpu-trace": 1}'), ("name", "true"),
                       ("runs", '["r"]')):
        values = {"name": '"m"', "runs": '"r"', field: raw}
        text = refused(write(tmp_path, "{" + ", ".join(f'"{k}": {v}' for k, v in values.items()) + "}"))
        assert field in text, (field, raw, text)


def test_load_refuses_duplicates_in_nested_values_with_a_toolerror(tmp_path):
    refused(write(tmp_path, '{"name": "m", "runs": "r", "profile": {"a": 1, "a": 2}}'))


def test_load_refuses_odd_encodings(tmp_path):
    path = tmp_path / project.FILE_NAME
    for raw in (b"\xff\xfe" + '{"name":"m","runs":"r"}'.encode("utf-16-le"), b'{"name": "\xff", "runs": "r"}',
                b"", b"\xef\xbb\xbf", b"\x00", b"   "):
        path.write_bytes(raw)
        assert project.FILE_NAME in refused(path), raw


def test_load_refuses_lone_surrogates_everywhere(tmp_path):
    for body in ('{"name": "\\ud800", "runs": "r"}', '{"name": "m", "runs": "\\ud800"}',
                 '{"name": "m", "runs": "r", "\\ud800": 1}', '{"name": "m", "runs": "r", "baseline": "\\udfff"}',
                 '{"name": "m", "\\ud800": 1, "\\ud800": 2}'):
        refused(write(tmp_path, body))


def test_load_refuses_path_characters_in_name_and_baseline(tmp_path):
    for field in ("name", "baseline"):
        for value in ("..", ".", "a/b", "a\\b", "../x", "/", "a∕b", "a／b", "a b", "a\tb", "a\nb", "",
                      "a\u0000b", "~", "a:b", "​", "a‍b"):
            text = refused(write(tmp_path, {"name": "m", "runs": "r", field: value}))
            assert field in text, (field, value, text)


def test_load_refuses_a_project_path_that_is_not_a_readable_file(tmp_path):
    (tmp_path / "dir.json").mkdir()
    for path in (tmp_path / "dir.json", tmp_path / "missing.json"):
        try:
            project.load(path)
            raise AssertionError(f"{path!r} must be refused")
        except paths.ToolError as error:
            assert str(tmp_path) not in str(error), error


def test_bug_load_raises_valueerror_on_a_nul_byte_in_its_path(tmp_path):
    """read_text() raises ValueError for a path holding NUL; load catches OSError, not ValueError."""
    try:
        project.load(tmp_path / "a\u0000b.json")
        raise AssertionError("must be refused")
    except paths.ToolError as error:
        assert str(tmp_path) not in str(error), error


def test_load_error_text_is_bounded_for_many_unknown_keys(tmp_path):
    data = {"name": "m", "runs": "r", **{f"k{i}" + "x" * 300: i for i in range(1000)}}
    assert len(refused(write(tmp_path, data))) < 400


# --- runs folders that must never be accepted ----------------------------------------------------------------------

def test_bug_broken_symlink_as_runs_is_accepted_and_followed(tmp_path):
    """A dangling link resolves (non-strict) to its missing target, so is_symlink() is false and the target is used."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "runs").symlink_to(tmp_path / "elsewhere" / "target")
    text = refused(write(repo, {"name": "m", "runs": "runs"}), home=tmp_path / "h")
    assert "runs" in text and str(tmp_path) not in text, text


def test_runs_symlinks_to_home_root_repo_and_parents_are_refused(tmp_path):
    home = tmp_path / "h"
    repo = home / "src" / "repo"
    repo.mkdir(parents=True)
    for folder in (home, home / "src", tmp_path):
        (folder / project.RUNS_MARK).write_text("")
    for name, target in (("to-root", pathlib.Path("/")), ("to-home", home), ("to-repo", repo),
                         ("to-parent", home / "src"), ("to-self-up", repo / ".."), ("chain", repo / "to-home")):
        (repo / name).symlink_to(target)
        refused(write(repo, {"name": "m", "runs": name}), home=home)


def test_runs_escaping_with_dotdot_is_refused_when_it_lands_above(tmp_path):
    home = tmp_path / "h"
    repo = home / "a" / "repo"
    repo.mkdir(parents=True)
    (home / project.RUNS_MARK).write_text("")
    (home / "a" / project.RUNS_MARK).write_text("")
    for runs in ("x/../..", "./../", "../../", "x/y/../../..", "~/a/repo", "~/a", "~/./", "~/a/repo/x/..", "~//",
                 "~/" + "../" * 40, "../" * 40, "./", "~/a/../"):
        refused(write(repo, {"name": "m", "runs": runs}), home=home)


def test_bug_case_changed_parent_name_bypasses_the_parent_check(tmp_path):
    """On a case-insensitive disk "../../A" is the parent folder "a", but resolve() keeps the case written, so the
    comparison with root.parents misses it; a marked parent is then accepted (KEEP_RUNS would prune the parent)."""
    if not case_insensitive(tmp_path):
        return
    home = tmp_path / "h"
    repo = home / "a" / "repo"
    repo.mkdir(parents=True)
    (home / "a" / project.RUNS_MARK).write_text("")
    (home / project.RUNS_MARK).write_text("")
    for runs in ("../../A", "../../a"):
        text = refused(write(repo, {"name": "m", "runs": runs}), home=home)
        assert "folder of its own" in text, (runs, text)


def test_bug_case_changed_home_name_bypasses_the_home_check(tmp_path):
    """The same case trick on the home folder: "~/../H" is the marked home folder "h" and is accepted."""
    if not case_insensitive(tmp_path):
        return
    home = tmp_path / "h"
    (home / "x" / "repo").mkdir(parents=True)
    (home / project.RUNS_MARK).write_text("")
    text = refused(write(tmp_path / "elsewhere" / "repo", {"name": "m", "runs": "~/../H"}), home=home)
    assert "folder of its own" in text, text


def test_runs_holding_a_case_changed_git_or_project_file_is_refused(tmp_path):
    if not case_insensitive(tmp_path):
        return
    for i, inside in enumerate((".GIT", ".Git", "Metal-GPU-Trace.json", "METAL-GPU-TRACE.JSON")):
        runs = tmp_path / f"runs{i}"
        runs.mkdir()
        (runs / project.RUNS_MARK).write_text("")
        (runs / inside).mkdir()
        refused(write(tmp_path, {"name": "m", "runs": runs.name}))


def test_runs_with_a_case_changed_marker_or_litter_is_not_taken_as_empty(tmp_path):
    for i, inside in enumerate((".METAL-GPU-TRACE-RUNS", ".ds_store", "thumbs.db", ".DS_Store ")):
        runs = tmp_path / f"runs{i}"
        runs.mkdir()
        (runs / inside).write_text("")
        (runs / "keep.json").write_text("{}")
        refused(write(tmp_path, {"name": "m", "runs": runs.name}))


def test_runs_holding_only_hidden_user_files_is_refused(tmp_path):
    for i, inside in enumerate((".env", ".hidden.json", "a.json", ".localized", "Icon\r")):
        runs = tmp_path / f"runs{i}"
        runs.mkdir()
        (runs / inside).write_text("x")
        refused(write(tmp_path, {"name": "m", "runs": runs.name}))


def test_marker_that_is_a_folder_does_not_count(tmp_path):
    """Ambiguous spec: a folder named .metal-gpu-trace-runs counts as the marker, so a folder of user .json files is
    accepted. The error text asks for 'an empty ... file'; whether a folder may stand in for it is not specified."""
    runs = tmp_path / "data"
    (runs / project.RUNS_MARK).mkdir(parents=True)
    (runs / "precious.json").write_text("{}")
    refused(write(tmp_path / "repo", {"name": "m", "runs": "../data"}))


def test_marker_that_is_a_link_does_not_count(tmp_path):
    """Ambiguous spec: a marker that is a dangling link counts as the marker, and adopt's touch() follows it and
    creates the link's target outside the runs folder."""
    restore = saved_config()
    try:
        runs = tmp_path / "repo" / "runs"
        runs.mkdir(parents=True)
        target = tmp_path / "outside" / "created"
        target.parent.mkdir()
        (runs / project.RUNS_MARK).symlink_to(target)
        write(tmp_path / "repo", {"name": "m", "runs": "runs"})
        project.apply(tmp_path / "repo", {"HOME": "/nonexistent"})
        assert not target.exists(), "adopt wrote outside the runs folder"
    finally:
        restore()


def test_absolute_runs_is_accepted_and_checked(tmp_path):
    """An absolute runs (an external drive, say) is used as is, with the same checks; ~//x stays under home."""
    (tmp_path / "abs").mkdir()
    got = project.load(write(tmp_path / "repo", {"name": "m", "runs": str(tmp_path / "abs" / "new")}), home=tmp_path / "h")
    assert got["runs"] == (tmp_path / "abs" / "new").resolve(), got
    got = project.load(write(tmp_path / "repo", {"name": "m", "runs": "~//x"}), home=tmp_path / "h")
    assert got["runs"] == (tmp_path / "h" / "x").resolve(), got
    refused(write(tmp_path / "repo", {"name": "m", "runs": str(tmp_path)}), home=tmp_path / "h")


def test_runs_under_another_users_home_with_tilde_name_is_refused(tmp_path):
    for runs in ("~root", "~root/x", "~nobody/x", "~x", "~~/x", "~.", "~./x"):
        text = refused(write(tmp_path / "repo", {"name": "m", "runs": runs}), home=tmp_path / "h")
        assert "runs" in text and str(tmp_path) not in text, (runs, text)


# --- find and METAL_TRACE_PROJECT ----------------------------------------------------------------------------------

def test_bug_apply_raises_on_metal_trace_project_naming_an_unknown_user(tmp_path):
    """expanduser() raises RuntimeError for ~unknown-user; apply catches only OSError and ToolError."""
    restore = saved_config()
    try:
        project.apply(tmp_path, {"HOME": "/nonexistent", "METAL_TRACE_PROJECT": "~no-such-user-zz9/x.json"})
        assert config.PROJECT_ERROR and str(tmp_path) not in config.PROJECT_ERROR, config.PROJECT_ERROR
    finally:
        restore()


def test_bug_apply_raises_on_a_nul_byte_in_metal_trace_project(tmp_path):
    """read_text() of a path holding NUL raises ValueError, which neither load nor apply translates."""
    restore = saved_config()
    try:
        project.apply(tmp_path, {"HOME": "/nonexistent", "METAL_TRACE_PROJECT": str(tmp_path) + "/a\u0000b.json"})
        assert config.PROJECT_ERROR and str(tmp_path) not in config.PROJECT_ERROR, config.PROJECT_ERROR
    finally:
        restore()


def test_bug_apply_raises_on_a_nul_byte_in_home(tmp_path):
    restore = saved_config()
    try:
        project.apply(tmp_path, {"HOME": "/a\u0000b"})
    finally:
        restore()


def test_bug_apply_raises_on_a_nul_byte_in_metal_trace_out(tmp_path):
    """config.reload runs before apply's try block, so a bad METAL_TRACE_OUT escapes apply."""
    restore = saved_config()
    try:
        project.apply(tmp_path, {"HOME": "/nonexistent", "METAL_TRACE_OUT": "/a\u0000b"})
    finally:
        restore()


def test_apply_never_raises_on_odd_metal_trace_project(tmp_path):
    restore = saved_config()
    (tmp_path / "plain").write_text("x")
    write(tmp_path / "ok", {"name": "m", "runs": "r"})
    (tmp_path / "loop").symlink_to(tmp_path / "loop")
    try:
        for given in ("/", ".", "..", " ", "~", "~/", str(tmp_path / "plain"), str(tmp_path / "loop"),
                      str(tmp_path / "plain" / "x"), "/dev/null", str(tmp_path / ("x" * 300)),
                      str(tmp_path / "/".join(["x" * 200] * 10)), "\udcff"):
            project.apply(tmp_path, {"HOME": str(tmp_path / "h"), "METAL_TRACE_PROJECT": given})
            if config.PROJECT_ERROR:
                assert str(tmp_path) not in config.PROJECT_ERROR, (given, config.PROJECT_ERROR)
    finally:
        restore()


def test_apply_never_raises_on_odd_home(tmp_path):
    """A relative HOME is taken from the working directory: run from tmp_path so nothing lands in the checkout."""
    restore = saved_config()
    before = os.getcwd()
    write(tmp_path / "repo", {"name": "m", "runs": "~/r"})
    try:
        os.chdir(tmp_path)
        for home in ("relative", "/", "~", str(tmp_path / "loop"), "\udcff"):
            project.apply(tmp_path / "repo", {"HOME": home})
    finally:
        os.chdir(before)
        restore()


def test_find_with_home_at_the_disk_root_or_unset(tmp_path):
    write(tmp_path / "repo", {"name": "m", "runs": "r"})
    for env in ({"HOME": "/"}, {"HOME": ""}, {}):
        assert project.find(tmp_path / "repo", env) == tmp_path / "repo" / project.FILE_NAME, env


def test_find_does_not_take_a_folder_named_like_the_project_file(tmp_path):
    (tmp_path / "repo" / project.FILE_NAME).mkdir(parents=True)
    write(tmp_path, {"name": "m", "runs": "r"})
    assert project.find(tmp_path / "repo", {"HOME": "/nonexistent"}) == tmp_path / project.FILE_NAME


def test_find_stops_at_a_home_reached_through_a_symlink(tmp_path):
    real = tmp_path / "real-home"
    (real / "x").mkdir(parents=True)
    write(real, {"name": "home", "runs": "r"})
    (tmp_path / "link-home").symlink_to(real)
    assert project.find(tmp_path / "link-home" / "x", {"HOME": str(tmp_path / "link-home")}) is None
    assert project.find(real / "x", {"HOME": str(tmp_path / "link-home")}) is None


def test_bug_find_does_not_stop_at_a_case_changed_home(tmp_path):
    """On a case-insensitive disk HOME=/…/H and a start under /…/h are the same folder, but find compares the
    spelled paths and walks past the home folder, taking the project file in it."""
    if not case_insensitive(tmp_path):
        return
    home = tmp_path / "h"
    (home / "x").mkdir(parents=True)
    write(home, {"name": "home", "runs": "r"})
    assert project.find(home / "x", {"HOME": str(tmp_path / "H")}) is None


# --- info never names an absolute path -----------------------------------------------------------------------------

def test_bug_info_leaks_the_whole_path_when_the_working_directory_is_the_disk_root(tmp_path):
    """MCP clients often start servers with cwd "/". Without a project file root is cwd, so shown() makes OUT
    relative to "/" and returns the full path minus its leading slash (user name and temp folder included)."""
    restore = saved_config()
    before = os.getcwd()
    try:
        os.chdir("/")
        env = {"HOME": "/nonexistent", "METAL_TRACE_OUT": str(tmp_path / "o")}
        project.apply(tmp_path, env)
        got = project.info(env)
        assert str(tmp_path).lstrip("/") not in json.dumps(got), got
    finally:
        os.chdir(before)
        restore()


def test_bug_info_leaks_the_whole_path_when_home_is_the_disk_root(tmp_path):
    """HOME=/ (launchd, some services) makes every folder 'under home': runs comes back as ~/<the full path>."""
    restore = saved_config()
    try:
        env = {"HOME": "/", "METAL_TRACE_OUT": str(tmp_path / "o")}
        project.apply(tmp_path, env)
        got = project.info(env)
        assert str(tmp_path).lstrip("/") not in json.dumps(got), got
    finally:
        restore()


def test_info_never_prints_an_absolute_path_for_odd_outs(tmp_path):
    restore = saved_config()
    try:
        for out in ("/", str(tmp_path), str(tmp_path / "a b" / "ü"), str(tmp_path / ".." / "x")):
            env = {"HOME": "/nonexistent", "METAL_TRACE_OUT": out}
            project.apply(tmp_path, env)
            got = project.info(env)
            assert not got["runs"].startswith("/") and str(tmp_path) not in json.dumps(got), (out, got)
    finally:
        restore()


def test_info_after_apply_with_a_bad_file_does_not_leak_paths(tmp_path):
    restore = saved_config()
    try:
        (tmp_path / "repo" / "docs").mkdir(parents=True)
        (tmp_path / "repo" / "docs" / "a.md").write_text("x")
        for runs in ("docs", "..", "/", "~", "~bob", "a\u0000b", "\ud800"):
            write(tmp_path / "repo", json.dumps({"name": "m", "runs": runs}))
            project.apply(tmp_path / "repo", {"HOME": str(tmp_path)})
            assert config.PROJECT_ERROR and str(tmp_path) not in config.PROJECT_ERROR, (runs, config.PROJECT_ERROR)
            try:
                project.info({"HOME": str(tmp_path)})
                raise AssertionError("info must report the wrong file")
            except paths.ToolError as error:
                assert str(tmp_path) not in str(error)
    finally:
        restore()


def test_apply_twice_is_idempotent_and_keeps_user_files_safe(tmp_path):
    restore = saved_config()
    try:
        write(tmp_path / "repo", {"name": "m", "runs": "perf-runs"})
        env = {"HOME": "/nonexistent"}
        project.apply(tmp_path / "repo", env)
        first = config.OUT, list(config.READ), config.BASELINES
        project.apply(tmp_path / "repo", env)
        assert (config.OUT, list(config.READ), config.BASELINES) == first and config.PROJECT_ERROR is None
        assert sorted(p.name for p in (tmp_path / "repo" / "perf-runs").iterdir()) == [project.RUNS_MARK]
    finally:
        restore()
