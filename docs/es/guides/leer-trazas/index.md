# Leer trazas

**Lector:** personas que preguntan al servidor qué hay dentro de una grabación (un `.trace`, un `.gputrace` o los fotogramas de una corrida), o que cambian `traces.py` o `gputrace_read.py`. Revisado el 2026-11-16.

English: [Reading traces](../../../guides/reading-traces/index.md)

> **En corto:** una grabación es el archivo en bruto que deja una medición; un resumen son los pocos números sacados de ella.
> Estas siete herramientas abren el archivo en bruto, para preguntar «¿qué hay dentro?» sin abrir Instruments ni Xcode. Tres
> leen un `.trace` de Instruments, una convierte los fotogramas de una corrida en una línea de tiempo que Perfetto muestra, y
> tres leen una captura Metal `.gputrace`. Esta página da un ejemplo de cada una y dice cuál usar; las demás páginas
> profundizan, un tema por página.

Las herramientas: `trace_tables`, `trace_count`, `trace_query` (abren un `.trace` con `xctrace`), `perf_export_trace` (la tabla
por fotograma de una corrida, a un archivo que abre Perfetto) y `capture_summary`, `capture_diff`, `capture_records` (leen un
`.gputrace` sin Xcode). No se repite aquí: [Resumir y analizar](../resumir-y-analizar/index.md) (cómo `perf_report.py` lee ese mismo
`.trace` para el resumen `<run>.json`), [Datos y su ciclo de vida](../datos-y-su-ciclo-de-vida/index.md) (qué archivo se borra y
cuándo) y [Grabar](../grabar/index.md) (cómo se hace el `.trace`). Es la versión en español de la guía en inglés; si difieren, manda
el código.

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

Las líneas se mueven cuando cambia el código: busca el nombre, no solo el número. Cada número lleva su comando en
[Evidencia](./evidencia.md). Los tres límites del método (ninguna traza ni captura real en el repositorio, ningún Python
ejecutado, ningún `.gputrace` real examinado) están completos al principio de esa página: **ninguna herramienta de esta guía
se ejecutó**.

## Un ejemplo primero

Tres preguntas que una persona le hace a un agente. La primera se evalúa sobre una corrida real de este clon; las otras dos se
leen del código y de sus pruebas.

**1. «Muéstrame esta corrida en Perfetto.»** La corrida `a2-proof-first_20261115-085621` tiene una tabla por fotograma de 2045
fotogramas (E4). `perf_export_trace` con ese nombre lee esa tabla, no el `.trace`, escribe
`a2-proof-first_20261115-085621.chrome-trace` en la carpeta de corridas y responde
`{"file": "a2-proof-first_20261115-085621.chrome-trace", "frames": 2045}`. La primera fila de la tabla es
`6,1267.79,0.0243,1.7417,11.7952,13.5612`, y el código la convierte en una rebanada (E5):

```text
{"name":"GPU frame","ph":"X","pid":1,"tid":1,"ts":1267790,"dur":13561.2,"args":{"frame":6,"compute":0.0243,"fragment":1.7417,"vertex":11.7952}}
```

`ts` y `dur` están en microsegundos (lo que cuenta el formato de traza de Chrome): 1267.79 ms pasa a 1 267 790 y 13.5612 ms a
13 561.2. La rebanada empieza 1.27 s después del inicio de la grabación y dura lo que la GPU tardó en ese fotograma. La
herramienta **no se ejecutó**: E5 es la aritmética de `traces.py:22-25` hecha con `awk` sobre la fila real; la prueba que ancla
la misma aritmética en una tabla de dos filas es `tests/test_analysis.py:329-332`.

**2. «¿Qué partes de esta tabla están ocupadas?»** `trace_query` con `window_ms=10` sobre `metal-gpu-intervals` devuelve una
entrada por ventana de 10 ms en lugar de una por fila. Tres filas que empiezan en 1 ms (2 ms de duración), 9 ms (1 ms) y 12 ms
(4 ms) dan dos ventanas: `{"start_ms": 0, "count": 2, "duration_ms": 3.0}` y `{"start_ms": 10, "count": 1, "duration_ms": 4.0}`.
Es el ejemplo de `tests/test_traces.py:42-48` (no corrido); E6 lo evalúa a mano.

