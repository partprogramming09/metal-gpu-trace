# ADR-0005: Remove the HTML panel

**Reader:** people

- **Status:** accepted
- **Date:** 2026-11-15
- **Decided by:** the maintainer

## Context
The panel (`perf_panel`, `GET /panel`, `panel.py`, `data/panel.html`, the `panel.json` layout) drew one or two recordings
in a browser. In `origin/main` at 0.24.0 it was 1 324 lines (323 of Python, 1 001 of HTML) and 62 tests of its own, and
its numbers came from the same summaries that `perf_compare`, `perf_check`, `perf_history` and `perf_diagnose` read. A redesign
of its interface was started and stopped when the panel was removed.

## Decision
Remove it, in one release, as an incompatible change (0.x: the second number moves). The tools above keep returning
the numbers; an agent reads them from the tool results.

## Alternatives considered
| Option | For | Against | Why yes / no |
|---|---|---|---|
| Remove (chosen) | Less code to test and review; one way to read results | Anyone calling `perf_panel` or `/panel` breaks | Yes: the maintainer considers it unnecessary |
| Redesign it | A nicer page | Large work for a second way to read the same numbers | No |
| Keep it as it is | No break | Keeps 1 324 lines and 62 tests alive | No |

## Consequences
- **Positive:** 24 tools instead of 25; the HTTP endpoint only serves `POST /mcp`.
- **Negative / cost:** a client that called `perf_panel` gets an unknown-tool error; nobody was asked beforehand.
- **Left behind on purpose:** the `profile` key of `metal-gpu-trace.json` was still accepted (and ignored) in 0.25.0 and was removed in 0.26.0; a
  `panel.json` in a runs folder is still not a recording (`paths.LAYOUT_FILE`), so old folders keep working.

## Revisit when
The `profile` key was dropped in 0.26.0. Still open: the `panel.json` exclusion (`paths.LAYOUT_FILE`, plus the names written out in `analysis.py`, `perf_record_windows.py` and `prune_runs.sh`): dropping it makes `KEEP_RUNS` delete that file in old folders.
