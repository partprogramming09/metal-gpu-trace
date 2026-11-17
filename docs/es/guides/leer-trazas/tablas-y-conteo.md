# `trace_tables` y `trace_count`

**Lector:** personas que exploran las tablas de una grabación (su `.trace` guardado, o su archivo de tablas), o que cambian estas dos herramientas. Revisado el 2026-11-16.

> **Desde el archivo de tablas:** cuando el `.trace` ya no está, las dos herramientas leen `<run>.tables.sqlite`, que guarda las
> tablas que leyó el resumen (`trace_count` dice «not in this trace's tables file» para las demás). Ver
> [el archivo de tablas](./archivo-de-tablas.md).

English: [`trace_tables` and `trace_count`](../../../guides/reading-traces/trace-tables-count.md)

> **En corto:** una grabación tiene muchas tablas, como las hojas de una hoja de cálculo, y algunas están vacías.
> `trace_tables` lista sus nombres; `trace_count` dice cuáles tienen filas, para que nadie lea una página de nada. Luego lee una con [`trace_query`](./trace-query.md).

## `trace_tables`: qué hay en esta traza

`tool_trace_tables` (`traces.py:33-36`) pide el índice, junta cada `table` con atributo `schema` y devuelve
`{"tables": [<nombres ordenados>]}`: sin cuentas de filas ni tamaños. La más barata de las tres; las otras dos necesitan un nombre de ella.

## `trace_count`: qué tablas tienen filas

Una tabla puede existir y estar vacía: la grabación de E8 tiene 26, entre ellas la tabla de *spill* del compilador de shaders
(vacía salvo que un programa derrame registros). `tool_trace_count` (`traces.py:124-148`) exporta cada tabla nombrada y cuenta
sus filas, en total y por proceso (forma afirmada por `tests/test_report.py:207-208`, nombres sintéticos; no corrido):

```text
{"trace": "<name>", "tables": {"<schema>": {"rows": 3, "by_process": {"<name> (42)": 2, "<name> (7)": 1}}, ...}}
```

| Regla | Comportamiento | Línea |
|---|---|---|
| Sin argumento `tables` | cuenta las diez de `COUNTED_TABLES`: intervalos de GPU, lista de encoders, finalización de command buffers, las tablas de spill y actividad del compilador de shaders, la lista y las muestras del perfilador de shaders, asignaciones de recursos, intervalos de contadores de GPU, `time-profile` | `traces.py:117-121` |
| Un nombre que no está en el índice | no es un error: `{"rows": None, "note": "not in this trace"}`. **`rows: 0` y «no está» son respuestas distintas** | `:133-135` |
| Un nombre con caracteres que no son letras, dígitos ni `-` | `a table name holds only letters, digits and '-'; trace_tables lists them`; la comprobación protege el xpath, que se construye insertando el nombre en una cadena | `:131-132`, `:136` |
| `by_process` | los diez procesos con más filas, nombrados como los nombra la tabla (`name (pid)`), o por pid cuando la celda no tiene texto | `:142`, `:147` |
| Falla una exportación | las demás siguen: se captura un `RuntimeError` o un tiempo agotado y esa tabla recibe `{"rows": None, "note": <el texto del error>}` | `:144-146` |

La nota de la propia herramienta: «a table with 0 rows needs another instrument or Xcode, not a bigger page» (`:125-126`).

**Privacidad.** `by_process` nombra **todo lo que corría en la máquina** durante la grabación, no solo el programa bajo prueba
(un ayudante de navegador está entre los más activos de la tabla de GPU, E8). Viajan al cliente en el resultado; ningún resumen
guarda un nombre (`perf_report.py:584-590`), pero quien pega un resultado de `trace_count` en un lugar compartido se los lleva (F10, [límites](./limites.md)).

Siguiente: [`trace_query`](./trace-query.md). Volver al [índice](./index.md).
