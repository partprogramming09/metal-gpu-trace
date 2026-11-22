"""Tests of init.py: `metal-gpu-trace init` writes the server into client configs, merging and never touching the real HOME."""
import json
import stat
import os
import pathlib
import subprocess
import sys
import types

from support import ROOT  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import init, perf_record_windows_presentmon


def fake_uvx(tmp_path, name="bin dir"):
    """Returns (folder, uvx path): an executable uvx in a folder whose name has a space."""
    folder = tmp_path / name
    folder.mkdir()
    uvx = folder / "uvx"
    uvx.write_text("#!/bin/sh\n")
    uvx.chmod(0o755)
    return folder, uvx


def go(tmp_path, *argv, uvx=True, platform="darwin", run=None, claude=False, xcrun=None):
    """Runs init.main in a fake HOME under tmp_path; returns (code, home, uvx path)."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    folder, path = fake_uvx(tmp_path) if uvx and not (tmp_path / "bin dir").exists() else (tmp_path / "bin dir", tmp_path / "bin dir" / "uvx")
    environ = {"PATH": str(folder) if uvx else str(tmp_path / "empty")}
    which = (lambda name, **k: "/x/claude" if name == "claude" and claude else xcrun if name == "xcrun" else None)
    code = init.main(list(argv), environ=environ, home=home, cwd=tmp_path / "proj", platform=platform,
                     extra_dirs=(), run=run or subprocess.run, which=which)
    return code, home, path


DESKTOP = ("Library", "Application Support", "Claude", "claude_desktop_config.json")


def test_desktop_writes_absolute_paths_with_spaces(tmp_path):
    code, home, uvx = go(tmp_path, "--client", "claude-desktop")
    data = json.loads(home.joinpath(*DESKTOP).read_text())
    entry = data["mcpServers"]["metal-trace"]
    assert code == 0 and entry["command"] == str(uvx) and " " in entry["command"]
    assert entry["args"] == ["metal-gpu-trace"]
    assert entry["env"] == {"METAL_TRACE_OUT": str(home / "perf-runs")}  # no Wine found or given: no key


def test_merge_keeps_other_servers_and_makes_bak(tmp_path):
    (tmp_path / "home").mkdir()
    path = tmp_path / "home" / ".cursor" / "mcp.json"
    path.parent.mkdir()
    before = json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": 1})
    path.write_text(before)
    code, _, _ = go(tmp_path, "--client", "cursor")
    data = json.loads(path.read_text())
    assert code == 0 and data["mcpServers"]["other"] == {"command": "x"} and data["theme"] == 1
    assert data["mcpServers"]["metal-trace"]["type"] == "stdio"
    assert path.with_name("mcp.json.bak").read_text() == before


def test_keeps_the_file_mode_and_never_overwrites_an_older_bak(tmp_path):
    # found on a real Claude Desktop config: it was 600 and the rewrite left it 644; an older .bak was replaced
    (tmp_path / "home").mkdir()
    path = tmp_path / "home" / ".cursor" / "mcp.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    path.chmod(0o600)
    old = path.with_name("mcp.json.bak")
    old.write_text("an older backup")
    code, _, _ = go(tmp_path, "--client", "cursor")
    assert code == 0 and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert old.read_text() == "an older backup"  # kept: the new copy has its own name
    copies = [f for f in path.parent.iterdir() if f.name.startswith("mcp.json.bak-")]
    assert len(copies) == 1 and json.loads(copies[0].read_text())["mcpServers"] == {"other": {"command": "x"}}


def test_idempotent(tmp_path):
    go(tmp_path, "--client", "cursor")
    path = tmp_path / "home" / ".cursor" / "mcp.json"
    first = path.read_text()
    go(tmp_path, "--client", "cursor")
    assert path.read_text() == first
    assert not path.with_name("mcp.json.bak").exists()  # the second run wrote nothing


def test_invalid_json_is_refused_untouched(tmp_path):
    path = tmp_path / "home" / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    code, _, _ = go(tmp_path, "--client", "cursor")
    assert code == 2 and path.read_text() == "{not json" and not path.with_name("mcp.json.bak").exists()


def test_without_uvx_says_what_to_do(tmp_path):
    code, home, _ = go(tmp_path, "--client", "claude-desktop", uvx=False)
    assert code == 2 and not home.joinpath(*DESKTOP).exists()
    try:
        init.find_uvx({"PATH": ""}, home, ())
    except init.InitError as error:
        assert "brew install uv" in str(error)
    else:
        raise AssertionError("find_uvx should raise")


def test_dry_run_writes_nothing(tmp_path):
    code, home, _ = go(tmp_path, "--client", "claude-desktop", "--dry-run")
    assert code == 0 and not home.joinpath("Library").exists()
    code, home, _ = go(tmp_path, "--client", "codex", "--dry-run")
    assert code == 0 and not (home / ".codex").exists()


def test_codex_append_then_exists(tmp_path):
    path = tmp_path / "home" / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('model = "x"')
    go(tmp_path, "--client", "codex")
    text = path.read_text()
    assert text.startswith('model = "x"\n') and "[mcp_servers.metal-trace]" in text and "METAL_TRACE_OUT" in text
    assert path.with_name("config.toml.bak").read_text() == 'model = "x"'
    go(tmp_path, "--client", "codex")  # already there: shown, not edited
    assert path.read_text() == text


def test_wine_passed_is_validated_and_written(tmp_path):
    wine = tmp_path / "wine dir"
    (wine / "bin").mkdir(parents=True)
    (wine / "bin" / "wine").write_text("")
    (wine / "bin" / "wine").chmod(0o755)
    code, home, _ = go(tmp_path, "--client", "claude-desktop", "--wine", str(wine))
    env = json.loads(home.joinpath(*DESKTOP).read_text())["mcpServers"]["metal-trace"]["env"]
    assert code == 0 and env["METAL_TRACE_WINE"] == str(wine)
    code, _, _ = go(tmp_path, "--client", "cursor", "--wine", str(tmp_path / "nope"))
    assert code == 2


def test_vscode_needs_project_and_project_file_is_in_cwd(tmp_path):
    code, home, _ = go(tmp_path, "--client", "vscode")
    assert code == 2
    code, home, _ = go(tmp_path, "--client", "vscode", "--project")
    data = json.loads((tmp_path / "proj" / ".vscode" / "mcp.json").read_text())
    assert code == 0 and data["servers"]["metal-trace"]["type"] == "stdio"


def output_of(run_go):
    """Returns what `init.main` printed on stdout: the tests' runner hands no capsys (tests/run.py has no pytest)."""
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = run_go()
    return code, out.getvalue()


