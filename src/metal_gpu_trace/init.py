"""`metal-gpu-trace init`: writes the server into the config of the AI apps found on this machine.

Every path written is absolute and already resolved (no client documents `~` or `$HOME` expansion). An existing JSON
config is merged, never overwritten, and copied to <file>.bak first; one that is not valid JSON is refused untouched."""
import argparse
import json
import os
import pathlib
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from metal_gpu_trace import preflight

try:
    import tomllib  # Python 3.11+: only used to check a config is still valid TOML
except ImportError:
    tomllib = None

NAME = "metal-trace"
CLIENTS = ("claude-code", "claude-desktop", "cursor", "codex", "vscode")
UVX_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin", "~/.cargo/bin")
NO_UVX = ("uvx not found. Install uv (macOS: `brew install uv`; other systems: https://docs.astral.sh/uv/), "
          "then run init again.")


class InitError(Exception):
    """A reason init cannot do what was asked, in words that say what to do."""


def find_uvx(environ, home, extra_dirs=UVX_DIRS):
    """Returns the absolute path of uvx from PATH or the usual install folders; raises InitError when it is nowhere."""
    found = shutil.which("uvx", path=environ.get("PATH", ""))
    if found:
        return os.path.abspath(found)
    for folder in extra_dirs:
        candidate = pathlib.Path(folder.replace("~", str(home), 1)) / "uvx"
        if preflight.executable(candidate) and candidate.is_file():
            return str(candidate)
    raise InitError(NO_UVX)


def server_env(out, wine):
    """Returns the environment of the server entry: the runs folder, plus the Wine directory when there is one."""
    env = {"METAL_TRACE_OUT": out}
    if wine:
        env["METAL_TRACE_WINE"] = wine
    return env


def user_file(client, home, platform):
    """Returns the user-level config file of a client, or raises InitError when its path is not verified here."""
    if client == "cursor":
        return home / ".cursor" / "mcp.json"
    if platform == "darwin":
        if client == "claude-desktop":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if client == "codex":
            return home / ".codex" / "config.toml"
    if client == "vscode":
        raise InitError("vscode: the user-level file is not verified; use --project to write .vscode/mcp.json")
    raise InitError(f"{client}: not supported yet on this system")


def project_file(client, cwd):
    """Returns the project-level config file of a client, or raises InitError when it has none."""
    files = {"cursor": (".cursor", "mcp.json"), "vscode": (".vscode", "mcp.json"), "codex": (".codex", "config.toml")}
    if client not in files:
        raise InitError(f"{client}: no project-level file (only cursor, vscode and codex)")
    return cwd.joinpath(*files[client])


def installed(home, platform, which=shutil.which):
    """Returns the clients that look installed here (vscode is never guessed: it needs --project)."""
    found = []
    if which("claude"):
        found.append("claude-code")
    if platform == "darwin" and (home / "Library" / "Application Support" / "Claude").is_dir():
        found.append("claude-desktop")
    if (home / ".cursor").is_dir():
        found.append("cursor")
    if platform == "darwin" and ((home / ".codex").is_dir() or which("codex")):
        found.append("codex")
    return found


def write_file(path, text):
    """Writes `text` to `path` through a private temporary file made next to it, keeping the file's mode. A symlinked
    config (a dotfile manager) is written through its link. An existing file is copied first to <path>.bak, or to
    <path>.bak-<time>[-n] when that name is taken: an older backup is never replaced."""
    path = pathlib.Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o600  # a config may hold keys of other servers: a new file is private, an old one keeps its own mode
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        backup = path.with_name(path.name + ".bak")
        stamp, n = time.strftime("%Y%m%d-%H%M%S"), 0
        while os.path.lexists(backup):
            n += 1
            backup = path.with_name(f"{path.name}.bak-{stamp}" + (f"-{n}" if n > 1 else ""))
        shutil.copy2(path, backup)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)  # O_EXCL, mode 600
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        if os.path.lexists(temporary):
            os.remove(temporary)
        raise


def merge_json(path, key, entry, dry_run):
    """Adds the server under `key`, keeping every other server. Returns a one-line result."""
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (ValueError, OSError) as error:
            raise InitError(f"{path} is not valid JSON ({error}); fix or move it, nothing was changed") from None
        if not isinstance(data, dict) or not isinstance(data.get(key, {}), dict):
            raise InitError(f"{path} does not have the shape {{\"{key}\": {{...}}}}; nothing was changed")
    if data.get(key, {}).get(NAME) == entry:
        return f"{path}: already configured"
    data.setdefault(key, {})[NAME] = entry
    text = json.dumps(data, indent=2) + "\n"
    if dry_run:
        return f"{path}: would write\n{text}"
    write_file(path, text)
    return f"{path}: configured"


