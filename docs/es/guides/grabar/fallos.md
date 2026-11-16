# Cuando falla, y tocarlo sin romperlo

**Lector:** personas que depuran una grabación rechazada, detenida o vacía, y personas que cambian el grabador. Revisado el 2026-11-16. Etiquetas: véase [Grabar](./index.md#como-leer-las-etiquetas).

English: [When it fails](../../../guides/recording/failures.md)

**En corto:** pase lo que pase, una grabación o entrega un resumen o no deja nada: ni archivos a medias ni un candado
atascado. Esta página lista, para cada fallo, el mensaje que se ve y qué queda en disco, y luego las reglas para cambiar
el grabador sin que la limpieza deje de funcionar. Ejemplo: si el cliente cancela, la respuesta es
`the recording was cancelled; nothing was saved` y la carpeta de corridas queda como estaba.

## macOS

| Qué sale mal | Qué reciben | Qué queda | Línea |
|---|---|---|---|
| Falla una comprobación de preflight | El mensaje de la [tabla](./preflight.md) | Nada: no se arrancó ningún proceso | `preflight.py:101-137` |
| Falta `memory_pressure`, o no llega al porcentaje en 90 s | `memory_pressure is not available`, o `memory_pressure did not reach that free percentage; the Mac may already be below it` | Nada; el ayudante se detiene | `recording.py:287-306` |
| El propio script rechaza (etiqueta, cabecera del programa, ningún proceso al que engancharse, disco, candado) | `recording failed (exit N): <la última línea del script>`; salida 2 para argumentos, 4 para disco, 3 para el candado | Nada: el script sale antes de tomar el candado o de escribir | `perf_record.sh:10-24`, `:37`, `:47-50`; `recording.py:422-425` |
| Instruments falla o muere de inmediato | `recording failed (exit 1): no recording at <ruta>` | Nada: la trampa borra los archivos de la corrida | `perf_record.sh:139-156`; `test_script_failure_cleanup` `:534` |
| Instruments muere **a mitad** | Véase [abajo](#que-pasa-si-instruments-muere-a-mitad) | | |
| El cliente cancela | `the recording was cancelled; nothing was saved` | Nada (la [secuencia de cierre forzado](./recorrido-macos.md#la-secuencia-de-cierre-forzado)) | `recording.py:396-409` |
| La grabación pasa su plazo | `the recording took over N s and was stopped; nothing was saved. The likely cause is a hidden window: ...` | Nada | `recording.py:410-413` |
| El programa no hace trabajo de GPU | `the program did no GPU work: it ended (<motivo>) after N s of recording, and its summary was not saved; check that it starts (under Wine: the Wine build, the prefix and the program's own log)` | El `.trace` solo si se pidió conservarlo; el mensaje lo dice | `recording.py:427-436` |
| El servidor muere a mitad de la grabación | Nada que ver | Un bucle vigilante del script detiene el programa e Instruments | `perf_record.sh:82-92` |
| `wine --version` se cuelga | La versión de la capa es `null`; la grabación sigue | | `recording.py:140-143` |
| Dos grabaciones compiten por un candado cuyo dueño está muerto | Una lo toma, la otra recibe `another recording is running` | | `perf_record.sh:44-61`, [guía de datos](../datos-y-su-ciclo-de-vida/cache-y-candado.md#el-candado) |

### Qué pasa si Instruments muere a mitad

`xcrun xctrace record ... || true` ignora el estado de salida a propósito (`perf_record.sh:140-151`), así que el script
siempre continúa hasta `kill $sampler` (`:155`) y luego:

- **No** hay carpeta `.trace`: sale con 1 y `no recording at <ruta>` (`:156`), y la trampa `EXIT` borra los archivos de la
  corrida (`:71`). Lo fija `test_script_failure_cleanup`, donde un `xcrun` de mentira sale de inmediato.
- **Existe** una carpeta `.trace` (parcial): el script corre el informe sobre ella (`:160`). **No reproducido**: no se mató
  ningún `xctrace` real. Por el código, o `perf_report.py` sale con código distinto de cero (`set -e`, `:5`), la trampa
  borra la corrida y el error es `recording failed (exit N): <última línea>`, o escribe un resumen de lo que pudo leer; sin
  intervalos de GPU, el servidor lo convierte en `the program did no GPU work` y borra la corrida (`recording.py:427-436`).
  Cuál pasa depende de `perf_report.py`, tema de una guía posterior.
- Muere **el servidor**, no Instruments: el bucle vigilante del script lo nota (`kill -0 $PERF_PARENT_PID`, `:84`),
  detiene el programa, mata `xctrace` y el informe, y termina el script, cuya trampa limpia (`:82-92`).

## El motor de Windows

| Qué sale mal | El mensaje | Línea |
|---|---|---|
| Etiqueta o segundos malos (lanzado a mano) | `label may hold only letters, digits, '.', '_' and '-'`, `seconds must be 1 to 3600` | `perf_record_windows.py:560-564` |
| Una grabación viva tiene el candado | `another recording is running (<candado>); remove it if none is` | `:597` |
| Ningún proceso coincide con el objetivo de enganche | `no running process matches <objetivo>` | `:475`, `:480` |
| No se puede arrancar el programa | `recording failed: <el mensaje del sistema>` (un `OSError`) | `recording.py:383-384` |
| Cancelar o pasarse del plazo | los dos mensajes del [paso 5](./motor-windows.md#paso-a-paso-figura-1) | `:744-746` |
| Sin fotogramas, PresentMon corrió | `no frame data: PresentMon saw no Present() calls from this process; it is idle, minimized, or a launcher whose game runs in another process (use perf_attach on the game)` más la última línea de stderr de PresentMon | `:833-839` |
| Sin fotogramas, sin PresentMon | `no frame data: the program wrote no DRAWSTRESS_LOG, PresentMon is not installed (call presentmon_install) and DWM gave no samples (DwmGetCompositionTimingInfo needs the interactive desktop session, not SSH or a service)` | `:840-844` |

Un `RuntimeError` o `ValueError` del motor se convierte en un `ToolError` con el mismo texto (`recording.py:381-382`).
Todo **no reproducido** (no hay máquina Windows); `test_no_frame_data_is_an_error`, `test_timeout_and_cleanup` y
`test_lock_handling` (`tests/test_perf_record_windows.py:623`, `:281`, `:87`) lo fijan (no ejecutadas para esta guía).

## Tocarlo sin romperlo

| Si añades | Haz esto |
|---|---|
| Un rechazo nuevo | Ponlo en `preflight.check` **antes** de cualquier cosa que arranque un proceso, haz que el mensaje diga qué hacer, mantén las rutas fuera, añade la prueba junto a sus hermanas en `tests/test_preflight.py` (cada una comprueba la redacción). Si el script también debe rechazar, repítelo allí con su código de salida y actualiza la [tabla](./preflight.md#que-repite-cada-capa) |
| Una variable nueva para el script | Fíjala en `record_run` (`recording.py:360-370`), léela en `perf_record.sh`, documéntala en la [tabla](./recorrido-macos.md#paso-3-el-entorno-que-recibe-el-script). Los pares de `PERF_ENV` se parten por espacios: ningún valor puede contener uno (`check_env`) |
| Algo que el servidor mata al cancelar | Lístalo **antes** de arrancar, como hace `record_run` con `before` y `ktraces` (`recording.py:386-388`): una limpieza que borra lo que no creó borra un archivo de una persona |
| Un campo nuevo en el resumen | Escríbelo en el código compartido de `metrics.py` para los dos motores (véase la [guía de datos](../datos-y-su-ciclo-de-vida/limites.md#tocarlo-sin-romperlo)) |
| Un programa de prueba nuevo | Véase [Para añadir un programa](./archivos-de-datos.md#el-archivo-de-programas-de-prueba). Nunca por etiqueta ni por nombre: el hash es la identidad |
| Código de Windows que pregunta si un proceso está vivo | No `os.kill` (allí lo termina): usa `is_process_alive` (`preflight.py:18-20`) |
| Un archivo nuevo de una corrida de Windows | El `finally` del motor borra todo archivo que empiece por el nombre de la corrida (`:937-941`): consérvalo como prefijo para que se limpie y se pode con ella |
