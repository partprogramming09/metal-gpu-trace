# Del trace al resumen

**Lector:** personas que cambian `perf_report.py` o quieren saber qué tablas de una grabación alimentan cada número. Revisado el 2026-11-17.

English: [From a trace to the summary](../../../guides/summarizing/trace-to-summary.md)

**En corto:** un `.trace` es una grabación muy grande hecha por Instruments, de Apple. Un script le pide las tablas que
necesita, se queda con el trabajo de GPU del propio programa y escribe un archivo de resumen pequeño. Si el programa dejó de
dibujar en pantalla a mitad de camino, el script lo nota y aparta ese tramo en vez de dejar que arruine las cifras de FPS.

Volver al [índice de la guía](./index.md).

![Ocho cajas en dos filas unidas por flechas. Fila de arriba: exportar el índice y las tablas con xctrace; revisar el índice (una decisión: sin metal-gpu-intervals es un error, las demás tablas ausentes van a missing_tables); leer el trabajo de GPU del programa lanzado; decidir si hubo trabajo que nunca se presentó. Fila de abajo: los números por fotograma, las tablas opcionales, ritmo y hitches, y escribir los archivos.](./img/del-trace-al-resumen.png)
*Figura 1. Qué hace `perf_report.py` con un `.trace`. Fuente HTML: `docs/es/guides/resumir-y-analizar/img/del-trace-al-resumen.html`.*

El comando es `python3 -I src/metal_gpu_trace/perf_report.py <recording.trace> [--label NAME] [--out DIR] [--no-memory] [--counters]` (`perf_report.py:1-5`, `:840-847`; el trazo es **posicional**, `:842`). Imprime los bloques `gpu`, `metal_memory_mib` y `process_rss_mib` (`:852`) y escribe los archivos. Todo lo que sigue está **confirmado** por las líneas nombradas; correrlo **no se reprodujo** (no hay ningún `.trace` a mano).

## Paso 1: exportar

`toc_and_tables` (`:95-123`) pide a `xctrace` el índice y cada tabla, con como máximo dos llamadas a `xctrace export` a la vez (`EXPORT_WORKERS = 2`, `:40`): en un trazo grande cada exportación guarda un almacén temporal de gigabytes, así que dos acotan el disco necesario (`:39`). Cada llamada escribe un XML temporal (`export`, `:49-66`) que `rows` borra tras leerlo (`:170`).

| Caso | Qué pasa | Línea |
|---|---|---|
| Falta la carpeta `.trace` | `FileNotFoundError: no recording at <name>: perf_record.sh deletes the .trace once its summary is written, unless KEEP_TRACE=1`; la causa probable es que el trazo ya se borró | `:52-54` |
| `xctrace` 27.1 escribe una tabla entera y luego muere con `SIGTRAP` | `export` acepta el archivo si termina en el límite de una fila o justo tras el esquema de una tabla vacía (`complete_xml`); uno cortado en otro punto es `xctrace export of <name> failed (exit N): <última línea de stderr>`. Una prueba fija los tres casos (`tests/test_report.py:105-125`, dentro de `test_report`; no se ejecutó) | `:69-78`, `:60-61`, `:62-65` |

Solo se lee la **primera corrida** del trazo (xpath `run[@number="1"]`, `:90-92`). Una tabla de millones de filas se lee sin construir el árbol: `rows` hace una primera pasada para hallar qué `id` nombra un `ref` posterior y guarda solo esas celdas (`:131-170`). Si falla un paso posterior, los archivos temporales se borran igual (`finally`, `:825-829`).

## Paso 2: el índice y `missing_tables`

Las tablas que el resumen puede leer:

| Tabla (esquema de xctrace) | ¿Hace falta? | Qué alimenta | Si falta en el trazo |
|---|---|---|---|
| `metal-gpu-intervals` | **obligatoria** (`:34`, `:194`) | cada número de `gpu`, `encoders`, `gpu_idle`, `frames.csv`, los hitches | `ValueError: the trace has no metal-gpu-intervals table; this Xcode may name it differently: trace_tables lists the tables it has` (`:194-196`), pero véase el [límite 2](./limites.md) |
| `metal-current-allocated-size` | se pide salvo con `--no-memory` (`:34`, `:639`) | `metal_memory_mib`, `metal_memory.csv`, la causa de hitch `memory_growth` | con `--no-memory` no se exporta y se nombra en `missing_tables`; si no, la exportación de una tabla ausente falla (probable, [límite 3](./limites.md)) |
| `gpu-performance-state-intervals` | siempre se pide (`:34`) | `gpu_performance_state_share` | la exportación de una tabla ausente falla (probable, [límite 3](./limites.md)) |
| `metal-application-encoders-list` | opcional (`:36`) | las etiquetas de los encoders; qué command buffers son del programa (para `command_buffer_errors`) | sin etiquetas: los encoders se agrupan bajo `?` (`:724-727`, `metrics.label_name` `:89-91`); sin buffers del programa: `command_buffer_errors` cuenta todos los procesos ([límite 5](./limites.md)) |
| `graphics-compiler-activity-intervals` | opcional | `graphics_compiler` (`busy_ms`, `duration_ms`, y `startup` / `in_flight` con 10 fotogramas o más); la causa `shader_compile` | sin clave `graphics_compiler`; ningún hitch se llama `shader_compile` (`:774-781`) |
| `device-thermal-state-intervals` | opcional | `thermal_state_share`; la causa `thermal` | ninguna de las dos existe; el aviso de throttling sigue siendo el basado en FPS (`:782-790`, `:819-820`) |
| `ProcessCPUUsage` | opcional | `cpu`; el `cpu_pct` de cada hitch | sin `cpu`, sin `cpu_pct` (`:791-798`) |
| `metal-resource-allocations`, `graphics-compiler-spill-events`, `metal-command-buffer-error` | opcional | `resource_allocations`, `shader_spills`, `command_buffer_errors` | sin clave (`:799-806`), salvo que `command_buffer_errors` cuenta entonces todos los procesos y lo dice en `command_buffer_errors_scope` ([límite 5](./limites.md)); **ausente no es cero** (y sin `resource_allocations` si el programa no hace ninguna asignación) |
| `gpu-counter-info`, `gpu-counter-value` | solo con `--counters` o `PERF_INSTRUMENTS` que nombre Metal GPU Counters (`:42`, `:632-633`, `:640`) | `gpu_counters`; el `top_limiter` de cada hitch | sin `gpu_counters` (`:812-824`) |

