# Límites conocidos

**Lector:** personas que quieren saber dónde es débil esta parte del proyecto, o que van a fiarse de un número que depende de uno de estos límites. Revisado el 2026-11-16.

English: [Known limits](../../../guides/summarizing/limits.md)

**En corto:** esta página lista 13 sitios donde el comportamiento de hoy sorprende o no está probado, y lo que no se pudo
ejecutar para la guía. Están anotados, no arreglados. Cada uno lleva un estado: confirmado por el código, probable o no verificado.

Volver al [índice de la guía](./index.md).

| # | Límite | Dónde | Estado |
|---|---|---|---|
| 1 | Los dos resúmenes reales son de generación 1: no tienen `schema_version`, `tier`, `common` ni `noisy_environment`, así que la guía recalculó con las fórmulas de hoy y la coincidencia ([E3](./evidencia.md#e3)) comprueba esas fórmulas sobre datos viejos, no lo que hacía la versión que los escribió | `perf-runs/` (local, no publicada) | Confirmado |
| 2 | El mensaje amable para un trazo sin `metal-gpu-intervals` puede ser inalcanzable: `toc_and_tables` toma la exportación de una tabla obligatoria con `future.result()`, y el propio comentario del código dice «xctrace fails on a table that is not there», así que el fallo sería primero el genérico `xctrace export ... failed`; el `ValueError` solo se alcanza si la exportación tiene éxito sobre una tabla ausente. `tests/test_report.py:128-135` prueba `missing_tables` directamente | `perf_report.py:98-99`, `:116-117`, `:194-196` | Probable: no reproducido (sin trazo) |
| 3 | `missing_tables` lista `metal-current-allocated-size` y `gpu-performance-state-intervals` como si fueran opcionales, pero solo la primera puede faltar sin fallar (se omite con `--no-memory`); un trazo sin la segunda con toda probabilidad rompe la exportación, así que el nombre nunca llegaría al resumen | `perf_report.py:190-197` contra `:95-123` | Probable |
| 4 | `export` no captura un `subprocess.TimeoutExpired` (600 s por tabla, 3600 para los valores de contadores), y `main` solo captura `ValueError`, `FileNotFoundError` y `RuntimeError`: una exportación lenta acaba en un traceback, que lleva la línea de comandos, y el XML temporal que `export` creó no se borra por ese camino (el `finally` de `summarize` solo quita los archivos ya devueltos). Una tabla cortada a mitad de fila (un `ET.ParseError` que `complete_xml` no perdona) acaba igual | `perf_report.py:55-59`, `:166-168`, `:850` | Confirmado por el código; no reproducido |
| 5 | `command_buffer_errors` cuenta cada fila de su tabla, no solo las del programa; las tablas de asignaciones y de spills se filtran por el pid del programa | `perf_report.py:805-806` contra `:457-522` | Confirmado por el código |
| 6 | `stutter_rate_pct` salta los intervalos que cruzan un fotograma sin presentar; `hitches` y `steady_summary` arman sus intervalos con los inicios de fotograma que quedan, así que cuentan un intervalo así y el stutter no, y `hitches.count` puede superar la cuenta de stutter | `perf_report.py:243-244`, `:706`, `:822` contra `analysis.py:568` | Probable: el atasco de la segunda corrida real está al final, así que no lo muestra |
| 7 | `perf_ab`, `perf_sweep` y `perf_cold_warm` no informan `unpresented` ni `noisy_environment` de las corridas que graban (solo `too_short`); `perf_baseline` sí | `experiments.py:202-222`, `:187`, `:72-87` contra `analysis.py:288-292` | Confirmado |
| 8 | `perf_check` usa un `margin_pct` fijo (3) y no lee el `spread_pct` de la línea base; una referencia de una corrida tiene spread 0, y una caída de FPS del 3.1 % se lee `regressed` | `analysis.py:317-330`, `:310-314` | Confirmado ([E6](./evidencia.md#e6)) |
| 9 | El 1 % low es el percentil del intervalo, no la media del 1 % más lento; si eso coincide con otras herramientas no está verificado | `perf_report.py:262-266` | No verificado |
| 10 | Un aviso de throttling se sobrescribe con «cualquier intervalo térmico distinto de Nominal» siempre que exista la tabla térmica, haya caído o no el FPS | `perf_report.py:819-820` | Confirmado |
| 11 | `perf_diagnose` escribe sus recomendaciones en español, todo lo demás está en inglés | `analysis.py:756-807` | Confirmado (cosmético) |
| 12 | El margen del 3 %, el umbral de ruido de 20 puntos, el suelo de 8 ms y los umbrales de ocio de 25 %, 20 %, 15 % son decisiones del proyecto, algunas marcadas «provisional» en el código; ninguna se volvió a medir aquí | `analysis.py:325`, `:746-748`; `perf_report.py:250`, `:562` | No verificado |
| 13 | Dos corridas reales prueban las fórmulas sobre resúmenes de un programa en un Mac; los números de un resumen de Windows (PresentMon, el log) no se recalcularon | | No reproducido |

## Lo que no se reprodujo

Además de los dos límites de toda la guía ([índice](./index.md#como-leer-las-etiquetas)): un resumen con `missing_tables` no vacío, un trazo sin `metal-gpu-intervals`, una tabla cortada a mitad de fila, una exportación que agota el tiempo, el recálculo de un resumen de Windows y los números de la 0.27.2 (los dos resúmenes reales son de generación 1 y anteriores al código descrito). Una línea base real, A B B A y un barrido piden de 4 a 24 grabaciones.
