# Tocarlo sin romperlo

**Lector:** personas que añaden o cambian una herramienta en `traces.py` o `gputrace_read.py`. Revisado el 2026-11-16.

English: [Touching it without breaking it](../../../guides/reading-traces/touching-it.md)

> **En corto:** una regla por tipo de cambio. La idea detrás de casi todas: nunca fiarse de un nombre o una ruta que llega de
> un cliente, nunca contar una suposición como un hecho, y mantener pruebas y contrato con los clientes al paso del código.

| Si añades o cambias... | Haz esto | Porque |
|---|---|---|
| Una llamada Metal nueva | Añade su id a `CALLS` como `"probable"`; pásala a `"confirmado"` solo tras emparejarla con una captura real; añade un registro con ella a una prueba de `tests/test_capture.py` (los ayudantes `record` y `capture` construyen un flujo) | `capture_diff` la cuenta en cuanto se confirma, y todo diff anterior cambia |
| Una herramienta que lee una captura | Pasa por `paths.allowed` y `stream_of`, nunca `read_bytes` sobre una ruta propia; deja en cada mensaje el nombre del paquete, no su carpeta | F1 |
| Una herramienta que lee un `.trace` | Toma `trace` con `paths.trace_path`; pasa el nombre de la tabla por la misma comprobación de letras-dígitos-guion; lee con `perf_report.rows` (borra el archivo exportado); conserva el `finally` que lo cierra (`traces.py:113-114`) | el nombre entra en un xpath, y el archivo exportado puede ser de gigabytes |
| Un campo nuevo de una ventana | `windows_of` guarda las sumas en nanosegundos y convierte una sola vez al final (`:85-87`) | el redondeo no se acumula |
| Cualquier cosa en `traces.py` | No debe leer un `<run>.json` (los resúmenes son de `analysis.py`); el único archivo parecido a un resumen que toca es la tabla por fotograma, a través de `tables.py` | un dueño por archivo |
| Una herramienta nueva | Añádela a `registry.py` (nombre, esquema, pistas) y a `PAGED_TOOLS` (`:9`) si devuelve `page()`; actualiza `tests/golden/protocol.json` | es el contrato con los clientes |

Volver al [índice](./index.md).
