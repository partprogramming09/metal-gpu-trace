# Las herramientas de captura

**Lector:** personas que leen o comparan capturas `.gputrace` con el servidor, o que cambian `tool_capture_*`. Revisado el 2026-11-16.

English: [The capture tools](../../../guides/reading-traces/capture-tools.md)

> **En corto:** tres herramientas leen una captura Metal. `capture_summary` cuenta lo que hay en una (cuántos dibujos, qué
> grupos con nombre). `capture_diff` compara dos («ahora 5 dibujos, antes 3»), emparejando los grupos por nombre.
> `capture_records` muestra las entradas en bruto, para comprobar a las otras dos. Ninguna dice cuánto tardó nada. Lee antes
> [el formato](./formato-gputrace.md): ahí están los ids y cuánto fiarse.

## `capture_summary`

`tool_capture_summary(capture)` (`traces.py:151-157`) resuelve la ruta con `paths.allowed` y llama a `gputrace_read.summarize`
(`:72-97`), que lee cada registro una vez y devuelve:

| Clave | Qué es |
|---|---|
| `capture` | el nombre del paquete, nunca su ruta |
| `records` | cuántos registros tiene el flujo |
| `command_buffers` | registros con id -16343 (`commandBuffer`) |
| `render_encoders` | registros con id -16353 (`renderCommandEncoder`) |
| `draw_primitives` | registros con id -16218; los dibujos indexados, instanciados, indirectos y de malla tienen otros ids y **no** se cuentan (`:88-89`), así que una escena puede mostrar `0` y dibujar igual |
| `debug_groups`, `signposts` | las etiquetas de los registros `pushDebugGroup` / `insertDebugSignpost`, en orden (primera cadena imprimible; aquí no se corta) |
| `pops` | cuántos registros `popDebugGroup` |
| `calls` | cada `(id, firma)` distinto con `count`, `name` y `certainty`, el más frecuente primero |

La herramienta añade `calls_total` (pares distintos; **no** es `records`) y conserva los primeros 100 de `calls`
(`traces.py:155-156`). `command_buffers` y `render_encoders` salen de ids `probable` y la respuesta no lo dice (solo las
entradas de `calls` llevan `certainty`): léelos como probables (F3, [límites](./limites.md)).

## `capture_diff`

`tool_capture_diff(a, b)` (`traces.py:160-166`) llama a `gputrace_read.diff` (`:124-141`), que corre `counts` (`:100-121`) sobre
cada captura, recorriendo los registros con una pila de grupos de depuración abiertos:

| Registro | Efecto | Línea |
|---|---|---|
| `pushDebugGroup` | abre un grupo nombrado por su etiqueta: primera cadena imprimible, **cortada a 200 caracteres**; sin cadena de 3 o más caracteres es `(unnamed)`, así que todos esos grupos se fusionan | `:110-113` |
| `popDebugGroup` | cierra el grupo más interno; un pop sin nada abierto se ignora | `:114-116` |
| cualquier otro registro con nombre **confirmado** que no sea un signpost | suma 1 al total de la captura para ese nombre y al grupo abierto más interno. Los ids `probable`, desconocidos, los signposts y los tres marcadores **no se cuentan**: un cambio que solo los toca no muestra diferencia | `:117-120` |
| grupos con la misma etiqueta | se suman; un grupo que nunca se cierra llega hasta el final del flujo (`tests/test_capture.py:156-161`, no corrido) | `:100-105` |

| Campo de `diff` | Regla | Línea |
|---|---|---|
| `captures` | `{"a": <name>, "b": <name>}` | |
| `totals` | `{<call>: {"a": n, "b": n, "delta": b - a}}`: una entrada por cada llamada confirmada que haga **cualquiera** de las capturas, delta 0 incluido | `:130`, `:141` |
| `groups` | `[{"name": <label>, "a": {<call>: n}, "b": {...}}]`: solo los grupos donde **alguna llamada difiere**, con solo las llamadas que difieren; un grupo en una sola captura lleva `{}` en el otro lado; mayor cambio total primero, luego por nombre; la herramienta conserva 100 y añade `groups_total` | `:132-138`, `traces.py:164-165` |
| `aligned_by` | `"debug_group"` o `"whole_capture"` (ninguna captura tiene grupo: `groups` queda vacío y solo `totals` dice algo) | `:140` |

Ejemplo publicado (flujos sintéticos, [prueba de la 0.26.0](../../../evidence/v0.26.0.md#capture_diff-compares-two-captures)):

```text
aligned_by: debug_group
totals: drawPrimitives {a: 3, b: 5, delta: 2}, setRenderPipelineState {a: 1, b: 1, delta: 0}
groups: [{name: main, a: {drawPrimitives: 2}, b: {drawPrimitives: 4}}]
```

`shadow` no aparece porque no cambió, sea cual sea su orden en cada captura. La prueba que construye este par es
`tests/test_capture.py:146-153` (no corrida).

## `capture_records`

`tool_capture_records(capture, offset=0, limit=100)` (`traces.py:169-174`) devuelve una página de registros en bruto, cada uno
`{"offset", "size", "id", "signature", "name", "strings"}` con como máximo 3 cadenas; `name` es `None` si el id no está en
`CALLS`. Sirve para ver lo que ve el lector cuando un resumen parece mal. La página se corta de **todos** los registros
(`:171-174`), así que cada página vuelve a leer todo el flujo. El límite por defecto es 100 frente a 50 de `trace_query`; el
esquema dice «default 50» (`registry.py:19`), falso para esta herramienta (límite 8). El mismo lector es un script:
`python3 -I src/metal_gpu_trace/gputrace_read.py <capture.gputrace> [--records]` imprime el resumen como JSON, o una línea por
registro (`gputrace_read.py:3`, `:144-155`); **no se ejecutó**.

## Lo que el lector no puede decirte

Todo esto se deduce de lo que devuelve el código (**confirmado**), no de una captura real:

| No puede | Por qué |
|---|---|
| **El tiempo** | La salida son nombres, ids, cuentas y etiquetas: qué se dibujó, no cuánto tardó. El tiempo de GPU viene de un `.trace` y su resumen |
| **Recursos ni shaders** | Los argumentos no se decodifican: buffers, texturas y código de shader no salen, solo las cadenas imprimibles de un registro |
| **La memoria es el tamaño del archivo** | `records` lee el archivo `capture` entero en memoria (`read_bytes`, `gputrace_read.py:50`) y `diff` lee dos. El tamaño de un `capture` real nunca se vio; **no medido** |

Volver al [índice](./index.md).
