# metal-gpu-trace

MCP server (stdio, JSON-RPC, standard library only) and shell scripts that record Wine or macOS programs with
Instruments' Metal System Trace on Apple silicon and read the recordings back. Published as `metal-gpu-trace` on PyPI.

## Layout

- `metal_trace_mcp.py`: the server, its tools, resources and `INSTRUCTIONS`, the text clients read about how to use it.
- `perf_record.sh`: records one run; `perf_report.py`: summarizes a `.trace`; `gputrace_read.py`: reads `.gputrace`.
- `data/`: Apple GPU family facts and workloads. `test_metal_trace_mcp.py`: the self-check.

## Rules

- Usage rules belong in `INSTRUCTIONS` in `metal_trace_mcp.py`, so they travel with the server: one recording at a
  time, 30 s or more under Wine, compare recordings of 100 frames or more, repeat a run before calling a change real.
- Standard library only; Python 3.9 or newer; run scripts with `python3 -I`.
- Summaries are shared: no machine name, UUID or absolute path in them or in the repo.
- Every change gets a test in `test_metal_trace_mcp.py` and a line under `## Unreleased` in `CHANGELOG.md`.
- Check with `python3 -I test_metal_trace_mcp.py`; it must print `ok`.
- Never commit, tag, push or release without the owner's explicit go-ahead.
