# Resumir y analizar

**Lector:** personas que leen un resumen o una comparación y quieren saber de dónde sale cada número y cuándo no fiarse de él, o que cambian `perf_report.py`, `analysis.py`, `metrics.py` o `experiments.py`. Revisado el 2026-11-17.

English: [Summarizing and analyzing](../../../guides/summarizing/index.md)

**En corto:** tras grabar un programa, un script reduce la grabación enorme a un archivo pequeño de números (fotogramas por
segundo, tirones, memoria). Otras herramientas leen esos archivos, comparan dos corridas y dicen «mejor», «peor» o «igual».
Esta guía muestra de dónde sale cada número, por qué una sola corrida prueba poco y cuándo no hay que fiarse de un resultado.

## Las páginas

| Página | Responde | Código |
|---|---|---|
| [Del trace al resumen](./del-trace-al-resumen.md) | qué lee `perf_report.py`, paso a paso; las tablas; el trabajo que nunca se presentó | `perf_report.py`: `summarize` `:627`, `main` `:840`, `export` `:49`, `toc_and_tables` `:95`, `rows` `:143`; un `xctrace export` por tabla, de dos en dos; escribe `<label>.json`, `.frames.csv.gz`, `.metal_memory.csv.gz` |
| [Cómo se calcula cada número](./como-se-calculan-los-numeros.md) | fórmula y línea de cada número principal; hitches, aviso de ruido, Windows | `perf_report.py`: `frame_pacing` `:253`, `attribute_hitches` `:283`, `unpresented` `:206`, `noisy_environment` `:565` |
| [Leer y comparar](./leer-y-comparar.md) | `analysis.py`: `skip_s`, comparar, línea base, check, gate, history, diagnose, números que faltan | `analysis.py`: `perf_runs`, `perf_compare`, `perf_baseline`, `perf_check`, `perf_history`, `perf_gate`, `perf_diagnose`, `perf_memory_breakdown` |
| [Los experimentos](./experimentos.md) | `experiments.py`: grabar línea base, A B B A, frío/caliente, barrido | `perf_baseline_record`, `perf_ab`, `perf_cold_warm`, `perf_sweep` (graban y luego llaman a `analysis`) |
| [Ruido y veredictos](./ruido-y-veredictos.md) | los cuatro jueces lado a lado; qué hace el proyecto con el ruido | |
| [Energía y calor en los dos extremos](./energia-y-calor.md) | `machine.power`: modo de bajo consumo y calor leídos antes y después de una grabación, y el aviso `power` de `perf_compare` | `perf_report.py`: `power_state` `:653`, `power_block` `:672`; `recording.py`: `:386`, `:438-439`; `analysis.py`: `:191-203` |
| [Cuando falla](./cuando-falla.md) | qué sale mal y qué recibe quien lee | |
| [Tocarlo sin romperlo](./tocarlo-sin-romperlo.md) | cómo cambiar el código sin romper nada | |
| [Límites conocidos](./limites.md) | 13 límites anotados y lo que no se reprodujo | |
| [Evidencia](./evidencia.md) | los comandos (E1 a E10) y su salida real | |

## Cómo leer las etiquetas

Cada afirmación técnica es **confirmada** (con `archivo:línea`, comprobada con `rg` o `sed` el 2026-11-16 contra el árbol de
trabajo: la 0.27.3), **probable** (leída en el código, no ejecutada aquí) o
**especulación** (una conjetura sobre el porqué). **No verificado** marca un dato de fuera que no se comparó con su fuente;
**no reproducido** significa que el comportamiento no se pudo ejecutar para esta guía. Las líneas se mueven con el código:
busca el nombre, no solo el número. Cada cifra tiene su comando en [Evidencia](./evidencia.md). Dos límites valen para toda la
guía: el repositorio no tiene ningún `.trace` (la carpeta `perf-runs/` del clon guarda dos resúmenes terminados y sus tablas)
y `xctrace` exige uno, así que **`perf_report.py` no se ejecutó**; y la sesión solo pudo correr comandos de lectura (`rg`,
`sed`, `jq`, `awk`), no Python, así que **tampoco se ejecutó ninguna herramienta de `analysis.py`**: sus números se evalúan a
mano con las fórmulas del código sobre los dos resúmenes reales, y el texto lo dice cada vez. Las pruebas nombradas **no se
ejecutaron**.

## Un ejemplo primero

