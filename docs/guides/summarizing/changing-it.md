# Changing it

**Reader:** people who add or change a number, a table, a comparison or a threshold in `perf_report.py`, `metrics.py`, `analysis.py` or `experiments.py`. Reviewed 2026-11-16.

Back to the [guide index](./index.md).

**In short:** the rule that holds everything together is that a number nobody could measure is "missing", never zero. A
second rule: the readers work after the recording is gone, so they never open the trace (`analysis.py` reads only summaries
and `frames.csv`; reading the trace is the job of `perf_report.py` and the `traces.py` tools). Follow the recipes below.

| You want to | Do | Check |
|---|---|---|
| Add a number | compute it in `metrics.py` if Windows can also produce it, in `perf_report.py` otherwise; add the key to the summary and to the [data guide](../data-and-lifecycle/json-keys.md#the-summary-key-by-key) | a missing input gives `None` or no key, never `0` |
| Read a new table | add its schema to `OPTIONAL`, read it only `if "<schema>" in tables`, add a test beside `test_toc_and_tables` | not in `TABLES` (required) unless every summary needs it: an absent required table fails the whole report ([limit 3](./limits.md)) |
| Compare a new thing | add it to `numbers` in `compare_summaries` (`analysis.py:168`) | to decide on it, add it to `CHECKED` (`:246`) and set its margin in `judge` (`:325`); to require it, add it to `GATES` (`:466`) |
| Change a threshold (`STUTTER_FLOOR_MS`, `NOISY_EXTERNAL_PCT`, the 1.5, the 3 %) | older summaries keep their numbers as written, and `skip_s` recomputes with the **current** `frame_pacing` but the **stored** `threshold_ms` (`analysis.py:573-577`): the two disagree on old runs | update `tests/golden/metrics.json` |
| Add a tool that reads a summary | keep `reads_recordings` on it (`analysis.py:37-48`) | keep paths out of its messages |
