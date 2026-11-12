# metal-gpu-trace

MCP server (stdio and Streamable HTTP, JSON-RPC, standard library only) and shell scripts that record Wine or macOS
programs with Instruments' Metal System Trace on Apple silicon and read the recordings back. Published as
`metal-gpu-trace` on PyPI.

## Layout

- `src/metal_gpu_trace/`: the package. `metal_trace_mcp.py` holds `INSTRUCTIONS`, the text clients read about how to
  use the server; `registry.py` the tools, resources and prompts; `protocol.py`, `stdio.py`, `http_transport.py` and
  `worker.py` the JSON-RPC side; `recording.py`, `experiments.py` and `analysis.py` what the tools do.
- `src/metal_gpu_trace/perf_record.sh`: records one run; `perf_report.py`: summarizes a `.trace`;
  `gputrace_read.py`: reads `.gputrace`; `perf_record_windows.py`: the Windows recording engine.
- `src/metal_gpu_trace/data/`: Apple GPU family facts, workloads and the HTML panel.
- `tests/`: `test_*.py` per area, `run.py` runs them without pytest; `conformance/` uses the official MCP SDK as a
  client. `windows/`: the scripts that run the Windows tests.

## Rules

- Usage rules belong in `INSTRUCTIONS` in `src/metal_gpu_trace/metal_trace_mcp.py`, so they travel with the server:
  one recording at a time, 30 s or more under Wine, compare recordings of 100 frames or more, repeat a run before
  calling a change real.
- Standard library only; Python 3.9 or newer; run scripts with `python3 -I`.
- Summaries are shared: no machine name, UUID or absolute path in them or in the repo.
- Every change gets a test in the matching `tests/test_*.py` and a line in `CHANGELOG.md` under the version it ships
  in.
- Check with `python3 -I tests/run.py`; it must print `ok`. `python -m pytest tests` also runs the Windows tests on
  Windows.
- Never commit, tag, push or release without the owner's explicit go-ahead.
