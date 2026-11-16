# Evidence: the commands and their real output

**Reader:** people who want to check a number of this guide, and the owner. Reviewed 2026-11-16.

Español: [Evidencia](../../es/guides/leer-trazas/evidencia.md)

> **In short:** every number in this guide comes from a command shown here with its real output. All commands only read.
> Because the repository holds no recording to open and Python could not be run, **no tool of this guide was run**; where a
> tool's result is shown, it was worked out by hand from the code's formula on a real run.

## Three limits of method

1. The repository holds **no `.trace`, no `.chrome-trace` and no `.gputrace`** (E3), and reading a `.trace` needs `xctrace`,
   so none of the `trace_*` tools was run.
2. The session that wrote the guide could run read-only shell commands (`rg`, `sed`, `awk`, `jq`, `wc`, `find`) and could not
   run Python, `xctrace` or `xxd`, so no tool of `traces.py` or `gputrace_read.py` was run either: what they return is read
   from the code, evaluated by hand on the two real runs of the clone where a run is needed, and pinned by tests that are
   named, not run.
3. No real `.gputrace` has been examined for this guide or for the project's published proof (see
   [the format](./gputrace-format.md)), so every claim about the format is the code's own claim.

Collected on 2026-11-16 on an Apple silicon Mac. The runs folder is `perf-runs/` of the clone (a local, ignored folder that is
not published; it holds two finished runs and their tables). E5 and E6 are the formulas of the code evaluated by hand.

## E1 Where each tool is registered

```text
$ rg -n '"(perf_export_trace|trace_tables|trace_count|trace_query|capture_summary|capture_diff|capture_records)":' src/metal_gpu_trace/registry.py | cut -c1-90
129:    "perf_export_trace": (traces.tool_perf_export_trace, schema(
159:    "trace_tables": (traces.tool_trace_tables, schema({"trace": TRACE}, ["trace"]), hi
160:    "trace_count": (traces.tool_trace_count, schema(
165:    "trace_query": (traces.tool_trace_query, schema(
172:    "capture_summary": (traces.tool_capture_summary, schema({"capture": CAPTURE}, ["ca
173:    "capture_diff": (traces.tool_capture_diff, schema(
177:    "capture_records": (traces.tool_capture_records, schema({"capture": CAPTURE, **PAG
```

## E2 How many call ids are confirmed and how many probable

```text
$ rg -c '"confirmado"\)' src/metal_gpu_trace/gputrace_read.py
17
$ rg -c '"probable"\)' src/metal_gpu_trace/gputrace_read.py
7
$ rg -n 'probable' src/metal_gpu_trace/gputrace_read.py | cut -c1-110
38:    -16353: ("renderCommandEncoder", "probable"),
39:    -16246: ("endEncoding", "probable"),
40:    -16343: ("commandBuffer", "probable"),
41:    -10240: ("buffer contents", "probable"),
42:    -15416: ("drawMeshThreadgroups", "probable"),
43:    -15415: ("drawMeshThreadgroupsWithIndirectBuffer", "probable"),
44:    -16327: ("dispatchThreadgroups", "probable"),
```

17 + 7 = 24 ids, the number the guide uses. The 17 are the three debug markers, `drawPrimitives` and the thirteen state calls.

## E3 The repository has no trace and no capture to read

```text
$ find . -name '*.gputrace' -not -path './node_modules/*' -not -path './.git/*' | wc -l
       0
$ find . \( -name '*.trace' -o -name '*.chrome-trace' \) -not -path './node_modules/*' -not -path './.git/*' | wc -l
       0
```

The tests build their own: `tests/test_capture.py:18-27` writes a `.gputrace` folder with a `capture` file of `MTSP`, 4 zero
bytes and records, and `tests/test_traces.py:11-16` writes an XML table. Neither is a file of the repository.

## E4 The per-frame tables of the two real runs

```text
$ head -2 perf-runs/a2-proof-first_20261115-085621.frames.csv
frame,start_ms,gpu_ms_compute,gpu_ms_fragment,gpu_ms_vertex,gpu_ms_total
6,1267.79,0.0243,1.7417,11.7952,13.5612
$ wc -l perf-runs/a2-proof-first_20261115-085621.frames.csv perf-runs/a2-proof-second_20261115-085735.frames.csv
    2046 perf-runs/a2-proof-first_20261115-085621.frames.csv
     154 perf-runs/a2-proof-second_20261115-085735.frames.csv
    2200 total
```

