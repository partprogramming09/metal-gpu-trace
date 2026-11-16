# Evidencia: preflight, script, plazo, motor de Windows

**Lector:** personas que quieren repetir una comprobación o ver de dónde sale una afirmación de la guía de grabación. Revisado el 2026-11-16. Etiquetas: véase [Grabar](./index.md#como-leer-las-etiquetas).

English: [Evidence](../../../guides/recording/evidence.md)

**En corto:** cada número y mensaje de la guía de grabación sale de un comando que cualquiera puede correr. Esta página
tiene los comandos de las comprobaciones, el script, las fórmulas de plazo y disco, el motor de Windows y PresentMon (E1,
E2, E3, E6, E8, E9, E10), con su salida real, y termina con lo que **no** se reprodujo. Los programas de prueba y los
archivos de datos (E4, E5, E7) están en [Evidencia: datos](./evidencia-datos.md).

Recogida el 2026-11-16 en un Mac con Apple silicon. Todos los comandos solo leen. Las rutas están acortadas: la carpeta
personal es `~`. La sesión podía correr comandos de solo lectura (`rg`, `sed`, `jq`, `ls`, `du`), no Python ni los
scripts, así que nada de lo que sigue es la salida de una grabación ni de una comprobación corrida en vivo: lo que *dice*
una comprobación se lee de la línea que la lanza.

## E1 Cada mensaje que puede lanzar preflight, con su línea

```text
$ rg -n "raise paths.ToolError" src/metal_gpu_trace/preflight.py | cut -c1-175
71:        raise paths.ToolError("the free disk space cannot be read for the runs or the temporary folder") from None
108:        raise paths.ToolError("seconds is a whole number from 1 to 3600")
110:        raise paths.ToolError("environ is a mapping of text")
113:        raise paths.ToolError("wine is a path or native or attach, and the command a list of strings")
116:        raise paths.ToolError("no Wine at bin/wine inside that Wine directory (pass native for a macOS program)")
119:        raise paths.ToolError(f"{name} is not an executable file")
121:        raise paths.ToolError("xcrun is not on PATH: install Xcode or the command line tools (xcode-select --install)")
130:            raise paths.ToolError(f"not enough free disk on {what}: {free} GB free, {need} GB needed "
133:        raise paths.ToolError("the screen is locked: a locked session leaves the program's frames unpaced by the display, "
136:        raise paths.ToolError("another recording is running; one runs at a time. If none is, remove the lock folder "
```

`cut` recorta cada línea a 175 caracteres. Los números de línea en orden (108, 116, 121, 130, 133, 136) son el orden en
que corren las comprobaciones. Correr `preflight.check` con un sustituto para cada fallo **no se reprodujo**;
`tests/test_preflight.py` tiene una prueba por fallo (`:65` a `:162`), no ejecutadas. Lo usa [Preflight](./preflight.md).

## E2 Qué rechaza el propio script, y con qué código de salida

```text
$ rg -n "exit [0-9]+|exit \$\{" src/metal_gpu_trace/perf_record.sh | cut -c1-170
10:[[ $label =~ '^[A-Za-z0-9._-]+$' ]] || { echo "label may hold only letters, digits, '.', '_' and '-'" >&2; exit 2; }
11:[[ $seconds == <1-3600> ]] || { echo "seconds must be 1 to 3600" >&2; exit 2; }
12:[[ $wine == (native|attach) || -x $wine/bin/wine ]] || { echo "no Wine at $wine/bin/wine (or pass native or attach)" >&2; exit 2; }
13:[[ $wine != native || ( -f $1 && -x $1 ) ]] || { echo "${1:t} is not an executable file" >&2; exit 2; }
18:    { echo "${1:t} is not a program the system can run (no Mach-O or #! header)" >&2; exit 2; }
24:  [[ -n $pid ]] && kill -0 $pid 2>/dev/null || { echo "no running process matches $1" >&2; exit 2; }
37:  (( free >= need )) || { echo "not enough free disk on $dir: $free GB free, $need GB needed (PERF_MIN_FREE_GB overrides)" >&2; exit 4; }
49:  exit 3
… recortado (líneas 55 `trap 'exit 130' INT TERM` y 74 `trap 'rm -rf $out/$name.*(N); exit 143' TERM`)
156:[ -d $out/$name.trace ] || { echo "no recording at $out/$name.trace" >&2; exit 1; }
```

El mensaje del candado es el `echo` de la línea anterior a la 49, `perf_record.sh:48`. Las líneas 12, 37, 48 y 156 imprimen
una ruta o una carpeta; la 13 y la 18 imprimen solo el nombre del archivo, lo que afirma una prueba
(`tests/test_recording.py:565`, [límite 1](./limites.md)). Correr el script con un argumento malo **no se reprodujo**.

## E3 Los números: plazo y disco, según las fórmulas del código

```text
$ jq -n -c '{deadline_s:([20,30,60]|map(.*15+180)), deadline_counters_s:([20,30,60]|map(.*55+180)), disk_gb:([20,30,60]|map(2+((.*8+9)/10|floor))), disk_gb_windows:1}'
{"deadline_s":[480,630,1080],"deadline_counters_s":[1280,1830,3480],"disk_gb":[18,26,50],"disk_gb_windows":1}
```

Las fórmulas son `seconds × 15 + 180` (`recording.py:269`, 55 con contadores) y `2 + (seconds × 8 + 9) / 10` en
división entera (`preflight.py:50`). Reproducen lo que declara el servidor: 630 s para 30 s de Wine, y «26 GB for 30 s,
50 GB for 60 s» (`metal_trace_mcp.py:27-28`). Son las fórmulas del código evaluadas por `jq`, no una medición.

## E6 Dónde fija el servidor el entorno del script

```text
$ rg -n 'env\["|PERF_OUT=|PERF_LOCK=|PERF_PARENT_PID=|PERF_ENV=' src/metal_gpu_trace/recording.py
360:    env = dict(os.environ, PERF_OUT=str(config.OUT), PERF_LOCK=str(config.LOCK), PERF_PARENT_PID=str(os.getpid()),
361:               PERF_ENV=" ".join(filter(None, [os.environ.get("PERF_ENV", ""), program_env])))
363:        env["PERF_MEMORY"] = "0"
365:        env["KEEP_TRACE"] = "1"
367:        env["PERF_PREFIX"] = BACKGROUND_PREFIX
369:        env["PERF_INSTRUMENTS"] = ";".join(filter(None, [os.environ.get("PERF_INSTRUMENTS", ""), "Metal GPU Counters"]))
370:    layer = layer or layer_of(wine, prefix, env["PERF_ENV"])
… recortado (377: la llamada al motor de Windows)
```

Lo usa [El recorrido en macOS, paso 3](./recorrido-macos.md#paso-3-el-entorno-que-recibe-el-script).

## E8 Qué fuente usa el motor de Windows, y dónde lo dice

```text
$ rg -n '"source": |if entries:|elif pm_intervals|elif dwm_samples' src/metal_gpu_trace/perf_record_windows.py
787:        if entries:
808:        elif pm_intervals:
819:        elif dwm_samples:
859:        if entries:
876:            "source": "drawstress-log" if entries else "presentmon" if pm_intervals else "dwm-composition",
… recortado (878: otro `if entries:`)
```

El `else` de cierre de la línea 830 es una palabra clave sola que este patrón no encuentra; `sed -n 830,844p` muestra los
dos errores `no frame data`. La cadena es el orden de la tabla de
[El motor de Windows](./motor-windows.md#las-tres-fuentes-de-fotogramas-y-cual-gana); la línea 859 anula los números de
ritmo por fotograma para el registro. Una grabación del motor **no se reprodujo** (no hay máquina Windows).

## E9 Las líneas del candado y la limpieza de Windows

```text
$ rg -n "lock_path|FileExistsError|is_process_alive" src/metal_gpu_trace/perf_record_windows.py
332:def is_process_alive(pid):
574:    lock_path = pathlib.Path(lock_path) if lock_path is not None else out_dir / ".recording"
579:            lock_path.mkdir(exist_ok=False)
583:        except FileExistsError:
587:                stale = not is_process_alive(int(owner.read_text(encoding="utf-8").strip()))
593:                    lock_path.rmdir()
597:            raise RuntimeError(f"another recording is running ({lock_path}); remove it if none is") from None
942:        if lock_acquired and lock_path.exists():
945:                lock_path.rmdir()
… recortado (394, 555, 575, 580, 584, 944)
```

Las líneas 590-596 son toda la toma del candado muerto: quitar el `pid`, `rmdir`, intentar otra vez, sin segundo candado: [límite 3](./limites.md).

## E10 PresentMon: dónde viven el pin y la búsqueda

```text
$ rg -n "find_presentmon|PRESENTMON_EXE|presentmon_dir|PRESENTMON\[" src/metal_gpu_trace/perf_record_windows.py src/metal_gpu_trace/workloads.py | cut -c1-140
src/metal_gpu_trace/workloads.py:196:    if target.is_file() and file_id(target)["sha256"] == PRESENTMON["sha256"]:
src/metal_gpu_trace/workloads.py:201:        download(PRESENTMON["url"], part, PRESENTMON["bytes"] * 2)
src/metal_gpu_trace/workloads.py:202:        if file_id(part)["sha256"] != PRESENTMON["sha256"]:
… recortado (workloads.py:194-195, 197, 205)
src/metal_gpu_trace/perf_record_windows.py:420:def find_presentmon():
src/metal_gpu_trace/perf_record_windows.py:424:    explicit = os.environ.get("PRESENTMON_EXE")
src/metal_gpu_trace/perf_record_windows.py:427:    cache = presentmon_dir()
src/metal_gpu_trace/perf_record_windows.py:649:        presentmon_exe = find_presentmon()
```

El hash se compara en `workloads.py:196` y `:202` (instalación) y en ningún sitio de `find_presentmon` (`:420-430`): [límite 4](./limites.md).

## Lo que no se reprodujo

- Cualquier grabación, de macOS o de Windows (hace falta Instruments, una máquina Windows y tiempo de GPU), y por tanto todo tiempo de la guía.
- `preflight.check` en sí, con una entrada que falla, y cada mensaje impreso en vivo (se leen del código, E1, y los fijan pruebas no ejecutadas).
- `perf_record.sh` o `perf_record_windows.py` con argumentos malos, incluidas sus líneas de uso.
- Una descarga: `workload_fetch`, `presentmon_install`, y un `shasum` de lo que las publicaciones del proyecto ofrecen hoy.
- Un `.trace` parcial de un Instruments interrumpido, y la cancelación de una grabación de Windows.
- Cuántos segundos dura el arranque de Wine.
