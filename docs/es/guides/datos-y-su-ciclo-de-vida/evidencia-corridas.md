# Evidencia E1 a E7: la carpeta de corridas

**Lector:** personas que quieren comprobar las afirmaciones de esta guía contra una salida real. Revisado el 2026-11-16.

English: [Evidence E1 to E7: the runs folder](../../../guides/data-and-lifecycle/evidence-runs.md)

> **En corto:** esta página guarda los comandos que se corrieron de verdad sobre una carpeta de corridas real, con su
> salida, para respaldar lo dicho sobre archivos, tamaños, claves y limpieza. Cada bloque se llama E1 a E7 y las demás
> páginas apuntan a él. Donde un comando no se pudo correr, la página dice «no reproducido».

Volver al [índice](./index.md). Siguiente: [Evidencia E8 a E12](./evidencia-cache-y-flujo.md).

Recogida el 2026-11-16 en un Mac con Apple silicon. Todos los comandos solo leen. Las rutas están acortadas: la carpeta
personal es `~`, la carpeta de grabaciones es `~/perf-runs/<project>`, el dueño de los archivos se omite. La carpeta de
corridas comprobada es una carpeta de grabaciones hechas en octubre de 2026 con una versión anterior; el `perf-runs/`
del propio repositorio tiene dos grabaciones más del 15 de noviembre. Los comandos y sus salidas no se traducen.

## E1 Los archivos que deja una corrida

```text
$ ls -a -1 ~/perf-runs/<project> | head -4
.
..
.metal-gpu-trace-runs
baselines.json

$ cd ~/perf-runs/<project> && ls -l -g -o -h . | sed 's/ [0-9]* *$//'
total
-rw-r--r--@  1     10K Oct 18 02:02 baselines.json
-rw-r--r--@  1    4.9K Oct 18 02:02 probe-d3d12_20261018-003026.json
-rw-r--r--@  1    2.7K Oct 18 02:02 probe-mtl_20261018-003242.json
-rw-r--r--@  1    4.2K Oct 18 02:02 ref-d3d12-1_20261018-002332.json
-rw-r--r--@  1    4.7K Oct 18 02:02 ref-d3d12-2_20261018-002603.json
-rw-r--r--@  1    4.9K Oct 18 02:02 ref-d3d12-3_20261018-002816.json
-rw-r--r--@  1    2.9K Oct 18 02:02 tp-d3d12_20261018-011509.json
-rw-r--r--@  1     56K Oct 18 02:13 v070-d3d12_20261018-021158.frames.csv
-rw-r--r--@  1    4.9K Oct 18 02:13 v070-d3d12_20261018-021158.json
-rw-r--r--@  1    418K Oct 18 02:13 v070-d3d12_20261018-021158.metal_memory.csv
-rw-r--r--@  1    367B Oct 18 02:12 v070-d3d12_20261018-021158.rss.csv
drwxr-xr-x@ 10    320B Oct 18 02:13 v070-d3d12_20261018-021158.trace
```

Siete resúmenes, una corrida con sus tres tablas y su muestreador, y un `.trace`. Todas las tablas son `.csv` sin
comprimir: ninguna es `.csv.gz`, así que el formato comprimido **no se reprodujo** en una corrida real.

## E2 Tamaño

```text
$ du -sh ~/perf-runs/<project> ~/perf-runs/<project>/v070-d3d12_20261018-021158.trace
259M	~/perf-runs/<project>
259M	~/perf-runs/<project>/v070-d3d12_20261018-021158.trace
```

`du -sh` imprime unidades binarias, así que 259M son 259 MiB. El `.trace` es toda la carpeta, con la precisión que da `du`.

## E3 Claves de resúmenes reales

```text
$ jq -r 'keys_unsorted|join(" ")' perf-runs/a2-proof-first_20261115-085621.json
label trace process device template duration_s machine missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_activity gpu_performance_state_share graphics_compiler thermal_state_share cpu resource_allocations command_buffer_errors hitches layer context

$ jq -c '{trace,schema:(.schema_version),tier,retention}' ~/perf-runs/<project>/v070-d3d12_20261018-021158.json perf-runs/a2-proof-first_20261115-085621.json
{"trace":"v070-d3d12_20261018-021158.trace","schema":null,"tier":null,"retention":null}
{"trace":"a2-proof-first_20261115-085621.trace","schema":null,"tier":null,"retention":null}

$ jq -r '"\(input_filename|split("/")|last|.[0:26]): \(keys_unsorted|join(" "))"' <the October summaries, 3 of the 5 shown here>
probe-d3d12_20261018-00302: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_performance_state_share layer
tp-d3d12_20261018-011509.j: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib gpu_performance_state_share
v070-d3d12_20261018-021158: label trace process device template duration_s missing_tables gpu encoders gpu_idle metal_memory_mib process_rss_mib gpu_performance_state_share layer
```

