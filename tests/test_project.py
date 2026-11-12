"""Tests of project.py: the metal-gpu-trace.json project file, which names a project and the folder of its recordings."""
import json
import pathlib

from support import ROOT  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import paths, project


def write(folder, data):
    """Writes `data` (a dict, or text as is) as the project file of `folder` and returns its path."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / project.FILE_NAME
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def refused(path, **kwargs):
    """Returns the text of the ToolError that load raises for `path`; fails when it loads."""
    try:
        got = project.load(path, **kwargs)
    except paths.ToolError as error:
        return str(error)
    raise AssertionError(f"{path.read_text()} must be refused, got {got}")


def test_load_reads_a_valid_file(tmp_path):
    got = project.load(write(tmp_path, {"name": "mullion", "runs": "perf-runs", "profile": "translation-layer",
                                        "baseline": "ds-d3d12"}))
    assert got["name"] == "mullion" and got["runs"] == (tmp_path / "perf-runs").resolve(), got
    assert got["profile"] == "translation-layer" and got["baseline"] == "ds-d3d12" and got["format"] == "metal-gpu-trace"
    assert got["root"] == tmp_path.resolve(), got


def test_load_defaults_profile_and_format(tmp_path):
    got = project.load(write(tmp_path, {"name": "m", "runs": "r"}))
    assert (got["profile"], got["format"], got["baseline"]) == ("generic", "metal-gpu-trace", None), got


def test_load_expands_home_in_runs(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    got = project.load(write(tmp_path / "repo", {"name": "m", "runs": "~/perf-runs/mullion"}), home=home)
    assert got["runs"] == (home / "perf-runs" / "mullion").resolve(), got


def test_load_accepts_missing_empty_or_marked_runs(tmp_path):
    (tmp_path / "empty").mkdir()
    (tmp_path / "finder").mkdir()
    (tmp_path / "finder" / ".DS_Store").write_bytes(b"\0")
    (tmp_path / "marked").mkdir()
    (tmp_path / "marked" / project.RUNS_MARK).write_text("")
    (tmp_path / "marked" / "a_20261112-000000.json").write_text("{}")
    for runs in ("missing", "empty", "finder", "marked"):
        assert project.load(write(tmp_path, {"name": "m", "runs": runs}))["runs"] == (tmp_path / runs).resolve()


def test_load_refuses_a_runs_folder_that_is_not_its_own(tmp_path):
    home = tmp_path / "h"
    repo = home / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "README.md").write_text("x")
    for runs in (".", "", "~", "/", "sub/..", "..", "docs"):
        text = refused(write(repo, {"name": "m", "runs": runs}), home=home)
        assert "runs" in text and str(tmp_path) not in text, (runs, text)
    assert project.RUNS_MARK in refused(write(repo, {"name": "m", "runs": "docs"}), home=home)


def test_load_refuses_a_runs_folder_holding_a_project_file_or_a_repo(tmp_path):
    for inside in (project.FILE_NAME, ".git"):
        runs = tmp_path / f"runs-{inside}"
        runs.mkdir()
        (runs / project.RUNS_MARK).write_text("")
        (runs / inside).write_text("{}")
        text = refused(write(tmp_path, {"name": "m", "runs": runs.name}))
        assert inside in text, text
    (tmp_path / "file").write_text("x")
    assert "names a file" in refused(write(tmp_path, {"name": "m", "runs": "file"}))


def test_load_refuses_unknown_keys(tmp_path):
    text = refused(write(tmp_path, {"name": "m", "runs": "r", "folder": "x"}))
    assert "folder" in text and project.FILE_NAME in text, text


def test_load_refuses_bad_values(tmp_path):
    for field, value in (("name", "a b"), ("name", 3), ("profile", "fast"), ("format", "vegaflow"),
                         ("baseline", 3), ("baseline", "../x"), ("runs", 5)):
        data = {"name": "m", "runs": "r", field: value}
        text = refused(write(tmp_path, data))
        assert field in text and project.FILE_NAME in text, (field, value, text)
    assert "metal-gpu-trace" in refused(write(tmp_path, {"name": "m", "runs": "r", "format": "vegaflow"}))
    for missing in ("name", "runs"):
        data = {"name": "m", "runs": "r"}
        del data[missing]
        assert missing in refused(write(tmp_path, data)), missing
    assert "object" in refused(write(tmp_path, "[1]"))


def test_load_refuses_broken_json(tmp_path):
    text = refused(write(tmp_path, "{"))
    assert project.FILE_NAME in text and str(tmp_path) not in text, text


def test_load_refuses_home_root_or_a_parent_even_when_marked(tmp_path):
    home = tmp_path / "h"
    repo = home / "repo"
    repo.mkdir(parents=True)
    for folder in (home, tmp_path):
        (folder / project.RUNS_MARK).write_text("")
    (repo / "loop").symlink_to(repo / "loop")
    (repo / "to-root").symlink_to(repo)
    (repo / "to-home").symlink_to(home)
    for runs in ("~", "..", "../..", "to-root", "to-home"):
        text = refused(write(repo, {"name": "m", "runs": runs}), home=home)
        assert "folder of its own" in text, (runs, text)
    for runs in ("loop", "a\u0000b", "~bob/x"):
        text = refused(write(repo, {"name": "m", "runs": runs}), home=home)
        assert "runs" in text and str(tmp_path) not in text, (runs, text)


def test_load_reads_a_file_with_a_byte_order_mark(tmp_path):
    path = tmp_path / project.FILE_NAME
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"name": "m", "runs": "r"}).encode())
    assert project.load(path)["name"] == "m"


def test_load_refuses_odd_json(tmp_path):
    assert "line 1" in refused(write(tmp_path, '{"name": "m",'))
    assert project.FILE_NAME in refused(write(tmp_path, "[" * 100_000))
    assert "runs" in refused(write(tmp_path, '{"name": "m", "runs": "a", "runs": "b"}'))
    text = refused(write(tmp_path, {"name": "m", "runs": "r", "x" * 500: 1}))
    assert len(text) < 300, text


def saved_config():
    """Returns a function that puts config's project settings back as they are now."""
    from metal_gpu_trace import config
    saved = config.OUT, list(config.READ), config.BASELINES, config.PROJECT, config.PROJECT_ERROR

    def restore():
        config.OUT, config.READ, config.BASELINES, config.PROJECT, config.PROJECT_ERROR = saved
    return restore


