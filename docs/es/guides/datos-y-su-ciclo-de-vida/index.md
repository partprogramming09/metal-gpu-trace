# Datos y su ciclo de vida

**Lector:** personas que cambian el grabador o el análisis, o que necesitan saber qué deja una grabación en disco, dónde vive y quién la borra. Revisado el 2026-11-16.

English: [Data and its lifecycle](../../../guides/data-and-lifecycle/index.md)

> **En corto:** cada grabación deja un pequeño grupo de archivos en una carpeta. Un archivo pequeño guarda los números
> que lee un agente; los demás son los datos de los que salieron. Solo un nombre común mantiene unido el grupo, y dos
> ajustes de limpieza deciden qué se borra y cuándo. Esta guía sigue una grabación desde que se pide hasta que se borra; las capas están en [How it works](../../../guides/how-it-works.md). Es la versión en español de la guía en inglés: mismo contenido, mismos diagramas y misma evidencia (comandos y salidas no se traducen).

## Cómo leer las etiquetas

| Etiqueta | Significado |
|---|---|
| **confirmado** | Leído con `rg` o `sed` el 2026-11-16 contra el árbol de trabajo (la 0.27.2 más las entradas `[Unreleased]` de `CHANGELOG.md`), con `archivo:línea` |
| **probable** | Leído en el código, no ejecutado aquí |
| **especulación** | Una conjetura sobre el porqué |
| **no reproducido** | No se pudo correr aquí (la página de evidencia dice por qué) |

Las líneas se mueven cuando cambia el código: busca el nombre. Cada cifra viene con su comando en las páginas de evidencia ([E1 a E7](./evidencia-corridas.md), [E8 a E12](./evidencia-cache-y-flujo.md)).

## Un ejemplo primero

Un agente graba un programa durante 20 segundos con la etiqueta `mygame`. La carpeta de grabaciones contiene entonces archivos como estos (una carpeta real de otra grabación del mismo tipo, recortada; comando: [E1](./evidencia-corridas.md#e1-los-archivos-que-deja-una-corrida)):

```text
baselines.json
v070-d3d12_20261018-021158.json
v070-d3d12_20261018-021158.rss.csv
v070-d3d12_20261018-021158.trace          <- una carpeta, 259 MiB
```

Los archivos de una grabación comparten un **stem** (el prefijo común del nombre): la etiqueta, un guion bajo y la hora de inicio (`<label>_<YYYYMMDD-HHMMSS>`, `perf_record.sh:26`). No hay base de datos ni índice. El `.json` pequeño es el **resumen** (lo que lee un agente); el `.trace` es la grabación cruda de Instruments y ocupa casi toda la carpeta ([E2](./evidencia-corridas.md#e2-tamano): 259 MiB de 259 MiB).

## Las páginas

| Página | Responde |
|---|---|
| [Por qué los datos tienen esta forma](./por-que-esta-forma.md) | JSON pequeño más archivos hermanos, sin base de datos, dos ajustes de limpieza |
| [Archivos en disco](./archivos-en-disco.md) | Dónde vive cada carpeta, qué deja una corrida, tablas y muestreadores (Figura 1) |
| [El resumen, clave por clave](./claves-del-resumen.md) | Qué claves hay, cuáles siempre, cuáles bajo una condición, las tres generaciones |
| [El archivo de proyecto, `config.py` y `paths.py`](./proyecto-y-configuracion.md) | El archivo de proyecto, la marca, las líneas base, los ajustes, las guardas de rutas |
| [Retención](./retencion.md) | `KEEP_RUNS` frente a `METAL_TRACE_MAX_DISK_MB`, y qué sobrevive |
| [La caché y el candado](./cache-y-candado.md) | La caché de programas de prueba y el candado de una grabación a la vez |
| [De una grabación a disco](./de-grabacion-a-disco.md) | Los ocho pasos de una grabación en macOS (Figura 2) |
| [Cuando falla](./cuando-falla.md) | Qué queda en disco tras cada fallo y quién lo limpia |
| [Límites conocidos y tocarlo sin romperlo](./limites.md) | Los 11 límites conocidos y cómo cambiar esta zona con seguridad |
| Evidencia: [E1 a E7](./evidencia-corridas.md), [E8 a E12](./evidencia-cache-y-flujo.md) | Archivos, tamaños, claves, columnas, el patrón del stem, líneas base; la caché, versiones fijadas, los ocho pasos, variables, lo no reproducido |

## Véase también

- [How it works](../../../guides/how-it-works.md): las capas y el recorrido de una petición.
- [ADR-0004](../../../adr/0004-project-file.md): el archivo de proyecto y la marca de la carpeta de corridas.
- [ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md): tablas comprimidas y el límite de disco.
- [Prueba de la 0.27.0](../../../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit): el límite de tamaño medido.
