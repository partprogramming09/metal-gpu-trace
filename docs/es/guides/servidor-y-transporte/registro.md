# El registro de herramientas

**Lector:** personas que añaden, renombran o describen una herramienta. Revisado el 2026-11-16.

English: [Registry](../../../guides/server-and-transport/registry.md) · [Índice](./index.md)

**En corto:** el registro es la carta de lo que un agente puede pedir: 26 herramientas, unos archivos de datos de solo lectura y tres prompts ya hechos. Son datos puros, una fila por herramienta; la misma fila alimenta la lista que ve el agente, la comprobación de sus argumentos y la función que corre. Las pruebas mantienen de acuerdo la carta y el README.

`registry.py` importa los módulos de dominio (`analysis`, `experiments`, `recording`, `traces`, `workloads`, `project`) y pone sus funciones en tres tablas. No ejecuta nada.

## Herramientas

`TOOLS` (`registry.py:69-188`): un nombre corresponde a `(función, esquema, pistas)`.

| Parte | Qué es |
|---|---|
| `función` | La función de dominio, como `recording.tool_perf_record`: argumentos con nombre, devuelve un diccionario |
| `esquema` | JSON Schema de `schema(properties, required)` (`:24-26`); el cliente lo ve como `inputSchema`, `worker.check_arguments` comprueba una llamada contra él |
| `pistas` | De `hints(title, destructive, idempotent, open_world)` (`:29-34`), se vuelven anotaciones MCP. Por defecto solo lectura; `destructive=True` o `False` dice que la herramienta escribe y si sus escrituras detienen programas |

16 de las 26 herramientas son de solo lectura y 10 escriben ([E4](./evidencia.md#e4-cuantas-herramientas-cuantas-escriben-cuales-preguntan-a-la-persona)); las cinco que graban (`perf_record`, `perf_baseline_record`, `perf_sweep`, `perf_ab`, `perf_cold_warm`) llevan `destructiveHint: true`, porque detienen programas.

Lo que `tools/list` construye con una fila (`protocol.py:146-150`):

| Campo | Regla |
|---|---|
| Descripción | El docstring de la función (`inspect.cleandoc`) |
| Sin propiedades | `additionalProperties: false` |
| Salida paginada | `perf_runs`, `trace_query`, `capture_records` (`PAGED_TOOLS` `:9`) reciben el esquema paginado (`PAGED` `:6-8`) |
| `META` | Añade `anthropic/requiresUserInteraction` a las dos herramientas que descargan e instalan (`workload_fetch`, `presentmon_install`, `registry.py:190-191`), de modo que un cliente que lo respete pregunta a la persona cada vez (E4) |

## Recursos y prompts

- **Recursos** (`RESOURCES`, `registry.py:12-15`): uno para todas las familias de GPU y uno por familia de `data/apple-gpu-families.json`, JSON de solo lectura; cinco en el `resources/list` grabado ([E9](./evidencia.md#e9-lo-que-responde-el-servidor-segun-lo-grabaron-las-pruebas)). Las grabaciones se sirven distinto: `metal-trace://runs/<run>` es una plantilla (`resources/templates/list`) que `protocol.handle` sirve leyendo el resumen (`protocol.py:118-145`).
- **Prompts** (`PROMPTS`, `registry.py:193-216`): `compare-layer`, `diagnose-stutter`, `bisect-regression`. Cada `render` construye texto para el agente; el servidor no ejecuta nada, y `prompts/list` deja fuera `render` (`protocol.py:152-153`). `prompts/get` descarta todo argumento vacío o que no pase `paths.name_ok` antes de `render` (`:159`).

## Qué fija el registro

- `test_tool_schemas_match_signatures` (`tests/test_server.py:1137`): cada argumento que toma una función está en su esquema, cada uno sin valor por defecto es obligatorio, y un nombre extra del esquema solo se permite si la función reenvía `**kwargs` (`tools/call` rechaza los nombres que el esquema no tiene).
- `test_readme_lists_every_tool` (`tests/test_server.py:18`): los dos README tienen una fila por herramienta.
- El número 26 está en cuatro sitios (`tests/test_server.py:14`, `:139`, `:325`, `:666`) y `tests/golden/protocol.json` guarda el `tools/list` completo: añadir una herramienta cambia todo a propósito ([Tocarlo sin romperlo](./tocarlo.md)).