def test_find_takes_the_nearest_file(tmp_path):
    env = {"HOME": str(tmp_path / "h")}
    (tmp_path / ".git").mkdir()
    path = write(tmp_path, {"name": "m", "runs": "r"})
    (tmp_path / "mullion" / ".git").mkdir(parents=True)
    worktree = tmp_path / "comparacion" / "mullion-main"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: elsewhere\n")
    for start in (tmp_path, tmp_path / "mullion", worktree):
        assert project.find(start, env) == path, start


def test_find_prefers_a_closer_file(tmp_path):
    write(tmp_path, {"name": "m", "runs": "r"})
    closer = write(tmp_path / "dxmt", {"name": "d", "runs": "r"})
    (tmp_path / "dxmt" / "src").mkdir()
    assert project.find(tmp_path / "dxmt" / "src", {"HOME": str(tmp_path / "h")}) == closer


def test_find_stops_at_home(tmp_path):
    home = tmp_path / "h"
    (home / "x").mkdir(parents=True)
    write(tmp_path, {"name": "m", "runs": "r"})
    write(home, {"name": "home", "runs": "r"})
    assert project.find(home / "x", {"HOME": str(home)}) is None, "a file in the home folder or above it is no project"


def test_find_prefers_metal_trace_project(tmp_path):
    write(tmp_path, {"name": "m", "runs": "r"})
    other = write(tmp_path / "other", {"name": "o", "runs": "r"})
    for given in (other, other.parent):
        assert project.find(tmp_path, {"HOME": "/nonexistent", "METAL_TRACE_PROJECT": str(given)}) == other


