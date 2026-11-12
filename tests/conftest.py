"""Lets pytest import the package from src/ and the shared helpers from tests/."""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
for path in (HERE.parent / "src", HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
import support  # noqa: E402,F401  (before any test imports config: the tests' own recording lock)
