# `trace_query`: filas, páginas y ventanas

**Lector:** personas que leen las filas de una tabla de un `.trace` guardado o de su archivo de tablas, o que cambian `traces.py:92-114`. Revisado el 2026-11-16.

English: [`trace_query`](../../../guides/reading-traces/trace-query.md)

> **En corto:** `trace_query` te da una página de una tabla, 50 filas por defecto. Para una tabla demasiado larga, pide
> ventanas de tiempo: «cuántas filas y cuánto tiempo en cada 10 ms». Tres filas en 1 ms, 9 ms y 12 ms dan dos ventanas, con
> 2 filas y 1. Cada página vuelve a correr la exportación, así que las tablas grandes son lentas.

`tool_trace_query(trace, schema, offset=0, limit=50, pid=None, window_ms=None)` (`traces.py:92-114`), en orden:

| # | Paso | Detalle | Línea |
|---|---|---|---|
| 1 | `check_window` valida `window_ms` | `None` sigue siendo `None`; un decimal entero como `10.0` cuenta como `10`; un booleano, una fracción, `0`, un negativo o más de `3 600 000` da `window_ms is a whole number of milliseconds from 1 to 3600000` | `:42-51` |
| 2 | Nombre del esquema | solo letras, dígitos y `-` | `:98-99` |
| 3 | Exportar y leer | se exporta con el xpath de `:100` y lo lee `perf_report.rows` | `:100-101` |
| 4 | Filtro `pid` | `pid is None or "process" not in row or perf_report.pid_of(row["process"]) == int(pid)`: una tabla **sin** columna `process` se devuelve entera diga lo que diga `pid`, aunque la herramienta diga «keep only this process's rows» (F6) | `:102-103` |
| 5 | Filas (sin `window_ms`) | cada fila pasa a `{columna: valor}`, siendo el valor el texto `fmt` de la celda si lo tiene, si no su texto: como lo muestra Instruments. **Probable:** una columna de tiempo puede leerse `1.5 ms` cuando el texto crudo son nanosegundos, por eso las ventanas leen `.text` y no `fmt` (`:68`, `:79`). Luego `paths.page` corta una página | `:111-112` |
| 6 | Limpieza | el archivo que leyó `rows` se borra en un `finally`, también si el código de ventanas lanzó una excepción (`tests/test_traces.py:118-124`, no corrida) | `:113-114` |

## Paginación

> **Desde el archivo de tablas:** las filas también pueden venir de `<run>.tables.sqlite` cuando el `.trace` ya no está, y los
> argumentos `where`, `columns`, `order_by`, `descending`, `group_by` y `aggregates` filtran, ordenan y agrupan esas filas: ver
> [el archivo de tablas](./archivo-de-tablas.md). Los números de línea de arriba describen la ruta de exportación.

## Argumentos de filtro

| Argumento | Qué hace |
|---|---|
| `where` | lista de `{column, op, value}` unidos con Y; `op` es `=`, `!=`, `<`, `<=`, `>` o `>=`. Una columna de tiempo o de tamaño guarda su número como texto, así que se compara con un número |
| `columns` | deja solo esas columnas de cada fila |
| `order_by` | una columna; con `group_by`, el nombre de un agregado (`count`, `sum_duration`) |
| `descending` | con `order_by`, el mayor primero |
| `group_by` | agrupa las filas por esas columnas; cada grupo lleva su cuenta salvo que `aggregates` diga otra cosa |
| `aggregates` | lista de `{fn, column}`, con `fn` en `count`, `sum`, `avg`, `min` o `max`; cada uno se llama `fn_columna`, y `count` se llama `count` |

Estos argumentos leen el archivo de tablas aunque el `.trace` siga existiendo. Si el archivo no está (una corrida anterior a él,
o grabada con `PERF_TABLES=0`), la llamada falla y dice que hay que quitar los argumentos o grabar la corrida de nuevo.
`window_ms` solo se combina con `where` y `pid`: con cualquiera de los otros, la llamada falla con `window_ms combines only with
where and pid`. La paginación (`total`, `offset`, `rows`, `next_offset`) es la misma en todos los modos.

## Paginación

`paths.page(items, offset, limit)` (`paths.py:94-99`) fija `offset` en 0 o más y `limit` entre 1 y 500 (`config.MAX_LIMIT`,
`config.py:43`; esquema «default 50, at most 500», `registry.py:19`) y devuelve:

```text
{"total": <todas las filas>, "offset": <n>, "rows": [...], "next_offset": <n + len(rows), o null al final>}
```

`next_offset: null` dice al cliente que llegó al final. Todo sale de una **lista de todas las filas** (`:111-112` la construye,
`:94-99` la corta) y cada llamada exporta otra vez: un millón de filas en páginas de 500 corre la exportación 2000 veces. Sin
caché (**confirmado**); el coste de una exportación de una tabla grande **no se midió**. Si una exportación tarda más de 600 s,
la llamada termina con `subprocess.TimeoutExpired`, que el worker convierte en error (`worker.py:165-168`; tiempo límite en `perf_report.py:49`).

## Ventanas

Con `window_ms`, `windows_of(selected, window_ms)` (`traces.py:54-89`) reemplaza las filas:

| Regla | Comportamiento | Línea |
|---|---|---|
| La **primera fila decide la forma** | su columna de tiempo es `start` si existe, si no `time` (`TIME_COLUMNS`); hay columna de duración cuando la primera fila tiene `duration` | `:39`, `:62`, `:63` |
| Sin columna de tiempo | `window_ms needs a table with a time column (start or time); trace_tables lists the tables and trace_query without window_ms shows the columns` | `:64-66` |
| Qué ventana | el tiempo de una fila es `int(cell.text)` en nanosegundos; ventana = `ns // (window_ms × 1 000 000)` | `:68`, `:74` |
| Tiempo malo (no numérico, negativo, ausente) | se cuenta en `skipped_rows`, que la respuesta lleva solo cuando no es 0 | `:69-73`, `:108-109` |
| Una ventana | `{"start_ms": índice × window_ms, "count": N}` más `"duration_ms"` cuando la tabla tiene duración: la **suma** de las duraciones de sus filas en ms, redondeada a 3 decimales; una fila con duración ilegible cuenta pero no suma | `:75-87`, `:77-81` |
| Cuáles se listan | solo las ventanas con una fila, en orden de tiempo, paginadas como las filas; la respuesta lleva además `window_ms` | `:83-84`, `:107` |

Como las duraciones se suman, el trabajo en paralelo en una ventana puede superar la ventana: la misma salvedad que la
[suma de GPU por fotograma](../resumir-y-analizar/como-se-calculan-los-numeros.md#el-tiempo-de-gpu-por-fotograma-es-una-suma-sobre-canales).

Las doce pruebas de `tests/test_traces.py` anclan todo esto (ventanas de 10 ms, una columna `time` sin duración, rechazo de
cero, negativos y no numéricos, sin columna de tiempo, tabla vacía, filas sin tiempo utilizable, un decimal entero,
paginación, filtro por pid, borrado del archivo); **no se corrieron**. Evaluación a mano del ejemplo: E6 en [Evidencia](./evidencia.md).

Volver al [índice](./index.md).
