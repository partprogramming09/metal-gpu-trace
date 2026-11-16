# Límites conocidos y hallazgos nuevos

**Lector:** el responsable del proyecto y quien decida qué arreglar en `traces.py` o `gputrace_read.py`. Revisado el 2026-11-16.

English: [Known limits and new findings](../../../guides/reading-traces/limits.md)

> **En corto:** esta página lista lo que estas herramientas no pueden hacer hoy (límites) y lo que parecía mal mientras se
> escribía la guía (hallazgos). Nada de esto se arregló: cada punto es algo que el código hace ahora, anotado para que el
> responsable decida. El mayor: nunca se leyó una captura real, así que el formato de captura es lo que afirma el propio código.

## Límites conocidos

Cada punto es un límite del comportamiento de hoy, anotado, no arreglado aquí.

| # | Límite | Dónde | Estado |
|---|---|---|---|
| 1 | El repositorio no tiene ningún `.trace` ni `.gputrace` real: ninguna herramienta de esta guía se ejecutó, y la única prueba publicada de `capture_diff` es sobre flujos sintéticos | E3, `docs/evidence/v0.26.0.md` | No reproducido |
| 2 | Los ids de llamada y la disposición de un `.gputrace` son lo que afirma el código; la investigación del 2026-11-15 dice que no había ninguna captura real, y el código dice que sus ids salen de una | `gputrace_read.py:7-8`, `:19` | Contradicción, ver F5 |
| 3 | `capture_diff` cuenta solo 17 ids confirmados; un cambio en dibujos indexados, indirectos o de malla, o en encoders, le es invisible | `gputrace_read.py:20-45`, `:117` | Confirmado |
| 4 | Cada página de `trace_query` y `trace_count` vuelve a correr `xctrace export`, y una página se corta de una lista de todas las filas en memoria | `traces.py:101`, `:111-112` | Confirmado; coste no medido |
| 5 | Una tabla se lee solo de la **primera corrida** de la traza (`run[@number="1"]`) | `traces.py:100`, `perf_report.py:92` | Confirmado |
| 6 | Un `.trace` se puede leer solo mientras exista: tras una grabación normal se borra, y `trace_query` lo dice | `perf_report.py:52-54` | Confirmado |
| 7 | `perf_export_trace` tiene una rebanada por fotograma en una pista, y omite los fotogramas que el resumen omitió | `traces.py:19-25` | Confirmado |
| 8 | El tamaño de página tiene dos valores por defecto: `registry.py:19` dice «default 50» para toda herramienta paginada, pero `capture_records` tiene `limit=100` | `traces.py:169`, `registry.py:19`, `:177` | Confirmado |
| 9 | El resumen de una captura con muchos grupos de depuración no tiene `limit`, así que puede pasar el tope de 40 000 caracteres sin forma de pedir menos | `traces.py:151-157`, `worker.py:162-163` | Probable (F2) |
| 10 | La unidad de una celda de tiempo en las páginas de `trace_query` (el texto que muestra Instruments) puede diferir de los nanosegundos que usan las ventanas | `traces.py:68`, `:111` | Probable |
| 11 | No se midieron los tamaños de un archivo `capture` real ni la duración de una exportación de una tabla real | | No reproducido |

## Hallazgos nuevos en el código (sin arreglar)

Encontrados al escribir esta guía. Cada uno es algo que el código hace hoy; ninguno es una decisión.

| # | Hallazgo | Dónde | Estado |
|---|---|---|---|
| F1 | `capture_records` abre `<capture>/capture` por su cuenta y no pasa por `stream_of`, así que un paquete sin archivo `capture` lanza el `OSError` de `read_bytes`, cuyo texto lleva la **ruta completa**, y una ruta que es un archivo lanza `NotADirectoryError`, un `OSError` que no es `FileNotFoundError` y por eso se informa como `internal error: NotADirectoryError`. El changelog dice que los errores de `capture_records` ya no incluyen la carpeta, y las pruebas cubren solo `summarize` y `diff` | `traces.py:173`, `gputrace_read.py:50` y `:64-69`, `CHANGELOG.md` (la entrada de `capture_diff` de la 0.26.0) | Probable (código leído, no ejecutado) |
| F2 | `capture_summary` no tiene `limit` y `debug_groups` y `signposts` no tienen tope, así que una captura con miles de grupos con etiqueta puede producir un resultado de más de 40 000 caracteres, y el error le dice a quien llama que pida una página menor con `limit`, que esta herramienta no tiene | `gputrace_read.py:90-91`, `traces.py:151-157`, `registry.py:172`, `worker.py:162-163` | Probable |
| F3 | `command_buffers` y `render_encoders` del resumen salen de ids `probable` y la respuesta no los marca como tales | `gputrace_read.py:86-87`, `:38-40` | Confirmado |
| F4 | `capture_summary` no corta nada y `counts` corta una etiqueta a 200 caracteres, así que la misma etiqueta puede verse distinta en el resumen (`debug_groups`) y en el diff (`groups[].name`) | `gputrace_read.py:81`, `:111` | Confirmado |
| F5 | El módulo dice que sus ids se emparejaron con una captura cuya lista de comandos mostró Xcode en macOS 27.0.1; la prueba de la 0.26.0 y la investigación del 2026-11-15 dicen que no había ninguna captura real. Cuál es cierta decide qué significa «confirmado» | `gputrace_read.py:7-8`, `:19`; `docs/evidence/v0.26.0.md`; la nota de investigación del 2026-11-15 | Contradicción, necesita al responsable |
| F6 | `trace_query` con `pid` devuelve todas las filas de una tabla sin columna `process`, mientras la herramienta dice «keep only this process's rows» | `traces.py:102-103`, `registry.py:167` | Confirmado |
| F7 | `trace_query` construye la lista completa de filas antes de cortar una página, así que una tabla de millones de filas se tiene en memoria en cada llamada | `traces.py:111-112` | Confirmado; tamaño no medido |
| F8 | El docstring de `perf_export_trace` dice que un fotograma con encoders en paralelo «can show shorter than it took»; el largo es una suma (`gpu_ms_total`), que en trabajo paralelo es mayor que el tiempo transcurrido, como dice la [guía de resumen](../resumir-y-analizar/como-se-calculan-los-numeros.md#el-tiempo-de-gpu-por-fotograma-es-una-suma-sobre-canales) | `traces.py:10-13` | Probable (redacción) |
| F9 | `records` ignora en silencio menos de 8 bytes finales, y un archivo que no empieza por `MTSP` se interpreta desde el byte 0 en vez de rechazarse | `gputrace_read.py:51-52` | Confirmado |
| F10 | `trace_count` devuelve los nombres de todos los procesos de la traza (`by_process`), no solo los del programa | `traces.py:142` | Confirmado |

Volver al [índice](./index.md).
