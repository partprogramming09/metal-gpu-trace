# Run from a clone

**Reader:** people who work on the code, or run it without PyPI.

Everything runs with Python 3.9 or newer and the standard library; nothing has to be installed. Run Python with `-I`
(isolated mode) so a file in the current folder can never shadow a module.

## The server

```sh
python3 -I src/metal_gpu_trace/metal_trace_mcp.py                           # stdio, what MCP clients start
PYTHONPATH=src python3 -m metal_gpu_trace                                  # the same, as a package
METAL_TRACE_TOKEN=<16+ random chars> python3 -I src/metal_gpu_trace/metal_trace_mcp.py --http --port 8765
```

`-I` ignores `PYTHONPATH`, so the `-m` form runs without it (or from an installed wheel). Running a file by its path
works with `-I` because each entry script adds its package folder itself.

Register the clone with Claude Code:

```sh
claude mcp add --scope user metal-trace -e METAL_TRACE_OUT=$HOME/perf-runs -- python3 -I "$PWD/src/metal_gpu_trace/metal_trace_mcp.py"
```

## The scripts

```sh
PERF_OUT=~/perf-runs zsh src/metal_gpu_trace/perf_record.sh app-metal 30 native - /path/to/app ./app
python3 -I src/metal_gpu_trace/perf_report.py path/to/recording.trace
python3 -I src/metal_gpu_trace/gputrace_read.py path/to/capture.gputrace
```

From a clone, `perf_record.sh` writes its logs to `logs/perf/` at the repository root (ignored by git).

## The checks

```sh
python3 -I tests/run.py                       # prints ok
python3 -I tests/run.py test_server           # one test module
```

`CONTRIBUTING.md` lists the other checks (pytest, the official MCP SDK, the wheel smoke test).