Header included, the first run has 2045 frames and the second 153: the same numbers as in the
[summarizing guide](../summarizing/index.md) (the second run stopped presenting at 3.6 s). Both tables are plain
`.csv`, from before the compression of 0.27.0; `tables.find` reads either format.

## E5 `perf_export_trace` on the first row, by hand

```text
$ sed -n 2p perf-runs/a2-proof-first_20261115-085621.frames.csv | awk -F, '{printf "{\"name\":\"GPU frame\",\"ph\":\"X\",\"pid\":1,\"tid\":1,\"ts\":%s,\"dur\":%s,\"args\":{\"frame\":%d,\"compute\":%s,\"fragment\":%s,\"vertex\":%s}}\n",$2*1000,$6*1000,$1,$3,$4,$5}'
{"name":"GPU frame","ph":"X","pid":1,"tid":1,"ts":1267790,"dur":13561.2,"args":{"frame":6,"compute":0.0243,"fragment":1.7417,"vertex":11.7952}}
```

This is `awk` doing the arithmetic of `traces.py:22-25` (`start_ms × 1000`, `gpu_ms_total × 1000`, the `gpu_ms_` prefix cut), not
the tool. Python's own floating-point result may differ in the last digits (for example `13561.2` against
`13561.199999999999`); **not reproduced** with the tool. The same arithmetic is asserted for a two-row table by
`tests/test_analysis.py:329-332` (`ts == 10500.0`, `dur == 600.0`), not run. The sum 0.0243 + 1.7417 + 11.7952 is 13.5612,
the `gpu_ms_total` of the row.

## E6 `trace_query` windows, by hand

Three rows with `start` and `duration` in ns: (1 000 000, 2 000 000), (9 000 000, 1 000 000), (12 000 000, 4 000 000), and
`window_ms=10`. A window is `start // 10 000 000`:

```text
1 000 000 // 10 000 000 = 0     9 000 000 // 10 000 000 = 0     12 000 000 // 10 000 000 = 1
window 0: start_ms 0 x 10 = 0,   count 2, duration (2 000 000 + 1 000 000) / 1 000 000 = 3.0 ms
window 1: start_ms 1 x 10 = 10,  count 1, duration 4 000 000 / 1 000 000 = 4.0 ms
```

These are the rows and answer asserted by `tests/test_traces.py:42-48`
(`[{"start_ms": 0, "count": 2, "duration_ms": 3.0}, {"start_ms": 10, "count": 1, "duration_ms": 4.0}]`), not run; the sums
above are the formulas of `traces.py:74-87` evaluated by hand.

## E7 The limits and the GPU family data the code enforces

```text
$ rg -n 'MAX_LIMIT|MAX_TEXT' src/metal_gpu_trace/config.py src/metal_gpu_trace/worker.py src/metal_gpu_trace/registry.py | cut -c1-140
src/metal_gpu_trace/registry.py:19:        "limit": {**I, "description": f"rows per page, default 50, at most {config.MAX_LIMIT}"}}
src/metal_gpu_trace/config.py:43:MAX_LIMIT = 500
src/metal_gpu_trace/config.py:45:MAX_TEXT = 40_000
src/metal_gpu_trace/worker.py:162:        if len(text) > config.MAX_TEXT:
$ jq -r '.families|keys|join(",")' src/metal_gpu_trace/data/apple-gpu-families.json
Apple10,Apple7,Apple8,Apple9
```

## E8 What a real recording held (a measurement of 2026-11-15, not repeated)

The project's research note of 2026-11-15 (internal, not published) records, for one 8-second recording of the `drawstress`
test program at the `deep` tier, made with `xctrace` 27.2 on an Apple M1 Pro under macOS 27.0.1 and 170 MB on disk: **85
tables exported, 59 with rows and 26 empty**, and, for the GPU intervals table, the share of its summed duration by process.
The busiest processes were the program under test and, behind it, other programs of the machine (a browser helper and the
window server): the reason for [the names in `by_process`](./trace-tables-count.md). Those numbers were **not re-measured**
for this guide; the recording is not in the clone.

## What was not reproduced

- Any `xctrace` call, and so `trace_tables`, `trace_count` and `trace_query` on a real `.trace` (no `.trace` at hand, E3).
- Any tool of `traces.py` or `gputrace_read.py`: Python could not be run by the session that wrote this guide.
- A hex dump of a record of a real `.gputrace`, or of a synthetic one (`xxd` could not be run): the layout is the code's.
- Opening a `.chrome-trace` in Perfetto or `chrome://tracing`.
- The tests named in this guide (they were read, not run).
- The cost of one `xctrace export` of a large table, and the size of a real `capture` file.

Back to the [index](./index.md).
