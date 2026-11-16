# Límites conocidos y tocarlo sin romperlo

**Lector:** personas que planifican un arreglo en esta zona o la cambian. Revisado el 2026-11-16.

English: [Known limits and touching it without breaking it](../../../guides/data-and-lifecycle/limits.md)

> **En corto:** once comportamientos sorprendentes del código de hoy. Nueve siguen abiertos y anotados; dos (los límites 1
> y 6) se arreglaron el 2026-11-16 y siguen listados con sus commits. Después vienen las reglas para cambiar la zona de
> datos sin romper grabaciones antiguas, la limpieza o la privacidad de los resúmenes compartidos.

Volver al [índice](./index.md). Ejemplo: el límite 6 era que `KEEP_RUNS=2` borraba el `.trace` grande de una corrida vieja, aunque el [ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md) diga que nunca poda un `.trace` conservado; el arreglo (24490ec) hace que el código cumpla el ADR.

## Límites conocidos

| # | Límite | Dónde | Estado |
|---|---|---|---|
| 1 | Una clave `profile` en un archivo de proyecto sigue rechazándose: es el contrato desde la 0.26.0 (figura como quitada en `CHANGELOG.md`). El error ahora dice que se quitó y que la borres, pero solo cuando `profile` está entre las cinco primeras claves desconocidas que lista (9b66165) | `project.py:43-47` | Arreglado el 2026-11-16 (commits 2720b23, 9b66165); si volver a aceptarla sigue abierto |
| 2 | Los archivos `.presentmon.csv` nunca cuentan para la cuota y esta nunca los borra | `retention.py:43` | Confirmado |
| 3 | La caché no tiene limpieza; 5 de sus 8 carpetas son versiones fijadas antiguas (308 MiB) | `workloads.py:22`, E8-E10 | Confirmado |
| 4 | Un resumen cuyo `.trace` ya no está es normal: `trace` es solo el nombre y el archivo se borra por defecto; `perf_runs` informa `trace_kept` | `perf_report.py:650`, `perf_record.sh:163`, `analysis.py:79`, E5 | Confirmado |
| 5 | `panel.json` se sigue omitiendo en todas partes aunque el panel ya no existe | `paths.py:10`, `retention.py:7`, `prune_runs.sh:3` y `:9`, `perf_record_windows.py:508`, `analysis.py:52` | Confirmado; el comentario dice «drop this in a later version» |
| 6 | `KEEP_RUNS` borraba el `.trace` de una corrida vieja, porque `${old:r}.*` abarcaba `<run>.trace`, contra el [ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md) («never prunes a kept `.trace`»). Ahora el patrón excluye `*.trace` y el `clean_runs` de Windows lo salta; solo `METAL_TRACE_MAX_DISK_MB` libera un `.trace` | `prune_runs.sh:10`, `perf_record_windows.py:515` | Arreglado el 2026-11-16 (commit 24490ec). E6 midió el patrón antiguo, antes de 24490ec |
| 7 | Un `.trace` sin `.json` nunca lo cuenta `KEEP_RUNS`, así que tampoco lo borra: una grabación sin trabajo de GPU, con `deep` o `KEEP_TRACE=1`, y una corrida vieja cuyo `.json` ya quitó `KEEP_RUNS`. `perf_runs` no lo lista. Solo `METAL_TRACE_MAX_DISK_MB` lo borra; con esa variable sin fijar (por defecto) se queda en disco | `recording.py:427-433`, `prune_runs.sh:10` | Confirmado por el código |
| 8 | El límite de disco puede ser inalcanzable y no dice nada | `retention.py:65-80`, `recording.py:348` | Confirmado por el código |
| 9 | El resumen se reescribe con una escritura no atómica | `perf_report.py:836`, `recording.py:350` | Confirmado por el código |
| 10 | Una grabación a mano y otra del servidor usan carpetas distintas por defecto | `config.py:16`, `perf_record.sh:28-29` | Confirmado |
| 11 | No hay aquí un resumen real de generación 2 o 3 con el que comparar las listas de claves | E3 | No reproducido |

E3, E5, E6 están en [Evidencia E1 a E7](./evidencia-corridas.md); E8 a E10 en [Evidencia E8 a E12](./evidencia-cache-y-flujo.md).

## Tocarlo sin romperlo

- **Una clave nueva del resumen:** escríbela con las otras de su grupo, di en las [tablas de claves](./claves-del-resumen.md) si es siempre presente o condicional, y si es de ambas plataformas ponla en `common` con `metrics.common_block` y la prueba de lista de claves actualizada (`test_common_block_has_the_same_keys_on_both_platforms`, `tests/test_analysis.py:878`). Quien lee nunca debe dar por hecha una clave condicional.
- **Un tipo de archivo nuevo en la carpeta de corridas:** dale el stem de la corrida para que `KEEP_RUNS` lo borre con ella, y decide si `retention.kind_of` lo lista; si no, la cuota nunca podrá liberar su espacio (límite 2).
- **Una regla de retención nueva:** mantén los dos mecanismos separados; si un cambio necesita ambos, actualiza las dos columnas de la tabla de [Retención](./retencion.md).
- **Una tabla:** escríbela con `tables.write`, léela con `tables.find` y `tables.open_text`; nunca abras un `.csv` directamente, o se romperán las corridas de antes o de después de la 0.27.0.
- **Leer un archivo de la carpeta de corridas:** por `paths.read_object` o `paths.read_text`, para no seguir nunca un enlace.
- **Un resumen compartido** no debe llevar nombre de máquina, UUID ni ruta absoluta.
