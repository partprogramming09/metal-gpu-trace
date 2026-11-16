# Changing it

**Reader:** people who add or change a number, a table, a comparison or a threshold in `perf_report.py`, `metrics.py`, `analysis.py` or `experiments.py`. Reviewed 2026-11-16.

Español: [Tocarlo sin romperlo](../../es/guides/resumir-y-analizar/tocarlo-sin-romperlo.md)

**In short:** the rule that holds everything together is that a number nobody could measure is "missing", never zero. A
second rule: the readers work after the recording is gone, so they never open the trace. Follow the recipes below and the
older summaries keep working.

Back to the [guide index](./index.md).

| You want to | Do | Check |
|---|---|---|
| Add a number | compute it in `metrics.py` if Windows can also produce it, in `perf_report.py` otherwise; add the key to the summary and to the [data guide](../data-and-lifecycle/json-keys.md#the-summary-key-by-key) | a missing input gives `None` or no key, never `0`: every reader treats `None` as "unknown" |
| Read a new table | add its schema to `OPTIONAL`, read it only `if "<schema>" in tables`, add a test beside `test_toc_and_tables` | do not put it in `TABLES` (required) unless every summary needs it: an absent required table fails the whole report ([limit 3](./limits.md)) |
| Compare a new thing | add it to `numbers` in `compare_summaries` (`analysis.py:168`) | to decide on it, add it to `CHECKED` (`:246`) and set its margin in `judge` (`:325`); to require it, add it to `GATES` (`:466`) |
| Change a threshold (`STUTTER_FLOOR_MS`, `NOISY_EXTERNAL_PCT`, the 1.5, the 3 %) | change it knowing older summaries keep their numbers as written, and `skip_s` recomputes with the **current** `frame_pacing` but the **stored** `threshold_ms` (`analysis.py:573-577`): the two will disagree on old runs | update `tests/golden/metrics.json` |
| Read a trace from `analysis.py` | do not: it reads summaries and `frames.csv` only, which is why it works after the trace is gone; reading the trace is `perf_report.py`'s and the `traces.py` tools' job | |
| Add a tool that reads a summary | keep `reads_recordings` on it (`analysis.py:37-48`) | keep paths out of its messages |
