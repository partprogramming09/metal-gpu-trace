# Exportar un `.chrome-trace`

**Lector:** personas que quieren ver los fotogramas de una corrida en una línea de tiempo, o que cambian `tool_perf_export_trace`. Revisado el 2026-11-16.

English: [Exporting a `.chrome-trace`](../../../guides/reading-traces/chrome-trace.md)

> **En corto:** `perf_export_trace` convierte la tabla de fotogramas de una corrida en un archivo que abre Perfetto (un visor
> de líneas de tiempo gratuito). Cada fotograma es una barra, tan larga como lo que la GPU trabajó en él. No necesita `.trace`
> ni `xctrace`, solo la tabla por fotograma que toda corrida conserva. Vista tosca: una pista, sin encoders ni memoria.

`tool_perf_export_trace(run)` (`traces.py:9-30`) escribe JSON en el formato de eventos de traza de Chrome, que abren
`ui.perfetto.dev` y `chrome://tracing` (docstring, `traces.py:10-13`; los visores **no se abrieron**). Ejemplo resuelto con la
primera fila real: [índice](./index.md#un-ejemplo-primero).

## Cómo funciona, en orden

| # | Paso | Detalle | Línea |
|---|---|---|---|
| 1 | Comprobar la corrida | `paths.run_path(run)`: nombre válido, `<run>.json` existe, no es un enlace, no es `baselines.json`. Desconocida: `no run <name>; perf_runs lists them` | `traces.py:14`, `paths.py:33-41` |
| 2 | Encontrar la tabla | `table_files.find(config.OUT, f"{run}.frames")`: primero `<run>.frames.csv.gz`, después `.csv`, sin enlaces. Ninguna: `<run> has no per-frame file; record it again` | `traces.py:15`, `tables.py:13-20`, `:16-17` |
| 3 | Un **evento completo** por fila | `"ph": "X"` (una rebanada con inicio y largo), llamada `GPU frame`, proceso 1, hilo 1: `ts = start_ms × 1000`, `dur = gpu_ms_total × 1000` (microsegundos); `args` = número de fotograma más cada columna `gpu_ms_<canal>` salvo el total, sin el prefijo (`compute`, `fragment`, `vertex`) | `:22-25` |
| 4 | Tabla mala | ilegible, columna ausente o no numérico: `<file name> cannot be read; record it again`; no se escribe archivo parcial | `:26-27` |
| 5 | Escribir | `{"traceEvents": [...], "displayTimeUnit": "ms"}` en `<carpeta de corridas>/<run>.chrome-trace`; devuelve `{"file": "<run>.chrome-trace", "frames": <eventos>}`. `paths.write_file` reemplaza un archivo anterior y se niega a escribir a través de un enlace | `:28-30`, `paths.py:69-80` |

Las pistas dicen que es idempotente y no destructiva (`registry.py:129-131`): correrla dos veces escribe el mismo archivo.

## Qué muestra el archivo y qué no

| Aspecto | Qué pasa |
|---|---|
| **Una pista, una rebanada por fotograma** | Todo está en el proceso 1, hilo 1, así que una rebanada más larga que el hueco hasta el siguiente fotograma lo solapa; Perfetto las apila. El largo es la **suma** de los tres canales (`gpu_ms_total`), no el tiempo entre el primer y el último intervalo. El docstring dice que encoders en paralelo «can show shorter than it took», pero una suma de trabajo en paralelo es más larga, no más corta (F8, [límites](./limites.md)) |
| **Solo los fotogramas que el resumen conservó** | Los tramos dibujados pero no presentados quedan fuera de `frames.csv` (ver [Trabajo que nunca se presentó](../resumir-y-analizar/del-trace-al-resumen.md#trabajo-que-nunca-se-presento)), y de la línea de tiempo. La segunda corrida real tiene 153 fotogramas (E4) para 20 segundos |
| **Sin encoders, command buffers ni memoria** | La vista más fina es `trace_query` sobre los intervalos de GPU de un `.trace` guardado |
| **Una clase de retención propia** | La cuota de disco lo borra en segundo lugar, después de un `.trace` y antes de las tablas, pero la exportación de la corrida **actual** se queda (`retention.py:5-8`, `:30-43`; [guía de datos](../datos-y-su-ciclo-de-vida/index.md)). No crea una corrida: `perf_runs` no lo lista (`tests/test_analysis.py:333`, no corrido) |

Volver al [índice](./index.md).
