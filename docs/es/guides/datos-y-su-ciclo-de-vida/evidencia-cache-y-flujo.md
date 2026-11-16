# Evidencia E8 a E12: la caché, los pasos y las variables

**Lector:** personas que quieren comprobar las afirmaciones sobre la caché, los pasos de grabación y la retención contra una salida real. Revisado el 2026-11-16.

English: [Evidence E8 to E12: the cache, the steps and the variables](../../../guides/data-and-lifecycle/evidence-cache-and-flow.md)

> **En corto:** los comandos de solo lectura detrás de lo dicho sobre la caché, los ocho pasos de una grabación y las dos
> variables de retención, con su salida real, y al final lo que no se pudo reproducir porque necesita una grabación o borra archivos.

Volver al [índice](./index.md). Anterior: [Evidencia E1 a E7](./evidencia-corridas.md). Misma fecha de recogida y mismo acortamiento de rutas (2026-11-16, el home es `~`).

## E8 La caché y el candado

```text
$ ls -a ~/Library/Caches/metal-gpu-trace
bgfx-examples-1d120363981c
bgfx-examples-320a6b3bbc11
bgfx-examples-9c1bd6164b4a
bgfx-examples-bd41458ee01e
bgfx-examples-c5b25350c15e
drawstress-2b3b01fa2dd0
drawstress-f7e25cbb8c4a
godot-a85320f08e1a

$ du -sh ~/Library/Caches/metal-gpu-trace
942M	~/Library/Caches/metal-gpu-trace

$ du -sh ~/Library/Caches/metal-gpu-trace/*
 97M	~/Library/Caches/metal-gpu-trace/bgfx-examples-1d120363981c
 63M	… bgfx-examples-320a6b3bbc11
 65M	… bgfx-examples-9c1bd6164b4a
 79M	… bgfx-examples-bd41458ee01e
 78M	… bgfx-examples-c5b25350c15e
 27M	… drawstress-2b3b01fa2dd0
 23M	… drawstress-f7e25cbb8c4a
510M	… godot-a85320f08e1a
```

(Se omiten `.` y `..`.) No aparece ningún `recording.lock`: nada está grabando.

## E9 Las versiones que fija el paquete

```text
$ jq -r '.workloads|to_entries[]|"\(.key) \(.value.sha256[0:12])"' src/metal_gpu_trace/data/workloads.json
drawstress 2b3b01fa2dd0
bgfx-examples 1d120363981c
godot a85320f08e1a
```

Tres pines frente a ocho carpetas: `bgfx-examples-320a`, `-9c1b`, `-bd41`, `-c5b2` y `drawstress-f7e2` no coinciden con ningún pin.

## E10 Nada borra una carpeta de la caché

```text
$ rg -n "rmtree|unlink" src/metal_gpu_trace/workloads.py
173:            part.unlink()
```

## E11 Los ocho pasos de la Figura 2

Cada paso se lee de la línea que lo hace (`rg -n` en `src/metal_gpu_trace`), no de una grabación. La disposición es mía (paso, `archivo:línea`, la línea sin sangría, recortada a 140 caracteres):

```text
1  preflight.py:135        if recording_running(alive):
2  perf_record.sh:52       if ! mkdir $lock 2>/dev/null; then
2  perf_record.sh:62       echo $$ > $lock/pid
3  perf_record.sh:105      echo "time_s,rss_kib" > $out/$name.rss.csv
3  perf_record.sh:140      xcrun xctrace record --template "Metal System Trace" --time-limit ${seconds}s --output $out/$name.trace \
4  perf_record.sh:160      python3 -I $here/perf_report.py $out/$name.trace $report
5  perf_report.py:745      table_files.write(out, f"{label}.metal_memory", ["time_ms", "metal_allocated_bytes"],
5  perf_report.py:831      table_files.write(
5  perf_report.py:836      (out / f"{label}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
6  perf_record.sh:163      [[ ${KEEP_TRACE:-0} == 1 ]] || rm -rf $out/$name.trace
6  perf_record.sh:164      if [[ ${KEEP_RUNS:-} == <1-> ]]; then zsh $here/prune_runs.sh $out $KEEP_RUNS; fi
7  perf_record.sh:68       rm -rf $lock
7  perf_record.sh:73       trap cleanup EXIT
8  recording.py:346        if config.MAX_DISK_MB and not preflight.recording_running():
8  recording.py:347        removed = retention.prune_to_quota(config.OUT, config.MAX_DISK_MB, json_path.stem)
8  recording.py:350        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

El orden en el tiempo (2 antes de 7, 5 antes de 8) sale del orden de las líneas y las llamadas. Una ejecución en vivo con marcas de tiempo **no se reprodujo**: graba.

## E12 Dónde aparecen las dos variables de retención

```text
$ rg -n "KEEP_RUNS|METAL_TRACE_MAX_DISK_MB" src
src/metal_gpu_trace/perf_record_windows.py:922:        keep_runs_env = os.environ.get("KEEP_RUNS")
src/metal_gpu_trace/project.py:3:The folder is checked before use, because KEEP_RUNS removes the older .json files in it
src/metal_gpu_trace/retention.py:1:"""Keeping the runs folder under a size limit (METAL_TRACE_MAX_DISK_MB): removes the heavy files of old recordings."""
src/metal_gpu_trace/config.py:22:    limit = environ.get("METAL_TRACE_MAX_DISK_MB", "").strip()
src/metal_gpu_trace/recording.py:338:    """Adds `layer`, the run's `context` and `tier` to the summary, applies METAL_TRACE_MAX_DISK_MB ...
src/metal_gpu_trace/perf_record.sh:164:if [[ ${KEEP_RUNS:-} == <1-> ]]; then zsh $here/prune_runs.sh $out $KEEP_RUNS; fi
```

Se muestran seis de las 21 líneas que imprimió `rg` (las que leen o actúan sobre una variable), cada una recortada a 120 caracteres; el resto son comentarios o docstrings. `KEEP_RUNS` se lee en `perf_record.sh:164` y `perf_record_windows.py:922`, y actúa en `prune_runs.sh:9` (que recibe el número como `keep`). `METAL_TRACE_MAX_DISK_MB` se lee solo en `config.py:22` y actúa en `retention.py` por `recording.py:346-347`.

## Lo que no se reprodujo

- Un resumen de generación 2 o 3 de una grabación real (necesita Instruments).
- Un `.csv.gz` en una corrida real y su proporción de compresión.
- Una grabación que tenga el candado, y la limpieza tras un script matado.
- La cuota borrando archivos, `retention` en un resumen, `trace_dropped` y `KEEP_RUNS` borrando un `.trace` (borran archivos).
- El listado de claves con `python3 -I -c`.
