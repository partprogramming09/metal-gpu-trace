# Archivos en disco

**Lector:** personas que necesitan saber qué deja una grabación en disco y dónde. Revisado el 2026-11-16.

English: [Files on disk](../../../guides/data-and-lifecycle/files-on-disk.md)

> **En corto:** una corrida es un puñado de archivos que comparten el principio del nombre, en una carpeta. Esta página
> dice dónde está esa carpeta, qué guarda cada archivo, quién lo escribe y quién lo lee, y luego los dos formatos de tabla y los dos muestreadores de una vez por segundo.

Volver al [índice](./index.md). Ejemplo: en la corrida `v070-d3d12_20261018-021158`, el `.rss.csv` pesa 367 bytes y la carpeta `.trace` 259 MiB ([E1](./evidencia-corridas.md#e1-los-archivos-que-deja-una-corrida), [E2](./evidencia-corridas.md#e2-tamano)).

## Dónde vive cada cosa

| Qué | Dónde | Quién lo fija |
|---|---|---|
| Carpeta de corridas, servidor MCP | `./perf-runs` del directorio de trabajo del servidor | `METAL_TRACE_OUT` (`config.py:16`); un archivo de proyecto la sustituye (`project.py:188`) |
| Carpeta de corridas, `perf_record.sh` a mano | `PERF_OUT`, si no `<clone>/logs/perf` si existe, si no `./perf-runs` | `perf_record.sh:28-29` |
| Otras carpetas legibles | `METAL_TRACE_READ`, separadas por `:` | `config.py:17` |
| Caché de programas de prueba | `~/Library/Caches/metal-gpu-trace` (Windows: `%LOCALAPPDATA%\metal-gpu-trace`) | `config.py:37-40` |
| Candado de grabación | `<cache>/recording.lock/` | `METAL_TRACE_LOCK` o `PERF_LOCK` (`config.py:42`, `perf_record.sh:42`) |
| Temporales `.ktrace` de Instruments | `$TMPDIR/instruments*.ktrace`, se borran al terminar el script | `perf_record.sh:63-69` |

Los dos valores por defecto de la carpeta de corridas difieren: una grabación del servidor y otra a mano desde un clon caen en sitios distintos (confirmado; límite conocido 10).

## Qué deja una grabación en disco

| Archivo | Contiene | Lo escribe | Tamaño (E1, E2) | Lo lee |
|---|---|---|---|---|
| `<run>.json` | El resumen ([claves](./claves-del-resumen.md)) | `perf_report.py:836`, reescrito por `recording.py:350` | 4,9 KiB | Todas las herramientas de análisis (`analysis.py`), `perf_runs` |
| `<run>.frames.csv.gz` | Una fila por fotograma de GPU presentado; `.csv` sin comprimir antes de la 0.27.0 | `perf_report.py:831` (macOS), `perf_record_windows.py:847` (Windows) | 56 KiB sin comprimir, 20 s | `analysis.read_frames` (`analysis.py:508`), exportación a Chrome trace (`traces.py:15`) |
| `<run>.metal_memory.csv.gz` | Memoria de Metal a lo largo del tiempo | `perf_report.py:745` | 418 KiB sin comprimir | `analysis.py:527` |
| `<run>.rss.csv` | Memoria residente, una vez por segundo | muestreador `perf_record.sh:105-113`; `perf_record_windows.py:669` (Windows) | 367 bytes | `perf_report.py:749-753` la integra en `process_rss_mib` |
| `<run>.agx.csv` | Contadores del controlador de la GPU para toda la GPU, una vez por segundo | muestreador `perf_record.sh:106-114` | 575 bytes | `perf_report.py:754-756` la integra en `gpu_activity` |
| `<run>.trace/` | El paquete de Instruments (una carpeta) | `xctrace`, `perf_record.sh:140-151` | 259 MiB | `trace_query`, `trace_tables`, Instruments |
| `<run>.chrome-trace` | Fotogramas como Chrome trace, solo al llamar a la herramienta de exportación | `traces.py:28` | no medido aquí | visor de trazas de un navegador |
| `<run>.presentmon.csv` | Filas de PresentMon (solo Windows) | `perf_record_windows.py:650` | no medido aquí | `perf_record_windows.py` |
| `<run>.drawstress.log` | Registro del programa de prueba, una línea por lote de fotogramas (solo Windows, fuente `drawstress-log`) | `perf_record_windows.py:632-633`, se conserva tras una grabación buena (`:937-941`) | no medido aquí | `perf_record_windows.py:762-764`; la cuota lo ignora, como `.presentmon.csv` (`retention.py:30-43`) |
| `baselines.json` | Referencias con nombre: copias de varios resúmenes | `analysis.py:282` | 10 KiB, 1 línea base de 3 corridas ([E7](./evidencia-corridas.md#e7-el-archivo-de-lineas-base)) | `load_baselines`, `analysis.py:254` |
| `.metal-gpu-trace-runs` | La marca de la carpeta: un archivo simple con el nombre del proyecto | `project.py:198` | 8 bytes | `project.mark_owner`, `project.py:109` |
| `panel.json` | Lo dejó la 0.24.0, cuyo panel se quitó ([ADR-0005](../../../adr/0005-remove-the-panel.md)) | nadie ahora | ninguno aquí | solo se omite: `paths.py:10`, `analysis.py:52` |

Archivos que existen solo mientras graba: `<run>.validation.log` (con validación de Metal; se borra en `perf_record.sh:161`) y restos de una escritura de tabla interrumpida (`<table>.csv.gz.<hex>.tmp`, ver [Cuando falla](./cuando-falla.md)).

![Una tabla con una fila por tipo de archivo de una corrida y cuatro columnas: quién lo escribe, qué pasa al final de una corrida, qué hace KEEP_RUNS y qué hace METAL_TRACE_MAX_DISK_MB. Solo KEEP_RUNS borra alguna vez un resumen, y solo la cuota borra un .trace; baselines.json y la marca de la carpeta no se borran nunca.](./img/data-files-per-run.png)
*Figura 1. Los archivos de una corrida y qué borra cada poda. Fuente HTML: `docs/es/guides/datos-y-su-ciclo-de-vida/img/data-files-per-run.html`.*

## Las tablas y los muestreadores

| Archivo | Cabecera | Notas |
|---|---|---|
| `frames.csv(.gz)` | `frame,start_ms,gpu_ms_<channel>...,gpu_ms_total` | Una columna `gpu_ms_<channel>` en minúsculas por canal del trazo (`perf_report.py:831-834`); el ejemplo real ([E4](./evidencia-corridas.md#e4-las-columnas-de-las-tablas)) tiene `compute`, `fragment`, `vertex`. En Windows el único canal es `draw` (`perf_record_windows.py:847`). Los fotogramas no presentados no están aquí sino en `gpu.unpresented` (`perf_report.py:695-721`) |
| `metal_memory.csv(.gz)` | `time_ms,metal_allocated_bytes` | Una fila por muestra de las asignaciones de Metal del programa (`perf_report.py:745-746`) |
| `rss.csv` | `time_s,rss_kib` | Bucles de shell de fondo (`perf_record.sh:104-118`), `seconds + 5` pasos de un segundo; texto simple, nunca comprimido |
| `agx.csv` | `time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib` | Los mismos bucles (`perf_record.sh:105-106`) |

**Cómo se escribe y se lee una tabla** (`tables.py`):

- Se escribe como `<stem>.csv.gz` con nombre temporal `<target>.<8 hex>.tmp` en la misma carpeta y se renombra sobre el destino con `os.replace` (`tables.py:43-52`): un lector nunca ve media tabla, y una excepción borra el temporal (`tables.py:53-58`).
- Mismas filas, mismos bytes: la cabecera gzip no lleva nombre y `mtime=0` (`tables.py:48`).
- La lee `tables.find` (`tables.py:13`): primero `.csv.gz`, luego `.csv`, así que las corridas anteriores a la 0.27.0 siguen funcionando. Un enlace nunca es una tabla (`tables.py:18`, `:26`); un `.gz` de cero bytes es un error, no una tabla vacía (`tables.py:29-30`).

Las carpetas reales de aquí no tienen ningún `.csv.gz` (E1), así que la ruta comprimida y su ahorro **no se reprodujeron** en una grabación real. La proporción viene del [ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md) y de [la prueba de la 0.27.0](../../../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit).
