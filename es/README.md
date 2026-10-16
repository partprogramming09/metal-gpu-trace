# metal-gpu-trace

Mide cómo usa la GPU un programa de Wine o de macOS en un Mac con Apple silicon, desde la terminal o con un agente
de programación con IA: tiempo de GPU por frame, ritmo de frames, FPS y memoria, grabados con Metal System Trace de
Instruments; capturas `.gputrace` de Metal leídas sin Xcode; y los datos que publica Apple de cada familia de GPU
para interpretar las cifras. Biblioteca estándar de Python 3.9+, `zsh` y Xcode (por `xctrace`). Licencia MIT.
[English](../README.md).

| Archivo | Qué hace |
| --- | --- |
| `perf_record.sh` | Graba un programa N segundos con Metal System Trace y escribe `<etiqueta>_<fecha>.json` (ms de GPU por frame, intervalos entre frames, FPS, memoria de Metal y residente) y CSV por frame y de memoria. Borra el `.trace` al terminar salvo con `KEEP_TRACE=1`. |
| `perf_report.py` | Resume igual un `.trace` ya grabado. |
| `gputrace_read.py` | Lee una captura `.gputrace` de Metal sin Xcode: command buffers, encoders, dibujos, grupos de depuración. Los nombres marcados `probable` no están confirmados. |
| `data/apple-gpu-families.json` | Apple7 a Apple10: chips, qué añade cada familia y los límites que cambian, con las fuentes de Apple. |
| `metal_trace_mcp.py` | Un servidor MCP sobre todo lo anterior. |
| `test_metal_trace_mcp.py` | Comprobación sin Instruments: `python3 -I test_metal_trace_mcp.py` imprime `ok`. |

## Grabar

```sh
PERF_OUT=~/perf-runs zsh perf_record.sh juego-d3d12 30 /ruta/a/wine ~/.wine /ruta/al/juego juego.exe
PERF_OUT=~/perf-runs zsh perf_record.sh app-metal 30 native - /ruta/a/app ./app
```

Argumentos: etiqueta, segundos, un directorio de Wine con `bin/wine` (o `native`), el prefijo de Wine, el directorio
de trabajo, el programa y sus argumentos. Sin `PERF_OUT`, las grabaciones van a `./perf-runs`. Leer la traza después
tarda cerca de un minuto en un M1 Pro (87 s para una grabación de 10 s); con el servidor MCP la llamada entera se
corta 300 s después de la grabación. Solo corre una grabación a la vez; no uses la GPU para otra cosa mientras graba.

Con Wine, dale 30 s: el arranque de Wine ocupa parte de la grabación. Una grabación de menos de 100 frames es
demasiado corta para comparar.

## Espacio en disco

Cada grabación guarda un resumen JSON y tres CSV, unos 2 MB por 10 s (casi todo, las muestras de memoria de Metal).
El `.trace` (decenas o cientos de MB) se borra salvo con `KEEP_TRACE=1`. `KEEP_RUNS=N` guarda solo las N grabaciones
más recientes.

## Servidor MCP

```sh
claude mcp add metal-trace -e METAL_TRACE_OUT=$HOME/perf-runs -e METAL_TRACE_WINE=/ruta/a/wine \
  -- python3 -I /ruta/a/metal-gpu-trace/metal_trace_mcp.py
```

| Herramienta | Lee o graba |
| --- | --- |
| `perf_record` | Graba un programa y devuelve su resumen |
| `perf_runs` | Lista las grabaciones, la más reciente primero, por páginas |
| `perf_compare` | Compara dos grabaciones; marca las de menos de 100 frames |
| `trace_tables` | Lista las tablas de un `.trace` guardado |
| `trace_query` | Una página de filas de una tabla, opcionalmente de un proceso |
| `capture_summary` | Resume un `.gputrace` |
| `capture_records` | Una página de los registros de un `.gputrace` |
| `gpu_family` | Los datos de Apple de una familia o chip (`Apple7`, `M1 Pro`, `M3 Max`) |

Los mismos datos están como resources de MCP: `metal-trace://gpu-families` (todos) y
`metal-trace://gpu-families/apple7` a `apple10`. Repiten con otras palabras las
[Metal Feature Set Tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf) de Apple del 21 de mayo de
2026, [`MTLGPUFamily`](https://developer.apple.com/documentation/metal/mtlgpufamily) y la
[charla sobre el M3](https://developer.apple.com/videos/play/tech-talks/111375/); en un equipo concreto, compruébalo
con `supportsFamily`.

Cómo sigue la [especificación MCP](https://modelcontextprotocol.io/specification/2025-06-18) y
[los límites de Claude Code](https://code.claude.com/docs/en/mcp):

- stdout lleva solo mensajes MCP; cada llamada a una herramienta deja una línea en stderr (`METAL_TRACE_LOG=off` la
  quita), sin argumentos ni rutas.
- Las listas van por páginas (`offset`, `limit`, 50 por defecto, 500 como mucho) con `total` y `next_offset`; un
  resultado de más de 40 000 caracteres se rechaza con la indicación de pedir una página más pequeña.
- Solo lee archivos dentro de `METAL_TRACE_OUT` y de los directorios de `METAL_TRACE_READ` (separados por `:`).
- Los fallos vuelven como resultados `isError` que dicen qué hacer, sin trazas de pila ni rutas locales. Los
  resúmenes recortan las rutas absolutas al nombre del archivo, así que se pueden compartir.
- Cada llamada a `xctrace` tiene tiempo límite.

## Créditos

- La estructura de los registros de un `.gputrace` sigue [tmc/gputrace](https://github.com/tmc/gputrace) (MIT); no se
  copia su código. Los identificadores de llamada se cotejaron con la lista de comandos de Xcode en macOS 27.0.1.
- Datos de las familias de GPU: los documentos de Apple enlazados arriba, contados con otras palabras, sin citarlos.
