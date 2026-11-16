# El argumento `trace` y qué es un `.trace`

**Lector:** personas que llaman a `trace_tables`, `trace_count` o `trace_query`, o que cambian cómo encuentran y abren una traza. Revisado el 2026-11-16.

English: [The `trace` argument](../../../guides/reading-traces/trace-argument.md)

> **En corto:** nombras la grabación con un nombre corto, como `a2-proof-first_20261115-085621`, o con una ruta. El servidor
> busca el nombre en su carpeta de corridas y rechaza lo que esté fuera de las carpetas que puede leer. Luego le pide el
> contenido a `xctrace` de Apple, una tabla cada vez. Si la grabación ya se borró recibes una frase que lo dice: el error más probable aquí.

## Cómo se entiende el argumento `trace`

El argumento se describe como «un nombre de corrida de perf_runs cuyo trace_kept es verdadero, o la ruta de un .trace»
(`registry.py:20`). `paths.trace_path` (`:83-91`) decide cuál:

| El texto es... | Se convierte en | Si falla |
|---|---|---|
| un **nombre** válido (`name_ok`: letras, dígitos, `.`, `_`, `-`, como máximo 120 bytes; `paths.py:25-30`) | `<carpeta de corridas>/<name>.trace` (se acepta un `.trace` final) | un enlace ahí: `<name>.trace cannot be read` (`:88-89`) |
| cualquier otra cosa, una **ruta** | resuelta por `allowed` (`:91`); dentro de la carpeta de corridas o de una carpeta de `METAL_TRACE_READ` | `<name> is outside the readable directories; add its directory to METAL_TRACE_READ` (`paths.py:20-21`) |

Consecuencia (**confirmada**, **no ejecutada**): `foo.trace` no tiene `/`, así que es un nombre de corrida buscado en la carpeta
de corridas. Un `.trace` en otro sitio necesita una ruta con directorio (`./foo.trace`, o una absoluta dentro de
`METAL_TRACE_READ`). La carpeta debe existir: `export` lanza `no recording at <name>: perf_record.sh deletes the .trace once its
summary is written, unless KEEP_TRACE=1` (`perf_report.py:52-54`): lo que ve un cliente ante una traza borrada.

## Cómo es un `.trace` visto desde aquí

Un `.trace` es un **paquete** (bundle): una carpeta que escribe Instruments y lee `xctrace`. Este proyecto nunca abre sus
entrañas; le pide dos cosas a `xctrace` (**confirmado**, `perf_report.py:49-66`):

| Petición | Comando | Qué vuelve |
|---|---|---|
| El **índice** (table of contents) | `xcrun xctrace export --input <trace> --output <temporal.xml> --toc` | XML con raíz `trace-toc`, elementos `run` (el código siempre lee `run number="1"`, `perf_report.py:92`), cada uno con un elemento `data` que tiene un `table` por tabla; `schema` es el nombre de la tabla (`traces.py:36`, `:100`) |
| Una **tabla** | lo mismo con `--xpath '/trace-toc/run[@number="1"]/data/table[@schema="<name>"]'` en vez de `--toc` | XML con un `schema` que lista las columnas (cada `col` tiene un `mnemonic`, el nombre de la columna) y un `row` por fila, cuyas celdas son hijas con el nombre de la columna (`perf_report.py:143-179`; fixture `tests/test_traces.py:11-16`) |

- Las celdas llevan el valor como texto y a menudo un atributo `fmt` con la versión formateada (`traces.py:111`).
- Para mantener pequeña una tabla grande, `xctrace` escribe un valor repetido una vez con un `id` y las celdas siguientes lo
  señalan con `ref`; `rows` las resuelve al leer (`perf_report.py:131-170`; [guía de resumen](../resumir-y-analizar/del-trace-al-resumen.md#paso-1-exportar)).
- Los nombres de las tablas son los de Instruments y este proyecto no los lista: son lo que devuelva `trace_tables`.

**Una medida de una grabación real.** Una grabación de 8 segundos de un programa de prueba en el nivel `deep` (2026-11-15, Apple
M1 Pro, `xctrace` 27.2) exportó **85 tablas**, 59 con filas y 26 vacías (E8; nota de investigación interna, no publicada; **no
reproducido aquí**). El resumen lee las pocas que importan ([la tabla de tablas](../resumir-y-analizar/del-trace-al-resumen.md#paso-2-el-indice-y-missing_tables)); el resto están para `trace_query`.

Siguiente: [`trace_tables` y `trace_count`](./tablas-y-conteo.md). Volver al [índice](./index.md).
