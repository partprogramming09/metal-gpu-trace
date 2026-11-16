# Evidencia: los comandos y su salida real

**Lector:** personas que quieren comprobar un número de esta guía, y el responsable del proyecto. Revisado el 2026-11-16.

English: [Evidence](../../../guides/reading-traces/evidence.md)

> **En corto:** cada número de esta guía sale de un comando que se muestra aquí con su salida real. Todos los comandos solo
> leen. Como el repositorio no tiene ninguna grabación que abrir y no se pudo correr Python, **ninguna herramienta de esta
> guía se ejecutó**; donde se muestra el resultado de una herramienta, se calculó a mano con la fórmula del código sobre una
> corrida real.

## Tres límites del método

1. El repositorio **no tiene ningún `.trace`, ningún `.chrome-trace` ni ningún `.gputrace`** (E3), y leer un `.trace` exige
   `xctrace`, así que ninguna herramienta `trace_*` se ejecutó.
2. La sesión que escribió la guía podía correr comandos de solo lectura (`rg`, `sed`, `awk`, `jq`, `wc`, `find`) y no podía
   correr Python, `xctrace` ni `xxd`, así que tampoco se ejecutó ninguna herramienta de `traces.py` ni de `gputrace_read.py`:
   lo que devuelven se lee del código, se evalúa a mano sobre las dos corridas reales del clon donde hace falta una corrida, y
   se ancla en pruebas que se nombran y no se corrieron.
3. Ninguna captura `.gputrace` real se ha examinado para esta guía ni para la prueba publicada del proyecto (ver
   [el formato](./formato-gputrace.md)), así que toda afirmación sobre el formato es afirmación del propio código.

Recogido el 2026-11-16 en un Mac con Apple silicon. La carpeta de corridas es `perf-runs/` del clon (una carpeta local e
ignorada, no publicada; tiene dos corridas terminadas y sus tablas). E5 y E6 son las fórmulas del código evaluadas a mano.

## E1 Dónde se registra cada herramienta

```text
$ rg -n '"(perf_export_trace|trace_tables|trace_count|trace_query|capture_summary|capture_diff|capture_records)":' src/metal_gpu_trace/registry.py | cut -c1-90
129:    "perf_export_trace": (traces.tool_perf_export_trace, schema(
159:    "trace_tables": (traces.tool_trace_tables, schema({"trace": TRACE}, ["trace"]), hi
160:    "trace_count": (traces.tool_trace_count, schema(
165:    "trace_query": (traces.tool_trace_query, schema(
172:    "capture_summary": (traces.tool_capture_summary, schema({"capture": CAPTURE}, ["ca
173:    "capture_diff": (traces.tool_capture_diff, schema(
177:    "capture_records": (traces.tool_capture_records, schema({"capture": CAPTURE, **PAG
```

## E2 Cuántos ids de llamada son confirmados y cuántos probables

```text
$ rg -c '"confirmado"\)' src/metal_gpu_trace/gputrace_read.py
17
$ rg -c '"probable"\)' src/metal_gpu_trace/gputrace_read.py
7
$ rg -n 'probable' src/metal_gpu_trace/gputrace_read.py | cut -c1-110
38:    -16353: ("renderCommandEncoder", "probable"),
39:    -16246: ("endEncoding", "probable"),
40:    -16343: ("commandBuffer", "probable"),
41:    -10240: ("buffer contents", "probable"),
42:    -15416: ("drawMeshThreadgroups", "probable"),
43:    -15415: ("drawMeshThreadgroupsWithIndirectBuffer", "probable"),
44:    -16327: ("dispatchThreadgroups", "probable"),
```

17 + 7 = 24 ids, el número que usa la guía. Los 17 son los tres marcadores de depuración, `drawPrimitives` y las trece
llamadas de estado.

## E3 El repositorio no tiene ninguna traza ni captura que leer

```text
$ find . -name '*.gputrace' -not -path './node_modules/*' -not -path './.git/*' | wc -l
       0
$ find . \( -name '*.trace' -o -name '*.chrome-trace' \) -not -path './node_modules/*' -not -path './.git/*' | wc -l
       0
```

Las pruebas construyen las suyas: `tests/test_capture.py:18-27` escribe una carpeta `.gputrace` con un archivo `capture` de
`MTSP`, 4 bytes en cero y registros, y `tests/test_traces.py:11-16` escribe una tabla XML. Ninguna es un archivo del
repositorio.

## E4 Las tablas por fotograma de las dos corridas reales

```text
$ head -2 perf-runs/a2-proof-first_20261115-085621.frames.csv
frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total
6,1267.79,0.0243,1.7417,11.7952,13.5612
$ wc -l perf-runs/a2-proof-first_20261115-085621.frames.csv perf-runs/a2-proof-second_20261115-085735.frames.csv
    2046 perf-runs/a2-proof-first_20261115-085621.frames.csv
     154 perf-runs/a2-proof-second_20261115-085735.frames.csv
    2200 total
```

