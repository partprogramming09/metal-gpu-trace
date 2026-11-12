# metal-gpu-trace

[![test](https://github.com/partprogramming09/metal-gpu-trace/actions/workflows/test.yml/badge.svg)](https://github.com/partprogramming09/metal-gpu-trace/actions/workflows/test.yml)

Mide cómo usa la GPU un programa de Wine o de macOS en un Mac con Apple silicon, desde la terminal o con un agente
de programación con IA: tiempo de GPU por frame, ritmo de frames, FPS y memoria, grabados con Metal System Trace de
Instruments; si una capa de traducción (DXMT, Mullion, MoltenVK) reparte el trabajo en demasiados encoders cortos;
capturas `.gputrace` de Metal leídas sin Xcode; y los datos que publica Apple de cada familia de GPU
para interpretar las cifras. Biblioteca estándar de Python 3.9+, `zsh` y Xcode (por `xctrace`). Licencia MIT.
[English](../README.md).

Arquitectura, decisiones y guías (en inglés): [`docs/README.md`](../docs/README.md). Para enviar un cambio:
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

| Archivo | Qué hace |
| --- | --- |
| `src/metal_gpu_trace/perf_record.sh` | Graba un programa N segundos con Metal System Trace y escribe `<etiqueta>_<fecha>.json` (ms de GPU por frame, intervalos entre frames, FPS, memoria de Metal y residente) y CSV por frame y de memoria. Borra el `.trace` al terminar salvo con `KEEP_TRACE=1`. |
| `src/metal_gpu_trace/perf_report.py` | Resume igual un `.trace` ya grabado. |
| `src/metal_gpu_trace/gputrace_read.py` | Lee una captura `.gputrace` de Metal sin Xcode: command buffers, encoders, dibujos, grupos de depuración. Los nombres marcados `probable` no están confirmados. |
| `src/metal_gpu_trace/data/apple-gpu-families.json` | Apple7 a Apple10: chips, qué añade cada familia y los límites que cambian, con las fuentes de Apple. |
| `src/metal_gpu_trace/metal_trace_mcp.py` | Un servidor MCP sobre todo lo anterior. |
| `tests/` | Comprobación sin Instruments: `python3 -I tests/run.py` imprime `ok`; `pytest tests` corre las mismas pruebas. |

## Grabar

```sh
PERF_OUT=~/perf-runs zsh src/metal_gpu_trace/perf_record.sh juego-d3d12 30 /ruta/a/wine ~/.wine /ruta/al/juego juego.exe
PERF_OUT=~/perf-runs zsh src/metal_gpu_trace/perf_record.sh app-metal 30 native - /ruta/a/app ./app
```

Argumentos: etiqueta, segundos, un directorio de Wine con `bin/wine` (o `native`), el prefijo de Wine, el directorio
de trabajo, el programa y sus argumentos. Sin `PERF_OUT`, las grabaciones van a `./perf-runs`. Leer la traza después
tarda cerca de un minuto en un M1 Pro (87 s para una grabación de 10 s); con el servidor MCP la llamada entera se
corta tras 10 s por segundo grabado más 120 s, y una grabación cortada no deja archivos. Solo corre una grabación a la
vez; no uses la GPU para otra cosa mientras graba.

Con Wine, dale 30 s: el arranque de Wine ocupa parte de la grabación. Una grabación de menos de 100 frames es
demasiado corta para comparar.

## Espacio en disco

Cada grabación guarda un resumen JSON y tres CSV, unos 2 MB por 10 s (casi todo, las muestras de memoria de Metal).
El `.trace` (decenas o cientos de MB) se borra salvo con `KEEP_TRACE=1`. `KEEP_RUNS=N` guarda solo las N grabaciones
más recientes. `PERF_MEMORY=0` se salta la tabla de memoria de Metal, la más lenta de leer: el resumen no trae
`metal_memory_mib` y no hay CSV de memoria (un 41 % más rápido al resumir una traza de 626 MB). Las herramientas MCP
`perf_record` y `perf_baseline_record` ofrecen lo mismo con `memory=false`.

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
la primera vez; para tener la última, corre el comando una vez con `--refresh` después de `uvx`.
`uvx metal-gpu-trace@0.4.0` fija una versión.

El servidor lee estas variables de entorno:

| Variable | Qué fija |
| --- | --- |
| `METAL_TRACE_OUT` | Dónde van las grabaciones. Usa una ruta absoluta: la de serie, `./perf-runs`, depende del directorio de trabajo del cliente. Un archivo de proyecto (abajo) manda sobre ella. |
| `METAL_TRACE_PROJECT` | El archivo de proyecto que se usa (o la carpeta que lo tiene), en vez de buscarlo desde el directorio de trabajo. |
| `METAL_TRACE_WINE` | El directorio de Wine (con `bin/wine`) que usa `perf_record` si la llamada no indica otro. |
| `WINEPREFIX` | El prefijo de Wine si la llamada no indica otro; si no, `~/.wine`. |
| `METAL_TRACE_READ` | Más directorios que las herramientas pueden leer, separados por `:`. |
| `METAL_TRACE_LOG` | `off` apaga la línea de log por llamada en stderr. |
| `KEEP_TRACE` | `1` guarda el `.trace` de cada grabación, para `trace_tables`, `trace_query` o Instruments. |
| `KEEP_RUNS` | Guarda solo las N grabaciones más recientes; nunca borra `baselines.json` ni `panel.json`. |
| `METAL_TRACE_LOCK` | El candado que hace que las grabaciones vayan de una en una, vaya cada una a la carpeta que vaya (de serie, `~/Library/Caches/metal-gpu-trace/recording.lock`). `perf_record.sh` lanzado a mano toma el mismo, o el que diga `PERF_LOCK`. |
| `PERF_ENV` | Pares `NOMBRE=VALOR`, separados por espacios, que recibe el programa grabado. |
| `PERF_INSTRUMENTS` | Instrumentos que se añaden a la plantilla Metal System Trace, separados por `;` (`xcrun xctrace list instruments` los nombra); sus tablas necesitan el `.trace`, así que va con `KEEP_TRACE=1`. |

### Proyectos

Un repositorio puede tener un `metal-gpu-trace.json` con el nombre de su proyecto y la carpeta de sus grabaciones:

```json
{"name": "mi-juego", "runs": "perf-runs", "profile": "translation-layer", "baseline": "main-ref"}
```

El servidor lo busca en su directorio de trabajo y en las carpetas de encima, hasta debajo de la carpeta personal,
así que un solo archivo en la raíz del repositorio sirve para todas sus carpetas. Si lo encuentra, las grabaciones se
guardan y se leen en `runs` en vez de en `METAL_TRACE_OUT` (`METAL_TRACE_READ` sigue añadiendo carpetas de lectura), y `baselines.json` también vive allí: los proyectos ya no mezclan sus grabaciones y
`KEEP_RUNS` limpia la carpeta de cada proyecto por separado. `runs` es relativa al archivo, empieza por `~/` o es absoluta.

| Clave | Significado |
| --- | --- |
| `name` | El nombre del proyecto (letras, dígitos, `.`, `_`, `-`). Obligatoria. |
| `runs` | La carpeta de las grabaciones. Obligatoria. Tiene que ser nueva, estar vacía o tener ya la marca del servidor (un archivo `.metal-gpu-trace-runs` normal, no una carpeta ni un enlace): `KEEP_RUNS` borra allí los `.json` antiguos, así que se rechaza una carpeta con otros archivos. La marca que deja el servidor lleva el `name` del proyecto, y el archivo de otro proyecto que nombre una carpeta marcada con otro nombre se rechaza; una marca vacía, puesta a mano, toma el nombre del primer proyecto que use la carpeta. Para pasar una carpeta a otro proyecto, edita o borra su marca. |
| `profile` | `translation-layer`, `native` o `generic` (la de serie). `perf_panel` abre con los ms de GPU por cuadro en `translation-layer` (con vsync, los FPS dejan de distinguir builds) y con los FPS en los demás, y redacta sus definiciones en consecuencia; `project_info` lo informa. |
| `baseline` | El nombre de la referencia del proyecto (`perf_baseline`). `perf_panel` juzga cada corrida contra ella, como lo haría `perf_check`, y `project_info` la informa; `perf_check` sigue usando la referencia que se le pasa. |
| `format` | `metal-gpu-trace`, el único por ahora. |

Cualquier otra clave, o un valor equivocado, es un error que cada herramienta explica, con el campo, hasta que se
arregle el archivo. `project_info` dice qué proyecto está activo y de dónde sale su carpeta. Sin archivo de proyecto
no cambia nada: se usa `METAL_TRACE_OUT`, o `./perf-runs`, como antes.

Con un `baseline`, `perf_panel` pone arriba de la página la comprobación contra la referencia: el veredicto de cada
corrida (el que da `perf_check`, con un margen del 3 %), el rango de la referencia, un mapa de calor y la tendencia de las
grabaciones más recientes del mismo programa. Sin `baseline`, o si la referencia nombrada no existe, la página lo dice y
muestra el resto.

### Claude Code

```sh
claude mcp add --scope user metal-trace -e METAL_TRACE_OUT=$HOME/perf-runs -e METAL_TRACE_WINE=/ruta/a/wine \
  -- uvx metal-gpu-trace
claude mcp list
```

`claude mcp list` muestra `metal-trace` conectado. `--scope user` lo deja disponible en todos los proyectos; sin él,
solo en el proyecto actual.

### Windows

En Windows el servidor graba programas nativos (`src/metal_gpu_trace/perf_record_windows.py`), sin Wine y sin Metal.
`METAL_TRACE_WINE` no hace falta: `perf_record` y `perf_attach` usan `native`. `METAL_TRACE_READ` se separa con `;`.

Los frames vienen de la aplicación de consola [PresentMon](https://github.com/GameTechDev/PresentMon) de Intel (MIT):
una fila por cada `Present()` del proceso, con `MsBetweenPresents` y el tiempo de GPU `MsGPUTime`. Descarga
`PresentMon-<versión>-x64.exe` de sus releases, comprueba su SHA-256 contra el que muestra GitHub y llama a la
herramienta `presentmon_install`, o ponlo en `%LOCALAPPDATA%\metal-gpu-trace` o en el `PATH`, o apunta
`PRESENTMON_EXE` a él. El usuario debe ser administrador o estar en el grupo «Performance Log Users». Sin PresentMon,
el resumen usa los intervalos de composición de DWM (`gpu.source` es `dwm-composition`): cubren todo el escritorio,
no ven juegos en pantalla completa exclusiva y no traen tiempo de GPU. Sin log de frames, sin PresentMon y sin
muestras de DWM, la grabación falla; nunca inventa frames.

Lo que no se puede medir es `null`, no cero: el 1 % bajo necesita 100 frames y el 0,1 % bajo 1000; la tasa de tirones
y el jitter necesitan dos frames; `thermal_throttling_detected` necesita tiempos de GPU; un log de drawstress tiene una
media por línea, así que su resumen (`gpu.frame_times`) no trae percentiles por frame, tirones ni jitter. DWM solo
guarda intervalos entre frames compuestos seguidos y descarta un salto de varios frames. `perf_diagnose` llama
`MEMORY_PRESSURE_SUSPECTED` a un conjunto de trabajo grande con tiempos de frame irregulares: es una sospecha, porque
el ancho de banda de memoria no se mide.

```powershell
winget install --id=astral-sh.uv -e
claude mcp add --scope user metal-trace -e METAL_TRACE_OUT=%USERPROFILE%\perf-runs -- uvx metal-gpu-trace
claude mcp list
```

Para correrlo desde un clon en vez de PyPI (necesita Python 3.9 o más nuevo):

```powershell
claude mcp add --scope user metal-trace -e METAL_TRACE_OUT=%USERPROFILE%\perf-runs -- python C:\ruta\a\metal-gpu-trace\src\metal_gpu_trace\metal_trace_mcp.py
```

En los clientes con JSON usa `"command": "uvx"` (o la ruta completa que imprime `where uvx`) y rutas de Windows con las
barras invertidas dobles. Claude Desktop lee `%APPDATA%\Claude\claude_desktop_config.json`. Las pruebas de Windows se
corren con `python -m pytest tests/test_perf_record_windows.py`.

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
| `perf_record` | Graba un programa y devuelve su resumen; al terminar cierra todo programa de su prefijo de Wine, o todo proceso con el nombre de un programa nativo. `counters=true` graba además los contadores de GPU de Metal: `gpu_counters` (los limitadores, la utilización, la ocupación y el ancho de banda de memoria de la GPU, con el limitador principal) en el resumen, a unos 40 s de lectura por segundo grabado; no en Windows |
| `perf_attach` | Graba un programa que ya corre, por pid o nombre, y lo deja corriendo |
| `project_info` | Dice qué proyecto está activo (por `metal-gpu-trace.json`), su perfil y su referencia, y su carpeta de grabaciones y de dónde sale |
| `perf_runs` | Lista las grabaciones, la más reciente primero, por páginas, si cada una guardó su `.trace`, y la capa de traducción con que corrió (una huella de sus DLL de Direct3D, y su Wine); `project` nombra el proyecto activo |
| `perf_compare` | Compara dos grabaciones: cifras principales, encoders, tiempo ocioso de la GPU y los ms de GPU por cuadro de cada etiqueta de encoder, el mayor cambio primero; marca las de menos de 100 frames. `markdown=true` añade las cifras como tablas Markdown para un comentario de PR; `skip_s` deja fuera los primeros segundos de cada grabación (el arranque) y recalcula sin ellos las cifras de GPU, los hitches y la memoria de Metal. `perf_gate` y `perf_panel` también aceptan `skip_s` |
| `perf_baseline` | Guarda varias grabaciones iguales como referencia con nombre y devuelve el rango que abarca cada cifra entre ellas y `spread_pct`, cuánto difieren corridas iguales (el ruido que un cambio tiene que superar); sola, lista las referencias. `skip_s` guarda cada corrida sin sus primeros segundos y `perf_check` aplica el mismo corte a la corrida que juzga |
| `perf_baseline_record` | Graba el mismo programa `count` veces (3 por defecto) con los argumentos de `perf_record` y guarda las corridas como referencia en una sola llamada. `skip_s` como en `perf_baseline` |
| `perf_cold_warm` | Graba el mismo programa dos veces seguidas y dice cuántos tirones por compilación de shaders tiene la primera ejecución más que la segunda (`first_seen_hitches`), con los tirones de cada una, los tirones por minuto y el tiempo del compilador gráfico; la caché de shaders de Metal no se vacía entre ellas |
| `perf_ab` | Graba el mismo programa con dos entornos (`env_a`, `env_b`: pares `NOMBRE=VALOR`) en el orden A B B A y dice por métrica (FPS, 1 % bajo, ms de GPU, tirones) si B es mejor, peor o igual: mejor o peor solo cuando todos los valores de B quedan fuera del rango de A |
| `perf_sweep` | Graba el mismo programa una vez por cada valor de una variable (`dim`, `size`, `example`, `api` o `env:NAME`), de 2 a 8 valores, `rounds` veces (una de cada dos rondas en orden inverso), y devuelve por valor la mediana de FPS, 1 % bajo, ms de GPU por cuadro y tirones; con 3 o más valores numéricos ajusta los ms de GPU por cuadro sobre el valor (ms fijos y ms por dibujo para `dim`) con su r2 |
| `perf_check` | Juzga una grabación contra una referencia: `regressed` si los FPS bajan del rango más de `margin_pct` (3 por defecto), los ms de GPU por cuadro lo superan, o los encoders o command buffers por cuadro lo exceden; `improved` o `same` si no, con las razones y la comparación completa |
| `perf_gate` | Comprueba una grabación contra presupuestos que fijas (pisos de FPS y de 1 % bajo; techos de tirones, ms de GPU p95, hitches y MiB de Metal) y devuelve pasa o falla con cada límite y valor; una cifra que falta falla |
| `perf_history` | Sigue FPS, 1 % bajo, ms de GPU, tirones, hitches y MiB de Metal en las corridas cuyo nombre empieza por un prefijo, de la más antigua a la más reciente, con el cambio de la primera a la última |
| `perf_panel` | Escribe `<nombre>.panel.html`: una página que abre con la comprobación contra la referencia del proyecto (el veredicto de cada corrida, dónde cae en el rango de la referencia, un mapa de calor y la tendencia de las builds más recientes) y luego muestra solo las secciones para las que las grabaciones tienen datos: el tiempo de GPU por cuadro y sus hitches, las cifras, la memoria de Metal y, con dos corridas, A contra B; lo que una grabación no recopiló se lista con lo que hay que hacer. Un proyecto `translation-layer` abre con los ms de GPU por cuadro, no con los FPS. Una grabación sin su `.frames.csv` se abre con sus cifras y sin curvas (no junto con `skip_s`). No tiene servidor y no carga nada de la red; quien la ve oculta o reordena widgets y exporta la disposición como JSON. Con `--http`, `/panel#token=...&runs=a,b` la muestra en vivo, refrescada cada 10 s. `layout` (ids de las secciones en orden: `tests`, `summary`, `ab`, `frames`, `encoders`, `counters`, `memory`, `data`) guarda `panel.json` en el directorio de corridas como orden por defecto de todo panel, el vivo incluido; un `panel.json` anterior a `tests` sigue funcionando |
| `perf_export_trace` | Escribe los frames de GPU de una grabación como `<corrida>.chrome-trace`, un corte por frame, para ui.perfetto.dev o chrome://tracing |
| `perf_diagnose` | Dice si una grabación reparte su trabajo de GPU en demasiados encoders cortos, como hacen las capas de traducción, con encoders y command buffers por cuadro, las etiquetas con más tiempo de GPU y el tiempo ocioso de la GPU |
| `trace_tables` | Lista las tablas de un `.trace` guardado, por el nombre de su grabación o su ruta |
| `trace_count` | Cuenta las filas de varias tablas de un `.trace` guardado, en total y por proceso; por defecto las que importan para una capa de traducción (intervalos de GPU, encoders, derrames del compilador, shaders compilados, asignaciones, contadores, Time Profiler), para ver una vacía antes de leerla |
| `trace_query` | Una página de filas de una tabla, opcionalmente de un proceso |
| `capture_summary` | Resume un `.gputrace`; lista sus 100 llamadas más frecuentes de `calls_total` |
| `capture_records` | Una página de los registros de un `.gputrace` |
| `gpu_family` | Los datos de Apple de una familia o chip (`Apple7`, `M1 Pro`, `M3 Max`) |
| `presentmon_install` | Solo Windows: descarga PresentMon, comprueba su SHA-256 fijado y lo guarda en `%LOCALAPPDATA%\metal-gpu-trace`, donde `perf_record` y `perf_attach` lo encuentran; Claude Code pregunta antes de cada uso |
| `workload_list` | Lista los programas de prueba que `workload_fetch` puede descargar; para `bgfx-examples`, `example_traits` da la clase de cada ejemplo y sus encoders por cuadro en Metal nativo |
| `workload_fetch` | Descarga un programa de prueba una vez, comprueba su SHA-256 y lo guarda en `~/Library/Caches/metal-gpu-trace`; Claude Code pregunta antes de cada uso |

`perf_record` acepta `workload`, `api` (`mtl`, `mtl-x64`, `vk`, `d3d11` o `d3d12`), `dim`, `size` y `example` en vez de
`program`, para grabar un programa de prueba descargado (`workload_list` dice qué tiene cada uno). `mtl-x64` es Metal
nativo compilado para x86_64 y ejecutado bajo Rosetta, como los programas de Wine; `size` (`"1920x1080"`) fija la
ventana de drawstress. El primer workload es
[17-drawstress](https://github.com/partprogramming09/metal-gpu-trace/releases/tag/workloads-3) de bgfx (BSD-2,
9,3 MB), compilado desde su código por `.github/workflows/workloads.yml`: una rejilla de cubos, `dim`³ dibujos por
cuadro, con sus shaders dentro del programa. El prompt `compare-layer` (`/metal-trace:compare-layer drawstress d3d12`
en Claude Code) lo graba en Metal nativo y bajo el Wine de `METAL_TRACE_WINE`, y después corre `perf_diagnose` y
`perf_compare`.

El segundo workload, `bgfx-examples` (55 MiB), trae treinta ejemplos de bgfx, cada uno una carga distinta (muchos
cubos, texturas, cadenas de render targets, un G-buffer, cómputo, mapas de sombras reflectantes, posprocesado, dibujos
que decide la GPU, texto e interfaz, sombras, transparencia, lectura desde la GPU, texturas virtuales, escalado,
formatos de textura, consultas de oclusión, teselado, varias ventanas, render fuera de pantalla; los últimos veintiuno
se midieron solo en Metal nativo y en D3D12 bajo Wine, `example_traits` en `workload_list` da la clase de cada uno y sus
encoders por cuadro en ambos, y 40-svt escribe una caché de teselas de 370 MB en `temp/` dentro de la carpeta del
workload la primera vez que corre): `perf_record(workload="bgfx-examples", api="d3d12", example="21-deferred")`. Dos
palancas de macOS cambian el Mac durante una grabación: `memory_free_pct` (de 20 a 60) mantiene todo el Mac con ese
porcentaje de RAM libre (`memory_pressure`), y `background` ejecuta el programa bajo `taskpolicy -b`, un
estrangulamiento fuerte. Un programa pequeño limitado por la GPU no nota la primera (drawstress siguió en 728 FPS y
bajó su memoria residente); la segunda lo frena varias veces. Repite una corrida que use cualquiera de las dos.

El tercer workload, `godot`, es una escena 3D iluminada que un motor real construye desde código (Godot 4.7.2,
Forward+): 400 mallas, 8 luces, un sol con sombras, `api="mtl"` para el driver Metal de Godot y `api="d3d12"` bajo Wine
para su driver Direct3D 12, con `args="-- meshes=800 lights=16"` para cambiarla. `workload_fetch("godot")` guarda el
proyecto de 10 KB de la release de este repositorio y descarga las builds oficiales de Godot para macOS (171 MB) y
Windows (86 MB) desde godotengine/godot-builds, comprobando el SHA-512 que fija este paquete; necesita unos 257 MB y
algunos segundos. La escena no tiene assets importados, así que Godot no importa nada. Godot compila sus pipelines en
cada arranque, lo que lo hace un caso para `perf_cold_warm`: sus tirones por compilación de shaders volvieron igual en
la segunda corrida.

### Leer las cifras entre corridas

- Un resumen dice dónde corrió y qué hizo la GPU: `machine` (chip, núcleos, RAM, macOS, `screen_locked`), `gpu_activity`
  (utilización del dispositivo, del renderizador y del tiler, escenas divididas, recuperaciones de la GPU: cubre toda la
  GPU, no solo el programa), `resource_allocations` (asignaciones por cuadro y por tipo; un total acumulado, no la
  memoria en uso) y `command_buffer_errors`.
- Una sesión bloqueada del Mac deja sin ritmo las ventanas de Metal nativo: de 3 000 a 4 000 FPS frente a 120 con vsync,
  en los mismos ejemplos. Graba con el Mac desbloqueado; `perf_compare` devuelve `screen` cuando una corrida se grabó
  bloqueada y la otra no.
- Los ms de GPU por cuadro siguen el estado de rendimiento de la GPU: una corrida a 120 FPS está en Minimum y tarda más ms
  para el mismo trabajo (21-deferred: 1,75 ms con vsync, 0,27 ms sin él). `perf_compare` devuelve `gpu_state` cuando dos
  corridas estuvieron en estados distintos, y `perf_diagnose` devuelve `display_synced_hz` cuando los FPS coinciden con
  una tasa de pantalla. Compara corridas con el mismo ritmo: Metal nativo y D3D12 bajo Wine con Mullion, ambos a
  120 FPS, sí se comparan.
- Con `counters=true`, cada hitch listado trae además `top_limiter`: el contador Limiter con mayor media en el intervalo
  anterior (`window_ms`, leído en bins enteros de 10 ms; `null` si ninguna muestra cae en él), que puede diferir del
  limitador principal de toda la grabación.

`api=vk` corre el mismo programa con Vulkan sobre MoltenVK. MoltenVK no viene incluido: apunta `METAL_TRACE_MOLTENVK`
a un directorio (sin espacios) con una `libMoltenVK.dylib` arm64, como la de un Vulkan SDK o la de
`brew install molten-vk`. El `layer` de la corrida nombra MoltenVK con el SHA-256 de la biblioteca, así que
`perf_compare` contra una corrida de Metal nativo dice que compara dos capas. En una medición con `dim=20`, 10 s cada
una: Metal nativo, 2 encoders por cuadro; MoltenVK, 13, el 91 % cortos, y la GPU ociosa el 89 % del tiempo
(`perf_diagnose`: `too_many_short_encoders` true). Es un par de corridas, no un benchmark.

`api=vk` es solo nativo. `drawstress.exe --vk` bajo Wine necesita un Wine compilado con Vulkan: se probaron el Wine de
DXMT y el Game Porting Toolkit de Apple, y los dos registran `Wine was built without Vulkan support`, así que la
grabación no tiene frames de GPU. El Wine de CrossOver trae Vulkan pero solo corre dentro de una de sus botellas, y eso
no se probó.

Los mismos datos están como resources de MCP: `metal-trace://gpu-families` (todos) y
`metal-trace://gpu-families/apple7` a `apple10`. Cada corrida guardada también es un resource:
`metal-trace://runs/<corrida>` lee su resumen. Repiten con otras palabras las
[Metal Feature Set Tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf) de Apple del 21 de mayo de
2026, [`MTLGPUFamily`](https://developer.apple.com/documentation/metal/mtlgpufamily) y la
[charla sobre el M3](https://developer.apple.com/videos/play/tech-talks/111375/); en un equipo concreto, compruébalo
con `supportsFamily`.

Cómo sigue la especificación MCP ([2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25) y
[2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)) y
[los límites de Claude Code](https://code.claude.com/docs/en/mcp):

- stdout lleva solo mensajes MCP; cada llamada a una herramienta deja una línea en stderr (`METAL_TRACE_LOG=off` la
  quita), sin argumentos ni rutas.
- Las listas van por páginas (`offset`, `limit`, 50 por defecto, 500 como mucho) con `total` y `next_offset`; un
  resultado de más de 40 000 caracteres se rechaza con la indicación de pedir una página más pequeña.
- Solo lee archivos dentro de la carpeta de grabaciones (`METAL_TRACE_OUT`, o el `runs` del proyecto) y de los directorios
  de `METAL_TRACE_READ` (separados por `:`).
- Los fallos vuelven como resultados `isError` que dicen qué hacer, sin trazas de pila ni rutas locales. Los
  resúmenes recortan las rutas absolutas al nombre del archivo, así que se pueden compartir.
- Cada llamada a `xctrace` tiene tiempo límite.

## HTTP

`METAL_TRACE_TOKEN=<secreto de 16 caracteres o más> metal-gpu-trace --http [--port N]` sirve las mismas herramientas en
`POST http://127.0.0.1:8765/mcp` (Streamable HTTP, una respuesta JSON por petición), para un cliente del mismo Mac que
no puede lanzar un servidor stdio. Cada petición necesita `Authorization: Bearer <token>`. Escucha solo en 127.0.0.1,
rechaza una petición cuyo Host u Origin no sea localhost o 127.0.0.1 (DNS rebinding) y no arranca sin el token. Habla
las dos épocas de MCP: un cliente que envía `initialize` recibe el comportamiento de siempre; uno que envía
`MCP-Protocol-Version: 2026-07-28` no tiene estado y debe enviar también `Mcp-Method` (y `Mcp-Name` para `tools/call`,
`prompts/get` y `resources/read`), que el servidor compara con el cuerpo (400 con `-32020` si no coinciden). Un cliente
moderno cancela una llamada en curso cerrando la conexión; un cliente `initialize` envía `notifications/cancelled`
desde otra conexión. Por HTTP no hay flujo de progreso ni acceso remoto: para llegar a otro Mac usa un túnel SSH
(`ssh -L 8765:127.0.0.1:8765 mac`), no abras el puerto. Por qué dos épocas:
[`docs/adr/0002-dual-era-mcp.md`](../docs/adr/0002-dual-era-mcp.md).

## Pruebas de Windows en una máquina real

El `windows-latest` de GitHub no tiene GPU ni sesión de escritorio, así que las grabaciones con PresentMon y DWM solo
se prueban en una máquina Windows real. `windows/winbridge-run-tests.ps1` pone al día un checkout allí y corre
`tests/test_perf_record_windows.py`; está escrito como una tarea de [WinBridge](https://github.com/partprogramming09/winbridge)
(nombre fijo, script fijado por SHA-256, sin argumentos). Para registrarlo, cópialo al portátil, pon en `$repo` la ruta
del checkout, saca allí su hash con `Get-FileHash <archivo> -Algorithm SHA256` (Git puede haber cambiado los finales
de línea, así que el hash de la copia de este repositorio no es el que sirve) y añade una tabla `[tasks.<nombre>]` con
`script` y `sha256` al TOML del agente.

## Compuerta de CI

`metal-gpu-trace check CORRIDA REFERENCIA [--margin-pct N]` corre `perf_check` sin cliente e imprime una línea JSON
(veredicto, razones, pistas). Código de salida 0: igual o mejor; 1: empeoró; 2: no se pudo juzgar (no existe la
corrida o la referencia, o tiene menos de 100 frames). Las corridas se leen de la carpeta de grabaciones (`METAL_TRACE_OUT`, o el `runs` del proyecto). Grabar necesita
Instruments, así que el job corre en un runner macOS propio:

```yaml
jobs:
  perf:
    runs-on: [self-hosted, macOS, ARM64]
    steps:
      - run: PERF_OUT=~/perf-runs zsh path/to/metal-gpu-trace/src/metal_gpu_trace/perf_record.sh pr 30 native - . ./app
      - run: METAL_TRACE_OUT=~/perf-runs metal-gpu-trace check "$(ls -t ~/perf-runs/pr_*.json | head -1 | xargs basename -s .json)" main-ref
```

## Créditos

- La estructura de los registros de un `.gputrace` sigue [tmc/gputrace](https://github.com/tmc/gputrace) (MIT); no se
  copia su código. Los identificadores de llamada se cotejaron con la lista de comandos de Xcode en macOS 27.0.1.
- Datos de las familias de GPU: los documentos de Apple enlazados arriba, contados con otras palabras, sin citarlos.
