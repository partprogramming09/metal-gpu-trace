# Known limits

**Reader:** people who want to know where this part of the project is weak, or about to rely on a number that depends on one of these. Reviewed 2026-11-16.

Español: [Límites conocidos](../../es/guides/resumir-y-analizar/limites.md) · Back to the [guide index](./index.md).

**In short:** this page lists 13 places where today's behaviour is surprising or unproven, and what could not be run for the
guide. They are written down, not fixed. Each carries a status: confirmed by the code, probable, or not verified.

| # | Limit | Where | Status |
|---|---|---|---|
| 1 | The two real summaries are generation 1: no `schema_version`, `tier`, `common` or `noisy_environment`, so the guide recomputed with today's formulas and the match ([E3](./evidence.md#e3)) checks those formulas on old data, not what the version that wrote them did | `perf-runs/` (local, not published) | Confirmed |
| 2 | The friendly message for a trace without `metal-gpu-intervals` may be unreachable: `toc_and_tables` takes the export of a required table with `future.result()`, and the code's own comment says "xctrace fails on a table that is not there", so the generic `xctrace export ... failed` would come first; the `ValueError` is reached only if the export succeeds on an absent table. `tests/test_report.py:128-135` tests `missing_tables` directly | `perf_report.py:98-99`, `:116-117`, `:194-196` | Probable: not reproduced (no trace) |
| 3 | `missing_tables` lists `metal-current-allocated-size` and `gpu-performance-state-intervals` as if optional, but only the first can be absent without failing (skipped with `--no-memory`); a trace without the second most likely fails the export, so the name would never reach the summary | `perf_report.py:190-197` against `:95-123` | Probable |
| 4 | `export` does not catch a `subprocess.TimeoutExpired` (600 s per table, 3600 for counter values), and `main` catches only `ValueError`, `FileNotFoundError` and `RuntimeError`: a slow export ends in a traceback, which carries the command line, and the temporary XML file `export` created is not deleted on that path (the `finally` of `summarize` removes only files already returned). A table cut mid-row (an `ET.ParseError` that `complete_xml` does not forgive) ends the same way | `perf_report.py:55-59`, `:166-168`, `:850` | Confirmed by the code; not reproduced |
| 5 | `command_buffer_errors` counts every row of its table, not only the program's; the allocations and spills tables are filtered by the program's pid | `perf_report.py:805-806` against `:457-522` | Confirmed by the code |
| 6 | `stutter_rate_pct` skips gaps that span an unpresented frame; `hitches` and `steady_summary` build their gaps from the frame starts left, so they count such a gap and the stutter rate does not, and `hitches.count` can exceed the stutter count | `perf_report.py:243-244`, `:706`, `:822` against `analysis.py:568` | Probable: the real second run's stall is at its end, so it does not show this |
| 7 | `perf_ab`, `perf_sweep` and `perf_cold_warm` do not report `unpresented` or `noisy_environment` of the runs they record (only `too_short`); `perf_baseline` does | `experiments.py:202-222`, `:187`, `:72-87` against `analysis.py:288-292` | Confirmed |
| 8 | `perf_check` uses a fixed `margin_pct` (3) and does not read the baseline's `spread_pct`. A one-run reference has spread 0 and its range is a point, so a 3.1 % FPS dip still reads `regressed`. Since 53f742b the result says so in a `note` (only when the verdict is not `same`, 9b66165): the noise between equal runs is not measured. A reference of several runs already holds its noise in its range, so `spread_pct` is not added to the margin, on purpose | `analysis.py:317-330`, `:310-314`, `:378-380` | Confirmed ([E6](./evidence.md#e6)); the verdict did not change, only the warning was added (53f742b, 9b66165) |
| 9 | The 1 % low is the percentile of the interval, not the average of the slowest 1 %; whether that matches other tools is not verified | `perf_report.py:262-266` | Not verified |
| 10 | A throttling flag is overwritten by "any non-Nominal thermal interval" whenever the thermal table exists, whether or not FPS fell | `perf_report.py:819-820` | Confirmed |
| 11 | `perf_diagnose` writes its recommendations in Spanish, everything else is English | `analysis.py:756-807` | Confirmed (cosmetic) |
| 12 | The 3 % margin, the 20-point noise threshold, the 8 ms floor and the 25 %, 20 %, 15 % idle thresholds are the project's choices, some marked "provisional" in the code; none is re-measured here | `analysis.py:325`, `:746-748`; `perf_report.py:250`, `:562` | Not verified |
| 13 | Two real runs prove the formulas on summaries of one program on one Mac; a Windows summary's numbers (PresentMon, the log) were not recomputed | | Not reproduced |

## What was not reproduced

Besides the two limits of the whole guide ([index](./index.md#how-to-read-the-labels)): a summary with a non-empty `missing_tables`, a trace without `metal-gpu-intervals`, a table cut mid-row, an export that times out, a Windows summary's recomputation, and the numbers of 0.27.2 (the two real summaries are generation 1 and older than the code described). A real baseline, A B B A and sweep need 4 to 24 recordings.
