"""Runs every test_* function of every tests/test_*.py without pytest: python3 -I tests/run.py [module ...].

Each module runs its tests in source order; a test that takes tmp_path gets a fresh temporary directory. The first
failure stops the run with its traceback and a non-zero exit. test_perf_record_windows.py is left out: it needs
pytest and Windows."""
import importlib
import inspect
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SKIP = {"test_perf_record_windows"}


def tests_of(module):
    """Returns the module's test_* functions in source order."""
    found = [f for name, f in vars(module).items() if name.startswith("test_") and callable(f)
             and getattr(inspect.unwrap(f), "__module__", None) == module.__name__]
    return sorted(found, key=lambda f: inspect.unwrap(f).__code__.co_firstlineno)


def run(test):
    if inspect.signature(test).parameters:
        with tempfile.TemporaryDirectory() as tmp:
            test(pathlib.Path(tmp).resolve())
    else:
        test()


def main(names):
    sys.path.insert(0, str(HERE))
    import support  # noqa: F401  (puts src/ on sys.path)
    names = names or sorted(p.stem for p in HERE.glob("test_*.py") if p.stem not in SKIP)
    count = 0
    for name in names:
        for test in tests_of(importlib.import_module(name)):
            run(test)
            count += 1
    print(f"{count} tests ok")
    print("ok")


if __name__ == "__main__":
    main(sys.argv[1:])