def test_apply_points_out_at_the_project(tmp_path):
    from metal_gpu_trace import config
    restore = saved_config()
    try:
        write(tmp_path, {"name": "m", "runs": "perf-runs", "baseline": "b"})
        project.apply(tmp_path, {"HOME": "/nonexistent", "METAL_TRACE_READ": str(tmp_path / "more")})
        runs = (tmp_path / "perf-runs").resolve()
        assert config.OUT == runs and config.BASELINES == runs / "baselines.json", config.OUT
        assert config.READ == [runs, (tmp_path / "more").resolve()], config.READ
        assert (runs / project.RUNS_MARK).exists() and config.PROJECT["name"] == "m" and config.PROJECT_ERROR is None
        project.check()
        project.apply(tmp_path, {"HOME": "/nonexistent"})
        assert config.OUT == runs, "applying again accepts the folder it marked"
    finally:
        restore()


def test_apply_beats_metal_trace_out(tmp_path):
    from metal_gpu_trace import config
    restore = saved_config()
    try:
        write(tmp_path, {"name": "m", "runs": "perf-runs"})
        project.apply(tmp_path, {"HOME": "/nonexistent", "METAL_TRACE_OUT": str(tmp_path / "elsewhere")})
        assert config.OUT == (tmp_path / "perf-runs").resolve(), config.OUT
    finally:
        restore()


def test_apply_without_a_project_changes_nothing(tmp_path):
    from metal_gpu_trace import config
    restore = saved_config()
    try:
        for env in ({"HOME": "/nonexistent"}, {"HOME": "/nonexistent", "METAL_TRACE_OUT": str(tmp_path / "o")}):
            config.reload(env)
            expected = config.OUT, list(config.READ), config.BASELINES
            project.apply(tmp_path, env)
            assert (config.OUT, config.READ, config.BASELINES) == expected and config.PROJECT is None, env
            assert config.PROJECT_ERROR is None
        assert config.OUT == (tmp_path / "o").resolve()
    finally:
        restore()


def test_apply_keeps_a_bad_file_as_an_error(tmp_path):
    from metal_gpu_trace import config
    restore = saved_config()
    try:
        write(tmp_path, {"name": "m", "runs": "r", "folder": "x"})
        project.apply(tmp_path, {"HOME": "/nonexistent"})
        assert "folder" in config.PROJECT_ERROR and config.PROJECT is None, config.PROJECT_ERROR
        try:
            project.check()
            raise AssertionError("check must raise")
        except paths.ToolError as error:
            assert "folder" in str(error)
    finally:
        restore()


def test_check_cli_exits_2_on_a_bad_project_file(tmp_path):
    import contextlib
    import io
    from metal_gpu_trace import config, metal_trace_mcp
    restore = saved_config()
    try:
        config.PROJECT_ERROR = f"{project.FILE_NAME}: unknown key 'folder'"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert metal_trace_mcp.check_cli(["a", "b"]) == 2
        assert "folder" in err.getvalue(), err.getvalue()
    finally:
        restore()


def test_apply_reports_a_missing_or_unusable_project(tmp_path):
    from metal_gpu_trace import config
    restore = saved_config()
    try:
        for given in (tmp_path / "nowhere.json", tmp_path / "empty-folder"):
            (tmp_path / "empty-folder").mkdir(exist_ok=True)
            project.apply(tmp_path, {"HOME": "/nonexistent", "METAL_TRACE_PROJECT": str(given)})
            assert config.PROJECT_ERROR and project.FILE_NAME in config.PROJECT_ERROR, (given, config.PROJECT_ERROR)
            assert str(tmp_path) not in config.PROJECT_ERROR
        (tmp_path / "f").write_text("x")
        write(tmp_path, {"name": "m", "runs": "f/sub"})
        project.apply(tmp_path, {"HOME": "/nonexistent"})
        assert "cannot be created" in config.PROJECT_ERROR, config.PROJECT_ERROR
    finally:
        restore()


