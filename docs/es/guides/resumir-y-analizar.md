# Resumir y analizar

**Lector:** personas que leen un resumen o una comparación y quieren saber de dónde sale cada número y cuándo no fiarse de él, o que cambian `perf_report.py`, `analysis.py`, `metrics.py` o `experiments.py`. Revisado el 2026-11-16.

English: [Summarizing and analyzing](../../guides/summarizing.md)

Esta página sigue una grabación después de hecha: cómo `perf_report.py` convierte un `.trace` de Instruments en el
resumen `<run>.json`, cómo se calcula cada número principal (con la fórmula y la línea), qué hace `analysis.py` cuando lee
resúmenes y los compara, qué añaden los experimentos de `experiments.py`, cómo se decide «mejor», «peor» o «igual» y cómo se
trata el ruido, y qué pasa cuando algo falla. No repite [Datos y su ciclo de vida](./datos-y-su-ciclo-de-vida.md) (las claves
del resumen una a una, las generaciones del formato, qué archivo se borra y cuándo) ni [Grabar](./grabar.md) (cómo se hace el
`.trace`, el candado, el motor de Windows); los enlaza donde la historia continúa. Es la versión en español de la guía en
inglés: mismo contenido, mismos diagramas y la misma evidencia (los comandos y sus salidas no se traducen, ni los mensajes
de error del programa).

