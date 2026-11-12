# Architecture

**Reader:** people who change the code. Reviewed 2026-11-11.

## Why it is shaped this way

The server has to run on a fresh Mac with nothing but the `python3` macOS ships, so it is standard library only
([ADR-0003](adr/0003-python-3-9-floor.md)). It speaks two MCP eras at once ([ADR-0002](adr/0002-dual-era-mcp.md)).
And a recording takes 30 seconds or more, so tool calls run one at a time on a worker thread while the transport
keeps reading messages (to cancel, or to answer `tools/list` meanwhile).

Think of it as a small restaurant: the transport is the waiter, `protocol` reads the order, the `worker` is the one
cook who makes one dish at a time, and the domain modules are the recipes.

## Layers

Each module may import only modules in its own layer or a lower one. `tests/test_architecture.py` holds the same
table (`LAYERS`) and fails when an import goes upward.

```
+------------------------------------------------------------------+
| 7  metal_trace_mcp   entry point: INSTRUCTIONS, version, main()  |
|                      configures protocol and worker              |
+------------------------------------------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 6  stdio             newline-delimited JSON-RPC on stdin/stdout  |
|    http_transport    POST /mcp on 127.0.0.1, bearer token, panel |
+------------------------------------------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 5  protocol          one JSON-RPC request -> one reply; picks    |
|                      the era, checks _meta, decorates results    |
+------------------------------------------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 4  worker            one tool call at a time, cancel, progress   |
+------------------------------------------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 3  registry          tool list and schemas, resources, prompts   |
+------------------------------------------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 2  recording         record a run (perf_record, perf_attach)     |
|    analysis          runs, compare, baselines, gates, diagnose   |
|    experiments       A/B, cold/warm, sweeps                      |
|    workloads         test programs, downloads, PresentMon        |
|    traces            .trace / .gputrace files, GPU families      |
|    panel             the HTML panel                              |
+------------------------------------------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 1  paths             names and paths a caller may use, paging    |
+------------------------------------------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 0  config            settings, read as config.NAME at use time   |
|    logs              one stderr line per tool call               |
|    metrics           numbers Mac and Windows summaries share     |
|    perf_report       summarize a .trace (also a script)          |
|    perf_record_windows  Windows recording (also a script)        |
|    gputrace_read     read a .gputrace (also a script)            |
+------------------------------------------------------------------+
```

`perf_record.sh` (zsh) drives Instruments and calls `perf_report.py`; `data/` holds the GPU family facts and the
workload list.

## Two rules that keep it testable

1. **Import modules, not names:** `from metal_gpu_trace import config`, then `config.OUT`. A test patches one
   attribute and every reader sees it. The architecture test rejects `from metal_gpu_trace.config import OUT`.
2. **Inject upward dependencies:** `protocol` needs the entry point's `INSTRUCTIONS` and version, and `worker` needs
   the transport's `send` and the protocol's `answer` and `finish`; both sit below what they need, so
   `metal_trace_mcp` passes them in with `protocol.configure(instructions, version)` and
   `worker.configure(send, answer, finish)`. Both raise a clear error if used before that.

## One request, end to end

```
client sends tools/call
        |
        v
transport reads one JSON message
        |
        v
protocol.handle: era? _meta ok? known tool?
        |
        v
worker queue (at most MAX_QUEUE waiting)
        |
        v
worker thread runs the tool from registry
        |
        v
protocol decorates the result for its era
        |
        v
transport writes the reply
```

## Where the facts are pinned

- `tests/golden/protocol.json`: the replies to a fixed list of messages in both eras.
- `tests/golden/metrics.json`: the summary numbers from fixed inputs.
- `tests/conformance/`: the official MCP SDK as an outside client (stdio both eras, HTTP modern era).

Key points:
- Imports only go down the layer table; the test says which one went up.
- The worker is the only place tool calls run; transports never run tools themselves.
- A change in replies or numbers shows up as a diff in `tests/golden/`.
