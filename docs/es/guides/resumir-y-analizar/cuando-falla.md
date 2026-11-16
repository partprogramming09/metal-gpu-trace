# Cuando falla

**Lector:** personas que ven un error de `perf_report.py`, `analysis.py` o `experiments.py` y quieren saber qué significa y qué queda atrás. Revisado el 2026-11-16.

English: [When it fails](../../../guides/summarizing/when-it-fails.md)

**En corto:** la mayoría de los fallos acaban en una frase clara que dice qué hacer (por ejemplo, «grábala de nuevo»). Unos
pocos no: una exportación lenta o cortada acaba en un volcado de error crudo. No queda nada a medio escribir en lo que
alguien pueda fiarse, salvo las corridas ya grabadas por un experimento que se detuvo a mitad.

Volver al [índice de la guía](./index.md).

| Qué sale mal | Qué recibe quien lee | Qué queda | Línea (`perf_report.py` salvo que se nombre otro) |
|---|---|---|---|
| El `.trace` ya se borró, no tiene `metal-gpu-intervals` o no tiene proceso lanzado ni adjuntado | los mensajes del [Paso 1](./del-trace-al-resumen.md#paso-1-exportar), del [Paso 2](./del-trace-al-resumen.md#paso-2-el-indice-y-missing_tables) y del Paso 3 de la misma página | nada nuevo | `:52-54`, `:194-196`, `:644-645` |
| `xctrace export` falla | `xctrace export of <name> failed (exit N): <última línea de stderr>` | los temporales de las demás exportaciones se borran | `:62-65`, `:106-110`, `:121-123` |
| El programa no hizo trabajo de GPU | se arma un resumen con `frames` 0 y sin FPS; desde una grabación, `recording.py` lo vuelve `the program did no GPU work ...` y borra la corrida | el `.trace` solo si se pidió | `recording.py:427-436` |
| `perf_report` sale con código distinto de cero en una grabación | `recording failed (exit N): <última línea>` | la trampa del script borra los archivos de la corrida | `perf_record.sh:5`, `:71`, [guía de grabación](../grabar/fallos.md#que-pasa-si-instruments-muere-a-mitad) |
| Una exportación agota el tiempo, o una tabla se corta a mitad de fila | un traceback de Python, no una frase ([límite 4](./limites.md)) | puede quedar un XML temporal ([límite 4](./limites.md)) | `:59`, `:166-168`, `:850` |
| Un resumen no es JSON válido, es un enlace o tiene una sección de tipo equivocado | `<run> is not valid JSON; record it again` / `<run> cannot be read` / `... not in the form the recorder writes (<ErrorType>)` | nada | `paths.py:54-66`, `analysis.py:37-48` |
| Falta una corrida, una referencia o un `frames.csv`, o `skip_s` deja menos de 2 fotogramas | `no run <name>; perf_runs lists them` (`paths.py:33-41`); `no reference <name>; perf_baseline with no arguments lists them` (`analysis.py:285`, `:345`); `<run> has no per-frame file; record it again`; `<run> has under 2 frames after the first N s; use a smaller skip_s` | | `analysis.py:510`, `:565-566` |
| Un experimento falla a mitad | el `ToolError` de la grabación que falló; **las corridas ya grabadas se quedan**, y no se escribe línea base, veredicto ni ajuste | las corridas anteriores, como corridas normales | `experiments.py:23-27`, `:64-69`, `:160-172` (sin `try`: confirmado por el código, **no reproducido**) |
| Un experimento se cancela mientras descansa | `cancelled while cooling down` y no empieza otra grabación | las corridas ya hechas | `recording.py:240-249` |
