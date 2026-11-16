# `trace_query`: filas, páginas y ventanas

**Lector:** personas que leen las filas de una tabla de un `.trace` guardado, o que cambian `traces.py:92-114`. Revisado el 2026-11-16.

English: [`trace_query`](../../../guides/reading-traces/trace-query.md)

> **En corto:** `trace_query` te da una página de una tabla, 50 filas por defecto. Para una tabla demasiado larga para leerla,
> pídele ventanas de tiempo: «cuántas filas y cuánto tiempo en cada 10 ms». Ejemplo: tres filas en 1 ms, 9 ms y 12 ms dan dos
> ventanas, la primera con 2 filas y la segunda con 1. Cada página vuelve a correr la exportación, así que las tablas grandes
> son lentas.

`tool_trace_query(trace, schema, offset=0, limit=50, pid=None, window_ms=None)` (`traces.py:92-114`) devuelve una página de una
tabla. En orden:

| # | Paso | Detalle | Línea |
|---|---|---|---|
| 1 | `check_window` valida `window_ms` | `None` sigue siendo `None`; un decimal entero como `10.0` cuenta como `10`; un booleano, una fracción, `0`, un negativo o más de `3 600 000` da `window_ms is a whole number of milliseconds from 1 to 3600000` | `:42-51` |
| 2 | El nombre del esquema | solo letras, dígitos y `-` | `:98-99` |
| 3 | Exportar y leer | la tabla se exporta con el xpath de `:100` y la lee `perf_report.rows` | `:100-101` |
| 4 | Filtro `pid` | `pid is None or "process" not in row or perf_report.pid_of(row["process"]) == int(pid)`: una tabla **sin** columna `process` se devuelve entera diga lo que diga `pid`, aunque la herramienta diga «keep only this process's rows» (hallazgo F6) | `:102-103` |
| 5 | Filas (sin `window_ms`) | cada fila pasa a `{columna: valor}`, siendo el valor el texto `fmt` de la celda si lo tiene, si no su texto: el valor como lo muestra Instruments. **Probable:** una columna de tiempo puede leerse como `1.5 ms` cuando el texto crudo son nanosegundos, por eso las ventanas leen `.text` y no `fmt` (`:68`, `:79`). Luego se corta en una página con `paths.page` | `:111-112` |
| 6 | Limpieza | el archivo que leyó `rows` se borra en un `finally`, también si el código de ventanas lanzó una excepción (prueba: `tests/test_traces.py:118-124`, no corrida) | `:113-114` |

## Paginación

`paths.page(items, offset, limit)` (`paths.py:94-99`) fija `offset` en 0 o más y `limit` entre 1 y 500 (`config.MAX_LIMIT`,
`config.py:43`; el esquema dice «default 50, at most 500», `registry.py:19`) y devuelve:

```text
{"total": <todas las filas>, "offset": <n>, "rows": [...], "next_offset": <n + len(rows), o null al final>}
```

`next_offset: null` es como un cliente sabe que llegó al final. Todo se calcula desde una **lista de todas las filas** (`:111-112`
la construye, `:94-99` la corta) y cada llamada exporta la tabla otra vez: una tabla de un millón de filas en páginas de 500
corre la exportación 2000 veces. El código no tiene caché (**confirmado**); el coste de una exportación de una tabla grande
**no se midió**. Si una exportación tarda más de 600 s, la llamada termina con `subprocess.TimeoutExpired`, que el worker
convierte en un resultado de error (`worker.py:165-168`; el tiempo límite es `perf_report.py:49`).

## Ventanas

Con `window_ms`, `windows_of(selected, window_ms)` (`traces.py:54-89`) reemplaza las filas:

| Regla | Comportamiento | Línea |
|---|---|---|
| La **primera fila decide la forma** | su columna de tiempo es `start` si existe, si no `time` (`TIME_COLUMNS`); la tabla tiene columna de duración cuando la primera fila tiene `duration` | `:39`, `:62`, `:63` |
| Sin columna de tiempo | `window_ms needs a table with a time column (start or time); trace_tables lists the tables and trace_query without window_ms shows the columns` | `:64-66` |
| Qué ventana | el tiempo de una fila es `int(cell.text)` en nanosegundos; ventana = `ns // (window_ms × 1 000 000)` | `:68`, `:74` |
| Tiempo malo (no numérico, negativo, ausente) | se cuenta en `skipped_rows`; la respuesta lleva `skipped_rows` solo cuando no es 0 | `:69-73`, `:108-109` |
| Una ventana | `{"start_ms": índice × window_ms, "count": N}` más `"duration_ms"` cuando la tabla tiene duración: la **suma** de las duraciones de sus filas en ms, redondeada a 3 decimales; una fila cuya duración no se puede leer cuenta igual pero no suma nada | `:75-87`, `:77-81` |
| Cuáles se listan | solo las ventanas que tienen una fila, en orden de tiempo; se paginan como las filas y la respuesta lleva además `window_ms` | `:83-84`, `:107` |

Como las duraciones se suman, la suma de trabajo en paralelo en una ventana puede ser mayor que la ventana: la misma
salvedad que la [suma de GPU por fotograma](../resumir-y-analizar/como-se-calculan-los-numeros.md#el-tiempo-de-gpu-por-fotograma-es-una-suma-sobre-canales).

Las doce pruebas de `tests/test_traces.py` anclan todo esto: ventanas de 10 ms, una columna `time` sin duración, rechazo de
cero, negativos y no numéricos, una tabla sin columna de tiempo, una tabla vacía, filas sin tiempo utilizable, un decimal
entero, paginación, el filtro por pid y el borrado del archivo. **No se corrieron** para esta guía. La evaluación a mano del
ejemplo de ventanas es E6 en [Evidencia](./evidencia.md).

Volver al [índice](./index.md).
