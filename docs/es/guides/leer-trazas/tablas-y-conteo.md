# `trace_tables` y `trace_count`

**Lector:** personas que exploran un `.trace` guardado, o que cambian estas dos herramientas. Revisado el 2026-11-16.

English: [`trace_tables` and `trace_count`](../../../guides/reading-traces/trace-tables-count.md)

> **En corto:** una grabación tiene muchas tablas, como las hojas de una hoja de cálculo, y algunas están vacías.
> `trace_tables` lista sus nombres. `trace_count` dice cuáles tienen filas de verdad, para que nadie lea una página de nada.
> Empieza por la primera, sigue con la segunda y lee una tabla con [`trace_query`](./trace-query.md).

## `trace_tables`: qué hay en esta traza

`tool_trace_tables` (`traces.py:33-36`) pide el índice, junta cada elemento `table` que tiene atributo `schema` y devuelve
`{"tables": [<nombres ordenados>]}`. Nada más: ni cuentas de filas ni tamaños. Es la más barata de las tres llamadas; las dos
siguientes necesitan un nombre de ella.

## `trace_count`: qué tablas tienen filas

Una tabla puede existir y estar vacía. La grabación de E8 tiene 26 vacías, entre ellas la tabla de *spill* del compilador de
shaders (vacía salvo que un programa derrame registros). `tool_trace_count` (`traces.py:124-148`) exporta cada tabla nombrada y
cuenta sus filas, en total y por proceso:

```text
{"trace": "<name>", "tables": {"<schema>": {"rows": 3, "by_process": {"<name> (42)": 2, "<name> (7)": 1}}, ...}}
```

(la forma es lo que afirma `tests/test_report.py:207-208`, con nombres de proceso sintéticos; no corrido).

| Regla | Comportamiento | Línea |
|---|---|---|
| Sin argumento `tables` | cuenta las diez de `COUNTED_TABLES`: intervalos de GPU, lista de encoders, finalización de command buffers, las tablas de spill y actividad del compilador de shaders, la lista y las muestras del perfilador de shaders, asignaciones de recursos, intervalos de contadores de GPU, `time-profile` | `traces.py:117-121` |
| Un nombre que no está en el índice | no es un error: `{"rows": None, "note": "not in this trace"}`. **`rows: 0` y «no está» son respuestas distintas** | `:133-135` |
| Un nombre con caracteres que no son letras, dígitos ni `-` | `a table name holds only letters, digits and '-'; trace_tables lists them`; la comprobación protege el xpath, que se construye insertando el nombre en una cadena | `:131-132`, `:136` |
| `by_process` | los diez procesos con más filas, nombrados como los nombra la tabla (`name (pid)`), o por el pid cuando la celda no tiene texto | `:142`, `:147` |
| Falla una exportación | las demás siguen: se captura un `RuntimeError` o un tiempo agotado y esa tabla recibe `{"rows": None, "note": <el texto del error>}` | `:144-146` |

La nota de la propia herramienta lo dice claro: «a table with 0 rows needs another instrument or Xcode, not a bigger page»
(`:125-126`).

**Privacidad.** Los nombres de `by_process` son los de **todo lo que corría en la máquina** durante la grabación, no solo el
programa bajo prueba (la misma medida muestra un ayudante de navegador entre los procesos más activos de la tabla de GPU, E8).
Viajan al cliente en el resultado. No se escriben en un resumen (`perf_report.py:584-590` no guarda ningún nombre ahí), pero
quien pega un resultado de `trace_count` en un lugar compartido se los lleva (hallazgo F10, [límites](./limites.md)).

Siguiente: [`trace_query`](./trace-query.md). Volver al [índice](./index.md).
