# Las herramientas de captura

**Lector:** personas que leen o comparan capturas `.gputrace` con el servidor, o que cambian `tool_capture_*`. Revisado el 2026-11-16.

English: [The capture tools](../../../guides/reading-traces/capture-tools.md)

> **En corto:** tres herramientas leen una captura Metal. `capture_summary` cuenta lo que hay en una (cuántos dibujos, qué
> grupos con nombre). `capture_diff` compara dos y dice qué se añadió o quitó, como «ahora 5 dibujos, antes 3», emparejando
> los grupos por su nombre. `capture_records` muestra las entradas en bruto, para comprobar a las otras dos. Ninguna dice
> cuánto tardó nada.

El formato y los ids de llamada están en [el formato `.gputrace`](./formato-gputrace.md); lee su primera sección antes de
fiarte de cualquier número de aquí.

## `capture_summary`

`tool_capture_summary(capture)` (`traces.py:151-157`) resuelve la ruta con `paths.allowed` (solo carpetas legibles) y llama a
`gputrace_read.summarize` (`:72-97`), que lee cada registro una vez y devuelve:

| Clave | Qué es |
|---|---|
| `capture` | el nombre del paquete, nunca su ruta |
| `records` | cuántos registros tiene el flujo |
| `command_buffers` | registros con id -16343 (`commandBuffer`) |
| `render_encoders` | registros con id -16353 (`renderCommandEncoder`) |
| `draw_primitives` | registros con id -16218; los dibujos indexados, de malla e indirectos tienen otros ids y **no** se cuentan (`:88-89`) |
| `debug_groups` | las etiquetas de los registros `pushDebugGroup`, en orden (la primera cadena imprimible de cada uno; aquí no se corta) |
| `signposts` | lo mismo para `insertDebugSignpost` |
| `pops` | cuántos registros `popDebugGroup` |
| `calls` | cada `(id, firma)` distinto con su `count`, `name` y `certainty`, el más frecuente primero |

La herramienta añade `calls_total` (cuántos pares `(id, firma)` distintos; **no** es el número de registros, ese es `records`)
y conserva solo los primeros 100 de `calls` (`traces.py:155-156`). `command_buffers` y `render_encoders` salen de ids que la
tabla llama `probable`, y la respuesta no lo dice junto a esos dos números (solo las entradas de `calls` llevan `certainty`):
léelos como probables (hallazgo F3, [límites](./limites.md)).

## `capture_diff`

`tool_capture_diff(a, b)` (`traces.py:160-166`) llama a `gputrace_read.diff` (`:124-141`), que llama a `counts` (`:100-121`)
para cada captura. `counts` recorre los registros con una pila de grupos de depuración abiertos:

| Registro | Efecto | Línea |
|---|---|---|
| `pushDebugGroup` | abre un grupo nombrado por su etiqueta: la primera cadena imprimible, **cortada a 200 caracteres**; un push sin cadena de 3 o más caracteres es `(unnamed)`, así que todos esos grupos se fusionan | `:110-113` |
| `popDebugGroup` | cierra el grupo más interno; un pop sin nada abierto se ignora | `:114-116` |
| cualquier otro registro cuyo nombre es **confirmado** y no es un signpost | suma 1 al total de la captura para ese nombre y al grupo abierto más interno, si hay. Los registros con ids `probable`, ids desconocidos, signposts y los tres marcadores de depuración **no se cuentan** | `:117-120` |
| grupos con la misma etiqueta | se suman; un grupo que nunca se cierra llega hasta el final del flujo (anclado por `tests/test_capture.py:156-161`, no corrido) | `:100-105` |

`diff` devuelve:

```text
{"captures": {"a": <name>, "b": <name>},
 "aligned_by": "debug_group" | "whole_capture",
 "totals": {<call>: {"a": n, "b": n, "delta": b - a}, ...},
 "groups": [{"name": <label>, "a": {<call>: n, ...}, "b": {<call>: n, ...}}, ...]}
```

| Campo | Regla | Línea |
|---|---|---|
| `totals` | una entrada por cada llamada confirmada que haga **cualquiera** de las capturas, incluidas las de delta 0 | `:130`, `:141` |
| `groups` | solo los grupos donde **alguna llamada difiere**, con las cuentas de solo las llamadas que difieren; un grupo que está en una sola captura se lista con `{}` en el otro lado; ordenados por el tamaño del cambio total, de mayor a menor, y luego por nombre; la herramienta conserva 100 y añade `groups_total` | `:132-138`, `traces.py:164-165` |
| `aligned_by` | `"whole_capture"` cuando ninguna captura tiene grupo de depuración: entonces `groups` está vacío y solo `totals` dice algo | `:140` |

El ejemplo publicado (flujos sintéticos, [prueba de la 0.26.0](../../../evidence/v0.26.0.md#capture_diff-compares-two-captures)):

```text
aligned_by: debug_group
totals: drawPrimitives {a: 3, b: 5, delta: 2}, setRenderPipelineState {a: 1, b: 1, delta: 0}
groups: [{name: main, a: {drawPrimitives: 2}, b: {drawPrimitives: 4}}]
```

`shadow` no aparece porque no cambió, y no importa que fuera primero en una captura y segundo en la otra. La prueba que
construye este par exacto es `tests/test_capture.py:146-153` (no corrida).

## `capture_records`

`tool_capture_records(capture, offset=0, limit=100)` (`traces.py:169-174`) devuelve una página de los registros en bruto, cada
uno como `{"offset", "size", "id", "signature", "name", "strings"}` con como máximo las 3 primeras cadenas; `name` es `None`
cuando el id no está en `CALLS`. Sirve para ver lo que ve el lector cuando un resumen parece mal. La página se construye con
**todos** los registros y luego se corta (`:171-174`), así que cada página vuelve a leer todo el flujo. El límite por defecto es
100 frente a 50 de `trace_query`; el texto del esquema dice «default 50» (`registry.py:19`), lo cual es falso para esta
herramienta (límite 8).

El mismo lector es también un script: `python3 -I src/metal_gpu_trace/gputrace_read.py <capture.gputrace> [--records]` imprime
el resumen como JSON, o con `--records` una línea por registro (`gputrace_read.py:3`, `:144-155`). **No se ejecutó**.

## Lo que el lector no puede decirte

Todo esto se deduce de lo que devuelve el código (**confirmado**), no de una prueba con una captura real:

| No puede | Por qué |
|---|---|
| **El tiempo** | La salida tiene nombres, ids, cuentas y etiquetas: qué se dibujó, no cuánto tardó. El tiempo de GPU viene de un `.trace` y su resumen |
| **Recursos ni shaders** | Los argumentos no se decodifican: buffers, texturas y código de shader no están en la salida, solo las cadenas imprimibles de un registro |
| **Dibujos distintos de la única sobrecarga** | Una escena dibujada con dibujos indexados, instanciados, indirectos o de malla puede mostrar `draw_primitives: 0` y tener llamadas de dibujo (sus ids son `probable` o no están) |
| **Cuentas de estructura seguras** | `command_buffers` y `render_encoders` salen de los ids `probable` |
| **Cambios en llamadas sin confirmar** | `diff` ignora todo lo no confirmado: un cambio que solo toca llamadas `probable` o desconocidas no muestra diferencia |
| **La memoria es el tamaño del archivo** | `records` lee el archivo `capture` entero en memoria (`read_bytes`, `gputrace_read.py:50`) y `diff` lee dos. El tamaño de un archivo `capture` real nunca se vio; **no medido** |

Volver al [índice](./index.md).
