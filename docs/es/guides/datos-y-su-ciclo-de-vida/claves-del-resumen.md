# El resumen, clave por clave

**Lector:** personas que añaden, leen o cambian una clave del JSON de resumen. Revisado el 2026-11-16.

English: [The summary, key by key](../../../guides/data-and-lifecycle/json-keys.md)

> **En corto:** el resumen es el archivo pequeño con los números de una grabación. Tres piezas de código distintas le
> añaden claves una tras otra, y no todas las claves están siempre: algunas dependen de lo que capturó la grabación.
> Una herramienta que lo lea debe tratar las claves condicionales como opcionales. Esta página lista cada clave, cuándo
> aparece y quién la lee.

Volver al [índice](./index.md). Ejemplo: un resumen real de esta máquina tiene `label`, `trace`, `process`, `device`,
`gpu`, `encoders` y algunas más, pero no `machine` ni `context`; véase
[E3](./evidencia-corridas.md#e3-claves-de-resumenes-reales).

Las claves las escriben tres piezas de código en secuencia:

1. `perf_report.summarize` lo construye a partir del `.trace` (`perf_report.py:648-835`) y escribe el primer `.json`.
2. `recording.finish` añade `layer`, `context`, `tier` y `retention`, reconstruye `common` y reescribe el archivo
   (`recording.py:337-351`).
3. En Windows, `perf_record_windows.py` construye un objeto distinto y más pequeño (`perf_record_windows.py:887-917`) y
   luego `finish` hace el paso 2 sobre él.

## Las generaciones

`schema_version` dice qué generación es un resumen (`metrics.py:10`, lo lee `metrics.schema_of`, `metrics.py:13`). Un
resumen sin ella es de la generación 1, y todas las herramientas siguen leyendo las generaciones 1, 2 y 3 (`CHANGELOG.md`,
0.27.0, Changed: un resumen sin ella es la versión 1 y toda herramienta lo sigue leyendo).

| Generación | Qué añadió | Publicada en |
|---|---|---|
| 1 | Las claves originales | antes de la 0.27.0 |
| 2 | Tablas comprimidas, `tier`, `retention` (`metrics.py:9`) | 0.27.0 (`CHANGELOG.md`) |
| 3 | El bloque `common` (`metrics.py:9`) | `[Unreleased]` en `CHANGELOG.md`; el código ya la escribe |

**Todos los resúmenes reales de la máquina donde se comprobó esta página son de la generación 1** (E3: sin
`schema_version`, sin `common`, sin `tier`, sin `retention`), porque se grabaron antes de la 0.27.0. Por eso las listas
de claves de abajo salen del código, no de un archivo real de generación 3. Un resumen de generación 3 **no se
reprodujo** (hace falta una grabación en macOS con Instruments). Aun así, con los archivos de generación 1 se
compararon las tablas de abajo: cada clave de un archivo real está en ellas (E3, límite conocido 11).

## Claves de un resumen de macOS: siempre presentes

| Clave | Qué contiene | Escrita en | La lee |
|---|---|---|---|
| `schema_version` | La generación (primera clave) | `perf_report.py:648` | `analysis.py:74` por medio de `metrics.schema_of` |
| `label` | La etiqueta de la grabación | `perf_report.py:649` | `analysis.py:643` |
| `trace` | El nombre del `.trace`, que se conserva aunque el archivo se borre | `perf_report.py:650` | nada en `src/` lee la clave (`rg`); `perf_runs` comprueba el archivo (`analysis.py:79`) |
| `process` | `name`, `pid`, `termination-reason`, `arguments` (hechos compartibles por `public_arguments`) | `perf_report.py:651-652` | `analysis.py:74` (`arguments`), `recording.py:432` (`termination-reason`) |
| `device` | `platform`, `model`, `memory-size`, `os-version`; el nombre de la máquina y su UUID se dejan fuera a propósito | `perf_report.py:654` | `analysis.py:138`, `metrics.py:55` |
| `template` | El nombre de la plantilla de Instruments | `perf_report.py:659` | `analysis.py:759` |
| `duration_s` | Segundos grabados | `perf_report.py:660` | `analysis.py:673` |
| `machine` | Chip, núcleos, RAM, macOS, `screen_locked` | `perf_report.py:661` | `analysis.py:195` (pantalla bloqueada) |
| `missing_tables` | Tablas de Instruments que el trazo no tenía | `perf_report.py:664` | ningún lector en `src/` (`rg`); es para quien lee el resumen |
| `gpu` | `intervals`, `frames`, `frame_gpu_ms`, `per_channel_ms`, `frame_interval_ms`, `start_latency_ms`, `fps_estimate` y las claves de ritmo de abajo | `perf_report.py:709` | `perf_runs`, comparar, diagnosticar, puertas (`analysis.py` en general) |
| `encoders` | Encoders y búferes de comandos por fotograma, los encoders más cortos, las 20 etiquetas principales | `perf_report.py:728` | `analysis.py:223`, `:702` |
| `gpu_idle` | Cuándo esperó la GPU | `perf_report.py:729` | `analysis.py:231`, `:715` |
| `gpu_performance_state_share` | Porcentaje de tiempo por estado de reloj de la GPU; `{}` si no hay | `perf_report.py:771` | `analysis.py:144` |
| `hitches` | `count`, `per_minute`, `threshold_ms`, `causes`, los 20 `worst` | `perf_report.py:822` | `analysis.py:574`, `:773` |
| `common` | `frame_pacing`, `memory_pressure`, `boundness`, `submission_overhead`, `api`, construido por `metrics.common_block` | `perf_report.py:835`, reconstruido en `recording.py:343` | `analysis.py:153` |
| `layer` | La capa de traducción: Wine con sus anulaciones y hashes de DLL, o `none` (nativo), `unknown` (adjuntado), MoltenVK, Rosetta | `recording.py:341` | `recording.py:208`, `metrics.layer_label` |
| `context` | `git` (commit corto y `dirty`, o nulo) e `instruments` (la versión, o nulo) | `recording.py:341`, `run_context` en `recording.py:168` | `recording.py:195` |

Un resumen escrito por `perf_report.py` lanzado a mano no tiene `layer` ni `context`: esas dos las pone
`recording.finish` (confirmado: las asignaciones solo están en `recording.py:341`).

Las claves de ritmo dentro de `gpu` salen de `frame_pacing` (`perf_report.py:253`) y están presentes solo cuando hay
intervalos entre fotogramas: `fps_1pct_low` y `fps_01pct_low` (nulo salvo que haya 100 y 1000 fotogramas),
`stutter_rate_pct` y `frame_jitter_ms` (más de un intervalo), `throttling_analysis` (cinco intervalos o más).

## Claves de un resumen de macOS: presentes solo bajo una condición

| Clave | Condición (leída del `if` que rodea la asignación) | Escrita en |
|---|---|---|
| `tier` | `recording.finish` recibió un nivel: `perf_record` pasa uno, `perf_attach` no | `recording.py:344-345` |
| `retention` | `METAL_TRACE_MAX_DISK_MB` está fijado, no corre otra grabación y se borró al menos un archivo: `{freed_mb, removed, trace_dropped}` | `recording.py:346-349` |
| `gpu.unpresented` | El programa dejó de presentar; el trabajo posterior queda fuera de los fotogramas | `perf_report.py:721` |
| `metal_memory_mib` | Se leyó la tabla de memoria de Metal (`memory` verdadero: no el nivel `light`, no `PERF_MEMORY=0`); `{"samples": 0}` si no tenía muestras | `perf_report.py:740` |
| `process_rss_mib` | Existe `<run>.rss.csv` junto al trazo | `perf_report.py:753` |
| `gpu_activity` | `<run>.agx.csv` dio filas | `perf_report.py:756` |
| `noisy_environment` | `noisy_environment()` devolvió algo; `true` o `false` | `perf_report.py:759` |
| `noisy_basis` | `noisy_environment` es `true`; lleva `other_processes` | `perf_report.py:761-762` |
| `graphics_compiler` | Existe la tabla `graphics-compiler-activity-intervals` | `perf_report.py:780` |
| `thermal_state_share` | Existe la tabla `device-thermal-state-intervals` | `perf_report.py:790` |
| `cpu` | `ProcessCPUUsage` tuvo filas del programa | `perf_report.py:798` |
| `resource_allocations` | Existe la tabla de asignaciones y tiene eventos | `perf_report.py:802` |
| `shader_spills` | Existe la tabla `graphics-compiler-spill-events` | `perf_report.py:804` |
| `command_buffer_errors` | Existe la tabla `metal-command-buffer-error` (un conteo) | `perf_report.py:806` |
| `validation` | Existe `<run>.validation.log` (la validación de Metal estaba activada) | `perf_report.py:811` |
| `gpu_counters` | Existen las dos tablas de contadores y dieron muestras (`counters=true`, el nivel `deep`) | `perf_report.py:817` |

## Un resumen de Windows

`perf_record_windows.py:887-917` escribe un objeto más pequeño:

| Parte | Contenido |
|---|---|
| Claves que escribe el motor | `schema_version`, `label`, `trace` (el nombre `<run>.trace`, un archivo que nunca existe en Windows), `process`, `device`, `template` (`Windows Native Trace`), `duration_s`, `missing_tables` (tres nombres fijos), `gpu`, `encoders`, `gpu_idle`, `metal_memory_mib` (`{"samples": 0}`), `process_rss_mib`, `layer`, `common` |
| `gpu` | Lleva `source` (uno de `drawstress-log`, `presentmon` o `dwm-composition`), las claves de ritmo y `throttling_analysis` |
| Las añade `finish` | `context`, y `tier` y `retention` bajo las mismas condiciones |
| Ausentes | `machine`, `hitches`, `gpu_performance_state_share` y toda clave condicional de Metal: una herramienta debe tratar cada una como opcional (confirmado: no están en el diccionario de esas líneas) |

`finish` también sustituye `layer` por la que calculó `record_run` (`recording.py:341`, `:370`, `:385`), que para una
corrida nativa en Windows dice `native Metal, no translation layer` (`recording.py:134-135`) donde el motor había escrito
`native Windows` (`perf_record_windows.py`, mismo diccionario); `layer_label` llama `native` a las dos, así que ningún
lector lo nota (confirmado por el código, no reproducido).
