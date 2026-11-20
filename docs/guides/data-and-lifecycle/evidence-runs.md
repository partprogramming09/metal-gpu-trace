# Evidence E1 to E7: the runs folder

**Reader:** people who want to check the claims of this guide against real output. Reviewed 2026-11-16.

> **In short:** the commands really run on a real runs folder, with their output, backing the claims about files, sizes,
> keys and cleanup. Each block is E1 to E7 and the other pages point to it. Where a command could not be run, it says "not reproduced".

Back to the [index](./index.md). Next: [Evidence E8 to E12](./evidence-cache-and-flow.md).

Collected on 2026-11-16 on an Apple silicon Mac; all commands only read. Paths are shortened (home is `~`, recordings in `~/perf-runs/<project>`, file owner left out). The folder holds recordings made in October 2026 with an older version; the repository's own `perf-runs/` has two more from November 15.

## E1 The files a run leaves

```text
$ ls -a -1 ~/perf-runs/<project> | head -4
.
..
.metal-gpu-trace-runs
baselines.json

$ cd ~/perf-runs/<project> && ls -l -g -o -h . | sed 's/ [0-9]* *$//'
-rw-r--r--@  1     10K Oct 18 02:02 baselines.json
-rw-r--r--@  1    2.7K Oct 18 02:02 probe-mtl_20261018-003242.json
… recortado: 5 more summaries (probe-d3d12, 3 ref-d3d12, tp-d3d12)
-rw-r--r--@  1     56K Oct 18 02:13 v070-d3d12_20261018-021158.frames.csv
-rw-r--r--@  1    4.9K Oct 18 02:13 v070-d3d12_20261018-021158.json
-rw-r--r--@  1    418K Oct 18 02:13 v070-d3d12_20261018-021158.metal_memory.csv
-rw-r--r--@  1    367B Oct 18 02:12 v070-d3d12_20261018-021158.rss.csv
drwxr-xr-x@ 10    320B Oct 18 02:13 v070-d3d12_20261018-021158.trace
```

Seven summaries, one run with three tables and a sampler, and one `.trace`. Every table is plain `.csv`, none `.csv.gz`: the compressed format was **not reproduced** on a real run.

## E2 Size

```text
$ du -sh ~/perf-runs/<project> ~/perf-runs/<project>/v070-d3d12_20261018-021158.trace
259M	~/perf-runs/<project>
259M	~/perf-runs/<project>/v070-d3d12_20261018-021158.trace
```

`du -sh` prints binary units, so 259M is 259 MiB. The `.trace` is the whole folder, to `du`'s precision.

## E3 Keys of real summaries

```text
$ jq -r 'keys_unsorted|join(" ")' perf-runs/a2-proof-first_20261115-085621.json
label trace process device template duration_s machine missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_activity gpu_performance_state_share graphics_compiler thermal_state_share cpu resource_allocations command_buffer_errors hitches layer context

$ jq -c '{trace,schema:(.schema_version),tier,retention}' ~/perf-runs/<project>/v070-d3d12_20261018-021158.json perf-runs/a2-proof-first_20261115-085621.json
{"trace":"v070-d3d12_20261018-021158.trace","schema":null,"tier":null,"retention":null}
{"trace":"a2-proof-first_20261115-085621.trace","schema":null,"tier":null,"retention":null}

$ jq -r '"\(input_filename|split("/")|last|.[0:26]): \(keys_unsorted|join(" "))"' <the October summaries, 2 of the 5 shown here>
tp-d3d12_20261018-011509.j: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib gpu_performance_state_share
v070-d3d12_20261018-021158: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_performance_state_share layer
```

Every key in these real files is in the [always-present and conditional tables](./json-keys.md) (`label`, `trace`, `process`, `device`, `template`, `duration_s`, `machine`, `missing_tables`, `gpu`, `encoders`, `gpu_idle`, `metal_memory_mib`, `process_rss_mib`, `gpu_activity`, `gpu_performance_state_share`, `graphics_compiler`, `thermal_state_share`, `cpu`, `resource_allocations`, `command_buffer_errors`, `hitches`, `layer`, `context`). The reverse check (a real summary with every key the code can write) was **not reproduced**: there is none. The files show why keys are optional: the older ones have no `machine`, `hitches` or `context`, and `tp-d3d12` has no `layer`. The `python3 -I -c` listing the plan asked for was **not reproduced**: the collecting tool ran only read-only tools without Python, so `jq` was used.

## E4 The columns of the tables

```text
$ head -2 ~/perf-runs/<project>/v070-d3d12_20261018-021158.frames.csv
frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total
1,8920.469,0.1068,0.0,0.0,0.1068
$ head -1 ~/perf-runs/<project>/v070-d3d12_20261018-021158.metal_memory.csv
time_ms,metal_allocated_bytes
$ head -1 ~/perf-runs/<project>/v070-d3d12_20261018-021158.rss.csv
time_s,rss_kib
$ head -1 perf-runs/a2-proof-first_20261115-085621.agx.csv
time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib
```

## E5 A summary whose `.trace` is gone

```text
$ cd ~/perf-runs/<project>
$ ls -d probe-mtl_20261018-003242.*
probe-mtl_20261018-003242.json

$ jq -r '.trace' v070-d3d12_20261018-021158.json probe-mtl_20261018-003242.json
v070-d3d12_20261018-021158.trace
probe-mtl_20261018-003242.trace
```

The second summary names a `.trace` that is not there (the first has its folder, E1): the normal case, since the `.trace` is deleted unless asked for.

## E6 What the stem glob matches

```text
$ cd ~/perf-runs/<project>
$ ls -d v070-d3d12_20261018-021158.*
v070-d3d12_20261018-021158.frames.csv
v070-d3d12_20261018-021158.json
v070-d3d12_20261018-021158.metal_memory.csv
v070-d3d12_20261018-021158.rss.csv
v070-d3d12_20261018-021158.trace
```

This is the glob `${old:r}.*` that `prune_runs.sh` expanded for an old run's stem at the time of the measurement, before 24490ec (`${old:r}` is the `.json` name without `.json`); it includes the `.trace`. Since 24490ec the script expands `${old:r}.*~*.trace` (`prune_runs.sh:10`), which leaves the `.trace` out. Limit 6 rested on this output; `rm -rf` itself was **not reproduced** (a deletion).

## E7 The baselines file

```text
$ jq -r 'to_entries[]|"\(.key): \(.value|keys|join(","))"' ~/perf-runs/<project>/baselines.json
<baseline>: runs,set,summaries

$ jq -r '.[].summaries|length' ~/perf-runs/<project>/baselines.json
3
```

(The baseline's name was replaced by `<baseline>`.) One baseline with `runs`, `set` and `summaries` (three copies), as `analysis.py:279-280` writes it.
