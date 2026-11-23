# The GPU family facts

**Reader:** people who ask what a GPU can do, or who change `gpu_family` or its data file. Reviewed 2026-11-16.

> **In short:** a small reference book, not a reader of recordings. Give it a chip name such as `M1 Pro` and it returns the
> facts Apple publishes about that GPU family, with their source links: "what can this GPU do?" while reading a trace.

`gpu_family(name)` and the resources `metal-trace://gpu-families` and `metal-trace://gpu-families/<family>` read no recording. **Not run.**

| Aspect | Behaviour | Line |
|---|---|---|
| Accepted names | a family key (`Apple7`) or a chip name (`M1 Pro`, `A15`), lowercased with spaces removed; for a chip with the suffix `ultra`, `max` or `pro` it also tries the name without it | `traces.py::query_tables_file` (`family_of`), `:182` |
| Data | `src/metal_gpu_trace/data/apple-gpu-families.json`, read once at import; four families: `Apple7`, `Apple8`, `Apple9`, `Apple10` (E7) | `config.py:35` |
| Unknown name | `unknown family or chip '<name>'; try one of Apple7, ... or a chip such as M1 Pro, M2, M3 Max, A17 Pro` | `traces.py:192-194` |
| Sources | the facts carry their source URLs | `:195-196` |

This project restates Apple's pages and does not quote them (README "Credits"). Back to the [index](./index.md).
