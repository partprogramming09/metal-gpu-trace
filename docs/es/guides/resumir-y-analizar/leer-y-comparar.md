# Leer y comparar

**Lector:** personas que usan `perf_compare`, `perf_check`, `perf_gate` y compañía y quieren saber qué hace cada una de verdad, o que cambian `analysis.py`. Revisado el 2026-11-16.

English: [Reading and comparing](../../../guides/summarizing/reading-and-comparing.md)

**En corto:** cuando ya hay resúmenes, `analysis.py` los lista, compara dos, construye un «rango normal» con varias corridas
iguales y revisa una corrida nueva contra él. Comparar solo dice qué se movió; revisar (check) dice mejor, peor o igual; un
gate es una vara fija. Lo que falta sigue siendo «desconocido» y nunca se vuelve cero.

Volver al [índice de la guía](./index.md). Las líneas son de `analysis.py` salvo que se nombre otro archivo. Ninguna herramienta de aquí se ejecutó ([índice](./index.md#como-leer-las-etiquetas)); los números se evalúan a mano en [E6 y E7](./evidencia.md#e6).

## Encontrar y leer una corrida

`perf_runs` lista los `*.json` de la carpeta de corridas, del más nuevo al más viejo, saltando `baselines.json`, el antiguo `panel.json` (`:51-62`) y un archivo que aún se escribe o que no es un resumen (`:80-81`). Un nombre debe ser letras, dígitos, `.`, `_`, `-`; un enlace nunca se sigue (`paths.run_path` `paths.py:33-41`, `paths.read_object` `:54-66`). Toda herramienta que lee un resumen va envuelta por `reads_recordings` (`:37-48`): un resumen cuyas secciones tienen el tipo equivocado (edición a mano, otra versión) se vuelve un `ToolError` que nombra el tipo de error y nunca una ruta. Los resúmenes viejos tienen menos claves: `metrics.schema_of` dice de qué generación es (`metrics.py:13-16`) y la comparación dice «summaries written before version 0.4.0 have no encoder numbers» en vez de fallar (`:223-227`).

## `skip_s`: el régimen estable

Ejemplo: un programa que compila shaders en sus primeros 3 segundos parece lento si esos segundos cuentan. `steady_summary(run, skip_s)` (`:552-599`) con `skip_s > 0` lee `frames.csv`, conserva los fotogramas que empiezan al menos `skip_s` segundos después del primero y recalcula **desde esos fotogramas**:

| Se recalcula o no | Cómo |
|---|---|
| `frames`, `frame_gpu_ms`, `frame_interval_ms`, `fps_estimate`, los mínimos, stutter, jitter | se recalculan con el mismo `perf_report.frame_pacing` (`:573`) |
| la cuenta de hitches | intervalos sobre el `threshold_ms` guardado, con tolerancia de 0.002 ms porque `frames.csv` redondea los inicios a 0.001 ms (`:503`, `:577`) |
| el `peak` de memoria Metal | se recalcula desde los fotogramas conservados |
| `gpu.start_latency_ms`, `thermal_state_share`, `process_rss_mib`, `encoders`, `gpu_idle`, `gpu_counters` | quedan de toda la corrida; `steady.whole_run` los lista (`:598`) |
| bloque `cpu`, `throttling_analysis` | se descartan (`:569`, `:592`) |
| **causas** de hitch | solo para los 20 que lista el resumen; `causes_partial` avisa si hubo más (`:579-586`) |

Con menos de 2 fotogramas se niega: `<run> has under 2 frames after the first N s; use a smaller skip_s` (`:565-566`). `skip_s` va de 0 a 600 (`paths.py:118-126`). `suggested_actions` propone uno por sí misma: cuando cada hitch `shader_compile` entre los 20 más largos termina en el primer cuarto de la corrida, sugiere los segundos enteros que los cubren (`_startup_skip_s`, `:670-690`; pruebas `tests/test_analysis.py:1162-1180`, no se ejecutaron).

## `perf_compare`

`compare_summaries` (`:166-242`) calcula, para 11 números, `change(a, b)`: `b - a` redondeado a 3 decimales y `100 × change / a` redondeado a 1 (`:392-396`), `None` si falta un valor. Los 11: FPS, los dos mínimos, stutter, jitter, ms de GPU medios y p95, intervalo p95, latencia de inicio p50, MiB Metal pico, RSS pico (`:168-180`). **No decide nada**: dice qué se movió y añade todo lo que podría volver el movimiento sin sentido:

| Clave | Aparece cuando | Línea |
|---|---|---|
| `too_short` | una corrida tiene menos de 100 fotogramas | `:187` |
| `layer`, `context` | las corridas difieren en capa de traducción, commit o versión de Instruments ([guía de grabación](../grabar/recorrido-macos.md#que-identifica-una-corrida)) | `:188` |
| `unpresented`, `noisy_environment` | una corrida dejó de presentar; una corrida se marcó ruidosa | `:189-191`, `:192-194` |
| `screen` | una corrida se grabó con la pantalla bloqueada y la otra no | `:195-200` |
| `tier` | los niveles difieren (una corrida `light` no tiene memoria) | `:201-205` |
| `gpu_state` | el nivel de rendimiento ponderado por tiempo difiere en 0.25 o más (0 todo Minimum, 1 todo Medium, 2 todo Maximum): el mismo trabajo tarda más ms de GPU en un estado más bajo | `:206-211`, `:141-146` |
| `memory_pressure` | ambas midieron la memoria igual (su cambio), o una nota de que no | `:212-214`, `:149-163` |
| `measure` | una corrida de Windows contra una de Metal: los ms de GPU y la memoria Metal no se restan, los encoders son «not comparable» y la función vuelve antes de tiempo | `:215-222` |
| `encoders` y `labels` | ambos son resúmenes Metal con encoders: encoders y command buffers por fotograma, parte de encoders cortos, parte ociosa (las partes cambian en puntos, nunca en %, porque de 1.9 % a 49.7 % se leería +2516 %, `:239-240`), y la cuenta y los ms de GPU por fotograma de cada etiqueta, el mayor cambio primero, hasta 20 | `:223-242`, `:399-421` |

`short_us` debe ser 10, 25, 50, 100, 250, 500 o 1000 (`:228-230`). Con `markdown` verdadero el resultado trae también una tabla para un pull request (`:85-102`), y `suggested_actions` lista qué llamar después para cada corrida (`:125-126`). Una etiqueta ausente de un resumen puede haber caído solo fuera de su top 20, así que es `outside_top_20` sin cambio, no `new` ni `gone` (`:399-421`).

## Líneas base: un rango, no una corrida

`perf_baseline name runs` (`:259-293`) guarda **copias de los resúmenes** (así la referencia sobrevive a `KEEP_RUNS`) en `baselines.json` con la fecha, reemplazando una referencia del mismo nombre, y devuelve por métrica revisada el `range` (valor mínimo y máximo entre las corridas, `None` si una corrida no tiene la métrica; `ranges`, `:296-307`) y el `spread_pct`: `200 × (max - min) / (max + min)`, el ancho como porcentaje del punto medio (`spreads`, `:310-314`), «el ruido de este programa en esta máquina, que un cambio debe superar» (`:264-265`). Se revisan cuatro métricas: `fps`, `gpu_ms_mean` y el p50 de encoders y de command buffers por fotograma (`CHECKED`, `:246-251`). El código acepta una sola corrida (rango de un punto, spread 0); `CHANGELOG.md` dice «idealmente 3 o más». El archivo se describe en la [guía de datos](../datos-y-su-ciclo-de-vida/proyecto-y-configuracion.md#el-archivo-de-proyecto-la-marca-y-las-lineas-base). Informa `unpresented` y `noisy_environment` de sus corridas (`:288-292`), así que una mala referencia se ve.

## `perf_check`: el veredicto

`judge(metric, value, span, margin_pct)` (`:317-330`): donde más es peor (ms de GPU, las cuentas), `worse` si `value > span.max × (1 + margin)`, `better` si `value < span.min × (1 - margin)`, si no `same`; para FPS los lados se invierten. El margen es `margin_pct / 100` (por defecto **3**, `:334`) para FPS y ms de GPU, y **0** para las dos cuentas `_p50` (`:325`): una cuenta de encoders es exacta y un encoder más por fotograma es un cambio. Luego (`:351-368`): una métrica que falta en la corrida o en la referencia es `unchecked`; si un lado es Windows y el otro Metal, solo se juzgan los FPS (`cross`, `:350-354`); el veredicto es **`regressed` si alguna métrica es peor, `improved` si alguna es mejor y ninguna peor, `same` si no** (`:368`).

La respuesta lleva `regressed` y `improved` (métrica, valor y rango de cada una), `unchecked`, el `range` y el `perf_compare` completo de la *primera* corrida de la referencia contra esta (`:369-371`). El ritmo de fotogramas, los encoders cortos y el tiempo ocioso están en la comparación pero **nunca deciden**: «varían demasiado entre corridas iguales» (13 % y 7 puntos en el changelog, `:338-340`). El 3 % es un valor por defecto que eligió el proyecto (**no verificado** como medido; los spreads de 4.4 % y 6.1 % del [índice](./index.md#por-que-esta-parte-tiene-esta-forma) son la razón de que la referencia sea un rango); `perf_check` **no lee** el `spread_pct` de la línea base ([límite 8](./limites.md)). Prueba: `test_judge_matches_perf_check` (`tests/test_analysis.py:342`, no se ejecutó) fija que `judge` dice `worse` exactamente para las métricas que `perf_check` lista como regresadas, y `better` para las que lista como mejoradas.

## `perf_gate`: una vara, no una referencia

`perf_gate` (`:471-500`) revisa presupuestos fijos: `fps_min`, `fps_1pct_low_min`, `stutter_rate_pct_max`, `gpu_ms_p95_max`, `hitches_max`, `metal_mib_max` (`GATES`, `:466-468`); se exige al menos uno. Un presupuesto es `ok` solo si el valor existe y está del lado correcto: `ok = value is not None and (value >= limit if min else value <= limit)` (`:490`). La respuesta es `pass` solo si todos se cumplen **y** la corrida no tiene `unpresented` (`:493`). Usa un gate para una vara que un cambio debe superar; `perf_check` para «¿este cambio lo movió más allá de lo que hacen corridas iguales?».

## `perf_history` y `perf_diagnose`

`perf_history prefix` lista las corridas cuyo nombre empieza por el prefijo, de la más vieja a la más nueva, con seis números y el cambio de la primera a la última (`:437-462`). Marca una serie que mezcla Windows y Metal y dice «under 3 runs: not a trend yet» (`:458-461`); toma una tendencia por real solo si supera el `spread_pct` de corridas iguales (`:440-441`).

`perf_diagnose` (`:693-820`) es una lectura por reglas de un resumen: **una heurística, y su texto no está en inglés**: las recomendaciones son frases en español (`:756-807`), lo único en español de la salida de las herramientas.

| Salida | Regla (los umbrales están en el código) | Línea |
|---|---|---|
| `stutter_analysis.verdict` | `UNKNOWN` sin el número de stutter; `SEVERE_STUTTER` sobre 7 %; `MICRO_STUTTER` desde 2 %; si no `SMOOTH` | `:720-727` |
| `bottleneck` | `MEMORY_PRESSURE_SUSPECTED` si la varianza es alta (jitter de al menos 3 ms, o p95 menos p50 del intervalo de al menos 5 ms) y el conjunto de trabajo es de al menos 1500 MiB; `UNKNOWN` sin `idle_share`; `CPU_SUBMISSION_BOUND` si `idle_share >= 0.25` (o `>= 0.20` con demasiados encoders cortos); `GPU_BOUND` si `idle_share <= 0.15` y los ms de GPU son al menos el 80 % del intervalo; si no `BALANCED` | `:737-752` |
| `too_many_short_encoders` | encoders por fotograma p50 de al menos `min_encoders` (4) **y** la parte bajo `short_us` de al menos `short_share` (0.25) | `:711` |

Los valores por defecto «salen de bgfx 17-drawstress en un M1 Pro: 7 encoders por fotograma y 50 % bajo 25 µs bajo Mullion, 2 y 2 % en Metal nativo» (`:698-699`). El veredicto de memoria es una inferencia («el ancho de banda de memoria no se mide», `:742`). A mano sobre las dos corridas reales ([E7](./evidencia.md#e7)): `SMOOTH` (0.29 %) y `MICRO_STUTTER` (2.63 %), ambas `CPU_SUBMISSION_BOUND` por la regla (**probable**, herramienta no ejecutada). `perf_memory_breakdown` (`:823-870`) solo reordena el bloque `resource_allocations` y calcula razones (`live_share_pct`, `allocated_mib_per_live_mib`).

## Cuando falta un número

| Lector | Un número que falta se vuelve |
|---|---|
| `compare_summaries` | `change(None, None)`: `a` y `b` en `None` cuando la clave no está (`:182-186`) |
| `perf_check` | `unchecked`; `hint_unchecked` dice que un resumen anterior a 0.4.0 no tiene números de encoders (`:359-361`, `:382-383`) |
| `perf_gate` | el presupuesto **falla** (`value` nulo, `ok` falso): «un gate no debe pasar con datos que faltan» (`:476-477`, `:490`) |
| `perf_history` | `null` en la fila (`dig`, `:424-428`) |
| `perf_diagnose`, una corrida corta | veredictos `UNKNOWN` (`:720-721`, `:744-745`); `fps_1pct_low` y `fps_01pct_low` son `None` (`perf_report.py:264`) |