Con la cabecera incluida, la primera corrida tiene 2045 fotogramas y la segunda 153: los mismos números que en la
[guía de resumen](../resumir-y-analizar/index.md) (la segunda corrida dejó de presentar a los 3.6 s). Las dos
tablas son `.csv` planos, de antes de la compresión de la 0.27.0; `tables.find` lee cualquiera de los dos formatos.

## E5 `perf_export_trace` sobre la primera fila, a mano

```text
$ sed -n 2p perf-runs/a2-proof-first_20261115-085621.frames.csv | awk -F, '{printf "{\"name\":\"GPU frame\",\"ph\":\"X\",\"pid\":1,\"tid\":1,\"ts\":%s,\"dur\":%s,\"args\":{\"frame\":%d,\"compute\":%s,\"fragment\":%s,\"vertex\":%s}}\n",$2*1000,$6*1000,$1,$3,$4,$5}'
{"name":"GPU frame","ph":"X","pid":1,"tid":1,"ts":1267790,"dur":13561.2,"args":{"frame":6,"compute":0.0243,"fragment":1.7417,"vertex":11.7952}}
```

Es `awk` haciendo la aritmética de `traces.py:22-25` (`start_ms × 1000`, `gpu_ms_total × 1000`, el prefijo `gpu_ms_` quitado),
no la herramienta. El resultado en coma flotante de Python puede diferir en los últimos dígitos (por ejemplo `13561.2` frente
a `13561.199999999999`); **no reproducido** con la herramienta. La misma aritmética la afirma para una tabla de dos filas
`tests/test_analysis.py:329-332` (`ts == 10500.0`, `dur == 600.0`), no corrida. La suma 0.0243 + 1.7417 + 11.7952 es 13.5612,
el `gpu_ms_total` de la fila.

## E6 Las ventanas de `trace_query`, a mano

Tres filas con `start` y `duration` en ns: (1 000 000, 2 000 000), (9 000 000, 1 000 000), (12 000 000, 4 000 000), y
`window_ms=10`. Una ventana es `start // 10 000 000`:

```text
1 000 000 // 10 000 000 = 0     9 000 000 // 10 000 000 = 0     12 000 000 // 10 000 000 = 1
window 0: start_ms 0 x 10 = 0,   count 2, duration (2 000 000 + 1 000 000) / 1 000 000 = 3.0 ms
window 1: start_ms 1 x 10 = 10,  count 1, duration 4 000 000 / 1 000 000 = 4.0 ms
```

Son las filas y la respuesta que afirma `tests/test_traces.py:42-48`
(`[{"start_ms": 0, "count": 2, "duration_ms": 3.0}, {"start_ms": 10, "count": 1, "duration_ms": 4.0}]`), no corrida; las sumas
de arriba son las fórmulas de `traces.py:74-87` evaluadas a mano.

## E7 Los límites y los datos de familias de GPU que el código impone

```text
$ rg -n 'MAX_LIMIT|MAX_TEXT' src/metal_gpu_trace/config.py src/metal_gpu_trace/worker.py src/metal_gpu_trace/registry.py | cut -c1-140
src/metal_gpu_trace/registry.py:19:        "limit": {**I, "description": f"rows per page, default 50, at most {config.MAX_LIMIT}"}}
src/metal_gpu_trace/config.py:43:MAX_LIMIT = 500
src/metal_gpu_trace/config.py:45:MAX_TEXT = 40_000
src/metal_gpu_trace/worker.py:162:        if len(text) > config.MAX_TEXT:
$ jq -r '.families|keys|join(",")' src/metal_gpu_trace/data/apple-gpu-families.json
Apple10,Apple7,Apple8,Apple9
```

## E8 Lo que guardó una grabación real (una medida del 2026-11-15, no repetida)

La nota de investigación del proyecto del 2026-11-15 (interna, no publicada) registra, para una grabación de 8 segundos del
programa de prueba `drawstress` en el nivel `deep`, hecha con `xctrace` 27.2 en un Apple M1 Pro bajo macOS 27.0.1 y 170 MB en
disco: **85 tablas exportadas, 59 con filas y 26 vacías**, y, para la tabla de intervalos de GPU, el reparto de su duración
sumada por proceso. Los procesos más activos fueron el programa bajo prueba y, detrás, otros programas de la máquina (un
ayudante de navegador y el servidor de ventanas): la razón de [los nombres en `by_process`](./tablas-y-conteo.md). Esos números
**no se volvieron a medir** para esta guía; la grabación no está en el clon.

## Qué no se reprodujo

- Cualquier llamada a `xctrace`, y por tanto `trace_tables`, `trace_count` y `trace_query` sobre un `.trace` real (no había `.trace`, E3).
- Cualquier herramienta de `traces.py` o `gputrace_read.py`: la sesión que escribió esta guía no pudo correr Python.
- Un volcado hexadecimal de un registro de un `.gputrace` real, o de uno sintético (no se pudo correr `xxd`): la disposición es la del código.
- Abrir un `.chrome-trace` en Perfetto o `chrome://tracing`.
- Las pruebas nombradas en esta guía (se leyeron, no se corrieron).
- El coste de una `xctrace export` de una tabla grande, y el tamaño de un archivo `capture` real.

Volver al [índice](./index.md).
