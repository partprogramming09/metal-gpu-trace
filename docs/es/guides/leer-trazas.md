# Leer trazas

**Lector:** personas que preguntan al servidor qué hay dentro de una grabación (un `.trace`, un `.gputrace` o los fotogramas de una corrida), o que cambian `traces.py` o `gputrace_read.py`. Revisado el 2026-11-16.

English: [Reading traces](../../guides/reading-traces.md)

Esta página trata de las herramientas que **leen la grabación misma** y no su resumen: `trace_tables`, `trace_count` y
`trace_query` (abren un `.trace` de Instruments con `xctrace`), `perf_export_trace` (convierte la tabla por fotograma de una
corrida en un archivo que abre Perfetto) y `capture_summary`, `capture_diff` y `capture_records` (leen una captura Metal
`.gputrace` sin Xcode). Explica cómo encuentra cada una su archivo, qué devuelve, cómo es el formato de un `.gputrace` hasta
donde el código lo conoce, dónde se detiene cada herramienta y qué ve quien llama cuando falla. No repite
[Resumir y analizar](./resumir-y-analizar.md) (cómo `perf_report.py` lee ese mismo `.trace` para escribir el resumen
`<run>.json` y cada número de él), [Datos y su ciclo de vida](./datos-y-su-ciclo-de-vida.md) (qué archivo se borra y cuándo,
incluidos el `.trace` y el `.chrome-trace`) ni [Grabar](./grabar.md) (cómo se hace el `.trace`); los enlaza donde la historia
continúa. Es la versión en español de la guía en inglés; si difieren, manda el código.

