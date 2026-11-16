# Tocarlo sin romperlo

**Lector:** personas que añaden o cambian una herramienta en `traces.py` o `gputrace_read.py`. Revisado el 2026-11-16.

English: [Touching it without breaking it](../../../guides/reading-traces/touching-it.md)

> **En corto:** una lista corta de reglas, una por tipo de cambio. La idea detrás de casi todas: nunca fiarse de un nombre o
> una ruta que llega de un cliente, nunca contar una suposición como un hecho, y mantener las pruebas y el contrato con los
> clientes al paso del código.

| Si añades o cambias... | Haz esto | Porque |
|---|---|---|
| Una llamada Metal nueva | Añade su id a `CALLS` como `"probable"` primero. Pásala a `"confirmado"` solo tras emparejarla con una captura real. Añade un registro con ella a una prueba de `tests/test_capture.py` (los ayudantes `record` y `capture` construyen un flujo) | `capture_diff` empieza a contarla en cuanto se confirma, y todo diff anterior cambia |
| Una herramienta nueva que lee una captura | Pasa por `paths.allowed` y `stream_of`, nunca `read_bytes` sobre una ruta propia; deja en cada mensaje el nombre del paquete, no su carpeta | hallazgo F1 |
| Una herramienta nueva que lee un `.trace` | Toma `trace` con `paths.trace_path`; pasa el nombre de la tabla por la misma comprobación de letras-dígitos-guion; lee con `perf_report.rows` (borra el archivo exportado); conserva el `finally` que lo cierra (`traces.py:113-114`) | el nombre entra en un xpath, y el archivo exportado puede ser de gigabytes |
| Un campo nuevo de una ventana | `windows_of` guarda sus sumas en nanosegundos y convierte una sola vez al final (`:85-87`); mantenlo así | el redondeo no se acumula |
| Cualquier cosa en `traces.py` | No debe leer un `<run>.json`: los resúmenes son de `analysis.py`. El único archivo parecido a un resumen que toca es la tabla por fotograma, a través de `tables.py` | un dueño por archivo |
| Una herramienta nueva, de cualquier tipo | Añádela a `registry.py` (nombre, esquema, pistas) y a `PAGED_TOOLS` (`:9`) si devuelve `page()`; actualiza el archivo golden `tests/golden/protocol.json` | es el contrato con los clientes |

Volver al [índice](./index.md).