Dos grabaciones del mismo programa, de 20 segundos cada una (`a2-proof-first_20261115-085621` y
`a2-proof-second_20261115-085735`; el nombre es la etiqueta más una marca de tiempo), comandos E2 y E3:

| | primera | segunda |
|---|---|---|
| `gpu.frames` | 2045 | 153 |
| `gpu.fps_estimate` | 105.4 | 102.1 |
| `gpu.fps_1pct_low` | 96.2 | 40.8 |
| `gpu.stutter_rate_pct` | 0.29 | 2.63 |
| `gpu.unpresented` | ausente | presente: 1776 command buffers desde los 3.637 s |

De dónde sale 105.4: [fps_estimate](./como-se-calculan-los-numeros.md#fps_estimate). Por qué solo 153 fotogramas en 20 s:
[Trabajo que nunca se presentó](./del-trace-al-resumen.md#trabajo-que-nunca-se-presento). Si 102.1 frente a 105.4 es una
regresión (`perf_compare` informa -3.3, -3.1 % y nada más): [Ruido y veredictos](./ruido-y-veredictos.md).

## Por qué esta parte tiene esta forma

| Decisión | Por qué | Alternativas que se dejaron fuera |
|---|---|---|
| El resumen es un JSON corto leído del trazo una vez; el `.trace` se borra | Un `.trace` pesa cientos de MB y `xctrace` tarda minutos en leerlo; lo que las herramientas necesitan cabe en pocos KB más dos tablas ([guía de datos](../datos-y-su-ciclo-de-vida/index.md)). El script borra el trazo justo después del informe salvo con `KEEP_TRACE=1` (`perf_record.sh:160-163`) | Releer el trazo en cada pregunta: **especulación** de que se descartó por el tiempo y el disco que cuesta cada lectura (`perf_report.py:39-41`, `:126-165`); ningún ADR lo recoge (el ADR-0006 trata de conservar el trazo, no de esto) |
| `perf_report.py` también es un script que se lanza por ruta | `perf_record.sh` llama a `python3 -I perf_report.py <trazo>` (`:160`) y el archivo añade el paquete a la ruta por sí mismo (`perf_report.py:24-26`) | Solo un módulo: debe funcionar con `-I`, que ignora el entorno |
| Los números que comparten ambas plataformas viven en `metrics.py` | Windows no tiene `.trace`, pero sí un resumen de la misma forma: `frame_pacing`, `stats` y `common_block` son una sola copia (`metrics.py:1-2`, `perf_record_windows.py:489`, `:917`) | Dos copias de cada fórmula: las de Windows se desviarían |
| «Mejor» significa fuera de un **rango**, no un número distinto | Corridas iguales difieren por sí solas: 5 corridas de un programa difirieron un 4.4 % en FPS y un 6.1 % en ms de GPU (`CHANGELOG.md`, entrada de `perf_baseline`; no se volvió a medir aquí), así que una corrida no es referencia (`analysis.py:259-268`). La decisión usa pocos números: el ritmo de fotogramas, los encoders cortos y el tiempo ocioso de la GPU «varían demasiado entre corridas iguales» (13 % y 7 puntos en la misma entrada, `analysis.py:338-340`) | Un porcentaje fijo sobre una corrida (llama regresión al ruido); juzgar con todo (más falsas alarmas) |
| La regla de 100 fotogramas es un aviso, no una negativa | Se añaden `too_short` y un `hint` y la respuesta se calcula igual (`analysis.py:187`, `:377-378`, `:498-499`) | Negarse con corridas cortas: nada en vez de un número con una advertencia |

## Las piezas y dónde viven

El archivo y las funciones de cada página están en la última columna de arriba. Lo que comparten ambas plataformas es
`metrics.py` (`stats` `:75`, `encoder_stats` `:94`, `idle_gaps` `:122`, `common_block` `:49`): las mismas fórmulas para macOS y
Windows.

## Véase también

- [Datos y su ciclo de vida](../datos-y-su-ciclo-de-vida/index.md): las claves del resumen, las generaciones del formato, las tablas, el archivo de líneas base, qué borra qué. Este módulo no lo repite.
- [Grabar](../grabar/index.md): el `.trace`, los muestreadores `rss.csv` y `agx.csv`, el candado, el motor de Windows. [How it works](../../../guides/how-it-works.md): qué capa llama a cuál. [Run from a clone](../../../guides/run-from-a-clone.md): cómo correr el código y las pruebas.