Cómo leer las etiquetas: cada afirmación técnica es **confirmada** (con `archivo:línea`, comprobada con `rg` o `sed` el
2026-11-16 contra el árbol de trabajo, que es la 0.27.2 más las entradas `[Unreleased]` de `CHANGELOG.md`), **probable**
(leída en el código pero no ejecutada aquí) o **especulación** (una conjetura sobre el porqué). **No verificado** marca un
dato de fuera que no se comparó con su fuente. Las líneas se mueven cuando cambia el código: busca el nombre, no solo el
número. Cada cifra viene con el comando que la produjo, en [Evidencia](#evidencia-los-comandos-y-su-salida-real). **No
reproducido** significa que el comportamiento no se pudo ejecutar para esta página. Valen dos límites. Primero, el
repositorio no tiene ningún `.trace` que leer (la carpeta `perf-runs/` del clon guarda dos resúmenes terminados y sus tablas,
y nada más), y correr `xctrace` exige una grabación, así que **`perf_report.py` no se ejecutó en absoluto**: lo que hace con un
trazo se lee de su código y se nombran las pruebas que lo fijan. Segundo, la sesión que escribió esta página podía correr
comandos de lectura (`rg`, `sed`, `jq`, `awk`) y no podía correr Python, así que **tampoco se ejecutó ninguna herramienta de
`analysis.py`**: los números que daría se evalúan a mano con las fórmulas del código sobre los dos resúmenes reales, y la
página lo dice cada vez. Las pruebas nombradas **no se ejecutaron** para esta página.

## Un ejemplo primero

Dos grabaciones del mismo programa están en una carpeta de corridas, de 20 segundos cada una (son
`a2-proof-first_20261115-085621` y `a2-proof-second_20261115-085735`; los nombres son la etiqueta más una marca de tiempo).
Sus resúmenes dicen, lado a lado (los comandos son E2 y E3):

| | primera | segunda |
|---|---|---|
| `gpu.frames` | 2045 | 153 |
| `gpu.fps_estimate` | 105.4 | 102.1 |
| `gpu.fps_1pct_low` | 96.2 | 40.8 |
| `gpu.stutter_rate_pct` | 0.29 | 2.63 |
| `gpu.unpresented` | ausente | presente: 1776 command buffers desde los 3.637 s |

Qué se pregunta quien lee, y dónde responde esta página:

1. *¿De dónde sale 105.4?* De la **mediana del intervalo entre inicios de fotograma**, 9.4845 ms: `1000 / 9.4845 = 105.4`
   ([fps_estimate](#fps-estimate)). La página lo recalcula desde `frames.csv` y obtiene el mismo número (E3).
2. *¿Por qué la segunda grabación tiene 153 fotogramas en 20 segundos?* El programa **dejó de presentar** a los 3.6 s (una
   ventana tapada es la causa habitual), así que Instruments dejó de numerar fotogramas y los 17 s restantes de trabajo de GPU
   quedaron fuera de los números de fotograma (`unpresented`, [más abajo](#trabajo-que-nunca-se-presento)). Los 102.1 FPS son la
   velocidad de los primeros 3.6 s solamente.
3. *¿102.1 frente a 105.4 es una regresión?* `perf_compare` informa el cambio (-3.3, -3.1 %) y nada más. `perf_check` juzga
   contra un **rango** con un margen del 3 %; contra una referencia de una sola corrida, 102.1 queda bajo
   `105.4 × 0.97 = 102.238`, así que diría `regressed`, sobre una corrida cuyo propio resumen dice que dejó de presentar (E6).
   Por eso la página dedica una sección al [ruido](#mejor-peor-igual-y-el-ruido).

## Por qué esta parte tiene esta forma

| Decisión | Por qué | Alternativas que se dejaron fuera |
|---|---|---|
| El resumen es un JSON corto leído del trazo una vez, y el `.trace` se borra | Un `.trace` pesa cientos de MB y `xctrace` tarda minutos en leerlo; todo lo que las herramientas necesitan cabe en un archivo de pocos KB más dos tablas (véase la [guía de datos](./datos-y-su-ciclo-de-vida.md)). El script de grabación borra el trazo justo después del informe salvo con `KEEP_TRACE=1` (`perf_record.sh:160-163`) | Releer el trazo en cada pregunta: **especulación** de que se descartó por el tiempo y el disco que cuesta cada lectura (`perf_report.py:39-41`, `:126-165`); ningún ADR recoge la decisión (el ADR-0006 trata de conservar el trazo, no de esto) |
| `perf_report.py` también es un script que se lanza por ruta | `perf_record.sh` llama a `python3 -I perf_report.py <trazo>` (`perf_record.sh:160`) y el archivo añade el paquete a la ruta por sí mismo (`perf_report.py:24-26`) | Solo un módulo: el script debe funcionar con `-I`, que ignora el entorno |
| Los números que comparten ambas plataformas viven en `metrics.py` | Windows no tiene `.trace`, pero su resumen tiene la misma forma: `frame_pacing`, `stats` y `common_block` son una sola copia (`metrics.py:1-2`, `perf_record_windows.py:489`, `:917`) | Dos copias de cada fórmula: las de Windows se desviarían |
| El lector nunca recalcula desde el trazo, solo desde `frames.csv` | `skip_s` recalcula FPS, mínimos, stutter e hitches desde la tabla por fotograma (`analysis.py:552-599`); las demás claves quedan de toda la corrida y lo dicen (`steady.whole_run`) | Conservar el trazo entero para recalcular cualquier cosa: es el trazo que el proyecto borra |
| «Mejor» significa fuera de un **rango**, no un número distinto | Corridas iguales difieren por sí solas: 5 corridas de un programa difirieron un 4.4 % en FPS y un 6.1 % en ms de GPU (`CHANGELOG.md`, la entrada de `perf_baseline`; no se volvió a medir para esta página), así que una sola corrida no es referencia (`analysis.py:259-268`) | Un porcentaje fijo sobre una corrida: llamaría regresión al ruido, como muestra el [ejemplo](#un-ejemplo-primero) |
| La decisión usa pocos números | El ritmo de fotogramas, los encoders cortos y el tiempo ocioso de la GPU «varían demasiado entre corridas iguales»: 13 % y 7 puntos en la misma entrada del changelog (`analysis.py:338-340`) | Juzgar con todo: más falsas alarmas |
| La regla de 100 fotogramas es un aviso, no una negativa | Se añaden `too_short` y un `hint`, y la respuesta se calcula igual (`analysis.py:187`, `:377-378`, `:498-499`) | Negarse con corridas cortas: la persona se quedaría sin nada en vez de con un número y una advertencia |

## Las piezas y dónde viven

| Pieza | Archivo | Qué hace |
|---|---|---|
| El resumidor | `perf_report.py` (`summarize` `:627`, `main` `:840`) | Lee un `.trace` con `xctrace`, escribe `<label>.json`, `.frames.csv.gz`, `.metal_memory.csv.gz` |
| La exportación y el análisis del XML | `perf_report.py` (`export` `:49`, `toc_and_tables` `:95`, `rows` `:143`) | Un `xctrace export` por tabla, de dos en dos; filas resueltas desde las celdas `id`/`ref` de xctrace |
| Las estadísticas | `perf_report.py` (`frame_pacing` `:253`, `attribute_hitches` `:283`, `unpresented` `:206`, `noisy_environment` `:565`) | Los números de la [sección siguiente](#como-se-calcula-cada-numero) |
| Lo que comparten ambas plataformas | `metrics.py` (`stats` `:75`, `encoder_stats` `:94`, `idle_gaps` `:122`, `common_block` `:49`) | Las mismas fórmulas para macOS y Windows |
| Leer y comparar | `analysis.py` | `perf_runs`, `perf_compare`, `perf_baseline`, `perf_check`, `perf_history`, `perf_gate`, `perf_diagnose`, `perf_memory_breakdown` |
| Experimentos | `experiments.py` | `perf_baseline_record`, `perf_ab`, `perf_cold_warm`, `perf_sweep` (graban y luego llaman a `analysis`) |

## De un `.trace` al resumen

![Ocho cajas en dos filas unidas por flechas. Fila de arriba: exportar el índice y las tablas con xctrace; revisar el índice (una decisión: sin metal-gpu-intervals es un error, las demás tablas ausentes van a missing_tables); leer el trabajo de GPU del programa lanzado; decidir si hubo trabajo que nunca se presentó. Fila de abajo: los números por fotograma, las tablas opcionales, ritmo y hitches, y escribir los archivos.](/diagrams/analysis-trace-to-summary.png)
*Figura 1. Qué hace `perf_report.py` con un `.trace`. Fuente HTML: `docs/diagrams/analysis-trace-to-summary.html`.*

El comando es `python3 -I src/metal_gpu_trace/perf_report.py <recording.trace> [--label NAME] [--out DIR] [--no-memory]
[--counters]` (`perf_report.py:1-5`, `:840-847`); el trazo es un argumento **posicional** (`:842`). Imprime los bloques `gpu`,
`metal_memory_mib` y `process_rss_mib` (`:852`) y escribe los archivos. Todo lo que sigue está **confirmado** por las líneas
nombradas; correrlo **no se reprodujo** (no hay ningún `.trace` a mano).

### Paso 1: exportar

`toc_and_tables` (`:95-123`) pide a `xctrace` el índice y cada tabla, con como máximo dos llamadas a `xctrace export` a la vez
(`EXPORT_WORKERS = 2`, `:40`): cada exportación guarda un almacén temporal de gigabytes en un trazo grande, así que dos
acotan el disco que necesita (`:39`). Cada llamada escribe un XML temporal (`export`, `:49-66`) que `rows` borra tras
leerlo (`:170`).

- Una carpeta `.trace` que falta es `FileNotFoundError: no recording at <name>: perf_record.sh deletes the .trace once its
  summary is written, unless KEEP_TRACE=1` (`:52-54`): la causa probable es simplemente que el trazo ya se borró.
- `xctrace` 27.1 a veces escribe una tabla entera y luego muere con `SIGTRAP`. `export` acepta ese archivo cuando termina en
  el límite de una fila o justo tras el esquema de una tabla vacía (`complete_xml`, `:69-78`, `:60-61`); un archivo cortado en
  otro punto es `xctrace export of <name> failed (exit N): <última línea de stderr>` (`:62-65`). Una prueba fija los tres casos
  (`tests/test_report.py:105-125`, dentro de `test_report`; no se ejecutó).
- Las tablas salen solo de la **primera corrida** del trazo: el xpath dice `run[@number="1"]` (`:90-92`).
- Una tabla de millones de filas se lee sin construir el árbol: `rows` hace una primera pasada sobre el archivo para hallar qué
  `id` nombra un `ref` posterior y guarda solo esas celdas (`:131-170`).
- Los archivos temporales se borran aunque falle un paso posterior (`finally`, `:825-829`).

### Paso 2: el índice y `missing_tables`

Las tablas que el resumen puede leer:

| Tabla (esquema de xctrace) | ¿Hace falta? | Qué alimenta | Si falta en el trazo |
|---|---|---|---|
| `metal-gpu-intervals` | **obligatoria** (`:34`, `:194`) | cada número de `gpu`, `encoders`, `gpu_idle`, `frames.csv`, los hitches | `ValueError: the trace has no metal-gpu-intervals table; this Xcode may name it differently: trace_tables lists the tables it has` (`:194-196`), pero véase el [límite 2](#limites-conocidos) |
| `metal-current-allocated-size` | se pide salvo con `--no-memory` (`:34`, `:639`) | `metal_memory_mib`, `metal_memory.csv`, la causa de hitch `memory_growth` | con `--no-memory` no se exporta y se nombra en `missing_tables`; si no, la exportación de una tabla ausente falla (probable, [límite 3](#limites-conocidos)) |
| `gpu-performance-state-intervals` | siempre se pide (`:34`) | `gpu_performance_state_share` | la exportación de una tabla ausente falla (probable, [límite 3](#limites-conocidos)) |
| `metal-application-encoders-list` | opcional (`:36`) | las etiquetas de los encoders | sin etiquetas: los encoders se agrupan bajo `?` (`:724-727`, `metrics.label_name` `:89-91`) |
| `graphics-compiler-activity-intervals` | opcional | `graphics_compiler`; la causa `shader_compile` | sin clave `graphics_compiler`; ningún hitch se llama `shader_compile` (`:774-781`) |
| `device-thermal-state-intervals` | opcional | `thermal_state_share`; la causa `thermal` | sin `thermal_state_share`; sin causa `thermal`; el aviso de throttling sigue siendo el basado en FPS (`:782-790`, `:819-820`) |
| `ProcessCPUUsage` | opcional | `cpu`; el `cpu_pct` de cada hitch | sin `cpu`; los hitches no llevan `cpu_pct` (`:791-798`) |
| `metal-resource-allocations` | opcional | `resource_allocations` | sin clave (tampoco si el programa no tiene ninguna asignación) (`:799-802`) |
| `graphics-compiler-spill-events` | opcional | `shader_spills` | sin clave (`:803-804`) |
| `metal-command-buffer-error` | opcional | `command_buffer_errors` | sin clave: **ausente no es cero** (`:805-806`) |
| `gpu-counter-info`, `gpu-counter-value` | solo con `--counters` o con `PERF_INSTRUMENTS` que nombre Metal GPU Counters (`:42`, `:632-633`, `:640`) | `gpu_counters`; el `top_limiter` de cada hitch | sin `gpu_counters` (`:812-824`) |

`missing_tables(toc)` (`:190-197`) es la lista, ordenada, de las tablas de arriba (con la de memoria y la de estado de
rendimiento incluidas, aunque solo `OPTIONAL` es opcional) que el índice no tiene, y se escribe en el resumen como
`missing_tables` (`:664`). Está para que «sus números salen vacíos» no se confunda con cero (`:663`). Una prueba fija la lista
completa para un trazo que solo tiene los intervalos de GPU, y el error para uno vacío (`tests/test_report.py:128-135`, no
se ejecutó; E7). **Nada en `src/` lee la clave** (`rg`; véase [la guía de datos](./datos-y-su-ciclo-de-vida.md#el-resumen-clave-por-clave)):
es para quien lee el resumen, y una puerta no la mira; falla por el propio valor que falta ([Cuando falta un
número](#cuando-falta-un-numero)).

En un resumen real de este repositorio la lista es `[]` en las dos corridas (E4): estaban todas las tablas. Los tres nombres
que el motor de Windows escribe siempre son una lista fija, no una lectura de un trazo (`perf_record_windows.py:900`,
[guía de grabación](./grabar.md#por-que-un-motor-aparte-y-que-mide)).

### Paso 3: el trabajo de GPU del programa

`summarize` toma el primer proceso de tipo `launched` o `attached` (`:643`); sin él se detiene con `the trace has no launched or
attached process; record it with xctrace --launch or --attach` (`:644-645`). Luego lee cada fila de `metal-gpu-intervals`
(`:674-693`):

- Una fila de **otro** proceso suma su duración a `by_process`: no se guarda ningún nombre, así que nada de lo que una persona
  ejecuta llega a un resumen compartido (`other_processes`, `:584-590`). Solo se usa para `noisy_basis`.
- Una fila de este proceso suma su duración (ms) a `frames[frame][canal]`, donde el canal es `vertex`, `fragment` o `compute`
  (`:681-685`), guarda el primer instante de inicio de cada fotograma (`:690`), la latencia de arranque cuando la fila trae una
  razonable (`:686-689`) y un tramo `(frame, inicio, duración, id de encoder, id de command buffer)` (`:692-693`).

### Trabajo que nunca se presentó

`unpresented(spans)` (`:206-230`) existe por cómo Instruments numera los fotogramas: por *presentaciones*. Un programa que
renderiza sin presentar (su ventana tapada, minimizada o fuera de pantalla, o una carga larga que no presenta nada) deja
**todos los command buffers posteriores bajo su último número de fotograma**. Un número de fotograma cuenta como detenido cuando
se cumplen las dos cosas: tiene al menos `max(32, 8 × la mediana de command buffers por fotograma)` command buffers
(`UNPRESENTED_MIN_BUFFERS = 32`, `UNPRESENTED_FACTOR = 8`, `:201-202`, `:220-221`) y su trabajo abarca al menos un segundo
(`UNPRESENTED_MIN_S`, `:203`, `:222`).

Esos fotogramas se **dejan fuera de todo lo que es por fotograma**: no entran en `frames`, ni en `frame_gpu_ms`, ni en los
intervalos, ni en `frames.csv` (`:696-701`, `:233-245`), y se informan una vez en `gpu.unpresented` con cuándo empezó, cuánto
duró, cuántos command buffers y cuánto tiempo de GPU tenía (`:227-230`). El tiempo de GPU no se pierde: `gpu_idle` lo sigue
contando (`idle_gaps(spans, left_out)`, `:245`).

La segunda corrida del [ejemplo](#un-ejemplo-primero) es este caso, y E5 muestra el bloque: el fotograma 160 tiene 1776
command buffers a lo largo de 17.236 s y el 92 % del tiempo de GPU de la corrida (`share_of_gpu_time` 0.92), desde los
3.637 s. Los otros 153 fotogramas son los primeros 3.6 s. Las herramientas posteriores lo ven: `perf_compare` y `perf_check`
añaden una entrada `unpresented` con una nota (`analysis.py:13-16`, `:30-34`, `:189-191`, `:374-376`), `perf_gate` **falla** la
corrida (`:493`) y `suggested_actions` dice que se grabe de nuevo con la ventana visible (`:660-662`). Pruebas:
`test_unpresented_tail`, `test_unpresented_spares_heavy_frames`, `test_summary_leaves_out_unpresented`,
`test_unpresented_mid_run` (`tests/test_report.py:690`, `:701`, `:715`, `:765`; no se ejecutaron).

### Pasos 4 y 5: los números por fotograma y luego las demás tablas

Tras el filtro `summarize` construye el bloque `gpu` (`:703-721`), el bloque de encoders (`:723-729`) y luego cada tabla
opcional por turno (`:731-817`), saltando con `if "<esquema>" in tables` las que el trazo no tiene. El bloque de ritmo y los
hitches van al final (`:818-822`) porque necesitan las listas del compilador, térmica y memoria leídas antes. Por último se
escribe `frames.csv.gz` (`:831-834`), se añade el bloque `common` (`:835`) y se escribe el resumen (`:836`).
`recording.finish` añade después `layer`, `context`, `tier` y `retention` (`recording.py:337-351`; [guía de
grabación](./grabar.md#paso-5-cuando-el-script-vuelve)).

## Cómo se calcula cada número

Todo esto está **confirmado** por la línea que se indica. «Los intervalos» son las diferencias, en ms, entre el primer inicio
de fotogramas **presentados** consecutivos; «los totales» son los ms de GPU de cada fotograma, sumados sobre sus canales.

| Clave | Fórmula | Línea |
|---|---|---|
| los intervalos | para cada par de números de fotograma consecutivos `a < b` en orden: `first_start[b] - first_start[a]`, solo si es positivo y si no hay un fotograma no presentado entre ambos | `perf_report.py:233-245` |
| los totales | para cada fotograma: la suma de `duration / 1e6` de sus intervalos | `:685`, `:705` |
| `gpu.frames` | el número de fotogramas que quedan | `:711` |
| `gpu.frame_gpu_ms`, `frame_interval_ms` | `stats(totales)`, `stats(intervalos)` | `:712`, `:714` |
| `stats` | `count`, `mean` (3 decimales), `p50 = ordered[n // 2]`, `p95 = ordered[min(n-1, int(n × 0.95))]`, `max` | `metrics.py:75-86` |
| `gpu.fps_estimate` | `round(1000 / mediana(intervalos), 1)`, `None` sin intervalos | `perf_report.py:718` |
| `gpu.fps_1pct_low` | `1000 / intervalos_ordenados[min(n-1, int(n × 0.99))]`, solo con al menos 100 intervalos | `:262-266` |
| `gpu.fps_01pct_low` | igual con `0.999` y al menos 1000 intervalos | `:266` |
| `gpu.stutter_rate_pct` | `100 × (número de intervalos > max(1.5 × mediana, 8.0 ms)) / n`, dos decimales; pide al menos 2 intervalos | `:250`, `:267-268` |
| `gpu.frame_jitter_ms` | `pstdev(intervalos)`, tres decimales (desviación típica poblacional) | `:269` |
| `gpu.throttling_analysis` | con al menos 5 intervalos: `k = max(1, int(n × 0.2))`; `fps_initial` y `fps_final` son `1000 / mediana` de los primeros y los últimos `k` intervalos; `drift = (inicial - final) / inicial × 100`; se detecta cuando la caída pasa del 10 % **y** la media de ms de GPU de los últimos `k` fotogramas supera la de los primeros `k` | `:270-279` |
| `hitches` | el mismo límite que el stutter; cada intervalo por encima es un hitch, con una causa | `:283-320` |
| `gpu.start_latency_ms` | `stats` de la latencia de arranque de cada fila del programa que la tiene, sin los fotogramas no presentados | `:716-717` |
| `gpu_idle` | el tiempo ocioso de la GPU entre los intervalos propios del programa: por fotograma, huecos de más de 1 ms, e `idle_share = suma(huecos) / tramo total` | `metrics.py:122-138` |
| `encoders` | encoders y command buffers por fotograma, el tiempo de GPU de cada encoder, la proporción más corta que 10, 25, 50, 100, 250, 500 y 1000 µs, las 20 etiquetas con más tiempo de GPU | `metrics.py:94-119` |
| `metal_memory_mib` | `peak`, `final`, `mean` de las muestras del programa; `trend_mib_per_min` es la pendiente de mínimos cuadrados sobre la segunda mitad del tiempo, con al menos 5 muestras y 5 s | `perf_report.py:731-746`, `:438-450` |
| `gpu_performance_state_share`, `thermal_state_share` | tiempo en cada estado sobre el total, 3 decimales | `:765-771`, `:782-790` |
| `noisy_environment` | `externo = device_pct_mean - 100 × (1 - idle_share)`; se marca cuando `externo >= 20` puntos | `:560-581` |

Las secciones siguientes explican los que necesitan una razón.

### fps_estimate

La **mediana** del intervalo, no la media: un intervalo largo (una carga, una ventana tapada) mueve la media y no la mediana.
`1000 / mediana` convierte ms por fotograma en fotogramas por segundo. Ojo con dos medianas en el mismo resumen:
`fps_estimate` usa `statistics.median` (la media de los dos valores centrales cuando la cuenta es par) y
`frame_interval_ms.p50` usa `ordered[n // 2]` (el superior). Difieren en el tercer decimal como mucho: en la primera corrida
9.4845 frente a 9.485 (E2, E3). Es cosmético.

### Los mínimos del 1 % y del 0.1 %

`low(share, frames)` (`:262-264`) ordena los intervalos, toma el de la posición `int(n × share)` (acotado al último) y lo
convierte en FPS. Así, el 1 % low es **el intervalo que el 99 % de los fotogramas mejora**, vuelto FPS (un percentil), y es
`None` hasta que la corrida tiene 100 intervalos detrás (1000 para el 0.1 % low): con menos, un fotograma *es* el 1 %. Las
palabras del README, «el FPS del 1 % de fotogramas más lento», describen la idea. Si otras herramientas definen el 1 % low como
este percentil o como la media del 1 % más lento **no se verificó**; compara cifras entre herramientas solo tras comprobarlo.

A 100 FPS, 100 intervalos son un segundo de grabación, así que la regla no es lo que alarga una grabación: los 30 s bajo Wine
tratan del arranque, como dice la [guía de grabación](./grabar.md#por-que-30-segundos-o-mas-bajo-wine).

### Stutter, jitter y hitches

Un intervalo es un stutter **y** un hitch cuando es mayor que `max(1.5 × mediana, 8 ms)` (`STUTTER_FLOOR_MS`, `:250`). El suelo
de 8 ms existe «porque a 500 FPS un fotograma de 3 ms es ruido del planificador, no un stutter» (`:248-249`; prueba
`test_pacing_and_hitches`, `tests/test_report.py:154`, no se ejecutó). Las dos claves usan ese límite; el stutter cuenta los
intervalos sobre `n` y la lista de hitches nombra una causa. En las dos corridas reales las cifras coinciden: 6 intervalos por
encima del límite de 14.227 ms son el 0.29 % de 2044 y `hitches.count` es 6; 4 intervalos por encima de 14.690 ms son el
2.63 % de 152 y `hitches.count` es 4 (E3, E4).

`frame_jitter_ms` es la desviación típica de los intervalos, así que un solo intervalo de 799 ms (la segunda corrida) da
63.799 ms (E3): el jitter se lee junto con `stutter_rate_pct`, no solo.

Cada hitch recibe el nombre del **primero** de estos casos que encaja con lo que el trazo muestra en el intervalo anterior al
fotograma lento (`attribute_hitches`, `:294-310`):

| Orden | Causa | Regla |
|---|---|---|
| 1 | `shader_compile` | el compilador gráfico trabajó para el programa durante el intervalo |
| 2 | `thermal` | el estado térmico del dispositivo fue distinto de `Nominal` durante él |
| 3 | `memory_growth` | la memoria Metal del programa creció 8 MiB o más entre los dos extremos del intervalo |
| 4 | `gpu_heavy` | el fotograma que abre el intervalo usó la GPU al menos el 80 % del intervalo |
| 5 | `cpu_or_wait` | ninguna de las anteriores: el programa estaba ocupado en la CPU o esperando |

La lista guarda los 20 más largos, cada uno con su `frame` (el fotograma que cerró el intervalo), `interval_ms`, `window_ms` y,
si está la tabla de CPU, `cpu_pct` (`:312-320`). `per_minute` es `count / ((último inicio - primer inicio) / 60 000 ms)`, así
que cuenta sobre el tramo presentado y no sobre `duration_s`: la segunda corrida dice 103.3 hitches por minuto porque su
tramo presentado dura 2.3 s (E4). Eso hace de `per_minute` un número que se lee junto con `frames`, no solo. Las causas son
etiquetas, no pruebas: cinco de los seis hitches de la primera corrida son `cpu_or_wait`, que significa «ninguna tabla lo
explica».

### El tiempo de GPU por fotograma es una suma sobre canales

`frame_gpu_ms` suma los intervalos de vértices, fragmentos y cómputo de un fotograma (`:685`, `:705`). Los canales corren en
paralelo, así que el total de un fotograma puede ser mayor que el tiempo entre fotogramas; por eso `gpu_idle` y `gpu_heavy`
se definen sobre los intervalos propios del programa y no sobre la suma. `other_processes` también lo dice (`:587-588`). En
Windows este número no es lo mismo (sale de PresentMon) y la comparación se niega a restar ambos (`NOT_COMPARABLE`,
`analysis.py:132`).

### El aviso de entorno ruidoso

Dos cosas cargan la GPU: el programa y todo lo demás. `device_pct` (de los contadores del controlador, la GPU entera) menos la
parte ocupada propia del programa (`100 × (1 - idle_share)`) es lo que usó «todo lo demás»; 20 puntos o más es
`noisy_environment: true` y añade `noisy_basis` con el número y la proporción de los otros procesos (`:565-581`, `:757-762`).
El 20 es «provisional, no una medición: reajustarlo con al menos 3 corridas tranquilas del mismo Mac» (`:560-561`) y hay una
prueba de que el límite es inclusivo (`test_noisy_boundary_is_inclusive`, `tests/test_report.py:905`, no se ejecutó). Evaluado
a mano sobre las dos corridas reales (E7), la diferencia es -6.4 y 0.6 puntos: ninguna se marcaría. Los dos resúmenes reales ni
siquiera tienen la clave: los escribió una versión anterior a que existiera (generación 1: sin `schema_version`, `tier` ni
`common`), así que la página no puede decir qué escribía esa versión para ella.

### Windows

`perf_record_windows.py` llama al mismo `frame_pacing` (`:489`) y a `common_block` (`:917`), así que los FPS, mínimos,
stutter y jitter de un resumen de Windows siguen las fórmulas de arriba, sobre los intervalos de fotograma de PresentMon o las
medias del registro de drawstress. Lo que no puede medir es `null`, no cero, y la fuente que usó es `gpu.source` (véase la
[guía de grabación](./grabar.md#las-tres-fuentes-de-fotogramas-y-cual-gana)).

## Leer los resúmenes de vuelta: `analysis.py`

### Encontrar y leer una corrida

- `perf_runs` lista los `*.json` de la carpeta de corridas, la más nueva primero, saltando `baselines.json` y el antiguo
  `panel.json` (`analysis.py:51-62`), y un archivo que aún se está escribiendo o que no es un resumen (`:80-81`). Un nombre
  son letras, dígitos, `.`, `_`, `-`; nunca se sigue un enlace (`paths.run_path` `paths.py:33-41`, `paths.read_object`
  `:54-66`).
- Toda herramienta que lee un resumen va envuelta en `reads_recordings` (`:37-48`): un resumen cuyas secciones tienen el tipo
  equivocado (una edición a mano, otra versión) se vuelve un `ToolError` que nombra el tipo de error y nunca una ruta, no un
  error interno.
- Los resúmenes antiguos tienen menos claves. `metrics.schema_of` dice a qué generación pertenece un resumen
  (`metrics.py:13-16`); la comparación dice «summaries written before version 0.4.0 have no encoder numbers» en vez de fallar
  (`:223-227`).

### `skip_s`: el régimen estable

Los primeros segundos de una corrida no son el programa en reposo: se compilan shaders, se cargan recursos.
`steady_summary(run, skip_s)` (`:552-599`) con `skip_s > 0` lee `frames.csv` y conserva los fotogramas que empiezan al menos
`skip_s` segundos después del primero, y recalcula **desde esos fotogramas**: `frames`, `frame_gpu_ms`, `frame_interval_ms`,
`fps_estimate`, los mínimos, stutter y jitter (con el mismo `perf_report.frame_pacing`, `:573`), la cuenta de hitches
(intervalos por encima del `threshold_ms` guardado, con una tolerancia de 0.002 ms porque `frames.csv` redondea los inicios a
0.001 ms, `:503`, `:577`) y el `peak` de la memoria Metal. Lo que no puede recalcular queda de toda la corrida, y el resumen
dice qué: `steady.whole_run` lista `gpu.start_latency_ms`, `thermal_state_share`, `process_rss_mib`, `encoders`, `gpu_idle` y
`gpu_counters` (`:598`). El bloque `cpu` y `throttling_analysis` se quitan (`:569`, `:592`). Las **causas** de los hitches se
conservan solo para los 20 que lista el resumen, y `causes_partial` avisa cuando había más hitches que eso (`:579-586`). Con
menos de 2 fotogramas restantes se niega: `<run> has under 2 frames after the first N s; use a smaller skip_s` (`:565-566`).
`skip_s` va de 0 a 600 (`paths.py:118-126`).

`suggested_actions` propone un `skip_s` por sí misma: cuando cada hitch `shader_compile` entre los 20 más largos termina dentro
del primer cuarto de la corrida, sugiere los segundos enteros que los cubren (`_startup_skip_s`, `:670-690`; pruebas en
`tests/test_analysis.py:1162-1180`, no se ejecutaron).

### `perf_compare`

`compare_summaries` (`:166-242`) es el corazón. Calcula, para 11 números, `change(a, b)`: `b - a` redondeado a 3 decimales y
`100 × cambio / a` redondeado a 1 (`:392-396`); cualquiera es `None` si falta un valor. Los números son los FPS, los dos
mínimos, stutter, jitter, ms de GPU medios y p95, intervalo de fotograma p95, latencia de arranque p50, MiB Metal máximos y
RSS máximo (`:168-180`). **No decide nada.** No dice «más rápido» ni «más lento»; dice qué se movió y añade todo lo que
podría quitar sentido al movimiento:

| Clave | Aparece cuando | Línea |
|---|---|---|
| `too_short` | una corrida tiene menos de 100 fotogramas | `:187` |
| `layer`, `context` | las dos corridas difieren en capa de traducción, commit o versión de Instruments (la [guía de grabación](./grabar.md#que-identifica-una-corrida)) | `:188` |
| `unpresented` | una corrida dejó de presentar | `:189-191` |
| `noisy_environment` | una corrida se marcó como ruidosa | `:192-194` |
| `screen` | una corrida se grabó con la pantalla bloqueada y la otra no | `:195-200` |
| `tier` | los niveles difieren (una corrida `light` no tiene memoria) | `:201-205` |
| `gpu_state` | el nivel de rendimiento ponderado por tiempo difiere en 0.25 o más (0 todo Minimum, 1 todo Medium, 2 todo Maximum): el mismo trabajo cuesta más ms de GPU en un estado más bajo | `:206-211`, `:141-146` |
| `memory_pressure` | ambas midieron la memoria de la misma manera (su cambio), o una nota de que no | `:212-214`, `:149-163` |
| `measure` | una corrida de Windows contra una de Metal: los ms de GPU y la memoria Metal no se restan, los encoders son «no comparables» y la función termina antes | `:215-222` |
| `encoders` y `labels` | ambas son resúmenes de Metal con encoders: encoders y command buffers por fotograma, proporción de encoders cortos, proporción ociosa (las proporciones cambian en puntos, nunca en %, porque de 1.9 % a 49.7 % leería +2516 %, `:239-240`), y la cuenta y los ms de GPU por fotograma de cada etiqueta, el mayor cambio primero, como mucho 20 | `:223-242`, `:399-421` |

`short_us` debe ser uno de 10, 25, 50, 100, 250, 500, 1000 (`:228-230`). Con `markdown` verdadero el resultado trae además una
tabla para un comentario de pull request (`:85-102`), y `suggested_actions` lista qué llamar a continuación para cada corrida
(`:125-126`).

Una etiqueta que falta en un resumen puede haberse caído solo de su lista de las 20 primeras, así que es `outside_top_20` y no
tiene cambio, en vez de `new` o `gone` (`:399-421`).

### Líneas base: un rango, no una corrida

`perf_baseline name runs` (`:259-293`) guarda **copias de los resúmenes** de las corridas (así la referencia sobrevive a
`KEEP_RUNS`) en `baselines.json` con la fecha, reemplazando una referencia del mismo nombre, y devuelve dos cosas por métrica
comprobada:

- el `range`: el valor más bajo y el más alto entre las corridas (`ranges`, `:296-307`), `None` para una métrica que falta en
  alguna corrida;
- el `spread_pct`: `200 × (máx - mín) / (máx + mín)`, el ancho como porcentaje del punto medio (`spreads`, `:310-314`), «el
  ruido de este programa en esta máquina, que un cambio debe superar» (`:264-265`).

Las métricas comprobadas son cuatro: `fps`, `gpu_ms_mean` y el p50 de encoders y de command buffers por fotograma (`CHECKED`,
`:246-251`). El código acepta una sola corrida (el rango es entonces un punto y la dispersión 0); `CHANGELOG.md` dice «ideally 3
or more». El archivo se describe en la [guía de datos](./datos-y-su-ciclo-de-vida.md#el-archivo-de-proyecto-la-marca-y-las-lineas-base).
La línea base informa `unpresented` y `noisy_environment` de las corridas con que se construyó (`:288-292`), así que una mala
referencia se ve.

### `perf_check`: el veredicto

`judge(metric, value, span, margin_pct)` (`:317-330`) es la regla. Para una métrica donde más alto es peor (ms de GPU, los
conteos): `worse` si `value > span.max × (1 + margen)`, `better` si `value < span.min × (1 - margen)`, si no `same`; para los
FPS los lados se intercambian. El margen es `margin_pct / 100` (por defecto **3**, `:334`) para FPS y ms de GPU, y **0** para
los dos conteos `_p50` (`:325`): un conteo de encoders es exacto, y un encoder más por fotograma es un cambio. Después
(`:351-368`):

1. Una métrica que le falta a la corrida o a la referencia es `unchecked`, no se juzga.
2. Si un lado es Windows y el otro Metal, solo se juzgan los FPS (`cross`, `:350-354`).
3. Veredicto: **`regressed` si alguna métrica es peor; `improved` si alguna es mejor y ninguna peor; `same` en otro caso**
   (`:368`).

La respuesta lleva `regressed` e `improved` con la métrica, el valor y el rango de cada una, `unchecked`, el `range` y el
`perf_compare` completo de la *primera* corrida de la referencia contra esta (`:369-371`). El ritmo de fotogramas, los
encoders cortos y el tiempo ocioso están en la comparación pero **nunca deciden** (`:338-340`). El 3 % es un valor por
defecto que eligió el proyecto (**no verificado** como medido: las dispersiones del 4.4 % y el 6.1 % del changelog son la razón
de que la referencia sea un rango); el `spread_pct` de `perf_baseline` se informa pero `perf_check` **no lo lee** ([límite
8](#limites-conocidos)).

Prueba: `test_judge_matches_perf_check` (`tests/test_analysis.py:342`, no se ejecutó) fija que `judge` dice `worse` para
exactamente las métricas que `perf_check` lista como regresiones y `better` para las que lista como mejoras.

### `perf_gate`: una vara, no una referencia

`perf_gate` (`:471-500`) comprueba presupuestos fijos: `fps_min`, `fps_1pct_low_min`, `stutter_rate_pct_max`,
`gpu_ms_p95_max`, `hitches_max`, `metal_mib_max` (`GATES`, `:466-468`); hace falta al menos uno. Cada presupuesto es `ok` solo
si el valor existe y está del lado correcto: `ok = value is not None and (value >= limit if min else value <= limit)` (`:490`).
La respuesta es `pass` solo si todos se cumplen **y** la corrida no tiene `unpresented` (`:493`). Una puerta es la herramienta
para una vara que un cambio debe superar; `perf_check` es para «¿este cambio lo movió más allá de lo que hacen corridas
iguales?».

### `perf_history` y `perf_diagnose`

- `perf_history prefix` lista las corridas cuyo nombre empieza por el prefijo, la más antigua primero, con seis números y el
  cambio de la primera a la última (`:437-462`). Avisa de una serie que mezcla Windows y Metal, y dice «under 3 runs: not a
  trend yet» (`:458-461`). Su propio consejo: tratar una tendencia como real solo cuando supera el `spread_pct` de corridas
  iguales (`:440-441`).
- `perf_diagnose` (`:693-820`) es una lectura por reglas de un resumen. Es **una heurística, y su texto no está en inglés**: las
  recomendaciones son frases en español (`:756-807`), lo único en español de la salida de las herramientas. Sus reglas:

  | Salida | Regla (los umbrales están en el código) | Línea |
  |---|---|---|
  | `stutter_analysis.verdict` | `UNKNOWN` sin el número de stutter; `SEVERE_STUTTER` por encima del 7 %; `MICRO_STUTTER` desde el 2 %; si no `SMOOTH` | `:720-727` |
  | `bottleneck` | `MEMORY_PRESSURE_SUSPECTED` cuando la varianza es alta (jitter de al menos 3 ms, o p95 menos p50 del intervalo de al menos 5 ms) y el conjunto de trabajo es de al menos 1500 MiB; `UNKNOWN` sin `idle_share`; `CPU_SUBMISSION_BOUND` cuando `idle_share >= 0.25` (o `>= 0.20` con demasiados encoders cortos); `GPU_BOUND` cuando `idle_share <= 0.15` y los ms de GPU son al menos el 80 % del intervalo; si no `BALANCED` | `:737-752` |
  | `too_many_short_encoders` | encoders por fotograma p50 de al menos `min_encoders` (4) **y** la proporción bajo `short_us` de al menos `short_share` (0.25) | `:711` |

  Los valores por defecto «salen de bgfx 17-drawstress en un M1 Pro: 7 encoders por fotograma y 50 % bajo 25 µs con Mullion, 2
  y 2 % en Metal nativo» (`:698-699`). El veredicto de memoria es una inferencia («el ancho de banda de memoria no se mide»,
  `:742`). Evaluado a mano sobre las dos corridas reales (E7): la primera es `SMOOTH` (stutter 0.29 %) y la segunda
  `MICRO_STUTTER` (2.63 %), ambas con `idle_share` por encima de 0.25, que por la regla es `CPU_SUBMISSION_BOUND`; la página no
  ejecutó la herramienta, así que esa línea es **probable**.

`perf_memory_breakdown` (`:823-870`) solo reordena el bloque `resource_allocations`; no calcula ninguna magnitud nueva salvo
razones (`live_share_pct`, `allocated_mib_per_live_mib`) y no se detalla aquí.

### Cuando falta un número

Todo lo anterior está hecho para llevar `None` y no cero:

| Lector | Un número que falta se vuelve |
|---|---|
| `compare_summaries` | `change(None, None)`: `a` y `b` en `None` cuando la clave no está (`:182-186`) |
| `perf_check` | la métrica queda `unchecked`; `hint_unchecked` dice que un resumen anterior a la 0.4.0 no tiene números de encoders (`:359-361`, `:382-383`) |
| `perf_gate` | el presupuesto **falla** (`value` nulo, `ok` falso): «a gate must not pass on missing data» (`:476-477`, `:490`) |
| `perf_history` | `null` en la fila (`dig`, `:424-428`) |
| `perf_diagnose` | cuello de botella `UNKNOWN` sin `idle_share` o veredicto de stutter `UNKNOWN` sin el número de stutter (`:720-721`, `:744-745`) |
| una corrida corta | `fps_1pct_low` y `fps_01pct_low` son `None` (un número necesita sus fotogramas, `perf_report.py:264`) |

## Los experimentos

`experiments.py` graba varias corridas y llama a los lectores de arriba. Cada grabación pasa por `record_new_summary`
(`recording.py:440-449`), que llama a `perf_record` y relee el único resumen que escribió, así que cada corrida es una corrida
normal con una etiqueta normal. Las cuatro comparten `cooldown_s` (de 0 a 600 s, descansa entre dos grabaciones y nunca antes
de la primera ni después de la última; una llamada cancelada termina el descanso, `recording.py:240-249`, `paths.py:102-115`)
y reciben los argumentos de `perf_record`. Cada grabación tarda sus segundos más cerca de un minuto en leerse (docstrings), y
el candado de grabación solo deja correr una a la vez (véase la [guía de grabación](./grabar.md#una-grabacion-a-la-vez)).

| Herramienta | Qué graba | Qué devuelve | Límites | Línea |
|---|---|---|---|---|
| `perf_baseline_record` | el mismo programa `count` veces seguidas, corridas `<name>-1`, `-2`, ... | la línea base: el rango y `spread_pct` (termina en `perf_baseline`) | `count` de 1 a 10 | `experiments.py:9-27`, `:20` |
| `perf_ab` | dos entornos en el orden **A B B A**, repetido `rounds` veces; corridas `<name>-a1`, `-b1`, `-b2`, `-a2`, ... | por métrica (FPS, 1 % low, ms de GPU, stutter) los valores de cada lado y un veredicto | `rounds` de 1 a 5 (de 4 a 20 grabaciones) | `:48-69`, `:202-222` |
| `perf_cold_warm` | el mismo programa dos veces: `<name>-first` y `<name>-second` (solo macOS) | hitches y causas de cada corrida y `first_seen_hitches` | ninguno | `:72-102` |
| `perf_sweep` | una vez por cada valor de una variable (`dim`, `example`, `api`, `size` o `env:NAME`), los valores en un sentido en una ronda y al revés en la siguiente | por valor la mediana de las cuatro métricas, y un ajuste a una recta | de 2 a 8 valores, `rounds` de 1 a 5, como mucho 24 grabaciones | `:141-199`, `:117-138` |

### Por qué A B B A

Un portátil se calienta mientras graba. Correr A, B, A, B pondría cada B en una máquina más caliente que la A anterior; A B B A
pone una de cada en el principio y una al final, así que la deriva lenta afecta a ambos lados por igual, y `rounds` repite el
patrón (`:49-51`). El barrido hace lo mismo invirtiendo el orden de los valores una ronda sí y otra no (`:161`). Que la deriva
importa es afirmación del propio proyecto (el enfriamiento existe por eso: «so a laptop does not throttle», `:13-14`); el
tamaño de la deriva **no se midió** para esta página.

### Cómo decide `perf_ab`

`ab_verdict(a, b, higher_better)` (`:36-45`):

- `unknown` si algún lado no tiene valores;
- **better** si cada valor de `b` está por encima de cada valor de `a` (`min(b) > max(a)`) en una métrica donde más alto es
  mejor (FPS, 1 % low), y por debajo en una donde más bajo es mejor (ms de GPU, stutter);
- **worse** en el caso simétrico;
- `same` en otro caso, incluido cualquier solapamiento.

No hay margen ni porcentaje: la **dispersión de las corridas A es la regla de medir**, «para que la dispersión de una corrida
nunca pase por un efecto» (`:37-38`). Con `rounds=1` cada lado tiene dos valores (A B B A), así que la regla mide dos corridas
de ancho. Un valor que una corrida no tiene (un 1 % low de una corrida corta, `None`) se deja fuera de la lista, así que un
lado puede tener menos valores que corridas (`:213-215`). `too_short` es verdadero si alguna corrida tiene menos de 100
fotogramas (`:217-219`). A mano sobre las dos corridas reales, tomando la primera como lado A y la segunda como lado B: FPS
`a = [105.4]` y `b = [102.1]`, así que `max(b) < min(a)` y una métrica donde más alto es mejor da `worse` para una caída del 3 %,
porque un solo valor no tiene dispersión. Es la aritmética de la regla, no una ejecución de la herramienta; por eso `perf_ab`
graba cuatro corridas, y por eso una corrida por lado no es un experimento (E6).

### Cómo decide `perf_cold_warm`

`cold_warm_report` (`:72-87`): `first_seen_hitches = max(0, hitches shader_compile de la primera - los de la segunda)` y
`extra_hitches_in_first = max(0, hitches de la primera - hitches de la segunda)`. La pista dice que la caché de shaders de Metal
**no se borra** entre las corridas, así que la primera corrida es «fría» solo si las pipelines del programa no se habían
construido antes. A mano sobre las dos corridas reales, que se llaman como una pareja de `perf_cold_warm` (las etiquetas
acaban en `-first` y `-second`; que vengan de la herramienta es **probable**): las dos tienen 0 hitches `shader_compile`, así
que `first_seen_hitches` es 0; las cuentas de hitches son 6 y 4, así que `extra_hitches_in_first` es 2 (E7). Los 4 de la segunda
no son comparables con los 6 de la primera: su tramo presentado dura 2.3 s.

### Cómo ajusta `perf_sweep` una recta

Con al menos 3 valores que sean números (`dim` lo es; `size` no, y `example` y `api` son nombres), ajusta los `ms de GPU por
fotograma` contra el valor por mínimos cuadrados (`line_fit`, `:105-114`): `pendiente = Σ(x - mx)(y - my) / Σ(x - mx)²`,
`ordenada = my - pendiente × mx`, `r² = 1 - residuo / total`. Para `dim` la x es `dim³`, porque drawstress dibuja `dim³` cubos por
fotograma (64 000 con `dim` 40, [guía de grabación](./grabar.md#que-hay-en-la-lista-e4)), así que la pendiente son **ms por
dibujo** y la ordenada el coste fijo (`:189-196`). Una variable cuyos valores no son números no da ajuste (se captura el
`ValueError`, `:188-191`), y `line_fit` devuelve `None` cuando x nunca cambia (`:109-110`). Las pruebas que fijan los
experimentos son `test_baseline_record`, `test_perf_sweep`, `test_cold_warm` (`tests/test_analysis.py:170`, `:198`, `:269`) y las
del enfriamiento en `tests/test_recording.py:1398-1443` (no se ejecutaron). Un barrido real **no se reprodujo**: pide de 4 a 24
grabaciones.

## Mejor, peor, igual y el ruido

Una tabla, porque los cuatro que deciden se parecen y no son lo mismo:

| Herramienta | Referencia | Margen | ¿Una sola corrida? | Dice |
|---|---|---|---|---|
| `perf_compare` | una corrida | ninguno | sí | el cambio, y lo que podría quitarle sentido; **ningún veredicto** |
| `perf_check` | el rango de N corridas | 3 % para FPS y ms de GPU (`margin_pct`), 0 para los conteos | sí, contra N | `regressed`, `improved` o `same` |
| `perf_ab` | el rango de las corridas A de este experimento | ninguno | hacen falta 2 por lado como mínimo para que signifique algo | `better`, `worse`, `same` o `unknown` por métrica |
| `perf_gate` | un número que tú pones | ninguno | sí | `pass` o fallo por presupuesto |

![Ocho cajas en dos filas unidas por flechas. Fila de arriba: leer los resúmenes, perf_compare (cambios, sin veredicto), perf_baseline (el rango y la dispersión de corridas iguales) y la decisión de perf_check sobre cada métrica contra ese rango con un margen. Fila de abajo: el veredicto regressed, improved o same; perf_ab; perf_gate; y los avisos que nunca cambian un veredicto.](/diagrams/analysis-compare-flow.png)
*Figura 2. Cómo se compara y se juzga una corrida. Fuente HTML: `docs/diagrams/analysis-compare-flow.html`.*

Qué hace el proyecto con el ruido, en el orden en que lo encuentras:

1. **Repetir.** «Repite una corrida antes de llamar real a un cambio» (el `CLAUDE.md` del proyecto; el [índice de guías](../../guides/index.md)
   dice lo mismo en inglés). `perf_baseline_record` y A B B A son las herramientas que repiten por ti.
2. **Medir el ruido.** El `spread_pct` de una línea base es cuánto difieren corridas iguales.
3. **Juzgar fuera del ruido.** El rango sustituye a la corrida sola, y el margen añade un pequeño colchón más allá.
4. **Decir cuándo la corrida es sospechosa.** Los avisos de `perf_compare`: `unpresented`, `noisy_environment`, `screen`,
   `gpu_state`, `tier`, `too_short`. Son visibles y **no cambian el veredicto** de `perf_check`; solo `perf_gate` falla por
   `unpresented`.
5. **Descansar.** `cooldown_s`, y una entrada de `suggested_actions` que propone 60 s de descanso cuando el Mac se estranguló
   («60 s is a starting value, not a measurement», `analysis.py:665-666`).

El [ejemplo](#un-ejemplo-primero) muestra por qué importa el paso 1: una sola corrida de referencia da un rango de un punto de
ancho, y un 3 % es poco frente al 4.4 % en que difirieron una vez cinco corridas iguales (`CHANGELOG.md`, no se volvió a
medir). Contra `a2-proof-first` sola, la segunda corrida es `regressed`; contra tres corridas iguales del primer tipo muy
probablemente sería `same`. La primera afirmación es aritmética a mano (E6); la segunda es **especulación**.

## Cuando falla

| Qué sale mal | Qué recibe quien lee | Qué queda | Línea |
|---|---|---|---|
| El `.trace` ya se borró | `no recording at <name>: perf_record.sh deletes the .trace once its summary is written, unless KEEP_TRACE=1` | nada nuevo | `perf_report.py:52-54` |
| `xctrace export` falla | `xctrace export of <name> failed (exit N): <última línea de stderr>` | los temporales de las demás exportaciones se borran | `:62-65`, `:106-110`, `:121-123` |
| El trazo no tiene `metal-gpu-intervals` | el mensaje del [Paso 2](#paso-2-la-tabla-de-contenidos-y-missing-tables) | nada | `:194-196` |
| El trazo no tiene proceso lanzado ni adjuntado | `the trace has no launched or attached process; record it with xctrace --launch or --attach` | nada | `:644-645` |
| El programa no hizo trabajo de GPU | se construye un resumen con `frames` 0 y sin FPS; cuando viene de una grabación, `recording.py` lo convierte en `the program did no GPU work ...` y borra la corrida | el `.trace` solo si se pidió | `recording.py:427-436` |
| `perf_report` sale con error en una grabación | `recording failed (exit N): <última línea>` | la trampa del script borra los archivos de la corrida | `perf_record.sh:5`, `:71`, [guía de grabación](./grabar.md#que-pasa-si-instruments-muere-a-mitad) |
| Una exportación agota el tiempo, o una tabla se corta a mitad de fila | un traceback de Python, no una frase ([límite 4](#limites-conocidos)) | puede quedar un XML temporal ([límite 4](#limites-conocidos)) | `:59`, `:166-168`, `:850` |
| Un resumen no es JSON válido, es un enlace o tiene una sección de tipo equivocado | `<run> is not valid JSON; record it again` / `<run> cannot be read` / `... not in the form the recorder writes (<TipoDeError>)` | nada | `paths.py:54-66`, `analysis.py:37-48` |
| `perf_compare` nombra una corrida que no existe | `no run <name>; perf_runs lists them` | | `paths.py:33-41` |
| `skip_s` deja menos de 2 fotogramas, o no hay `frames.csv` | `<run> has under 2 frames after the first N s; use a smaller skip_s`, `<run> has no per-frame file; record it again` | | `analysis.py:510`, `:565-566` |
| `perf_check` o `perf_baseline` nombra una referencia que no existe | `no reference <name>; perf_baseline with no arguments lists them` | | `:285`, `:345` |
| Un experimento falla a mitad | el `ToolError` de la grabación que falló; **las corridas ya grabadas se quedan**, y no se escribe línea base, veredicto ni ajuste | las corridas anteriores, como corridas normales | `experiments.py:23-27`, `:64-69`, `:160-172` (sin `try`) |
| Un experimento se cancela mientras descansa | `cancelled while cooling down` y no empieza ninguna grabación más | las corridas ya hechas | `recording.py:240-249` |

Las dos últimas filas están confirmadas por el código (no hay `try` alrededor de los bucles); un experimento que falla **no se
reprodujo**.

## Límites conocidos

Cada elemento es un límite del comportamiento de hoy, anotado, no arreglado aquí.

| # | Límite | Dónde | Estado |
|---|---|---|---|
| 1 | Los dos resúmenes reales de este repositorio son de generación 1: no tienen `schema_version`, `tier`, `common` ni `noisy_environment`, así que la página recalculó con las fórmulas de hoy y la coincidencia (E3) comprueba esas fórmulas sobre datos viejos, no lo que hacía la versión que los escribió | `perf-runs/` (carpeta local, no se publica) | Confirmado |
| 2 | El mensaje amable para un trazo sin `metal-gpu-intervals` puede ser inalcanzable: `toc_and_tables` toma la exportación de una tabla obligatoria con `future.result()`, y el propio comentario del código dice «xctrace fails on a table that is not there», así que el fallo sería antes el genérico `xctrace export ... failed`; el `ValueError` solo se alcanza si la exportación tiene éxito sobre una tabla ausente. `tests/test_report.py:128-135` prueba `missing_tables` directamente | `perf_report.py:98-99`, `:116-117`, `:194-196` | Probable: no reproducido (no hay trazo) |
| 3 | `missing_tables` lista `metal-current-allocated-size` y `gpu-performance-state-intervals` como si fueran opcionales, pero solo la primera puede faltar sin que falle (cuando la memoria se salta con `--no-memory`); un trazo sin la segunda con toda probabilidad hace fallar la exportación, así que el nombre nunca llegaría al resumen | `perf_report.py:190-197` frente a `:95-123` | Probable |
| 4 | `export` no captura un `subprocess.TimeoutExpired` (600 s por tabla, 3600 para los valores de contadores) y `main` solo captura `ValueError`, `FileNotFoundError` y `RuntimeError`: una exportación lenta acaba en un traceback, que lleva la línea de comando, y el XML temporal que creó `export` no se borra por ese camino (el `finally` de `summarize` solo quita los archivos ya devueltos). Una tabla cortada a mitad de fila (un `ET.ParseError` que `complete_xml` no perdona) acaba igual | `perf_report.py:55-59`, `:166-168`, `:850` | Confirmado por el código; no reproducido |
| 5 | `command_buffer_errors` cuenta todas las filas de su tabla, no solo las del programa; las tablas de asignaciones y de derrames sí se filtran por el pid del programa | `perf_report.py:805-806` frente a `:457-522` | Confirmado por el código |
| 6 | `stutter_rate_pct` salta los intervalos que cruzan un fotograma no presentado; `hitches` y `steady_summary` construyen sus intervalos desde los inicios de fotograma que quedan, así que un intervalo que cruza un fotograma no presentado lo cuentan ellos y no la tasa de stutter, y `hitches.count` puede entonces superar la cuenta de stutter | `perf_report.py:243-244`, `:706`, `:822` frente a `analysis.py:568` | Probable: la detención de la segunda corrida real está al final, así que no lo muestra |
| 7 | `perf_ab`, `perf_sweep` y `perf_cold_warm` no informan `unpresented` ni `noisy_environment` de las corridas que graban (solo `too_short`); `perf_baseline` sí | `experiments.py:202-222`, `:187`, `:72-87` frente a `analysis.py:288-292` | Confirmado |
| 8 | `perf_check` usa un `margin_pct` fijo (3) y no lee el `spread_pct` de la línea base; una referencia de una corrida tiene dispersión 0, y una caída de FPS del 3.1 % sale `regressed` | `analysis.py:317-330`, `:310-314` | Confirmado (E6) |
| 9 | El 1 % low es el percentil del intervalo, no la media del 1 % más lento; que coincida con otras herramientas no está verificado | `perf_report.py:262-266` | No verificado |
| 10 | Un aviso de throttling lo sobrescribe «cualquier intervalo térmico que no sea Nominal» siempre que exista la tabla térmica, hayan caído o no los FPS | `perf_report.py:819-820` | Confirmado |
| 11 | `perf_diagnose` escribe sus recomendaciones en español mientras todo lo demás está en inglés | `analysis.py:756-807` | Confirmado (cosmético) |
| 12 | El margen del 3 %, el umbral de 20 puntos de ruido, el suelo de 8 ms y los umbrales de ocio del 25 %, 20 %, 15 % son elecciones del proyecto, algunas marcadas «provisional» en el código; ninguna se volvió a medir aquí | `analysis.py:325`, `:746-748`; `perf_report.py:250`, `:562` | No verificado |
| 13 | Dos corridas reales prueban las fórmulas sobre resúmenes de un programa en un Mac; los números de un resumen de Windows (PresentMon, el registro) no se recalcularon | | No reproducido |

## Tocarlo sin romperlo

- Un número nuevo: calcúlalo en `metrics.py` si Windows también puede producirlo, y en `perf_report.py` si no; añade la clave
  al resumen y a la [guía de datos](./datos-y-su-ciclo-de-vida.md#el-resumen-clave-por-clave). Haz que una entrada que falta dé
  `None` o ninguna clave, nunca `0`: todos los lectores de arriba tratan `None` como «desconocido».
- Una tabla nueva en `perf_report.py`: añade su esquema a `OPTIONAL`, léela solo `if "<esquema>" in tables` y añade una prueba
  junto a `test_toc_and_tables`. No pongas una tabla en `TABLES` (obligatoria) salvo que todo resumen la necesite: una tabla
  obligatoria ausente hace fallar el informe entero ([límite 3](#limites-conocidos)).
- Algo nuevo que comparar: añádelo a `numbers` en `compare_summaries` (`:168`); para decidir con ello, añádelo a `CHECKED`
  (`:246`) y decide su margen en `judge` (`:325`); para exigirlo, añádelo a `GATES` (`:466`).
- Un cambio de umbral (`STUTTER_FLOOR_MS`, `NOISY_EXTERNAL_PCT`, el 1.5, el 3 %): los números de todo resumen anterior quedan
  como estaban escritos, y `skip_s` recalcula con el `frame_pacing` **actual** pero el `threshold_ms` **guardado**
  (`analysis.py:573-577`); cámbialos sabiendo que los dos discreparán en corridas viejas, y actualiza
  `tests/golden/metrics.json`.
- `analysis.py` no debe llamar a `xctrace`: lee resúmenes y `frames.csv` solamente, y por eso funciona cuando el trazo ya no
  existe. Leer el trazo es trabajo de `perf_report.py` y de las herramientas de `traces.py`.
- Mantén `reads_recordings` en toda herramienta nueva que lea un resumen (`:37-48`), y mantén las rutas fuera de sus mensajes.

## Evidencia: los comandos y su salida real

Recogida el 2026-11-16 en un Mac con Apple silicon. Todos los comandos solo leen. La carpeta de corridas es `perf-runs/` del
clon (una carpeta local, ignorada, que no se publica; guarda las dos corridas de abajo). La sesión que la recogió podía correr
`rg`, `sed`, `jq` y `awk` y no podía correr Python ni `xctrace`: ninguna herramienta de esta página se ejecutó, y E3, E6 y E7
son las fórmulas del código evaluadas a mano.

### E1 Las tablas, los trabajadores, los umbrales y los mensajes de error

```text
$ rg -n '^MEMORY =|^TABLES =|^OPTIONAL =|^COUNTER_TABLES =|^EXPORT_WORKERS =|^STUTTER_FLOOR_MS =|^UNPRESENTED_' src/metal_gpu_trace/perf_report.py | cut -c1-120
33:MEMORY = "metal-current-allocated-size"
34:TABLES = ("metal-gpu-intervals", MEMORY, "gpu-performance-state-intervals")
36:OPTIONAL = ("metal-application-encoders-list", "graphics-compiler-activity-intervals", "device-thermal-state-interval
40:EXPORT_WORKERS = 2
42:COUNTER_TABLES = ("gpu-counter-info", "gpu-counter-value")
201:UNPRESENTED_MIN_BUFFERS = 32
202:UNPRESENTED_FACTOR = 8
203:UNPRESENTED_MIN_S = 1.0
250:STUTTER_FLOOR_MS = 8.0

$ rg -n 'raise ValueError|sys.exit|raise RuntimeError|raise FileNotFoundError' src/metal_gpu_trace/perf_report.py | cut -c1-170
53:        raise FileNotFoundError(f"no recording at {pathlib.Path(trace).name}: perf_record.sh deletes the .trace once "
65:        raise RuntimeError(f"xctrace export of {pathlib.Path(trace).name} failed (exit {proc.returncode}): {reason}")
195:        raise ValueError("the trace has no metal-gpu-intervals table; this Xcode may name it differently: "
645:        raise ValueError("the trace has no launched or attached process; record it with xctrace --launch or --attach")
851:        sys.exit(str(error))
```

Solo estas cuatro condiciones tienen una frase; el `except` de la línea 850 captura exactamente esas tres clases. Cualquier
otra cosa escapa de `main` como un traceback ([límite 4](#limites-conocidos)).

### E2 El bloque `gpu` de los dos resúmenes reales

```text
$ jq -c '.gpu | del(.per_channel_ms)' a2-proof-first_20261115-085621.json
{"intervals":6269,"frames":2045,"frame_gpu_ms":{"count":2045,"mean":5.937,"p50":6.008,"p95":6.213,"max":13.561},"frame_interval_ms":{"count":2044,"mean":9.587,"p50":9.485,"p95":10.098,"max":36.335},"fps_estimate":105.4,"fps_1pct_low":96.2,"fps_01pct_low":48.2,"stutter_rate_pct":0.29,"frame_jitter_ms":0.817,"throttling_analysis":{"thermal_throttling_detected":false,"fps_initial":103.0,"fps_final":105.8,"fps_drift_pct":-2.7}}

$ jq -c '.gpu | del(.per_channel_ms)' a2-proof-second_20261115-085735.json
{"intervals":548,"frames":153,"frame_gpu_ms":{"count":153,"mean":5.86,"p50":6.058,"p95":6.798,"max":13.704},"frame_interval_ms":{"count":152,"mean":15.286,"p50":9.795,"p95":11.982,"max":798.956},"fps_estimate":102.1,"unpresented":{"frames":[160],"from_s":3.637,"span_s":17.236,"command_buffers":1776,"gpu_ms":10358.288,"share_of_gpu_time":0.92},"fps_1pct_low":40.8,"fps_01pct_low":null,"stutter_rate_pct":2.63,"frame_jitter_ms":63.799,"throttling_analysis":{"thermal_throttling_detected":false,"fps_initial":100.6,"fps_final":100.8,"fps_drift_pct":-0.2}}
```

### E3 Recalcular los números desde `frames.csv`

La tabla tiene una fila por fotograma: `frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total` (la [guía de
datos](./datos-y-su-ciclo-de-vida.md#las-tablas-y-los-muestreadores)). Los intervalos son las diferencias de `start_ms` (solo
las positivas); las fórmulas son las de la tabla de arriba.

```text
$ cd perf-runs
$ tail -n +2 a2-proof-first_20261115-085621.frames.csv | awk -F, 'NR>1{g=$2-p; if(g>0) print g} {p=$2}' | sort -n | awk '{a[NR]=$1; s+=$1; q+=$1*$1} END{n=NR; med=(n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2; lim=1.5*med; if(lim<8)lim=8; for(k=1;k<=n;k++) if(a[k]>lim) c++; i=int(n*0.99); if(i>n-1)i=n-1; j=int(n*0.999); if(j>n-1)j=n-1; m=s/n; sd=sqrt(q/n-m*m); printf "n=%d median=%.4f fps=%.1f low1=%.1f low01=%.1f limit=%.3f over=%d stutter=%.2f jitter=%.3f max=%.3f\n", n, med, 1000/med, 1000/a[i+1], 1000/a[j+1], lim, c, c/n*100, sd, a[n]}'
n=2044 median=9.4845 fps=105.4 low1=96.2 low01=48.2 limit=14.227 over=6 stutter=0.29 jitter=0.817 max=36.335
$ tail -n +2 a2-proof-first_20261115-085621.frames.csv | awk -F, '{s+=$6; n++} END{printf "frames=%d gpu_ms_mean=%.3f\n", n, s/n}'
frames=2045 gpu_ms_mean=5.937

$ tail -n +2 a2-proof-second_20261115-085735.frames.csv | awk -F, 'NR>1{g=$2-p; if(g>0) print g} {p=$2}' | sort -n | awk '{a[NR]=$1; s+=$1; q+=$1*$1} END{n=NR; med=(n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2; lim=1.5*med; if(lim<8)lim=8; for(k=1;k<=n;k++) if(a[k]>lim) c++; i=int(n*0.99); if(i>n-1)i=n-1; j=int(n*0.999); if(j>n-1)j=n-1; m=s/n; sd=sqrt(q/n-m*m); printf "n=%d median=%.4f fps=%.1f low1=%.1f low01(n<1000: null)=%.1f limit=%.3f over=%d stutter=%.2f jitter=%.3f max=%.3f\n", n, med, 1000/med, 1000/a[i+1], 1000/a[j+1], lim, c, c/n*100, sd, a[n]}'
n=152 median=9.7935 fps=102.1 low1=40.8 low01(n<1000: null)=1.3 limit=14.690 over=4 stutter=2.63 jitter=63.799 max=798.956
$ tail -n +2 a2-proof-second_20261115-085735.frames.csv | awk -F, '{s+=$6; n++} END{printf "frames=%d gpu_ms_mean=%.3f\n", n, s/n}'
frames=153 gpu_ms_mean=5.860
```

Frente a E2: `fps_estimate` 105.4 y 102.1, `fps_1pct_low` 96.2 y 40.8, `fps_01pct_low` 48.2 (primera) y `null` (segunda: 152 intervalos son
menos de 1000, así que el `1.3` que imprime el script es lo que la regla descarta, y el resumen correctamente tiene `null`),
`stutter_rate_pct` 0.29 y 2.63, `frame_jitter_ms` 0.817 y 63.799, fotogramas 2045 y 153, ms de GPU medios 5.937 y 5.860 (5.86 en
el resumen). Todas las cifras publicadas coinciden. El umbral de hitch es 14.227 para la primera corrida y 14.690 aquí (14.691 en
el resumen: el resumen lo calculó con inicios en nanosegundos, la tabla los guarda a 0.001 ms). Otra diferencia es de diseño:
`frame_interval_ms.p50` es 9.485 y 9.795 frente a las medianas verdaderas 9.4845 y 9.7935 (véase
[fps_estimate](#fps-estimate)). Los resúmenes los escribió una versión del código anterior a las fórmulas usadas aquí, así que
esto comprueba las fórmulas sobre datos viejos ([límite 1](#limites-conocidos)).

### E4 Los bloques de hitches

```text
$ jq -c '{missing_tables, hitches: (.hitches | del(.worst))}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"missing_tables":[],"hitches":{"count":6,"per_minute":18.37,"threshold_ms":14.227,"causes":{"cpu_or_wait":5,"memory_growth":1}}}
{"missing_tables":[],"hitches":{"count":4,"per_minute":103.3,"threshold_ms":14.691,"causes":{"cpu_or_wait":3,"memory_growth":1}}}

$ jq -c '.hitches.worst[0:2]' a2-proof-second_20261115-085735.json
[{"frame":159,"interval_ms":798.956,"cause":"cpu_or_wait","window_ms":[2825.46,3624.416],"cpu_pct":4.8},{"frame":23,"interval_ms":24.502,"cause":"cpu_or_wait","window_ms":[1465.036,1489.538],"cpu_pct":95.0}]
```

`count` es 6 y 4, igual que las cuentas «over» de E3 (así que hitches y stutter comparten límite). `per_minute` 103.3 con 4 hitches
significa un tramo de 2.32 s, la parte presentada de una corrida de 20.9 s (el `duration_s` del resumen es 20.87). El peor
hitch de la segunda corrida es el intervalo de 799 ms que cierra la parte presentada, con el programa al 4.8 % de CPU: estaba
esperando, lo que encaja con una ventana tapada (**especulación**: por qué la ventana se tapó no está en los datos).

### E5 El bloque `unpresented`, tomado de E2

`gpu.unpresented` de la segunda corrida: `frames` `[160]`, `from_s` 3.637, `span_s` 17.236, `command_buffers` 1776, `gpu_ms`
10358.288, `share_of_gpu_time` 0.92. La regla del propio código pide al menos `max(32, 8 × mediana)` command buffers y al menos
1 s (`perf_report.py:220-222`); 1776 y 17.236 s la cumplen de sobra. Los `intervals` de la corrida son 548 y sus `frames` 153: el
trabajo dejado fuera no está en ellos. La lectura «la ventana se tapó a los 3.6 s» es **especulación**.

### E6 `perf_compare` y `perf_check`, evaluados a mano

Las dos funciones **no se ejecutaron**. Estas son sus fórmulas (`change`, `analysis.py:392-396`; `judge`, `:317-330`) aplicadas
con `jq` a los dos resúmenes, `a` la primera corrida y `b` la segunda:

```text
$ jq -n --slurpfile a a2-proof-first_20261115-085621.json --slurpfile b a2-proof-second_20261115-085735.json 'def ch(x;y): {a:x,b:y,change:((y-x)*1000|round/1000),change_pct:(if x==0 then null else ((100*(y-x)/x)*10|round/10) end)}; ($a[0]) as $A | ($b[0]) as $B | {fps:ch($A.gpu.fps_estimate;$B.gpu.fps_estimate), fps_1pct_low:ch($A.gpu.fps_1pct_low;$B.gpu.fps_1pct_low), stutter_rate_pct:ch($A.gpu.stutter_rate_pct;$B.gpu.stutter_rate_pct), frame_jitter_ms:ch($A.gpu.frame_jitter_ms;$B.gpu.frame_jitter_ms), gpu_ms_mean:ch($A.gpu.frame_gpu_ms.mean;$B.gpu.frame_gpu_ms.mean), metal_mib_peak:ch($A.metal_memory_mib.peak;$B.metal_memory_mib.peak), too_short:[], unpresented_runs:["b"]}' -c
{"fps":{"a":105.4,"b":102.1,"change":-3.3,"change_pct":-3.1},"fps_1pct_low":{"a":96.2,"b":40.8,"change":-55.4,"change_pct":-57.6},"stutter_rate_pct":{"a":0.29,"b":2.63,"change":2.34,"change_pct":806.9},"frame_jitter_ms":{"a":0.817,"b":63.799,"change":62.982,"change_pct":7708.9},"gpu_ms_mean":{"a":5.937,"b":5.86,"change":-0.077,"change_pct":-1.3},"metal_mib_peak":{"a":83.17,"b":94.38,"change":11.21,"change_pct":13.5},"too_short":[],"unpresented_runs":["b"]}

$ jq -n --slurpfile a a2-proof-first_20261115-085621.json --slurpfile b a2-proof-second_20261115-085735.json '($a[0].gpu.fps_estimate) as $lo | ($b[0].gpu.fps_estimate) as $v | {fps_floor_with_3pct_margin:($lo*0.97), run_fps:$v, verdict:(if $v < $lo*0.97 then "worse" else "same" end), gpu_ms_ceiling:($a[0].gpu.frame_gpu_ms.mean*1.03), run_gpu_ms:$b[0].gpu.frame_gpu_ms.mean}' -c
{"fps_floor_with_3pct_margin":102.238,"run_fps":102.1,"verdict":"worse","gpu_ms_ceiling":6.1151100000000005,"run_gpu_ms":5.86}
```

Lectura: `perf_compare` daría el primer bloque (más una entrada `unpresented` que nombra a `b`, y ningún `too_short` porque 153 no es
menos de 100). Para `perf_check` contra una referencia hecha solo con la primera corrida, los FPS quedan bajo el suelo
(102.1 < 102.238), así que el veredicto sería `regressed`; los ms de GPU por fotograma (5.86 bajo 6.115) y los conteos de
encoders (las dos corridas tienen p50 de 2 y 1, de los `encoders` de los resúmenes) son `same`. La referencia de la primera
corrida tiene `spread_pct` 0. Esto es el [límite 8](#limites-conocidos) y la razón de que `perf_baseline` quiera varias
corridas. Los resultados son **probables** (el código se leyó, no se ejecutó).

### E7 `missing_tables`, ruido y diagnóstico a mano

```text
$ sed -n 128,132p tests/test_report.py
    assert perf_report.missing_tables(toc) == ["ProcessCPUUsage", "device-thermal-state-intervals", "gpu-performance-state-intervals",
                                               "graphics-compiler-activity-intervals", "graphics-compiler-spill-events",
                                               "metal-application-encoders-list",
                                               "metal-command-buffer-error", "metal-current-allocated-size",
                                               "metal-resource-allocations"]

$ jq -c '{label, stutter:.gpu.stutter_rate_pct, stutter_verdict:(if .gpu.stutter_rate_pct==null then "UNKNOWN" elif .gpu.stutter_rate_pct>7 then "SEVERE_STUTTER" elif .gpu.stutter_rate_pct>=2 then "MICRO_STUTTER" else "SMOOTH" end), idle_share:.gpu_idle.idle_share, high_variance:((.gpu.frame_jitter_ms>=3) or ((.gpu.frame_interval_ms.p95-.gpu.frame_interval_ms.p50)>=5)), working_set_mib:([.process_rss_mib.max,.metal_memory_mib.peak]|max), noisy_external_pct:((.gpu_activity.device_pct.mean - 100*(1-.gpu_idle.idle_share))*10|round/10)}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"label":"a2-proof-first_20261115-085621","stutter":0.29,"stutter_verdict":"SMOOTH","idle_share":0.381,"high_variance":false,"working_set_mib":237.312,"noisy_external_pct":-6.4}
{"label":"a2-proof-second_20261115-085735","stutter":2.63,"stutter_verdict":"MICRO_STUTTER","idle_share":0.425,"high_variance":true,"working_set_mib":238.672,"noisy_external_pct":0.6}

$ jq -c '{label,hitches:.hitches.count,shader_compile:(.hitches.causes.shader_compile // 0),compiler_busy_ms:.graphics_compiler.busy_ms}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"label":"a2-proof-first_20261115-085621","hitches":6,"shader_compile":0,"compiler_busy_ms":0.227}
{"label":"a2-proof-second_20261115-085735","hitches":4,"shader_compile":0,"compiler_busy_ms":0.292}
```

El primer bloque es la aserción completa de `missing_tables` para un trazo que solo tiene los intervalos de GPU: nueve nombres,
ordenados. El segundo aplica a mano los umbrales de `perf_diagnose` y de `noisy_environment`: veredictos de stutter `SMOOTH` y
`MICRO_STUTTER`, varianza alta solo en la segunda, un conjunto de trabajo muy por debajo de 1500 MiB, y proporciones ociosas de
0.381 y 0.425 (ambas por encima de 0.25: un cuello de botella `CPU_SUBMISSION_BOUND` por la regla, **probable**, la herramienta
no se ejecutó); y la diferencia entre el uso de la GPU y el propio del programa, -6.4 y 0.6 puntos, lejos de los 20 que marcan
ruido. El tercer bloque es la entrada de `cold_warm_report`: ningún hitch `shader_compile` en ninguna de las dos corridas, así
que `first_seen_hitches` sería 0, y `extra_hitches_in_first` sería `max(0, 6 - 4)` = 2.

### E8 Los límites que el código impone

```text
$ rg -n "1 <= count|1 <= rounds|2 <= len\(values\)|> 24|<= seconds <= 600|<= skip <= 600|ok = value|margin = 0 if" src/metal_gpu_trace/experiments.py src/metal_gpu_trace/analysis.py src/metal_gpu_trace/paths.py | cut -c1-190
src/metal_gpu_trace/experiments.py:20:    if not 1 <= count <= 10:
src/metal_gpu_trace/experiments.py:60:    if not 1 <= rounds <= 5:
src/metal_gpu_trace/experiments.py:124:    if not isinstance(values, list) or not 2 <= len(values) <= 8:
src/metal_gpu_trace/experiments.py:153:    if not 1 <= rounds <= 5:
src/metal_gpu_trace/experiments.py:156:    if len(values) * rounds > 24:
src/metal_gpu_trace/paths.py:113:    if not 0 <= seconds <= 600:  # a NaN is false here too
src/metal_gpu_trace/paths.py:124:    if not 0 <= skip <= 600:
src/metal_gpu_trace/analysis.py:325:    margin = 0 if metric.endswith("_p50") else margin_pct / 100
src/metal_gpu_trace/analysis.py:490:        ok = value is not None and (value >= limit if kind == "min" else value <= limit)
```

### Lo que no se reprodujo

- **`perf_report.py` sobre un `.trace`**: no existe ningún trazo en el repositorio (`perf-runs/` solo tiene resúmenes y
  tablas) y no se ejecutó `xctrace`. La exportación, la revisión del índice, `missing_tables`, la lectura tolerante a cortes y
  los mensajes de error se leen del código y los fijan las pruebas de `tests/test_report.py` (no se ejecutaron).
- **Cualquier herramienta de `analysis.py` y `experiments.py`**: la sesión no tenía Python; `perf_compare`, `perf_check`,
  `perf_gate`, `perf_diagnose`, `perf_ab`, `perf_cold_warm`, `perf_sweep` y `perf_baseline_record` se evaluaron a mano o no se
  evaluaron. Una línea base real, A B B A y un barrido piden de 4 a 24 grabaciones.
- **Un resumen con `missing_tables` no vacío**, un trazo sin `metal-gpu-intervals`, una tabla cortada a mitad de fila y una
  exportación que agota el tiempo.
- **El recálculo de un resumen de Windows.**
- **Los números de la 0.27.2**: los dos resúmenes reales son de generación 1 y anteriores al código descrito.

## Véase también

- [Datos y su ciclo de vida](./datos-y-su-ciclo-de-vida.md): las claves del resumen una a una, las generaciones, las tablas, el
  archivo de líneas base y qué borra qué.
- [Grabar](./grabar.md): cómo se hacen el `.trace` y los muestreadores `rss.csv` y `agx.csv`, el candado, el motor de Windows.
- [How it works](../../guides/how-it-works.md): qué capa llama a cuál.
- [Run from a clone](../../guides/run-from-a-clone.md): cómo correr el código y las pruebas.
