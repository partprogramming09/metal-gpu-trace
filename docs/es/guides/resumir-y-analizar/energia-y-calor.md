# Energía y calor en los dos extremos de una corrida

**Lector:** personas que comparan dos grabaciones hechas en un Mac, y cualquiera que lea una nota `power` o un bloque
`machine.power` y quiera saber qué significa. Revisado el 2026-11-17.

English: [Power and heat at both ends of a run](../../../guides/summarizing/power-and-heat.md)

Volver al [índice de la guía](./index.md).

**En corto:** un Mac en modo de bajo consumo, o caliente, frena su chip para ahorrar energía o para enfriarse, y los
fotogramas se frenan con él. El grabador le pregunta al Mac dos cosas, una antes de que arranque el programa y otra al
terminar la grabación, y escribe las dos respuestas en el resumen. Si dos corridas empezaron en condiciones distintas, o
una cambió mientras se grababa, `perf_compare` lo dice, para que un chip más lento no se lea como un programa más lento.

## Un ejemplo primero

Dos corridas del mismo programa, con el mismo código. La corrida A empieza con el modo de bajo consumo apagado y el Mac
frío. La corrida B empieza con el modo de bajo consumo encendido. La B muestra menos fotogramas por segundo, y esa caída
no tiene nada que ver con el código. Ahora `perf_compare` añade un bloque `power` y este aviso: las corridas «se grabaron
con distinto modo de bajo consumo o estado térmico (el Mac baja sus relojes), así que los FPS y los ms de GPU no son
comparables».

