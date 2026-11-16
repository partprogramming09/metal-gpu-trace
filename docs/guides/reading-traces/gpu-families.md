# The GPU family facts

**Reader:** people who ask what a GPU can do, or who change `gpu_family` or its data file. Reviewed 2026-11-16.

Español: [Los datos de las familias de GPU](../../es/guides/leer-trazas/familias-gpu.md)

> **In short:** this is a small reference book, not a reader of recordings. You give a chip name such as `M1 Pro` and it
> returns the facts Apple publishes about that family of GPU, with the links they come from. It is here because those facts
> help when reading a trace: "what can this GPU do?".

`gpu_family(name)` and the resources `metal-trace://gpu-families` and `metal-trace://gpu-families/<family>` return Apple's
published facts for a GPU family or a chip. They read no recording. **Not run.**

| Aspect | Behaviour | Line |
|---|---|---|
| Accepted names | a family key (`Apple7`) or a chip name (`M1 Pro`, `A15`), after lowering the case and removing spaces; for a chip with the suffix `ultra`, `max` or `pro` it also tries the name without it | `traces.py:177-185` (`family_of`), `:182` |
| Data | `src/metal_gpu_trace/data/apple-gpu-families.json`, read once at import; four families: `Apple7`, `Apple8`, `Apple9`, `Apple10` (E7) | `config.py:35` |
| Unknown name | `unknown family or chip '<name>'; try one of Apple7, ... or a chip such as M1 Pro, M2, M3 Max, A17 Pro` | `traces.py:192-194` |
| Sources | the facts carry their source URLs | `:195-196` |

This project restates Apple's pages and does not quote them (README "Credits").

Back to the [index](./index.md).
