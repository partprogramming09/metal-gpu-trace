# Configuración

**Lector:** personas que configuran el servidor: variables de entorno y archivos de proyecto.

English: [Configuration](../../../guides/server-and-transport/configuration.md) · [Índice](./index.md)

## Variables de entorno

| Variable | Qué fija |
| --- | --- |
| `METAL_TRACE_OUT` | Dónde van las grabaciones. Da una ruta absoluta: la de serie, `./perf-runs`, depende de la carpeta de trabajo del cliente. Un archivo de proyecto (abajo) manda sobre ella. |
| `METAL_TRACE_PROJECT` | El archivo de proyecto que se usa (o la carpeta que lo tiene), en vez de buscarlo desde el directorio de trabajo. |
| `METAL_TRACE_WINE` | El directorio de Wine (con `bin/wine`) que usa `perf_record` si la llamada no indica otro. |
| `WINEPREFIX` | El prefijo de Wine si la llamada no indica otro; si no, `~/.wine`. |
| `METAL_TRACE_READ` | Más directorios que las herramientas pueden leer, separados por `:` (`;` en Windows). |
| `METAL_TRACE_LOG` | `off` apaga la línea de log por llamada en stderr. |
| `KEEP_TRACE` | `1` guarda el `.trace` de cada grabación, para Instruments o el export en bruto (el archivo de tablas ya responde `trace_tables`, `trace_count` y `trace_query`). |
| `PERF_TABLES` | `0` no escribe `<etiqueta>.tables.sqlite`. |
| `METAL_TRACE_ALLOW_LOCKED` | `1` graba con la pantalla bloqueada. Sin él la grabación se rechaza: una sesión bloqueada deja los frames sin ritmo. |
| `METAL_TRACE_MAX_DISK_MB` | Límite de tamaño de la carpeta de grabaciones, en MiB. Tras cada grabación se borran primero el `.trace` más viejo, luego el `.chrome-trace` y luego las tablas por frame y de memoria; nunca los resúmenes ni `baselines.json`. [Retención](../../../guides/data-and-lifecycle/retention.md) |
| `KEEP_RUNS` | Guarda solo las N grabaciones más recientes. Nunca quita un `.trace`, y `baselines.json` nunca se borra. [Retención](../../../guides/data-and-lifecycle/retention.md) |
| `METAL_TRACE_LOCK` | El candado que hace que las grabaciones vayan de una en una, vaya cada una a la carpeta que vaya (de serie, `~/Library/Caches/metal-gpu-trace/recording.lock`). [Caché y candado](../../../guides/data-and-lifecycle/cache-and-lock.md) |
| `PERF_ENV` | Pares `NOMBRE=VALOR`, separados por espacios, que recibe el programa grabado. |
| `PERF_INSTRUMENTS` | Instrumentos que se añaden a la plantilla Metal System Trace, separados por `;` (`xcrun xctrace list instruments` los nombra). Sus tablas necesitan el `.trace`: va con `KEEP_TRACE=1`. |

## Proyectos

Un repositorio puede tener un `metal-gpu-trace.json` que da nombre a su proyecto y a la carpeta de sus grabaciones:

```json
{"name": "my-game", "runs": "perf-runs", "baseline": "main-ref"}
```

El servidor lo busca en su directorio de trabajo y en las carpetas de encima, hasta debajo de la carpeta personal, así que un solo archivo en la raíz del repositorio sirve para todas sus carpetas. Si lo encuentra, las grabaciones van a `runs` y se leen de allí en vez de `METAL_TRACE_OUT`, y `baselines.json` vive allí también: los proyectos no mezclan sus grabaciones. [Archivo de proyecto](../../../guides/data-and-lifecycle/project-and-config.md)

| Clave | Significado |
| --- | --- |
| `name` | El nombre del proyecto (letras, dígitos, `.`, `_`, `-`). Obligatorio. |
| `runs` | La carpeta de las grabaciones. Obligatoria. Tiene que ser nueva, estar vacía o tener ya la marca del servidor (un archivo `.metal-gpu-trace-runs` normal, no una carpeta ni un enlace). Una carpeta con otros archivos se rechaza, porque `KEEP_RUNS` borra allí los `.json` viejos. Una carpeta marcada con el nombre de otro proyecto se rechaza; para pasarla, edita o borra su marca. |
| `baseline` | El nombre de la referencia del proyecto (`perf_baseline`). `project_info` la informa. |
| `format` | `metal-gpu-trace`, el único por ahora. |

Cualquier otra clave, o un valor equivocado, es un error que cada herramienta explica, con el campo, hasta que se arregle el archivo. Sin archivo de proyecto se usa `METAL_TRACE_OUT`, o `./perf-runs`, como antes.