Una grabación real de 30 segundos escribió este bloque ([E9](./evidencia.md#e9)):

```json
"power": {"start": {"low_power_mode": false, "thermal_warning": false},
          "end": {"low_power_mode": false, "thermal_warning": false}, "changed": false}
```

Va dentro de `machine`, junto al chip y la RAM, así que el resumen tiene `machine.power`. Las dos respuestas fueron «no»,
así que `changed` es `false` y `perf_compare` no añade nada.

## Cuáles son las dos preguntas

Dos comandos que vienen con macOS responden. No se instala nada para esto.

| Comando | Qué informa | Se convierte en |
|---|---|---|
| `pmset -g` (`pmset` es la herramienta de macOS para los ajustes de energía) | una línea `lowpowermode 1` o `lowpowermode 0` | `low_power_mode`: `true` o `false` |
| `pmset -g therm` (el estado térmico) | una línea con «warning level» cuando el Mac avisó de calor, y `CPU_Speed_Limit`, que es 100 cuando la CPU va a plena velocidad | `thermal_warning`: `true` cuando una línea de aviso no dice «no», o cuando `CPU_Speed_Limit` está por debajo de 100 |

Las reglas del código (`power_state`, `perf_report.py:653-668`):

- Un dato que el Mac no da es `null`, nunca una conjetura. Lo mismo si `pmset` falta o falla.
- Si `pmset -g therm` no muestra ni una línea `CPU_Speed_Limit` ni una de aviso, `thermal_warning` queda en `null`, no en `false`.

## Cuándo se preguntan las dos cosas

1. **Antes de que arranque el programa**: `record_run` llama a `power_state()` (`recording.py:386`) antes de que corra
   `perf_record.sh`.
2. **Después de escribir el resumen**: `record_run` la llama otra vez, y `power_block` pone las dos lecturas en
   `machine.power` (`recording.py:438-439`, `perf_report.py:672-676`).

El bloque existe solo si el resumen tiene un bloque `machine`. `machine` es `null` en el JSON cuando este Mac no es el que
grabó la traza (su RAM o su versión de macOS difieren de las del dispositivo de la traza) o cuando un dato de la máquina no
se puede leer (`machine_info`, `perf_report.py:679`). Entonces tampoco hay `power`.

## Qué significa `changed`

`changed` es `true` solo cuando un dato se conoce en los dos extremos y las dos lecturas difieren. Un `null` en un extremo
nunca cuenta, así que un dato que no se pudo leer no hace ver una corrida como inestable (`perf_report.py:676`). Ejemplo:
`low_power_mode` `false` al inicio y `null` al final deja `changed` en `false`.

## Qué hace perf_compare con esto

`compare_summaries` (`analysis.py:191-203`) lee el `machine.power` de las dos corridas. Añade la clave `power` solo cuando
los dos resúmenes tienen el bloque y se cumple una de dos cosas:

| Condición | Aviso en la respuesta | `changed_in` |
|---|---|---|
| Al empezar, las dos corridas difieren en modo de bajo consumo o en `thermal_warning` (ambos conocidos) | «las corridas se grabaron con distinto modo de bajo consumo o estado térmico (el Mac baja sus relojes), así que los FPS y los ms de GPU no son comparables; grabar ambas con el modo de bajo consumo apagado y el Mac frío» | aparece si además una corrida cambió mientras se grababa |
| Al empezar coinciden, pero una corrida cambió mientras se grababa | «el modo de bajo consumo o el estado térmico cambió durante una grabación (changed_in): la corrida no es estable, repetirla» | el nombre de esa corrida (`a` o `b`) |

Si ocurren las dos cosas, se escribe el primer aviso. La clave siempre guarda `a` y `b` (las lecturas del inicio), así que
quien lee puede ver qué dato difería. Un resumen sin la clave `power` (una corrida antigua, una corrida de Windows, una
corrida cuyo `machine` era `null`) no recibe aviso. Sin aviso significa «no medido», no «sin calor».

## En qué se diferencia de thermal_state_share

`thermal_state_share` es un registro completo: el tiempo que el Mac pasó en cada estado térmico durante la grabación, leído
de la tabla `device-thermal-state-intervals` (`perf_report.py:782-790`). `machine.power` son solo dos lecturas. Usa
`thermal_state_share` para ver una bajada de velocidad en medio de la corrida; usa `power` para saber si el Mac llegó ya
lento a la corrida.

## Diagrama

El flujo desde las dos lecturas hasta el aviso: fuente HTML `docs/diagrams/energia-en-los-dos-extremos.html` (PNG pendiente
de exportar).

## Límites

- **Solo dos lecturas.** Un período de bajo consumo o de calor que empieza y termina dentro de la corrida no lo ve `power`;
  solo lo cubre `thermal_state_share`.
- **Solo macOS.** Un resumen de Windows no tiene bloque `machine`, así que no tiene `power` ([guía de datos](../datos-y-su-ciclo-de-vida/claves-del-resumen.md)).
- **Depende del texto que imprime `pmset`.** Una versión de macOS que lo redacte de otra forma da `null`, no un error. No
  comprobado en otras versiones de macOS (no verificado).
- **La regla de aviso lee una línea de texto.** El código ignora una línea que contiene «no » (por ejemplo «No thermal
  warning level»). Si una versión de macOS redacta un aviso de otra forma, se pierde (probable; no reproducido).
- **Solo se vio el caso `false` en una grabación real.** El caso `true` (modo de bajo consumo encendido, un aviso) lo cubren
  pruebas, no una grabación real. Pendiente de evidencia: no se dio la salida de esas pruebas para esta página.

## Por qué tiene esta forma

| Decisión | Motivo | Alternativas descartadas |
|---|---|---|
| Dos lecturas, una antes y otra después de la grabación | La pregunta es en qué estado empezó y terminó el Mac; dos momentos la responden sin una tabla extra | Alternativas no anotadas para este cambio: pendiente de confirmar |
| Dos comandos integrados, sin biblioteca | `pmset` viene con macOS; `subprocess` está en la biblioteca estándar | No anotadas: pendiente de confirmar |
| `null` para un dato que no se puede leer | Una conjetura haría que `perf_compare` culpe a una corrida por un estado que nadie midió | Un valor por defecto `false`: ocultaría un dato que nunca se leyó |

## Evidencia

Nada de este cambio se volvió a ejecutar para esta página. Las filas de abajo son lo que la sesión dio, con lo que falta
marcado. La tabla completa está en [Evidencia](./evidencia.md#e9).

| Qué muestra | Comando | Salida |
|---|---|---|
| Una grabación de 30 segundos: los dos extremos en false, `changed` en false | pendiente de evidencia: el comando que hizo la grabación de 30 segundos (no se dio) | el JSON de arriba, tal como se dio |
| El aviso `power` de `perf_compare` sobre dos corridas que difieren | pendiente de evidencia: la llamada a `perf_compare` sobre dos corridas distintas (no se dio) | no se dio |
