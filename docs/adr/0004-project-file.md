# ADR-0004: A project file in each repository picks the recordings folder

**Reader:** people

- **Status:** accepted
- **Date:** 2026-11-12
- **Decided by:** the maintainer

## Context
Every recording went to one folder, `METAL_TRACE_OUT` (usually `~/perf-runs`), whatever project it belonged to. With
several projects on one Mac (a translation layer, its test programs, a game), their recordings mixed: `perf_runs`
listed them all, `baselines.json` held every project's references, and `KEEP_RUNS` pruned one project's recordings to
make room for another's. The server is set up once per user (`claude mcp add --scope user`), so the variable cannot
differ per project.

## Decision
A repository may hold a `metal-gpu-trace.json` with the project's `name`, its recordings folder `runs`, and optionally
its `profile`, `baseline` and `format`. At start-up the server looks for the file in its working directory and the
folders above it, stopping below the home folder; `METAL_TRACE_PROJECT` names it instead. When found, `runs` replaces
`METAL_TRACE_OUT` for recording and reading, and `baselines.json` moves with it. The recording lock stays global (one
recording at a time on the Mac). The `runs` folder must be new, empty or carry the server's mark
(`.metal-gpu-trace-runs`), because `KEEP_RUNS` removes old `.json` files in it. A wrong file does not stop the server:
every tool answers with what is wrong. `project_info` says which project is active; the panel uses `profile` (which metric
leads) and `baseline` (the reference every run is judged against).

## Alternatives considered
| Option | For | Against | Why yes / no |
|---|---|---|---|
| File in each repository (chosen) | Lives with the code it measures; one file covers every folder below it | One more file per repository | Yes |
| Central registry (one file listing projects and their folders) | One place to edit | Must be kept in step with repositories that move; machine-specific paths | No |
| Scan for recordings by program name | Nothing to write | Guesses; the same program can belong to several projects | No |
| Filter `~/perf-runs` by a prefix or tag | No new folder | `KEEP_RUNS` and `baselines.json` stay shared, the real problem | No |
| MCP roots (the client says which folders are open) | Follows the client's open folder | Deprecated in protocol revision 2026-07-28 (SEP-2577), which tells servers to take folders from tool parameters, resources or server configuration; not every client sends roots | No |

Source for roots: https://modelcontextprotocol.io/specification/2026-07-28/client/roots and
https://modelcontextprotocol.io/specification/versioning, read on 2026-11-12.

## Consequences
- **Positive:** each project keeps its own recordings, references and pruning; without a project file nothing changes.
- **Negative / cost:** the working directory decides the project, so a client started elsewhere uses another folder or
  none; `project_info` makes that visible.
- **Harder:** recordings already in a shared folder must be moved by hand to their project's folder.

## Revisit when
A client needs one server for several projects at once (the folder would then come from each tool call), or the
project file needs a format other than metal-gpu-trace's own recordings.
