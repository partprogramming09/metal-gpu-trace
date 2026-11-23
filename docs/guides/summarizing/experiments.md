# The experiments

**Reader:** people who run `perf_baseline_record`, `perf_ab`, `perf_cold_warm` or `perf_sweep`, or who change `experiments.py`. Reviewed 2026-11-16.

**In short:** one measurement of a program is not trustworthy, because equal runs differ a little by themselves. The
experiments record the program several times in a planned order, then use the readers of the previous page to say whether a
difference is real. They take minutes per run, so use them on purpose.

Back to the [guide index](./index.md). Lines are in `experiments.py` unless another file is named.

`experiments.py` records several runs and calls the readers of [Reading and comparing](./reading-and-comparing.md). Each recording goes through `record_new_summary` (`recording.py::run_recording`), which calls `perf_record` and reads back the one summary it wrote, so each run is a normal run with a normal label. All four share `cooldown_s` (0 to 600 s, rests between two recordings, never before the first or after the last; a cancelled call ends the rest; `recording.py::cooldown`, `paths.py:102-115`) and take `perf_record`'s arguments. Each recording takes its seconds plus about a minute to read back (docstrings), and the recording lock lets only one run at a time ([recording guide](../recording/rules.md#one-recording-at-a-time)).

| Tool | What it records | What it returns | Limits | Line |
|---|---|---|---|---|
| `perf_baseline_record` | the same program `count` times in a row, runs named `<name>-1`, `-2`, ... | the baseline: range and `spread_pct` (it ends in `perf_baseline`) | `count` 1 to 10 | `:9-27`, `:20` |
| `perf_ab` | two environments in the order **A B B A**, repeated `rounds` times; runs `<name>-a1`, `-b1`, `-b2`, `-a2`, ... | per metric (FPS, 1 % low, GPU ms, stutter) the values of each side and a verdict | `rounds` 1 to 5 (4 to 20 recordings) | `:48-69`, `:202-222` |
| `perf_cold_warm` | the same program twice: `<name>-first` and `<name>-second` (macOS only) | hitches and causes of each run and `first_seen_hitches` | none | `:72-102` |
| `perf_sweep` | once per value of one variable (`dim`, `example`, `api`, `size` or `env:NAME`), values forward in one round and backward in the next | per value the median of the four metrics, and a straight-line fit | 2 to 8 values, `rounds` 1 to 5, at most 24 recordings | `:141-199`, `:117-138` |

## Why A B B A

A laptop warms up as it records. Running A, B, A, B puts every B on a warmer machine than the A before it; A B B A puts one of each at the start and one at the end, so slow drift hits both sides alike, and `rounds` repeats the pattern (`:49-51`). The sweep reverses the order of the values every other round (`:161`). That the drift matters is the project's own claim (the cooldown exists "so a laptop does not throttle", `:13-14`); its size was **not measured** for this guide.

## How `perf_ab` decides

`ab_verdict(a, b, higher_better)` (`:36-45`): `unknown` if either side has no values; **better** if every `b` value is above every `a` value (`min(b) > max(a)`) for a metric where higher is better (FPS, 1 % low), or below for one where lower is better (GPU ms, stutter); **worse** in the mirrored case; `same` otherwise, including every overlap.

No margin and no percentage: the **spread of the A runs is the ruler**, "so a run's own spread never passes for an effect" (`:37-38`). With `rounds=1` each side has two values, so the ruler is two runs wide. A value a run does not have (a 1 % low of a short run, `None`) is left out, so a side can have fewer values than runs (`:213-215`). `too_short` is true if any run has under 100 frames (`:217-219`). By hand on the two real runs, first as side A and second as side B: FPS `a = [105.4]` and `b = [102.1]`, so `max(b) < min(a)` and the rule gives `worse` for a 3 % drop, because one value has no spread. That is the arithmetic of the rule fed one value per side, not a run of the tool: `perf_ab` itself always records at least two runs per side. It shows why a single comparison is not an experiment ([E6](./evidence.md#e6)).

## How `perf_cold_warm` decides

`cold_warm_report` (`:72-87`): `first_seen_hitches = max(0, shader_compile hitches of the first - those of the second)` and `extra_hitches_in_first = max(0, hitches of the first - hitches of the second)`. The hint says the Metal shader cache is **not cleared** between runs, so the first run is "cold" only if the program's pipelines were not built before. By hand on the two real runs, named like a `perf_cold_warm` pair (the labels end in `-first` and `-second`; that the tool made them is **probable**): both have 0 `shader_compile` hitches, so `first_seen_hitches` is 0; the hitch counts are 6 and 4, so `extra_hitches_in_first` is 2 ([E7](./evidence.md#e7)), though the second run's 4 are not comparable with the first's 6: its presented span is 2.3 s.

## How `perf_sweep` fits a line

With at least 3 numeric values (`dim` is; `size` is not; `example` and `api` are names) it fits GPU ms per frame against the value by least squares (`line_fit`, `:105-114`): `slope = Σ(x - mx)(y - my) / Σ(x - mx)²`, `intercept = my - slope × mx`, `r² = 1 - residual / total`. For `dim` the x is `dim³`, because drawstress draws `dim³` cubes per frame (64 000 at `dim` 40, [recording guide](../recording/test-programs.md#what-is-in-the-list-e4)), so the slope is **ms per draw** and the intercept the fixed cost (`:189-196`). A variable with non-numeric values gives no fit (`ValueError` caught, `:188-191`), and `line_fit` returns `None` when x never changes (`:109-110`).

Tests: `test_baseline_record`, `test_perf_sweep`, `test_cold_warm` (`tests/test_analysis.py::test_baseline`, `:198`, `:269`) and the cooldown ones in `tests/test_recording.py:1398-1443` (not run). A real sweep was **not reproduced**: it needs 4 to 24 recordings.
