"""Guards of the package layout: modules import each other as modules (so a test's patch reaches every user), lower
layers never import higher ones, and every name a test patches still exists where the test patches it."""
import ast
import importlib
import os
import subprocess
import sys

from support import PKG, ROOT  # also puts src/ on sys.path

PACKAGE = "metal_gpu_trace"
NOT_MODULES = {"__init__", "__main__"}  # __main__ starts the server when imported

# lower numbers are lower layers; a module imports modules of its own layer or below, never above
LAYERS = {
    "config": 0, "logs": 0, "metrics": 0, "gputrace_read": 0, "perf_report": 0, "perf_record_windows": 0,
    "paths": 1, "project": 1,
    "recording": 2, "workloads": 2, "analysis": 2, "experiments": 2, "panel": 2, "traces": 2,
    "registry": 3,
    "worker": 4,
    "protocol": 5,
    "stdio": 6, "http_transport": 6,
    "metal_trace_mcp": 7,
}


def module_names():
    return sorted(p.stem for p in PKG.glob("*.py") if p.stem not in NOT_MODULES)


def imports_of(tree):
    """Returns (module, name, node) for each `from metal_gpu_trace... import` and `import metal_gpu_trace...` in the
    tree, including those inside functions. `module` is "" for `from metal_gpu_trace import name`; a relative import
    reports its dots in `module`."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                found.extend(("." * node.level + (node.module or ""), a.name, node) for a in node.names)
            elif node.module == PACKAGE:
                found.extend(("", a.name, node) for a in node.names)
            elif node.module and node.module.startswith(PACKAGE + "."):
                found.extend((node.module[len(PACKAGE) + 1:], a.name, node) for a in node.names)
        elif isinstance(node, ast.Import):
            found.extend((a.name[len(PACKAGE) + 1:], "", node) for a in node.names if a.name.startswith(PACKAGE + "."))
    return found


def test_package_imports_modules_only():
    """Only `from metal_gpu_trace import <module>` is allowed: `from metal_gpu_trace.x import name` and relative imports
    copy a name, and a test's patch of `x.name` would no longer reach the module that copied it."""
    assert "config" in module_names(), "the configuration lives in config.py"
    bad = []
    for name in module_names():
        for module, imported, node in imports_of(ast.parse((PKG / f"{name}.py").read_text(encoding="utf-8"))):
            if module or imported not in module_names():
                bad.append(f"{name}.py:{node.lineno} imports {module or PACKAGE}.{imported}")
    assert not bad, bad


def package_imports(name):
    tree = ast.parse((PKG / f"{name}.py").read_text(encoding="utf-8"))
    return {imported for module, imported, _ in imports_of(tree) if not module}


def test_layers():
    """A module imports only modules of its own layer or a lower one; every module has a layer."""
    assert set(module_names()) == set(LAYERS), "give each module a layer in LAYERS"
    bad = [f"{name} (layer {LAYERS[name]}) imports {other} (layer {LAYERS[other]})"
           for name in module_names() for other in sorted(package_imports(name))
           if other in LAYERS and LAYERS[other] > LAYERS[name]]
    assert not bad, bad


def patched_targets(tree):
    """Returns (alias, attribute, line) for each `alias.attribute = ...`, `alias.attribute[key] = ...` and
    `monkeypatch.setattr(alias, "attribute", ...)` in the tree."""
    found = []

    def target(node):
        if isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                target(item)
        elif isinstance(node, ast.Subscript):
            target(node.value)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            found.append((node.value.id, node.attr, node.lineno))

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for item in node.targets:
                target(item)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            target(node.target)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in (
                "setattr", "setitem", "delattr") and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) \
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
            found.append((node.args[0].id, node.args[1].value, node.lineno))
    return found


