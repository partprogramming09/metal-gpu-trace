"""What clients read: the tool list with its schemas, the resources and the prompts."""
from metal_gpu_trace import analysis, config, experiments, project, recording, screenshots, traces, winelog, workloads


OBJECT = {"type": "object"}
PAGED = {"type": "object", "required": ["total", "offset", "rows", "next_offset"],
         "properties": {"total": {"type": "integer"}, "offset": {"type": "integer"}, "rows": {"type": "array"},
                        "next_offset": {"type": ["integer", "null"]}}}
# optional on every tool; worker.call applies it, so it is added to each inputSchema in tools/list, not to TOOLS
FIELDS = {"type": "array", "items": {"type": "string"},
          "description": "result paths to keep, dotted: common.frame_pacing"}
PAGED_TOOLS = ("perf_runs", "trace_query", "capture_records")  # the tools that return page()


RESOURCES = {"metal-trace://gpu-families": ("Apple GPU families", config.FAMILIES["about"], lambda: config.FAMILIES)} | {
    f"metal-trace://gpu-families/{key.lower()}": (f"{key} GPU family", f"Apple's published facts for {key}",
                                                  lambda key=key: traces.tool_gpu_family(key))
    for key in config.FAMILIES["families"]}

S, I = {"type": "string"}, {"type": "integer"}
RUN = {**S, "description": "a run name from perf_runs"}
PAGE = {"offset": {**I, "description": "default 0"},
        "limit": {**I, "description": f"default 50, at most {config.MAX_LIMIT}"}}
TRACE = {**S, "description": "a run name from perf_runs with trace_kept or tables_kept true, or a .trace path"}
CAPTURE = {**S, "description": "a .gputrace bundle inside METAL_TRACE_OUT or METAL_TRACE_READ"}


def schema(properties, required=()):
    """Returns a JSON Schema object with these properties."""
    return {"type": "object", "properties": properties, "required": list(required)}


def hints(title, destructive=None, idempotent=False, open_world=False):
    """Returns a tool's MCP annotations: read-only unless `destructive` says whether its writes stop programs."""
    if destructive is None:
        return {"title": title, "readOnlyHint": True, "openWorldHint": open_world}
    return {"title": title, "readOnlyHint": False, "destructiveHint": destructive, "idempotentHint": idempotent,
            "openWorldHint": open_world}


FILES = {"type": "array", "items": {"type": "string"}, "maxItems": 32,
         "description": "files to hash into the summary; compare shows changes"}
RECORD_PROPS = {"label": {**S, "description": "run name: letters, digits, '.', '_', '-'"},
         "program": {**S, "description": "path of the .exe, or of the macOS binary with wine=native"},
         "seconds": {**I, "description": "seconds, default 20; 30 under Wine (start-up eats part); the export takes minutes under Wine"},
         "wine": {**S, "description": "Wine directory holding bin/wine, or native"},
         "prefix": {**S, "description": "Wine prefix, default WINEPREFIX or ~/.wine; ignored with native"},
         "workdir": {**S, "description": "directory to start in, default the program's own"},
         "args": {**S, "description": "program arguments as in a shell"},
         "workload": {**S, "description": "a test program from workload_list (fetch it first) instead of program"},
         "api": {**S, "description": "with workload: mtl, mtl-x64 (Metal under Rosetta), vk (needs METAL_TRACE_MOLTENVK), d3d11 or d3d12 (under wine)"},
         "dim": {**I, "description": "with drawstress: cube grid side, dim^3 draws per frame"},
         "example": {**S, "description": "with a workload that lists examples: the one to run"},
         "size": {**S, "description": "with drawstress: window size, such as 1920x1080"},
         "memory": {"type": "boolean", "description": "default true; false skips the slowest table, Metal memory (no metal_mib_peak)"},
         "env": {**S, "description": "NAME=VALUE pairs separated by spaces; MTL_SHADER_VALIDATION=1 or MTL_DEBUG_LAYER=1 adds `validation`"},
         "memory_free_pct": {**I, "description": "macOS, 20 to 60: holds the whole Mac at this % RAM free while recording; lower can freeze it"},
         "background": {"type": "boolean", "description": "macOS, default false; true throttles the program hard and unevenly (taskpolicy -b): repeat the run"},
         "counters": {"type": "boolean", "description": "default false; true adds gpu_counters; not on Windows; about 40 s of read-back per second"},
         "tier": {**S, "enum": list(recording.TIERS),
                  "description": "default standard. light: no memory or counters; standard: memory; deep: also counters and a kept .trace (macOS). memory and counters given alone override"},
         "fingerprint_paths": FILES}