def test_init_names_the_missing_xctrace_with_its_real_fix(tmp_path):
    """`init` looked for xcrun alone and said `xcode-select --install`, which the Command Line Tools satisfy without
    bringing xctrace: it uses the same report the recording does."""
    code, out = output_of(lambda: go(tmp_path, "--client", "cursor")[0])  # no xcrun on this PATH
    assert code == 0 and "xctrace" in out and "xcode-select --install" not in out, out


def test_init_says_nothing_when_xctrace_is_found(tmp_path):
    """A report of `ok` prints no note: no invented warning on a machine that can record."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    xcrun = stubs / "xcrun"
    xcrun.write_text('#!/bin/sh\n[ "$1" = --find ] && [ "$2" = xctrace ] && echo "$2"\n')
    xcrun.chmod(0o755)
    code, out = output_of(lambda: go(tmp_path, "--client", "cursor", xcrun=str(xcrun))[0])
    assert code == 0 and "note:" not in out, out


def test_windows_init_notes_a_missing_presentmon_with_its_fix(tmp_path):
    """A Windows machine without PresentMon still gets the server written, plus the note that says how to install it."""
    saved = perf_record_windows_presentmon.find_presentmon
    perf_record_windows_presentmon.find_presentmon = lambda: None
    try:
        code, out = output_of(lambda: go(tmp_path, "--client", "cursor", platform="win32")[0])
    finally:
        perf_record_windows_presentmon.find_presentmon = saved
    assert code == 0 and (tmp_path / "home" / ".cursor" / "mcp.json").exists(), out
    assert "presentmon_install" in out, out


def test_unverified_system_says_not_supported(tmp_path):
    code, home, _ = go(tmp_path, "--client", "claude-desktop", platform="linux")
    assert code == 2 and not (home / ".config").exists()


def test_detects_installed_clients(tmp_path):
    (tmp_path / "home" / ".cursor").mkdir(parents=True)
    code, home, _ = go(tmp_path)
    assert code == 0 and (home / ".cursor" / "mcp.json").exists()
    assert not home.joinpath(*DESKTOP).exists()  # Claude Desktop is not installed here
    other = tmp_path / "again"
    other.mkdir()
    assert go(other)[0] == 2  # nothing installed: asks for --client


def test_claude_code_runs_claude_mcp_add_once(tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return types.SimpleNamespace(returncode=1 if argv[2] == "get" else 0, stdout="", stderr="")

    assert go(tmp_path, "--client", "claude-code", run=run, claude=True)[0] == 0
    add = calls[-1]
    assert add[:6] == ["claude", "mcp", "add", "--scope", "user", "metal-trace"]
    assert add[-2:] == [str(tmp_path / "bin dir" / "uvx"), "metal-gpu-trace"]
    assert not any(a.startswith("~") for a in add)
    calls.clear()
    go(tmp_path, "--client", "claude-code", "--dry-run", run=run, claude=True)
    assert calls == []  # a dry run runs nothing


def test_real_home_is_not_touched(tmp_path):
    before = os.path.getmtime(pathlib.Path.home())
    go(tmp_path, "--client", "cursor")
    assert os.path.getmtime(pathlib.Path.home()) == before


def test_cli_entry_point_runs_init(tmp_path):
    done = subprocess.run([sys.executable, "-I", str(ROOT / "src" / "metal_gpu_trace" / "metal_trace_mcp.py"), "init", "--help"],
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0 and "--dry-run" in done.stdout


def test_write_file_follows_neither_a_planted_tmp_nor_a_symlinked_config(tmp_path):
    # review findings: a fixed .tmp name followed a planted link; os.replace turned a symlinked dotfile into a plain file
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    config = tmp_path / "real.json"
    config.write_text("{}")
    (tmp_path / "real.json.tmp").symlink_to(victim)
    init.write_file(config, '{"a": 1}\n')
    assert victim.read_text() == "keep me" and config.read_text() == '{"a": 1}\n'
    link = tmp_path / "dotfile.json"
    link.symlink_to(config)
    init.write_file(link, '{"b": 2}\n')
    assert link.is_symlink() and config.read_text() == '{"b": 2}\n'


def test_backups_never_replace_each_other(tmp_path):
    path = tmp_path / "c.json"
    for n in range(1, 5):  # four writes inside one second: three older versions must all survive
        init.write_file(path, f"v{n}\n")
    kept = sorted(f.read_text() for f in tmp_path.iterdir() if f.name.startswith("c.json.bak"))
    assert kept == ["v1\n", "v2\n", "v3\n"], kept


def test_toml_is_not_edited_when_the_block_may_exist_or_the_file_is_not_toml(tmp_path):
    cases = ["[ mcp_servers . metal-trace ]\ncommand = 'x'\n", "[mcp_servers]\nmetal-trace = { command = 'x' }\n",
             "[mcp_servers.metal-trace.env]\nA = 'b'\n"]
    if init.tomllib:  # Python 3.9 and 3.10 have no TOML parser: there the name check is all there is
        cases.append("this is [not toml\n")
    for text in cases:
        path = tmp_path / "config.toml"
        path.write_text(text)
        result = init.merge_toml(path, init.toml_block("/u/uvx", {"METAL_TRACE_OUT": "/o"}), False)
        assert path.read_text() == text and not path.with_name("config.toml.bak").exists(), (text, result)


def test_toml_block_keeps_non_bmp_characters_as_they_are():
    block = init.toml_block("/u/uvx", {"METAL_TRACE_OUT": "/tmp/\U0001F600"})
    assert "\U0001F600" in block and "\\ud83d" not in block


def test_claude_code_command_is_quoted_and_uses_the_given_which():
    shown = init.claude_code("/u/uvx", {"METAL_TRACE_OUT": "/tmp/a'b;id"}, "user", True, which=lambda name: None)
    import shlex  # what a shell would hand to claude: the value with its quote and its ';' intact, in one word
    assert "METAL_TRACE_OUT=/tmp/a'b;id" in shlex.split(shown.splitlines()[1]), shown


def test_empty_out_or_wine_is_a_usage_error(tmp_path):
    for flag in ("--out", "--wine"):
        try:
            go(tmp_path, "--client", "cursor", flag, "")
        except SystemExit as exit_:
            assert exit_.code == 2
        else:
            raise AssertionError(f"{flag} '' was accepted")
