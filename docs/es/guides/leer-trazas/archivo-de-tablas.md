# El archivo de tablas: consultar una grabación después de borrar su `.trace`

**Lector:** personas que llaman a `trace_tables`, `trace_count` o `trace_query`, o que cambian `tabledb.py`. Revisado el 2026-11-16.

English: [The tables file: question a recording after its `.trace` is gone](../../../guides/reading-traces/tables-file.md)

> **En corto:** cada grabación deja `<run>.tables.sqlite` junto a su resumen. Guarda las tablas que el resumen leyó, así que
> las tres herramientas de tablas siguen respondiendo después de borrar el `.trace` (cientos de MB), y `trace_query` puede
> filtrar, ordenar y agrupar sin que escribas SQL. `perf_runs` dice `tables_kept: true` en las corridas que lo tienen.

## Qué se guarda

Las tablas que `perf_report` ya lee para el resumen: los intervalos de GPU, la memoria de Metal, el estado de rendimiento, y
las opcionales que tenga la traza (encoders, compilador de shaders, térmica, CPU, asignaciones de recursos, errores de command
buffer, derrames de shaders), más `gpu-counter-info` cuando la grabación usó contadores de GPU. Las muestras de los contadores (`gpu-counter-value`) no se
guardan: una grabación de 6 s tuvo 2 955 137, 229 MB de un archivo de 233 MB, y el resumen ya guarda la media, el p95 y el
máximo de cada contador. Las tablas que solo
`trace_count` nombra por defecto (como `time-profile`) no se guardan; `trace_count` dice «not in this trace's tables file»
para ellas (no está en el archivo de tablas de esta traza).

Cada tabla tiene las columnas que nombra la exportación, sin suponer ninguna. Una columna `c` se guarda como el texto de la
celda (un entero o un decimal cuando el texto es exactamente uno, así que `duration > 1000000` compara números; los tiempos
van en nanosegundos), y el valor con formato que muestra Instruments es lo que devuelve `trace_query`. Una columna `process`
guarda además el id del proceso, que es lo que filtra `pid`.

Las columnas de línea de comandos reciben la misma limpieza que `process.arguments` del resumen, y cualquier `/Users/<nombre>`
pasa a `~`, así que el archivo no guarda ninguna carpeta de usuario. Sí guarda nombres de procesos, así que consérvalo en local
igual que el `.trace`.

## Qué fuente responde

| La corrida tiene | `trace_tables`, `trace_count`, `trace_query` leen |
|---|---|
| su `.trace` (`KEEP_TRACE=1`) | el `.trace`, como antes |
| solo el archivo de tablas | el archivo de tablas |
| ninguno de los dos | un error que nombra los dos archivos |

`where`, `columns`, `order_by`, `descending`, `group_by` y `aggregates` leen siempre el archivo de tablas, aunque el `.trace`
siga ahí; sin él, el error lo dice. Una corrida grabada antes de que esto existiera sigue funcionando por su resumen y sus
tablas comprimidas, como antes.

## Filtrar

```json
{"trace": "run1", "schema": "metal-gpu-intervals",
 "where": [{"column": "duration", "op": ">", "value": 16600000}],
 "columns": ["start", "duration", "channel-name"], "order_by": "duration", "descending": true, "limit": 20}
```

```json
{"trace": "run1", "schema": "metal-gpu-intervals", "group_by": ["channel-name"],
 "aggregates": [{"fn": "count"}, {"fn": "avg", "column": "duration"}], "order_by": "avg_duration", "descending": true}
```

- `where`: los filtros se unen con Y; `op` es uno de `=`, `!=`, `<`, `<=`, `>`, `>=`; `value` es un texto o un número (`null`
  solo con `=` y `!=`). Una columna se compara tal como se guardó, así que una celda que solo tiene valor con formato (un
  `process`) se encuentra con `pid`, no con `where`.
- `group_by`: agrupa por el valor con formato; cada agregado se llama `fn_columna` (`avg_duration`), y `count` para un conteo
  simple. `order_by` toma entonces una columna de grupo o el nombre de un agregado.
- `window_ms` se combina solo con `where` y `pid`. La paginación (`total`, `offset`, `rows`, `next_offset`) es la misma en
  todos los modos.

No hay SQL: los nombres de columna tienen que ser de la tabla, los operadores y las funciones salen de las listas de arriba, y
los valores van como parámetros ligados. El archivo se abre en solo lectura, un enlace se rechaza, y todo lo que no sea un
`SELECT` se niega.

## Disco

Con `METAL_TRACE_MAX_DISK_MB` activo, la cuota borra en este orden, y dentro de cada tipo primero el más antiguo: el `.trace`,
el `.chrome-trace`, el `.tables.sqlite` y luego las tablas comprimidas. El Chrome trace se recupera desde la tabla por
fotograma; el archivo de tablas solo sirve para preguntas puntuales; las tablas comprimidas alimentan `perf_compare` con
`skip_s` y `perf_export_trace`. `KEEP_RUNS=N` quita el archivo de tablas de una corrida vieja junto con el resto de sus
archivos. El archivo de la corrida actual nunca se borra. `PERF_TABLES=0` no lo escribe.

Ver [ADR-0007](../../../adr/0007-sqlite-tables-beside-the-compressed-tables.md).

Volver al [índice](./index.md).
