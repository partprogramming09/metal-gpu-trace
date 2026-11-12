# ADR-0001: Package in `src/metal_gpu_trace/`, tests in `tests/`

**Reader:** people

- **Status:** accepted
- **Date:** 2026-11-11
- **Decided by:** the maintainer

## Context
Until 0.22.0 the server, the scripts and the self-check lived at the repository root, and the server was one file of
about 2,000 lines. The wheel was built from a hand-kept file list, a test could import a module the wheel did not ship,
and every change touched the same file.

## Decision
The code is one package in `src/metal_gpu_trace/`, split into modules with one job each, and the tests live in
`tests/`. Modules import each other as modules (`from metal_gpu_trace import config`), so a test can patch one name in
one place; `tests/test_architecture.py` checks that and the layers in `docs/architecture.md`.

## Alternatives considered
| Option | For | Against | Why yes / no |
|---|---|---|---|
| `src/` package + `tests/` (chosen) | The tests run against the installed layout; the wheel ships exactly the package | Scripts run by path need a short bootstrap (`python3 -I` does not add the script's folder to `sys.path`) | Yes: the Python Packaging User Guide describes it as the layout that tests the installed package ([src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)) |
| Keep everything at the root | No move | A test can pass while the wheel lacks a file; one 2,000-line module | No |
| Subpackages (`domain/`, `transport/`) | Groups by layer | More import paths for about twenty small modules | No: flat modules and a layer test are enough at this size |

## Consequences
- **Positive:** the wheel is built from the package folder; `python -m metal_gpu_trace` works; each module is small.
- **Negative / cost:** paths in old notes and in the Windows bridge script changed once (see the CHANGELOG for 0.23.0).
- **Harder:** nothing day to day; a new module has to pick its layer.

## Revisit when
The package grows past about 30 modules, or a second program needs part of it as a library.
