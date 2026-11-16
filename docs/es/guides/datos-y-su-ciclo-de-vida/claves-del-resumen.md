# El resumen, clave por clave

**Lector:** personas que añaden, leen o cambian una clave del JSON de resumen. Revisado el 2026-11-16.

English: [The summary, key by key](../../../guides/data-and-lifecycle/json-keys.md)

> **En corto:** el resumen es el archivo pequeño con los números de una grabación. Tres piezas de código le añaden claves
> una tras otra, y algunas claves dependen de lo que capturó la grabación, así que quien lo lee debe tratar las condicionales como opcionales.

Volver al [índice](./index.md). Ejemplo: un resumen real de aquí tiene `label`, `trace`, `process`, `device`, `gpu`, `encoders` y alguna más, pero no `machine` ni `context` ([E3](./evidencia-corridas.md#e3-claves-de-resumenes-reales)).

Las claves se escriben en secuencia:

1. `perf_report.summarize` lo construye desde el `.trace` (`perf_report.py:648-835`) y escribe el primer `.json`.
2. `recording.finish` añade `layer`, `context`, `tier`, `retention`, reconstruye `common` y reescribe el archivo (`recording.py:337-351`).
3. En Windows, `perf_record_windows.py` construye un objeto más pequeño (`perf_record_windows.py:887-917`) y luego `finish` hace el paso 2 sobre él.

## Las generaciones

`schema_version` dice la generación (`metrics.py:10`, la lee `metrics.schema_of`, `metrics.py:13`). Sin ella, un resumen es de generación 1, y todas las herramientas siguen leyendo 1, 2 y 3 (`CHANGELOG.md`, 0.27.0, Changed).

| Generación | Qué añadió | Publicada en |
|---|---|---|
| 1 | Las claves originales | antes de la 0.27.0 |
| 2 | Tablas comprimidas, `tier`, `retention` (`metrics.py:9`) | 0.27.0 (`CHANGELOG.md`) |
| 3 | El bloque `common` (`metrics.py:9`) | `[Unreleased]` en `CHANGELOG.md`; el código ya lo escribe |

**Todos los resúmenes reales de aquí son de generación 1** (E3: sin `schema_version`, `common`, `tier` ni `retention`), grabados antes de la 0.27.0. Las listas de claves salen del código; un resumen de generación 3 **no se reprodujo** (necesita una grabación en macOS con Instruments). Toda clave de un archivo real está en estas tablas (E3, límite conocido 11).

## Claves de un resumen de macOS: siempre presentes

| Clave | Contiene | Escrita en; leída por |
|---|---|---|
| `schema_version` | La generación (primera clave) | `perf_report.py:648`; `analysis.py:74` vía `metrics.schema_of` |
| `label`, `template`, `duration_s` | Etiqueta de la grabación, nombre de la plantilla de Instruments, segundos grabados | `perf_report.py:649`, `:659`, `:660`; `analysis.py:643`, `:759`, `:673` |
| `trace` | Nombre del `.trace`, se conserva tras borrar el archivo | `perf_report.py:650`; nada en `src/` la lee (`rg`); `perf_runs` prueba el archivo (`analysis.py:79`) |
| `process` | `name`, `pid`, `termination-reason`, `arguments` (compartibles con `public_arguments`) | `perf_report.py:651-652`; `analysis.py:74` (`arguments`), `recording.py:432` (`termination-reason`) |
| `device` | `platform`, `model`, `memory-size`, `os-version`; el nombre de la máquina y su UUID se omiten a propósito | `perf_report.py:654`; `analysis.py:138`, `metrics.py:55` |
| `machine` | Chip, núcleos, RAM, macOS, `screen_locked` | `perf_report.py:661`; `analysis.py:195` (pantalla bloqueada) |
| `missing_tables` | Tablas de Instruments que el trazo no tenía | `perf_report.py:664`; ningún lector en `src/` (`rg`) |
| `gpu` | `intervals`, `frames`, `frame_gpu_ms`, `per_channel_ms`, `frame_interval_ms`, `start_latency_ms`, `fps_estimate`, claves de ritmo de abajo | `perf_report.py:709`; `perf_runs`, compare, diagnose, puertas (`analysis.py`) |
| `encoders` | Encoders y command buffers por fotograma, los encoders más cortos, las 20 etiquetas principales | `perf_report.py:728`; `analysis.py:223`, `:702` |
| `gpu_idle` | Cuándo esperó la GPU | `perf_report.py:729`; `analysis.py:231`, `:715` |
| `gpu_performance_state_share` | Proporción de tiempo por estado de reloj de la GPU; `{}` si no hay | `perf_report.py:771`; `analysis.py:144` |
| `hitches` | `count`, `per_minute`, `threshold_ms`, `causes`, los 20 `worst` | `perf_report.py:822`; `analysis.py:574`, `:773` |
| `common` | `frame_pacing`, `memory_pressure`, `boundness`, `submission_overhead`, `api`, de `metrics.common_block` | `perf_report.py:835`, reconstruida en `recording.py:343`; `analysis.py:153` |
| `layer` | Capa de traducción: Wine con sus overrides y hashes de DLL, `none` (nativo), `unknown` (adjunto), MoltenVK, Rosetta | `recording.py:341`; `recording.py:208`, `metrics.layer_label` |
| `context` | `git` (commit corto y `dirty`, o null) e `instruments` (la versión, o null) | `recording.py:341`, `run_context` en `:168`; `recording.py:195` |

Un resumen de un `perf_report.py` lanzado a mano no tiene `layer` ni `context`: vienen de `recording.finish` (confirmado: se asignan solo en `recording.py:341`).

Las claves de ritmo dentro de `gpu` vienen de `frame_pacing` (`perf_report.py:253`), solo si hay huecos entre fotogramas: `fps_1pct_low` y `fps_01pct_low` (null salvo con 100 y 1000 fotogramas), `stutter_rate_pct` y `frame_jitter_ms` (más de un hueco), `throttling_analysis` (cinco huecos o más).

## Claves de un resumen de macOS: presentes solo bajo una condición

| Clave | Condición (del `if` alrededor de la asignación) | Escrita en |
|---|---|---|
| `tier` | `recording.finish` recibió un nivel: `perf_record` lo pasa, `perf_attach` no | `recording.py:344-345` |
| `retention` | `METAL_TRACE_MAX_DISK_MB` fijado, sin otra grabación en curso y al menos un archivo borrado: `{freed_mb, removed, trace_dropped}` | `recording.py:346-349` |
| `gpu.unpresented` | El programa dejó de presentar; el trabajo posterior queda fuera de los fotogramas | `perf_report.py:721` |
| `metal_memory_mib` | Se leyó la tabla de memoria de Metal (`memory` verdadero: no nivel `light`, no `PERF_MEMORY=0`); `{"samples": 0}` si no hubo muestra | `perf_report.py:740` |
| `process_rss_mib` | Existe `<run>.rss.csv` junto al trazo | `perf_report.py:753` |
| `gpu_activity` | `<run>.agx.csv` dio filas | `perf_report.py:756` |
| `noisy_environment`, `noisy_basis` | `noisy_environment()` devolvió algo (`true` o `false`); la base (con `other_processes`) solo si es `true` | `perf_report.py:759`, `:761-762` |
| `graphics_compiler`, `thermal_state_share` | Existe la tabla `graphics-compiler-activity-intervals`, `device-thermal-state-intervals` | `perf_report.py:780`, `:790` |
| `cpu` | `ProcessCPUUsage` tenía filas del programa | `perf_report.py:798` |
| `resource_allocations` | Existe la tabla de asignaciones y tiene eventos | `perf_report.py:802` |
| `shader_spills`, `command_buffer_errors` | Existe la tabla `graphics-compiler-spill-events`, `metal-command-buffer-error` (un recuento) | `perf_report.py:804`, `:806` |
| `validation` | Existe `<run>.validation.log` (la validación de Metal estaba activa) | `perf_report.py:811` |
| `gpu_counters` | Las dos tablas de contadores existen y dieron muestras (`counters=true`, nivel `deep`) | `perf_report.py:817` |

## Un resumen de Windows

`perf_record_windows.py:887-917` escribe un objeto más pequeño:

| Parte | Contenido |
|---|---|
| Escritas por el motor | `schema_version`, `label`, `trace` (el nombre `<run>.trace`, un archivo que nunca existe en Windows), `process`, `device`, `template` (`Windows Native Trace`), `duration_s`, `missing_tables` (tres nombres fijos), `gpu`, `encoders`, `gpu_idle`, `metal_memory_mib` (`{"samples": 0}`), `process_rss_mib`, `layer`, `common` |
| `gpu` | Tiene `source` (`drawstress-log`, `presentmon` o `dwm-composition`), las claves de ritmo y `throttling_analysis` |
| Añadidas por `finish` | `context`, y `tier`, `retention` bajo las mismas condiciones |
| Ausentes | `machine`, `hitches`, `gpu_performance_state_share` y toda clave condicional de Metal: trata cada una como opcional (confirmado: no están en el dict en esas líneas) |

`finish` sustituye `layer` por la que calculó `record_run` (`recording.py:341`, `:370`, `:385`): en una corrida nativa de Windows `native Metal, no translation layer` (`recording.py:134-135`) en vez del `native Windows` del motor; `layer_label` llama `native` a ambas, así que ningún lector lo nota (confirmado por el código, no reproducido).
