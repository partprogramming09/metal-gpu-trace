# metal-gpu-trace

Mide cómo usa la GPU un programa de Wine o de macOS en un Mac con Apple silicon, desde la terminal o con un agente
de programación con IA: tiempo de GPU por frame, ritmo de frames, FPS y memoria, grabados con Metal System Trace de
Instruments; si una capa de traducción (DXMT, Mullion, MoltenVK) reparte el trabajo en demasiados encoders cortos;
capturas `.gputrace` de Metal leídas sin Xcode; y los datos que publica Apple de cada familia de GPU
para interpretar las cifras. Biblioteca estándar de Python 3.9+, `zsh` y Xcode (por `xctrace`). Licencia MIT.
[English](../README.md).

| Archivo | Qué hace |
| --- | --- |
| `perf_record.sh` | Graba un programa N segundos con Metal System Trace y escribe `<etiqueta>_<fecha>.json` (ms de GPU por frame, intervalos entre frames, FPS, memoria de Metal y residente) y CSV por frame y de memoria. Borra el `.trace` al terminar salvo con `KEEP_TRACE=1`. |
| `perf_report.py` | Resume igual un `.trace` ya grabado. |
| `gputrace_read.py` | Lee una captura `.gputrace` de Metal sin Xcode: command buffers, encoders, dibujos, grupos de depuración. Los nombres marcados `probable` no están confirmados. |
| `data/apple-gpu-families.json` | Apple7 a Apple10: chips, qué añade cada familia y los límites que cambian, con las fuentes de Apple. |
| `metal_trace_mcp.py` | Un servidor MCP sobre todo lo anterior. |
| `test_metal_trace_mcp.py` | Comprobación sin Instruments: `python3 -I test_metal_trace_mcp.py` imprime `ok`; `pytest` corre las mismas pruebas. |

## Grabar

```sh
PERF_OUT=~/perf-runs zsh perf_record.sh juego-d3d12 30 /ruta/a/wine ~/.wine /ruta/al/juego juego.exe
PERF_OUT=~/perf-runs zsh perf_record.sh app-metal 30 native - /ruta/a/app ./app
```

Argumentos: etiqueta, segundos, un directorio de Wine con `bin/wine` (o `native`), el prefijo de Wine, el directorio
de trabajo, el programa y sus argumentos. Sin `PERF_OUT`, las grabaciones van a `./perf-runs`. Leer la traza después
tarda cerca de un minuto en un M1 Pro (87 s para una grabación de 10 s); con el servidor MCP la llamada entera se
corta tras 10 s por segundo grabado más 120 s, y una grabación cortada no deja archivos. Solo corre una grabación a la vez; no uses la GPU para otra cosa mientras graba.

Con Wine, dale 30 s: el arranque de Wine ocupa parte de la grabación. Una grabación de menos de 100 frames es
demasiado corta para comparar.

## Espacio en disco

Cada grabación guarda un resumen JSON y tres CSV, unos 2 MB por 10 s (casi todo, las muestras de memoria de Metal).
El `.trace` (decenas o cientos de MB) se borra salvo con `KEEP_TRACE=1`. `KEEP_RUNS=N` guarda solo las N grabaciones
más recientes.

## Servidor MCP

### Instalar

