# Ruido y veredictos

**Lector:** personas que deciden si un cambio de verdad volvió un programa más rápido o más lento. Revisado el 2026-11-17.

English: [Noise and verdicts](../../../guides/summarizing/noise-and-verdicts.md)

**En corto:** medir dos veces el mismo programa nunca da el mismo número. Por eso el proyecto no llama «real» a un cambio
hasta que cae fuera de lo que ya hacen corridas iguales. Cuatro herramientas se parecen y responden preguntas distintas; esta
página las pone lado a lado y lista los hábitos que evitan tomar el ruido por un efecto.

Volver al [índice de la guía](./index.md).

El [ejemplo de la guía](./index.md#un-ejemplo-primero) muestra por qué: contra `a2-proof-first` sola, la segunda corrida es `regressed` (102.1 bajo 102.238, aritmética a mano, [E6](./evidencia.md#e6)), pero dejó de presentar a los 3.6 s y un 3 % es poco frente a cuánto difieren corridas iguales ([índice](./index.md#por-que-esta-parte-tiene-esta-forma)); contra tres corridas iguales de la primera clase sería, muy probablemente, `same` (**especulación**).

| Herramienta | Referencia | Margen | ¿Una sola corrida? | Dice |
|---|---|---|---|---|
| `perf_compare` | una corrida | ninguno | sí | el cambio, y lo que podría volverlo sin sentido; **sin veredicto** |
| `perf_check` | el rango de N corridas | 3 % para FPS y ms de GPU (`margin_pct`), 0 para las cuentas | sí, contra N | `regressed`, `improved` o `same` |
| `perf_ab` | el rango de las corridas A de este experimento | ninguno | hacen falta 2 por lado como mínimo para que signifique algo | `better`, `worse`, `same` o `unknown` por métrica |
| `perf_gate` | un número que fijas tú | ninguno | sí | `pass` o falla por presupuesto |

![Ocho cajas en dos filas unidas por flechas. Fila de arriba: leer los resúmenes, perf_compare (cambios, sin veredicto), perf_baseline (el rango y la dispersión de corridas iguales) y la decisión de perf_check sobre cada métrica contra ese rango con un margen. Fila de abajo: el veredicto regressed, improved o same; perf_ab; perf_gate; y los avisos que nunca cambian un veredicto.](./img/comparar-y-juzgar.png)
*Figura 2. Cómo se compara y se juzga una corrida. Fuente HTML: `docs/es/guides/resumir-y-analizar/img/comparar-y-juzgar.html`.*

Qué hace el proyecto con el ruido, en el orden en que lo encuentras: **1 Repetir**: «Repite una corrida antes de llamar real a un cambio» (el `CLAUDE.md` del proyecto; el [índice de guías](../../../guides/index.md) lo dice igual); `perf_baseline_record` y A B B A repiten por ti. **2 Medir el ruido**: el `spread_pct` de una línea base es cuánto difieren corridas iguales. **3 Juzgar fuera del ruido**: el rango sustituye a la corrida suelta; el margen añade un colchón pequeño más allá. **4 Decir cuándo la corrida es sospechosa**: los avisos de `perf_compare` (`unpresented`, `noisy_environment`, `screen`, `power`, `gpu_state`, `tier`, `too_short`) son visibles y **no cambian el veredicto** de `perf_check`; solo `perf_gate` falla por `unpresented`. **5 Descansar**: `cooldown_s`, y una entrada de `suggested_actions` que propone 60 s de descanso cuando el Mac hizo throttling («60 s es un valor de partida, no una medida», `analysis.py:665-666`).
