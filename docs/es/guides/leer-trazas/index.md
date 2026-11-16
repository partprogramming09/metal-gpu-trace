# Leer trazas

**Lector:** personas que preguntan al servidor qué hay dentro de una grabación (un `.trace`, un `.gputrace` o los fotogramas de una corrida), o que cambian `traces.py` o `gputrace_read.py`. Revisado el 2026-11-16.

English: [Reading traces](../../../guides/reading-traces/index.md)

> **En corto:** una grabación es el archivo en bruto que deja una medición; un resumen son los pocos números sacados de ella.
> Estas siete herramientas abren el archivo en bruto, para preguntar «¿qué hay dentro?» sin Instruments ni Xcode: tres leen un
> `.trace` de Instruments, una convierte los fotogramas de una corrida en una línea de tiempo que muestra Perfetto, tres leen
> una captura Metal `.gputrace`. Abajo, un ejemplo de cada una.

## Las páginas de esta guía

| Página | Un tema |
|---|---|
| [Por qué tiene esta forma](./por-que-asi.md) | las decisiones de diseño y las alternativas descartadas |
| [El argumento `trace`](./argumento-trace.md) | cómo se entiende un nombre o una ruta; qué es un `.trace` desde aquí |
| [`trace_tables` y `trace_count`](./tablas-y-conteo.md) | qué tablas existen y cuáles tienen filas |
| [`trace_query`](./trace-query.md) | filas, páginas y ventanas de tiempo |
| [Exportar un `.chrome-trace`](./chrome-trace.md) | `perf_export_trace`, qué muestra y qué omite el archivo |
| [El formato `.gputrace`](./formato-gputrace.md) | lo que el código supone; los ids de llamada |
| [Las herramientas de captura](./herramientas-captura.md) | `capture_summary`, `capture_diff`, `capture_records`, lo que no pueden decir |
| [Los datos de las familias de GPU](./familias-gpu.md) | `gpu_family`, sin ninguna grabación |
| [Cuando falla](./cuando-falla.md) | cada error y su texto |
| [Límites conocidos y hallazgos](./limites.md) | límites 1-11 y hallazgos F1-F10, sin arreglar |
| [Tocarlo sin romperlo](./tocarlo.md) | reglas para cambiar el código |
| [Evidencia](./evidencia.md) | E1-E8, comandos y salida real; lo que no se reprodujo |

## Cómo leer las etiquetas

| Etiqueta | Significa |
|---|---|
| **confirmada** | con `archivo:línea`, comprobada con `rg` o `sed` el 2026-11-16 contra el árbol de trabajo (0.27.2 más las entradas `[Unreleased]` de `CHANGELOG.md`) |
| **probable** | leída en el código, no ejecutada aquí |
| **especulación** | una conjetura sobre el porqué |
| **no verificado** | un dato de fuera que no se comprobó contra su fuente |
| **no reproducido** | el comportamiento no se pudo ejecutar para esta guía |

Las líneas se mueven cuando cambia el código: busca el nombre. Cada número lleva su comando en [Evidencia](./evidencia.md), cuyo
inicio da los tres límites del método: **ninguna herramienta de esta guía se ejecutó** (ni traza ni captura real, ni Python, ni `.gputrace` real).
Es la versión en español de la guía en inglés; si difieren, manda el código.

## Un ejemplo primero

Tres preguntas que una persona le hace a un agente. La primera se evalúa sobre una corrida real de este clon; las otras dos salen del código y sus pruebas.

**1. «Muéstrame esta corrida en Perfetto.»** La corrida `a2-proof-first_20261115-085621` tiene una tabla por fotograma de 2045
fotogramas (E4). `perf_export_trace` lee esa tabla, no el `.trace`, escribe `a2-proof-first_20261115-085621.chrome-trace` en la
carpeta de corridas y responde `{"file": "a2-proof-first_20261115-085621.chrome-trace", "frames": 2045}`. La primera fila,
`6,1267.79,0.0243,1.7417,11.7952,13.5612`, pasa a ser una rebanada (E5):

```text
{"name":"GPU frame","ph":"X","pid":1,"tid":1,"ts":1267790,"dur":13561.2,"args":{"frame":6,"compute":0.0243,"fragment":1.7417,"vertex":11.7952}}
```

`ts` y `dur` están en microsegundos (la unidad del formato de traza de Chrome): 1267.79 ms pasa a 1 267 790 y 13.5612 ms a 13 561.2.
La rebanada empieza 1.27 s después del inicio y dura lo que la GPU tardó en ese fotograma. La herramienta **no se ejecutó**: E5 es
la aritmética de `traces.py:22-25` hecha con `awk`; la prueba que la ancla es `tests/test_analysis.py:329-332`.

**2. «¿Qué partes de esta tabla están ocupadas?»** `trace_query` con `window_ms=10` sobre `metal-gpu-intervals` devuelve una
entrada por ventana de 10 ms. Filas que empiezan en 1 ms (2 ms de duración), 9 ms (1 ms) y 12 ms (4 ms) dan
`{"start_ms": 0, "count": 2, "duration_ms": 3.0}` y `{"start_ms": 10, "count": 1, "duration_ms": 4.0}`
(`tests/test_traces.py:42-48`, no corrido; E6 a mano).