# the experiment tools take perf_record's arguments: the full text is in perf_record, the same list holds it
SAME = {k: {t: v[t] for t in ("type", "enum") if t in v} for k, v in RECORD_PROPS.items() if k != "fingerprint_paths"}

SKIP = "seconds to leave out at the start (shaders compile, resources load), default 0; GPU numbers, hitches and Metal memory are recomputed without them"
COOLDOWN = {"type": "number", "description": "seconds to rest between recordings, 0 to 600, default 0; 60 on a laptop is a start, thermal_state_share says if it throttled"}
NAME = {**S, "description": "name: letters, digits, '.', '_', '-'"}

TOOLS = {
    "perf_record": (recording.tool_perf_record, schema(RECORD_PROPS, ["label"]), hints("Record a program", destructive=True)),
    "perf_baseline_record": (experiments.tool_perf_baseline_record, schema(
        {"name": NAME,
         "count": {**I, "description": "equal recordings to make, default 3"},
         "cooldown_s": COOLDOWN,
                  "skip_s": {"type": "number", "description": SKIP + "; perf_check applies the same cut"},
         **{k: v for k, v in SAME.items() if k != "label"}}, ["name"]),
        hints("Record a reference", destructive=True)),
    "perf_sweep": (experiments.tool_perf_sweep, schema(
        {"name": NAME,
         "variable": {**S, "description": "what changes: dim, example, api, size, or env:NAME"},
         "values": {"type": "array", "items": {"type": ["string", "integer"]},
                    "description": "2 to 8 values of the variable, such as [10, 20, 30] for dim"},
         "rounds": {**I, "description": "default 1, at most 5 and 24 recordings in all"},
         "metric": {**S, "description": "app_metrics.<column>, a column of the program's telemetry"},
         "cooldown_s": COOLDOWN,
                  "skip_s": {"type": "number", "description": SKIP},
         **{k: v for k, v in SAME.items() if k != "label"}}, ["name", "variable", "values"]),
        hints("Record one run per value of a variable", destructive=True)),
    "perf_ab": (experiments.tool_perf_ab, schema(
        {"name": NAME,
         "env_a": {**S, "description": "NAME=VALUE pairs for side A, the reference (empty: none)"},
         "env_b": {**S, "description": "NAME=VALUE pairs for side B, the change under test (empty: none)"},
         "rounds": {**I, "description": "A B B A rounds, default 1 (4 recordings), at most 5"},
         "cooldown_s": COOLDOWN,
                  "skip_s": {"type": "number", "description": SKIP},
         "fingerprint_paths": FILES,
         **{k: v for k, v in SAME.items() if k not in ("label", "env")}}, ["name", "env_a", "env_b"]),
        hints("Record two settings in A B B A order", destructive=True)),
    "perf_cold_warm": (experiments.tool_perf_cold_warm, schema(
        {"name": NAME,
         **{k: v for k, v in SAME.items() if k != "label"}}, ["name"]),
        hints("Record a run twice to find first-seen shader stutter", destructive=True)),
    "perf_attach": (recording.tool_perf_attach, schema(
        {"label": NAME,
         "process": {**S, "description": "pid, or a name in the program's command line such as Game.exe"},
         "seconds": {**I, "description": "recording length, default 20"}},
        ["label", "process"]), hints("Record a running program", destructive=False)),
    "project_info": (project.tool_project_info, schema({}), hints("Show the active project")),
    "perf_runs": (analysis.tool_perf_runs, schema(PAGE), hints("List recordings")),
    "perf_compare": (analysis.tool_perf_compare, schema(
        {"a": {**S, "description": "run name from perf_runs: the reference, such as the run before a change"},
         "b": {**S, "description": "run name from perf_runs: the run to compare against a"},
         "short_us": {**I, "description": "an encoder under this GPU time counts as short: 10, 25 (default), 50, 100, "
                                          "250, 500 or 1000"},
         "markdown": {"type": "boolean", "description": "also return the numbers as Markdown tables, default false"},
         "skip_s": {"type": "number", "description": SKIP}},
        ["a", "b"]),
        hints("Compare two recordings")),
    "perf_baseline": (analysis.tool_perf_baseline, schema(
        {"name": {**S, "description": "reference name; alone, shows that reference"},
         "runs": {"type": "array", "items": S, "description": "run names to save as this reference, ideally 3 or more equal runs"},
         "skip_s": {"type": "number", "description": SKIP + "; perf_check applies the same cut"}}),
        hints("Name a reference", destructive=False, idempotent=True)),
    "perf_check": (analysis.tool_perf_check, schema(
        {"run": RUN,
         "baseline": {**S, "description": "a reference name from perf_baseline"},
         "margin_pct": {"type": "number", "description": "how far outside the reference's range FPS or GPU ms per "
                                                         "frame may fall before counting, default 3"}},
        ["run", "baseline"]), hints("Check a run against a reference")),
    "perf_export_trace": (traces.tool_perf_export_trace, schema(
        {"run": RUN}, ["run"]),
        hints("Export frames to Perfetto", destructive=False, idempotent=True)),
    "perf_gate": (analysis.tool_perf_gate, schema(
        {"run": RUN,
         "fps_min": {"type": "number", "description": "the FPS must be at least this"},
         "fps_1pct_low_min": {"type": "number", "description": "the 1% low FPS must be at least this"},
         "stutter_rate_pct_max": {"type": "number", "description": "the share of stutter frames, in %, at most this"},
         "gpu_ms_p95_max": {"type": "number", "description": "the p95 GPU ms per frame at most this"},
         "hitches_max": {"type": "number", "description": "the number of hitches at most this"},
         "metal_mib_max": {"type": "number", "description": "the peak Metal memory in MiB at most this"},
         "skip_s": {"type": "number", "description": SKIP}}, ["run"]),
        hints("Check a run against budgets")),
    "perf_history": (analysis.tool_perf_history, schema(
        {"prefix": {**S, "description": "the start of the run names to follow: letters, digits, '.', '_', '-'"},
         "limit": {**I, "description": "newest runs to keep, default 50"},
         "skip_s": {"type": "number", "description": SKIP}}, ["prefix"]),
        hints("Follow a number across runs")),
    "perf_diagnose": (analysis.tool_perf_diagnose, schema(
        {"run": RUN,
         "min_encoders": {**I, "description": "encoders per frame (median) from which the verdict can be yes, default 4"},
         "short_us": {**I, "description": "an encoder under this GPU time counts as short: 10, 25 (default), 50, 100, "
                                          "250, 500 or 1000"},
         "short_share": {"type": "number", "description": "share of short encoders from which the verdict is yes, "
                                                          "default 0.25"}}, ["run"]),
        hints("Diagnose encoder use")),
    "perf_memory_breakdown": (analysis.tool_perf_memory_breakdown, schema(
        {"run": RUN,
         "top": {**I, "description": "how many resource types to keep, the largest allocated first, default 10"}}, ["run"]),
        hints("Break down Metal allocations by type")),
    "trace_tables": (traces.tool_trace_tables, schema({"trace": TRACE}, ["trace"]), hints("List a trace's tables")),
    "trace_count": (traces.tool_trace_count, schema(
        {"trace": TRACE,
         "tables": {"type": "array", "items": S, "description": "table names from trace_tables; default the tables "
                                                                 "that matter for a translation layer"}}, ["trace"]),
                    hints("Count a trace's rows")),
    "trace_query": (traces.tool_trace_query, schema(
        {"trace": TRACE, "schema": {**S, "description": "a table name that trace_tables lists, such as metal-gpu-intervals"},
         "pid": {**I, "description": "keep only this process's rows"},
         "window_ms": {"type": "integer", "description": "1 to 3600000: time windows of this many ms instead of rows (needs a start or time column)"},
         "where": {"type": "array", "description": "tables file only, joined by AND: {column, op, value}, op one of = != < <= > >=; a time or size column holds its number as text: compare with a number",
                   "items": {"type": "object", "properties": {"column": S, "op": {**S, "enum": ["=", "!=", "<", "<=", ">", ">="]},
                                                            "value": {"type": ["string", "number", "null"]}},
                             "required": ["column", "op", "value"]}},
         "columns": {"type": "array", "items": S, "description": "tables file only: keep these columns"},
         "order_by": {**S, "description": "tables file only: a column, or with group_by an aggregate name such as count or sum_duration"},
         "descending": {"type": "boolean", "description": "with order_by, largest first"},
         "group_by": {"type": "array", "items": S, "description": "tables file only: group rows by these columns (each group gets its count)"},
         "aggregates": {"type": "array", "description": "tables file only: {fn, column}, fn count, sum, avg, min or max; named fn_column",
                        "items": {"type": "object", "properties": {"fn": {**S, "enum": ["count", "sum", "avg", "min", "max"]}, "column": S},
                                  "required": ["fn"]}},
         **PAGE}, ["trace", "schema"]),
                    hints("Read a trace table")),
    "capture_summary": (traces.tool_capture_summary, schema({"capture": CAPTURE}, ["capture"]), hints("Summarize a capture")),
    "capture_diff": (traces.tool_capture_diff, schema(
        {"a": {**CAPTURE, "description": "the first .gputrace (usually the one before a change)"},
         "b": {**CAPTURE, "description": "the second .gputrace"}}, ["a", "b"]),
                     hints("Compare two captures")),
    "capture_records": (traces.tool_capture_records, schema({"capture": CAPTURE, **PAGE}, ["capture"]),
                        hints("Read a capture's records")),
    "screenshots_check": (screenshots.tool_screenshots_check, schema(
        {"path": {**S, "description": "a PNG, or a folder of PNGs (in a readable folder), 100 at most"},
         "sequence": {"type": "boolean", "description": "true: the PNGs, in name order, are frames of one run; adds frozen and flicker"},
         "ignore_rects": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}, "maxItems": 8,
                          "description": "areas to leave out, [x0, y0, x1, y1] as fractions 0 to 1"}}, ["path"]),
                          hints("Flag black, flat, frozen or flickering screenshots")),
    "wine_log_census": (winelog.tool_wine_log_census, schema(
        {"path": {**S, "description": "a Wine debug log, or a folder of logs (in a readable folder), 50 at most"},
         "top": {**I, "description": "messages to list, 1 to 100, default 15"}}, ["path"]),
                        hints("Count what a Wine log says is missing or wrong")),
    "gpu_family": (traces.tool_gpu_family, schema(
        {"name": {**S, "description": "a family (Apple7 to Apple10) or a chip (M1 Pro, M2, M4 Max, A17 Pro)"}},
        ["name"]), hints("Apple GPU family facts")),
    "workload_list": (workloads.tool_workload_list, schema({}), hints("List test programs")),
    "workload_fetch": (workloads.tool_workload_fetch, schema(
        {"name": {**S, "description": "a workload name from workload_list, such as drawstress"}}, ["name"]),
        hints("Download a test program", destructive=False, idempotent=True, open_world=True)),
    "presentmon_install": (workloads.tool_presentmon_install, schema({}),
                           hints("Install PresentMon (Windows)", destructive=False, idempotent=True, open_world=True)),
}
# Claude Code asks the user before every call of these tools
META = {"workload_fetch": {"anthropic/requiresUserInteraction": True},
        "presentmon_install": {"anthropic/requiresUserInteraction": True}}

