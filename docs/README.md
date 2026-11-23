# Documentation index

**Reader:** people

ADR status: proposed · accepted · rejected · superseded by NNNN.

## Where to start

| If you are... | Read |
|---|---|
| **A user** who installed it and wants to measure something | [guides/using-it.md](guides/using-it.md), then the [README](../README.md#words-used-here) glossary |
| **An AI agent** working with the server | The server's own instructions (what `initialize` returns, kept in `INSTRUCTIONS` in `metal_trace_mcp.py`), then [guides/using-it.md](guides/using-it.md) for what to answer a user, and [../CLAUDE.md](../CLAUDE.md) for the rules of this repository |
| **A new contributor** | [../CONTRIBUTING.md](../CONTRIBUTING.md), then [guides/how-it-works.md](guides/how-it-works.md) and [guides/run-from-a-clone.md](guides/run-from-a-clone.md) |
| **Checking a claim** about a release | [evidence/README.md](evidence/README.md) |

## For people
| Document | Answers |
|---|---|
| [guides/using-it.md](guides/using-it.md) | "I installed it, now what?": five typical jobs with the sentence to say to your agent and how to read the answer |
| [guides/how-it-works.md](guides/how-it-works.md) | How the modules are layered, how one request flows through them, where recordings live and what reads them |
| [adr/0001-src-layout.md](adr/0001-src-layout.md) | Why the code is a package in `src/` with tests in `tests/` (accepted) |
| [adr/0002-dual-era-mcp.md](adr/0002-dual-era-mcp.md) | Why the server speaks both MCP eras, and where it deviates (accepted) |
| [adr/0003-python-3-9-floor.md](adr/0003-python-3-9-floor.md) | Why Python 3.9 is the oldest supported version (accepted) |
| [adr/0004-project-file.md](adr/0004-project-file.md) | Why a metal-gpu-trace.json in each repository picks the recordings folder (accepted) |
| [adr/0005-remove-the-panel.md](adr/0005-remove-the-panel.md) | Why the HTML panel was removed in 0.25.0 and what stays for old files (accepted) |
| [adr/0006-compressed-tables-and-disk-quota.md](adr/0006-compressed-tables-and-disk-quota.md) | Why per-frame tables are gzip and the runs folder has a size limit (accepted) |
| [adr/0007-sqlite-tables-beside-the-compressed-tables.md](adr/0007-sqlite-tables-beside-the-compressed-tables.md) | Why each recording keeps its tables in a SQLite file beside the compressed ones (accepted, amends 0006) |
| [adr/0008-lift-the-standard-library-only-rule.md](adr/0008-lift-the-standard-library-only-rule.md) | Why a dependency is allowed when it saves work, and the Python 3.9 floor stays (accepted) |
| [adr/0009-keep-the-trace-uncompressed.md](adr/0009-keep-the-trace-uncompressed.md) | Why the `.trace` is not compressed, measured with the standard library's lzma (accepted) |
| [adr/0010-stability-policy-and-the-road-to-1-0.md](adr/0010-stability-policy-and-the-road-to-1-0.md) | What counts as the public surface and when 1.0 happens (proposed, not decided) |
| [evidence/README.md](evidence/README.md) | How each release proves its improvements, and the rule `tests/test_docs.py` checks |
| [evidence/reference-runs-windows.md](evidence/reference-runs-windows.md) | Reference runs on Windows: `drawstress` with and without the VegaFlow daemon, what the numbers show and what they do not |
| [evidence/internal-tools.md](evidence/internal-tools.md) | What VegaFlow and WinBridge are (the maintainer's own tools, not needed to use the project) |
| [guides/run-from-a-clone.md](guides/run-from-a-clone.md) | Commands to run the server, the scripts and the checks from a clone |
| [guides/data-and-lifecycle/](guides/data-and-lifecycle/index.md) | What a recording leaves on disk, the summary key by key, the two retention settings, the cache and the lock |
| [guides/recording/](guides/recording/index.md) | The path of one recording, why one at a time and 30 s under Wine, what preflight checks and says, the test programs and their pins, the Windows engine, what happens when it fails |
| [guides/summarizing/](guides/summarizing/index.md) | How a `.trace` becomes the summary, how each number is computed, what compare, check and gate decide, the experiments, noise, what happens when it fails |
| [guides/reading-traces/](guides/reading-traces/index.md) | The tools that read a `.trace` or a `.gputrace`, windows and paging, Chrome-trace export, what the code assumes about a capture, what happens when it fails |
| [guides/server-and-transport/](guides/server-and-transport/index.md) | Starting over stdio and HTTP, the registry, the worker, the HTTP checks, the logs, what happens when it fails |
| [../tests/golden/README.md](../tests/golden/README.md) | What the golden files pin and how to re-record them |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) · [../SECURITY.md](../SECURITY.md) | How to send a change · how to report a vulnerability |
