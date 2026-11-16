# Exportar un `.chrome-trace`

**Lector:** personas que quieren ver los fotogramas de una corrida en una línea de tiempo, o que cambian `tool_perf_export_trace`. Revisado el 2026-11-16.

English: [Exporting a `.chrome-trace`](../../../guides/reading-traces/chrome-trace.md)

> **En corto:** `perf_export_trace` convierte la tabla de fotogramas de una corrida en un archivo que abre Perfetto (un visor
> de líneas de tiempo gratuito). Cada fotograma es una barra: empieza cuando empezó el fotograma y mide lo que la GPU trabajó
> en él. No necesita `.trace` ni `xctrace`, solo la tabla por fotograma que toda corrida conserva. Es una vista tosca: una
> pista, sin encoders ni memoria.

`tool_perf_export_trace(run)` (`traces.py:9-30`) responde «muéstrame los fotogramas de esta corrida en una línea de tiempo». El
archivo es JSON en el formato de eventos de traza de Chrome, que abren `ui.perfetto.dev` y `chrome://tracing` (docstring,
`traces.py:10-13`; los visores **no se abrieron** para esta guía). El ejemplo resuelto, con la primera fila real, está en el
[índice](./index.md#un-ejemplo-primero).

## Cómo funciona, en orden

| # | Paso | Detalle | Línea |
|---|---|---|---|
| 1 | Comprobar la corrida | `paths.run_path(run)`: nombre válido, `<run>.json` existe, no es un enlace, no es `baselines.json`. Corrida desconocida: `no run <name>; perf_runs lists them` | `traces.py:14`, `paths.py:33-41` |
| 2 | Encontrar la tabla | `table_files.find(config.OUT, f"{run}.frames")`: primero `<run>.frames.csv.gz`, después `.csv`, sin enlaces. Ninguna: `<run> has no per-frame file; record it again` | `traces.py:15`, `tables.py:13-20`, `:16-17` |
| 3 | Un **evento completo** por fila | `"ph": "X"` (una rebanada con inicio y largo), llamada `GPU frame`, proceso 1, hilo 1: `ts = start_ms × 1000`, `dur = gpu_ms_total × 1000` (microsegundos); `args` = el número de fotograma más cada columna `gpu_ms_<canal>` salvo el total, sin el prefijo (`compute`, `fragment`, `vertex`) | `:22-25` |
| 4 | Tabla mala | ilegible, una columna ausente o un no numérico: `<file name> cannot be read; record it again`; no se escribe ningún archivo parcial | `:26-27` |
| 5 | Escribir | `{"traceEvents": [...], "displayTimeUnit": "ms"}` en `<carpeta de corridas>/<run>.chrome-trace`; devuelve `{"file": "<run>.chrome-trace", "frames": <eventos>}`. `paths.write_file` reemplaza un archivo anterior con ese nombre y se niega a escribir a través de un enlace | `:28-30`, `paths.py:69-80` |

Las pistas de la herramienta dicen que es idempotente y no destructiva (`registry.py:129-131`): correrla dos veces escribe el
mismo archivo.

## Qué muestra el archivo y qué no

| Aspecto | Qué pasa |
|---|---|
| **Una pista, una rebanada por fotograma** | Todo está en el proceso 1 e hilo 1, así que un fotograma cuya rebanada es más larga que el hueco hasta el siguiente lo solapa; Perfetto las apila. El largo es el tiempo de GPU, la **suma** de los tres canales (`gpu_ms_total`), no el tiempo entre el primer y el último intervalo. El docstring dice que un fotograma con encoders en paralelo «can show shorter than it took», pero una suma de trabajo en paralelo es más larga que el tiempo transcurrido, no más corta (hallazgo F8, [límites](./limites.md)) |
| **Solo los fotogramas que el resumen conservó** | Un tramo donde el programa dibujó pero no presentó queda fuera de `frames.csv` (ver [Trabajo que nunca se presentó](../resumir-y-analizar/del-trace-al-resumen.md#trabajo-que-nunca-se-presento)), y por tanto fuera de la línea de tiempo. La segunda corrida real del clon tiene 153 fotogramas (E4) para 20 segundos de grabación |
| **Sin encoders, sin command buffers, sin memoria** | Una pista tosca; la vista más fina es `trace_query` sobre los intervalos de GPU de un `.trace` guardado |
| **Una clase de retención propia** | Un `.chrome-trace` es lo segundo que borra la cuota de disco, después de un `.trace` y antes de las tablas, salvo que la exportación de la corrida **actual** se queda (`retention.py:5-8`, `:30-43`; el orden completo en la [guía de datos](../datos-y-su-ciclo-de-vida/index.md)). No crea una corrida nueva: `perf_runs` no lo lista (`tests/test_analysis.py:333`, no corrido) |

Volver al [índice](./index.md).