PROMPTS = {
    "compare-layer": {
        "description": "Records a test program in native Metal and under a translation layer, then diagnoses and "
                       "compares both runs",
        "arguments": [{"name": "workload", "description": "a workload from workload_list, default drawstress"},
                      {"name": "api", "description": "the API run under Wine: d3d12 (default) or d3d11"}],
    },
    "diagnose-stutter": {
        "description": "Records a program twice to tell first-seen shader stutter from steady stutter, then diagnoses it",
        "arguments": [{"name": "workload", "description": "a workload from workload_list, default drawstress"},
                      {"name": "api", "description": "the API the workload runs: mtl (default, native Metal), d3d12 or d3d11"}],
    },
    "bisect-regression": {
        "description": "Finds the commit that made a workload slower: git bisect, with a recording and a check at each step. "
                       "The recordings use a workload, so a commit must change what the workload runs (its arguments or "
                       "environment)",
        "arguments": [{"name": "good_rev", "required": True,
                       "description": "a commit, tag or branch name that was fast (letters, digits, . _ -)"},
                      {"name": "bad_rev", "required": True,
                       "description": "a commit, tag or branch name that is slow (letters, digits, . _ -)"},
                      {"name": "workload", "description": "the workload to record, default drawstress"},
                      {"name": "api", "description": "the API the workload runs: mtl (default, native Metal), d3d12 or d3d11"}],
    },
}  # each prompt also holds "render", the function that builds its text from the arguments; prompts/list leaves it out


