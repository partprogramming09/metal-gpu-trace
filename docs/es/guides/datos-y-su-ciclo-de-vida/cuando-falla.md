# Cuando falla

**Lector:** personas que depuran una grabación que se paró a medias o una carpeta con restos raros. Revisado el 2026-11-16.

English: [When it fails](../../../guides/data-and-lifecycle/when-it-fails.md)

> **En corto:** casi todos los fallos limpian tras de sí: el script o el servidor borran los archivos de la corrida
> fallida. Las excepciones son un script matado sin oportunidad de limpiar, una tabla cortada y una corrida que no hizo
> trabajo de GPU. Esta página lista, por cada fallo, qué queda en disco y quién lo borra.

Volver al [índice](./index.md). Ejemplo: cancela una grabación de 60 s en el segundo 10 y no queda nada de esa corrida,
ni siquiera el candado; mata el script con `SIGKILL` y quedan un `recording.lock` caducado y archivos parciales.

| Qué sale mal | Qué queda en disco | Quién lo limpia | Línea |
|---|---|---|---|
| El cliente cancela o la grabación pasa su plazo | Nada: el servidor mata el grupo de procesos, el programa, suelta el candado y borra los archivos nuevos de la corrida y los `.ktrace` temporales nuevos | el servidor | `recording.py:396-413` |
| El script sale con error | Nada de esa corrida: la trampa `EXIT` borra `$out/$name.*` si el código no es 0 | el script | `perf_record.sh:71` |
| El script recibe `TERM` | Lo mismo | el script | `perf_record.sh:74` |
| El servidor muere a mitad de grabación | La grabación y su programa los detiene un bucle vigilante dentro del script | el script | `perf_record.sh:82-92` |
| Se mata el script con `SIGKILL` (no corre ninguna trampa) | Un `recording.lock` caducado, archivos parciales de la corrida | El siguiente script toma por encima un candado cuyo dueño está muerto; `preflight` no rechaza por un dueño muerto. Los archivos parciales se quedan hasta que `KEEP_RUNS` o la cuota los alcancen | `perf_record.sh:47-61`, `preflight.py:74-98` (probable: no reproducido) |
| El programa no hizo trabajo de GPU | Se borran el resumen y todos los archivos de la corrida; el `.trace` se queda si se pidió conservarlo, y el error lo dice | el servidor | `recording.py:427-436` |
| Se interrumpe la escritura de una tabla | `<table>.csv.gz.<hex>.tmp`. Su nombre empieza con el stem de la corrida, así que `KEEP_RUNS` lo borra con la corrida; la cuota no (su sufijo no es de tabla) | `KEEP_RUNS` | `tables.py:40-43`, `retention.py:10` |
| Un `.csv.gz` está cortado o vacío | Un error que dice que grabes de nuevo, no una tabla corta | nadie: el archivo se queda | `tables.py:29-30`, [ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md) |
| Hace falta una tabla podada (`perf_compare` con `skip_s`) | Un mensaje «has no per-frame file; record it again» | nadie | `analysis.py:510` |
| El disco está casi lleno | Se rechaza la grabación antes de empezar: hacen falta `2 + (seconds × 8 + 9) / 10` GB libres (división entera) en la carpeta temporal y en la de corridas; `PERF_MIN_FREE_GB` lo cambia | nadie | `perf_record.sh:34-38`, `preflight.py:128-131` |

El comentario de `perf_record.sh:33` explica la cifra de disco: los temporales de Instruments llegan a unos 0,8 GB por
segundo grabado, y se midieron 48 GB para 60 s de Wine D3D12. Es un comentario del código, no una medida hecha para
esta página (**probable**).
