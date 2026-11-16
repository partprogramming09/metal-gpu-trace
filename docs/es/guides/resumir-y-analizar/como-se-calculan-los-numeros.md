# Cómo se calcula cada número

**Lector:** personas que ven un número en un resumen y preguntan de dónde sale, o que cambian `perf_report.py` o `metrics.py`. Revisado el 2026-11-16.

English: [How each number is computed](../../../guides/summarizing/how-numbers-are-computed.md)

**En corto:** casi todos los números salen de una sola lista: cuántos milisegundos pasan entre el inicio de un fotograma y el
del siguiente. Los «FPS» son el intervalo típico puesto del revés, un «stutter» es un intervalo mucho más largo de lo normal
y un «hitch» es ese mismo intervalo lento con una conjetura sobre su causa. Esta página da cada fórmula y la línea de código.

Volver al [índice de la guía](./index.md).

Primero el ejemplo: en la primera corrida del ejemplo de la guía, el intervalo mediano es 9.4845 ms, así que
`1000 / 9.4845 = 105.4` FPS; 6 de 2044 intervalos pasan de 14.227 ms, así que el stutter es 0.29 % ([E3](./evidencia.md#e3)).

Todo lo de aquí está **confirmado** por la línea dada. «Los intervalos» son los tiempos entre el primer inicio de
fotogramas **presentados** consecutivos, en ms; «los totales» son los ms de GPU de cada fotograma, sumados sobre sus canales.

| Clave | Fórmula | Línea |
|---|---|---|
| los intervalos | para cada par de números de fotograma consecutivos `a < b` en orden: `first_start[b] - first_start[a]`, solo si es positivo y si no hay un fotograma sin presentar entre ellos | `perf_report.py:233-245` |
| los totales | por fotograma: la suma de `duration / 1e6` de sus intervalos | `:685`, `:705` |
| `gpu.frames` | el número de fotogramas que se conservan | `:711` |
| `gpu.frame_gpu_ms`, `frame_interval_ms` | `stats(totales)`, `stats(intervalos)` | `:712`, `:714` |
| `stats` | `count`, `mean` (3 decimales), `p50 = ordered[n // 2]`, `p95 = ordered[min(n-1, int(n × 0.95))]`, `max` | `metrics.py:75-86` |
| `gpu.fps_estimate` | `round(1000 / median(intervalos), 1)`, `None` sin intervalos | `perf_report.py:718` |
| `gpu.fps_1pct_low` | `1000 / ordered_gaps[min(n-1, int(n × 0.99))]`, solo con al menos 100 intervalos | `:262-266` |
| `gpu.fps_01pct_low` | igual con `0.999` y al menos 1000 intervalos | `:266` |
| `gpu.stutter_rate_pct` | `100 × (número de intervalos > max(1.5 × mediana, 8.0 ms)) / n`, dos decimales; exige al menos 2 intervalos | `:250`, `:267-268` |
| `gpu.frame_jitter_ms` | `pstdev(intervalos)`, tres decimales (desviación típica poblacional) | `:269` |
| `gpu.throttling_analysis` | con al menos 5 intervalos: `k = max(1, int(n × 0.2))`; `fps_initial` y `fps_final` son `1000 / mediana` de los primeros y últimos `k` intervalos; `drift = (initial - final) / initial × 100`; se detecta cuando la caída pasa del 10 % **y** el promedio de ms de GPU de los últimos `k` fotogramas supera al de los primeros `k` | `:270-279` |
| `hitches` | el mismo límite que el stutter; cada intervalo por encima es un hitch, con una causa | `:283-320` |
| `gpu.start_latency_ms` | `stats` de la latencia de inicio de cada fila del programa que la tiene, sin los fotogramas sin presentar | `:716-717` |
| `gpu_idle` | el tiempo ocioso de la GPU entre los intervalos del propio programa: por fotograma, huecos de más de 1 ms, y `idle_share = suma(huecos) / tramo total` | `metrics.py:122-138` |
| `encoders` | encoders y command buffers por fotograma, el tiempo de GPU de cada encoder, la parte más corta que 10, 25, 50, 100, 250, 500 y 1000 µs, las 20 etiquetas con más tiempo de GPU | `metrics.py:94-119` |
| `metal_memory_mib` | `peak`, `final`, `mean` de las muestras del programa; `trend_mib_per_min` es la pendiente de mínimos cuadrados sobre la segunda mitad del tiempo, con al menos 5 muestras y 5 s | `perf_report.py:731-746`, `:438-450` |
| `gpu_performance_state_share`, `thermal_state_share` | tiempo en cada estado sobre el total, 3 decimales | `:765-771`, `:782-790` |
| `noisy_environment` | `external = device_pct_mean - 100 × (1 - idle_share)`; se marca cuando `external >= 20` puntos | `:560-581` |

Las secciones siguientes explican las que necesitan una razón.

## fps_estimate

La **mediana** del intervalo, no la media: un intervalo largo (una carga, una ventana tapada) mueve la media y no la mediana.
`1000 / mediana` convierte ms por fotograma en fotogramas por segundo. Hay dos medianas en un mismo resumen: `fps_estimate`
usa `statistics.median` (la media de los dos valores centrales si la cuenta es par) y `frame_interval_ms.p50` usa
`ordered[n // 2]` (el superior). Difieren en el tercer decimal como mucho: 9.4845 frente a 9.485 en la primera corrida
([E2, E3](./evidencia.md#e3)). Es cosmético.

## Los mínimos del 1 % y del 0.1 %

`low(share, frames)` (`:262-264`) ordena los intervalos, toma el de la posición `int(n × share)` (acotado al último) y lo
convierte en FPS. Así, el 1 % low es **el intervalo que el 99 % de los fotogramas mejora**, vuelto FPS (un percentil), y es
`None` hasta que la corrida tiene 100 intervalos detrás (1000 para el 0.1 % low): con menos, un fotograma *es* el 1 %. El
README dice «el FPS del 1 % de fotogramas más lento», que describe la idea. Si otras herramientas definen el 1 % low como
este percentil o como la media del 1 % más lento **no se verificó**; compara entre herramientas solo tras comprobarlo.

A 100 FPS, 100 intervalos son un segundo de grabación, así que la regla no es lo que alarga una grabación: los 30 s bajo
Wine tratan del arranque ([guía de grabación](../grabar/reglas.md#por-que-30-segundos-o-mas-bajo-wine)).

## Stutter, jitter y hitches

Un intervalo es un stutter **y** un hitch cuando es mayor que `max(1.5 × mediana, 8 ms)` (`STUTTER_FLOOR_MS`, `:250`). El
suelo de 8 ms existe «porque a 500 FPS un fotograma de 3 ms es ruido del planificador, no un stutter» (`:248-249`; prueba
`test_pacing_and_hitches`, `tests/test_report.py:154`, no se ejecutó). El stutter cuenta los intervalos sobre `n`; la lista
de hitches nombra una causa. En las dos corridas reales coinciden: 6 intervalos sobre 14.227 ms son el 0.29 % de 2044 y
`hitches.count` es 6; 4 sobre 14.690 ms son el 2.63 % de 152 y `hitches.count` es 4 ([E3, E4](./evidencia.md#e4)).

`frame_jitter_ms` es la desviación típica de los intervalos, así que un solo intervalo de 799 ms (segunda corrida) da
63.799 ms ([E3](./evidencia.md#e3)): el jitter se lee junto a `stutter_rate_pct`, no solo.

Cada hitch se nombra con la **primera** regla que encaja con lo que el trazo muestra en el intervalo previo al fotograma
lento (`attribute_hitches`, `:294-310`):

| Orden | Causa | Regla |
|---|---|---|
| 1 | `shader_compile` | el compilador gráfico trabajó para el programa durante el intervalo |
| 2 | `thermal` | el estado térmico del equipo fue distinto de `Nominal` durante él |
| 3 | `memory_growth` | la memoria Metal del programa creció 8 MiB o más entre los dos extremos del intervalo |
| 4 | `gpu_heavy` | el fotograma que abre el intervalo usó la GPU al menos el 80 % del intervalo |
| 5 | `cpu_or_wait` | ninguna de las anteriores: el programa estaba ocupado en la CPU o esperando |

La lista guarda los 20 más largos, cada uno con `frame` (el fotograma que cerró el intervalo), `interval_ms`, `window_ms` y,
si está la tabla de CPU, `cpu_pct` (`:312-320`). `per_minute` es `count / ((último inicio - primer inicio) / 60 000 ms)`:
cuenta sobre el tramo presentado, no sobre `duration_s`, así que la segunda corrida dice 103.3 hitches por minuto porque su
tramo presentado dura 2.3 s (E4). Léelo junto a `frames`, no solo. Las causas son etiquetas, no pruebas: cinco de los seis
hitches de la primera corrida son `cpu_or_wait`, que significa «ninguna tabla lo explica».

## El tiempo de GPU por fotograma es una suma sobre canales

`frame_gpu_ms` suma los intervalos vertex, fragment y compute de un fotograma (`:685`, `:705`). Los canales corren en
paralelo, así que el total de un fotograma puede superar el tiempo entre fotogramas; por eso `gpu_idle` y `gpu_heavy` se
definen sobre los intervalos del propio programa y no sobre la suma (`other_processes` también lo dice, `:587-588`). En
Windows este número no es lo mismo (sale de PresentMon) y la comparación se niega a restar ambos (`NOT_COMPARABLE`,
`analysis.py:132`).

## El aviso de entorno ruidoso

Dos cosas cargan la GPU: el programa y todo lo demás. `device_pct` (contadores del controlador, toda la GPU) menos la parte
ocupada del propio programa (`100 × (1 - idle_share)`) es lo que usó «todo lo demás»; 20 puntos o más es
`noisy_environment: true` y añade `noisy_basis` con la cuenta y la parte de los otros procesos (`:565-581`, `:757-762`). El 20
es «provisional, no una medida: reajustar con al menos 3 corridas tranquilas del mismo Mac» (`:560-561`); una prueba dice que
el límite es inclusivo (`test_noisy_boundary_is_inclusive`, `tests/test_report.py:905`, no se ejecutó). A mano sobre las dos
corridas reales ([E7](./evidencia.md#e7)) la diferencia es -6.4 y 0.6 puntos: ninguna se marcaría. Los dos resúmenes reales
no tienen la clave: los escribió una versión anterior a que existiera (generación 1: sin `schema_version`, `tier` ni
`common`), así que no se sabe qué escribía esa versión para ella.

## Windows

`perf_record_windows.py` llama al mismo `frame_pacing` (`:489`) y `common_block` (`:917`), así que los FPS, mínimos, stutter y
jitter de un resumen de Windows siguen estas fórmulas, sobre los intervalos de PresentMon o las medias del log de drawstress.
Lo que no puede medir es `null`, no cero, y la fuente usada es `gpu.source` ([guía de
grabación](../grabar/motor-windows.md#las-tres-fuentes-de-fotogramas-y-cual-gana)).