def prompt_compare_layer(workload="drawstress", api="d3d12"):
    """Returns the steps of the compare-layer prompt for `workload` and `api`."""
    return (
        f"Compare {workload} in native Metal with {workload} through {api} under the Wine in METAL_TRACE_WINE, with "
        "the metal-trace tools:\n"
        f"1. workload_fetch name={workload} (it is skipped when already downloaded).\n"
        f"2. perf_record label={workload}-mtl workload={workload} api=mtl seconds=20.\n"
        f"3. perf_record label={workload}-{api} workload={workload} api={api} seconds=30.\n"
        "4. perf_compare a=<the mtl run> b=<the other run>, and perf_diagnose on the other run for its verdict.\n"
        "Report perf_compare's metrics and encoders as one table (a, b, change), then its labels with the largest "
        "change in GPU ms per frame, then the verdict. Say which runs are in too_short, and that one pair of runs is "
        "not enough to call a difference real: repeat both before concluding."
    )


PROMPTS["compare-layer"]["render"] = prompt_compare_layer


def prompt_diagnose_stutter(workload="drawstress", api="mtl"):
    """Returns the steps of the diagnose-stutter prompt for `workload` run with `api`."""
    return (
        f"Find out whether {workload} stutters because pipelines are built while it runs, with the metal-trace tools:\n"
        f"1. workload_fetch name={workload} (it is skipped when already downloaded).\n"
        f"2. perf_cold_warm name={workload}-stutter workload={workload} api={api} seconds=30. It records the program twice.\n"
        "3. Read first_seen_hitches (shader_compile hitches only the first run had), extra_hitches_in_first (hitches of "
        "any cause the first run had more) and compiler_busy_ms of both runs.\n"
        "4. perf_diagnose run=<the first run's name> and perf_diagnose run=<the second run's name>: its stutter_analysis "
        "is the steady state.\n"
        "Say which case it is: first_seen_hitches above 0 means the first frames compile shaders (cache them or build "
        "the pipelines at load); hitches in both runs with causes other than shader_compile mean steady stutter, and "
        "the stutter_analysis of perf_diagnose says where to look. Name the cause counts you read. A run with `unpresented` in "
        "perf_diagnose had its window hidden: record it again with the window visible before concluding. A run under 100 frames is "
        "too_short to trust, and one pair of runs is not enough to call a cause real: repeat before concluding."
    )


