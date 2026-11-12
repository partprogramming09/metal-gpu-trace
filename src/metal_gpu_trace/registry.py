"""What clients read: the tool list with its schemas, the resources and the prompts."""
from metal_gpu_trace import analysis, config, experiments, panel, recording, traces, workloads


OBJECT = {"type": "object"}
PAGED = {"type": "object", "required": ["total", "offset", "rows", "next_offset"],
         "properties": {"total": {"type": "integer"}, "offset": {"type": "integer"}, "rows": {"type": "array"},
                        "next_offset": {"type": ["integer", "null"]}}}
PAGED_TOOLS = ("perf_runs", "trace_query", "capture_records")  # the tools that return page()


RESOURCES = {"metal-trace://gpu-families": ("Apple GPU families", config.FAMILIES["about"], lambda: config.FAMILIES)} | {
    f"metal-trace://gpu-families/{key.lower()}": (f"{key} GPU family", f"Apple's published facts for {key}",
                                                  lambda key=key: traces.tool_gpu_family(key))
    for key in config.FAMILIES["families"]}

S, I = {"type": "string"}, {"type": "integer"}
PAGE = {"offset": {**I, "description": "first row, default 0"},
        "limit": {**I, "description": f"rows per page, default 50, at most {config.MAX_LIMIT}"}}
TRACE = {**S, "description": "a run name from perf_runs whose trace_kept is true, or the path of a .trace"}
CAPTURE = {**S, "description": "path of a .gputrace bundle saved from Xcode, inside METAL_TRACE_OUT or METAL_TRACE_READ"}


def schema(properties, required=()):
    """Returns a JSON Schema object with these properties."""
    return {"type": "object", "properties": properties, "required": list(required)}


def hints(title, destructive=None, idempotent=False, open_world=False):
    """Returns a tool's MCP annotations: read-only unless `destructive` says whether its writes stop programs."""
    if destructive is None:
        return {"title": title, "readOnlyHint": True, "openWorldHint": open_world}
    return {"title": title, "readOnlyHint": False, "destructiveHint": destructive, "idempotentHint": idempotent,
            "openWorldHint": open_world}


RECORD_PROPS = {"label": {**S, "description": "name for the run: letters, digits, '.', '_', '-'"},
         "program": {**S, "description": "path of the .exe, or of the macOS binary with wine=native"},
         "seconds": {**I, "description": "recording length, default 20; use 30 under Wine, whose start-up takes part of it; the export afterwards takes several minutes under Wine"},
         "wine": {**S, "description": "Wine directory holding bin/wine, or native"},
         "prefix": {**S, "description": "Wine prefix, default WINEPREFIX or ~/.wine; ignored with native"},
         "workdir": {**S, "description": "directory the program starts in, default the program's own"},
         "args": {**S, "description": "program arguments as in a shell, quotes included"},
         "workload": {**S, "description": "a test program from workload_list, fetched with workload_fetch, instead "
                                          "of program"},
         "api": {**S, "description": "with workload: mtl (native Metal), mtl-x64 (Metal built for x86_64, run under Rosetta like Wine), vk (Vulkan through MoltenVK: set "
                                                        "METAL_TRACE_MOLTENVK), d3d11 or d3d12 (under wine)"},
         "dim": {**I, "description": "with workload drawstress: side of the cube grid, dim^3 draws per frame"},
         "example": {**S, "description": "with a workload that lists examples in workload_list: the one to run"},
         "size": {**S, "description": "with a workload that has size_variables (drawstress): the window size, WIDTHxHEIGHT such as 1920x1080"},
         "memory": {"type": "boolean", "description": "default true; false skips the Metal memory table, the slowest "
                                                      "to read (about 40 % faster summary): no metal_mib_peak"},
         "env": {**S, "description": "NAME=VALUE pairs separated by spaces, set in the program's environment; MTL_SHADER_VALIDATION=1 or MTL_DEBUG_LAYER=1 adds `validation` to the summary: the layers' messages counted by kind"},
         "memory_free_pct": {**I, "description": "macOS only, 20 to 60: holds the whole Mac at this percentage of RAM free "
                                                 "while recording (memory_pressure), to see how the program behaves short of memory; lower can freeze the Mac"},
         "background": {"type": "boolean", "description": "macOS only, default false; true runs the program under taskpolicy -b, "
                                                        "which throttles it hard and unevenly (drawstress: 18 to 280 times slower): repeat the run"},
         "counters": {"type": "boolean", "description": "default false; true also records Metal GPU Counters (gpu_counters in "
                                                        "the summary); not under Windows; adds about 40 s of read-back per recorded second"}}

SKIP = ("seconds to leave out at the start of each recording, where shaders compile and resources load; 0 (default) "
        "keeps all. The GPU numbers, hitches and Metal memory are recomputed without them")