El servidor corre con [`uvx`](https://docs.astral.sh/uv/) desde [PyPI](https://pypi.org/project/metal-gpu-trace/), sin clonar nada
(`brew install uv` lo instala). Para grabar hace falta además Xcode instalado (`xcrun xctrace version` imprime una
versión).

```sh
uvx metal-gpu-trace
```

Es el comando que lanza cada cliente de abajo. Las apps de escritorio no ven el `PATH` de Homebrew: dales la ruta
completa que imprime `which uvx` (`/opt/homebrew/bin/uvx` en Apple silicon). `uvx` se queda con la versión que bajó
la primera vez; para tener la última, corre el comando una vez con `--refresh` después de `uvx`. `uvx metal-gpu-trace@0.4.0` fija una versión.

El servidor lee estas variables de entorno:

| Variable | Qué fija |
| --- | --- |
| `METAL_TRACE_OUT` | Dónde van las grabaciones. Usa una ruta absoluta: la de serie, `./perf-runs`, depende del directorio de trabajo del cliente. |
| `METAL_TRACE_WINE` | El directorio de Wine (con `bin/wine`) que usa `perf_record` si la llamada no indica otro. |
| `WINEPREFIX` | El prefijo de Wine si la llamada no indica otro; si no, `~/.wine`. |
| `METAL_TRACE_READ` | Más directorios que las herramientas pueden leer, separados por `:`. |
| `METAL_TRACE_LOG` | `off` apaga la línea de log por llamada en stderr. |
| `KEEP_TRACE` | `1` guarda el `.trace` de cada grabación, para `trace_tables`, `trace_query` o Instruments. |
| `KEEP_RUNS` | Guarda solo las N grabaciones más recientes. |
| `PERF_ENV` | Pares `NOMBRE=VALOR`, separados por espacios, que recibe el programa grabado. |
| `PERF_INSTRUMENTS` | Instrumentos que se añaden a la plantilla Metal System Trace, separados por `;` (`xcrun xctrace list instruments` los nombra); sus tablas necesitan el `.trace`, así que va con `KEEP_TRACE=1`. |

### Claude Code

```sh
claude mcp add --scope user metal-trace -e METAL_TRACE_OUT=$HOME/perf-runs -e METAL_TRACE_WINE=/ruta/a/wine \
  -- uvx metal-gpu-trace
claude mcp list
```

`claude mcp list` muestra `metal-trace` conectado. `--scope user` lo deja disponible en todos los proyectos; sin él,
solo en el proyecto actual.

### Claude Desktop, Cursor y otros clientes con JSON

Estas apps no expanden `~` ni `$HOME`: escribe rutas absolutas.

```json
{
  "mcpServers": {
    "metal-trace": {
      "command": "/opt/homebrew/bin/uvx",
      "args": ["metal-gpu-trace"],
      "env": {
        "METAL_TRACE_OUT": "/ruta/absoluta/a/perf-runs",
        "METAL_TRACE_WINE": "/ruta/absoluta/a/wine"
      }
    }
  }
}
```

| Cliente | Archivo |
| --- | --- |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (Ajustes, Desarrollador, Editar configuración); reinicia la app |
| Cursor | `~/.cursor/mcp.json` |
| VS Code | `.vscode/mcp.json` en el proyecto; la clave de arriba es `servers` en vez de `mcpServers`, y el servidor añade `"type": "stdio"` |

### Codex CLI

En `~/.codex/config.toml`:

```toml
[mcp_servers.metal-trace]
command = "/opt/homebrew/bin/uvx"
args = ["metal-gpu-trace"]
env = { METAL_TRACE_OUT = "/ruta/absoluta/a/perf-runs", METAL_TRACE_WINE = "/ruta/absoluta/a/wine" }
```

### Herramientas

| Herramienta | Lee o graba |
| --- | --- |
| `perf_record` | Graba un programa y devuelve su resumen; al terminar cierra todo programa de su prefijo de Wine, o todo proceso con el nombre de un programa nativo |
| `perf_attach` | Graba un programa que ya corre, por pid o nombre, y lo deja corriendo |
| `perf_runs` | Lista las grabaciones, la más reciente primero, por páginas, si cada una guardó su `.trace`, y la capa de traducción con que corrió (una huella de sus DLL de Direct3D, y su Wine) |
| `perf_compare` | Compara dos grabaciones: cifras principales, encoders, tiempo ocioso de la GPU y los ms de GPU por cuadro de cada etiqueta de encoder, el mayor cambio primero; marca las de menos de 100 frames |
| `perf_baseline` | Guarda varias grabaciones iguales como referencia con nombre y devuelve el rango que abarca cada cifra entre ellas; sola, lista las referencias |
| `perf_baseline_record` | Graba el mismo programa `count` veces (3 por defecto) con los argumentos de `perf_record` y guarda las corridas como referencia en una sola llamada |
| `perf_check` | Juzga una grabación contra una referencia: `regressed` si los FPS bajan del rango más de `margin_pct` (3 por defecto), los ms de GPU por cuadro lo superan, o los encoders o command buffers por cuadro lo exceden; `improved` o `same` si no, con las razones y la comparación completa |
| `perf_diagnose` | Dice si una grabación reparte su trabajo de GPU en demasiados encoders cortos, como hacen las capas de traducción, con encoders y command buffers por cuadro, las etiquetas con más tiempo de GPU y el tiempo ocioso de la GPU |
| `trace_tables` | Lista las tablas de un `.trace` guardado, por el nombre de su grabación o su ruta |
| `trace_count` | Cuenta las filas de varias tablas de un `.trace` guardado, en total y por proceso; por defecto las que importan para una capa de traducción (intervalos de GPU, encoders, derrames del compilador, shaders compilados, asignaciones, contadores, Time Profiler), para ver una vacía antes de leerla |
| `trace_query` | Una página de filas de una tabla, opcionalmente de un proceso |
| `capture_summary` | Resume un `.gputrace`; lista sus 100 llamadas más frecuentes de `calls_total` |
| `capture_records` | Una página de los registros de un `.gputrace` |
| `gpu_family` | Los datos de Apple de una familia o chip (`Apple7`, `M1 Pro`, `M3 Max`) |
| `workload_list` | Lista los programas de prueba que `workload_fetch` puede descargar |
| `workload_fetch` | Descarga un programa de prueba una vez, comprueba su SHA-256 y lo guarda en `~/Library/Caches/metal-gpu-trace`; Claude Code pregunta antes de cada uso |

`perf_record` acepta `workload`, `api` (`mtl`, `d3d11` o `d3d12`) y `dim` en vez de `program`, para grabar un
programa de prueba descargado. El primero es
[17-drawstress](https://github.com/partprogramming09/metal-gpu-trace/releases/tag/workloads-1) de bgfx (BSD-2,
7,5 MB), compilado desde su código por `.github/workflows/workloads.yml`: una rejilla de cubos, `dim`³ dibujos por
cuadro, con sus shaders dentro del programa. El prompt `compare-layer` (`/metal-trace:compare-layer drawstress d3d12`
en Claude Code) lo graba en Metal nativo y bajo el Wine de `METAL_TRACE_WINE`, y después corre `perf_diagnose` y
`perf_compare`.

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