Cada clave de estos archivos reales está en las [tablas de siempre presentes y condicionales](./claves-del-resumen.md),
una por una (`label`, `trace`, `process`, `device`, `template`, `duration_s`, `machine`, `missing_tables`, `gpu`,
`encoders`, `gpu_idle`, `metal_memory_mib`, `process_rss_mib`, `gpu_activity`, `gpu_performance_state_share`,
`graphics_compiler`, `thermal_state_share`, `cpu`, `resource_allocations`, `command_buffer_errors`, `hitches`, `layer`,
`context`). La comprobación inversa (un resumen real con todas las claves que el código puede escribir) **no se
reprodujo**: no existe. Los archivos muestran además por qué un lector debe tratar las claves como opcionales: los más
antiguos no tienen `machine`, `hitches` ni `context`, y `tp-d3d12` no tiene `layer`. El listado con `python3 -I -c` que
pedía el plan **no se reprodujo**: la evidencia se recogió solo con herramientas de lectura sin Python, así que se usó
`jq`.

## E4 Las columnas de las tablas

```text
$ head -3 ~/perf-runs/<project>/v070-d3d12_20261018-021158.frames.csv
frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total
1,8920.469,0.1068,0.0,0.0,0.1068
2,8939.648,0.1057,0.0,0.0,0.1057

$ head -3 ~/perf-runs/<project>/v070-d3d12_20261018-021158.metal_memory.csv
time_ms,metal_allocated_bytes
2267.019,131072
8887.183,147456

$ head -3 ~/perf-runs/<project>/v070-d3d12_20261018-021158.rss.csv
time_s,rss_kib
0,0
1,0

$ head -3 perf-runs/a2-proof-first_20261115-085621.agx.csv
time_s,device_pct,renderer_pct,tiler_pct,split_scenes,recovery_count,in_use_mib
0,0,0,0,0,0,361
1,3,3,3,0,0,362
```

## E5 Un resumen cuyo `.trace` ya no existe

```text
$ cd ~/perf-runs/<project>
$ ls -d probe-mtl_20261018-003242.*
probe-mtl_20261018-003242.json

$ jq -r '.trace' v070-d3d12_20261018-021158.json probe-mtl_20261018-003242.json
v070-d3d12_20261018-021158.trace
probe-mtl_20261018-003242.trace
```

El segundo resumen nombra un `.trace`, y el `ls` muestra que no hay ninguno (el primero sí tiene su carpeta, E1).

La clave nombra un archivo que no está: es el caso normal, porque el `.trace` se borra salvo que se pida conservarlo.

## E6 Qué abarca el patrón del stem

```text
$ cd ~/perf-runs/<project>
$ ls -d v070-d3d12_20261018-021158.*
v070-d3d12_20261018-021158.frames.csv
v070-d3d12_20261018-021158.json
v070-d3d12_20261018-021158.metal_memory.csv
v070-d3d12_20261018-021158.rss.csv
v070-d3d12_20261018-021158.trace
```

Es el patrón `${old:r}.*` que `prune_runs.sh:9` expande para el stem de una corrida vieja (`${old:r}` es el nombre del
`.json` sin `.json`). Incluye el `.trace`. El límite 6 se apoya en esta salida; el `rm -rf` en sí **no se reprodujo**
(es un borrado).

## E7 El archivo de líneas base

```text
$ jq -r 'to_entries[]|"\(.key): \(.value|keys|join(","))"' ~/perf-runs/<project>/baselines.json
<baseline>: runs,set,summaries

$ jq -r '.[].summaries|length' ~/perf-runs/<project>/baselines.json
3
```

(El nombre propio de la línea base se sustituyó por `<baseline>`.) Una línea base, con `runs`, `set` y `summaries` (tres
copias de resúmenes), como la escribe `analysis.py:279-280`.