**3. «¿Qué añadió mi cambio a las llamadas de dibujo?»** `capture_diff` sobre dos capturas `.gputrace` cuenta las llamadas Metal
confirmadas en cada una. La [prueba de la 0.26.0](../../../evidence/v0.26.0.md#capture_diff-compares-two-captures) muestra
`drawPrimitives` 3 contra 5 (delta 2) y el grupo de depuración `main` pasando de 2 dibujos a 4; `shadow` no aparece porque no
cambió. Ese par es **sintético** (un flujo de bytes que construye una prueba): la evidencia publicada del proyecto no ha leído ninguna captura real.

## Las tres formas de leer, y donde viven

![Tres filas de tres cajas, cada fila un flujo de izquierda a derecha. Fila uno, un .trace leído por trace_tables, trace_count y trace_query: encontrar la traza, exportar una tabla con xctrace, filtrar y devolver filas o ventanas de tiempo. Fila dos, un .gputrace leído por capture_summary, capture_diff y capture_records: resolver el paquete dentro de las carpetas legibles, partir su archivo capture en registros, contar, comparar o listarlos. Fila tres, perf_export_trace: encontrar la tabla por fotograma de una corrida, hacer una rebanada por fotograma, escribir el archivo de traza de Chrome. El texto en rojo marca dónde se detiene cada paso.](./img/tres-formas.png)
*Figura 1. Las tres formas de leer una grabación. Fuente HTML: `docs/es/guides/leer-trazas/img/tres-formas.html`.*

| Tienes | Pregunta con | Necesita `xctrace` | Necesita el `.trace` guardado |
|---|---|---|---|
| Un nombre de corrida: la lista de tablas, cuáles tienen filas, o las filas (o ventanas) de una | `trace_tables`, `trace_count`, `trace_query` | sí | sí (así que `KEEP_TRACE=1`; cada página vuelve a exportar, por eso las tablas grandes son lentas: [trace_query](./trace-query.md)) |
| Un nombre de corrida: sus fotogramas en Perfetto | `perf_export_trace` | no | no (lee la tabla por fotograma, que se queda) |
| Un `.gputrace` guardado desde Xcode | `capture_summary`, `capture_diff`, `capture_records` | no | no es un `.trace`; nombres, cuentas y etiquetas, ningún tiempo ([herramientas de captura](./herramientas-captura.md)) |

`perf_runs` tiene un indicador `trace_kept` por corrida (`analysis.py:79`): es verdadero cuando existe la carpeta `<run>.trace` y
no es un enlace, así que dice si la primera fila puede funcionar (**confirmada**; una traza se guarda con `KEEP_TRACE=1` o el
nivel `deep`, ver la [guía de datos](../datos-y-su-ciclo-de-vida/index.md)).

| Pieza | Archivo | Qué hace |
|---|---|---|
| Las siete herramientas | `traces.py` | `tool_perf_export_trace` `:9`, `tool_trace_tables` `:33`, `tool_trace_query` `:92`, `tool_trace_count` `:124`, `tool_capture_summary` `:151`, `tool_capture_diff` `:160`, `tool_capture_records` `:169` |
| Entradas del registro | `registry.py` | nombre, esquema y pistas (`:129`, `:159`, `:160`, `:165`, `:172`, `:173`, `:177`); agrupar por ventanas vive en `traces.py`: `check_window` `:42`, `windows_of` `:54` |
| La capa de `xctrace` | `perf_report.py` | `export` `:49`, `toc_of` `:81`, `table_xpath` `:90`, `rows` `:143`, `pid_of` `:182` (el mismo código del resumen) |
| El lector de `.gputrace` | `gputrace_read.py` | `CALLS` `:20`, `records` `:48`, `stream_of` `:64`, `summarize` `:72`, `counts` `:100`, `diff` `:124`; también un script (`main` `:144`) |
| Rutas y paginación | `paths.py` | `allowed` `:17`, `trace_path` `:83`, `page` `:94` |
| Tablas por fotograma | `tables.py` | `find` y `open_text`: tanto `.csv.gz` como el `.csv` antiguo ([guía de datos](../datos-y-su-ciclo-de-vida/index.md)) |
| Qué pasa con un error | `worker.py` | `call` convierte un fallo en un resultado `isError` (`:165-168`) |

`gpu_family` también vive en `traces.py` pero no lee ninguna grabación: [los datos de las familias de GPU](./familias-gpu.md).

## Véase también

[Resumir y analizar](../resumir-y-analizar/index.md) (cómo `perf_report.py` lee ese mismo `.trace` para el resumen `<run>.json`; la regla `unpresented` que también da forma a la tabla por fotograma) · [Datos y su ciclo de vida](../datos-y-su-ciclo-de-vida/index.md) (cuándo existen un `.trace` y un `.chrome-trace`, qué los borra) · [Grabar](../grabar/index.md) (cómo se hace el `.trace`, por qué se borra) · [Cómo funciona](../../../guides/how-it-works.md) (qué capa llama a cuál) · [Prueba de la 0.26.0](../../../evidence/v0.26.0.md#capture_diff-compares-two-captures) (el ejemplo publicado de `capture_diff`, sobre flujos sintéticos).