def test_find_ignores_a_file_at_the_disk_root(tmp_path):
    calls = []
    real = pathlib.Path.is_file

    def spy(self):
        calls.append(self)
        return real(self)
    pathlib.Path.is_file = spy
    try:
        project.find(tmp_path, {"HOME": "/nonexistent"})
    finally:
        pathlib.Path.is_file = real
    assert calls and pathlib.Path(tmp_path.anchor) / project.FILE_NAME not in calls, calls[-1]


def test_project_info_names_the_project_and_its_folder(tmp_path):
    restore = saved_config()
    try:
        write(tmp_path, {"name": "mullion", "runs": "perf-runs", "profile": "translation-layer", "baseline": "ds-d3d12"})
        env = {"HOME": "/nonexistent"}
        project.apply(tmp_path, env)
        got = project.info(env)
        assert got == {"project": "mullion", "profile": "translation-layer", "baseline": "ds-d3d12",
                       "format": "metal-gpu-trace", "runs": "perf-runs", "source": "project file"}, got
    finally:
        restore()


def test_project_info_names_a_folder_under_home_with_a_tilde(tmp_path):
    restore = saved_config()
    try:
        home = tmp_path / "h"
        write(home / "repo", {"name": "m", "runs": "~/perf-runs/m"})
        env = {"HOME": str(home)}
        project.apply(home / "repo", env)
        assert project.info(env)["runs"] == "~/perf-runs/m"
    finally:
        restore()


def test_project_info_never_prints_an_absolute_path(tmp_path):
    restore = saved_config()
    try:
        write(tmp_path / "repo", {"name": "m", "runs": "../outside/runs"})
        env = {"HOME": "/nonexistent"}
        project.apply(tmp_path / "repo", env)
        got = project.info(env)
        assert got["runs"] == "runs" and str(tmp_path) not in json.dumps(got), got
    finally:
        restore()


def test_project_info_without_a_project(tmp_path):
    restore = saved_config()
    try:
        for env, source in (({"HOME": "/nonexistent"}, "default"),
                            ({"HOME": "/nonexistent", "METAL_TRACE_OUT": str(tmp_path / "o")}, "METAL_TRACE_OUT")):
            project.apply(tmp_path, env)
            got = project.info(env)
            assert got["project"] is None and got["profile"] == "generic" and got["baseline"] is None, got
            assert got["source"] == source and str(tmp_path) not in json.dumps(got), got
    finally:
        restore()


def test_project_info_reports_a_wrong_project_file(tmp_path):
    restore = saved_config()
    try:
        write(tmp_path, {"name": "m"})
        project.apply(tmp_path, {"HOME": "/nonexistent"})
        try:
            project.info({"HOME": "/nonexistent"})
            raise AssertionError("a wrong project file must be reported")
        except paths.ToolError as error:
            assert "runs" in str(error)
    finally:
        restore()


def test_project_info_tool_reads_the_environment(tmp_path):
    restore = saved_config()
    try:
        project.apply(tmp_path, {"HOME": "/nonexistent"})
        assert project.tool_project_info()["project"] is None
    finally:
        restore()


def test_project_info_source_follows_the_folder_in_use(tmp_path):
    restore = saved_config()
    try:
        write(tmp_path / "repo", {"name": "m", "runs": "perf-runs"})
        env = {"HOME": "/nonexistent", "METAL_TRACE_OUT": str(tmp_path / "o")}
        project.apply(tmp_path / "repo", env)
        assert project.info(env)["source"] == "project file", "the project file wins over METAL_TRACE_OUT"
        env = {"HOME": "/nonexistent", "METAL_TRACE_OUT": ""}
        project.apply(tmp_path, env)
        assert project.info(env)["source"] == "METAL_TRACE_OUT", "an empty METAL_TRACE_OUT is still the one in use"
    finally:
        restore()