Cómo leer las etiquetas: cada afirmación técnica es **confirmada** (con `archivo:línea`, comprobada con `rg` o `sed` el
2026-11-16 contra el árbol de trabajo, que es la 0.27.2 más las entradas `[Unreleased]` de `CHANGELOG.md`), **probable** (leída
en el código pero no ejecutada aquí) o **especulación** (una conjetura sobre el porqué). **No verificado** marca un dato de fuera
que no se comprobó contra su fuente. Las líneas se mueven cuando cambia el código: busca el nombre, no solo el número. Cada
número lleva el comando que lo produjo, en [Evidencia](#evidencia-los-comandos-y-su-salida-real). **No reproducido** significa
que el comportamiento no se pudo ejecutar para esta página. Rigen tres límites. Primero, el repositorio **no tiene ningún
`.trace`, ningún `.chrome-trace` ni ningún `.gputrace`** (E3), y leer un `.trace` exige `xctrace`, así que ninguna herramienta
`trace_*` se ejecutó. Segundo, la sesión que escribió esta página podía correr comandos de solo lectura (`rg`, `sed`, `awk`,
`jq`, `wc`) y no podía correr Python, así que tampoco se ejecutó ninguna herramienta de `traces.py` ni de `gputrace_read.py`:
lo que devuelven se lee del código, se evalúa a mano sobre las dos corridas reales del clon donde hace falta una corrida, y se
ancla en pruebas que se nombran y no se corrieron. Tercero, ninguna captura `.gputrace` real se ha examinado para esta
página ni para la prueba publicada del proyecto (ver [el formato](#que-hay-dentro-de-un-gputrace)), así que toda afirmación
sobre el formato es afirmación del propio código.

## Un ejemplo primero

Tres preguntas que una persona le hace a un agente, y qué hace cada herramienta. La primera se evalúa sobre una corrida real
de este clon; las otras dos se leen del código y de sus pruebas.

**1. «Muéstrame esta corrida en Perfetto.»** La corrida `a2-proof-first_20261115-085621` tiene una tabla por fotograma de 2045
fotogramas (E4). `perf_export_trace` con ese nombre lee esa tabla, no el `.trace`, y escribe
`a2-proof-first_20261115-085621.chrome-trace` en la carpeta de corridas; responde
`{"file": "a2-proof-first_20261115-085621.chrome-trace", "frames": 2045}`. La primera fila de la tabla es
`6,1267.79,0.0243,1.7417,11.7952,13.5612`, y el código la convierte en una rebanada (E5):

```text
{"name":"GPU frame","ph":"X","pid":1,"tid":1,"ts":1267790,"dur":13561.2,"args":{"frame":6,"compute":0.0243,"fragment":1.7417,"vertex":11.7952}}
```

`ts` y `dur` están en microsegundos (lo que cuenta el formato de traza de Chrome), así que 1267.79 ms pasa a 1 267 790 y
13.5612 ms a 13 561.2. La rebanada empieza 1.27 s después del inicio de la grabación y dura lo que la GPU tardó en ese
fotograma. La herramienta **no se ejecutó**: E5 es la aritmética de `traces.py:22-25` hecha con `awk` sobre la fila real, y la
prueba que ancla la misma aritmética en una tabla de dos filas es `tests/test_analysis.py:329-332`.

**2. «¿Qué partes de esta tabla están ocupadas?»** `trace_query` con `window_ms=10` sobre `metal-gpu-intervals` devuelve una
entrada por ventana de 10 ms en lugar de una por fila. Para tres filas que empiezan en 1 ms (2 ms de duración), 9 ms (1 ms) y
12 ms (4 ms), la respuesta son dos ventanas: `{"start_ms": 0, "count": 2, "duration_ms": 3.0}` y
`{"start_ms": 10, "count": 1, "duration_ms": 4.0}`. Es el ejemplo de `tests/test_traces.py:42-48` (no corrido), y E6 lo evalúa
a mano desde la fórmula.

**3. «¿Qué añadió mi cambio a las llamadas de dibujo?»** `capture_diff` sobre dos capturas `.gputrace` cuenta las llamadas Metal
confirmadas en cada una y dice qué cambió. La prueba publicada de la 0.26.0 muestra el par: `drawPrimitives` 3 contra 5 (delta
2), y el grupo de depuración `main` pasando de 2 dibujos a 4 mientras `shadow` no aparece porque no cambió
([prueba de la 0.26.0](../../evidence/v0.26.0.md#capture_diff-compares-two-captures)). Ese par es **sintético** (un flujo de
bytes que construye una prueba), no una captura hecha por Xcode: ninguna captura real se ha leído en la evidencia publicada de
este proyecto.

Lo que se pregunta un lector, y dónde lo responde esta página:

1. *¿Por qué necesito `KEEP_TRACE=1` para `trace_query` y no para `perf_export_trace`?* Porque la primera lee el `.trace` (que se
   borra por defecto al escribir el resumen) y la segunda lee la tabla por fotograma, que se queda
   ([las tres formas de leer](#las-piezas-y-donde-viven)).
2. *¿Por qué recorrer una tabla grande por páginas se siente lento?* Cada página vuelve a correr `xctrace export`
   ([trace_query](#trace-query-filas-paginas-y-ventanas)).
3. *¿Puede la herramienta decirme cuánto tardó una llamada de dibujo en un `.gputrace`?* No: el lector expone nombres, cuentas
   y etiquetas, ningún tiempo ([lo que no puede leer](#lo-que-el-lector-no-puede-decirte)).

## Por qué esta parte tiene esta forma

| Decisión | Por qué | Alternativas que se dejaron fuera |
|---|---|---|
| Un `.trace` se lee **una tabla por llamada**, con `xctrace export` | Una grabación tiene 85 tablas en la medida (E8); cada exportación guarda un almacén temporal que en una traza grande puede llegar a gigabytes (`perf_report.py:39`), así que pedir solo la tabla que se quiere es lo que acota disco y tiempo | Exportar la traza entera una vez y responder desde ahí: gigabytes de XML en disco para una pregunta sobre una tabla |
| `trace_query` no guarda nada: cada página vuelve a correr la exportación | `trace_query` arma sus filas desde una exportación nueva en cada llamada y borra el archivo al terminar (`traces.py:101`, `:113-114`); el código no tiene caché. **Especulación:** la razón es el coste en disco de conservar un XML de la tabla | Guardar el XML exportado entre páginas: un archivo viejo podría leerse cuando la traza ya no está, y tendría la tabla dos veces |
| `window_ms` suma una tabla por ventana de tiempo | Una tabla de cientos de miles de filas no se puede leer fila a fila; el docstring dice que es «un resumen de una tabla demasiado larga para leerla fila a fila» (`traces.py:93-96`) | Devolver más filas por página: la página se limita a 500 filas y 40 000 caracteres ([límites](#limites-conocidos)) |
| `perf_export_trace` lee la tabla por fotograma, no el `.trace` | El `.trace` se borra por defecto ([ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md), `perf_record.sh:162-163`) y la tabla por fotograma se queda, así que la exportación funciona con una corrida cuya traza lleva tiempo borrada (`traces.py:15`) | Leer el `.trace`: solo funcionaría con `KEEP_TRACE=1` y necesitaría `xctrace` de nuevo |
| El lector de `.gputrace` está escrito a mano con `struct` | No hace falta Xcode en la máquina que lee, y el servidor usa solo la biblioteca estándar (`CLAUDE.md`, [ADR-0003](../../adr/0003-python-3-9-floor.md)); `struct` y `re` bastan para un flujo de registros (`gputrace_read.py:9-14`) | Llamar a Xcode o a un framework privado: ataría la herramienta a una máquina con Xcode, y el formato de la lista de llamadas no es público |
| Cada llamada Metal lleva una **certeza**, y `capture_diff` cuenta solo las confirmadas | Los ids de llamada se dedujeron a mano: 17 de los 24 ids con nombre son `"confirmado"` y 7 son `"probable"` (E2). Un diff que contara una suposición informaría de un cambio que puede no existir (`gputrace_read.py:117`) | Contar todos los ids: un nombre equivocado aparecería como un cambio |
| `capture_diff` alinea por **etiqueta de grupo de depuración**, no por posición | Dos capturas de la misma escena suelen dibujar en otro orden; un grupo se empareja por su etiqueta, así que un grupo reordenado no es una diferencia (`gputrace_read.py:124-128`) | Comparar registro a registro: una sola llamada añadida desplaza todo lo que sigue |
| Las rutas se comprueban antes de abrir nada | La ruta de un `.gputrace` debe estar dentro de `METAL_TRACE_OUT` o `METAL_TRACE_READ` (`paths.py:17-22`); el nombre de un `.trace` se resuelve dentro de la carpeta de corridas y un enlace se rechaza (`paths.py:83-91`) | Leer cualquier ruta: un cliente podría pedirle al servidor que abra un archivo en cualquier sitio que el usuario pueda leer |

## Las piezas y dónde viven

| Pieza | Archivo | Qué hace |
|---|---|---|
| Las herramientas de esta página | `traces.py` | `tool_perf_export_trace` `:9`, `tool_trace_tables` `:33`, `tool_trace_query` `:92`, `tool_trace_count` `:124`, `tool_capture_summary` `:151`, `tool_capture_diff` `:160`, `tool_capture_records` `:169` |
| Las entradas del registro | `registry.py` | nombre, esquema de entrada y pistas de cada herramienta (`:129`, `:159`, `:160`, `:165`, `:172`, `:173`, `:177`) |
| Agrupar por ventanas | `traces.py` | `check_window` `:42`, `windows_of` `:54` |
| La capa de `xctrace` | `perf_report.py` | `export` `:49`, `toc_of` `:81`, `table_xpath` `:90`, `rows` `:143`, `pid_of` `:182` (el mismo código que usa el resumen) |
| El lector de `.gputrace` | `gputrace_read.py` | `CALLS` `:20`, `records` `:48`, `stream_of` `:64`, `summarize` `:72`, `counts` `:100`, `diff` `:124`; también es un script (`main` `:144`) |
| Rutas y paginación | `paths.py` | `allowed` `:17`, `trace_path` `:83`, `page` `:94` |
| Tablas por fotograma | `tables.py` | `find` y `open_text`: tanto el `.csv.gz` como el `.csv` anterior ([guía de datos](./datos-y-su-ciclo-de-vida.md)) |
| Qué pasa con un error | `worker.py` | `call` convierte un fallo en un resultado `isError` (`:165-168`) |

Otra herramienta vive en `traces.py` por otra razón: `gpu_family`, con los dos tipos de recurso `metal-trace://gpu-families` y
`metal-trace://gpu-families/<familia>`, da los datos que Apple publica de una familia de GPU
([abajo](#los-datos-de-las-familias-de-gpu)). No leen ninguna grabación.

![Tres filas de tres cajas, cada fila un flujo de izquierda a derecha. Fila uno, un .trace leído con trace_tables, trace_count y trace_query: encontrar la traza, exportar una tabla con xctrace, filtrar y devolver filas o ventanas de tiempo. Fila dos, un .gputrace leído con capture_summary, capture_diff y capture_records: resolver el paquete dentro de las carpetas legibles, partir su archivo capture en registros, contar, comparar o listar. Fila tres, perf_export_trace: encontrar la tabla por fotograma de una corrida, hacer una rebanada por fotograma, escribir el archivo de traza de Chrome. El texto en rojo marca dónde se detiene cada paso.](/diagrams/reading-traces.png)
*Figura 1. Las tres formas de leer una grabación. Fuente HTML: `docs/diagrams/reading-traces.html` (el texto del diagrama está en inglés).*

Cuál usar, según lo que tengas en la mano:

| Tienes | Pregunta con | Necesita `xctrace` | Necesita el `.trace` conservado |
|---|---|---|---|
| Un nombre de corrida y quieres la lista de tablas | `trace_tables` | sí | sí |
| Un nombre de corrida y quieres saber qué tablas tienen filas | `trace_count` | sí | sí |
| Un nombre de corrida y quieres las filas (o ventanas de tiempo) de una tabla | `trace_query` | sí | sí |
| Un nombre de corrida y quieres ver sus fotogramas en Perfetto | `perf_export_trace` | no | no (necesita la tabla por fotograma) |
| Un `.gputrace` guardado desde Xcode | `capture_summary`, `capture_diff`, `capture_records` | no | no es un `.trace` |

`perf_runs` trae un indicador `trace_kept` por corrida (`analysis.py:79`): es verdadero cuando existe la carpeta
`<run>.trace` y no es un enlace. Es la forma más rápida de saber si las tres primeras filas pueden funcionar para una corrida
(**confirmado**; la [guía de datos](./datos-y-su-ciclo-de-vida.md) dice cuándo se conserva una traza: `KEEP_TRACE=1`, o el nivel
`deep`).

## Leer un `.trace` con `xctrace`

### Cómo se entiende el argumento `trace`

El argumento `trace` de las tres herramientas se describe como «un nombre de corrida de perf_runs cuyo trace_kept sea true, o la
ruta de un .trace» (`registry.py:20`). `paths.trace_path` (`:83-91`) decide cuál:

- Si el texto es un **nombre** válido (`name_ok`: letras, dígitos, `.`, `_` y `-`, hasta 120 bytes; `paths.py:25-30`), es
  `<carpeta de corridas>/<nombre>.trace`, y se admite un `.trace` final en el nombre. Un enlace en ese lugar se rechaza con
  `<nombre>.trace cannot be read` (`:88-89`).
- Si no, es una ruta y pasa por `allowed` (`:91`): se resuelve y debe estar dentro de la carpeta de corridas o de una de las
  carpetas de `METAL_TRACE_READ`; si no, `<nombre> is outside the readable directories; add its directory to METAL_TRACE_READ`
  (`paths.py:20-21`).

Una consecuencia que conviene saber (**confirmada** en el código, **no corrida**): `foo.trace` no tiene `/`, así que cuenta como
nombre de corrida y se busca en la carpeta de corridas; un `.trace` que vive en otro sitio necesita una ruta con directorio
(por ejemplo `./foo.trace`, o una ruta absoluta dentro de `METAL_TRACE_READ`).

La carpeta debe existir como directorio: `export` lo comprueba primero y lanza `no recording at <nombre>: perf_record.sh deletes
the .trace once its summary is written, unless KEEP_TRACE=1` (`perf_report.py:52-54`). Esa frase es lo que ve un cliente cuando
la traza ya se borró, y es el error más probable de toda esta página.

### Cómo es un `.trace` visto desde aquí

Un `.trace` es un **paquete**: una carpeta que escribe Instruments y lee `xctrace`. Este proyecto nunca abre sus entrañas; le
pide a `xctrace` dos cosas (**confirmado**, `perf_report.py:49-66`):

1. El **índice**: `xcrun xctrace export --input <traza> --output <temporal.xml> --toc`. Es un documento XML cuya raíz es
   `trace-toc`, con elementos `run` (el código siempre lee `run number="1"`, `perf_report.py:92`), cada uno con un elemento
   `data` que guarda un elemento `table` por **tabla** y el atributo `schema` de la tabla como su nombre (`traces.py:36`,
   `:100`).
2. Una **tabla**: el mismo comando con `--xpath '/trace-toc/run[@number="1"]/data/table[@schema="<nombre>"]'` en lugar de
   `--toc`. El resultado es XML con un `schema` que lista las columnas (cada `col` tiene un `mnemonic`, el nombre de la columna)
   y un elemento `row` por fila, cuyas celdas son hijos con el nombre de las columnas (`perf_report.py:143-179`; la forma es la
   del montaje de `tests/test_traces.py:11-16`). Las celdas llevan el valor como texto y a menudo un atributo `fmt` con la
   versión formateada (`traces.py:111`). Para que una tabla grande no pese, `xctrace` escribe una vez un valor repetido con un
   `id` y las celdas siguientes lo citan con `ref`; `rows` resuelve esas referencias al leer (`perf_report.py:131-170`, ver la
   [guía de resumir](./resumir-y-analizar.md#paso-1-exportar)).

Los nombres de las tablas son los de Instruments y este proyecto no los lista (son lo que devuelva `trace_tables`). Una medida
de lo que guarda una grabación real: una grabación de 8 segundos de un programa de prueba en el nivel `deep`, hecha el
2026-11-15 en un Apple M1 Pro con `xctrace` 27.2, exportó **85 tablas**, 59 con filas y 26 vacías (E8; la nota de investigación
interna del proyecto de esa fecha, no publicada; **no reproducido aquí**). El resumen lee las pocas que importan
([la tabla de tablas de la guía de resumir](./resumir-y-analizar.md#paso-2-el-indice-y-missing-tables)); las demás están para
`trace_query`.

### `trace_tables`: qué hay en esta traza

`tool_trace_tables` (`traces.py:33-36`) pide el índice, junta cada elemento `table` que tenga atributo `schema` y devuelve
`{"tables": [<nombres ordenados>]}`. Nada más: ni cuentas de filas ni tamaños. Es la más barata de las tres llamadas y por
donde empezar: las otras dos necesitan un nombre de aquí.

### `trace_count`: qué tablas tienen filas

Una tabla puede existir y estar vacía. La grabación de E8 tiene 26 vacías, entre ellas la tabla de *spills* de shader, que está
vacía salvo que un programa derrame registros. `tool_trace_count` (`traces.py:124-148`) responde justo eso, antes de que nadie
lea una página de nada: por cada tabla nombrada la exporta y cuenta las filas, en total y por proceso:

```text
{"trace": "<nombre>", "tables": {"<schema>": {"rows": 3, "by_process": {"<nombre> (42)": 2, "<nombre> (7)": 1}}, ...}}
```

(la forma es la que afirma `tests/test_report.py:207-208`, con nombres de proceso sintéticos; no corrido).

- Sin argumento `tables` cuenta las diez de `COUNTED_TABLES` (`traces.py:117-121`): los intervalos de GPU, la lista de encoders,
  la finalización de command buffers, las tablas de *spill* y de actividad del compilador de shaders, la lista y las muestras
  del perfilador de shaders, las asignaciones de recursos, los intervalos de contadores de GPU y `time-profile`.
- Un nombre que no está en el índice de la traza no es un error: vuelve como `{"rows": None, "note": "not in this trace"}`
  (`:133-135`). **Una tabla con `rows: 0` y una tabla que no está son respuestas distintas.**
- Un nombre solo puede tener letras, dígitos y `-`; si no, `a table name holds only letters, digits and '-'; trace_tables lists
  them` (`:131-132`). La comprobación protege el xpath, que se arma insertando el nombre en un texto (`:136`).
- `by_process` guarda los diez procesos con más filas, con el nombre que la tabla les da (`nombre (pid)`) o con el pid cuando
  la celda no tiene texto (`:142`, `:147`). La nota de la herramienta lo dice claro: «una tabla con 0 filas necesita otro
  instrumento o Xcode, no una página más grande» (`:125-126`).
- Que falle la exportación de una tabla no detiene las demás: un `RuntimeError` o un tiempo agotado se captura y esa tabla recibe
  `{"rows": None, "note": <el texto del error>}` (`:144-146`).

Los nombres de `by_process` son los de **cualquier cosa que corriera en la máquina** mientras se grababa, no solo el programa
de prueba (la misma medida muestra un ayudante de navegador entre los procesos más activos de la tabla de GPU, E8). Viajan al
cliente en el resultado. No se escriben en un resumen (`perf_report.py:584-590` no guarda ningún nombre ahí), pero quien pegue
un resultado de `trace_count` en un sitio compartido se los lleva.

### `trace_query`: filas, páginas y ventanas

`tool_trace_query(trace, schema, offset=0, limit=50, pid=None, window_ms=None)` (`traces.py:92-114`) devuelve una página de una
tabla. En orden:

1. `check_window` (`:42-51`) valida `window_ms`: `None` se queda en `None`; un decimal entero como `10.0` cuenta como `10`; un
   booleano, una fracción, `0`, un negativo o más de `3 600 000` da `window_ms is a whole number of milliseconds from 1 to
   3600000`.
2. El nombre del esquema solo puede tener letras, dígitos y `-` (`:98-99`).
3. La tabla se exporta con el xpath de `:100` y la lee `perf_report.rows` (`:101`).
4. Con `pid` se descartan las filas de otros procesos. El filtro es
   `pid is None or "process" not in row or perf_report.pid_of(row["process"]) == int(pid)` (`:102-103`): una tabla **sin**
   columna `process` se devuelve entera diga lo que diga `pid`. La descripción de la herramienta dice «conserva solo las filas
   de este proceso», así que un lector puede esperar una respuesta vacía para esa tabla
   ([hallazgo F6](#hallazgos-nuevos-en-el-codigo-sin-arreglar)).
5. Sin `window_ms`, cada fila pasa a `{columna: valor}` donde el valor es el texto `fmt` de la celda cuando lo tiene, y si no
   su texto (`:111`). Es el valor tal como lo muestra Instruments. **Probable:** en una columna de tiempo puede leerse como
   `1.5 ms` donde el texto crudo son nanosegundos, y por eso las ventanas leen `.text` y no `fmt` (`:68`, `:79`). Luego se
   corta en una página con `paths.page` (`:111-112`).
6. El archivo que leyó `rows` se borra en un `finally` (`:113-114`), también cuando el código de ventanas lanzó un error; una
   prueba lo comprueba (`tests/test_traces.py:118-124`, no corrida).

**Paginación.** `paths.page(items, offset, limit)` (`paths.py:94-99`) lleva `offset` a 0 o más y `limit` a 1..500
(`config.MAX_LIMIT`, `config.py:43`; el esquema dice «por defecto 50, como mucho 500», `registry.py:19`) y devuelve:

```text
{"total": <todas las filas>, "offset": <n>, "rows": [...], "next_offset": <n + len(rows), o null al final>}
```

`next_offset: null` es como un cliente sabe que llegó al final. Todo se calcula desde una **lista con todas las filas**
(`:111-112` la arma, `:94-99` la corta), y cada llamada vuelve a exportar la tabla, así que leer una tabla de un millón de filas
en páginas de 500 corre la exportación 2000 veces. El código no tiene caché (**confirmado**); el coste de una exportación de una
tabla grande **no se midió aquí**. Si una exportación tarda más de 600 segundos, la llamada termina con
`subprocess.TimeoutExpired`, que el worker convierte en un resultado de error (`worker.py:165-168`; el límite está en
`perf_report.py:49`).

**Ventanas.** Con `window_ms`, `windows_of(selected, window_ms)` (`traces.py:54-89`) reemplaza las filas:

- La **primera fila decide la forma**: su columna de tiempo es `start` si la tiene, si no `time` (`TIME_COLUMNS`, `:39`, `:62`),
  y la tabla tiene columna de duración cuando la primera fila tiene `duration` (`:63`). Una tabla con ninguna de las dos
  columnas de tiempo falla con `window_ms needs a table with a time column (start or time); trace_tables lists the tables and
  trace_query without window_ms shows the columns` (`:64-66`).
- El tiempo de cada fila es `int(celda.text)` en nanosegundos; una ventana es `ns // (window_ms × 1 000 000)` (`:68`, `:74`).
  Una fila cuyo tiempo no es un número, es negativo o falta se cuenta en `skipped_rows` (`:69-73`); la respuesta lleva
  `skipped_rows` solo cuando no es 0 (`:108-109`).
- Una ventana es `{"start_ms": índice × window_ms, "count": N}` y, cuando la tabla tiene duración, `"duration_ms"`: la **suma**
  de las duraciones de sus filas en ms, redondeada a 3 decimales (`:75-87`). Una fila cuya duración no se puede leer cuenta
  igual pero no suma nada (`:77-81`). Solo se listan las ventanas que tienen una fila, en orden de tiempo (`:83-84`), y se
  paginan como las filas (`:107`); la respuesta lleva además `window_ms`.
- Como las duraciones se suman, la suma de trabajo en paralelo de una ventana puede ser mayor que la ventana: la misma
  salvedad que la [suma de GPU por fotograma](./resumir-y-analizar.md#el-tiempo-de-gpu-por-fotograma-es-una-suma-sobre-canales).

Las doce pruebas de `tests/test_traces.py` anclan todo esto: ventanas de 10 ms, una columna `time` sin duración, rechazo de cero,
negativos y no números, una tabla sin columna de tiempo, una tabla vacía, filas sin tiempo usable, un decimal entero, la
paginación, el filtro por pid y el borrado del archivo. **No se corrieron** para esta página.

## Exportar un `.chrome-trace`

`tool_perf_export_trace(run)` (`traces.py:9-30`) responde «muéstrame los fotogramas de esta corrida en una línea de tiempo». El
archivo que escribe es JSON en el formato de eventos de traza de Chrome, que abren `ui.perfetto.dev` y `chrome://tracing` (lo
dice el docstring, `traces.py:10-13`; los visores **no se abrieron** para esta página).

Cómo funciona, en orden:

1. `paths.run_path(run)` comprueba el nombre y que `<run>.json` exista, no sea un enlace y no sea `baselines.json`
   (`traces.py:14`, `paths.py:33-41`). Una corrida desconocida es `no run <nombre>; perf_runs lists them`.
2. `table_files.find(config.OUT, f"{run}.frames")` busca primero `<run>.frames.csv.gz` y luego `<run>.frames.csv`, y no un
   enlace (`traces.py:15`, `tables.py:13-20`). Ninguno: `<run> has no per-frame file; record it again` (`:16-17`).
3. Por cada fila de la tabla arma un **evento completo** (`"ph": "X"`, una rebanada con inicio y largo) llamado `GPU frame`, en
   el proceso 1 y el hilo 1: `ts = start_ms × 1000`, `dur = gpu_ms_total × 1000` (microsegundos), y en `args` el número de
   fotograma más cada columna `gpu_ms_<canal>` salvo el total, con el prefijo `gpu_ms_` recortado (`compute`, `fragment`,
   `vertex`) (`:22-25`).
4. Una tabla que no se puede leer, a la que le falta una columna o que trae un valor que no es número da
   `<nombre del archivo> cannot be read; record it again` (`:26-27`); no se escribe un archivo a medias.
5. Escribe `{"traceEvents": [...], "displayTimeUnit": "ms"}` en `<carpeta de corridas>/<run>.chrome-trace` y devuelve
   `{"file": "<run>.chrome-trace", "frames": <eventos>}` (`:28-30`). `paths.write_file` reemplaza un archivo anterior con ese
   nombre y se niega a escribir a través de un enlace (`paths.py:69-80`). Las pistas de la herramienta dicen que es idempotente
   y no destructiva (`registry.py:129-131`): correrla dos veces escribe el mismo archivo.

Qué muestra el archivo y qué no:

- **Una pista, una rebanada por fotograma.** Todo va en el proceso 1 y el hilo 1, así que un fotograma cuya rebanada es más
  larga que el hueco hasta el siguiente lo solapa; Perfetto las apilará. El largo del fotograma es su tiempo de GPU, la **suma**
  de los tres canales (`gpu_ms_total`), no el tiempo entre su primer y su último intervalo. El docstring dice que un fotograma
  con encoders en paralelo «puede verse más corto de lo que tardó», pero una suma de trabajo en paralelo es más larga que el
  tiempo transcurrido, no más corta ([hallazgo F8](#hallazgos-nuevos-en-el-codigo-sin-arreglar)).
- **Solo los fotogramas que el resumen conservó.** Un tramo de la grabación en que el programa renderizó pero no presentó queda
  fuera de `frames.csv` (ver [Trabajo que nunca se presentó](./resumir-y-analizar.md#trabajo-que-nunca-se-presento)), así que
  también queda fuera de la línea de tiempo. En la segunda corrida real del clon la tabla tiene 153 fotogramas (E4) para 20
  segundos de grabación.
- **Sin encoders, sin command buffers, sin memoria.** Es una pista gruesa; la vista fina es `trace_query` sobre los intervalos
  de GPU de un `.trace` conservado.
- **El archivo es un tipo propio de retención.** Un `.chrome-trace` es lo segundo que borra la cuota de disco, después de un
  `.trace` y antes de las tablas, salvo que la exportación de la corrida **actual** se queda (`retention.py:5-8`, `:30-43`; la
  [guía de datos](./datos-y-su-ciclo-de-vida.md) tiene el orden completo). No crea una corrida nueva: `perf_runs` no lo lista
  (`tests/test_analysis.py:333`, no corrida).

## Leer un `.gputrace` sin Xcode

### Qué hay dentro de un `.gputrace`

**Lee primero este párrafo: el proyecto no ha examinado una captura real.** El docstring del módulo dice que la cabecera de 8
bytes, los ids de llamada y sus nombres «se dedujeron aquí contra una captura cuya lista de comandos mostraba Xcode (macOS
27.0.1)» (`gputrace_read.py:7-8`). Pero la investigación del 2026-11-15 que debía estudiar el formato deja escrito que **no se
hizo**, porque «necesita dos capturas reales hechas en Xcode» y no había ninguna en ese Mac; y la prueba de `capture_diff`
(0.26.0) anota como **no probado** «dos capturas reales hechas por Xcode (ninguna estaba en este Mac)». Las dos afirmaciones no
se concilian en ningún lugar del repositorio ([hallazgo F5](#hallazgos-nuevos-en-el-codigo-sin-arreglar)). Lo que esta página
puede decir se limita, entonces, a lo que hace el código y a lo que construyen sus pruebas. La disposición de los registros sigue
al proyecto público [tmc/gputrace](https://github.com/tmc/gputrace) (MIT; lo dice el módulo en `gputrace_read.py:6`, y no se
copia código, README «Credits»); **no verificado aquí** contra el código de ese proyecto.

Lo que el código supone (**confirmado** como suposición, `gputrace_read.py:1-8`, `:48-69`):

- Un `.gputrace` es una **carpeta** (un paquete) guardada desde Xcode. El lector abre **un archivo** de ella, llamado `capture`
  (`stream_of`, `:64-69`); cualquier otro archivo del paquete no se lee, y qué más guarda un paquete real no se examinó.
- `capture` es un flujo llamado **MTSP**: los primeros 4 bytes son el ASCII `MTSP`, los 4 siguientes son una palabra que el
  lector salta (`off = 8`, `:51`). Si la marca no está, el lector empieza en 0 en vez de fallar.
- Después vienen los **registros**, uno tras otro. Cada uno empieza con `[u32 tamaño][i32 id de llamada]`, en little-endian
  (`struct.unpack_from("<Ii", ...)`, `:53`), y `tamaño` es el largo del registro **entero**, esos 8 bytes incluidos, así que el
  siguiente registro empieza `tamaño` bytes después (`:56`, `:61`).
- Dentro de un registro, en el desplazamiento `0x24` (36), hay una **firma**: un texto ASCII corto terminado en un byte cero.
  Los registros sintéticos de las pruebas usan `Cuu` (`tests/test_capture.py:20`). **Especulación:** nombra los tipos de los
  argumentos de la llamada. Tras la firma vienen los argumentos (`:57-58`).
- El lector no decodifica los argumentos. Extrae las **secuencias ASCII imprimibles de 3 o más caracteres** que siguen a la
  firma (`re.findall(rb"[ -~]{3,}", tail)`, `:59`) y las llama `strings`. En un `pushDebugGroup` la primera es la **etiqueta**
  que el programa le dio al grupo; es el único argumento del que depende algo.
- El docstring también lista un `u32` en `+0x20` (`:5`); el código nunca lo lee.

```text
 el archivo:  [MTSP][palabra][registro 1][registro 2] ... hasta el final del archivo
              bytes 0-3  4-7   desde el byte 8, uno tras otro

 un registro: [u32 tamaño][i32 id][ ... ][firma, NUL][argumentos ...]
              la firma empieza en el desplazamiento 0x24 del registro
              tamaño cuenta el registro entero, esos 8 bytes incluidos
```

Un registro que no se puede analizar detiene toda la lectura. Si `tamaño` es menor que 8, o el registro se pasaría del final del
archivo, el lector lanza `ValueError`: `<nombre del paquete>: record at 0x<desplazamiento> has size <n>; the stream is not MTSP
as expected` (`:54-55`, con solo el nombre de la carpeta del paquete, nunca su ruta; anclado por `tests/test_capture.py:86-97`,
no corrida). Los menos de 8 bytes que sobren al final del archivo se ignoran sin avisar (`while off + 8 <= len(data)`, `:52`).

**Los ids de llamada.** `CALLS` (`gputrace_read.py:20-45`) asocia 24 ids de llamada con un nombre de llamada Metal y una
certeza. Los ids son números negativos; el código no da razón de la numeración (**no verificado**). Los nombres son los del
API de Metal:

| Grupo | Llamadas | Certeza |
|---|---|---|
| Marcadores de depuración (3) | `pushDebugGroup` -16244, `insertDebugSignpost` -16245, `popDebugGroup` -16243 | `confirmado` |
| Dibujo (1) | `drawPrimitives` -16218 (una sola sobrecarga, `:88`) | `confirmado` |
| Estado del que depende un dibujo (13) | `setRenderPipelineState`, `setDepthStencilState`, `setStencilReferenceValue`, `setTriangleFillMode`, `setCullMode`, `setDepthClipMode`, `setDepthBias`, `setFrontFacingWinding`, `setBlendColor`, `setViewports`, `setScissorRects`, `setVertexBufferOffset`, `useResource` | `confirmado` |
| Estructura (3) | `renderCommandEncoder` -16353, `endEncoding` -16246, `commandBuffer` -16343 | `probable` |
| Otras (4) | `buffer contents` -10240, `drawMeshThreadgroups` -15416, `drawMeshThreadgroupsWithIndirectBuffer` -15415, `dispatchThreadgroups` -16327 | `probable` |

Las dos palabras están en español en el código (`"confirmado"`, `"probable"`) y se devuelven tal cual en el campo `certainty` de
`capture_summary`. `confirmado` significa «emparejada una por una con la lista de comandos de Xcode» (`:19`); `probable` es un
nombre que encaja pero no se emparejó. Un registro cuyo id no está en la tabla tiene `name: None`: se cuenta, se muestra por id y
firma, y nunca se nombra. Si una captura real usa ids que no están aquí (los dibujos indexados, instanciados, indirectos y de
malla tienen los suyos, según el comentario de `:88`) es **desconocido**.

### `capture_summary`

`tool_capture_summary(capture)` (`traces.py:151-157`) resuelve la ruta con `paths.allowed` (solo carpetas legibles) y llama a
`gputrace_read.summarize` (`:72-97`), que lee cada registro una vez y devuelve:

| Clave | Qué es |
|---|---|
| `capture` | el nombre del paquete, nunca su ruta |
| `records` | cuántos registros tiene el flujo |
| `command_buffers` | cuántos registros tienen el id -16343 (`commandBuffer`) |
| `render_encoders` | cuántos tienen el id -16353 (`renderCommandEncoder`) |
| `draw_primitives` | cuántos tienen el id -16218; los dibujos indexados, de malla e indirectos tienen otros ids y **no** se cuentan (`:88-89`) |
| `debug_groups` | las etiquetas de los registros `pushDebugGroup`, en orden (la primera cadena imprimible de cada uno; aquí sin recorte) |
| `signposts` | lo mismo para `insertDebugSignpost` |
| `pops` | cuántos registros `popDebugGroup` |
| `calls` | cada `(id, firma)` distinto con su `count`, `name` y `certainty`, el más frecuente primero |

La herramienta añade luego `calls_total` (cuántos pares `(id, firma)` distintos hay) y conserva solo los 100 primeros de `calls`
(`traces.py:155-156`). `calls_total` no es el número de registros: ese es `records`.

Ojo: `command_buffers` y `render_encoders` se cuentan desde ids que la tabla llama `probable`, y la respuesta no lo dice junto a
esos dos números (solo las entradas de `calls` llevan `certainty`). Léelos como probables
([hallazgo F3](#hallazgos-nuevos-en-el-codigo-sin-arreglar)).

### `capture_diff`

`tool_capture_diff(a, b)` (`traces.py:160-166`) llama a `gputrace_read.diff` (`:124-141`), que llama a `counts` (`:100-121`) por
cada captura. `counts` recorre los registros con una pila de grupos de depuración abiertos:

- En un `pushDebugGroup` abre un grupo con su etiqueta: la primera cadena imprimible, **cortada a 200 caracteres**; un push sin
  ninguna cadena de 3 o más caracteres se llama `(unnamed)`, así que todos esos grupos se funden (`:110-113`).
- En un `popDebugGroup` cierra el más interno; un pop sin nada abierto se ignora (`:114-116`).
- Cualquier otro registro cuyo nombre sea **confirmado** y no sea un signpost suma 1 al total de la captura para ese nombre y al
  grupo abierto más interno, si lo hay (`:117-120`). Los registros con ids `probable`, ids desconocidos, signposts y los tres
  marcadores de depuración **no se cuentan**.
- Los grupos con la misma etiqueta se suman, y un grupo que nunca se cierra corre hasta el final del flujo (`:100-105`, anclado
  por `tests/test_capture.py:156-161`, no corrida).

`diff` devuelve luego:

```text
{"captures": {"a": <nombre>, "b": <nombre>},
 "aligned_by": "debug_group" | "whole_capture",
 "totals": {<llamada>: {"a": n, "b": n, "delta": b - a}, ...},
 "groups": [{"name": <etiqueta>, "a": {<llamada>: n, ...}, "b": {<llamada>: n, ...}}, ...]}
```

- `totals` tiene una entrada por cada llamada confirmada que haga **alguna** de las dos capturas, incluso las de delta 0
  (`:130`, `:141`).
- `groups` lista solo los grupos donde **alguna llamada difiere**, con las cuentas de solo las llamadas que difieren
  (`:132-137`). Un grupo que existe en una sola captura se lista con `{}` del otro lado. Se ordenan por el tamaño del cambio
  total, el mayor primero, y luego por nombre (`:138`); la herramienta conserva 100 y añade `groups_total`
  (`traces.py:164-165`).
- `aligned_by` es `"whole_capture"` cuando ninguna captura tiene grupos de depuración; entonces `groups` está vacío y solo
  `totals` dice algo (`:140`).

El ejemplo publicado (flujos sintéticos, [prueba de la 0.26.0](../../evidence/v0.26.0.md#capture_diff-compares-two-captures)):

```text
aligned_by: debug_group
totals: drawPrimitives {a: 3, b: 5, delta: 2}, setRenderPipelineState {a: 1, b: 1, delta: 0}
groups: [{name: main, a: {drawPrimitives: 2}, b: {drawPrimitives: 4}}]
```

`shadow` no aparece porque no cambió, y da igual que fuera primero en una captura y segundo en la otra. La prueba que construye
este par exacto es `tests/test_capture.py:146-153` (no corrida).

### `capture_records`

`tool_capture_records(capture, offset=0, limit=100)` (`traces.py:169-174`) devuelve una página de los registros crudos, cada uno
como `{"offset", "size", "id", "signature", "name", "strings"}` con como mucho las 3 primeras cadenas, y `name` es `None` cuando
el id no está en `CALLS`. Sirve para ver lo que ve el lector cuando un resumen parece equivocado. La página se arma con **todos**
los registros y luego se corta (`:171-174`), así que cada página vuelve a leer el flujo entero, y el límite por defecto aquí es
100 contra 50 de `trace_query` (el texto del propio esquema dice «por defecto 50», `registry.py:19`, que es incorrecto para esta
herramienta; límite 8 más abajo).

El mismo lector es también un script: `python3 -I src/metal_gpu_trace/gputrace_read.py <capture.gputrace> [--records]` imprime
el resumen como JSON, o con `--records` una línea por registro (`gputrace_read.py:3`, `:144-155`). **No se corrió.**

### Lo que el lector no puede decirte

Todo esto se sigue de lo que devuelve el código (**confirmado**), no de una prueba con una captura real:

- **Ningún tiempo.** La salida tiene nombres, ids, cuentas y etiquetas. Una captura muestra qué se dibujó, no cuánto tardó; el
  tiempo de GPU sale de un `.trace` y de su resumen.
- **Ni recursos ni shaders.** Los argumentos no se decodifican: buffers, texturas y código de shader no están en la salida,
  solo las cadenas imprimibles de un registro.
- **Solo los dibujos de la única sobrecarga.** Una escena dibujada con dibujos indexados, instanciados, indirectos o de malla
  puede mostrar `draw_primitives: 0` y tener llamadas de dibujo igual (los ids de esos figuran como `probable` o no están).
- **Las cuentas de estructura son probables.** `command_buffers` y `render_encoders` salen de los ids `probable`.
- **`diff` ignora todo lo no confirmado.** Un cambio que solo toque llamadas `probable` o desconocidas no muestra diferencia.
- **La memoria es el tamaño del archivo.** `records` lee el archivo `capture` entero a memoria (`read_bytes`,
  `gputrace_read.py:50`), y `diff` lee dos. El tamaño de un archivo `capture` real nunca se vio aquí; **no medido**.

## Los datos de las familias de GPU

`gpu_family(name)` y los recursos `metal-trace://gpu-families` no tratan de una grabación. Devuelven los datos que Apple
publica de una familia de GPU o de un chip: `traces.family_of` (`:177-185`) acepta una clave de familia (`Apple7`) o un nombre
de chip (`M1 Pro`, `A15`) tras pasar a minúsculas y quitar espacios, y para un chip con el sufijo `ultra`, `max` o `pro` prueba
también el nombre sin él (`:182`). Los datos están en `src/metal_gpu_trace/data/apple-gpu-families.json`, que se lee una vez al
importar (`config.py:35`) y tiene cuatro familias: `Apple7`, `Apple8`, `Apple9` y `Apple10` (E7). Un nombre desconocido da
`unknown family or chip '<nombre>'; try one of Apple7, ... or a chip such as M1 Pro, M2, M3 Max, A17 Pro`
(`traces.py:192-194`). Los datos llevan las URL de su fuente (`:195-196`). Responden «qué puede hacer esta GPU», para leer una
traza contra ellos; este proyecto reformula las páginas de Apple y no las cita (README «Credits»). **No corrido.**

## Cuando falla

Cada herramienta de esta página corre dentro de `worker.call`, que convierte `ToolError`, `FileNotFoundError`, `ValueError`,
`RuntimeError` y `subprocess.TimeoutExpired` en un resultado con `isError: true` cuyo texto es el mensaje del error
(`worker.py:165-166`); cualquier otra excepción pasa a `internal error: <TipoDeExcepción>` (`:167-168`). Un resultado de más de
40 000 caracteres se rechaza con `the result has N characters; ask for a smaller page with limit` (`worker.py:162-163`,
`config.py:45`). Así que un fallo nunca detiene el servidor, y la persona recibe una frase.

| Qué sale mal | Qué recibe quien lee | Línea |
|---|---|---|
| El `.trace` no está (borrado tras el resumen) | `no recording at <nombre>: perf_record.sh deletes the .trace once its summary is written, unless KEEP_TRACE=1` | `perf_report.py:52-54` |
| Un nombre `trace` con otros caracteres, como una ruta fuera de las carpetas legibles | `<nombre> is outside the readable directories; add its directory to METAL_TRACE_READ` | `paths.py:20-21` |
| El `.trace` de un nombre es un enlace | `<nombre>.trace cannot be read` | `paths.py:88-89` |
| `xctrace` falla en una exportación | `xctrace export of <nombre> failed (exit N): <última línea de su error>`; una tabla cortada por el cierre conocido con `SIGTRAP` en un límite de fila se acepta | `perf_report.py:62-65`, `:60-61` |
| Una exportación tarda más de 600 s | el worker informa del `TimeoutExpired`; en `trace_count` la tabla recibe `rows: None` y las demás siguen | `perf_report.py:49`, `traces.py:144-146`, `worker.py:165` |
| `schema` o el nombre de una tabla contada tiene un carácter raro | `schema holds only letters, digits and '-'; trace_tables lists them` / `a table name holds only letters, digits and '-'; ...` | `traces.py:98-99`, `:131-132` |
| La tabla no existe en la traza (`trace_query`) | la exportación de una tabla ausente falla: **probable** `xctrace export ... failed`; `trace_count` dice `not in this trace` en cambio | `traces.py:100-101`, `:133-135` |
| `window_ms` no es un entero de 1 a 3 600 000 | `window_ms is a whole number of milliseconds from 1 to 3600000` | `traces.py:50` |
| `window_ms` sobre una tabla sin `start` ni `time` | `window_ms needs a table with a time column (start or time); trace_tables lists the tables and trace_query without window_ms shows the columns` | `traces.py:64-66` |
| Algunas filas no tienen tiempo usable (ventanas) | no es un error: las filas se cuentan en `skipped_rows` | `traces.py:69-73`, `:108-109` |
| `perf_export_trace` de una corrida desconocida | `no run <nombre>; perf_runs lists them` | `paths.py:33-41` |
| `perf_export_trace` de una corrida sin tabla por fotograma | `<run> has no per-frame file; record it again` | `traces.py:16-17` |
| La tabla por fotograma está dañada (una celda no es número, falta una columna, un gzip malo) | `<nombre del archivo> cannot be read; record it again`; no se escribe nada | `traces.py:26-27` |
| La ruta de la captura está fuera de las carpetas legibles | `<nombre> is outside the readable directories; add its directory to METAL_TRACE_READ` | `paths.py:20-21` |
| El paquete no tiene archivo `capture` (summary, diff) | `FileNotFoundError: <nombre del paquete> has no capture file`, sin carpeta | `gputrace_read.py:67-68` |
| Un registro mide menos de 8 o se pasa del final | `ValueError: <nombre del paquete>: record at 0x<desp> has size <n>; the stream is not MTSP as expected` | `gputrace_read.py:54-55` |
| `capture_records` sobre un paquete sin archivo `capture`, o sobre una ruta que es un archivo | **probable:** el `OSError` crudo de `read_bytes` (ver hallazgo F1) | `traces.py:173`, `gputrace_read.py:50` |
| Un resultado es demasiado grande (una captura con muchísimos grupos de depuración, una página de filas anchas) | `the result has N characters; ask for a smaller page with limit` | `worker.py:162-163` |

Nada de esto se **reprodujo**: los textos de error se leen del código, y los de captura los ancla
`tests/test_capture.py:86-97`, `:103-112`, `:115-132` y `:170-178` (no corridas).

## Límites conocidos

Cada punto es un límite del comportamiento de hoy, escrito, no arreglado aquí.

| # | Límite | Dónde | Estado |
|---|---|---|---|
| 1 | El repositorio no tiene ningún `.trace` ni `.gputrace` real: ninguna herramienta de esta página se ejecutó, y la única prueba publicada de `capture_diff` es sobre flujos sintéticos | E3, `docs/evidence/v0.26.0.md` | No reproducido |
| 2 | Los ids de llamada y la disposición de un `.gputrace` son afirmación del código; la investigación del 2026-11-15 dice que no había captura real, y el código dice que sus ids salen de una | `gputrace_read.py:7-8`, `:19` | Contradicción, ver F5 |
| 3 | `capture_diff` cuenta solo 17 ids confirmados; un cambio en dibujos indexados, indirectos o de malla, o en encoders, le es invisible | `gputrace_read.py:20-45`, `:117` | Confirmado |
| 4 | Cada página de `trace_query` y `trace_count` vuelve a correr `xctrace export`, y una página se corta de una lista con todas las filas en memoria | `traces.py:101`, `:111-112` | Confirmado; coste sin medir |
| 5 | Una tabla se lee solo de la **primera corrida** de la traza (`run[@number="1"]`) | `traces.py:100`, `perf_report.py:92` | Confirmado |
| 6 | Un `.trace` se puede leer solo mientras existe: tras una grabación normal se borra, y `trace_query` lo dice | `perf_report.py:52-54` | Confirmado |
| 7 | `perf_export_trace` tiene una rebanada por fotograma en una pista, y deja fuera los fotogramas que el resumen dejó fuera | `traces.py:19-25` | Confirmado |
| 8 | El tamaño de página tiene dos valores por defecto: `registry.py:19` dice «por defecto 50» para toda herramienta paginada, pero `capture_records` tiene `limit=100` | `traces.py:169`, `registry.py:19`, `:177` | Confirmado |
| 9 | El resumen de una captura con muchos grupos de depuración no tiene `limit`, así que puede pasar el tope de 40 000 caracteres sin forma de pedir menos | `traces.py:151-157`, `worker.py:162-163` | Probable (F2) |
| 10 | La unidad de una celda de tiempo en las páginas de `trace_query` (el texto que muestra Instruments) puede diferir de los nanosegundos que usan las ventanas | `traces.py:68`, `:111` | Probable |
| 11 | No se midieron ni el tamaño de un archivo `capture` real ni la duración de una exportación de una tabla real | | No reproducido |

## Hallazgos nuevos en el código (sin arreglar)

Encontrados al escribir esta página. Cada uno es algo que el código hace hoy; ninguno es una decisión. Quedan para que decida el
dueño.

| # | Hallazgo | Dónde | Estado |
|---|---|---|---|
| F1 | `capture_records` abre `<capture>/capture` por su cuenta y no pasa por `stream_of`, así que un paquete sin archivo `capture` lanza el `OSError` de `read_bytes`, cuyo texto lleva la **ruta completa**, y una ruta que es un archivo lanza `NotADirectoryError`, un `OSError` que no es `FileNotFoundError` y por eso se informa como `internal error: NotADirectoryError`. El changelog dice que los errores de `capture_records` ya no incluyen la carpeta, y las pruebas cubren solo `summarize` y `diff` | `traces.py:173`, `gputrace_read.py:50` y `:64-69`, `CHANGELOG.md` (la entrada de `capture_diff` de la 0.26.0) | Probable (código leído, no corrido) |
| F2 | `capture_summary` no tiene `limit` y `debug_groups` y `signposts` no tienen tope, así que una captura con miles de grupos etiquetados puede dar un resultado de más de 40 000 caracteres, y el error le dice a quien llama que pida una página menor con `limit`, que esta herramienta no tiene | `gputrace_read.py:90-91`, `traces.py:151-157`, `registry.py:172`, `worker.py:162-163` | Probable |
| F3 | `command_buffers` y `render_encoders` del resumen salen de ids `probable` y la respuesta no los marca como tales | `gputrace_read.py:86-87`, `:38-40` | Confirmado |
| F4 | `capture_summary` no corta nada y `counts` corta una etiqueta a 200 caracteres, así que la misma etiqueta puede verse distinta en el resumen (`debug_groups`) y en el diff (`groups[].name`) | `gputrace_read.py:81`, `:111` | Confirmado |
| F5 | El módulo dice que sus ids se emparejaron con una captura cuya lista de comandos mostraba Xcode en macOS 27.0.1; la prueba de la 0.26.0 y la investigación del 2026-11-15 dicen que no había captura real. Cuál sea cierta decide qué significa «confirmado» | `gputrace_read.py:7-8`, `:19`; `docs/evidence/v0.26.0.md`; la nota de investigación del 2026-11-15 | Contradicción, necesita al dueño |
| F6 | `trace_query` con `pid` devuelve todas las filas de una tabla que no tiene columna `process`, mientras la herramienta dice «conserva solo las filas de este proceso» | `traces.py:102-103`, `registry.py:167` | Confirmado |
| F7 | `trace_query` arma la lista completa de filas antes de cortar una página, así que una tabla de millones de filas se guarda en memoria en cada llamada | `traces.py:111-112` | Confirmado; tamaño sin medir |
| F8 | El docstring de `perf_export_trace` dice que un fotograma con encoders en paralelo «puede verse más corto de lo que tardó»; el largo es una suma (`gpu_ms_total`), que para trabajo en paralelo es mayor que el tiempo transcurrido, como dice la [guía de resumir](./resumir-y-analizar.md#el-tiempo-de-gpu-por-fotograma-es-una-suma-sobre-canales) | `traces.py:10-13` | Probable (redacción) |
| F9 | `records` ignora en silencio menos de 8 bytes finales, y un archivo que no empieza con `MTSP` se analiza desde el byte 0 en vez de rechazarse | `gputrace_read.py:51-52` | Confirmado |
| F10 | `trace_count` devuelve los nombres de todos los procesos de la traza (`by_process`), no solo los del programa | `traces.py:142` | Confirmado |

## Tocarlo sin romperlo

- Una llamada Metal nueva: añade su id a `CALLS` como `"probable"` primero. Solo cámbialo a `"confirmado"` tras emparejarlo con una
  captura real, porque `capture_diff` empieza a contarlo en cuanto se confirma, y todo diff anterior cambia. Añade un registro con
  ella a una prueba de `tests/test_capture.py` (los ayudantes `record` y `capture` arman un flujo).
- Una herramienta nueva que lea una captura: pasa por `paths.allowed` y `stream_of`, nunca `read_bytes` sobre una ruta propia
  (hallazgo F1), y deja en cada mensaje el nombre del paquete, no su carpeta.
- Una herramienta nueva que lea un `.trace`: toma `trace` con `paths.trace_path`, pasa el nombre de la tabla por la misma
  comprobación de letras, dígitos y guion, lee con `perf_report.rows` (borra el archivo exportado) y conserva el `finally` que
  lo cierra (`traces.py:113-114`).
- Un campo nuevo de una ventana: `windows_of` guarda sus sumas en nanosegundos y convierte una sola vez al final (`:85-87`);
  mantenlo así para que el redondeo no se acumule.
- `traces.py` no debe leer un `<run>.json`: los resúmenes son de `analysis.py`. El único archivo parecido a un resumen que toca
  es la tabla por fotograma, a través de `tables.py`.
- Añade la herramienta a `registry.py` (nombre, esquema, pistas) y a `PAGED_TOOLS` (`:9`) si devuelve `page()`; el archivo
  `tests/golden/protocol.json` es el contrato con los clientes y hay que actualizarlo.

## Evidencia: los comandos y su salida real

Recogida el 2026-11-16 en un Mac con Apple silicon. Todos los comandos solo leen. La carpeta de corridas es `perf-runs/` del clon
(una carpeta local, ignorada, que no se publica; guarda dos corridas terminadas y sus tablas). La sesión que la recogió podía
correr `rg`, `sed`, `awk`, `jq`, `wc` y `find` y no podía correr Python, `xctrace` ni `xxd`: ninguna herramienta de esta página
se ejecutó, y E5 y E6 son las fórmulas del código evaluadas a mano.

### E1 Dónde se registra cada herramienta

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

### E2 Cuántos ids de llamada son confirmados y cuántos probables

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

17 + 7 = 24 ids, el número que usa la página. Los 17 son los tres marcadores de depuración, `drawPrimitives` y las trece llamadas de
estado.

### E3 El repositorio no tiene ninguna traza ni captura que leer

```text
$ find . -name '*.gputrace' -not -path './node_modules/*' -not -path './.git/*' | wc -l
       0
$ find . \( -name '*.trace' -o -name '*.chrome-trace' \) -not -path './node_modules/*' -not -path './.git/*' | wc -l
       0
```

Las pruebas construyen las suyas: `tests/test_capture.py:18-27` escribe una carpeta `.gputrace` con un archivo `capture` de
`MTSP`, 4 bytes en cero y registros, y `tests/test_traces.py:11-16` escribe una tabla XML. Ninguna es un archivo del
repositorio.

### E4 Las tablas por fotograma de las dos corridas reales

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
[guía de resumir](./resumir-y-analizar.md#un-ejemplo-primero) (la segunda dejó de presentar a los 3.6 s). Las dos tablas son
`.csv` planos, anteriores a la compresión de la 0.27.0; `tables.find` lee cualquiera de los dos formatos.

### E5 `perf_export_trace` sobre la primera fila, a mano

```text
$ sed -n 2p perf-runs/a2-proof-first_20261115-085621.frames.csv | awk -F, '{printf "{\"name\":\"GPU frame\",\"ph\":\"X\",\"pid\":1,\"tid\":1,\"ts\":%s,\"dur\":%s,\"args\":{\"frame\":%d,\"compute\":%s,\"fragment\":%s,\"vertex\":%s}}\n",$2*1000,$6*1000,$1,$3,$4,$5}'
{"name":"GPU frame","ph":"X","pid":1,"tid":1,"ts":1267790,"dur":13561.2,"args":{"frame":6,"compute":0.0243,"fragment":1.7417,"vertex":11.7952}}
```

Es `awk` haciendo la aritmética de `traces.py:22-25` (`start_ms × 1000`, `gpu_ms_total × 1000`, el prefijo `gpu_ms_` recortado), no la
herramienta. El resultado en coma flotante de Python puede diferir en las últimas cifras (por ejemplo `13561.2` contra
`13561.199999999999`); **no reproducido** con la herramienta. La misma aritmética la afirma para una tabla de dos filas
`tests/test_analysis.py:329-332` (`ts == 10500.0`, `dur == 600.0`), no corrida. La suma 0.0243 + 1.7417 + 11.7952 es 13.5612, el
`gpu_ms_total` de la fila.

### E6 Las ventanas de `trace_query`, a mano

Tres filas con `start` y `duration` en ns: (1 000 000, 2 000 000), (9 000 000, 1 000 000), (12 000 000, 4 000 000), y
`window_ms=10`. Una ventana es `start // 10 000 000`:

```text
1 000 000 // 10 000 000 = 0     9 000 000 // 10 000 000 = 0     12 000 000 // 10 000 000 = 1
ventana 0: start_ms 0 x 10 = 0,   count 2, duración (2 000 000 + 1 000 000) / 1 000 000 = 3.0 ms
ventana 1: start_ms 1 x 10 = 10,  count 1, duración 4 000 000 / 1 000 000 = 4.0 ms
```

Son las filas y la respuesta que afirma `tests/test_traces.py:42-48`
(`[{"start_ms": 0, "count": 2, "duration_ms": 3.0}, {"start_ms": 10, "count": 1, "duration_ms": 4.0}]`), no corrida; las sumas de
arriba son las fórmulas de `traces.py:74-87` evaluadas a mano.

### E7 Los límites y los datos de familias de GPU que el código impone

```text
$ rg -n 'MAX_LIMIT|MAX_TEXT' src/metal_gpu_trace/config.py src/metal_gpu_trace/worker.py src/metal_gpu_trace/registry.py | cut -c1-140
src/metal_gpu_trace/registry.py:19:        "limit": {**I, "description": f"rows per page, default 50, at most {config.MAX_LIMIT}"}}
src/metal_gpu_trace/config.py:43:MAX_LIMIT = 500
src/metal_gpu_trace/config.py:45:MAX_TEXT = 40_000
src/metal_gpu_trace/worker.py:162:        if len(text) > config.MAX_TEXT:
$ jq -r '.families|keys|join(",")' src/metal_gpu_trace/data/apple-gpu-families.json
Apple10,Apple7,Apple8,Apple9
```

### E8 Lo que guardó una grabación real (una medida del 2026-11-15, no repetida)

La nota de investigación del proyecto del 2026-11-15 (interna, no publicada) registra, para una grabación de 8 segundos del
programa de prueba `drawstress` en el nivel `deep`, hecha con `xctrace` 27.2 en un Apple M1 Pro con macOS 27.0.1 y 170 MB en
disco: **85 tablas exportadas, 59 con filas y 26 vacías**, y, para la tabla de intervalos de GPU, el reparto de su duración
sumada por proceso. Los procesos más activos fueron el programa de prueba y, detrás, otros programas de la máquina (un ayudante
de navegador y el servidor de ventanas): la razón de [los nombres en `by_process`](#trace-count-que-tablas-tienen-filas). Esas
cifras **no se volvieron a medir** para esta página; la grabación no está en el clon.

### Qué no se reprodujo

- Cualquier llamada a `xctrace`, y por tanto `trace_tables`, `trace_count` y `trace_query` sobre un `.trace` real (no había
  ningún `.trace` a mano, E3).
- Cualquier herramienta de `traces.py` o `gputrace_read.py`: la sesión que escribió esta página no podía correr Python.
- Un volcado hexadecimal de un registro de un `.gputrace` real, o de uno sintético (`xxd` no se pudo correr): la disposición de
  arriba es la del código.
- Abrir un `.chrome-trace` en Perfetto o en `chrome://tracing`.
- Las pruebas que nombra esta página (se leyeron, no se corrieron).
- El coste de una exportación de `xctrace` de una tabla grande, y el tamaño de un archivo `capture` real.

## Véase también

- [Resumir y analizar](./resumir-y-analizar.md): cómo `perf_report.py` lee el mismo `.trace` para el resumen, y la regla de
  `unpresented` que también da forma a la tabla por fotograma.
- [Datos y su ciclo de vida](./datos-y-su-ciclo-de-vida.md): cuándo existen un `.trace` y un `.chrome-trace` y qué los borra.
- [Grabar](./grabar.md): cómo se hace el `.trace` y por qué se borra.
- [How it works](../../guides/how-it-works.md): qué capa llama a cuál.
- [Prueba de la 0.26.0](../../evidence/v0.26.0.md#capture_diff-compares-two-captures): el ejemplo publicado de `capture_diff`, sobre
  flujos sintéticos.
