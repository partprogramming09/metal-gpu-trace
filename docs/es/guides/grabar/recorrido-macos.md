# El recorrido en macOS

**Lector:** personas que cambian `recording.py` o `perf_record.sh`. Revisado el 2026-11-16. Etiquetas: véase [Grabar](./index.md#como-leer-las-etiquetas).

English: [The macOS journey](../../../guides/recording/macos-journey.md)

**En corto:** una petición de grabación pasa por cinco etapas: se vuelve un comando, un envoltorio revisa y prepara el
Mac, se arranca un script con un entorno limpio, el servidor lo vigila cada segundo y, cuando el script vuelve, el
servidor completa el resumen. Cancelar o pasarse del plazo sigue una secuencia fija que borra todo lo que la corrida
creó. Cada corrida registra además sobre qué capa de traducción corrió y de dónde salió el código.

Todo lo que sigue es **confirmado** por las líneas nombradas. Los archivos que deja están en la
[guía de datos](../datos-y-su-ciclo-de-vida/archivos-en-disco.md#que-deja-una-grabacion-en-disco).

![Cajas de izquierda a derecha: petición, comprobaciones de la herramienta, envoltorio con preflight, script en su propio grupo de procesos, bucle de vigilancia cada segundo, terminar y responder. Bajo el bucle una flecha de cancelar o pasarse del plazo lleva a la secuencia de cierre forzado.](./img/recorrido-macos.png)
*Figura 1. Una grabación de macOS y la salida por cancelación o plazo vencido. Fuente HTML: `img/recorrido-macos.html`.*

## Paso 1: la petición se vuelve un comando

`tool_perf_record`, `recording.py:36-73`.

1. `resolve_tier` convierte `tier` en tres ajustes (`recording.py:23-33`):

   | Tier | Memoria Metal | Contadores de GPU | `.trace` conservado | Qué cuesta |
   |---|---|---|---|---|
   | `light` | no | no | no | segundos de lectura de vuelta: para iterar |
   | `standard` (por defecto) | sí | no | no | la tabla de memoria es la más lenta de leer |
   | `deep` | sí | sí | sí (salvo que el límite de disco lo borre) | los contadores suman unos 40 s de lectura por cada segundo grabado (`recording.py:44`) |

   Un `memory` o `counters` pasado aparte reemplaza esa parte del tier. `deep` se rechaza en Windows (`recording.py:49-50`).
2. `check_levers` rechaza un `memory_free_pct` fuera de 20 a 60 y cualquiera de las dos palancas en Windows (`recording.py:274-284`).
3. `check_env` solo acepta pares `NOMBRE=VALOR` separados por espacios (`recording.py:76-81`): el script parte el texto por espacios.
4. Con `workload`, `workloads.workload_command` aporta el programa, el modo de Wine, los argumentos y el entorno
   (`recording.py:53-56`; [Los programas de prueba](./programas-de-prueba.md)). `size` sin workload se rechaza (`:57-58`); sin `program` también (`:59-60`).
5. Sin `wine` se usa `METAL_TRACE_WINE`; en macOS sin ninguno, la llamada se rechaza (`:61-65`). El programa debe existir
   (`:66-68`); el error nombra el archivo, no la ruta.
6. `perf_attach` se salta casi todo eso: `record(label, seconds, "attach", "-", "-", [process])` (`recording.py:95`). No
   tiene tier, así que el resumen no trae la clave `tier` (`recording.py:344-345`), y el programa sigue corriendo después.

## Paso 2: el envoltorio

`record`, `recording.py:309-322`. En este orden:

| # | Qué | Línea |
|---|---|---|
| 1 | La etiqueta: letras, dígitos, `.`, `_`, `-`, hasta 100 | `:312` |
| 2 | Las palancas | `:314` |
| 3 | **Preflight** ([Preflight](./preflight.md)) | `:315` |
| 4 | `memory_pressure` si se dio `memory_free_pct`: espera hasta 90 s a «Stable at percent free» y rechaza si nunca llega (`hold_memory_pressure`) | `:316`, `:287-306` |
| 5 | `record_run`. Un `finally` detiene la presión pase lo que pase | `:319-322` |

Preflight va antes de la presión a propósito: una corrida rechazada no debe arrancar nada. `test_record_runs_preflight_before_memory_pressure`
y `test_preflight_failure_starts_no_process` (`tests/test_preflight.py:275`, `:296`) lo fijan (no ejecutadas para esta guía).

## Paso 3: el entorno que recibe el script

`record_run` lo arma en `recording.py:360-370` ([E6](./evidencia.md)).

| Variable | Se fija cuando | Qué significa para el script |
|---|---|---|
| `PERF_OUT` | siempre | la carpeta de corridas (`config.OUT`) |
| `PERF_LOCK` | siempre | la carpeta-candado (`config.LOCK`), compartida con el servidor |
| `PERF_PARENT_PID` | siempre | el pid del servidor: el script detiene su programa si el servidor muere (`perf_record.sh:82-92`) |
| `PERF_ENV` | siempre | las variables `NOMBRE=VALOR` del programa, del entorno más `env` y el workload |
| `PERF_MEMORY=0` | `memory` es false | saltarse la tabla de memoria Metal |
| `KEEP_TRACE=1` | tier `deep` | conservar el `.trace` |
| `PERF_PREFIX` | `background` | correr el programa bajo `taskpolicy -b` (`recording.py:271`) |
| `PERF_INSTRUMENTS` | contadores | añadir el instrumento `Metal GPU Counters` |

El script lee `KEEP_RUNS` y `PERF_MIN_FREE_GB` del entorno que el servidor le pasó (`dict(os.environ, ...)`, `recording.py:360`).
Luego corre `layer_of` (`recording.py:370`): le pregunta a Wine su versión (`wine --version`, plazo de 30 s, `:140-143`) y
calcula la huella de la capa ([Qué identifica una corrida](#que-identifica-una-corrida)).

## Paso 4: el bucle de vigilancia

`record_run`, `recording.py:386-421`.

- **Antes de arrancar**, el servidor recuerda qué archivos `<label>_*` e `instruments*.ktrace` ya existen (`:386-388`), así que nunca borra un archivo que no creó.
- **El arranque**: `start_new_session=True` (`:389-392`) hace que el script encabece su propio grupo de procesos, que es lo que mata `os.killpg`.
- **El bucle** (`:394-421`) da vueltas de un segundo como máximo. Si el tiempo se acabó o el cliente canceló, pasa a la
  secuencia de cierre forzado; si no, espera hasta un segundo al script y, cada `PROGRESS_TICKS` (5, `config.py:48`)
  vueltas, envía «recording and reading back: N s of up to M s».

## Paso 5: cuando el script vuelve

| El script termina con | El servidor hace | Línea |
|---|---|---|
| Una salida distinta de cero, o ningún `.json` nuevo | `recording failed (exit N): <última línea de stderr>` | `recording.py:422-425` |
| Un resumen sin intervalos de GPU | El programa no hizo trabajo de GPU: los archivos de la corrida se borran y el error dice cómo terminó ([Cuando falla](./fallos.md)) | `:427-436` |
| Si no | `finish` añade `layer`, `context`, `tier`, aplica el límite de disco y reescribe el resumen. Tablas de claves: [guía de datos](../datos-y-su-ciclo-de-vida/claves-del-resumen.md#el-resumen-clave-por-clave) | `recording.py:337-351`, `:437` |

## La secuencia de cierre forzado

Cancelar y pasarse del plazo terminan igual, en este orden (`recording.py:396-413`):

1. `os.killpg(proc.pid, SIGKILL)`: el script y todo lo que arrancó (`:397`). `SIGKILL` no se puede atrapar, así que la trampa del script no corre y el servidor limpia él mismo.
2. Detener el programa: `native`, todos los procesos de ese nombre (`kill_program`, `:255-263`: `SIGTERM`, hasta 3 s, luego `SIGKILL`); Wine, `wineserver -k` para el prefijo (`:402-403`); `attach`, nada: el programa no era nuestro (`:401`).
3. `free_lock(proc.pid)`: quitar el candado solo si todavía guarda el pid del script (`:326-335`).
4. Borrar los archivos que esta corrida creó: entradas `<label>_*` nuevas y `instruments*.ktrace` nuevos (`:406-407`).
5. Lanzar `the recording was cancelled; nothing was saved` o, si fue por plazo, el mensaje que nombra la causa probable (una ventana oculta) (`:408-413`).

`test_overrun`, `test_overrun_removes_lock_with_pid` y `test_free_lock_only_frees_its_own`
(`tests/test_recording.py:358`, `:387`, `:733`) lo fijan (no ejecutadas para esta guía).

## Qué identifica una corrida

Se calcula en el servidor, no en el script, porque necesita leer la máquina y el repositorio. Ejemplo: dos corridas del
mismo juego, una en CrossOver y otra en un Wine más nuevo, dan huellas distintas, así que `perf_compare` dice «capas
distintas» antes de decir que una es más rápida (`layer_change`, `:205-223`).

| Pieza | Qué registra | Línea |
|---|---|---|
| **`layer_of`** | Sobre qué capa de traducción corrió la grabación. `native` da `{"none": "native Metal, no translation layer"}` y `attach` da `{"unknown": ...}` | `recording.py:127-157`, `:134-137` |
| (con Wine) versión | `wine_version`, que une las líneas «Product Name» y «Public Version» de CrossOver | `:117-124` |
| (con Wine) reemplazos | El `WINEDLLOVERRIDES` que pasará el script, y los reemplazos de DLL del prefijo leídos de `user.reg` (`registry_overrides`) | `:102-114` |
| (con Wine) DLL | Tamaño y SHA-256 de cinco DLL (`d3d12`, `d3d12core`, `d3d11`, `d3d10core`, `dxgi`, `LAYER_DLLS`) en Wine y en el prefijo, más una huella de 12 caracteres de todo eso | `:99` |
| **`run_context`** | El commit corto y si hubo cambios en archivos rastreados, del repositorio que contiene el archivo de proyecto, y la versión de `xctrace`. Descarta toda variable `GIT_*` para que ninguna apunte a git a otro repositorio, y deja fuera la rama, la ruta y el nombre de usuario: los resúmenes se comparten | `recording.py:168-188` |

- Cuál de las dos copias de DLL carga Wine de verdad **no se sabe** (`:128-130`: Instruments no guarda el registro propio de Wine), así que la huella trata la copia del prefijo como la efectiva cuando existe (`effective_dlls`, `:160-162`).
- Un workload que pasa por MoltenVK o Rosetta aporta su propio `layer` (`workloads.workload_layer`, `workloads.py:39-49`), así que una comparación contra nativo dice «capas distintas».
