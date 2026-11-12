"""The CI's `changes` job starts the macOS and Windows jobs from the changed paths: every code and test file must start
the jobs that cover it, or a change would pass CI without them."""
import re
import subprocess

from support import ROOT


def ci_patterns():
    """Returns {job: regex} from the grep lines of test.yml's `changes` job, read as text (no YAML parser)."""
    text = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    found = dict((job, pattern) for pattern, job in re.findall(r"grep -qE '([^']+)' <<< \"\$files\" && (\w+)=true", text))
    assert set(found) == {"windows", "macos"}, found
    return {job: re.compile(pattern) for job, pattern in found.items()}


def test_ci_paths():
    """Every package module starts both jobs, every test file starts macOS, and the README starts neither."""
    if not (ROOT / ".git").exists():  # an unpacked sdist has no git history to list
        return
    patterns = ci_patterns()
    files = subprocess.run(["git", "ls-files", "src", "tests"], cwd=ROOT, text=True, capture_output=True,
                           check=True).stdout.split()
    modules = [f for f in files if re.fullmatch(r"src/metal_gpu_trace/[^/]+\.py", f)]
    assert modules, files
    for f in modules:
        assert patterns["windows"].search(f) and patterns["macos"].search(f), f
    for f in (f for f in files if f.startswith("tests/")):
        assert patterns["macos"].search(f), f
    for f in ("tests/test_perf_record_windows.py", "tests/conftest.py"):  # the Windows job runs these
        assert patterns["windows"].search(f), f
    assert not any(p.search("README.md") for p in patterns.values())
