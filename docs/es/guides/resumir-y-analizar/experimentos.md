# Los experimentos

**Lector:** personas que ejecutan `perf_baseline_record`, `perf_ab`, `perf_cold_warm` o `perf_sweep`, o que cambian `experiments.py`. Revisado el 2026-11-16.

English: [The experiments](../../../guides/summarizing/experiments.md)

**En corto:** una sola medida de un programa no es de fiar, porque corridas iguales difieren un poco por sí solas. Los
experimentos graban el programa varias veces en un orden planeado y luego usan los lectores de la página anterior para decir
si una diferencia es real. Cada corrida tarda minutos, así que se usan a propósito.

Volver al [índice de la guía](./index.md). Las líneas son de `experiments.py` salvo que se nombre otro archivo.

`experiments.py` graba varias corridas y llama a los lectores de [Leer y comparar](./leer-y-comparar.md). Cada grabación pasa por `record_new_summary` (`recording.py:440-449`), que llama a `perf_record` y relee el único resumen que escribió, así que cada corrida es una corrida normal con una etiqueta normal. Las cuatro comparten `cooldown_s` (0 a 600 s, descansos entre dos grabaciones, nunca antes de la primera ni después de la última; una llamada cancelada termina el descanso; `recording.py:240-249`, `paths.py:102-115`) y aceptan los argumentos de `perf_record`. Cada grabación tarda sus segundos más cerca de un minuto de relectura (docstrings), y el candado de grabación deja correr una sola a la vez ([guía de grabación](../grabar/reglas.md#una-grabacion-a-la-vez)).

| Herramienta | Qué graba | Qué devuelve | Límites | Línea |
|---|---|---|---|---|
| `perf_baseline_record` | el mismo programa `count` veces seguidas, corridas `<name>-1`, `-2`, ... | la línea base: rango y `spread_pct` (termina en `perf_baseline`) | `count` de 1 a 10 | `:9-27`, `:20` |
| `perf_ab` | dos entornos en el orden **A B B A**, repetido `rounds` veces; corridas `<name>-a1`, `-b1`, `-b2`, `-a2`, ... | por métrica (FPS, 1 % low, ms de GPU, stutter) los valores de cada lado y un veredicto | `rounds` de 1 a 5 (4 a 20 grabaciones) | `:48-69`, `:202-222` |
| `perf_cold_warm` | el mismo programa dos veces: `<name>-first` y `<name>-second` (solo macOS) | hitches y causas de cada corrida y `first_seen_hitches` | ninguno | `:72-102` |
| `perf_sweep` | una vez por valor de una variable (`dim`, `example`, `api`, `size` o `env:NAME`), los valores hacia delante en una ronda y hacia atrás en la siguiente | por valor la mediana de las cuatro métricas, y un ajuste de recta | 2 a 8 valores, `rounds` de 1 a 5, como máximo 24 grabaciones | `:141-199`, `:117-138` |

## Por qué A B B A

Un portátil se calienta mientras graba. Hacer A, B, A, B pone cada B en una máquina más caliente que la A anterior; A B B A pone una de cada en el inicio y una al final, así que la deriva lenta afecta a ambos lados por igual, y `rounds` repite el patrón (`:49-51`). El barrido invierte el orden de los valores cada dos rondas (`:161`). Que la deriva importa es afirmación del propio proyecto (el descanso existe «para que un portátil no haga throttling», `:13-14`); su tamaño **no se midió** para esta guía.

## Cómo decide `perf_ab`

`ab_verdict(a, b, higher_better)` (`:36-45`): `unknown` si algún lado no tiene valores; **better** si todo valor de `b` está por encima de todo valor de `a` (`min(b) > max(a)`) en una métrica donde más es mejor (FPS, 1 % low), o por debajo en una donde menos es mejor (ms de GPU, stutter); **worse** en el caso espejo; `same` en cualquier otro caso, incluido todo solapamiento.

Sin margen ni porcentaje: la **dispersión de las corridas A es la regla**, «para que la dispersión propia de una corrida nunca pase por un efecto» (`:37-38`). Con `rounds=1` cada lado tiene dos valores, así que la regla mide dos corridas de ancho. Un valor que una corrida no tiene (un 1 % low de una corrida corta, `None`) se deja fuera, así que un lado puede tener menos valores que corridas (`:213-215`). `too_short` es verdadero si alguna corrida tiene menos de 100 fotogramas (`:217-219`). A mano sobre las dos corridas reales, la primera como lado A y la segunda como B: FPS `a = [105.4]` y `b = [102.1]`, así que `max(b) < min(a)` y la regla da `worse` para una caída del 3 %, porque un valor no tiene dispersión. Es la aritmética de la regla, no una ejecución de la herramienta, y por eso una corrida por lado no es un experimento ([E6](./evidencia.md#e6)).

## Cómo decide `perf_cold_warm`

`cold_warm_report` (`:72-87`): `first_seen_hitches = max(0, hitches shader_compile de la primera - los de la segunda)` y `extra_hitches_in_first = max(0, hitches de la primera - hitches de la segunda)`. La pista dice que la caché de shaders de Metal **no se vacía** entre corridas, así que la primera es «fría» solo si los pipelines del programa no se habían construido antes. A mano sobre las dos corridas reales, nombradas como un par de `perf_cold_warm` (las etiquetas acaban en `-first` y `-second`; que las haya hecho la herramienta es **probable**): ambas tienen 0 hitches `shader_compile`, así que `first_seen_hitches` es 0; las cuentas de hitches son 6 y 4, así que `extra_hitches_in_first` es 2 ([E7](./evidencia.md#e7)), aunque los 4 de la segunda no se comparan con los 6 de la primera: su tramo presentado dura 2.3 s.

## Cómo ajusta `perf_sweep` una recta

Con al menos 3 valores numéricos (`dim` lo es; `size` no; `example` y `api` son nombres) ajusta ms de GPU por fotograma contra el valor por mínimos cuadrados (`line_fit`, `:105-114`): `slope = Σ(x - mx)(y - my) / Σ(x - mx)²`, `intercept = my - slope × mx`, `r² = 1 - residual / total`. Para `dim` la x es `dim³`, porque drawstress dibuja `dim³` cubos por fotograma (64 000 con `dim` 40, [guía de grabación](../grabar/programas-de-prueba.md#que-hay-en-la-lista-e4)), así que la pendiente son **ms por dibujo** y la ordenada el coste fijo (`:189-196`). Una variable con valores no numéricos no da ajuste (se captura `ValueError`, `:188-191`), y `line_fit` devuelve `None` cuando x nunca cambia (`:109-110`).

Pruebas: `test_baseline_record`, `test_perf_sweep`, `test_cold_warm` (`tests/test_analysis.py:170`, `:198`, `:269`) y las del descanso en `tests/test_recording.py:1398-1443` (no se ejecutaron). Un barrido real **no se reprodujo**: pide de 4 a 24 grabaciones.
