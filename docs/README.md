# Documentation index

**Reader:** people

ADR status: proposed · accepted · rejected · superseded by NNNN.

## For people
| Document | Answers |
|---|---|
| [guides/how-it-works.md](guides/how-it-works.md) | How the modules are layered, how one request flows through them, where recordings live and what reads them |
| [adr/0001-src-layout.md](adr/0001-src-layout.md) | Why the code is a package in `src/` with tests in `tests/` (accepted) |
| [adr/0002-dual-era-mcp.md](adr/0002-dual-era-mcp.md) | Why the server speaks both MCP eras, and where it deviates (accepted) |
| [adr/0003-python-3-9-floor.md](adr/0003-python-3-9-floor.md) | Why Python 3.9 is the oldest supported version (accepted) |
| [adr/0004-project-file.md](adr/0004-project-file.md) | Why a metal-gpu-trace.json in each repository picks the recordings folder (accepted) |
| [adr/0005-remove-the-panel.md](adr/0005-remove-the-panel.md) | Why the HTML panel was removed in 0.25.0 and what stays for old files (accepted) |
| [evidence/README.md](evidence/README.md) | How each release proves its improvements, and the rule `tests/test_docs.py` checks |
| [adr/0006-compressed-tables-and-disk-quota.md](adr/0006-compressed-tables-and-disk-quota.md) | Why per-frame tables are gzip and the runs folder has a size limit (accepted) |
| [guides/run-from-a-clone.md](guides/run-from-a-clone.md) | Commands to run the server, the scripts and the checks from a clone |
| [guides/data-and-lifecycle.md](guides/data-and-lifecycle.md) | What a recording leaves on disk, the summary key by key, the two retention settings, the cache and the lock |
| [es/guides/datos-y-su-ciclo-de-vida.md](es/guides/datos-y-su-ciclo-de-vida.md) | The same guide in Spanish |
| [guides/recording.md](guides/recording.md) | The path of one recording, why one at a time and 30 s under Wine, what preflight checks and says, the test programs and their pins, the Windows engine, what happens when it fails |
| [es/guides/grabar.md](es/guides/grabar.md) | The same guide in Spanish |
| [guides/summarizing.md](guides/summarizing.md) | How a `.trace` becomes the summary, how each number is computed, what compare, check and gate decide, the experiments, noise, what happens when it fails |
| [es/guides/resumir-y-analizar.md](es/guides/resumir-y-analizar.md) | The same guide in Spanish |
| [guides/reading-traces.md](guides/reading-traces.md) | The tools that read a `.trace` or a `.gputrace`, windows and paging, Chrome-trace export, what the code assumes about a capture, what happens when it fails |
| [es/guides/leer-trazas.md](es/guides/leer-trazas.md) | The same guide in Spanish |
| [guides/server-and-transport.md](guides/server-and-transport.md) | Starting over stdio and HTTP, the registry, the worker, the HTTP checks, the logs, what happens when it fails |
| [es/guides/servidor-y-transporte.md](es/guides/servidor-y-transporte.md) | The same guide in Spanish |
| [../tests/golden/README.md](../tests/golden/README.md) | What the golden files pin and how to re-record them |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) · [../SECURITY.md](../SECURITY.md) | How to send a change · how to report a vulnerability |
