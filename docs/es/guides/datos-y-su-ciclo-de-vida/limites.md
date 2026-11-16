# Límites conocidos y tocarlo sin romperlo

**Lector:** personas que planifican un arreglo en esta zona o la cambian. Revisado el 2026-11-16.

English: [Known limits and touching it without breaking it](../../../guides/data-and-lifecycle/limits.md)

> **En corto:** esta página lista once comportamientos del código de hoy que sorprenden pero están anotados, no
> arreglados. Después vienen las reglas para cambiar la zona de datos sin romper las grabaciones antiguas, la limpieza
> ni la privacidad de los resúmenes compartidos.

Volver al [índice](./index.md). Ejemplo: el límite 6 significa que `KEEP_RUNS=2` también puede borrar el `.trace` grande de
una corrida vieja, aunque el [ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md) diga que nunca poda un
`.trace` conservado.

## Límites conocidos

Cada punto es un límite del comportamiento de hoy, anotado, no arreglado aquí.

| # | Límite | Dónde | Estado |
|---|---|---|---|
| 1 | Se rechaza una clave `profile` en un archivo de proyecto. Es el contrato desde la 0.26.0 (la clave figura como eliminada en `CHANGELOG.md`), así que un archivo que aún la tenga debe quitarla | `project.py:43-46` | Confirmado; si se vuelve a admitir está abierto |
| 2 | Los `.presentmon.csv` no cuentan para la cuota y la cuota nunca los borra | `retention.py:43` | Confirmado |
| 3 | La caché no tiene limpieza; 5 de sus 8 carpetas son versiones fijadas antiguas (308 MiB) | `workloads.py:22`, E8-E10 | Confirmado |
| 4 | Un resumen cuyo `.trace` ya no existe es lo normal: `trace` es solo el nombre, el archivo se borra por defecto; `perf_runs` informa `trace_kept` | `perf_report.py:650`, `perf_record.sh:163`, `analysis.py:79`, E5 | Confirmado |
| 5 | `panel.json` se sigue omitiendo en todas partes aunque el panel ya no exista | `paths.py:10`, `retention.py:7`, `prune_runs.sh:3` y `:9`, `perf_record_windows.py:508`, `analysis.py:52` | Confirmado; el comentario dice «drop this in a later version» |
| 6 | `KEEP_RUNS` borra el `.trace` de una corrida más vieja, porque `${old:r}.*` coincide con `<run>.trace`. El [ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md) dice que `KEEP_RUNS` «never prunes a kept `.trace`», lo cual solo es cierto de un `.trace` sin `.json` | `prune_runs.sh:9`, E6 | El patrón está confirmado (E6); el borrado en sí no se reprodujo |
| 7 | Un `.trace` sin `.json` (una corrida que no hizo trabajo de GPU, `deep` o `KEEP_TRACE=1`) nunca lo ve `KEEP_RUNS`; solo lo borra la cuota | `recording.py:427-433`, `prune_runs.sh:9` | Confirmado por el código |
| 8 | El límite de disco puede ser inalcanzable y no dice nada | `retention.py:65-80`, `recording.py:348` | Confirmado por el código |
| 9 | El resumen se reescribe con una escritura no atómica | `perf_report.py:836`, `recording.py:350` | Confirmado por el código |
| 10 | Una grabación a mano y una del servidor van por defecto a carpetas distintas | `config.py:16`, `perf_record.sh:28-29` | Confirmado |
| 11 | No hay en esta máquina un resumen real de generación 2 o 3 con el que comparar las listas de claves | E3 | No reproducido |

Evidencia: E3, E5 y E6 están en [Evidencia E1 a E7](./evidencia-corridas.md); E8 a E10 en
[Evidencia E8 a E12](./evidencia-cache-y-flujo.md).

## Tocarlo sin romperlo

- Una clave nueva del resumen: escríbela donde se escriben las otras de su grupo, di en las [tablas de claves](./claves-del-resumen.md)
  si está siempre presente o es condicional y, si pertenece a las dos plataformas, ponla en `common` por medio de
  `metrics.common_block`, con la prueba de la lista de claves actualizada (`test_common_block_has_the_same_keys_on_both_platforms`,
  `tests/test_analysis.py:878`). Un lector nunca debe suponer una clave condicional.
- Un tipo de archivo nuevo en la carpeta de corridas: dale el stem de la corrida para que `KEEP_RUNS` lo borre con ella, y
  decide si `retention.kind_of` debe listarlo. Si no está listado nunca cuenta como borrable y la cuota no puede liberar
  su espacio (el límite 2 es justo eso).
- Una regla de retención nueva: mantén los dos mecanismos separados. Si un cambio necesita conocer los dos, actualiza las
  dos columnas de la tabla de [Retención](./retencion.md).
- Una tabla: escríbela con `tables.write` y léela con `tables.find` y `tables.open_text`; no abras un `.csv` directamente,
  o las corridas grabadas antes de la 0.27.0, o después, se romperán de un modo u otro.
- Todo lo que lea un archivo de la carpeta de corridas pasa por `paths.read_object` o `paths.read_text`, para que nunca
  se siga un enlace.
- Un resumen compartido no debe llevar nombre de máquina, UUID ni ruta absoluta.
