# Evidencia: los comandos y su salida real

**Lector:** personas que quieren comprobar un número de esta guía o repetir un comando. Revisado el 2026-11-16.

English: [Evidence](../../../guides/summarizing/evidence.md)

**En corto:** cada número de esta guía sale de un comando que se ejecutó sobre dos grabaciones reales, o de una fórmula del
código evaluada a mano con `jq`. Esta página guarda cada comando con su salida literal para que puedas repetirlo. Donde no
se pudo ejecutar una herramienta, la página lo dice.

Volver al [índice de la guía](./index.md).

Recogida el 2026-11-16 en un Mac con Apple silicon. Todos los comandos solo leen. La carpeta de corridas es `perf-runs/` del
clon (una carpeta local, ignorada, que no se publica; guarda las dos corridas de abajo). La sesión podía correr `rg`, `sed`,
`jq` y `awk` y no podía correr Python ni `xctrace`: ninguna herramienta de esta guía se ejecutó, y E3, E6 y E7 son las
fórmulas del código evaluadas a mano. Lo que no se reprodujo está en [Límites conocidos](./limites.md#lo-que-no-se-reprodujo).

## E1 Las tablas, los trabajadores, los umbrales y los mensajes de error {#e1}

```text
$ rg -n '^MEMORY =|^TABLES =|^OPTIONAL =|^COUNTER_TABLES =|^EXPORT_WORKERS =|^STUTTER_FLOOR_MS =|^UNPRESENTED_' src/metal_gpu_trace/perf_report.py | cut -c1-120
33:MEMORY = "metal-current-allocated-size"
34:TABLES = ("metal-gpu-intervals", MEMORY, "gpu-performance-state-intervals")
36:OPTIONAL = ("metal-application-encoders-list", "graphics-compiler-activity-intervals", "device-thermal-state-interval
40:EXPORT_WORKERS = 2
42:COUNTER_TABLES = ("gpu-counter-info", "gpu-counter-value")
201:UNPRESENTED_MIN_BUFFERS = 32
202:UNPRESENTED_FACTOR = 8
203:UNPRESENTED_MIN_S = 1.0
250:STUTTER_FLOOR_MS = 8.0

$ rg -n 'raise ValueError|sys.exit|raise RuntimeError|raise FileNotFoundError' src/metal_gpu_trace/perf_report.py | cut -c1-170
53:        raise FileNotFoundError(f"no recording at {pathlib.Path(trace).name}: perf_record.sh deletes the .trace once "
65:        raise RuntimeError(f"xctrace export of {pathlib.Path(trace).name} failed (exit {proc.returncode}): {reason}")
195:        raise ValueError("the trace has no metal-gpu-intervals table; this Xcode may name it differently: "
645:        raise ValueError("the trace has no launched or attached process; record it with xctrace --launch or --attach")
851:        sys.exit(str(error))
```

Solo estas cuatro condiciones tienen una frase; el `except` de la línea 850 captura exactamente esos tres tipos. Todo lo
demás escapa de `main` como un traceback ([límite 4](./limites.md)).

## E2 El bloque `gpu` de los dos resúmenes reales {#e2}

```text
$ jq -c '.gpu | del(.per_channel_ms)' a2-proof-first_20261115-085621.json
{"intervals":6269,"frames":2045,"frame_gpu_ms":{"count":2045,"mean":5.937,"p50":6.008,"p95":6.213,"max":13.561},"frame_interval_ms":{"count":2044,"mean":9.587,"p50":9.485,"p95":10.098,"max":36.335},"fps_estimate":105.4,"fps_1pct_low":96.2,"fps_01pct_low":48.2,"stutter_rate_pct":0.29,"frame_jitter_ms":0.817,"throttling_analysis":{"thermal_throttling_detected":false,"fps_initial":103.0,"fps_final":105.8,"fps_drift_pct":-2.7}}

$ jq -c '.gpu | del(.per_channel_ms)' a2-proof-second_20261115-085735.json
{"intervals":548,"frames":153,"frame_gpu_ms":{"count":153,"mean":5.86,"p50":6.058,"p95":6.798,"max":13.704},"frame_interval_ms":{"count":152,"mean":15.286,"p50":9.795,"p95":11.982,"max":798.956},"fps_estimate":102.1,"unpresented":{"frames":[160],"from_s":3.637,"span_s":17.236,"command_buffers":1776,"gpu_ms":10358.288,"share_of_gpu_time":0.92},"fps_1pct_low":40.8,"fps_01pct_low":null,"stutter_rate_pct":2.63,"frame_jitter_ms":63.799,"throttling_analysis":{"thermal_throttling_detected":false,"fps_initial":100.6,"fps_final":100.8,"fps_drift_pct":-0.2}}
```

## E3 Recalcular los números desde `frames.csv` {#e3}

La tabla tiene una fila por fotograma: `frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total` (la [guía
de datos](../datos-y-su-ciclo-de-vida/archivos-en-disco.md#las-tablas-y-los-muestreadores)). Los intervalos son las diferencias de `start_ms`
(solo positivas); las fórmulas son las de [Cómo se calcula cada número](./como-se-calculan-los-numeros.md).

```text
$ cd perf-runs
$ tail -n +2 a2-proof-first_20261115-085621.frames.csv | awk -F, 'NR>1{g=$2-p; if(g>0) print g} {p=$2}' | sort -n | awk '{a[NR]=$1; s+=$1; q+=$1*$1} END{n=NR; med=(n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2; lim=1.5*med; if(lim<8)lim=8; for(k=1;k<=n;k++) if(a[k]>lim) c++; i=int(n*0.99); if(i>n-1)i=n-1; j=int(n*0.999); if(j>n-1)j=n-1; m=s/n; sd=sqrt(q/n-m*m); printf "n=%d median=%.4f fps=%.1f low1=%.1f low01=%.1f limit=%.3f over=%d stutter=%.2f jitter=%.3f max=%.3f\n", n, med, 1000/med, 1000/a[i+1], 1000/a[j+1], lim, c, c/n*100, sd, a[n]}'
n=2044 median=9.4845 fps=105.4 low1=96.2 low01=48.2 limit=14.227 over=6 stutter=0.29 jitter=0.817 max=36.335
$ tail -n +2 a2-proof-first_20261115-085621.frames.csv | awk -F, '{s+=$6; n++} END{printf "frames=%d gpu_ms_mean=%.3f\n", n, s/n}'
frames=2045 gpu_ms_mean=5.937

$ tail -n +2 a2-proof-second_20261115-085735.frames.csv | awk -F, 'NR>1{g=$2-p; if(g>0) print g} {p=$2}' | sort -n | awk '{a[NR]=$1; s+=$1; q+=$1*$1} END{n=NR; med=(n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2; lim=1.5*med; if(lim<8)lim=8; for(k=1;k<=n;k++) if(a[k]>lim) c++; i=int(n*0.99); if(i>n-1)i=n-1; j=int(n*0.999); if(j>n-1)j=n-1; m=s/n; sd=sqrt(q/n-m*m); printf "n=%d median=%.4f fps=%.1f low1=%.1f low01(n<1000: null)=%.1f limit=%.3f over=%d stutter=%.2f jitter=%.3f max=%.3f\n", n, med, 1000/med, 1000/a[i+1], 1000/a[j+1], lim, c, c/n*100, sd, a[n]}'
n=152 median=9.7935 fps=102.1 low1=40.8 low01(n<1000: null)=1.3 limit=14.690 over=4 stutter=2.63 jitter=63.799 max=798.956
$ tail -n +2 a2-proof-second_20261115-085735.frames.csv | awk -F, '{s+=$6; n++} END{printf "frames=%d gpu_ms_mean=%.3f\n", n, s/n}'
frames=153 gpu_ms_mean=5.860
```

Contra E2: `fps_estimate` 105.4 y 102.1, `fps_1pct_low` 96.2 y 40.8, `fps_01pct_low` 48.2 (primera) y `null` (segunda:
152 intervalos son menos de 1000, así que el `1.3` que imprime el script es lo que la regla descarta, y el resumen
correctamente tiene `null`), `stutter_rate_pct` 0.29 y 2.63, `frame_jitter_ms` 0.817 y 63.799, fotogramas 2045 y 153, ms de
GPU medios 5.937 y 5.860 (5.86 en el resumen). Todas las cifras publicadas coinciden. El umbral de hitch es 14.227 para la
primera corrida y 14.690 aquí (14.691 en el resumen: el resumen lo calculó con inicios en nanosegundos, la tabla los guarda
a 0.001 ms). Otra diferencia es de diseño: `frame_interval_ms.p50` es 9.485 y 9.795 frente a las medianas verdaderas 9.4845 y
9.7935 (véase [fps_estimate](./como-se-calculan-los-numeros.md#fps-estimate)). Los resúmenes los escribió una versión del
código más antigua que las fórmulas usadas aquí, así que esto comprueba las fórmulas sobre datos viejos ([límite 1](./limites.md)).

## E4 Los bloques de hitches {#e4}

```text
$ jq -c '{missing_tables, hitches: (.hitches | del(.worst))}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"missing_tables":[],"hitches":{"count":6,"per_minute":18.37,"threshold_ms":14.227,"causes":{"cpu_or_wait":5,"memory_growth":1}}}
{"missing_tables":[],"hitches":{"count":4,"per_minute":103.3,"threshold_ms":14.691,"causes":{"cpu_or_wait":3,"memory_growth":1}}}

$ jq -c '.hitches.worst[0:2]' a2-proof-second_20261115-085735.json
[{"frame":159,"interval_ms":798.956,"cause":"cpu_or_wait","window_ms":[2825.46,3624.416],"cpu_pct":4.8},{"frame":23,"interval_ms":24.502,"cause":"cpu_or_wait","window_ms":[1465.036,1489.538],"cpu_pct":95.0}]
```

`count` es 6 y 4, igual que las cuentas «over» de E3 (así que hitches y stutter comparten límite). `per_minute` 103.3 para 4
hitches significa un tramo de 2.32 s, la parte presentada de una corrida de 20.9 s (`duration_s` es 20.87). El peor hitch de
la segunda corrida es el intervalo de 799 ms que cierra la parte presentada, con el programa al 4.8 % de CPU: esperaba, lo
que encaja con una ventana tapada (**especulación**: por qué se tapó la ventana no está en los datos).

## E5 El bloque `unpresented`, tomado de E2 {#e5}

`gpu.unpresented` de la segunda corrida: `frames` `[160]`, `from_s` 3.637, `span_s` 17.236, `command_buffers` 1776, `gpu_ms`
10358.288, `share_of_gpu_time` 0.92. La regla del código pide al menos `max(32, 8 × mediana)` command buffers y al menos 1 s
(`perf_report.py:220-222`); 1776 y 17.236 s la cumplen de sobra. Los `intervals` de la corrida son 548 y sus `frames` 153:
el trabajo dejado fuera no está en ellos. La lectura «la ventana se tapó a los 3.6 s» es **especulación**.

## E6 `perf_compare` y `perf_check`, evaluados a mano {#e6}

Las dos funciones **no se ejecutaron**. Estas son sus fórmulas (`change`, `analysis.py:392-396`; `judge`, `:317-330`)
aplicadas con `jq` a los dos resúmenes, `a` la primera corrida y `b` la segunda:

```text
$ jq -n --slurpfile a a2-proof-first_20261115-085621.json --slurpfile b a2-proof-second_20261115-085735.json 'def ch(x;y): {a:x,b:y,change:((y-x)*1000|round/1000),change_pct:(if x==0 then null else ((100*(y-x)/x)*10|round/10) end)}; ($a[0]) as $A | ($b[0]) as $B | {fps:ch($A.gpu.fps_estimate;$B.gpu.fps_estimate), fps_1pct_low:ch($A.gpu.fps_1pct_low;$B.gpu.fps_1pct_low), stutter_rate_pct:ch($A.gpu.stutter_rate_pct;$B.gpu.stutter_rate_pct), frame_jitter_ms:ch($A.gpu.frame_jitter_ms;$B.gpu.frame_jitter_ms), gpu_ms_mean:ch($A.gpu.frame_gpu_ms.mean;$B.gpu.frame_gpu_ms.mean), metal_mib_peak:ch($A.metal_memory_mib.peak;$B.metal_memory_mib.peak), too_short:[], unpresented_runs:["b"]}' -c
{"fps":{"a":105.4,"b":102.1,"change":-3.3,"change_pct":-3.1},"fps_1pct_low":{"a":96.2,"b":40.8,"change":-55.4,"change_pct":-57.6},"stutter_rate_pct":{"a":0.29,"b":2.63,"change":2.34,"change_pct":806.9},"frame_jitter_ms":{"a":0.817,"b":63.799,"change":62.982,"change_pct":7708.9},"gpu_ms_mean":{"a":5.937,"b":5.86,"change":-0.077,"change_pct":-1.3},"metal_mib_peak":{"a":83.17,"b":94.38,"change":11.21,"change_pct":13.5},"too_short":[],"unpresented_runs":["b"]}

$ jq -n --slurpfile a a2-proof-first_20261115-085621.json --slurpfile b a2-proof-second_20261115-085735.json '($a[0].gpu.fps_estimate) as $lo | ($b[0].gpu.fps_estimate) as $v | {fps_floor_with_3pct_margin:($lo*0.97), run_fps:$v, verdict:(if $v < $lo*0.97 then "worse" else "same" end), gpu_ms_ceiling:($a[0].gpu.frame_gpu_ms.mean*1.03), run_gpu_ms:$b[0].gpu.frame_gpu_ms.mean}' -c
{"fps_floor_with_3pct_margin":102.238,"run_fps":102.1,"verdict":"worse","gpu_ms_ceiling":6.1151100000000005,"run_gpu_ms":5.86}
```

Lectura: `perf_compare` daría el primer bloque (más una entrada `unpresented` que nombra a `b`, y ningún `too_short` porque 153 no
es menos de 100). Para `perf_check` contra una referencia hecha solo de la primera corrida, los FPS están bajo el suelo
(102.1 < 102.238), así que el veredicto sería `regressed`; los ms de GPU por fotograma (5.86 bajo 6.115) y las cuentas de
encoders (ambas corridas tienen p50 2 y 1, de los `encoders` de los resúmenes) son `same`. La referencia de la primera
corrida tiene `spread_pct` 0. Es el [límite 8](./limites.md) y la razón de que `perf_baseline` pida varias corridas. Los
resultados son **probables** (código leído, no ejecutado).

## E7 `missing_tables`, ruido y diagnóstico a mano {#e7}

```text
$ sed -n 128,132p tests/test_report.py
    assert perf_report.missing_tables(toc) == ["ProcessCPUUsage", "device-thermal-state-intervals", "gpu-performance-state-intervals",
                                               "graphics-compiler-activity-intervals", "graphics-compiler-spill-events",
                                               "metal-application-encoders-list",
                                               "metal-command-buffer-error", "metal-current-allocated-size",
                                               "metal-resource-allocations"]

$ jq -c '{label, stutter:.gpu.stutter_rate_pct, stutter_verdict:(if .gpu.stutter_rate_pct==null then "UNKNOWN" elif .gpu.stutter_rate_pct>7 then "SEVERE_STUTTER" elif .gpu.stutter_rate_pct>=2 then "MICRO_STUTTER" else "SMOOTH" end), idle_share:.gpu_idle.idle_share, high_variance:((.gpu.frame_jitter_ms>=3) or ((.gpu.frame_interval_ms.p95-.gpu.frame_interval_ms.p50)>=5)), working_set_mib:([.process_rss_mib.max,.metal_memory_mib.peak]|max), noisy_external_pct:((.gpu_activity.device_pct.mean - 100*(1-.gpu_idle.idle_share))*10|round/10)}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"label":"a2-proof-first_20261115-085621","stutter":0.29,"stutter_verdict":"SMOOTH","idle_share":0.381,"high_variance":false,"working_set_mib":237.312,"noisy_external_pct":-6.4}
{"label":"a2-proof-second_20261115-085735","stutter":2.63,"stutter_verdict":"MICRO_STUTTER","idle_share":0.425,"high_variance":true,"working_set_mib":238.672,"noisy_external_pct":0.6}

$ jq -c '{label,hitches:.hitches.count,shader_compile:(.hitches.causes.shader_compile // 0),compiler_busy_ms:.graphics_compiler.busy_ms}' a2-proof-first_20261115-085621.json a2-proof-second_20261115-085735.json
{"label":"a2-proof-first_20261115-085621","hitches":6,"shader_compile":0,"compiler_busy_ms":0.227}
{"label":"a2-proof-second_20261115-085735","hitches":4,"shader_compile":0,"compiler_busy_ms":0.292}
```

El primer bloque es toda la aserción de `missing_tables` para un trazo que solo tiene los intervalos de GPU: nueve nombres,
ordenados. El segundo aplica a mano los umbrales de `perf_diagnose` y `noisy_environment`: veredictos `SMOOTH` y
`MICRO_STUTTER`, varianza alta solo en la segunda, un conjunto de trabajo muy por debajo de 1500 MiB, y partes ociosas de
0.381 y 0.425 (ambas sobre 0.25: un cuello `CPU_SUBMISSION_BOUND` por la regla, **probable**, herramienta no ejecutada); y la
diferencia entre el uso de la GPU y el del propio programa, -6.4 y 0.6 puntos, lejos de los 20 que marcan ruido. El tercer
bloque es la entrada de `cold_warm_report`: ningún hitch `shader_compile` en ninguna corrida, así que `first_seen_hitches`
sería 0 y `extra_hitches_in_first` `max(0, 6 - 4)` = 2.

## E8 Los límites que el código impone {#e8}

```text
$ rg -n "1 <= count|1 <= rounds|2 <= len\(values\)|> 24|<= seconds <= 600|<= skip <= 600|ok = value|margin = 0 if" src/metal_gpu_trace/experiments.py src/metal_gpu_trace/analysis.py src/metal_gpu_trace/paths.py | cut -c1-190
src/metal_gpu_trace/experiments.py:20:    if not 1 <= count <= 10:
src/metal_gpu_trace/experiments.py:60:    if not 1 <= rounds <= 5:
src/metal_gpu_trace/experiments.py:124:    if not isinstance(values, list) or not 2 <= len(values) <= 8:
src/metal_gpu_trace/experiments.py:153:    if not 1 <= rounds <= 5:
src/metal_gpu_trace/experiments.py:156:    if len(values) * rounds > 24:
src/metal_gpu_trace/paths.py:113:    if not 0 <= seconds <= 600:  # a NaN is false here too
src/metal_gpu_trace/paths.py:124:    if not 0 <= skip <= 600:
src/metal_gpu_trace/analysis.py:325:    margin = 0 if metric.endswith("_p50") else margin_pct / 100
src/metal_gpu_trace/analysis.py:490:        ok = value is not None and (value >= limit if kind == "min" else value <= limit)
```
