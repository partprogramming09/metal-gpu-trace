# Datos y su ciclo de vida

**Lector:** personas que cambian el grabador o el análisis, o que necesitan saber qué deja una grabación en disco, dónde vive y quién la borra. Revisado el 2026-11-16.

English: [Data and its lifecycle](../../guides/data-and-lifecycle.md)

Esta página sigue los datos de una grabación desde que se pide hasta que se borra. No repite
[How it works](../../guides/how-it-works.md) (qué capa llama a cuál); amplía la parte que dice dónde viven las
grabaciones. Es la versión en español de la guía en inglés: mismo contenido, mismos diagramas y la misma evidencia
(los comandos y sus salidas no se traducen).

Cómo leer las etiquetas: cada afirmación técnica es **confirmada** (con `archivo:línea`, comprobada con `rg` o `sed` el
2026-11-16 contra el árbol de trabajo, que es la 0.27.2 más las entradas `[Unreleased]` de `CHANGELOG.md`), **probable**
(leída en el código pero no ejecutada aquí) o **especulación** (una conjetura sobre el porqué). Las líneas se mueven
cuando cambia el código: busca el nombre, no solo el número. Cada cifra viene con el comando que la produjo, en
[Evidencia](#evidencia-los-comandos-y-su-salida-real). Donde un comando no se pudo correr dice **no reproducido**.

## Un ejemplo primero

Supón que un agente graba un programa durante 20 segundos con la etiqueta `mygame`. Unos minutos después la carpeta
de grabaciones contiene archivos como estos (una carpeta real de otra grabación del mismo tipo, recortada, sin su
dueño y con el nombre cambiado; el comando es E1):

```text
baselines.json
probe-d3d12_20261018-003026.json
v070-d3d12_20261018-021158.frames.csv
v070-d3d12_20261018-021158.json
v070-d3d12_20261018-021158.metal_memory.csv
v070-d3d12_20261018-021158.rss.csv
v070-d3d12_20261018-021158.trace          <- una carpeta, 259 MiB
```

Todo lo que pertenece a una grabación comparte un **stem** (el prefijo común del nombre): la etiqueta, un guion bajo y
la hora de inicio (`<label>_<YYYYMMDD-HHMMSS>`, `perf_record.sh:26`). El stem es lo único que une los archivos: no hay
base de datos ni índice. El `.json` pequeño es el **resumen** (los números que lee un agente); los demás archivos son
los datos con que se calculó, y el `.trace` es la grabación cruda de Instruments, que ocupa casi todo el tamaño de la
carpeta (E2: 259 MiB de 259 MiB).

## Por qué los datos tienen esta forma

| Decisión | Por qué | Alternativas descartadas |
|---|---|---|
| Un resumen JSON pequeño por corrida | Es lo que se compara, se comparte y se pega en una incidencia, así que debe ser pequeño y sin nombres de máquina, UUID ni rutas absolutas ([What this is about](../../guides/index.md#what-to-know-before-touching-it)) | Dejar los números solo en el `.trace`: pesa 259 MiB y hace falta Instruments para abrirlo |
| Datos pesados en archivos hermanos con el nombre del stem | Una herramienta que necesita los fotogramas lee `<stem>.frames.csv.gz`; la que solo necesita el resumen no los toca. Borrar lo pesado de una corrida vieja deja el resumen legible | Un solo archivo por corrida: podar significaría reescribirlo |
| Sin base de datos ni índice | El servidor usa solo la biblioteca estándar en Python 3.9 ([ADR-0003](../../adr/0003-python-3-9-floor.md)) y una carpeta se copia, se sube a una rama o se borra a mano | Un archivo de base de datos (por ejemplo SQLite): **especulación** de que se dejó fuera por la misma razón; ningún ADR recoge la decisión |
| `.trace` borrado por defecto | Pesa de decenas a cientos de MB y el resumen ya tiene sus números (`perf_record.sh:162-163`); se conserva con `KEEP_TRACE=1` o con el nivel `deep` cuando se quiere `trace_query` o Instruments | Conservar todos los trazos: la carpeta crecía sin tope ([ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md)) |
| Tablas como `.csv.gz` | Las mismas filas en una fracción del tamaño, y `tables.py` lee los dos formatos para que las corridas antiguas sigan funcionando ([ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md)) | CSV sin comprimir (pesado), `zlib` crudo (ninguna herramienta estándar lo abre), podar corridas enteras (pierde el resumen) |
| Dos mecanismos de retención | Uno cuenta corridas (`KEEP_RUNS`), otro cuenta bytes (`METAL_TRACE_MAX_DISK_MB`); responden a preguntas distintas y borran cosas distintas (ver [Retención](#retencion-dos-mecanismos-que-no-se-mezclan)) | Una sola regla: el ADR descartó podar corridas enteras por tamaño porque pierde el resumen |

## Dónde vive cada cosa

| Qué | Dónde | Quién lo fija |
|---|---|---|
| La carpeta de corridas, servidor MCP | `./perf-runs` del directorio de trabajo del servidor | `METAL_TRACE_OUT` (`config.py:16`); un archivo de proyecto la sustituye (`project.py:188`) |
| La carpeta de corridas, `perf_record.sh` lanzado a mano | `PERF_OUT`, si no `<clone>/logs/perf` si esa carpeta existe, si no `./perf-runs` | `perf_record.sh:28-29` |
| Carpetas que las herramientas pueden leer además | `METAL_TRACE_READ`, separadas por `:` | `config.py:17` |
| Caché de programas de prueba | `~/Library/Caches/metal-gpu-trace` (Windows: `%LOCALAPPDATA%\metal-gpu-trace`) | `config.py:37-40` |
| El candado de grabación | `<cache>/recording.lock/` | `METAL_TRACE_LOCK` o `PERF_LOCK` (`config.py:42`, `perf_record.sh:42`) |
| Temporales `.ktrace` de Instruments | `$TMPDIR/instruments*.ktrace`, se borran al terminar el script | `perf_record.sh:63-69` |

Los dos valores por defecto de la carpeta de corridas son distintos: una grabación lanzada por el servidor y otra
lanzada a mano desde un clon no caen en el mismo sitio (confirmado, líneas de arriba).

## Qué deja una grabación en disco

| Archivo | Qué contiene | Lo escribe | Tamaño (E1, E2) | Lo lee |
|---|---|---|---|---|
| `<run>.json` | El resumen (sección siguiente) | `perf_report.py:836`, reescrito por `recording.py:350` | 4,9 KiB | Todas las herramientas de análisis (`analysis.py`), `perf_runs` |
| `<run>.frames.csv.gz` | Una fila por fotograma de GPU presentado; `.csv` sin comprimir antes de la 0.27.0 | `perf_report.py:831` (macOS), `perf_record_windows.py:847` (Windows) | 56 KiB sin comprimir, 20 s | `analysis.read_frames` (`analysis.py:508`), la exportación a Chrome trace (`traces.py:15`) |
| `<run>.metal_memory.csv.gz` | Memoria de Metal asignada a lo largo del tiempo | `perf_report.py:745` | 418 KiB sin comprimir | `analysis.py:527` |
| `<run>.rss.csv` | La memoria residente del programa, una vez por segundo | el muestreador de `perf_record.sh:105-113`; `perf_record_windows.py:669` en Windows | 367 bytes | `perf_report.py:749-753` la integra en `process_rss_mib` |
| `<run>.agx.csv` | Los contadores del controlador de la GPU para toda la GPU, una vez por segundo | el muestreador de `perf_record.sh:106-114` | 575 bytes | `perf_report.py:754-756` la integra en `gpu_activity` |
| `<run>.trace/` | El paquete de Instruments (una carpeta) | `xctrace`, `perf_record.sh:140-151` | 259 MiB | `trace_query`, `trace_tables`, Instruments |
| `<run>.chrome-trace` | Los fotogramas como Chrome trace, solo cuando se llama a la herramienta de exportación | `traces.py:28` | no medido aquí | el visor de trazas de un navegador |
| `<run>.presentmon.csv` | Las filas de PresentMon (solo Windows) | `perf_record_windows.py:650` | no medido aquí | `perf_record_windows.py` |
| `baselines.json` | Referencias con nombre: copias de varios resúmenes | `analysis.py:282` | 10 KiB, 1 línea base de 3 corridas (E7) | `load_baselines`, `analysis.py:254` |
| `.metal-gpu-trace-runs` | La marca de la carpeta: un archivo simple con el nombre del proyecto | `project.py:198` | 8 bytes | `project.mark_owner`, `project.py:109` |
| `panel.json` | Lo dejó la 0.24.0, cuyo panel se quitó ([ADR-0005](../../adr/0005-remove-the-panel.md)) | nadie ahora | ninguno en esta máquina | solo se omite: `paths.py:10`, `analysis.py:52` |

Archivos que existen solo mientras corre una grabación: `<run>.validation.log` (con la validación de Metal activada, se
borra en `perf_record.sh:161`) y los restos de una escritura de tabla interrumpida (`<table>.csv.gz.<hex>.tmp`, ver
[Cuando falla](#cuando-falla)).

Cuáles de estos borra cada poda es la primera figura.

![Una tabla con una fila por tipo de archivo de una corrida y cuatro columnas: quién lo escribe, qué pasa al final de una corrida, qué hace KEEP_RUNS y qué hace METAL_TRACE_MAX_DISK_MB. Solo KEEP_RUNS borra alguna vez un resumen; baselines.json y la marca de la carpeta no se borran nunca.](/diagrams/data-files-per-run.png)
*Figura 1. Los archivos de una corrida y qué borra cada poda. Fuente HTML: `docs/diagrams/data-files-per-run.html`. Las etiquetas del diagrama están en inglés, como el resto de las páginas publicadas.*

## El resumen, clave por clave

El resumen es un objeto JSON cuyas claves escriben tres piezas de código en secuencia:

1. `perf_report.summarize` lo construye a partir del `.trace` (`perf_report.py:648-835`) y escribe el primer `.json`.
2. `recording.finish` añade `layer`, `context`, `tier` y `retention`, reconstruye `common` y reescribe el archivo
   (`recording.py:337-351`).
3. En Windows, `perf_record_windows.py` construye un objeto distinto y más pequeño (`perf_record_windows.py:887-917`) y
   luego `finish` hace el paso 2 sobre él.

### Las generaciones

`schema_version` dice qué generación es un resumen (`metrics.py:10`, lo lee `metrics.schema_of`, `metrics.py:13`). Un
resumen sin ella es de la generación 1, y todas las herramientas siguen leyendo las generaciones 1, 2 y 3 (`CHANGELOG.md`,
0.27.0, Changed: un resumen sin ella es la versión 1 y toda herramienta lo sigue leyendo).

| Generación | Qué añadió | Publicada en |
|---|---|---|
| 1 | Las claves originales | antes de la 0.27.0 |
| 2 | Tablas comprimidas, `tier`, `retention` (`metrics.py:9`) | 0.27.0 (`CHANGELOG.md`) |
| 3 | El bloque `common` (`metrics.py:9`) | `[Unreleased]` en `CHANGELOG.md`; el código ya la escribe |

**Todos los resúmenes reales de la máquina donde se comprobó esta página son de la generación 1** (E3: sin
`schema_version`, sin `common`, sin `tier`, sin `retention`), porque se grabaron antes de la 0.27.0. Por eso las listas
de claves de abajo salen del código, no de un archivo real de generación 3. Un resumen de generación 3 **no se
reprodujo** (hace falta una grabación en macOS con Instruments). Aun así, con los archivos de generación 1 se comparó la
tabla de la [Evidencia E3](#e3-claves-de-resumenes-reales): cada clave de un archivo real está en las listas de abajo.

### Claves de un resumen de macOS: siempre presentes

| Clave | Qué contiene | Escrita en | La lee |
|---|---|---|---|
| `schema_version` | La generación (primera clave) | `perf_report.py:648` | `analysis.py:74` por medio de `metrics.schema_of` |
| `label` | La etiqueta de la grabación | `perf_report.py:649` | `analysis.py:643` |
| `trace` | El nombre del `.trace`, que se conserva aunque el archivo se borre | `perf_report.py:650` | nada en `src/` lee la clave (`rg`); `perf_runs` comprueba el archivo (`analysis.py:79`) |
| `process` | `name`, `pid`, `termination-reason`, `arguments` (hechos compartibles por `public_arguments`) | `perf_report.py:651-652` | `analysis.py:74` (`arguments`), `recording.py:432` (`termination-reason`) |
| `device` | `platform`, `model`, `memory-size`, `os-version`; el nombre de la máquina y su UUID se dejan fuera a propósito | `perf_report.py:654` | `analysis.py:138`, `metrics.py:55` |
| `template` | El nombre de la plantilla de Instruments | `perf_report.py:659` | `analysis.py:759` |
| `duration_s` | Segundos grabados | `perf_report.py:660` | `analysis.py:673` |
| `machine` | Chip, núcleos, RAM, macOS, `screen_locked` | `perf_report.py:661` | `analysis.py:195` (pantalla bloqueada) |
| `missing_tables` | Tablas de Instruments que el trazo no tenía | `perf_report.py:664` | ningún lector en `src/` (`rg`); es para quien lee el resumen |
| `gpu` | `intervals`, `frames`, `frame_gpu_ms`, `per_channel_ms`, `frame_interval_ms`, `start_latency_ms`, `fps_estimate` y las claves de ritmo de abajo | `perf_report.py:709` | `perf_runs`, comparar, diagnosticar, puertas (`analysis.py` en general) |
| `encoders` | Encoders y búferes de comandos por fotograma, los encoders más cortos, las 20 etiquetas principales | `perf_report.py:728` | `analysis.py:223`, `:702` |
| `gpu_idle` | Cuándo esperó la GPU | `perf_report.py:729` | `analysis.py:231`, `:715` |
| `gpu_performance_state_share` | Porcentaje de tiempo por estado de reloj de la GPU; `{}` si no hay | `perf_report.py:771` | `analysis.py:144` |
| `hitches` | `count`, `per_minute`, `threshold_ms`, `causes`, los 20 `worst` | `perf_report.py:822` | `analysis.py:574`, `:773` |
| `common` | `frame_pacing`, `memory_pressure`, `boundness`, `submission_overhead`, `api`, construido por `metrics.common_block` | `perf_report.py:835`, reconstruido en `recording.py:343` | `analysis.py:153` |
| `layer` | La capa de traducción: Wine con sus anulaciones y hashes de DLL, o `none` (nativo), `unknown` (adjuntado), MoltenVK, Rosetta | `recording.py:341` | `recording.py:208`, `metrics.layer_label` |
| `context` | `git` (commit corto y `dirty`, o nulo) e `instruments` (la versión, o nulo) | `recording.py:341`, `run_context` en `recording.py:168` | `recording.py:195` |

Un resumen escrito por `perf_report.py` lanzado a mano no tiene `layer` ni `context`: esas dos las pone
`recording.finish` (confirmado: las asignaciones solo están en `recording.py:341`).

Las claves de ritmo dentro de `gpu` salen de `frame_pacing` (`perf_report.py:253`) y están presentes solo cuando hay
intervalos entre fotogramas: `fps_1pct_low` y `fps_01pct_low` (nulo salvo que haya 100 y 1000 fotogramas),
`stutter_rate_pct` y `frame_jitter_ms` (más de un intervalo), `throttling_analysis` (cinco intervalos o más).

### Claves de un resumen de macOS: presentes solo bajo una condición

| Clave | Condición (leída del `if` que rodea la asignación) | Escrita en |
|---|---|---|
| `tier` | `recording.finish` recibió un nivel: `perf_record` pasa uno, `perf_attach` no | `recording.py:344-345` |
| `retention` | `METAL_TRACE_MAX_DISK_MB` está fijado, no corre otra grabación y se borró al menos un archivo: `{freed_mb, removed, trace_dropped}` | `recording.py:346-349` |
| `gpu.unpresented` | El programa dejó de presentar; el trabajo posterior queda fuera de los fotogramas | `perf_report.py:721` |
| `metal_memory_mib` | Se leyó la tabla de memoria de Metal (`memory` verdadero: no el nivel `light`, no `PERF_MEMORY=0`); `{"samples": 0}` si no tenía muestras | `perf_report.py:740` |
| `process_rss_mib` | Existe `<run>.rss.csv` junto al trazo | `perf_report.py:753` |
| `gpu_activity` | `<run>.agx.csv` dio filas | `perf_report.py:756` |
| `noisy_environment` | `noisy_environment()` devolvió algo; `true` o `false` | `perf_report.py:759` |
| `noisy_basis` | `noisy_environment` es `true`; lleva `other_processes` | `perf_report.py:761-762` |
| `graphics_compiler` | Existe la tabla `graphics-compiler-activity-intervals` | `perf_report.py:780` |
| `thermal_state_share` | Existe la tabla `device-thermal-state-intervals` | `perf_report.py:790` |
| `cpu` | `ProcessCPUUsage` tuvo filas del programa | `perf_report.py:798` |
| `resource_allocations` | Existe la tabla de asignaciones y tiene eventos | `perf_report.py:802` |
| `shader_spills` | Existe la tabla `graphics-compiler-spill-events` | `perf_report.py:804` |
| `command_buffer_errors` | Existe la tabla `metal-command-buffer-error` (un conteo) | `perf_report.py:806` |
| `validation` | Existe `<run>.validation.log` (la validación de Metal estaba activada) | `perf_report.py:811` |
| `gpu_counters` | Existen las dos tablas de contadores y dieron muestras (`counters=true`, el nivel `deep`) | `perf_report.py:817` |

### Un resumen de Windows

`perf_record_windows.py:887-917` escribe un objeto más pequeño: `schema_version`, `label`, `trace` (el nombre
`<run>.trace`, un archivo que nunca existe en Windows), `process`, `device`, `template` (`Windows Native Trace`),
`duration_s`, `missing_tables` (tres nombres fijos), `gpu` (con `source`, uno de `drawstress-log`, `presentmon` o
`dwm-composition`, más las claves de ritmo y `throttling_analysis`), `encoders`, `gpu_idle`, `metal_memory_mib`
(`{"samples": 0}`), `process_rss_mib`, `layer`, `common`; `finish` añade entonces `context`, y `tier` y `retention` bajo
las mismas condiciones. `finish` también sustituye `layer` por la que calculó `record_run` (`recording.py:341`, `:370`,
`:385`), que para una corrida nativa en Windows dice `native Metal, no translation layer` (`recording.py:134-135`)
donde el motor había escrito `native Windows` (`perf_record_windows.py`, mismo diccionario); `layer_label` llama
`native` a las dos, así que ningún lector lo nota (confirmado por el código, no reproducido).
No hay `machine`, `hitches`, `gpu_performance_state_share` ni ninguna de las claves condicionales de Metal, así que una
herramienta debe tratar cada una como opcional (confirmado: no están en el diccionario de esas líneas).

## Las tablas y los muestreadores

**`frames.csv(.gz)`** tiene la cabecera `frame,start_ms,gpu_ms_<channel>...,gpu_ms_total`: una columna
`gpu_ms_<channel>` por cada canal que tenía el trazo, en minúsculas (`perf_report.py:831-834`). El ejemplo real (E4) tiene
`compute`, `fragment` y `vertex`. En Windows el único canal es `draw` (`perf_record_windows.py:847`). Los fotogramas que
el programa nunca presentó no están en ella; están en `gpu.unpresented` (`perf_report.py:695-721`).

**`metal_memory.csv(.gz)`** es `time_ms,metal_allocated_bytes`, una fila por muestra de las asignaciones de Metal del
programa (`perf_report.py:745-746`).

**`rss.csv`** es `time_s,rss_kib`, **`agx.csv`** es `time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib`
(`perf_record.sh:105-106`): las dos las escriben bucles de shell que corren en segundo plano durante la grabación
(`perf_record.sh:104-118`), durante `seconds + 5` pasos de un segundo, y son texto simple, nunca comprimido.

**Cómo se escribe y se lee una tabla** (`tables.py`):

- Se escribe como `<stem>.csv.gz` con un nombre temporal `<target>.<8 hex>.tmp` en la misma carpeta y luego se renombra
  sobre el destino con `os.replace` (`tables.py:43-52`): un lector nunca ve media tabla, y una excepción durante la
  escritura borra el temporal (`tables.py:53-58`).
- Las mismas filas dan los mismos bytes: la cabecera gzip no lleva nombre y `mtime=0` (`tables.py:48`).
- La lee `tables.find` (`tables.py:13`): primero `.csv.gz`, luego `.csv`, así que una corrida grabada antes de la 0.27.0
  sigue funcionando sin tocarla. Un enlace nunca es una tabla (`tables.py:18`, `:26`) y un `.gz` de cero bytes es un
  error, no una tabla vacía (`tables.py:29-30`).

Las carpetas reales de esta máquina no tienen ningún archivo `.csv.gz`: todas sus tablas son `.csv` sin comprimir (E1).
Por eso la ruta comprimida, y el tamaño que ahorra, **no se reprodujo** en una grabación real. La proporción de
compresión del [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md) y [la prueba de la 0.27.0](../../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit)
son la fuente publicada.

## El archivo de proyecto, la marca y las líneas base

`metal-gpu-trace.json` (`project.py`, [ADR-0004](../../adr/0004-project-file.md)) vive en un repositorio y nombra el
proyecto y adónde van sus grabaciones. Sus claves son `name` y `runs` (obligatorias), `baseline` y `format`
(`project.py:15`); cualquier otra clave se rechaza con su nombre (`project.py:43-46`, confirmado; es también lo que
pasa con una clave `profile` que haya quedado, quitada en la 0.26.0 según `CHANGELOG.md`). `runs` se comprueba con
dureza porque `KEEP_RUNS` borra archivos ahí (`project.py:3-5`): la carpeta debe ser nueva, estar vacía (la basura de
escritorio como `.DS_Store` no cuenta, `project.py:17`) o llevar la marca `.metal-gpu-trace-runs`, y una marca con el
nombre de otro proyecto la rechaza (`project.py:94-105`). `project.apply` (`project.py:162-189`) apunta `config.OUT`,
`config.READ[0]` y `config.BASELINES` a esa carpeta y escribe la marca (`project.py:192-201`).

`baselines.json` es un objeto JSON cuyas claves son los nombres de las líneas base; cada valor tiene `runs` (los
nombres de las corridas), `set` (una fecha), `summaries` (copias de los resúmenes de esas corridas) y, si se pidió,
`skip_s` (`analysis.py:279-280`). En el archivo real (E7) la única línea base contiene tres resúmenes. Las copias son el
punto: `KEEP_RUNS` puede borrar las corridas con que se hizo la línea base y `perf_check` sigue juzgando contra los
números guardados (`config.py:18`).

## `config.py` y `paths.py`

`config.py` guarda los ajustes, y cada otro módulo los lee como `config.NAME` en el momento de usarlos, nunca copiados
(`config.py:1-2`; la regla se explica en [How it works](../../guides/how-it-works.md#two-rules-that-keep-it-testable)).

| Nombre | Significado | Línea |
|---|---|---|
| `OUT` | La carpeta de corridas, resuelta | `config.py:16` |
| `READ` | `OUT` más las carpetas de `METAL_TRACE_READ`: lo que las herramientas pueden leer | `config.py:17` |
| `BASELINES` | `OUT/baselines.json` | `config.py:19` |
| `MAX_DISK_MB` | El límite de bytes en MiB: un entero de 1 o más en `METAL_TRACE_MAX_DISK_MB`, si no `None` (sin límite; un valor malo no da error) | `config.py:22-23` |
| `PROJECT`, `PROJECT_ERROR` | El archivo de proyecto en uso, o lo que tiene mal | `config.py:33-34` |
| `FAMILIES`, `WORKLOADS` | Los dos archivos de `data/`, cargados una vez al importar | `config.py:35-36` |
| `CACHE` | La carpeta de caché | `config.py:37-40` |
| `LOCK` | El candado de grabación, compartido por todas las carpetas de corridas | `config.py:42` |
| `MAX_LIMIT`, `MAX_TEXT` | Filas por página (500) y caracteres por resultado (40 000) | `config.py:43-45` |

`config.reload` (`config.py:11`) vuelve a leer `METAL_TRACE_OUT`, `METAL_TRACE_READ` y `METAL_TRACE_MAX_DISK_MB`; corre al
importar y otra vez desde `project.apply`. Todo lo demás de este archivo se lee una sola vez al importar.

`paths.py` es lo que impide que quien llama nombre un archivo que no debe tocar:

| Función | Qué garantiza | Línea |
|---|---|---|
| `name_ok` | Un nombre solo de letras, dígitos, `.`, `_`, `-` y de 120 bytes como máximo (una etiqueta se limita a 100 en `recording.record`, `recording.py:312`) | `paths.py:25` |
| `run_path` | El `.json` de una corrida con nombre; rechaza un nombre fuera de ese alfabeto, `baselines.json`, `panel.json`, un enlace y una corrida inexistente | `paths.py:33` |
| `allowed` | Una ruta dentro de `config.READ`, si no un `ToolError` que dice que añadas el directorio | `paths.py:17` |
| `read_text`, `read_object` | Leen un archivo de la carpeta de corridas nunca a través de un enlace (`O_NOFOLLOW`), sin quedarse esperando en una tubería; `read_object` devuelve un objeto JSON o un `ToolError` que nombra lo que falló, nunca la ruta | `paths.py:43`, `:54` |
| `write_file` | Reemplaza un archivo, rechazando un enlace | `paths.py:69` |
| `trace_path` | El `.trace` del nombre de una corrida, o una ruta dentro de las carpetas legibles | `paths.py:83` |
| `page` | Una página de una lista con `total`, `offset` y `next_offset` | `paths.py:94` |
| `check_cooldown`, `check_skip` | Segundos de 0 a 600, si no un `ToolError` | `paths.py:102`, `:118` |

La razón de las comprobaciones de enlaces está escrita en el código: una carpeta de corridas puede venir de un clon o de
una descarga, y un enlace dentro de ella podría apuntar a cualquier archivo (`paths.py:55-57`).

## Retención: dos mecanismos que no se mezclan

Dos ajustes impiden que la carpeta de corridas crezca. Se parecen y no son lo mismo: los escribe código distinto, se
leen en sitios distintos, cuentan cosas distintas y borran archivos distintos.

| | `KEEP_RUNS=N` | `METAL_TRACE_MAX_DISK_MB=M` |
|---|---|---|
| Cuenta | Corridas (por la fecha de modificación de su `.json`) | Bytes (MiB) de todo el primer nivel de la carpeta |
| Corre en | `perf_record.sh:164` llama a `prune_runs.sh`; el borrado es `prune_runs.sh:9` | `recording.finish` (`recording.py:346`) llama a `retention.prune_to_quota` (`retention.py:46`) |
| Se lee de | El entorno del proceso, por el script y por el motor de Windows (`perf_record_windows.py:922`); el servidor pasa su propio entorno (`recording.py:360`) | `config.py:22`, al arrancar el servidor y en cada `config.reload` |
| Borra | Todos los archivos de cada corrida más vieja que las N más nuevas: `${old:r}.*` (`prune_runs.sh:9`): su `.json`, tablas, muestreadores, `.chrome-trace` y `.trace` | Solo archivos pesados: `.trace`, luego `.chrome-trace`, luego tablas (`retention.py:8-10`, `:37-42`) |
| Nunca borra | `baselines.json`, `panel.json` (`prune_runs.sh:9`) y la marca (no es el stem de un `.json`) | Un `.json`, muestreadores, `baselines.json`, la marca, `.presentmon.csv` (`retention.py:43`) |
| Orden | Sobreviven las N más nuevas | Las más viejas primero dentro de cada tipo; los tipos en el orden de arriba; el `.trace` de la corrida actual el último |
| No actúa cuando | `KEEP_RUNS` no es un entero de 1 o más (`perf_record.sh:164`); `prune_runs.sh` mismo sale con 2 ante un valor malo (`prune_runs.sh:8`) | El límite no está fijado o es inválido; corre otra grabación (`recording.py:346`) |
| Avisa | Nada | `retention` en el resumen de la grabación que lo disparó, si se fue al menos un archivo |

### Cómo decide `KEEP_RUNS`

`prune_runs.sh:9` lista los `.json` de la carpeta salvo `baselines.json` y `panel.json`, los ordena por fecha de
modificación con el más nuevo primero (el calificador de zsh `om`), toma desde la posición `keep + 1` hasta el final y
borra todos los archivos que tienen el mismo stem. Una corrida es, por tanto, un `.json`: un `.trace` sin `.json` al
lado nunca lo mira `KEEP_RUNS` (ver [Cuando falla](#cuando-falla)). La prueba `test_keep_runs_still_removes_old_tables`
(`tests/test_recording.py:1101`) fija el borrado de las tablas comprimidas. En Windows `clean_runs`
(`perf_record_windows.py:503-518`) hace lo mismo en Python con `unlink`, una segunda implementación (confirmado: no
comparten código).

### Cómo decide la cuota

`prune_to_quota` (`retention.py:46-82`):

1. Lista el primer nivel de la carpeta con la fecha de modificación y el tamaño de cada entrada (una carpeta se cuenta
   de forma recursiva, un enlace como un archivo de su propio tamaño, `retention.py:13-27`).
2. Si el total es como mucho `M` MiB, termina sin tocar nada (`retention.py:60-61`).
3. Si no, ordena las entradas borrables por tipo y luego por edad, y las borra una a una hasta que el total cabe
   (`retention.py:62-81`). `kind_of` (`retention.py:30-43`) dice qué es cada entrada: el `.trace` de la corrida actual
   es `CURRENT_TRACE` y va el último; el `.chrome-trace` y las tablas de la corrida actual son `None`, así que se quedan
   siempre; cualquier otro `.trace`, `.chrome-trace` o tabla es candidato; todo lo demás es `None`.
4. Devuelve `{freed_mb, removed, trace_dropped}`; `trace_dropped` es verdadero solo si se fue el `.trace` de la corrida
   actual.

### Predecir qué sobrevive (un ejemplo trabajado, no una corrida medida)

Tres corridas `deep` A (la más vieja), B y C (la recién grabada), cada una con un `.trace` de 259 MiB, 0,5 MiB de tablas
y un resumen de 5 KiB, unos 778 MiB en total:

| `METAL_TRACE_MAX_DISK_MB` | Qué se va, en orden | Qué queda |
|---|---|---|
| 1000 | Nada: ya cabe | A, B, C completas |
| 600 | El `.trace` de A (total 519 MiB, cabe) | A sin trazo; B, C completas |
| 300 | El `.trace` de A y luego el de B (total 260 MiB) | Solo C tiene `.trace` |
| 200 | Los `.trace` de A y B, luego las tablas de A y B, luego el `.trace` de C (`trace_dropped: true`) | Los tres resúmenes, las tablas de C y los muestreadores, unos 1 MiB |

Las mismas tres corridas con `KEEP_RUNS=2` pierden **todos** los archivos de A (el resumen incluido) y conservan B y C
completas; con ambos ajustes, el script poda primero (`KEEP_RUNS`, al final de `perf_record.sh`) y la cuota corre
después, sobre lo que queda. Esta tabla está leída del código y de las reglas de `kind_of`; **no se reprodujo**:
ninguna carpeta real de aquí estuvo nunca por encima de un límite, y borrar archivos no es algo que haga una comprobación
de solo lectura. Para eso existe `tests/test_retention.py` (no ejecutado para esta página).

### Donde el límite no se puede cumplir

El total cuenta todo el primer nivel, incluidos los archivos que nunca son candidatos. Una carpeta cuyos resúmenes,
muestreadores y tablas de la corrida actual ya superan `M` se queda por encima de `M`: el bucle termina cuando se le
acaban los candidatos (`retention.py:65-80`), sin error, y `retention` aparece en el resumen solo si se borró algo
(`recording.py:348`). Nada avisa de que no se alcanzó el límite (confirmado por el código, no reproducido).

## La caché y el candado

### La caché no son las grabaciones

`~/Library/Caches/metal-gpu-trace` guarda **los programas de prueba que descarga `workload_fetch`**, no grabaciones.
Cada carpeta se llama `<workload>-<primeros 12 caracteres del SHA-256 fijado>` (`workloads.py:22`), se descarga una vez
en una carpeta temporal dentro de la caché, se verifica y se renombra a su sitio (`workloads.py:156-175`). Las llamadas
posteriores la reutilizan (`workloads.py:154-155`).

La caché de aquí pesa 942 MiB en 8 carpetas (E8). `data/workloads.json` fija solo 3 versiones (E9), así que 5 de esas 8
carpetas son versiones fijadas antiguas que nadie usa: 63 + 65 + 79 + 78 + 23 = 308 MiB. Nada en `workloads.py` borra una
carpeta de la caché (el `rg` de `rmtree` y `unlink` solo encuentra el `part.unlink()` del zip desempaquetado en
`workloads.py:173`, E10), así que la caché solo crece cuando una versión nueva cambia un valor fijado (confirmado, con el
límite de que la búsqueda cubre `workloads.py` y no se sabe de otros módulos que borren ahí). Nada la limpia: borra una
carpeta a mano y se vuelve a descargar cuando haga falta.

### El candado

Una grabación a la vez, vaya a la carpeta que vaya: dos programas que comparten la GPU estropean las dos mediciones
(`perf_record.sh:40`). El candado es una **carpeta** (`mkdir` es atómico: o la crea o falla) llamada `recording.lock`
en la caché, con un archivo `pid` dentro que guarda el id de proceso de su dueño.

- **Tomarlo.** `perf_record.sh:52-62`: `mkdir $lock`; si falla y el dueño está muerto (`ps -p`), lo toma por encima
  con un segundo candado (`$lock.takeover`) para que dos grabaciones que encuentren el mismo candado muerto no puedan
  tomarlo las dos (`perf_record.sh:44-61`); si el dueño está vivo sale con el código 3 y el mensaje
  `another recording is running` (`perf_record.sh:47-50`). Después `echo $$ > $lock/pid` (`perf_record.sh:62`).
- **Comprobarlo sin tomarlo.** `preflight.check` rechaza antes de empezar nada cuando el candado nombra un proceso vivo
  (`preflight.py:135-137`); `lock_owner_alive` (`preflight.py:74-94`) lee como mucho 32 bytes del archivo `pid`, nunca a
  través de un enlace, y trata un dueño ausente, raro o muerto como que no hay grabación. `recording.finish` usa la
  misma comprobación para no podar mientras otra grabación escribe en la carpeta (`recording.py:346`).
- **Soltarlo.** La trampa `EXIT` del script lo borra (`perf_record.sh:65-73`); el servidor lo borra si mató el script al
  cancelar o por tiempo agotado (`recording.free_lock`, `recording.py:326-335`, llamada en `:404`), y solo si el archivo
  `pid` aún guarda el pid del propio script, así que nunca borra el candado de otra grabación.
- **Windows.** `perf_record_windows.py` tiene su propia versión de la misma idea: crea el candado con `mkdir`, escribe el
  `pid`, toma por encima uno caducado una vez y lo suelta en `finally` (`perf_record_windows.py:574-597`, `:942-946`).

Ahora mismo la caché no tiene ningún candado (E8: nada llamado `recording.lock`), que es el estado esperado entre
grabaciones. Un candado tomado **no se reprodujo**: tenerlo tomado significa estar grabando.

## De una grabación a disco

![Secuencia de cinco actores, el servidor, el candado, el script, el informe y la carpeta de corridas, en ocho pasos numerados. El candado se mantiene del paso 2 al paso 7. El resumen se escribe dos veces, en los pasos 5 y 8.](/diagrams/data-recording-to-disk.png)
*Figura 2. Una grabación en macOS desde la primera comprobación hasta los archivos en disco. Fuente HTML: `docs/diagrams/data-recording-to-disk.html`. Las etiquetas del diagrama están en inglés.*

Los números son los de la figura; la prueba de cada uno está en [E11](#e11-los-ocho-pasos-de-la-figura-2).

1. **El servidor comprueba el candado.** `recording.record` llama a `preflight.check` (`recording.py:315`), que lee el
   candado y rechaza si un proceso vivo lo tiene. Nunca lo toma.
2. **El script toma el candado** y escribe su pid. Desde aquí la carpeta es de esta grabación.
3. **Escriben los muestreadores e Instruments.** Dos bucles en segundo plano escriben `.rss.csv` y `.agx.csv` una vez por
   segundo mientras `xctrace` escribe el `.trace`.
4. **El script lanza el informe**: `python3 -I perf_report.py <trace> --label <stem> --out <folder>`.
5. **El informe escribe las tablas y un primer resumen**, en ese orden: la tabla de memoria (`perf_report.py:745`), la
   tabla de fotogramas (`:831`), y luego el `.json` (`:836`).
6. **El script borra el `.trace`** salvo con `KEEP_TRACE=1`, y luego aplica `KEEP_RUNS` si está fijado.
7. **El script suelta el candado** al salir.
8. **El servidor termina.** `recording.finish` añade `layer`, `context`, `tier`, aplica el límite de disco si no corre
   otra grabación y **reescribe** el `.json`.

Consecuencias que conviene saber:

- **El resumen se escribe dos veces** (pasos 5 y 8), así que durante un rato la primera versión no tiene `layer` ni
  `context`. Las dos escrituras son un `write_text` simple (`perf_report.py:836`, `recording.py:350`), no el nombre
  temporal con renombrado que usan las tablas, así que en principio un lector puede encontrar un archivo a medias.
  `perf_runs` se salta un resumen que no se puede leer (`analysis.py:80-81`; su comentario dice «a summary still being
  written»). Confirmado por el código; una lectura a medias **no se reprodujo**.
- **El límite de disco solo existe en el camino del servidor.** Una grabación lanzada a mano con `perf_record.sh` termina
  en el paso 7: tiene `KEEP_RUNS` y `KEEP_TRACE`, pero no `METAL_TRACE_MAX_DISK_MB`, porque eso se aplica en Python
  (`recording.py:346`) (confirmado).
- **`KEEP_RUNS` corre con el candado todavía tomado** (el paso 6 va antes del 7), así que ninguna otra grabación puede
  empezar entre el borrado y el final de esta.

## Cuando falla

| Qué sale mal | Qué queda en disco | Quién lo limpia | Línea |
|---|---|---|---|
| El cliente cancela o la grabación pasa su plazo | Nada: el servidor mata el grupo de procesos, el programa, suelta el candado y borra los archivos nuevos de la corrida y los `.ktrace` temporales nuevos | el servidor | `recording.py:396-413` |
| El script sale con error | Nada de esa corrida: la trampa `EXIT` borra `$out/$name.*` si el código no es 0 | el script | `perf_record.sh:71` |
| El script recibe `TERM` | Lo mismo | el script | `perf_record.sh:74` |
| El servidor muere a mitad de grabación | La grabación y su programa los detiene un bucle vigilante dentro del script | el script | `perf_record.sh:82-92` |
| Se mata el script con `SIGKILL` (no corre ninguna trampa) | Un `recording.lock` caducado, archivos parciales de la corrida | El siguiente script toma por encima un candado cuyo dueño está muerto; `preflight` no rechaza por un dueño muerto. Los archivos parciales se quedan hasta que `KEEP_RUNS` o la cuota los alcancen | `perf_record.sh:47-61`, `preflight.py:74-98` (probable: no reproducido) |
| El programa no hizo trabajo de GPU | Se borran el resumen y todos los archivos de la corrida; el `.trace` se queda si se pidió conservarlo, y el error lo dice | el servidor | `recording.py:427-436` |
| Se interrumpe la escritura de una tabla | `<table>.csv.gz.<hex>.tmp`. Su nombre empieza con el stem de la corrida, así que `KEEP_RUNS` lo borra con la corrida; la cuota no (su sufijo no es de tabla) | `KEEP_RUNS` | `tables.py:40-43`, `retention.py:10` |
| Un `.csv.gz` está cortado o vacío | Un error que dice que grabes de nuevo, no una tabla corta | nadie: el archivo se queda | `tables.py:29-30`, [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md) |
| Hace falta una tabla podada (`perf_compare` con `skip_s`) | Un mensaje «has no per-frame file; record it again» | nadie | `analysis.py:510` |
| El disco está casi lleno | Se rechaza la grabación antes de empezar: hacen falta `2 + (seconds × 8 + 9) / 10` GB libres (división entera) en la carpeta temporal y en la de corridas; `PERF_MIN_FREE_GB` lo cambia | nadie | `perf_record.sh:34-38`, `preflight.py:128-131` |

El comentario de `perf_record.sh:33` explica la cifra de disco: los temporales de Instruments llegan a unos 0,8 GB por
segundo grabado, y se midieron 48 GB para 60 s de Wine D3D12. Es un comentario del código, no una medida hecha para
esta página (**probable**).

## Límites conocidos

Cada punto es un límite del comportamiento de hoy, anotado, no arreglado aquí.

| # | Límite | Dónde | Estado |
|---|---|---|---|
| 1 | Se rechaza una clave `profile` en un archivo de proyecto. Es el contrato desde la 0.26.0 (la clave figura como eliminada en `CHANGELOG.md`), así que un archivo que aún la tenga debe quitarla | `project.py:43-46` | Confirmado; si se vuelve a admitir está abierto |
| 2 | Los `.presentmon.csv` no cuentan para la cuota y la cuota nunca los borra | `retention.py:43` | Confirmado |
| 3 | La caché no tiene limpieza; 5 de sus 8 carpetas son versiones fijadas antiguas (308 MiB) | `workloads.py:22`, E8-E10 | Confirmado |
| 4 | Un resumen cuyo `.trace` ya no existe es lo normal: `trace` es solo el nombre, el archivo se borra por defecto; `perf_runs` informa `trace_kept` | `perf_report.py:650`, `perf_record.sh:163`, `analysis.py:79`, E5 | Confirmado |
| 5 | `panel.json` se sigue omitiendo en todas partes aunque el panel ya no exista | `paths.py:10`, `retention.py:7`, `prune_runs.sh:3` y `:9`, `perf_record_windows.py:508`, `analysis.py:52` | Confirmado; el comentario dice «drop this in a later version» |
| 6 | `KEEP_RUNS` borra el `.trace` de una corrida más vieja, porque `${old:r}.*` coincide con `<run>.trace`. El [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md) dice que `KEEP_RUNS` «never prunes a kept `.trace`», lo cual solo es cierto de un `.trace` sin `.json` | `prune_runs.sh:9`, E6 | El patrón está confirmado (E6); el borrado en sí no se reprodujo |
| 7 | Un `.trace` sin `.json` (una corrida que no hizo trabajo de GPU, `deep` o `KEEP_TRACE=1`) nunca lo ve `KEEP_RUNS`; solo lo borra la cuota | `recording.py:427-433`, `prune_runs.sh:9` | Confirmado por el código |
| 8 | El límite de disco puede ser inalcanzable y no dice nada | `retention.py:65-80`, `recording.py:348` | Confirmado por el código |
| 9 | El resumen se reescribe con una escritura no atómica | `perf_report.py:836`, `recording.py:350` | Confirmado por el código |
| 10 | Una grabación a mano y una del servidor van por defecto a carpetas distintas | `config.py:16`, `perf_record.sh:28-29` | Confirmado |
| 11 | No hay en esta máquina un resumen real de generación 2 o 3 con el que comparar las listas de claves | E3 | No reproducido |

## Tocarlo sin romperlo

- Una clave nueva del resumen: escríbela donde se escriben las otras de su grupo, di en las tablas de claves de arriba si
  está siempre presente o es condicional y, si pertenece a las dos plataformas, ponla en `common` por medio de
  `metrics.common_block`, con la prueba de la lista de claves actualizada (`test_common_block_has_the_same_keys_on_both_platforms`,
  `tests/test_analysis.py:878`). Un lector nunca debe suponer una clave condicional.
- Un tipo de archivo nuevo en la carpeta de corridas: dale el stem de la corrida para que `KEEP_RUNS` lo borre con ella, y
  decide si `retention.kind_of` debe listarlo. Si no está listado nunca cuenta como borrable y la cuota no puede liberar
  su espacio (el límite 2 es justo eso).
- Una regla de retención nueva: mantén los dos mecanismos separados. Si un cambio necesita conocer los dos, actualiza las
  dos columnas de la tabla de [Retención](#retencion-dos-mecanismos-que-no-se-mezclan).
- Una tabla: escríbela con `tables.write` y léela con `tables.find` y `tables.open_text`; no abras un `.csv` directamente,
  o las corridas grabadas antes de la 0.27.0, o después, se romperán de un modo u otro.
- Todo lo que lea un archivo de la carpeta de corridas pasa por `paths.read_object` o `paths.read_text`, para que nunca
  se siga un enlace.
- Un resumen compartido no debe llevar nombre de máquina, UUID ni ruta absoluta.

## Evidencia: los comandos y su salida real

Recogida el 2026-11-16 en un Mac con Apple silicon. Todos los comandos solo leen. Las rutas están acortadas: la carpeta
personal es `~`, la carpeta de grabaciones es `~/perf-runs/<project>`, el dueño de los archivos se omite. La carpeta de
corridas comprobada es una carpeta de grabaciones hechas en octubre de 2026 con una versión anterior; el `perf-runs/`
del propio repositorio tiene dos grabaciones más del 15 de noviembre.

### E1 Los archivos que deja una corrida

```text
$ ls -a -1 ~/perf-runs/<project> | head -4
.
..
.metal-gpu-trace-runs
baselines.json

$ cd ~/perf-runs/<project> && ls -l -g -o -h . | sed 's/ [0-9]* *$//'
total
-rw-r--r--@  1     10K Oct 18 02:02 baselines.json
-rw-r--r--@  1    4.9K Oct 18 02:02 probe-d3d12_20261018-003026.json
-rw-r--r--@  1    2.7K Oct 18 02:02 probe-mtl_20261018-003242.json
-rw-r--r--@  1    4.2K Oct 18 02:02 ref-d3d12-1_20261018-002332.json
-rw-r--r--@  1    4.7K Oct 18 02:02 ref-d3d12-2_20261018-002603.json
-rw-r--r--@  1    4.9K Oct 18 02:02 ref-d3d12-3_20261018-002816.json
-rw-r--r--@  1    2.9K Oct 18 02:02 tp-d3d12_20261018-011509.json
-rw-r--r--@  1     56K Oct 18 02:13 v070-d3d12_20261018-021158.frames.csv
-rw-r--r--@  1    4.9K Oct 18 02:13 v070-d3d12_20261018-021158.json
-rw-r--r--@  1    418K Oct 18 02:13 v070-d3d12_20261018-021158.metal_memory.csv
-rw-r--r--@  1    367B Oct 18 02:12 v070-d3d12_20261018-021158.rss.csv
drwxr-xr-x@ 10    320B Oct 18 02:13 v070-d3d12_20261018-021158.trace
```

Siete resúmenes, una corrida con sus tres tablas y su muestreador, y un `.trace`. Todas las tablas son `.csv` sin
comprimir: ninguna es `.csv.gz`, así que el formato comprimido **no se reprodujo** en una corrida real.

### E2 Tamaño

```text
$ du -sh ~/perf-runs/<project> ~/perf-runs/<project>/v070-d3d12_20261018-021158.trace
259M	~/perf-runs/<project>
259M	~/perf-runs/<project>/v070-d3d12_20261018-021158.trace
```

`du -sh` imprime unidades binarias, así que 259M son 259 MiB. El `.trace` es toda la carpeta, con la precisión que da `du`.

### E3 Claves de resúmenes reales

```text
$ jq -r 'keys_unsorted|join(" ")' perf-runs/a2-proof-first_20261115-085621.json
label trace process device template duration_s machine missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_activity gpu_performance_state_share graphics_compiler thermal_state_share cpu resource_allocations command_buffer_errors hitches layer context

$ jq -c '{trace,schema:(.schema_version),tier,retention}' ~/perf-runs/<project>/v070-d3d12_20261018-021158.json perf-runs/a2-proof-first_20261115-085621.json
{"trace":"v070-d3d12_20261018-021158.trace","schema":null,"tier":null,"retention":null}
{"trace":"a2-proof-first_20261115-085621.trace","schema":null,"tier":null,"retention":null}

$ jq -r '"\(input_filename|split("/")|last|.[0:26]): \(keys_unsorted|join(" "))"' <the October summaries, 3 of the 5 shown here>
probe-d3d12_20261018-00302: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_performance_state_share layer
tp-d3d12_20261018-011509.j: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib gpu_performance_state_share
v070-d3d12_20261018-021158: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_performance_state_share layer
```

Cada clave de estos archivos reales está en las tablas de siempre presentes o condicionales de arriba, una por una
(`label`, `trace`, `process`, `device`, `template`, `duration_s`, `machine`, `missing_tables`, `gpu`, `encoders`,
`gpu_idle`, `metal_memory_mib`, `process_rss_mib`, `gpu_activity`, `gpu_performance_state_share`, `graphics_compiler`,
`thermal_state_share`, `cpu`, `resource_allocations`, `command_buffer_errors`, `hitches`, `layer`, `context`). La
comprobación inversa (un resumen real con todas las claves que el código puede escribir) **no se reprodujo**: no existe.
Los archivos muestran además por qué un lector debe tratar las claves como opcionales: los más antiguos no tienen
`machine`, `hitches` ni `context`, y `tp-d3d12` no tiene `layer`. El listado con `python3 -I -c` que pedía el plan **no se
reprodujo**: la evidencia se recogió solo con herramientas de lectura sin Python, así que se usó `jq`.

### E4 Las columnas de las tablas

```text
$ head -3 ~/perf-runs/<project>/v070-d3d12_20261018-021158.frames.csv
frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total
1,8920.469,0.1068,0.0,0.0,0.1068
2,8939.648,0.1057,0.0,0.0,0.1057

$ head -3 ~/perf-runs/<project>/v070-d3d12_20261018-021158.metal_memory.csv
time_ms,metal_allocated_bytes
2267.019,131072
8887.183,147456

$ head -3 ~/perf-runs/<project>/v070-d3d12_20261018-021158.rss.csv
time_s,rss_kib
0,0
1,0

$ head -3 perf-runs/a2-proof-first_20261115-085621.agx.csv
time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib
0,0,0,0,0,0,361
1,3,3,3,0,0,362
```

### E5 Un resumen cuyo `.trace` ya no existe

```text
$ cd ~/perf-runs/<project>
$ ls -d probe-mtl_20261018-003242.*
probe-mtl_20261018-003242.json

$ jq -r '.trace' v070-d3d12_20261018-021158.json probe-mtl_20261018-003242.json
v070-d3d12_20261018-021158.trace
probe-mtl_20261018-003242.trace
```

El segundo resumen nombra un `.trace`, y el `ls` muestra que no hay ninguno (el primero sí tiene su carpeta, E1).

La clave nombra un archivo que no está: es el caso normal, porque el `.trace` se borra salvo que se pida conservarlo.

### E6 Qué abarca `${old:r}.*`

```text
$ cd ~/perf-runs/<project>
$ ls -d v070-d3d12_20261018-021158.*
v070-d3d12_20261018-021158.frames.csv
v070-d3d12_20261018-021158.json
v070-d3d12_20261018-021158.metal_memory.csv
v070-d3d12_20261018-021158.rss.csv
v070-d3d12_20261018-021158.trace
```

Es el patrón que `prune_runs.sh:9` expande para el stem de una corrida vieja (`${old:r}` es el nombre del `.json` sin
`.json`). Incluye el `.trace`. El límite 6 se apoya en esta salida; el `rm -rf` en sí **no se reprodujo** (es un borrado).

### E7 El archivo de líneas base

```text
$ jq -r 'to_entries[]|"\(.key): \(.value|keys|join(","))"' ~/perf-runs/<project>/baselines.json
<baseline>: runs,set,summaries

$ jq -r '.[].summaries|length' ~/perf-runs/<project>/baselines.json
3
```

(El nombre propio de la línea base se sustituyó por `<baseline>`.) Una línea base, con `runs`, `set` y `summaries` (tres
copias de resúmenes), como la escribe `analysis.py:279-280`.

### E8 La caché y el candado

```text
$ ls -a ~/Library/Caches/metal-gpu-trace
.
..
bgfx-examples-1d120363981c
bgfx-examples-320a6b3bbc11
bgfx-examples-9c1bd6164b4a
bgfx-examples-bd41458ee01e
bgfx-examples-c5b25350c15e
drawstress-2b3b01fa2dd0
drawstress-f7e25cbb8c4a
godot-a85320f08e1a

$ du -sh ~/Library/Caches/metal-gpu-trace
942M	~/Library/Caches/metal-gpu-trace

$ du -sh ~/Library/Caches/metal-gpu-trace/*
 97M	~/Library/Caches/metal-gpu-trace/bgfx-examples-1d120363981c
 63M	~/Library/Caches/metal-gpu-trace/bgfx-examples-320a6b3bbc11
 65M	~/Library/Caches/metal-gpu-trace/bgfx-examples-9c1bd6164b4a
 79M	~/Library/Caches/metal-gpu-trace/bgfx-examples-bd41458ee01e
 78M	~/Library/Caches/metal-gpu-trace/bgfx-examples-c5b25350c15e
 27M	~/Library/Caches/metal-gpu-trace/drawstress-2b3b01fa2dd0
 23M	~/Library/Caches/metal-gpu-trace/drawstress-f7e25cbb8c4a
510M	~/Library/Caches/metal-gpu-trace/godot-a85320f08e1a
```

No aparece ningún `recording.lock`: nada está grabando.

### E9 Las versiones que fija el paquete

```text
$ jq -r '.workloads|to_entries[]|"\(.key) \(.value.sha256[0:12])"' src/metal_gpu_trace/data/workloads.json
drawstress 2b3b01fa2dd0
bgfx-examples 1d120363981c
godot a85320f08e1a
```

Tres versiones fijadas frente a ocho carpetas: `bgfx-examples-320a`, `-9c1b`, `-bd41`, `-c5b2` y `drawstress-f7e2` no
coinciden con ninguna.

### E10 Nada borra una carpeta de la caché

```text
$ rg -n "rmtree|unlink" src/metal_gpu_trace/workloads.py
173:            part.unlink()
```

### E11 Los ocho pasos de la Figura 2

Cada paso se lee de la línea que lo hace (`rg -n` en `src/metal_gpu_trace`), no de una grabación. La disposición de abajo
es mía (paso, `archivo:línea`, la línea sin su sangría); el texto de cada línea es el que imprimió `rg`, recortado a 140
caracteres:

```text
1  preflight.py:135        if recording_running(alive):
2  perf_record.sh:52       if ! mkdir $lock 2>/dev/null; then
2  perf_record.sh:62       echo $$ > $lock/pid
3  perf_record.sh:105      echo "time_s,rss_kib" > $out/$name.rss.csv
3  perf_record.sh:140      xcrun xctrace record --template "Metal System Trace" --time-limit ${seconds}s --output $out/$name.trace \
4  perf_record.sh:160      python3 -I $here/perf_report.py $out/$name.trace $report
5  perf_report.py:745      table_files.write(out, f"{label}.metal_memory", ["time_ms", "metal_allocated_bytes"],
5  perf_report.py:831      table_files.write(
5  perf_report.py:836      (out / f"{label}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
6  perf_record.sh:163      [[ ${KEEP_TRACE:-0} == 1 ]] || rm -rf $out/$name.trace
6  perf_record.sh:164      if [[ ${KEEP_RUNS:-} == <1-> ]]; then zsh $here/prune_runs.sh $out $KEEP_RUNS; fi
7  perf_record.sh:68       rm -rf $lock
7  perf_record.sh:73       trap cleanup EXIT
8  recording.py:346        if config.MAX_DISK_MB and not preflight.recording_running():
8  recording.py:347        removed = retention.prune_to_quota(config.OUT, config.MAX_DISK_MB, json_path.stem)
8  recording.py:350        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

El orden en el tiempo (el 2 antes del 7, el 5 antes del 8) sale del orden de las líneas y de las llamadas. Una corrida en
vivo de la secuencia con marcas de tiempo **no se reprodujo**: graba.

### E12 Dónde aparecen las dos variables de retención

```text
$ rg -n "KEEP_RUNS|METAL_TRACE_MAX_DISK_MB" src
src/metal_gpu_trace/perf_record_windows.py:922:        keep_runs_env = os.environ.get("KEEP_RUNS")
src/metal_gpu_trace/project.py:3:The folder is checked before use, because KEEP_RUNS removes the older .json files in it
src/metal_gpu_trace/retention.py:1:"""Keeping the runs folder under a size limit (METAL_TRACE_MAX_DISK_MB): removes the heavy files of old recordings."""
src/metal_gpu_trace/config.py:22:    limit = environ.get("METAL_TRACE_MAX_DISK_MB", "").strip()
src/metal_gpu_trace/recording.py:338:    """Adds `layer`, the run's `context` and `tier` to the summary, applies METAL_TRACE_MAX_DISK_MB ...
src/metal_gpu_trace/perf_record.sh:164:if [[ ${KEEP_RUNS:-} == <1-> ]]; then zsh $here/prune_runs.sh $out $KEEP_RUNS; fi
```

Se muestran seis de las 21 líneas que imprimió `rg` (las que leen una variable o actúan según ella); cada una recortada a
120 caracteres. Las demás solo mencionan una variable en un comentario o en una docstring.

`KEEP_RUNS` se lee en `perf_record.sh:164` y en `perf_record_windows.py:922`, y actúa en `prune_runs.sh:9` (ese archivo
nunca nombra la variable: recibe el número como `keep`). `METAL_TRACE_MAX_DISK_MB` solo se lee en `config.py:22` y actúa
en `retention.py` por medio de `recording.py:346-347`.

### Lo que no se reprodujo

- Un resumen de generación 2 o 3 de una grabación real (hace falta Instruments).
- Un `.csv.gz` en una corrida real y su proporción de compresión.
- Una grabación que tiene el candado, y la limpieza tras un script matado.
- La cuota borrando archivos, `retention` apareciendo en un resumen, `trace_dropped`, y `KEEP_RUNS` borrando un `.trace`
  (borran archivos).
- El listado de claves con `python3 -I -c`.

## Véase también

- [How it works](../../guides/how-it-works.md): las capas y el recorrido de una petición.
- [ADR-0004](../../adr/0004-project-file.md): el archivo de proyecto y la marca de la carpeta de corridas.
- [ADR-0006](../../adr/0006-compressed-tables-and-disk-quota.md): tablas comprimidas y el límite de disco.
- [Prueba de la 0.27.0](../../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit): el límite de tamaño medido.
