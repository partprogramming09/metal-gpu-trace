# Grabar

**Lector:** personas que cambian cómo se hace una grabación (`recording.py`, `preflight.py`, `workloads.py`, los dos scripts de grabación y los archivos de `data/`), o que necesitan saber por qué una grabación fue rechazada, detenida o volvió vacía. Revisado el 2026-11-16.

English: [Recording](../../guides/recording.md)

Esta página sigue una grabación desde la petición del agente hasta el momento en que se devuelve el resumen, y dice qué
hace cada pieza y qué pasa cuando falla. No repite [How it works](../../guides/how-it-works.md) (qué capa llama a cuál)
ni [Datos y su ciclo de vida](./datos-y-su-ciclo-de-vida.md) (qué archivos deja una grabación, la vida del candado, los
ajustes de retención); los enlaza donde la historia continúa. Es la versión en español de la guía en inglés: mismo
contenido, mismos diagramas y la misma evidencia (los comandos y sus salidas no se traducen, ni los mensajes de error
del programa).

Cómo leer las etiquetas: cada afirmación técnica es **confirmada** (con `archivo:línea`, comprobada con `rg` o `sed` el
2026-11-16 contra el árbol de trabajo, que es la 0.27.2 más las entradas `[Unreleased]` de `CHANGELOG.md`), **probable**
(leída en el código pero no ejecutada aquí) o **especulación** (una conjetura sobre el porqué). **No verificado** marca un
dato de fuera que no se comparó con su fuente. Las líneas se mueven cuando cambia el código: busca el nombre, no solo el
número. Cada cifra viene con el comando que la produjo, en [Evidencia](#evidencia-los-comandos-y-su-salida-real). **No
reproducido** significa que el comportamiento no se pudo ejecutar para esta página: no se hizo ninguna grabación (hace
falta Instruments, una máquina Windows y minutos de GPU) y la sesión que la escribió solo podía correr comandos de
lectura, así que tampoco se corrió ninguna comprobación en vivo; se nombran en su lugar las pruebas que fijan cada
comportamiento, y **no se ejecutaron** para esta página.

## Un ejemplo primero

Supón que un agente le pide al servidor que grabe un programa de Windows bajo Wine durante 30 segundos:

```text
perf_record label=mygame program=~/Games/mygame.exe wine=~/wine seconds=30
```

Qué pasa, en el orden en que pasa:

1. El servidor revisa la petición: el nivel (tier), las palancas, los pares de entorno, que el programa exista, y luego
   la etiqueta (`recording.py:48-70`, `:312`). Todavía no ha empezado nada.
2. **Preflight** mira el Mac: ¿hay Wine?, ¿está instalado `xcrun`?, ¿hay sitio en el disco?, ¿está desbloqueada la
   pantalla?, ¿hay otra grabación en marcha? Para 30 segundos pide `2 + (30 × 8 + 9) / 10 = 26` GB libres (E3). Si algo
   falla la llamada termina aquí con una frase que dice qué hacer, y no se arrancó ningún proceso.
3. El servidor arranca `perf_record.sh` en su propio grupo de procesos y le dice al cliente el peor caso: «recording: up
   to 630 s including read-back» (`recording.py:371-372`; 15 s por cada segundo grabado más 180). Después mira cada
   segundo el reloj y la señal de cancelar del cliente (`recording.py:394-421`).
4. El script toma el candado, arranca Instruments sobre el programa y dos muestreadores pequeños, espera 30 s, corre el
   informe y borra el `.trace` crudo (esta parte es la
   [Figura 2 de la guía de datos](./datos-y-su-ciclo-de-vida.md#de-una-grabacion-a-disco)).
5. El servidor lee el resumen que escribió el informe, añade lo que solo él sabe (la capa de traducción, de dónde
   salió el código, el tier) y responde con él (`recording.py:437`).

La respuesta es el mismo resumen que leen todas las demás herramientas. Cancelar en cualquier momento, o pasar de 630 s,
mata todo y no deja ningún archivo.

## Por qué la grabación tiene esta forma

| Decisión | Por qué | Alternativas descartadas |
|---|---|---|
| Revisar todo primero en el servidor (`preflight`), en milisegundos | Una grabación de Wine D3D12 que falla tarde ya gastó hasta 630 s y gigabytes de disco temporal. Cada rechazo dice cómo arreglarlo (`preflight.py:1-3`, el docstring del propio módulo). El script repite las comprobaciones de programa, disco y candado como «defensa en profundidad» (`preflight.py:1-3`) | Solo las comprobaciones del script: sus fallos llegan al cliente como `recording failed (exit N): <última línea de stderr>` (`recording.py:425`) y algunos llevan una ruta local (límite 1) |
| Un script de zsh maneja Instruments; Python maneja el script | El script es lo que puede morir: su trampa `EXIT` quita el candado, los muestreadores y los archivos a medias se acabe como se acabe (`perf_record.sh:65-73`). El servidor sigue vivo, mata el grupo de procesos del script al cancelar y limpia lo que dejó (`recording.py:396-413`) | Python llamando a `xctrace` directamente: **especulación** de que se dejó fuera porque la limpieza tiene forma de shell (bucles en segundo plano, trampas); ningún ADR registra la elección |
| Una grabación a la vez, con una carpeta-candado | Dos programas que comparten la GPU estropean las dos mediciones (`perf_record.sh:40`). Véase [Una grabación a la vez](#una-grabacion-a-la-vez) | Fiarse solo del hilo trabajador: serializa las llamadas de un solo servidor (`worker.py:1`), no dos servidores ni un script lanzado a mano |
| Un plazo de 15 s por segundo grabado más 180 s | Cerrar y leer de vuelta un trace de Wine D3D12 es lento: una grabación de 30 s produjo un trace de 614 MB que tardó minutos en cerrarse y 93 s en leerse, y pasó el límite anterior (`CHANGELOG.md`, 0.8.1). Los contadores lo suben a 55 s por segundo (`recording.py:266-269`) | Un límite fijo: el primero (420 s) perdió una grabación real |
| Cancelar y pasarse del plazo matan el grupo de procesos, luego el programa, y borran los archivos nuevos | Una grabación a medias es peor que ninguna: aparecería listada como una corrida. El programa se detiene por nombre porque un juego que atrapa `SIGTERM` siguió corriendo 40 minutos (`recording.py:255-258`) | Dejar los archivos parciales a las reglas de retención: saldrían en `perf_runs` |
| Un motor aparte para Windows | Windows no tiene Instruments ni `xctrace`. El motor mide con PresentMon, o con el compositor del escritorio cuando falta PresentMon, y escribe la misma forma de resumen con código compartido en `metrics.py` (`perf_record_windows.py:24-28`) | Un solo motor con `if`: el camino de macOS es un script de shell, así que no hay nada que compartir salvo el resumen |
| Programas de prueba fijados por SHA-256 y construidos por el workflow de este proyecto | Un programa descargado se ejecuta, así que importan los bytes exactos; la construcción se reproduce desde el código fuente (`data/workloads.json`: «built from source by .github/workflows/workloads.yml») | Descargar binarios de los autores directamente: los editores de Godot son la excepción, y están fijados por SHA-512 (`workloads.py:166-171`) |
| Las familias de GPU y los programas de prueba viven en archivos JSON de `data/` | Los hechos cambian más rápido que el código: un chip nuevo o un programa nuevo es una edición de datos con su prueba, no un cambio de lógica. Ambos se leen una vez al importar (`config.py:35-36`) | Constantes en Python: **especulación**; ningún ADR registra la elección |

## Las piezas y dónde viven

| Pieza | Archivo | Qué hace |
|---|---|---|
| Las herramientas | `recording.py` (`tool_perf_record` `:36`, `tool_perf_attach` `:91`) | Revisan la petición, arman el comando, llaman a `record` |
| El envoltorio del servidor | `recording.py` (`record` `:309`, `record_run` `:354`, `finish` `:337`) | Preflight, presión de memoria, arrancar el script, vigilarlo, limpiar, terminar el resumen |
| Lo que identifica una corrida | `recording.py` (`layer_of` `:127`, `run_context` `:168`) | La huella de la capa de traducción y de dónde salió el código |
| Las comprobaciones | `preflight.py` | Lo que necesita una grabación, rechazado en milisegundos |
| El grabador de macOS | `perf_record.sh` | Candado, muestreadores, `xctrace`, informe, limpieza |
| El grabador de Windows | `perf_record_windows.py` | Toda la grabación de Windows; también se puede lanzar a mano |
| Los programas de prueba | `workloads.py`, `data/workloads.json` | La lista, la descarga, los hashes fijados, PresentMon |
| Los datos de GPU | `data/apple-gpu-families.json` | La grabación no lo usa; lo lee `gpu_family` (véase [Los archivos de datos](#los-archivos-de-datos)) |

## El recorrido de una grabación, paso a paso (macOS)

Todo lo que sigue es **confirmado** por las líneas nombradas. Los archivos que deja están en la
[guía de datos](./datos-y-su-ciclo-de-vida.md#que-deja-una-grabacion-en-disco).

### Paso 1: la petición se vuelve un comando

`tool_perf_record`, `recording.py:36-73`.

1. `resolve_tier` convierte `tier` en tres ajustes (`recording.py:23-33`):

   | Tier | Memoria Metal | Contadores de GPU | `.trace` conservado | Qué cuesta |
   |---|---|---|---|---|
   | `light` | no | no | no | segundos de lectura de vuelta: para iterar |
   | `standard` (por defecto) | sí | no | no | la tabla de memoria es la más lenta de leer |
   | `deep` | sí | sí | sí (salvo que el límite de disco lo borre) | los contadores suman unos 40 s de lectura por cada segundo grabado (`recording.py:44`) |

   Un `memory` o `counters` pasado aparte reemplaza esa parte del tier. `deep` se rechaza en Windows
   (`recording.py:49-50`).
2. `check_levers` rechaza un `memory_free_pct` fuera de 20 a 60 y cualquiera de las dos palancas en Windows
   (`recording.py:274-284`).
3. `check_env` solo acepta pares `NOMBRE=VALOR` separados por espacios (`recording.py:76-81`): el script parte luego el
   texto por espacios, así que un espacio dentro de un valor lo rompería.
4. Con `workload`, `workloads.workload_command` aporta el programa, el modo de Wine, los argumentos y el entorno
   (`recording.py:53-56`; [Los programas de prueba](#los-programas-de-prueba)). `size` sin workload se rechaza
   (`:57-58`); sin `program` también (`:59-60`).
5. Sin `wine` se usa `METAL_TRACE_WINE`; en macOS sin ninguno, la llamada se rechaza (`:61-65`). El programa debe existir
   (`:66-68`); el error nombra el archivo, no la ruta.
6. `perf_attach` se salta casi todo eso: `record(label, seconds, "attach", "-", "-", [process])` (`recording.py:95`). No
   tiene tier, así que el resumen no trae la clave `tier` (`recording.py:344-345`), y el programa sigue corriendo después.

### Paso 2: el envoltorio

`record`, `recording.py:309-322`. En este orden: la etiqueta (letras, dígitos, `.`, `_`, `-`, hasta 100, `:312`), las
palancas (`:314`), **preflight** (`:315`), después `memory_pressure` si se dio `memory_free_pct` (`:316`,
`hold_memory_pressure` `:287-306`: espera hasta 90 s a «Stable at percent free» y rechaza si nunca llega), y luego
`record_run`. Un `finally` detiene la presión pase lo que pase (`:319-322`).

Preflight va antes de la presión a propósito: una corrida rechazada no debe arrancar nada.
`test_record_runs_preflight_before_memory_pressure` y `test_preflight_failure_starts_no_process`
(`tests/test_preflight.py:275`, `:296`) lo fijan (no ejecutadas para esta página).

### Paso 3: el entorno que recibe el script

`record_run` lo arma en `recording.py:360-370`.

| Variable | Se fija cuando | Qué significa para el script |
|---|---|---|
| `PERF_OUT` | siempre | la carpeta de corridas (`config.OUT`) |
| `PERF_LOCK` | siempre | la carpeta-candado (`config.LOCK`), para que servidor y script compartan una |
| `PERF_PARENT_PID` | siempre | el pid del servidor: el script detiene su programa si el servidor muere (`perf_record.sh:82-92`) |
| `PERF_ENV` | siempre | las variables `NOMBRE=VALOR` del programa, del entorno más `env` y el workload |
| `PERF_MEMORY=0` | `memory` es false | saltarse la tabla de memoria Metal |
| `KEEP_TRACE=1` | tier `deep` | conservar el `.trace` |
| `PERF_PREFIX` | `background` | correr el programa bajo `taskpolicy -b` (`recording.py:271`) |
| `PERF_INSTRUMENTS` | contadores | añadir el instrumento `Metal GPU Counters` |

`KEEP_RUNS` y `PERF_MIN_FREE_GB` no se fijan aquí: el script las lee del entorno que el servidor le pasó
(`dict(os.environ, ...)`, `recording.py:360`).

Luego corre `layer_of` (`recording.py:370`): le pregunta a Wine su versión (`wine --version`, plazo de 30 s,
`:140-143`) y calcula la huella de la capa (véase [Qué identifica una corrida](#que-identifica-una-corrida)).

### Paso 4: el bucle de vigilancia

`record_run`, `recording.py:386-421`. Antes de arrancar el script el servidor recuerda qué archivos `<label>_*` y qué
`instruments*.ktrace` ya existen (`:386-388`); esa lista es lo único que puede borrar después, así que nunca borra un
archivo que no creó. El script arranca con `start_new_session=True` (`:389-392`): encabeza su propio grupo de procesos,
que es lo que mata `os.killpg`.

Luego un bucle de vueltas de un segundo como máximo (`:394-421`): si el tiempo se acabó o el cliente canceló, pasa a la
secuencia de cierre forzado de abajo; si no, espera hasta un segundo al script y, cada `PROGRESS_TICKS` (5,
`config.py:48`) vueltas, envía una línea de progreso «recording and reading back: N s of up to M s».

### Paso 5: cuando el script vuelve

- Una salida distinta de cero, o ningún `.json` nuevo: `recording failed (exit N): <última línea de stderr>`
  (`recording.py:422-425`).
- Un resumen sin intervalos de GPU: el programa no hizo trabajo de GPU; los archivos de la corrida se borran y el error
  dice cómo terminó (`:427-436`; véase [Cuando falla](#cuando-falla)).
- Si no, `finish` añade `layer`, `context`, `tier`, aplica el límite de disco y reescribe el resumen
  (`recording.py:337-351`, `:437`). Las tablas de claves del resumen están en la
  [guía de datos](./datos-y-su-ciclo-de-vida.md#el-resumen-clave-por-clave).

### La secuencia de cierre forzado

Cancelar y pasarse del plazo terminan igual, en este orden (`recording.py:396-413`):

1. `os.killpg(proc.pid, SIGKILL)`: el script y todo lo que arrancó (`:397`). `SIGKILL` no se puede atrapar, así que la
   trampa del propio script no corre: el servidor tiene que limpiar él mismo.
2. Detener el programa: con `native`, todos los procesos de ese nombre (`kill_program`, `:255-263`: `SIGTERM`, hasta 3 s
   de espera, luego `SIGKILL`); con Wine, `wineserver -k` para el prefijo (`:402-403`); con `attach`, nada: el programa
   no era nuestro (`:401`).
3. `free_lock(proc.pid)`: quitar el candado solo si todavía guarda el pid del script (`:326-335`).
4. Borrar los archivos que esta corrida creó: entradas `<label>_*` nuevas y `instruments*.ktrace` nuevos (`:406-407`).
5. Lanzar `the recording was cancelled; nothing was saved` o, si fue por plazo, el mensaje que nombra la causa probable
   (una ventana oculta) (`:408-413`).

`test_overrun`, `test_overrun_removes_lock_with_pid` y `test_free_lock_only_frees_its_own`
(`tests/test_recording.py:358`, `:387`, `:733`) lo fijan (no ejecutadas para esta página).

## Una grabación a la vez

La regla está en las instrucciones del servidor («One recording runs at a time», `metal_trace_mcp.py:25`), y se hace
cumplir en tres niveles que protegen de cosas distintas:

| Nivel | Qué impide | Dónde |
|---|---|---|
| El hilo trabajador | Dos llamadas de herramienta de un mismo servidor corriendo a la vez | `worker.py:1` |
| La carpeta-candado, leída por preflight | Que empiece una grabación mientras otra, de cualquier servidor o a mano, tiene el candado | `preflight.py:74-98`, `:135-137` |
| La carpeta-candado, tomada por el script (o el motor de Windows) | Lo mismo, en el momento que importa: `mkdir` es atómico, así que solo un proceso puede crearla | `perf_record.sh:52-62`, `perf_record_windows.py:577-598` |

**Por qué.** El comentario de `perf_record.sh:40` lo dice: «two programs sharing the GPU spoil both measurements» (dos
programas que comparten la GPU estropean las dos mediciones; confirmado). El resumen incluso tiene una forma de notarlo
a posteriori: `noisy_environment` compara el uso total de la GPU con la parte ocupada del propio programa y marca una
diferencia de 20 puntos o más, un umbral provisional (`how-it-works.md`, «What to do next»; la clave se describe en la
[guía de datos](./datos-y-su-ciclo-de-vida.md#claves-de-un-resumen-de-macos-presentes-solo-bajo-una-condicion)).

**Por qué un solo candado para todas las carpetas.** Cada proyecto tiene su propia carpeta de corridas, pero hay una
sola GPU: el candado vive en la carpeta de caché, no en la de corridas (`config.py:41-42`;
`test_recordings_into_two_folders_run_one_at_a_time`, `tests/test_recording.py:854`).

La vida del candado (tomar uno de un dueño muerto, soltarlo, quién lo quita) está en la
[guía de datos](./datos-y-su-ciclo-de-vida.md#el-candado). Lo nuevo aquí: un candado tomado hace que la segunda grabación
se rechace **antes** de arrancar nada (`preflight.py:135-137`), con el mensaje `another recording is running; one runs at
a time. If none is, remove the lock folder (METAL_TRACE_LOCK names it)`.

## Por qué 30 segundos o más bajo Wine

La instrucción dice: «Under Wine record 30 s or more: Wine's start-up takes part of the recording» (bajo Wine graba 30 s
o más: el arranque de Wine ocupa parte de la grabación; `metal_trace_mcp.py:27`; la misma frase está en la descripción de
`seconds`, `registry.py:39`, y en `README.md:138`). Eso es **confirmado como la razón que da el proyecto**. Qué hay detrás,
en dos partes:

- **Los primeros segundos no son el régimen estable del programa.** Wine arranca, el programa abre su ventana y compila
  sus shaders mientras Instruments ya graba. `skip_s` existe para recortar ese arranque de una comparación
  (`metal_trace_mcp.py:31`), y `analysis._startup_skip_s` busca hitches de compilación de shaders que terminen dentro del
  primer cuarto de la corrida (`analysis.py:670-690`). Una corrida de 30 s conserva la mayor parte de su duración tras el
  arranque. **Cuántos segundos dura el arranque no se midió para esta página**; el 30 es la regla práctica del proyecto
  (**probable**).
- **No es la regla de 100 fotogramas.** Una corrida de menos de 100 fotogramas se marca aparte (`analysis.py:378`, `:499`,
  `:655`: «under 100 frames: too short to judge; record 30 s or more»), y a 60 FPS 100 fotogramas son menos de 2 segundos.
  Así que 100 fotogramas es un suelo para comparar siquiera, y los 30 s son por el arranque (**especulación**: se deduce
  por aritmética de dos reglas que el código enuncia, no de una medición).

El lado del coste es real y es la razón del plazo: una grabación de Wine D3D12 de 30 s produjo un trace de 614 MB y unos
93 s solo para leerse (`CHANGELOG.md`, 0.8.1), y cada segundo grabado necesita unos 0,8 GB de disco temporal
(`perf_record.sh:33`, un comentario del código: **probable**). Las corridas nativas de Metal son más cortas: una entrada
del changelog menciona corridas nativas de 10 s junto a corridas de 30 s bajo Wine (`CHANGELOG.md:309`).

## Qué comprueba preflight y qué dice

`preflight.check` (`preflight.py:101-137`) corre seis comprobaciones en orden fijo y lanza un `ToolError` en la primera
que falla. Todas son de milisegundos y ninguna arranca un proceso, salvo leer el estado de la pantalla (`ioreg`, plazo de
10 s, `perf_report.py:593-604`).

![Siete cajas en fila, de izquierda a derecha: argumentos, programa, xcrun, disco, pantalla, candado e inicio. Bajo cada una de las seis primeras está escrito el mensaje exacto con que rechaza. Si todas pasan, la grabación arranca.](/diagrams/recording-preflight.png)
*Figura 1. Las comprobaciones de `preflight.check` y el mensaje de cada una. Fuente HTML: `docs/diagrams/recording-preflight.html`.*

| # | Qué comprueba | Mensaje cuando falla | Línea | Prueba (no ejecutada aquí) |
|---|---|---|---|---|
| 1 | `seconds` es un entero de 1 a 3600 (`whole_seconds` rechaza `10.5`, `True` y `"1_0"`, formas que Python acepta y el shell no) | `seconds is a whole number from 1 to 3600` | `preflight.py:107-108`, `:30-41` | `test_seconds_are_checked_before_anything_else` `:357` |
| 1 | `environ` es un mapa de texto; `wine` es una ruta o `native` o `attach`; `command` es una lista de textos | `environ is a mapping of text`, `wine is a path or native or attach, and the command a list of strings` | `:109-114` | |
| 2 | Un directorio de Wine tiene un `bin/wine` ejecutable | `no Wine at bin/wine inside that Wine directory (pass native for a macOS program)` | `:115-116` | `test_missing_wine_binary` `:65` |
| 2 | Con `native`: el programa es un archivo con el bit de ejecución | `<nombre> is not an executable file` (solo el nombre del archivo) | `:117-119` | `test_native_program_not_executable` `:72` |
| 3 | `xcrun` está en el `PATH` del entorno de la petición (no en Windows) | `xcrun is not on PATH: install Xcode or the command line tools (xcode-select --install)` | `:120-121` | `test_no_xcrun` `:81` |
| 4 | GB libres en la carpeta temporal y en la de corridas, cada una al menos lo necesario | `not enough free disk on the temporary folder (TMPDIR): N GB free, M GB needed (PERF_MIN_FREE_GB overrides)` (o `the runs folder`) | `:122-131` | `test_not_enough_disk_names_the_override` `:89` |
| 4 | Se puede leer el espacio libre (una ruta con byte nulo, un `disk_usage` que falla) | `the free disk space cannot be read for the runs or the temporary folder` | `:61-71` | |
| 5 | La pantalla de la sesión no está bloqueada (`ioreg`); no en Windows; `METAL_TRACE_ALLOW_LOCKED=1` la salta; un estado ilegible pasa | `the screen is locked: a locked session leaves the program's frames unpaced by the display, so the numbers do not compare; unlock the Mac, or set METAL_TRACE_ALLOW_LOCKED=1 to record anyway` | `:132-134` | `test_locked_screen_refuses_and_names_the_override` `:118` |
| 6 | La carpeta-candado no nombra un proceso vivo | `another recording is running; one runs at a time. If none is, remove the lock folder (METAL_TRACE_LOCK names it)` | `:135-137` | `test_live_lock_refuses` `:152` |

Cómo salen los números de la comprobación 4:

- Lo necesario es `PERF_MIN_FREE_GB` cuando es un número simple, y si no `2 + (seconds × 8 + 9) / 10` en división
  entera (`preflight.py:44-50`), que da 18 GB para 20 s, 26 para 30 s y 50 para 60 s (E3). En Windows es 1 GB, porque no
  hay Instruments (`:50`). El script de shell calcula la misma fórmula (`perf_record.sh:34`);
  `test_disk_formula_matches_the_shell` (`tests/test_preflight.py:101`) fija que las dos coinciden.
- La carpeta temporal es `TMPDIR` del entorno de la petición, o `/tmp` (`:126`): ahí escribe `xctrace` sus archivos
  `.ktrace` mientras graba.
- Una carpeta de corridas que aún no existe se mide en su padre existente más cercano (`free_gb`, `:61-71`).

La comprobación del candado (`lock_owner_alive`, `:74-93`) está hecha para una carpeta en la que cualquiera puede
escribir. Se niega a seguir un enlace, lee como mucho 32 bytes del archivo `pid` con una apertura que no bloquea, acepta
solo dígitos ASCII de hasta 10 caracteres y un pid de 1 a 2³¹−1, y trata cualquier cosa rara como «no hay dueño vivo». La
razón es dónde está el candado: un archivo `pid` hostil o roto no debe colgar una grabación (una tubería), señalar un
grupo entero de procesos (pid 0 o −1, `:16`) ni romper la comprobación. En Windows nunca se usa `os.kill`, porque allí
termina el proceso; `perf_record_windows.is_process_alive` pregunta con `OpenProcess` (`:18-20`).
`test_hostile_pid_files_are_not_a_live_owner` (`tests/test_preflight.py:336`) fija los casos raros.

### Qué no comprueba preflight

- **Que exista un proceso al que engancharse.** `perf_attach` pasa preflight con cualquier texto; el script dice
  `no running process matches <nombre>` (salida 2, `perf_record.sh:24`) y el motor de Windows dice lo mismo como
  `RuntimeError` (`perf_record_windows.py:475`, `:480`). En los dos casos llega como `recording failed ...` o como un
  `ToolError` simple.
- **El prefijo de Wine, el directorio de trabajo, el `api` frente a la plataforma.** Se usan después, por el script o
  por `Popen`.
- **Que el programa sea un Mach-O.** El script compara los cuatro primeros bytes con una lista de números mágicos de
  Mach-O (y ELF y `#!`, «para el CI de Linux») y rechaza con `<nombre> is not a program the system can run (no Mach-O or
  #! header)` (`perf_record.sh:14-19`).
- **La etiqueta.** `record` la comprueba antes de preflight (`recording.py:312`), y el script la vuelve a comprobar
  (`perf_record.sh:10`).

### Qué repite cada capa

| Comprobación | `recording.py` / `preflight.py` | `perf_record.sh` |
|---|---|---|
| Etiqueta | `recording.py:312` | `:10` (salida 2) |
| Segundos de 1 a 3600 | `preflight.py:107` | `:11` (salida 2) |
| Directorio de Wine | `preflight.py:115` | `:12` (salida 2) |
| Programa nativo | `preflight.py:117` | `:13`, `:14-19` (salida 2) |
| `xcrun` | `preflight.py:120` | ninguna: simplemente se llama a `xcrun` |
| Disco | `preflight.py:122-131` | `:34-38` (salida 4, el mensaje lleva la carpeta) |
| Pantalla bloqueada | `preflight.py:132` | ninguna |
| Candado | `preflight.py:135` | `:47-61` (salida 3) |
| Proceso al que engancharse | ninguna | `:20-25` (salida 2) |

## Qué identifica una corrida

Dos cosas se calculan en el servidor, no en el script, porque necesitan leer la máquina y el repositorio:

- **`layer_of`** (`recording.py:127-157`) dice sobre qué capa de traducción corrió la grabación. `native` da
  `{"none": "native Metal, no translation layer"}` y `attach` da `{"unknown": ...}` (`:134-137`). Con Wine registra la
  versión de Wine (`wine_version`, `:117-124`, que une las líneas «Product Name» y «Public Version» de CrossOver), el
  `WINEDLLOVERRIDES` que pasará el script, los reemplazos de DLL del prefijo leídos de `user.reg`
  (`registry_overrides`, `:102-114`), y el tamaño y SHA-256 de cinco DLL (`d3d12`, `d3d12core`, `d3d11`, `d3d10core`,
  `dxgi`, `LAYER_DLLS` `:99`) tanto en Wine como en el prefijo, más una huella de 12 caracteres de todo eso. Cuál de las
  dos copias carga Wine de verdad **no se sabe** (`:128-130`: Instruments no guarda el registro propio de Wine), así que
  la huella trata la copia del prefijo como la efectiva cuando existe (`effective_dlls`, `:160-162`). Para qué:
  `perf_compare` debe decir si dos corridas comparten capa antes de decir que una es más rápida (`layer_change`,
  `:205-223`).
- **`run_context`** (`recording.py:168-188`) dice de dónde salió el código: el commit corto y si hubo cambios en
  archivos rastreados, del repositorio que contiene el archivo de proyecto, y la versión de `xctrace`. Descarta toda
  variable `GIT_*` para que ninguna haga apuntar a git a otro repositorio, y deja fuera la rama, la ruta y el nombre de
  usuario: los resúmenes se comparten.

Un workload que pasa por MoltenVK o Rosetta aporta su propio `layer` (`workloads.workload_layer`, `workloads.py:39-49`),
así que una comparación contra nativo dice «capas distintas».

## Los programas de prueba

`workload_list` los muestra, `workload_fetch` descarga uno, y `perf_record` con `workload`, `api` (y `dim`, `example`,
`size`) lo corre. Existen para que dos personas en dos Mac graben la misma carga y comparen números.

### Qué hay en la lista (E4)

| Nombre | Qué dibuja | Valores de `api` | Descarga | Licencia |
|---|---|---|---|---|
| `drawstress` | 17-drawstress de bgfx: una cuadrícula de cubos, `dim`³ llamadas de dibujo por fotograma (64 000 con `dim` 40): el coste de un dibujo, nativo y a través de una capa | `mtl`, `mtl-x64` (Metal compilado para x86_64, corrido bajo Rosetta como un programa de Wine), `vk` (Vulkan por MoltenVK), `d3d11`, `d3d12` | 9 291 979 bytes | BSD-2-Clause (bgfx) |
| `bgfx-examples` | 30 ejemplos de bgfx, cada uno una carga distinta, elegidos con `example` | `mtl`, `d3d11`, `d3d12` | 57 350 072 bytes | BSD-2-Clause (bgfx) |
| `godot` | Una escena de Godot 4.7.2 construida desde código (400 formas, 8 luces, sombras, una cámara que orbita), sin recursos importados | `mtl`, `d3d12` | 1 525 bytes, más dos compilaciones del editor de Godot de 170 622 178 y 86 013 866 bytes | MIT (Godot); la escena es de este repositorio |

`example_traits` lista, para cada uno de los 30 ejemplos, una clase (`cpu_submit`, `compute`, `postprocess`, ...) y
cuántos encoders por fotograma esperar nativo y bajo D3D12 (E4: 30 ejemplos, 30 rasgos), de modo que una grabación se
pueda contrastar con lo que el programa debería hacer (`tool_workload_list`, `workloads.py:101-112`).

### Cómo una petición se vuelve un comando (`workload_command`, `workloads.py:65-91`)

1. El `api` debe estar en la entrada (`:69-70`): `api is one of mtl, mtl-x64, vk, d3d11, d3d12 for drawstress`.
2. Un workload con `examples` necesita que `example` sea uno de ellos; uno sin ellos lo rechaza (`:71-75`).
3. `dim` necesita que la entrada tenga `dim_variable` (`DRAWSTRESS_DIM`) (`:76-77`); `size` necesita `size_variables`
   (`DRAWSTRESS_WIDTH`, `DRAWSTRESS_HEIGHT`) y es `ANCHOxALTO` de 320x240 a 7680x4320 (`:52-57`, `:82-85`).
4. La carpeta debe estar descargada: `<nombre> is not downloaded yet; call workload_fetch first` (`:78-79`).
5. `vk` necesita además `METAL_TRACE_MOLTENVK`, una carpeta con `libMoltenVK.dylib` y sin espacios (`:25-36`), que va a
   `DYLD_LIBRARY_PATH` (`:86-87`).
6. El resultado es el programa (`<caché>/<nombre>-<12 hex>/<dir>/<programa>`), `wine` cuando el api lo necesita y la
   plataforma no es Windows, y si no `native` (`:88-89`), los argumentos con cada `{dir}` reemplazado por la carpeta
   entrecomillada (`dir_in_args`, `:94-98`) y el entorno del programa (`:81-87`).

`workload_layer` (`:39-49`) nombra la capa para el resumen: Rosetta para un api marcado `rosetta`, MoltenVK (con el
tamaño y el SHA-256 del dylib) para uno marcado `moltenvk`, y `None` en los demás: las capas normales de Wine y nativa
salen de `layer_of`.

### Cómo se verifica una descarga (`tool_workload_fetch`, `workloads.py:147-176`)

Esta sección no tiene figura propia: los pasos son una línea recta con un rechazo en el 4 y en el 6.

1. Si ya existe `<caché>/<nombre>-<12 primeros hex del sha256>`, se devuelve de inmediato (`:154-155`).
2. Si no, se crea una carpeta temporal **dentro de la caché** (para que el renombrado final quede en un solo disco)
   (`:157`).
3. `download` corre `curl -fsSL --proto =https --max-filesize <bytes> --max-time 600` (`:115-120`): solo https, nunca
   más que el tamaño que dice el archivo de datos, como mucho 10 minutos. Usa `curl` porque curl usa los certificados del
   sistema.
4. El SHA-256 del archivo debe ser igual al fijado, si no `<nombre>'s download does not match the SHA-256 this package
   pins; nothing was saved` (`:160-161`).
5. `unpack` rechaza todo miembro que no sea un archivo o carpeta normal, que empiece por `/` o contenga `..`
   (`:123-129`).
6. Para cada entrada de `downloads` (los dos editores de Godot), lo mismo, con un **SHA-512** fijado en el archivo de
   datos y `unzip` rechazando enlaces y rutas malas y restaurando los modos de Unix (`:163-173`, `:132-144`).
7. Se renombra la carpeta temporal `out` al nombre final (`:174`): la carpeta aparece entera o no aparece.

Si algo falla, la carpeta temporal se va con su bloque `with` (`:157`) y nada llega a la caché. Eso es **confirmado por
el código**; una descarga fallida o un hash equivocado **no se reprodujo** (hace falta red y un archivo erróneo;
`test_workload_downloads`, `tests/test_recording.py:286`, arma uno falso y fija los rechazos; no ejecutada para esta
página).

### Las versiones fijadas (E4, E5)

El archivo de datos fija cada archivo comprimido por su SHA-256, y la carpeta de la caché se nombra con los 12 primeros
caracteres (`workloads.py:22`), así que una versión nueva de un archivo es una carpeta nueva, nunca una sobrescritura:

| Workload | Etiqueta de la publicación | SHA-256 (completo) |
|---|---|---|
| `drawstress` | `workloads-3` | `2b3b01fa2dd0a7d5a1629046305319130d58ce4d843bd22c3f736071c0bfde2e` |
| `bgfx-examples` | `workloads-8` | `1d120363981ced4ae01dad57085258206fbc84f35bd9bcdcfe656b1af355d091` |
| `godot` | `workloads-9` | `a85320f08e1ac2721288441a5317796de4673a6df6fc727b71c135503adc09c5` |

Los archivos los construye desde el código fuente `.github/workflows/workloads.yml` y los sube a las publicaciones de
GitHub del proyecto con un archivo `.sha256` (`workloads.yml:35`, `:43`, `:102`, `:111`). Cada archivo trae un
`BUILD.txt` con los commits de que se construyó (E5), y la licencia de lo que contiene. Que el hash del archivo
publicado hoy sea igual al fijado **no se verificó** (no se hizo ninguna llamada de red para esta página), y una descarga
**no se reprodujo**.

Las dos compilaciones del editor de Godot vienen directo de las publicaciones del proyecto Godot y están fijadas por
SHA-512 en el mismo archivo (los 16 primeros caracteres en E4: `38aa16e5bba20839` para macOS, `83decd58fdf67b9d` para
Windows).

Como un pin nuevo crea una carpeta nueva y nada borra la vieja, la caché crece: 8 carpetas para 3 pins en la máquina
donde se comprobó esta página (E5). Las cifras y la pregunta abierta están en la
[guía de datos](./datos-y-su-ciclo-de-vida.md#la-cache-no-son-las-grabaciones).

### PresentMon (`tool_presentmon_install`, `workloads.py:179-205`)

PresentMon es el programa de consola de Intel (MIT) que registra cada `Present()` de un proceso en Windows. El paquete
fija la versión 2.6.0 (980 320 bytes, SHA-256 `b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af`,
`workloads.py:180-184`). `presentmon_install`:

1. Se rechaza en cualquier plataforma que no sea Windows (`:191-192`).
2. No hace nada si el archivo ya está en `%LOCALAPPDATA%\metal-gpu-trace` y su hash coincide (`:194-197`).
3. Si no, descarga a una carpeta temporal (el doble del tamaño fijado es el techo, `:201`), comprueba el SHA-256 y
   reemplaza el archivo destino (`:199-204`).

Necesita derechos de administrador o pertenecer al grupo Performance Log Users para correr (la descripción de la propia
herramienta, `workloads.py:187-190`: **no verificado** contra la documentación de Intel).

Al **grabar**, el motor busca PresentMon en este orden (`find_presentmon`, `perf_record_windows.py:420-430`): el archivo
que nombra `PRESENTMON_EXE` (y si está definida pero el archivo no existe, **ninguno**, sin alternativa), el
`PresentMon*.exe` más nuevo en la carpeta de la caché, y luego `PresentMon` o `PresentMon-x64` en el `PATH`. El hash se
comprueba solo al instalar, no al usar (límite 4).

## El motor de Windows

`perf_record_windows.py` es toda la grabación de Windows. El servidor lo llama desde `record_run` cuando
`sys.platform == "win32"` (`recording.py:373-385`), con una importación tardía porque el módulo puede haberse importado ya
por otra cosa (`:374`), y `record_run` termina luego en el mismo `finish` que macOS (`:385`). También se puede lanzar a
mano: `python src\metal_gpu_trace\perf_record_windows.py <label> <seconds> <wine|native|attach> <prefix> <workdir>
<command...>` (`main`, `:950-962`; correrlo en el Mac sin argumentos imprime la línea de uso, lo que **no se reprodujo**
aquí).

![Ocho cajas en dos filas unidas por flechas. Fila de arriba: candado, programa, fuente de fotogramas (una decisión), bucle de un segundo. Fila de abajo: detener y limpiar, qué fotogramas (una decisión), escribir, y recording.finish.](/diagrams/recording-windows-engine.png)
*Figura 2. Una grabación de Windows. Fuente HTML: `docs/diagrams/recording-windows-engine.html`.*

### Por qué un motor aparte, y qué mide

Instruments existe solo en macOS, así que el motor de Windows no puede producir un `.trace`: no hay `xctrace`, ni Metal
System Trace, ni tiempos por encoder. Lo que puede medir es **cuándo se presentaron los fotogramas**. Construye la misma
forma de resumen con `metrics.py` (`:24-28`, `:887-917`), pero varios bloques quedan vacíos o fijos: `missing_tables`
lista por nombre tres tablas de Metal, `metal_memory_mib` es `{"samples": 0}`, y `encoders` y `gpu_idle` se calculan con
los tramos de la única fuente que los tenga (E8). Las claves del resumen están en la
[guía de datos](./datos-y-su-ciclo-de-vida.md#un-resumen-de-windows).

### Las tres fuentes de fotogramas, y cuál gana

| Orden | Fuente | `gpu.source` | Qué da | Qué no puede dar |
|---|---|---|---|---|
| 1 | El registro del propio programa: `DRAWSTRESS_LOG`, una línea por lote de fotogramas (`dim`, `draws`, `frame_us`, `frames`) | `drawstress-log` | Tiempo de GPU por fotograma (una media por línea) y tramos para las estadísticas de encoders | Una distribución por fotograma: 1% low, 0,1% low, tasa de stutter y jitter quedan en `null` (`:859-862`), porque cada línea ya es una media |
| 2 | Filas de PresentMon: `MsBetweenPresents` y, cuando la columna existe y es positiva, `MsGPUTime` | `presentmon` | Una fila por `Present()` de ese proceso, con su tiempo de GPU | Tiempos por encoder |
| 3 | Un hilo de 1 ms que lee el compositor (`DwmGetCompositionTimingInfo`) | `dwm-composition` | Intervalos entre fotogramas compuestos de **todo el escritorio** | Tiempo de GPU por fotograma, y nada específico del proceso |
| ninguna | | | | La corrida falla: `no frame data` |

El orden es el de la cadena de `if` (`:787`, `:808`, `:819`, `:830`), así que una **corrida de drawstress en una máquina
con PresentMon instalado igualmente corre PresentMon** (arranca en `:652-659`, antes de leer el registro del programa)
**pero sus filas no se usan**: gana el registro. Esto está confirmado por el código; no se reprodujo.

Por qué tres fuentes: el registro es exacto para el programa de prueba del propio proyecto, PresentMon es la herramienta
adecuada para cualquier otro programa, y el compositor es un último recurso que funciona sin ninguna herramienta
instalada. El muestreador del compositor solo cuenta un intervalo entre dos fotogramas compuestos consecutivos: un salto
de varios fotogramas se descarta en lugar de repartirse en partes iguales (`:403-407`), así que nunca inventa
fotogramas.

### Paso a paso (Figura 2)

1. **Candado** (`:573-597`). El servidor pasa `config.LOCK`, la misma carpeta que usa macOS; lanzado a mano, el motor usa
   `<corridas>/.recording` (`:574`). `mkdir`, escribe el pid; si ya existe y su dueño está muerto, lo quita e intenta una
   vez más (dos intentos), y si no `another recording is running (<candado>); remove it if none is` (`:597`).
2. **Programa** (`:612-645`). Con `attach`, `find_attached_process` encuentra el pid por número o por un nombre dentro
   del nombre del proceso (gana el pid más alto, `:457-483`). Si no, mezcla `program_env` y `PERF_ENV` en el entorno,
   pone `DRAWSTRESS_LOG` en `<corridas>/<nombre>.drawstress.log` y arranca el programa con `Popen`.
3. **Fuente de fotogramas** (`:647-666`). Si `find_presentmon` encontró uno, lo arranca con `--process_id`,
   `--timed <segundos>`, `--terminate_after_timed`, `--stop_existing_session`; si no, arranca el hilo de DWM.
4. **El bucle** (`:673-705`). Una vez por segundo: toma una muestra del working set (`rss.csv`), mira el plazo y la señal
   de cancelar, y se detiene antes si el programa terminó solo. El progreso sale cada 5 s.
5. **Detener** (`:707-757`). Detiene el hilo de DWM; espera hasta 15 s a PresentMon y lo mata si no se detiene; al
   cancelar o pasarse del plazo, mata el árbol del programa, borra todo archivo que empiece por el nombre de la corrida y
   lanza `the recording was cancelled; nothing was saved` o `the recording took over N s and was stopped; nothing was
   saved` (`:744-746`). Si la grabación terminó y el programa sigue vivo, lo termina, y luego mata su árbol.
6. **Qué fotogramas** (`:759-844`): la tabla de arriba.
7. **Escribir** (`:846-927`): la tabla `frames.csv.gz`, las estadísticas (los números de ritmo salen de
   `perf_report.frame_pacing`, la misma función que usa macOS, `:489`), el resumen, el bloque `common`, el `.json`, y
   `KEEP_RUNS` con su propio `clean_runs` (`:503-518`, `:921-924`).
8. **Terminar**: de vuelta en `record_run`, `finish` añade `layer`, `context`, `tier` y el límite de disco
   (`recording.py:385`).

Un `finally` corre siempre que la grabación no tuvo éxito: detiene el hilo de DWM y PresentMon, mata el programa que
arrancó (nunca uno al que se enganchó) y borra todo archivo que empiece por el nombre de la corrida, y luego suelta el
candado (`:929-947`). El candado también se suelta si hubo éxito.

### Qué cambia respecto de macOS

| | macOS | Windows |
|---|---|---|
| Grabador | `perf_record.sh` manejando `xctrace` | `perf_record_windows.py`, en el propio proceso del servidor |
| Tiers | `light`, `standard`, `deep` | `deep` rechazado (`recording.py:49-50`); `memory` no tiene efecto: no hay tabla de memoria Metal |
| `memory_free_pct`, `background` | permitidos | rechazados (`recording.py:283-284`) |
| Disco necesario | `2 + 0,8 GB` por segundo, en `TMPDIR` y en la carpeta de corridas | 1 GB, en la carpeta de corridas (`preflight.py:50`, `:123-124`) |
| `xcrun`, pantalla | se comprueban | no se comprueban (`preflight.py:120`, `:132`) |
| Detener el programa al final | por nombre (`native`) o `wineserver -k` | el árbol de procesos (`kill_process_tree`, `:521-551`) |
| Wine | sí | no: `wine` pasa a ser `native` cuando no se da ninguno (`recording.py:61-65`), y un api marcado `wine: true` corre nativo (`workloads.py:88-89`) |
| Vida del candado | `mkdir` + tomar uno muerto bajo un segundo candado | `mkdir` + tomar uno muerto una vez, sin segundo candado (límite 3) |
| Tabla de fotogramas | `frames.csv.gz` con un `gpu_ms_<canal>` por canal | `frames.csv.gz` con `gpu_ms_draw` y `gpu_ms_total` (`:847`) |

`perf_record_windows.py` también lee datos de hardware para el bloque `device`: Win32 para el procesador, la RAM y la
versión del sistema, y, cuando se encuentra un `vegaflow_daemon.exe` junto al clon, una llamada `--system-info` con
plazo de 1 s que añade nombres de arquitectura de CPU y GPU (`collect_device_info`, `:242-283`; `daemon_candidates`
`:231-239`). Cualquier fallo vuelve a los datos de Win32 en silencio. Qué es VegaFlow, de dónde viene y quién lo ejecuta
**no está documentado en las guías de este repositorio** y no se investigó: pendiente de confirmar.

## Los archivos de datos

La carpeta es `src/metal_gpu_trace/data/`. Ambos son JSON simple que `config.py:35-36` lee **una vez, al importar**. No
hay `try` alrededor: un archivo ausente o roto detiene el servidor al arrancar, no en la primera llamada (**confirmado por
el código**; que ninguna prueba lo cubra no se comprobó).

### El archivo de familias de GPU

`apple-gpu-families.json`, 63 líneas. Hechos sobre las familias de GPU de Apple silicon Apple7 a Apple10: de cada una,
los chips de Mac y otros chips, las funciones que añade y los límites que difieren (`mesh_grid_threadgroups`,
`texture_2d_px`, ...); luego lo que es igual en todas, notas al pie y `guards` como `M1 only: Apple7 && !Apple8`. Su
`about` dice que son «facts restated from Apple's public documents, not Apple's text» (hechos reformulados de documentos
públicos de Apple, no su texto), y `sources` nombra tres URL, una con la fecha 2026-05-21. Que cada hecho coincida hoy
con esos documentos **no se verificó** para esta página.

| Lector | Qué hace | Línea |
|---|---|---|
| `traces.family_of`, `tool_gpu_family` | Busca una familia por clave (`Apple9`) o chip (`M1 Pro`, `A17 Pro`); la coincidencia por chip quita `series` y un sufijo `pro`/`max`/`ultra` | `traces.py:177-197` |
| `registry.RESOURCES` | Un recurso `metal-trace://gpu-families` para todo el archivo y uno por cada clave de familia | `registry.py:12-15` |

Qué pasa con una entrada ausente: `gpu_family` con un nombre desconocido lanza `unknown family or chip '<nombre>'; try
one of Apple10, Apple7, Apple8, Apple9 or a chip such as M1 Pro, M2, M3 Max, A17 Pro` (`traces.py:193`; la lista sale de
las claves del archivo, E7). Una familia sin `mac_chips` u `other_chips` lanzaría un `KeyError` dentro de `family_of`
(`traces.py:181`; **probable**, sin prueba). Para añadir una familia, se añade una clave: su recurso aparece solo
(`registry.py:14-15`).

La grabación no lee este archivo. Se describe aquí porque es la otra mitad de `data/`.

### El archivo de programas de prueba

`workloads.json`, 99 líneas. Una línea `about` y un objeto `workloads` con una entrada por programa de prueba. Los campos y
quién los lee:

| Campo | Significado | Lo lee |
|---|---|---|
| `title`, `about`, `license` | Lo que muestra `workload_list` | `workloads.py:101-112` |
| `url`, `sha256`, `bytes` | El archivo fijado: dónde está, su hash, su tamaño exacto | `workloads.py:159-161` |
| `dir` | La carpeta dentro del archivo que contiene el programa | `workloads.py:89` |
| `apis` | Para cada api: `program`, `args`, `wine` (true: correr bajo Wine), y opcionalmente `rosetta` o `moltenvk` | `workloads.py:43-47`, `:80-89` |
| `dim_variable`, `size_variables` | Las variables de entorno que fijan `dim` y `size` | `workloads.py:76-85` |
| `examples`, `example_traits` | Los nombres que acepta `example`, con el prefijo que toma el programa, y la clase y número de encoders esperados | `workloads.py:71-75`, `:101-112` |
| `downloads` | Archivos extra tomados de otro editor: `url`, `sha512`, `bytes`, `into` | `workloads.py:163-173` |

Qué pasa si una entrada falta o está mal: un **nombre** desconocido lanza `no workload '<nombre>'; workload_list lists
them` (`workloads.py:19-20`); un **api**, **example**, **dim** o **size** desconocido lanza los mensajes listados arriba;
un **campo ausente** dentro de una entrada (digamos `apis`) lanzaría un `KeyError` que el envoltorio de la herramienta
convierte en un error (**probable**: no se siguió, sin prueba). El archivo que se publica lo comprueban pruebas: la
entrada de drawstress debe tener un hash de 64 caracteres y una url `https`, `mtl-x64` debe estar marcada `rosetta`, y
`bgfx-examples` debe venir de `workloads-8` (`tests/test_recording.py:127-129`, `:281-284`; no ejecutadas).

**Para añadir un programa:** construir y subir un archivo con el workflow, tomar el SHA-256 de lo subido, añadir la
entrada con su `bytes`, y añadir una prueba que lea la entrada publicada. Fíjalo por hash: el código rechaza cualquier
otra cosa (`workloads.py:160-161`).

## Cuando falla

La primera columna es lo que ve la persona o el agente.

| Qué sale mal | Qué reciben | Qué queda | Línea |
|---|---|---|---|
| Falla una comprobación de preflight | El mensaje de la [tabla](#que-comprueba-preflight-y-que-dice) | Nada: no se arrancó ningún proceso | `preflight.py:101-137` |
| Falta `memory_pressure`, o no llega al porcentaje en 90 s | `memory_pressure is not available`, o `memory_pressure did not reach that free percentage; the Mac may already be below it` | Nada; el ayudante se detiene | `recording.py:287-306` |
| El propio script rechaza (etiqueta, cabecera del programa, ningún proceso al que engancharse, disco, candado) | `recording failed (exit N): <la última línea del script>`; salida 2 para argumentos, 4 para disco, 3 para el candado | Nada: el script sale antes de tomar el candado o antes de escribir | `perf_record.sh:10-24`, `:37`, `:47-50`; `recording.py:422-425` |
| Instruments falla o muere de inmediato | `no recording at <ruta>` del script, es decir `recording failed (exit 1): no recording at <ruta>` | Nada: la trampa borra los archivos de la corrida | `perf_record.sh:139-156`; `test_script_failure_cleanup` `:534` |
| Instruments muere **a mitad** | Véase [abajo](#que-pasa-si-instruments-muere-a-mitad) | | |
| El cliente cancela | `the recording was cancelled; nothing was saved` | Nada (la [secuencia de cierre forzado](#la-secuencia-de-cierre-forzado)) | `recording.py:396-409` |
| La grabación pasa su plazo | `the recording took over N s and was stopped; nothing was saved. The likely cause is a hidden window: ...` | Nada | `recording.py:410-413` |
| El programa no hace trabajo de GPU | `the program did no GPU work: it ended (<motivo>) after N s of recording, and its summary was not saved; check that it starts (under Wine: the Wine build, the prefix and the program's own log)` | El `.trace` solo si se pidió conservarlo; el mensaje lo dice | `recording.py:427-436` |
| El servidor muere a mitad de la grabación | Nada que ver: ya no hay servidor | Un bucle vigilante del script detiene el programa e Instruments | `perf_record.sh:82-92` |
| `wine --version` se cuelga | La versión de la capa es `null`; la grabación sigue | | `recording.py:140-143` |
| Dos grabaciones compiten por un candado cuyo dueño está muerto (macOS) | Una lo toma, la otra recibe `another recording is running` | | `perf_record.sh:44-61`, [la guía de datos](./datos-y-su-ciclo-de-vida.md#el-candado) |

### Qué pasa si Instruments muere a mitad

`xcrun xctrace record ... || true` ignora el estado de salida a propósito (`perf_record.sh:140-151`), así que el script
siempre continúa hasta `kill $sampler` (`:155`) y luego:

- Si **no** hay carpeta `.trace`, el script sale con 1 y `no recording at <ruta>` (`:156`), y la trampa `EXIT` borra los
  archivos de la corrida (`:71`). Esa rama la fija `test_script_failure_cleanup`, donde un `xcrun` de mentira sale de
  inmediato.
- Si **existe** una carpeta `.trace` (una parcial), el script corre el informe sobre ella (`:160`). **No reproducido**:
  no se mató ningún `xctrace` real. Por el código, pueden seguir dos cosas: `perf_report.py` sale con código distinto de
  cero (`set -e`, `:5`), la trampa borra la corrida y el error es `recording failed (exit N): <última línea>`, o escribe
  un resumen de lo que pudo leer; si ese no tiene intervalos de GPU, el servidor lo convierte en `the program did no GPU
  work` y borra la corrida (`recording.py:427-436`). Cuál de las dos pasa con un trace parcial concreto depende de
  `perf_report.py`, que es el tema de una guía posterior.
- Si muere **el servidor**, no Instruments, el bucle vigilante del script lo nota (`kill -0 $PERF_PARENT_PID`, `:84`),
  detiene el programa, mata `xctrace` y el informe, y termina el script, cuya trampa limpia (`:82-92`).

### Cuando falla el motor de Windows

| Qué sale mal | El mensaje | Línea |
|---|---|---|
| Etiqueta o segundos malos (lanzado a mano) | `label may hold only letters, digits, '.', '_' and '-'`, `seconds must be 1 to 3600` | `perf_record_windows.py:560-564` |
| Una grabación viva tiene el candado | `another recording is running (<candado>); remove it if none is` | `:597` |
| Ningún proceso coincide con el objetivo de enganche | `no running process matches <objetivo>` | `:475`, `:480` |
| No se puede arrancar el programa | `recording failed: <el mensaje del sistema>` (un `OSError`) | `recording.py:383-384` |
| Cancelar o pasarse del plazo | los dos mensajes del paso 5 | `:744-746` |
| Ninguna fuente dio fotogramas, y PresentMon corrió | `no frame data: PresentMon saw no Present() calls from this process; it is idle, minimized, or a launcher whose game runs in another process (use perf_attach on the game)` más la última línea de stderr de PresentMon | `:833-839` |
| Ninguna fuente dio fotogramas, sin PresentMon | `no frame data: the program wrote no DRAWSTRESS_LOG, PresentMon is not installed (call presentmon_install) and DWM gave no samples (DwmGetCompositionTimingInfo needs the interactive desktop session, not SSH or a service)` | `:840-844` |

Un `RuntimeError` o `ValueError` del motor se convierte en un `ToolError` con el mismo texto (`recording.py:381-382`).
Todo esto **no se reprodujo** (no hay máquina Windows); `test_no_frame_data_is_an_error`, `test_timeout_and_cleanup` y
`test_lock_handling` (`tests/test_perf_record_windows.py:623`, `:281`, `:87`) lo fijan (no ejecutadas para esta página).

## Límites conocidos

Cada elemento es un límite del comportamiento de hoy, escrito, no arreglado aquí.

| # | Límite | Dónde | Estado |
|---|---|---|---|
| 1 | Los rechazos del propio script llevan una ruta local en el error del cliente: la carpeta en `not enough free disk on <dir>`, el candado en `another recording is running (<lock>)` y el `.trace` en `no recording at <path>`; llegan al cliente por la última línea de stderr. Los mensajes de preflight y el «not an executable file» del script mantienen las rutas fuera (y una prueba lo dice), así que estas son las excepciones. Normalmente preflight rechaza primero, así que solo la carrera o un script lanzado a mano las muestran | `perf_record.sh:37`, `:48`, `:156`; `recording.py:424-425`; `tests/test_recording.py:565` | Confirmado por el código |
| 2 | `README.md` dice que la llamada vence «after 10 s per recorded second plus 120 s»; el código usa 15 s por segundo más 180 (55 con contadores) desde la 0.8.1 | `README.md:135-136`, `recording.py:266-269` | Confirmado: los dos difieren; cuál debe decir el README lo decide el dueño |
| 3 | La toma de un candado muerto en Windows no es atómica. El script de macOS toma un segundo candado mientras toma uno muerto; el motor de Windows quita el candado muerto y crea uno nuevo en dos pasos, así que dos procesos que ven el mismo dueño muerto pueden acabar teniéndolo ambos | `perf_record_windows.py:583-597` frente a `perf_record.sh:44-61` | Probable (leído del código; no reproducido: es una carrera). El hilo trabajador único lo hace improbable dentro de un servidor |
| 4 | El hash de PresentMon se comprueba al instalarlo, no al usarlo; un archivo nombrado por `PRESENTMON_EXE` o hallado en el `PATH` se ejecuta sin comprobar | `perf_record_windows.py:420-430`, `workloads.py:196-204` | Confirmado |
| 5 | Una grabación de Windows con la fuente `drawstress-log` deja `<run>.drawstress.log` (y `<run>.presentmon.csv` cuando corrió PresentMon) en disco: solo una corrida fallida los borra. La tabla de archivos de la guía de datos no lista `.drawstress.log`, y la cuota ignora los dos | `perf_record_windows.py:632-633`, `:762-764`, `:937-941`; `retention.py:30-43` | Confirmado por el código; no reproducido |
| 6 | Cancelar una grabación de Windows espera primero a PresentMon: `presentmon_proc.wait(timeout=15)` corre antes de la rama de cancelar, así que una cancelación puede tardar hasta 15 s en actuar | `perf_record_windows.py:711-723`, `:726-746` | Probable |
| 7 | `perf_record` detiene **todos** los procesos con el nombre del programa al terminar o cancelarse, no solo el que arrancó: una segunda copia del mismo programa, como un editor que tenías abierto, también termina | `perf_record.sh:80`, `recording.py:255-263` | Confirmado; la descripción de la herramienta dice «every process named like the program» (`recording.py:42`) |
| 8 | El primer mensaje de progreso dice «up to N s including read-back» también en Windows, donde no hay lectura de vuelta | `recording.py:371-372` | Confirmado (cosmético) |
| 9 | En Windows nada rechaza un api que no puede correr allí (`mtl`, `vk`, `mtl-x64` son programas de macOS): `os.access(..., X_OK)` es true para cualquier archivo en Windows, así que preflight pasa y `Popen` falla | `workloads.py:88-89`, `preflight.py:117-119` | Probable: no reproducido |
| 10 | Las líneas de `.drawstress.log` son medias, así que una corrida de drawstress en Windows no tiene 1% low, tasa de stutter ni jitter | `perf_record_windows.py:859-862` | Confirmado (un límite de la fuente, no un error) |
| 11 | La fuente DWM mide el compositor de todo el escritorio, no el programa | `perf_record_windows.py:351-363`, `:819-829` | Confirmado |
| 12 | La caché de programas de prueba no tiene limpieza | `workloads.py:147-176` | Véase la [guía de datos](./datos-y-su-ciclo-de-vida.md#la-cache-no-son-las-grabaciones) |
| 13 | Cuánto dura el arranque de Wine, y por tanto si 30 s es el número correcto, no se midió aquí | `metal_trace_mcp.py:27` | No reproducido |
| 14 | Qué es VegaFlow no está documentado en las guías | `perf_record_windows.py:181-283` | Pendiente de confirmar |

## Tocarlo sin romperlo

- Un rechazo nuevo: ponlo en `preflight.check` **antes** de cualquier cosa que arranque un proceso, haz que el mensaje
  diga qué hacer, mantén las rutas fuera de él y añade la prueba junto a sus hermanas en `tests/test_preflight.py` (cada
  una existente comprueba la redacción). Si el script de shell también debe rechazar, repítelo allí con su código de
  salida y actualiza la [tabla](#que-repite-cada-capa).
- Una variable nueva para el script: fíjala en `record_run` (`recording.py:360-370`), léela en `perf_record.sh` y
  documéntala en la [tabla](#paso-3-el-entorno-que-recibe-el-script). Los pares de `PERF_ENV` se parten por espacios:
  ningún valor puede contener uno (`check_env`).
- Todo lo que el servidor mata al cancelar debe listarse **antes** de arrancar, como hace `record_run` con `before` y
  `ktraces` (`recording.py:386-388`): una limpieza que borra lo que no creó borra un archivo de una persona.
- Un campo nuevo en el resumen: escríbelo en el código compartido de `metrics.py` para los dos motores, no a mano dos
  veces (véase la [guía de datos](./datos-y-su-ciclo-de-vida.md#tocarlo-sin-romperlo)).
- Un programa de prueba nuevo: véase [Para añadir un programa](#el-archivo-de-programas-de-prueba). Nunca lo fijes por
  etiqueta ni por nombre: el hash es la identidad.
- El código de Windows no debe llamar a `os.kill` para preguntar si un proceso está vivo (allí lo termina): usa
  `is_process_alive` (`preflight.py:18-20`).
- El `finally` del motor borra todo archivo que empiece por el nombre de la corrida (`:937-941`); un archivo nuevo de una
  corrida de Windows debe conservar el nombre de la corrida como prefijo para que se limpie y se pode con ella.

## Evidencia: los comandos y su salida real

Recogida el 2026-11-16 en un Mac con Apple silicon. Todos los comandos solo leen. Las rutas están acortadas: la carpeta
personal es `~`. La sesión que los recogió podía correr comandos de solo lectura (`rg`, `sed`, `jq`, `ls`, `du`), no
Python ni los scripts, así que nada de lo que sigue es la salida de una grabación ni de una comprobación corrida en vivo:
lo que *dice* una comprobación se lee de la línea que la lanza.

### E1 Cada mensaje que puede lanzar preflight, con su línea

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

Cada línea la recorta `cut` a 175 caracteres. El orden de los números de línea (108 antes de 116 antes de 121 antes de
130 antes de 133 antes de 136) es el orden en que corren las comprobaciones. Correr `preflight.check` con un sustituto
para cada fallo **no se reprodujo**; `tests/test_preflight.py` tiene una prueba por fallo (`:65` a `:162`), no ejecutadas
para esta página.

### E2 Qué rechaza el propio script, y con qué código de salida

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
55:  trap 'exit 130' INT TERM
74:trap 'rm -rf $out/$name.*(N); exit 143' TERM
156:[ -d $out/$name.trace ] || { echo "no recording at $out/$name.trace" >&2; exit 1; }
```

(El mensaje del candado es el `echo` de la línea anterior a la 49, `perf_record.sh:48`.) Las líneas 12, 37, 48 y 156
imprimen una ruta o una carpeta; la 13 y la 18 imprimen solo el nombre del archivo, lo que afirma una prueba
(`tests/test_recording.py:565`, límite 1). Correr el script con un argumento malo **no se reprodujo**.

### E3 Los números: plazo y disco, según las fórmulas del código

```text
$ jq -n -c '{deadline_s:([20,30,60]|map(.*15+180)), deadline_counters_s:([20,30,60]|map(.*55+180)), disk_gb:([20,30,60]|map(2+((.*8+9)/10|floor))), disk_gb_windows:1}'
{"deadline_s":[480,630,1080],"deadline_counters_s":[1280,1830,3480],"disk_gb":[18,26,50],"disk_gb_windows":1}
```

Las fórmulas son `seconds × 15 + 180` (`recording.py:269`, 55 con contadores) y `2 + (seconds × 8 + 9) / 10` en
división entera (`preflight.py:50`). Reproducen las cifras que declara el servidor: 630 s para 30 s de Wine, y «26 GB
for 30 s, 50 GB for 60 s» (`metal_trace_mcp.py:27-28`). Son las fórmulas del código evaluadas por `jq`, no la medición
de una grabación real.

### E4 Los programas de prueba fijados

```text
$ jq -r '.workloads|to_entries[]|"\(.key)\t\(.value.sha256)\t\(.value.bytes)\t\(.value.url|split("/")|.[7:]|join("/"))\t\(.value.apis|keys|join(","))"' src/metal_gpu_trace/data/workloads.json
drawstress	2b3b01fa2dd0a7d5a1629046305319130d58ce4d843bd22c3f736071c0bfde2e	9291979	workloads-3/drawstress-workloads-3.tar.gz	d3d11,d3d12,mtl,mtl-x64,vk
bgfx-examples	1d120363981ced4ae01dad57085258206fbc84f35bd9bcdcfe656b1af355d091	57350072	workloads-8/bgfx-examples-workloads-8.tar.gz	d3d11,d3d12,mtl
godot	a85320f08e1ac2721288441a5317796de4673a6df6fc727b71c135503adc09c5	1525	workloads-9/godot-workloads-9.tar.gz	d3d12,mtl

$ jq -r '.workloads.godot.downloads[]|"\(.into)\t\(.bytes)\t\(.sha512[0:16])"' src/metal_gpu_trace/data/workloads.json
bin/mac	170622178	38aa16e5bba20839
bin/win	86013866	83decd58fdf67b9d

$ jq -r '.workloads["bgfx-examples"].examples|length' src/metal_gpu_trace/data/workloads.json
30
$ jq -r '.workloads["bgfx-examples"].example_traits|length' src/metal_gpu_trace/data/workloads.json
30

$ jq -r '.workloads.drawstress.apis|to_entries[]|"\(.key) \(.value|tostring)"' src/metal_gpu_trace/data/workloads.json
mtl {"program":"drawstress","args":"--mtl","wine":false}
mtl-x64 {"program":"drawstress-x64","args":"--mtl","wine":false,"rosetta":true}
vk {"program":"drawstress","args":"--vk","wine":false,"moltenvk":true}
d3d11 {"program":"drawstress.exe","args":"--d3d11","wine":true}
d3d12 {"program":"drawstress.exe","args":"--d3d12","wine":true}
```

(El host y el proyecto de la URL los corta `.[7:]`; la URL completa es
`https://github.com/<proyecto>/releases/download/<etiqueta>/<archivo>`.) Los tamaños son los que el código usa como
`--max-filesize`. Un `curl` de estas URL, y un `shasum` de lo publicado, **no se reprodujeron**.

### E5 Qué guarda la caché, frente a los pins

```text
$ ls -a ~/Library/Caches/metal-gpu-trace
.
..
bgfx-examples-1d120363981c
bgfx-examples-320a6b3bbc11
bgfx-examples-9c1bd6164b4a
bgfx-examples-bd41458ee01e
bgfx-examples-c5b25350c15e
drawstress-2b3b01fa2dd0
drawstress-f7e25cbb8c4a
godot-a85320f08e1a

$ du -sh ~/Library/Caches/metal-gpu-trace
942M	~/Library/Caches/metal-gpu-trace

$ cd ~/Library/Caches/metal-gpu-trace
$ ls -1 drawstress-2b3b01fa2dd0/drawstress
BUILD.txt
LICENSE-bgfx
bgfx-drawstress-env.patch
drawstress
drawstress-x64
drawstress.exe

$ ls -1 godot-a85320f08e1a/godot godot-a85320f08e1a/godot/bin
godot-a85320f08e1a/godot:
BUILD.txt
bin
project

godot-a85320f08e1a/godot/bin:
mac
win

$ sed -n 2,6p drawstress-2b3b01fa2dd0/drawstress/BUILD.txt
GENie f7055e309a5c2bc28d7abd35960e14b9864fc5ea
bgfx 71539c41e7e782ccf30f19ae4498d25ddc7bc68c
bx d4e6ed3cf4f75c355bb04088bc1c13cd919aafa6
bimg 671fe06dd7012a1ab85aa931019ed16112909756
llvm-mingw 20260908 ucrt macos-universal
```

Las tres carpetas cuyo nombre coincide con un pin de E4 (`bgfx-examples-1d120363981c`, `drawstress-2b3b01fa2dd0`,
`godot-a85320f08e1a`) son las vigentes; las otras cinco no. No hay ningún `recording.lock` en la carpeta: nada está
grabando. Los nombres de carpeta son los 12 primeros caracteres del hash (`workloads.py:22`).

### E6 Dónde fija el servidor el entorno del script

```text
$ rg -n 'env\["|PERF_OUT=|PERF_LOCK=|PERF_PARENT_PID=|PERF_ENV=' src/metal_gpu_trace/recording.py
360:    env = dict(os.environ, PERF_OUT=str(config.OUT), PERF_LOCK=str(config.LOCK), PERF_PARENT_PID=str(os.getpid()),
361:               PERF_ENV=" ".join(filter(None, [os.environ.get("PERF_ENV", ""), program_env])))
363:        env["PERF_MEMORY"] = "0"
365:        env["KEEP_TRACE"] = "1"
367:        env["PERF_PREFIX"] = BACKGROUND_PREFIX
369:        env["PERF_INSTRUMENTS"] = ";".join(filter(None, [os.environ.get("PERF_INSTRUMENTS", ""), "Metal GPU Counters"]))
370:    layer = layer or layer_of(wine, prefix, env["PERF_ENV"])
377:                label, int(seconds), wine, prefix, workdir, command, env["PERF_ENV"],
```

### E7 Qué guarda el archivo de familias de GPU

```text
$ jq -r '.families|keys|join(" ")' src/metal_gpu_trace/data/apple-gpu-families.json
Apple10 Apple7 Apple8 Apple9

$ jq -r '.families.Apple9|keys|join(" ")' src/metal_gpu_trace/data/apple-gpu-families.json
adds limits mac_chips other_chips

$ jq -r '.families|to_entries[]|"\(.key): \(.value.mac_chips|join(", "))"' src/metal_gpu_trace/data/apple-gpu-families.json
Apple7: M1, M1 Pro, M1 Max, M1 Ultra
Apple8: M2 series
Apple9: M3 series, M4 series
Apple10: M5 series

$ jq -r '.sources.feature_set_tables_date' src/metal_gpu_trace/data/apple-gpu-families.json
2026-05-21

$ rg -n "FAMILIES|WORKLOADS" src/metal_gpu_trace --glob '*.py' | cut -c1-120
src/metal_gpu_trace/workloads.py:19:    if name not in config.WORKLOADS:
src/metal_gpu_trace/workloads.py:21:    entry = config.WORKLOADS[name]
src/metal_gpu_trace/workloads.py:105:    for name, entry in config.WORKLOADS.items():
src/metal_gpu_trace/traces.py:180:    for key, family in config.FAMILIES["families"].items():
src/metal_gpu_trace/traces.py:193:        raise paths.ToolError(f"unknown family or chip {name!r}; try one of {', '.join
src/metal_gpu_trace/traces.py:195:    return {"family": key, **config.FAMILIES["families"][key], "same_on_all": config.F
src/metal_gpu_trace/traces.py:196:            "footnotes": config.FAMILIES["footnotes"], "guards": config.FAMILIES["guards"], "sources": config.FAMILIES["sources"]}
src/metal_gpu_trace/registry.py:12:RESOURCES = {"metal-trace://gpu-families": ("Apple GPU families", config.FAMILIES["ab
src/metal_gpu_trace/registry.py:15:    for key in config.FAMILIES["families"]}
src/metal_gpu_trace/config.py:35:FAMILIES = json.loads((PACKAGE_DIR / "data" / "apple-gpu-families.json").read_text(enco
src/metal_gpu_trace/config.py:36:WORKLOADS = json.loads((PACKAGE_DIR / "data" / "workloads.json").read_text(encoding="ut
```

La salida de `rg` muestra los lectores de los dos archivos: `workloads.py` lee `WORKLOADS`, `traces.py` y `registry.py`
leen `FAMILIES`, y el código de grabación no lee ninguno (`rg` no encuentra `FAMILIES` en `recording.py` ni en
`preflight.py`).

### E8 Qué fuente usa el motor de Windows, y dónde lo dice

```text
$ rg -n '"source": |if entries:|elif pm_intervals|elif dwm_samples' src/metal_gpu_trace/perf_record_windows.py
787:        if entries:
808:        elif pm_intervals:
819:        elif dwm_samples:
859:        if entries:
876:            "source": "drawstress-log" if entries else "presentmon" if pm_intervals else "dwm-composition",
878:        if entries:
```

(El `else` de cierre de la línea 830 es una palabra clave sola que este patrón no encuentra; se lee con `sed -n 830,844p`,
que muestra los dos errores `no frame data`.) La cadena `if entries` / `elif pm_intervals` / `elif dwm_samples` / `else`
(línea 830) es el orden de la tabla de [El motor de Windows](#las-tres-fuentes-de-fotogramas-y-cual-gana); la línea 859
es la que anula los números de ritmo por fotograma para el registro. Correr una grabación del motor **no se reprodujo**
(aquí no hay máquina Windows).

### E9 Las líneas del candado y la limpieza de Windows

```text
$ rg -n "lock_path|FileExistsError|is_process_alive" src/metal_gpu_trace/perf_record_windows.py
332:def is_process_alive(pid):
394:                if pid and not is_process_alive(pid):
555:                   cancelled=None, progress=None, lock_path=None):
574:    lock_path = pathlib.Path(lock_path) if lock_path is not None else out_dir / ".recording"
575:    lock_path.parent.mkdir(parents=True, exist_ok=True)
579:            lock_path.mkdir(exist_ok=False)
580:            (lock_path / "pid").write_text(str(os.getpid()), encoding="utf-8")
583:        except FileExistsError:
584:            owner = lock_path / "pid"
587:                stale = not is_process_alive(int(owner.read_text(encoding="utf-8").strip()))
593:                    lock_path.rmdir()
597:            raise RuntimeError(f"another recording is running ({lock_path}); remove it if none is") from None
942:        if lock_acquired and lock_path.exists():
944:                (lock_path / "pid").unlink(missing_ok=True)
945:                lock_path.rmdir()
```

Las líneas 590-596 son toda la toma del candado muerto: quitar el `pid`, `rmdir`, intentar otra vez. No hay un segundo
candado alrededor, que es el límite 3.

### E10 PresentMon: dónde viven el pin y la búsqueda

```text
$ rg -n "find_presentmon|PRESENTMON_EXE|presentmon_dir|PRESENTMON\[" src/metal_gpu_trace/perf_record_windows.py src/metal_gpu_trace/workloads.py | cut -c1-140
src/metal_gpu_trace/workloads.py:194:    target_dir = perf_record_windows.presentmon_dir()
src/metal_gpu_trace/workloads.py:195:    target = target_dir / f"PresentMon-{PRESENTMON['version']}-x64.exe"
src/metal_gpu_trace/workloads.py:196:    if target.is_file() and file_id(target)["sha256"] == PRESENTMON["sha256"]:
src/metal_gpu_trace/workloads.py:197:        return {"installed": False, "path": str(target), "version": PRESENTMON["version"]}
src/metal_gpu_trace/workloads.py:201:        download(PRESENTMON["url"], part, PRESENTMON["bytes"] * 2)
src/metal_gpu_trace/workloads.py:202:        if file_id(part)["sha256"] != PRESENTMON["sha256"]:
src/metal_gpu_trace/workloads.py:205:    return {"installed": True, "path": str(target), "version": PRESENTMON["version"], "bytes": PRESENTM
src/metal_gpu_trace/perf_record_windows.py:415:def presentmon_dir():
src/metal_gpu_trace/perf_record_windows.py:420:def find_presentmon():
src/metal_gpu_trace/perf_record_windows.py:421:    """Returns the path of Intel's PresentMon console application, or None: $PRESENTMON_EXE, 
src/metal_gpu_trace/perf_record_windows.py:424:    explicit = os.environ.get("PRESENTMON_EXE")
src/metal_gpu_trace/perf_record_windows.py:427:    cache = presentmon_dir()
src/metal_gpu_trace/perf_record_windows.py:649:        presentmon_exe = find_presentmon()
```

El hash se compara en `workloads.py:196` y `:202` (instalación) y en ningún sitio de `find_presentmon` (`:420-430`):
límite 4.

### Lo que no se reprodujo

- Cualquier grabación, de macOS o de Windows (hace falta Instruments, una máquina Windows y tiempo de GPU), y por tanto
  todo tiempo de la página.
- `preflight.check` en sí, con una entrada que falla, y cada mensaje impreso en vivo (los mensajes se leen del código
  fuente, E1, y los fijan pruebas que no se ejecutaron).
- `perf_record.sh` o `perf_record_windows.py` con argumentos malos, incluidas sus líneas de uso.
- Una descarga: `workload_fetch`, `presentmon_install`, y un `shasum` de lo que las publicaciones del proyecto ofrecen hoy.
- Un `.trace` parcial de un Instruments interrumpido, y la cancelación de una grabación de Windows.
- Cuántos segundos dura el arranque de Wine.

## Véase también

- [How it works](../../guides/how-it-works.md): las capas y el recorrido de una petición.
- [Datos y su ciclo de vida](./datos-y-su-ciclo-de-vida.md): los archivos que deja una grabación, el candado y los dos
  ajustes de retención.
- [Prueba de la 0.27.0](../../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit): el límite de tamaño medido.
