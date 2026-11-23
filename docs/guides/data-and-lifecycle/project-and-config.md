# The project file, `config.py` and `paths.py`

**Reader:** people who change settings, the project file or anything that opens a file of the runs folder. Reviewed 2026-11-16.

> **In short:** a repository can carry a small file saying "keep this project's recordings here". Because cleanup deletes
> files in that folder, it is checked hard. `config.py` holds the settings; `paths.py` stops a caller from naming a file it should not touch, even through a link.

Back to the [index](./index.md). Example: the project file `{"name": "mygame", "runs": "perf-runs"}` makes the tools use `perf-runs/`, write the mark `.metal-gpu-trace-runs` holding `mygame` there, and refuse the folder if another project's name is in the mark.

## The project file, the mark and the baselines

`metal-gpu-trace.json` (`project.py`, [ADR-0004](../../adr/0004-project-file.md)) lives in a repository and names the project and where its recordings go.

| Piece | Rule | Where |
|---|---|---|
| Keys | `name` and `runs` (required), `baseline`, `format`; any other key is refused by name (also a leftover `profile`, removed in 0.26.0 per `CHANGELOG.md`; the error says to delete it when `profile` is among the first five unknown keys it lists: known limit 1) | `project.py::KEYS`, `project.py::load` |
| `runs` folder | Must be new, empty (litter such as `.DS_Store` does not count) or carry the mark; a mark with another project's name refuses it. Checked hard because `KEEP_RUNS` deletes files there | `project.py:3-5`, `project.py::LITTER`, `project.py::checked` |
| `project.apply` | Points `config.OUT`, `config.READ[0]`, `config.BASELINES` at that folder and writes the mark | `project.py::apply`, `project.py::adopt` |

`baselines.json` is a JSON object keyed by baseline name; each value has `runs` (run names), `set` (a date), `summaries` (copies of those runs' summaries) and, if asked, `skip_s` (`analysis.py::tool_perf_baseline`). The real file has one baseline of three summaries ([E7](./evidence-runs.md#e7-the-baselines-file)). The copies are the point: `KEEP_RUNS` can delete the runs and `perf_check` still judges against the saved numbers (`config.py::reload`).

## `config.py`

Every module reads these as `config.NAME` when it uses them, never copied (`config.py:1-2`; [How it works](../how-it-works.md#two-rules-that-keep-it-testable)).

| Name | Meaning | Line |
|---|---|---|
| `OUT` | The runs folder, resolved | `config.py::reload` |
| `READ` | `OUT` plus the folders in `METAL_TRACE_READ`: what the tools may read | `config.py::reload` |
| `BASELINES` | `OUT/baselines.json` | `config.py::reload` |
| `MAX_DISK_MB` | The limit in MiB: a whole number of 1 or more in `METAL_TRACE_MAX_DISK_MB`, else `None` (no limit; no error for a bad value) | `config.py::reload` |
| `PROJECT`, `PROJECT_ERROR` | The project file in use, or what is wrong with it | `config.py::PROJECT` |
| `FAMILIES`, `WORKLOADS` | The two files in `data/`, loaded once at import | `config.py::FAMILIES` |
| `CACHE`, `LOCK` | The cache folder; the recording lock, shared by every runs folder | `config.py::CACHE`, `config.py::LOCK` |
| `MAX_LIMIT`, `MAX_TEXT` | Rows per page (500), characters per result (40 000) | `config.py::MAX_LIMIT` |

`config.reload` (`config.py::reload`) re-reads `METAL_TRACE_OUT`, `METAL_TRACE_READ` and `METAL_TRACE_MAX_DISK_MB` at import and again from `project.apply`; the rest is read once at import.

## `paths.py`

It keeps a caller from naming a file it should not touch. A runs folder may come from a clone or a download, and a link inside could point at any file (`paths.py::read_object`), hence the link checks.

| Function | What it guarantees | Line |
|---|---|---|
| `name_ok` | Letters, digits, `.`, `_`, `-` only, at most 120 bytes (a label is limited to 100 in `recording.record`, `recording.py::record`) | `paths.py::name_ok` |
| `run_path` | The `.json` of a named run; refuses a name outside that alphabet, `baselines.json`, `panel.json`, a link and a missing run | `paths.py::run_path` |
| `allowed` | A path inside `config.READ`, else a `ToolError` saying to add the directory | `paths.py::allowed` |
| `read_text`, `read_object` | Read never through a link (`O_NOFOLLOW`), without blocking on a pipe; `read_object` returns a JSON object or a `ToolError` naming what failed, never the path | `paths.py::read_text`, `paths.py::read_object` |
| `write_file` | Replaces a file, refusing a link | `paths.py::write_file` |
| `trace_path` | The `.trace` of a run name, or a path inside the readable folders | `paths.py::write_file` |
| `page` | One page of a list with `total`, `offset`, `next_offset` | `paths.py::write_file` |
| `check_cooldown`, `check_skip` | Seconds from 0 to 600, else a `ToolError` | `paths.py::check_cooldown`, `paths.py::check_skip` |
