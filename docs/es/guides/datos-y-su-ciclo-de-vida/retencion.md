# Retención: dos mecanismos que no se mezclan

**Lector:** personas que cambian o ajustan cómo se mantiene pequeña la carpeta de corridas. Revisado el 2026-11-16.

English: [Retention: two mechanisms that do not mix](../../../guides/data-and-lifecycle/retention.md)

> **En corto:** dos ajustes parecidos impiden que la carpeta de corridas crezca sin fin. Uno conserva las N grabaciones
> más nuevas y borra enteras las más viejas. El otro mantiene la carpeta por debajo de un tamaño y borra solo los archivos
> pesados, los más viejos primero, así que los números pequeños sobreviven. Si no alcanza el tamaño, no dice nada.

Volver al [índice](./index.md). Ejemplo: tres grabaciones de 259 MiB; `KEEP_RUNS=2` borra la más vieja entera, mientras que `METAL_TRACE_MAX_DISK_MB=600` solo borra su `.trace` y deja su resumen (tabla trabajada más abajo).

| | `KEEP_RUNS=N` | `METAL_TRACE_MAX_DISK_MB=M` |
|---|---|---|
| Cuenta | Corridas (por la fecha de modificación de su `.json`) | Bytes (MiB) de todo el primer nivel de la carpeta |
| Corre en | `perf_record.sh:164` llama a `prune_runs.sh`; el borrado es `prune_runs.sh:9` | `recording.finish` (`recording.py:346`) llama a `retention.prune_to_quota` (`retention.py:46`) |
| Se lee de | El entorno del proceso, por el script y el motor de Windows (`perf_record_windows.py:922`); el servidor pasa el suyo (`recording.py:360`) | `config.py:22`, al arrancar el servidor y en cada `config.reload` |
| Borra | Todos los archivos de cada corrida más vieja que las N más nuevas: `${old:r}.*` (`prune_runs.sh:9`): `.json`, tablas, muestreadores, `.chrome-trace`, `.trace` | Solo archivos pesados: `.trace`, luego `.chrome-trace`, luego tablas (`retention.py:8-10`, `:37-42`) |
| Nunca borra | `baselines.json`, `panel.json` (`prune_runs.sh:9`), la marca (no es el stem de un `.json`) | Un `.json`, muestreadores, `baselines.json`, la marca, `.presentmon.csv` (`retention.py:43`) |
| Orden | Sobreviven las N más nuevas | Más viejas primero dentro de cada tipo; tipos en el orden de arriba; el `.trace` de la corrida actual el último |
| No actúa cuando | `KEEP_RUNS` no es un entero de 1 o más (`perf_record.sh:164`); `prune_runs.sh` sale con 2 ante un valor malo (`prune_runs.sh:8`) | Límite sin fijar o inválido; corre otra grabación (`recording.py:346`) |
| Avisa | Nada | `retention` en el resumen de la grabación que lo disparó, si se fue un archivo |

La Figura 1 de [Archivos en disco](./archivos-en-disco.md#que-deja-una-grabacion-en-disco) muestra la misma división por tipo de archivo.

## Cómo decide `KEEP_RUNS`

`prune_runs.sh:9` lista los `.json` de la carpeta salvo `baselines.json` y `panel.json`, el más nuevo primero (calificador de zsh `om`), toma desde la posición `keep + 1` y borra todos los archivos con el mismo stem. Una corrida es, por tanto, un `.json`: un `.trace` sin `.json` nunca se ve ([Cuando falla](./cuando-falla.md), límite conocido 7). `test_keep_runs_still_removes_old_tables` (`tests/test_recording.py:1101`) fija el borrado de las tablas comprimidas. En Windows `clean_runs` (`perf_record_windows.py:503-518`) hace lo mismo en Python con `unlink`, una segunda implementación (confirmado: sin código compartido).

## Cómo decide la cuota

`prune_to_quota` (`retention.py:46-82`):

1. Lista el primer nivel con la fecha de modificación y el tamaño de cada entrada (una carpeta se cuenta recursivamente, un enlace como un archivo de su propio tamaño, `retention.py:13-27`).
2. Si el total es como mucho `M` MiB, no toca nada (`retention.py:60-61`).
3. Si no, ordena las entradas borrables por tipo y luego edad, y las borra una a una hasta que cabe (`retention.py:62-81`). `kind_of` (`retention.py:30-43`): el `.trace` de la corrida actual es `CURRENT_TRACE` y va el último; el `.chrome-trace` y las tablas de la corrida actual son `None` (se quedan siempre); cualquier otro `.trace`, `.chrome-trace` o tabla es candidato; todo lo demás es `None`.
4. Devuelve `{freed_mb, removed, trace_dropped}`; `trace_dropped` es verdadero solo si se fue el `.trace` de la corrida actual.

## Predecir qué sobrevive (un ejemplo trabajado, no una corrida medida)

Tres corridas `deep` A (la más vieja), B y C (la recién grabada), cada una con un `.trace` de 259 MiB, 0,5 MiB de tablas y un resumen de 5 KiB, unos 778 MiB en total:

| `METAL_TRACE_MAX_DISK_MB` | Qué se va, en orden | Qué queda |
|---|---|---|
| 1000 | Nada: cabe | A, B, C completas |
| 600 | El `.trace` de A (total 519 MiB, cabe) | A sin trazo; B, C completas |
| 300 | El `.trace` de A y luego el de B (total 260 MiB) | Solo C tiene `.trace` |
| 200 | Los `.trace` de A y B, luego las tablas de A y B, luego el `.trace` de C (`trace_dropped: true`) | Los tres resúmenes, las tablas de C y los muestreadores, unos 1 MiB |

Con `KEEP_RUNS=2` las mismas corridas pierden **todos** los archivos de A (resumen incluido) y conservan B y C completas; con ambos ajustes el script poda primero (`KEEP_RUNS`, al final de `perf_record.sh`) y la cuota corre después, sobre lo que queda. Leído del código y de las reglas de `kind_of`; **no se reprodujo**: ninguna carpeta real de aquí estuvo nunca por encima de un límite, y borrar no es una comprobación de solo lectura. Para eso existe `tests/test_retention.py` (no ejecutado para esta página).

## Donde el límite no se puede cumplir

El total cuenta todo el primer nivel, incluidos los archivos que nunca son candidatos. Si los resúmenes, muestreadores y tablas de la corrida actual ya superan `M`, la carpeta se queda por encima de `M`: el bucle termina cuando se acaban los candidatos (`retention.py:65-80`), sin error, y `retention` aparece solo si se borró algo (`recording.py:348`). Nada avisa de que no se alcanzó el límite (confirmado por el código, no reproducido; límite conocido 8).
