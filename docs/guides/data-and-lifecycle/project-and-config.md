# The project file, `config.py` and `paths.py`

**Reader:** people who change settings, the project file or anything that opens a file of the runs folder. Reviewed 2026-11-16.

Español: [El archivo de proyecto, `config.py` y `paths.py`](../../es/guides/datos-y-su-ciclo-de-vida/proyecto-y-configuracion.md)

> **In short:** a repository can carry a small file that says "keep this project's recordings here". Because the
> cleanup deletes files in that folder, the folder is checked hard before use. Two modules guard the rest: `config.py`
> holds the settings and `paths.py` stops a caller from naming a file it should not touch, including through a link.

Back to the [index](./index.md). Example: a project file `{"name": "mygame", "runs": "perf-runs"}` makes the tools use
`perf-runs/`, write the mark `.metal-gpu-trace-runs` holding `mygame` there, and refuse the folder if another project's
name is in that mark.

## The project file, the mark and the baselines

`metal-gpu-trace.json` (`project.py`, [ADR-0004](../../adr/0004-project-file.md)) lives in a repository and names the
project and where its recordings go.

| Piece | Rule | Where |
|---|---|---|
| Keys | `name` and `runs` (required), `baseline` and `format`; any other key is refused with its name (also a leftover `profile` key, removed in 0.26.0 according to `CHANGELOG.md`: known limit 1) | `project.py:15`, `:43-46` |
| `runs` folder | Must be new, empty (desktop litter such as `.DS_Store` does not count) or carry the mark; a mark holding another project's name refuses it. Checked hard because `KEEP_RUNS` deletes files there | `project.py:3-5`, `:17`, `:94-105` |
| `project.apply` | Points `config.OUT`, `config.READ[0]` and `config.BASELINES` at that folder and writes the mark | `project.py:162-189`, `:192-201` |

`baselines.json` is a JSON object whose keys are the baseline names; each value has `runs` (the run names), `set` (a
date), `summaries` (copies of those runs' summaries) and, if asked for, `skip_s` (`analysis.py:279-280`). In the real
file ([E7](./evidence-runs.md#e7-the-baselines-file)) the single baseline holds three summaries. The copies are the
point: `KEEP_RUNS` can delete the runs the baseline was made from and `perf_check` still judges against the saved
numbers (`config.py:18`).

## `config.py`

It holds the settings, and every other module reads them as `config.NAME` at the moment it uses them, never copied
(`config.py:1-2`; the rule is explained in [How it works](../how-it-works.md#two-rules-that-keep-it-testable)).

| Name | Meaning | Line |
|---|---|---|
| `OUT` | The runs folder, resolved | `config.py:16` |
| `READ` | `OUT` plus the folders in `METAL_TRACE_READ`: what the tools may read | `config.py:17` |
| `BASELINES` | `OUT/baselines.json` | `config.py:19` |
| `MAX_DISK_MB` | The byte limit in MiB: a whole number of 1 or more in `METAL_TRACE_MAX_DISK_MB`, else `None` (no limit; no error for a bad value) | `config.py:22-23` |
| `PROJECT`, `PROJECT_ERROR` | The project file in use, or what is wrong with it | `config.py:33-34` |
| `FAMILIES`, `WORKLOADS` | The two files in `data/`, loaded once at import | `config.py:35-36` |
| `CACHE` | The cache folder | `config.py:37-40` |
| `LOCK` | The recording lock, shared by every runs folder | `config.py:42` |
| `MAX_LIMIT`, `MAX_TEXT` | Rows per page (500) and characters per result (40 000) | `config.py:43-45` |

`config.reload` (`config.py:11`) re-reads `METAL_TRACE_OUT`, `METAL_TRACE_READ` and `METAL_TRACE_MAX_DISK_MB`; it runs at
import and again from `project.apply`. Anything else in this file is read once at import.

## `paths.py`

It keeps a caller from naming a file it should not touch:

| Function | What it guarantees | Line |
|---|---|---|
| `name_ok` | A name of letters, digits, `.`, `_`, `-` only and at most 120 bytes (a label is limited to 100 in `recording.record`, `recording.py:312`) | `paths.py:25` |
| `run_path` | The `.json` of a named run; refuses a name outside that alphabet, `baselines.json`, `panel.json`, a link and a missing run | `paths.py:33` |
| `allowed` | A path inside `config.READ`, else a `ToolError` that says to add the directory | `paths.py:17` |
| `read_text`, `read_object` | Read a file of the runs folder never through a link (`O_NOFOLLOW`), without blocking on a pipe; `read_object` returns a JSON object or a `ToolError` that names what failed, never the path | `paths.py:43`, `:54` |
| `write_file` | Replaces a file, refusing a link | `paths.py:69` |
| `trace_path` | The `.trace` of a run name, or a path inside the readable folders | `paths.py:83` |
| `page` | One page of a list with `total`, `offset` and `next_offset` | `paths.py:94` |
| `check_cooldown`, `check_skip` | Seconds from 0 to 600, else a `ToolError` | `paths.py:102`, `:118` |

The reason for the link checks is written in the code: a runs folder may come from a clone or a download, and a link
inside it could point at any file (`paths.py:55-57`).
