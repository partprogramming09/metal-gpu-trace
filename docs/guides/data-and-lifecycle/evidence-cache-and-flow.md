# Evidence E8 to E12: the cache, the steps and the variables

**Reader:** people who want to check the claims about the cache, the recording steps and retention against real output. Reviewed 2026-11-16.

Español: [Evidencia E8 a E12: la caché, los pasos y las variables](../../es/guides/datos-y-su-ciclo-de-vida/evidencia-cache-y-flujo.md)

> **In short:** the read-only commands behind the claims about the cache, the eight recording steps and the two
> retention variables, with real output, ending with what could not be reproduced because it needs a recording or deletes files.

Back to the [index](./index.md). Previous: [Evidence E1 to E7](./evidence-runs.md). Same collection date and path shortening (2026-11-16, home is `~`).

## E8 The cache and the lock

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

(`.` and `..` omitted.) No `recording.lock` is listed: nothing is recording.

## E9 The versions the package pins

```text
$ jq -r '.workloads|to_entries[]|"\(.key) \(.value.sha256[0:12])"' src/metal_gpu_trace/data/workloads.json
drawstress 2b3b01fa2dd0
bgfx-examples 1d120363981c
godot a85320f08e1a
```

Three pins against eight folders: `bgfx-examples-320a`, `-9c1b`, `-bd41`, `-c5b2` and `drawstress-f7e2` match no pin.

## E10 Nothing deletes a cache folder

```text
$ rg -n "rmtree|unlink" src/metal_gpu_trace/workloads.py
173:            part.unlink()
```

## E11 The eight steps of Figure 2

Each step is read from the line that does it (`rg -n` in `src/metal_gpu_trace`), not from a recording. The layout is mine (step, `file:line`, the line without indentation, trimmed to 140 characters):

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

The order in time (2 before 7, 5 before 8) comes from the order of lines and calls. A live run with timestamps was **not reproduced**: it records.

## E12 Where the two retention variables appear

```text
$ rg -n "KEEP_RUNS|METAL_TRACE_MAX_DISK_MB" src
src/metal_gpu_trace/perf_record_windows.py:922:        keep_runs_env = os.environ.get("KEEP_RUNS")
src/metal_gpu_trace/project.py:3:The folder is checked before use, because KEEP_RUNS removes the older .json files in it
src/metal_gpu_trace/retention.py:1:"""Keeping the runs folder under a size limit (METAL_TRACE_MAX_DISK_MB): removes the heavy files of old recordings."""
src/metal_gpu_trace/config.py:22:    limit = environ.get("METAL_TRACE_MAX_DISK_MB", "").strip()
src/metal_gpu_trace/recording.py:338:    """Adds `layer`, the run's `context` and `tier` to the summary, applies METAL_TRACE_MAX_DISK_MB ...
src/metal_gpu_trace/perf_record.sh:164:if [[ ${KEEP_RUNS:-} == <1-> ]]; then zsh $here/prune_runs.sh $out $KEEP_RUNS; fi
```

Six of the 21 lines `rg` printed are shown (those that read or act on a variable), each trimmed to 120 characters; the rest are comments or docstrings. `KEEP_RUNS` is read in `perf_record.sh:164` and `perf_record_windows.py:922`, and acts in `prune_runs.sh:9` (which receives the number as `keep`). `METAL_TRACE_MAX_DISK_MB` is read only in `config.py:22` and acts in `retention.py` through `recording.py:346-347`.

## What was not reproduced

- A generation 2 or 3 summary of a real recording (needs Instruments).
- A `.csv.gz` on a real run and its compression ratio.
- A recording holding the lock, and the cleanup after a killed script.
- The quota removing files, `retention` in a summary, `trace_dropped`, and `KEEP_RUNS` removing a `.trace` (they delete files).
- The listing of keys with `python3 -I -c`.
