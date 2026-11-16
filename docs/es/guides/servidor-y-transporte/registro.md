# El registro de herramientas

**Lector:** personas que añaden, renombran o describen una herramienta. Revisado el 2026-11-16.

English: [Registry](../../../guides/server-and-transport/registry.md) · [Índice](./index.md)

**En corto:** el registro es la carta de lo que un agente puede pedir: 26 herramientas, unos archivos de datos de solo
lectura y tres prompts ya hechos. Son datos puros, una fila por herramienta, y la misma fila alimenta la lista que ve el
agente, la comprobación de sus argumentos y la función que corre. Las pruebas aseguran que la carta y el README nunca discrepen.

`registry.py` son datos: importa los módulos de dominio (`analysis`, `experiments`, `recording`, `traces`, `workloads`,
`project`) y pone sus funciones en tres tablas. No ejecuta nada.

## Herramientas

`TOOLS` (`registry.py:69-188`): un nombre corresponde a una tupla `(función, esquema, pistas)`.

| Parte | Qué es |
|---|---|
| `función` | La función de dominio, como `recording.tool_perf_record`. Recibe argumentos con nombre y devuelve un diccionario |
| `esquema` | Un objeto JSON Schema construido por `schema(properties, required)` (`:24-26`). El cliente lo ve como `inputSchema`; `worker.check_arguments` comprueba una llamada contra él |
| `pistas` | Vienen de `hints(title, destructive, idempotent, open_world)` (`:29-34`) y se vuelven las anotaciones MCP de la herramienta. Por defecto es de solo lectura; pasar `destructive=True` o `False` dice que la herramienta escribe y si sus escrituras detienen programas |

Hoy 16 de las 26 herramientas son de solo lectura y 10 escriben ([E4](./evidencia.md#e4-cuantas-herramientas-cuantas-escriben-cuales-preguntan-a-la-persona)); las cinco que graban (`perf_record`, `perf_baseline_record`,
`perf_sweep`, `perf_ab`, `perf_cold_warm`) llevan `destructiveHint: true`, porque detienen programas.

Lo que `tools/list` construye con una fila (`protocol.py:146-150`):

| Campo | Regla |
|---|---|
| Descripción | El docstring de la función (`inspect.cleandoc`, que quita la sangría) |
| Sin propiedades | La herramienta recibe `additionalProperties: false` |
| Salida paginada | Tres herramientas (`perf_runs`, `trace_query`, `capture_records`, `PAGED_TOOLS` `:9`) reciben el esquema de salida paginado (`PAGED` `:6-8`) |
| `META` | Añade `anthropic/requiresUserInteraction` a las dos herramientas que descargan e instalan cosas (`workload_fetch`, `presentmon_install`, `registry.py:190-191`), de modo que un cliente que lo respete pregunta a la persona antes de cada llamada (E4) |

## Recursos y prompts

- **Recursos** (`RESOURCES`, `registry.py:12-15`): uno para todas las familias de GPU y uno por familia de
  `data/apple-gpu-families.json`, JSON de solo lectura: cinco en el `resources/list` grabado ([E9](./evidencia.md#e9-lo-que-responde-el-servidor-segun-lo-grabaron-las-pruebas)). Las grabaciones también son
  un recurso, pero no de esta tabla: `metal-trace://runs/<run>` es una plantilla (`resources/templates/list`) que
  `protocol.handle` sirve leyendo el resumen (`protocol.py:118-145`).
- **Prompts** (`PROMPTS`, `registry.py:193-216`): `compare-layer`, `diagnose-stutter` y `bisect-regression`. Cada uno tiene
  una función `render` que construye texto para el agente; el servidor no ejecuta nada, y `prompts/list` deja fuera `render`
  (`protocol.py:152-153`). `prompts/get` descarta todo argumento cuyo valor esté vacío o no pase `paths.name_ok` antes de
  llamar a `render` (`:159`).

## Qué fija el registro

- `test_tool_schemas_match_signatures` (`tests/test_server.py:1137`): cada argumento que toma una función está en su
  esquema, cada argumento sin valor por defecto es obligatorio, y un nombre del esquema que la función no toma solo se
  permite cuando la función reenvía `**kwargs`. Importa porque `tools/call` rechaza los nombres que el esquema no tiene.
- `test_readme_lists_every_tool` (`tests/test_server.py:18`): los dos README tienen una fila de tabla por cada herramienta.
- El número 26 aparece en cuatro sitios (`tests/test_server.py:14`, `:139`, `:325`, `:666`), y `tests/golden/protocol.json`
  guarda la respuesta completa de `tools/list`. Añadir una herramienta cambia todo eso a propósito ([Tocarlo sin romperlo](./tocarlo.md)).
