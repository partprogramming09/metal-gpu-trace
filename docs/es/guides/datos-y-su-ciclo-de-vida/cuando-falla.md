# Cuando falla

**Lector:** personas que depuran una grabación que se paró a medias o una carpeta con restos raros. Revisado el 2026-11-16.

English: [When it fails](../../../guides/data-and-lifecycle/when-it-fails.md)

> **En corto:** casi todos los fallos limpian tras de sí. Las excepciones son un script matado sin oportunidad de limpiar,
> una tabla cortada y una corrida que no hizo trabajo de GPU. Para cada fallo: qué queda en disco y quién lo borra.

Volver al [índice](./index.md). Ejemplo: cancela una grabación de 60 s en el segundo 10 y no queda nada de esa corrida, ni el candado; mata el script con `SIGKILL` y quedan un `recording.lock` viejo y archivos parciales.

| Qué falla | Qué queda en disco | Quién lo limpia | Línea |
|---|---|---|---|
| El cliente cancela o la grabación pasa su plazo | Nada: el servidor mata el grupo de procesos y el programa, suelta el candado y borra los archivos nuevos de la corrida y los temporales `.ktrace` nuevos | el servidor | `recording.py:396-413` |
| El script sale con error, o recibe `TERM` | Nada de esa corrida: la trampa `EXIT` borra `$out/$name.*` si el código no es 0 | el script | `perf_record.sh:71`, `:74` |
| El servidor muere a mitad de grabación | La grabación y su programa los para un bucle vigilante del script | el script | `perf_record.sh:82-92` |
| El script muere con `SIGKILL` (no corre ninguna trampa) | Un `recording.lock` viejo, archivos parciales | El siguiente script toma un candado cuyo dueño está muerto (`preflight` no rechaza por eso); los parciales siguen hasta que `KEEP_RUNS` o la cuota los alcance | `perf_record.sh:47-61`, `preflight.py:74-98` (probable: no reproducido) |
| El programa no hizo trabajo de GPU | Se borran el resumen y todos los archivos; el `.trace` se queda si se pidió conservarlo, y el error lo dice | el servidor | `recording.py:427-436` |
| Se interrumpe la escritura de una tabla | `<table>.csv.gz.<hex>.tmp`; su nombre empieza con el stem de la corrida, así que `KEEP_RUNS` lo borra con ella; la cuota no (su sufijo no es de tabla) | `KEEP_RUNS` | `tables.py:40-43`, `retention.py:10` |
| Un `.csv.gz` está cortado o vacío | Un error que dice que grabes de nuevo, no una tabla corta | nadie: el archivo se queda | `tables.py:29-30`, [ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md) |
| Hace falta una tabla podada (`perf_compare` con `skip_s`) | «has no per-frame file; record it again» | nadie | `analysis.py:510` |
| El disco está casi lleno | Se rechaza antes de empezar: hacen falta `2 + (seconds × 8 + 9) / 10` GB (división entera) libres en la carpeta temporal y la de corridas; `PERF_MIN_FREE_GB` lo cambia | nadie | `perf_record.sh:34-38`, `preflight.py:128-131` |

El comentario de `perf_record.sh:33` explica la cifra de disco: los temporales de Instruments llegan a unos 0,8 GB por segundo grabado, y se midieron 48 GB en 60 s de Wine D3D12. Es un comentario del código, no una medición hecha para esta página (**probable**).
