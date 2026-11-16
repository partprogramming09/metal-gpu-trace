# When it fails

**Reader:** people who see an error from `perf_report.py`, `analysis.py` or `experiments.py` and want to know what it means and what is left behind. Reviewed 2026-11-16.

Español: [Cuando falla](../../es/guides/resumir-y-analizar/cuando-falla.md) · Back to the [guide index](./index.md).

**In short:** most failures end in a plain sentence that says what to do (for example, "record it again"). A few do not: a
slow or cut export ends in a raw error trace. Nothing half-written is left for the reader to trust, except runs already
recorded by an experiment that stopped midway.

| What goes wrong | What the reader gets | What is left | Line (`perf_report.py` unless named) |
|---|---|---|---|
| The `.trace` is already deleted, has no `metal-gpu-intervals`, or has no launched or attached process | the messages of [Step 1](./trace-to-summary.md#step-1-export), [Step 2](./trace-to-summary.md#step-2-the-table-of-contents-and-missing_tables) and Step 3 of the same page | nothing new | `:52-54`, `:194-196`, `:644-645` |
| `xctrace export` fails | `xctrace export of <name> failed (exit N): <last stderr line>` | temporary files of the other exports are deleted | `:62-65`, `:106-110`, `:121-123` |
| The program did no GPU work | a summary with `frames` 0 and no FPS is built; from a recording, `recording.py` turns it into `the program did no GPU work ...` and deletes the run | the `.trace` only if asked | `recording.py:427-436` |
| `perf_report` exits non-zero in a recording | `recording failed (exit N): <last line>` | the script's trap deletes the run's files | `perf_record.sh:5`, `:71`, [recording guide](../recording/failures.md#what-happens-if-instruments-dies-part-way) |
| An export times out, or a table is cut mid-row | a Python traceback, not a sentence ([limit 4](./limits.md)) | a temporary XML file may stay ([limit 4](./limits.md)) | `:59`, `:166-168`, `:850` |
| A summary is not valid JSON, is a link or has a wrong-typed section | `<run> is not valid JSON; record it again` / `<run> cannot be read` / `... not in the form the recorder writes (<ErrorType>)` | nothing | `paths.py:54-66`, `analysis.py:37-48` |
| A run, a reference or a `frames.csv` is missing, or `skip_s` leaves under 2 frames | `no run <name>; perf_runs lists them` (`paths.py:33-41`); `no reference <name>; perf_baseline with no arguments lists them` (`analysis.py:285`, `:345`); `<run> has no per-frame file; record it again`; `<run> has under 2 frames after the first N s; use a smaller skip_s` | | `analysis.py:510`, `:565-566` |
| An experiment fails mid-way | the `ToolError` of the failing recording; **runs already recorded stay**, and no baseline, verdict or fit is written | the earlier runs, as normal runs | `experiments.py:23-27`, `:64-69`, `:160-172` (no `try`: confirmed by the code, **not reproduced**) |
| An experiment is cancelled while resting | `cancelled while cooling down` and no further recording starts | the runs already made | `recording.py:240-249` |