def prompt_bisect_regression(good_rev, bad_rev, workload="drawstress", api="mtl"):
    """Returns the steps of the bisect-regression prompt. A revision that starts with '-' would be read by git as an
    option, so it is refused (the protocol answers with an invalid-params error)."""
    good_rev, bad_rev = str(good_rev), str(bad_rev)  # the protocol passes a number as it came
    if good_rev.startswith("-") or bad_rev.startswith("-"):
        raise TypeError("a revision does not start with '-'")
    return (
        f"Find the commit that made {workload} slower, between {good_rev} (fast) and {bad_rev} (slow). You run git with "
        "your own permissions: this server runs no commands. Work in the program's repository, with a clean tree.\n"
        f"1. workload_fetch name={workload} (it is skipped when already downloaded).\n"
        f"2. git checkout {good_rev}, then perf_baseline_record name=bisect-good workload={workload} api={api} seconds=30.\n"
        f"3. git bisect start {bad_rev} {good_rev}\n"
        f"4. At each step perf_record label=bisect-<short commit> workload={workload} api={api} seconds=30, then "
        "perf_check run=<that run> baseline=bisect-good. It is good when perf_check does not report a regression.\n"
        "5. Repeat step 4 once before you mark the commit: one run is not enough to call it slow. If the two "
        "disagree, record a third and take the majority; a run under 100 frames is too_short, record it again longer.\n"
        "6. git bisect good or git bisect bad, and go on until git names the first bad commit. Then git bisect reset.\n"
        "Report that commit, and the perf_check numbers of the last good and the first bad step."
    )


PROMPTS["diagnose-stutter"]["render"] = prompt_diagnose_stutter
PROMPTS["bisect-regression"]["render"] = prompt_bisect_regression
