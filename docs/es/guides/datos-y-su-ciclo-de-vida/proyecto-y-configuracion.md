# El archivo de proyecto, `config.py` y `paths.py`

**Lector:** personas que cambian ajustes, el archivo de proyecto o cualquier cosa que abra un archivo de la carpeta de corridas. Revisado el 2026-11-16.

English: [The project file, `config.py` and `paths.py`](../../../guides/data-and-lifecycle/project-and-config.md)

> **En corto:** un repositorio puede llevar un archivo pequeño que dice «guarda aquí las grabaciones de este proyecto».
> Como la limpieza borra archivos de esa carpeta, la carpeta se comprueba con dureza antes de usarla. Dos módulos
> guardan el resto: `config.py` tiene los ajustes y `paths.py` impide que quien llama nombre un archivo que no debe
> tocar, también a través de un enlace.

Volver al [índice](./index.md). Ejemplo: un archivo de proyecto `{"name": "mygame", "runs": "perf-runs"}` hace que las
herramientas usen `perf-runs/`, escriban ahí la marca `.metal-gpu-trace-runs` con `mygame` dentro, y rechacen la carpeta
si esa marca lleva el nombre de otro proyecto.

## El archivo de proyecto, la marca y las líneas base

`metal-gpu-trace.json` (`project.py`, [ADR-0004](../../../adr/0004-project-file.md)) vive en un repositorio y nombra el
proyecto y adónde van sus grabaciones.

| Pieza | Regla | Dónde |
|---|---|---|
| Claves | `name` y `runs` (obligatorias), `baseline` y `format`; cualquier otra clave se rechaza con su nombre (también una clave `profile` que haya quedado, quitada en la 0.26.0 según `CHANGELOG.md`: límite conocido 1) | `project.py:15`, `:43-46` |
| Carpeta `runs` | Debe ser nueva, estar vacía (la basura de escritorio como `.DS_Store` no cuenta) o llevar la marca; una marca con el nombre de otro proyecto la rechaza. Se comprueba con dureza porque `KEEP_RUNS` borra archivos ahí | `project.py:3-5`, `:17`, `:94-105` |
| `project.apply` | Apunta `config.OUT`, `config.READ[0]` y `config.BASELINES` a esa carpeta y escribe la marca | `project.py:162-189`, `:192-201` |

`baselines.json` es un objeto JSON cuyas claves son los nombres de las líneas base; cada valor tiene `runs` (los
nombres de las corridas), `set` (una fecha), `summaries` (copias de los resúmenes de esas corridas) y, si se pidió,
`skip_s` (`analysis.py:279-280`). En el archivo real ([E7](./evidencia-corridas.md#e7-el-archivo-de-lineas-base)) la
única línea base contiene tres resúmenes. Las copias son el punto: `KEEP_RUNS` puede borrar las corridas con que se hizo
la línea base y `perf_check` sigue juzgando contra los números guardados (`config.py:18`).

## `config.py`

Guarda los ajustes, y cada otro módulo los lee como `config.NAME` en el momento de usarlos, nunca copiados
(`config.py:1-2`; la regla se explica en [How it works](../../../guides/how-it-works.md#two-rules-that-keep-it-testable)).

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

## `paths.py`

Impide que quien llama nombre un archivo que no debe tocar:

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