TOOLS = {
    "perf_record": (recording.tool_perf_record, schema(RECORD_PROPS, ["label"]), hints("Record a program", destructive=True)),
    "perf_baseline_record": (experiments.tool_perf_baseline_record, schema(
        {"name": {**S, "description": "reference name: letters, digits, '.', '_', '-'"},
         "count": {**I, "description": "equal recordings to make, default 3"},
         "skip_s": {"type": "number", "description": SKIP + "; perf_check applies the same cut to the run it judges"},
         **{k: v for k, v in RECORD_PROPS.items() if k != "label"}}, ["name"]),
        hints("Record a reference", destructive=True)),
    "perf_sweep": (experiments.tool_perf_sweep, schema(
        {"name": {**S, "description": "name for the runs: letters, digits, '.', '_', '-'"},
         "variable": {**S, "description": "what changes between runs: dim, example, api, size, or env:NAME for an environment variable"},
         "values": {"type": "array", "items": {"type": ["string", "integer"]},
                    "description": "2 to 8 values of the variable, such as [10, 20, 30] for dim"},
         "rounds": {**I, "description": "rounds, default 1, at most 5 and at most 24 recordings in all; every other round runs the values in reverse"},
         "skip_s": {"type": "number", "description": SKIP},
         **{k: v for k, v in RECORD_PROPS.items() if k != "label"}}, ["name", "variable", "values"]),
        hints("Record one run per value of a variable", destructive=True)),
    "perf_ab": (experiments.tool_perf_ab, schema(
        {"name": {**S, "description": "name for the runs: letters, digits, '.', '_', '-'"},
         "env_a": {**S, "description": "NAME=VALUE pairs for side A, the reference (empty: none)"},
         "env_b": {**S, "description": "NAME=VALUE pairs for side B, the change under test (empty: none)"},
         "rounds": {**I, "description": "A B B A rounds, default 1 (4 recordings), at most 5"},
         "skip_s": {"type": "number", "description": SKIP},
         **{k: v for k, v in RECORD_PROPS.items() if k not in ("label", "env")}}, ["name", "env_a", "env_b"]),
        hints("Record two settings in A B B A order", destructive=True)),
    "perf_cold_warm": (experiments.tool_perf_cold_warm, schema(
        {"name": {**S, "description": "name for the runs: letters, digits, '.', '_', '-'"},
         **{k: v for k, v in RECORD_PROPS.items() if k != "label"}}, ["name"]),
        hints("Record a run twice to find first-seen shader stutter", destructive=True)),
    "perf_attach": (recording.tool_perf_attach, schema(
        {"label": {**S, "description": "name for the run: letters, digits, '.', '_', '-'"},
         "process": {**S, "description": "pid, or a name in the program's command line such as Game.exe"},
         "seconds": {**I, "description": "recording length, default 20; the export afterwards takes several minutes under Wine"}},
        ["label", "process"]), hints("Record a running program", destructive=False)),
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
        {"name": {**S, "description": "reference name: letters, digits, '.', '_', '-'; alone, shows that reference"},
         "runs": {"type": "array", "items": S, "description": "run names from perf_runs to save as this reference, "
                                                             "ideally 3 or more equal runs; replaces a previous one"},
         "skip_s": {"type": "number", "description": SKIP + "; perf_check applies the same cut to the run it judges"}}),
        hints("Name a reference", destructive=False, idempotent=True)),
    "perf_check": (analysis.tool_perf_check, schema(
        {"run": {**S, "description": "a run name from perf_runs"},
         "baseline": {**S, "description": "a reference name from perf_baseline"},
         "margin_pct": {"type": "number", "description": "how far outside the reference's range FPS or GPU ms per "
                                                         "frame may fall before counting, default 3"}},
        ["run", "baseline"]), hints("Check a run against a reference")),
    "perf_export_trace": (traces.tool_perf_export_trace, schema(
        {"run": {**S, "description": "a run name from perf_runs"}}, ["run"]),
        hints("Export frames to Perfetto", destructive=False, idempotent=True)),
    "perf_gate": (analysis.tool_perf_gate, schema(
        {"run": {**S, "description": "a run name from perf_runs"},
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
    "perf_panel": (panel.tool_perf_panel, schema(
        {"name": {**S, "description": "name for the panel file: letters, digits, '.', '_', '-'"},
         "runs": {"type": "array", "items": S, "description": "one or two run names from perf_runs; with two, the first "
                                                             "is A, the reference"},
         "preset": {**S, "description": "fps (default) or compare (needs two runs)"},
         "skip_s": {"type": "number", "description": SKIP},
         "layout": {"type": "array", "items": S, "description": "tabs to show, in order: summary, ab, frames, encoders, counters, memory, data; "
                                                                "saved as panel.json in the runs directory as the default for every panel"}},
        ["name", "runs"]),
        hints("Write an HTML panel", destructive=False, idempotent=True)),
    "perf_diagnose": (analysis.tool_perf_diagnose, schema(
        {"run": {**S, "description": "a run name from perf_runs"},
         "min_encoders": {**I, "description": "encoders per frame (median) from which the verdict can be yes, default 4"},
         "short_us": {**I, "description": "an encoder under this GPU time counts as short: 10, 25 (default), 50, 100, "
                                          "250, 500 or 1000"},
         "short_share": {"type": "number", "description": "share of short encoders from which the verdict is yes, "
                                                          "default 0.25"}}, ["run"]),
        hints("Diagnose encoder use")),
    "trace_tables": (traces.tool_trace_tables, schema({"trace": TRACE}, ["trace"]), hints("List a trace's tables")),
    "trace_count": (traces.tool_trace_count, schema(
        {"trace": TRACE,
         "tables": {"type": "array", "items": S, "description": "table names from trace_tables; default the tables "
                                                                 "that matter for a translation layer"}}, ["trace"]),
                    hints("Count a trace's rows")),
    "trace_query": (traces.tool_trace_query, schema(
        {"trace": TRACE, "schema": {**S, "description": "a table name that trace_tables lists, such as metal-gpu-intervals"},
         "pid": {**I, "description": "keep only this process's rows"}, **PAGE}, ["trace", "schema"]),
                    hints("Read a trace table")),
    "capture_summary": (traces.tool_capture_summary, schema({"capture": CAPTURE}, ["capture"]), hints("Summarize a capture")),
    "capture_records": (traces.tool_capture_records, schema({"capture": CAPTURE, **PAGE}, ["capture"]),
                        hints("Read a capture's records")),
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