**3. «¿Qué añadió mi cambio a las llamadas de dibujo?»** `capture_diff` sobre dos capturas `.gputrace` cuenta las llamadas Metal
confirmadas en cada una y dice qué cambió. La prueba publicada de la 0.26.0 muestra `drawPrimitives` 3 contra 5 (delta 2) y el
grupo de depuración `main` pasando de 2 dibujos a 4, mientras `shadow` no aparece porque no cambió
([prueba de la 0.26.0](../../../evidence/v0.26.0.md#capture_diff-compares-two-captures)). Ese par es **sintético** (un flujo de
bytes que construye una prueba), no una captura hecha por Xcode: la evidencia publicada del proyecto no ha leído ninguna
captura real.

| Un lector pregunta | Respuesta corta | Página |
|---|---|---|
| ¿Por qué `KEEP_TRACE=1` para `trace_query` y no para `perf_export_trace`? | la primera lee el `.trace` (se borra por defecto al escribir el resumen); la segunda lee la tabla por fotograma, que se queda | [más abajo](#las-tres-formas-de-leer-y-donde-viven) |
| ¿Por qué recorrer una tabla grande por páginas es lento? | cada página vuelve a correr `xctrace export` | [trace_query](./trace-query.md) |
| ¿Puede la herramienta decir cuánto tardó una llamada de dibujo en un `.gputrace`? | no: nombres, cuentas y etiquetas, ningún tiempo | [las herramientas de captura](./herramientas-captura.md) |

## Las tres formas de leer, y dónde viven

![Tres filas de tres cajas, cada fila un flujo de izquierda a derecha. Fila uno, un .trace leído por trace_tables, trace_count y trace_query: encontrar la traza, exportar una tabla con xctrace, filtrar y devolver filas o ventanas de tiempo. Fila dos, un .gputrace leído por capture_summary, capture_diff y capture_records: resolver el paquete dentro de las carpetas legibles, partir su archivo capture en registros, contar, comparar o listarlos. Fila tres, perf_export_trace: encontrar la tabla por fotograma de una corrida, hacer una rebanada por fotograma, escribir el archivo de traza de Chrome. El texto en rojo marca dónde se detiene cada paso.](./img/tres-formas.png)
*Figura 1. Las tres formas de leer una grabación. Fuente HTML: `docs/es/guides/leer-trazas/img/tres-formas.html`.*

| Tienes | Pregunta con | Necesita `xctrace` | Necesita el `.trace` guardado |
|---|---|---|---|
| Un nombre de corrida, quieres la lista de tablas | `trace_tables` | sí | sí |
| Un nombre de corrida, quieres saber qué tablas tienen filas | `trace_count` | sí | sí |
| Un nombre de corrida, quieres las filas (o ventanas de tiempo) de una tabla | `trace_query` | sí | sí |
| Un nombre de corrida, quieres sus fotogramas en Perfetto | `perf_export_trace` | no | no (necesita la tabla por fotograma) |
| Un `.gputrace` guardado desde Xcode | `capture_summary`, `capture_diff`, `capture_records` | no | no es un `.trace` en absoluto |

`perf_runs` tiene un indicador `trace_kept` por corrida (`analysis.py:79`): es verdadero cuando existe la carpeta `<run>.trace`
y no es un enlace. Es la forma más rápida de saber si las tres primeras filas pueden funcionar para una corrida
(**confirmada**; cuándo se guarda una traza: `KEEP_TRACE=1` o el nivel `deep`, ver la [guía de datos](../datos-y-su-ciclo-de-vida/index.md)).

| Pieza | Archivo | Qué hace |
|---|---|---|
| Las siete herramientas | `traces.py` | `tool_perf_export_trace` `:9`, `tool_trace_tables` `:33`, `tool_trace_query` `:92`, `tool_trace_count` `:124`, `tool_capture_summary` `:151`, `tool_capture_diff` `:160`, `tool_capture_records` `:169` |
| Entradas del registro | `registry.py` | nombre, esquema y pistas (`:129`, `:159`, `:160`, `:165`, `:172`, `:173`, `:177`) |
| Agrupar por ventanas | `traces.py` | `check_window` `:42`, `windows_of` `:54` |
| La capa de `xctrace` | `perf_report.py` | `export` `:49`, `toc_of` `:81`, `table_xpath` `:90`, `rows` `:143`, `pid_of` `:182` (el mismo código del resumen) |
| El lector de `.gputrace` | `gputrace_read.py` | `CALLS` `:20`, `records` `:48`, `stream_of` `:64`, `summarize` `:72`, `counts` `:100`, `diff` `:124`; también un script (`main` `:144`) |
| Rutas y paginación | `paths.py` | `allowed` `:17`, `trace_path` `:83`, `page` `:94` |
| Tablas por fotograma | `tables.py` | `find` y `open_text`: tanto `.csv.gz` como el `.csv` antiguo ([guía de datos](../datos-y-su-ciclo-de-vida/index.md)) |
| Qué pasa con un error | `worker.py` | `call` convierte un fallo en un resultado `isError` (`:165-168`) |

`gpu_family` también vive en `traces.py` pero no lee ninguna grabación: [los datos de las familias de GPU](./familias-gpu.md).

## Véase también

- [Resumir y analizar](../resumir-y-analizar/index.md): cómo `perf_report.py` lee ese mismo `.trace`, y la regla `unpresented` que también da forma a la tabla por fotograma.
- [Datos y su ciclo de vida](../datos-y-su-ciclo-de-vida/index.md): cuándo existen un `.trace` y un `.chrome-trace` y qué los borra.
- [Grabar](../grabar/index.md): cómo se hace el `.trace` y por qué se borra.
- [Cómo funciona](../../../guides/how-it-works.md): qué capa llama a cuál.
- [Prueba de la 0.26.0](../../../evidence/v0.26.0.md#capture_diff-compares-two-captures): el ejemplo publicado de `capture_diff`, sobre flujos sintéticos.
