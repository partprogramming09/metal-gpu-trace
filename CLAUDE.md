# metal-gpu-trace

lanzamientos: continuo

Tipo: abierto

MCP server (stdio and Streamable HTTP, JSON-RPC, standard library only) and scripts that record Wine, macOS or native
Windows programs and read the recordings back. macOS uses Instruments' Metal System Trace on Apple silicon; Windows
uses PresentMon. Published as `metal-gpu-trace` on PyPI.

**Modo de los docs:** terceros (the package is published on PyPI; docs name no personal tools).

Antes de tocar documentación, lee `.claude/ROUTING.md`. Mapa de piezas y flujo: `.claude/ARQUITECTURA.md`.

## Where things live

- Server and tools: `metal_trace_mcp.py` (`INSTRUCTIONS`, the text clients read), `registry.py` (tools, resources,
  prompts), `protocol.py`, `stdio.py`, `http_transport.py`, `worker.py` (JSON-RPC).
- Recording: `recording.py`, `perf_record.sh` (macOS), `perf_record_windows.py` (Windows engine).
- Summaries: `perf_report.py` (macOS `.trace`), `gputrace_read.py` (`.gputrace`), `metrics.py` (the numbers both
  engines share, and `SCHEMA_VERSION`).
- Analysis: `experiments.py`, `analysis.py`. Project and paths: `project.py`, `paths.py`. Facts: `data/`.
- Tests: `tests/test_*.py` per area, `tests/run.py` without pytest, `tests/conformance/` (official MCP SDK as a
  client), `tests/golden/` (contract with clients). Windows machine scripts: `windows/` (repo root, not in `tests/`).

## Rules

- Usage rules belong in `INSTRUCTIONS`, so they travel with the server: one recording at a time, 30 s or more under
  Wine, compare recordings of 100 frames or more, repeat a run before calling a change real.
- Standard library only; Python 3.9 or newer; run scripts with `python3 -I`.
- Summaries are shared: no machine name, UUID or absolute path in them or in the repo.
- Every change gets a test in the matching `tests/test_*.py` and a line in `CHANGELOG.md` under the version it ships in.
- Check with `python3 -I tests/run.py`; it must print `ok`. Lint as CI does: `uvx ruff@0.14.0 check src tests`. `python -m pytest tests` also runs the Windows tests on
  Windows.
- Never commit, tag, push or release without the owner's explicit go-ahead.

## Summary contract (from `schema_version` 3)

- A summary has a `common` block both engines write (frame pacing, memory pressure, graphics API) and, beside it, the
  keys each backend already had. A metric that cannot be measured the same way on both platforms is
  `{"comparable": false, "reason": ...}`, never an invented number. Each metric block says its `source`.
- A new field goes in `common` only when macOS and Windows mean the same thing by it; otherwise it stays in the
  backend's own keys. Adding a key to `common` needs its definition in `docs/guides/` and the key-list test updated.
- Existing keys do not move or change meaning (unless an owner-approved plan says so); readers (`perf_compare`, `perf_history`, `perf_runs`) keep reading
  generations 1, 2 and 3.
- Both engines write the shape through shared code in `metrics.py`, not by hand twice.

