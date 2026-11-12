"""Tests of project.py: the metal-gpu-trace.json project file, which names a project and the folder of its recordings."""
import json

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