`missing_tables(toc)` (`:190-197`) es la lista ordenada de las tablas de arriba (incluidas memoria y estado de rendimiento, aunque solo `OPTIONAL` es opcional) que el índice no tiene. Se escribe en el resumen (`:664`) para que «sus números salen vacíos» no se confunda con cero (`:663`); una prueba fija la lista completa para un trazo que solo tiene los intervalos de GPU, y el error para uno vacío (`tests/test_report.py:128-135`, no se ejecutó; [E7](./evidencia.md#e7)). **Nada en `src/` lee la clave** (`rg`; véase [la guía de datos](../datos-y-su-ciclo-de-vida/claves-del-resumen.md#el-resumen-clave-por-clave)): es para quien lee, y un gate falla por el propio valor que falta ([Cuando falta un número](./leer-y-comparar.md#cuando-falta-un-numero)). Es `[]` en las dos corridas reales ([E4](./evidencia.md#e4)); los tres nombres que el motor de Windows escribe siempre son una lista fija, no una lectura de un trazo (`perf_record_windows.py:900`, [guía de grabación](../grabar/motor-windows.md#por-que-un-motor-aparte-y-que-mide)).

## Paso 3: el trabajo de GPU del programa

`summarize` toma el primer proceso de tipo `launched` o `attached` (`:643`); sin uno se detiene con `the trace has no launched or attached process; record it with xctrace --launch or --attach` (`:644-645`). Luego lee cada fila de `metal-gpu-intervals` (`:674-693`). Una fila de **otro** proceso solo suma su duración a `by_process` (no se guarda ningún nombre, así que nada de lo que una persona ejecuta llega a un resumen compartido; sirve solo para `noisy_basis` y `other_processes`, `:584-590`). Una fila de **este** proceso guarda la duración (ms) en `frames[frame][channel]` (`vertex`, `fragment` o `compute`), el primer inicio de cada fotograma, la latencia de inicio si la fila trae una razonable, y un tramo `(frame, start, duration, encoder id, command buffer id)` (`:681-693`).

## Trabajo que nunca se presentó

Primero el ejemplo: la segunda corrida del [ejemplo de la guía](./index.md#un-ejemplo-primero). `unpresented(spans)` (`:206-230`) existe porque Instruments numera los fotogramas por *presentaciones*: un programa que dibuja sin presentar (ventana tapada, minimizada o fuera de pantalla, o una carga larga) deja **todos los command buffers posteriores bajo su último número de fotograma**. Un número de fotograma cuenta como atascado si tiene al menos `max(32, 8 × la mediana de command buffers por fotograma)` command buffers (`UNPRESENTED_MIN_BUFFERS = 32`, `UNPRESENTED_FACTOR = 8`, `:201-202`, `:220-221`) **y** su trabajo abarca al menos un segundo (`UNPRESENTED_MIN_S`, `:203`, `:222`).

Esos fotogramas **se dejan fuera de todo lo que es por fotograma**: ni en `frames`, ni en `frame_gpu_ms`, ni en los intervalos, ni en `frames.csv` (`:696-701`, `:233-245`), y se informan una vez en `gpu.unpresented` (cuándo empezó, cuánto duró, cuántos command buffers, cuánto tiempo de GPU; `:227-230`). El tiempo de GPU no se pierde: `gpu_idle` lo sigue contando (`idle_gaps(spans, left_out)`, `:245`).

[E5](./evidencia.md#e5) muestra la segunda corrida: el fotograma 160 guarda 1776 command buffers en 17.236 s y el 92 % del tiempo de GPU (`share_of_gpu_time` 0.92), desde los 3.637 s; los otros 153 fotogramas son los primeros 3.6 s. Después, `perf_compare` y `perf_check` añaden una entrada `unpresented` con una nota (`analysis.py:13-16`, `:30-34`, `:189-191`, `:374-376`), `perf_gate` **falla** la corrida (`:493`) y `suggested_actions` dice que se grabe de nuevo con la ventana visible (`:660-662`). Pruebas: `test_unpresented_tail`, `test_unpresented_spares_heavy_frames`, `test_summary_leaves_out_unpresented`, `test_unpresented_mid_run` (`tests/test_report.py:690`, `:701`, `:715`, `:765`; no se ejecutaron).

## Pasos 4 y 5: los números por fotograma y luego las demás tablas

Tras el filtro, `summarize` arma el bloque `gpu` (`:703-721`), el de encoders (`:723-729`) y luego cada tabla opcional por turno (`:731-817`, saltando con `if "<schema>" in tables` las que el trazo no tiene). El ritmo y los hitches van al final (`:818-822`) porque necesitan las listas de compilador, térmica y memoria. Después se escribe `frames.csv.gz` (`:831-834`), se añade el bloque `common` (`:835`) y se escribe el resumen (`:836`). `recording.finish` añade `layer`, `context`, `tier` y `retention` (`recording.py:337-351`; [guía de grabación](../grabar/recorrido-macos.md#paso-5-cuando-el-script-vuelve)).