def toml_string(value):
    """Returns `value` as a TOML basic string: json.dumps escapes quotes and control characters the same way."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def toml_block(command, env):
    """Returns the Codex config block of the server."""
    pairs = ", ".join(f"{k} = {toml_string(v)}" for k, v in env.items())
    return (f"[mcp_servers.{NAME}]\ncommand = {toml_string(command)}\nargs = [\"metal-gpu-trace\"]\n"
            f"env = {{ {pairs} }}\n")


def merge_toml(path, block, dry_run):
    """Appends the block when the name appears nowhere in the file; otherwise (or when the file is not valid TOML, or
    would stop being) shows the block and edits nothing. No parser runs on Python 3.9 and 3.10, so the check is the name."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if NAME in text:
        return f"{path}: {NAME} is already mentioned, not edited; [mcp_servers.{NAME}] should hold:\n{block}"
    new = text + ("" if not text or text.endswith("\n") else "\n") + ("\n" if text else "") + block
    if tomllib:
        try:
            tomllib.loads(text)
            tomllib.loads(new)
        except ValueError as error:
            return f"{path}: not valid TOML ({error}), not edited; [mcp_servers.{NAME}] should hold:\n{block}"
    if dry_run:
        return f"{path}: would append\n{block}"
    write_file(path, new)
    return f"{path}: configured"


def claude_code(command, env, scope, dry_run, run=subprocess.run, which=shutil.which):
    """Registers the server with `claude mcp add` (never editing ~/.claude.json by hand); skips it when present."""
    argv = ["claude", "mcp", "add", "--scope", scope, NAME]
    for key, value in env.items():
        argv += ["-e", f"{key}={value}"]
    argv += ["--", command, "metal-gpu-trace"]
    shown = " ".join(shlex.quote(a) for a in argv)
    if dry_run or not which("claude"):
        return f"claude-code: {'would run' if dry_run else 'claude is not on PATH; run'}\n  {shown}"
    if run(["claude", "mcp", "get", NAME], capture_output=True).returncode == 0:
        return f"claude-code: {NAME} already added (claude mcp remove {NAME} to redo it)"
    done = run(argv, capture_output=True, text=True)
    if done.returncode:
        raise InitError(f"claude mcp add failed: {(done.stderr or done.stdout).strip()}")
    return "claude-code: configured"


def nonempty(value):
    if not value.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return value


def build_parser():
    parser = argparse.ArgumentParser(prog="metal-gpu-trace init", description="Add metal-gpu-trace to AI apps.")
    parser.add_argument("--client", choices=CLIENTS, help="one app; without it, every installed app found")
    parser.add_argument("--wine", metavar="DIR", type=nonempty, help="Wine directory holding bin/wine (METAL_TRACE_WINE)")
    parser.add_argument("--out", metavar="DIR", type=nonempty, help="folder for recordings (default ~/perf-runs)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be written; write nothing")
    parser.add_argument("--project", action="store_true", help="write the project's config, not the user's")
    return parser


def main(argv, environ=None, home=None, cwd=None, platform=None, extra_dirs=UVX_DIRS, run=subprocess.run,
         which=shutil.which):
    """Runs init and returns the exit code: 0 done, 2 a usage problem or an error (nothing half written)."""
    environ = os.environ if environ is None else environ
    home = pathlib.Path(os.path.expanduser("~") if home is None else home)
    cwd = pathlib.Path.cwd() if cwd is None else pathlib.Path(cwd)
    platform = sys.platform if platform is None else platform
    args = build_parser().parse_args(argv)
    try:
        uvx = find_uvx(environ, home, extra_dirs)
        wine = args.wine or environ.get("METAL_TRACE_WINE")
        if wine:
            wine = os.path.abspath(os.path.expanduser(wine))
            if not preflight.executable(pathlib.Path(wine) / "bin" / "wine"):
                if args.wine:
                    raise InitError(f"no Wine at bin/wine inside {wine}")
                wine = None
        out = os.path.abspath(os.path.expanduser(args.out)) if args.out else str(home / "perf-runs")
        env = server_env(out, wine)
        clients = [args.client] if args.client else installed(home, platform, which)
        if not clients:
            raise InitError("no supported app found; name one with --client " + "|".join(CLIENTS))
    except InitError as error:
        print(f"metal-gpu-trace init: {error}", file=sys.stderr)
        return 2
    if platform == "darwin" and not which("xcrun"):
        print("note: xcrun not found; recording needs Xcode (xcode-select --install)")
    if not args.client:
        print("found: " + ", ".join(clients))
    failed = False
    for client in clients:
        try:
            if client == "claude-code":
                result = claude_code(uvx, env, "project" if args.project else "user", args.dry_run, run, which)
            else:
                path = project_file(client, cwd) if args.project else user_file(client, home, platform)
                entry = {"command": uvx, "args": ["metal-gpu-trace"], "env": env}
                if client == "codex":
                    result = merge_toml(path, toml_block(uvx, env), args.dry_run)
                elif client in ("cursor", "vscode"):
                    result = merge_json(path, "servers" if client == "vscode" else "mcpServers",
                                        {"type": "stdio", **entry}, args.dry_run)
                else:
                    result = merge_json(path, "mcpServers", entry, args.dry_run)
                if args.project and not args.dry_run:
                    result += "\n  note: this file holds absolute paths of this machine; do not commit it (add it to .gitignore)"
            print(result)
        except InitError as error:
            failed = True
            print(f"{client}: {error}", file=sys.stderr)
    if not failed and any(c in ("claude-desktop", "cursor", "codex", "vscode") for c in clients) and not args.dry_run:
        print("Restart the app to load the server.")
    return 2 if failed else 0
