# Cuando falla

**Lector:** personas que ven un error de una de estas herramientas y quieren saber qué significa, o que cambian un texto de error. Revisado el 2026-11-16.

English: [When it fails](../../../guides/reading-traces/when-it-fails.md)

> **En corto:** cuando algo sale mal el servidor no se detiene: recibes una frase que dice qué pasó y, casi siempre, qué hacer.
> La más común es «no recording at ...»: la grabación se borró tras escribir su resumen; volver a grabar con `KEEP_TRACE=1` la conserva.

Todas las herramientas de esta guía corren dentro de `worker.call`, que convierte `ToolError`, `FileNotFoundError`,
`ValueError`, `RuntimeError` y `subprocess.TimeoutExpired` en un resultado `isError: true` cuyo texto es el mensaje
(`worker.py:165-166`); cualquier otra excepción pasa a `internal error: <ExceptionType>` (`:167-168`). Un resultado de más de
40 000 caracteres (una captura con muchísimos grupos de depuración, una página de filas anchas) se rechaza con
`the result has N characters; ask for a smaller page with limit` (`worker.py:162-163`, `config.py:45`).

| Qué sale mal | Qué recibe el lector | Línea |
|---|---|---|
| El `.trace` no está (borrado tras el resumen) | `no recording at <name>: perf_record.sh deletes the .trace once its summary is written, unless KEEP_TRACE=1` | `perf_report.py:52-54` |
| Una ruta de `trace` o de captura fuera de las carpetas legibles | `<name> is outside the readable directories; add its directory to METAL_TRACE_READ` | `paths.py:20-21` |
| El `.trace` de un nombre es un enlace | `<name>.trace cannot be read` | `paths.py:88-89` |
| `xctrace` falla en una exportación | `xctrace export of <name> failed (exit N): <última línea de su error>`; una tabla cortada por el fallo `SIGTRAP` conocido en un límite de fila se acepta | `perf_report.py:62-65`, `:60-61` |
| Una exportación tarda más de 600 s | el worker informa el `TimeoutExpired`; en `trace_count` la tabla recibe `rows: None` y las demás continúan | `perf_report.py:49`, `traces.py:144-146`, `worker.py:165` |
| `schema` o el nombre de una tabla contada tiene un carácter raro | `schema holds only letters, digits and '-'; trace_tables lists them` / `a table name holds only letters, digits and '-'; ...` | `traces.py:98-99`, `:131-132` |
| La tabla no existe en la traza (`trace_query`) | la exportación falla: **probable** `xctrace export ... failed`; `trace_count` dice `not in this trace` | `traces.py:100-101`, `:133-135` |
| `window_ms` no es un entero de 1 a 3 600 000 / la tabla no tiene `start` ni `time` / algunas filas no tienen tiempo utilizable | `window_ms is a whole number of milliseconds from 1 to 3600000` / `window_ms needs a table with a time column (start or time); trace_tables lists the tables and trace_query without window_ms shows the columns` / no es un error: filas contadas en `skipped_rows` | `traces.py:50`, `:64-66`, `:69-73`, `:108-109` |
| `perf_export_trace`: corrida desconocida / sin tabla por fotograma / tabla dañada (una celda no es número, falta una columna, un gzip malo) | `no run <name>; perf_runs lists them` / `<run> has no per-frame file; record it again` / `<file name> cannot be read; record it again`, no se escribe nada | `paths.py:33-41`, `traces.py:16-17`, `:26-27` |
| El paquete no tiene archivo `capture` (resumen, diff) / un registro tiene tamaño menor que 8 o se sale del final | `FileNotFoundError: <bundle name> has no capture file`, sin carpeta / `ValueError: <bundle name>: record at 0x<off> has size <n>; the stream is not MTSP as expected` | `gputrace_read.py:67-68`, `:54-55` |
| `capture_records` en un paquete sin archivo `capture`, o en una ruta que es un archivo | **probable:** el `OSError` crudo de `read_bytes` (F1) | `traces.py:173`, `gputrace_read.py:50` |

Nada se **reprodujo**: los textos se leen del código, y los de captura los anclan `tests/test_capture.py:86-97`, `:103-112`,
`:115-132` y `:170-178` (no corridas).

Volver al [índice](./index.md).