def test_patched_names_exist():
    """Each `<module>.<name> = ...` in the tests names an attribute that exists in that module of src/, so a patch never
    points at a name that moved elsewhere."""
    bad = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = {}
        for module, imported, node in imports_of(tree):
            if not module:
                aliases[next(a.asname or a.name for a in node.names if a.name == imported)] = imported
        for alias, attribute, line in patched_targets(tree):
            if alias in aliases:
                if aliases[alias] not in module_names():
                    bad.append(f"{path.name}:{line} patches {alias}, which is not a module of the package")
                elif not hasattr(importlib.import_module(f"{PACKAGE}.{aliases[alias]}"), attribute):
                    bad.append(f"{path.name}:{line} patches {aliases[alias]}.{attribute}, which does not exist")
                else:  # an alias (perf_report.stats is metrics.stats): patching it misses the owner's own callers
                    owner = getattr(getattr(importlib.import_module(f"{PACKAGE}.{aliases[alias]}"), attribute),
                                    "__module__", None)
                    if owner and owner.startswith(f"{PACKAGE}.") and owner != f"{PACKAGE}.{aliases[alias]}":
                        bad.append(f"{path.name}:{line} patches {aliases[alias]}.{attribute}, an alias: patch {owner}")
    assert not bad, bad


def test_config_reload_rereads_the_environment(tmp_path):
    """config.reload() recomputes OUT, READ and BASELINES from METAL_TRACE_OUT and METAL_TRACE_READ."""
    from metal_gpu_trace import config
    saved = config.OUT, config.READ, config.BASELINES
    env = {key: os.environ.get(key) for key in ("METAL_TRACE_OUT", "METAL_TRACE_READ")}
    try:
        os.environ["METAL_TRACE_OUT"] = str(tmp_path / "runs")
        os.environ["METAL_TRACE_READ"] = str(tmp_path / "more")
        config.reload()
        assert config.OUT == (tmp_path / "runs").resolve()
        assert config.READ == [config.OUT, (tmp_path / "more").resolve()]
        assert config.BASELINES == config.OUT / "baselines.json"
    finally:
        for key, value in env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.OUT, config.READ, config.BASELINES = saved


def test_worker_needs_configure():
    """worker used without metal_trace_mcp (which calls worker.configure) fails with a message that names the fix,
    not with "'NoneType' object is not callable"."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from metal_gpu_trace import worker\n"
            "for f in (worker._send, worker._answer):\n"
            "    try:\n        f({})\n    except RuntimeError as e:\n        print(e)\n")
    out = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT / "src")], text=True, capture_output=True)
    assert out.stdout.count("worker.configure() was not called") == 2, (out.stdout, out.stderr)


def imported_modules(tree):
    """Returns the package modules a module's tree imports, by the name it binds them to."""
    bound = {}
    for module, imported, node in imports_of(tree):
        if not module:
            bound[next(a.asname or a.name for a in node.names if a.name == imported)] = imported
    return bound


def test_no_local_hides_a_module():
    """No parameter, local, loop, comprehension or lambda variable is named like a package module its file imports:
    `metrics = {}` inside a function hid the metrics module there, and only the branch that ran it would fail."""
    bad = []
    for name in module_names():
        tree = ast.parse((PKG / f"{name}.py").read_text(encoding="utf-8"))
        modules = imported_modules(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                args = node.args
                names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
                names += [a.arg for a in (args.vararg, args.kwarg) if a]
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names = [node.id]
            else:
                continue
            bad += [f"{name}.py:{node.lineno} binds {n}" for n in names if n in modules]
    assert not bad, bad


def test_module_attributes_exist():
    """Every `<module>.<name>` a package module reads from another package module exists there, Windows-only branches
    included, so a name left behind by the split fails here and not on a user's machine."""
    bad = []
    for name in module_names():
        tree = ast.parse((PKG / f"{name}.py").read_text(encoding="utf-8"))
        modules = imported_modules(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in modules:
                owner = importlib.import_module(f"{PACKAGE}.{modules[node.value.id]}")
                if not hasattr(owner, node.attr):
                    bad.append(f"{name}.py:{node.lineno} reads {modules[node.value.id]}.{node.attr}")
    assert not bad, bad


def test_protocol_needs_configure():
    """protocol used without metal_trace_mcp (which calls protocol.configure) refuses to answer initialize with an
    empty version and instructions, and names the fix."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from metal_gpu_trace import protocol\n"
            "try:\n    protocol.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})\n"
            "except RuntimeError as e:\n    print(e)\n")
    out = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT / "src")], text=True, capture_output=True)
    assert "protocol.configure() was not called" in out.stdout, (out.stdout, out.stderr)
