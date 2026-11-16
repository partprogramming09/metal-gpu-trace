# Summarizing and analyzing

**Reader:** people who read a summary or a comparison and want to know where each number comes from and when not to trust it, or who change `perf_report.py`, `analysis.py`, `metrics.py` or `experiments.py`. Reviewed 2026-11-16.

Español: [Resumir y analizar](../../es/guides/resumir-y-analizar/index.md)

**In short:** after a program is recorded, a script boils the huge recording down to one small file of numbers (frames per
second, stutters, memory). Other tools read those small files back, compare two runs and say "better", "worse" or "same".
This guide shows where every number comes from, why one run alone proves little, and when a result should not be trusted.

This module follows a recording after it is made. It does not repeat [Data and its lifecycle](../data-and-lifecycle/index.md)
(the summary's keys, the format generations, what is deleted when) or [Recording](../recording/index.md) (how the `.trace` is
made, the lock, the Windows engine); it links to them where the story continues.

## The pages

| Page | Answers |
|---|---|
| [From a trace to the summary](./trace-to-summary.md) | what `perf_report.py` reads, step by step; the tables; work that was never presented |
| [How each number is computed](./how-numbers-are-computed.md) | formula and line of every headline number; hitches, noise flag, Windows |
| [Reading and comparing](./reading-and-comparing.md) | `analysis.py`: `skip_s`, compare, baseline, check, gate, history, diagnose, missing numbers |
| [The experiments](./experiments.md) | `experiments.py`: baseline record, A B B A, cold/warm, sweep |
| [Noise and verdicts](./noise-and-verdicts.md) | the four deciders side by side; what the project does about noise |
| [When it fails](./when-it-fails.md) | what goes wrong and what the reader gets |
| [Changing it](./changing-it.md) | how to touch the code without breaking it |
| [Known limits](./limits.md) | 13 written-down limits and what was not reproduced |
| [Evidence](./evidence.md) | the commands (E1 to E8) and their real output |

## How to read the labels

Every technical claim is **confirmed** (with `file:line`, checked with `rg` or `sed` on 2026-11-16 against the working tree:
0.27.2 plus the `[Unreleased]` entries of `CHANGELOG.md`), **probable** (read from the code, not run here) or **speculation**
(a guess about why). **Not verified** marks an outside fact not checked against its source. **Not reproduced** means the
behaviour could not be run for this guide. Lines move with the code: search the name, not only the number. Every number has
its command in [Evidence](./evidence.md).

Two limits apply to the whole guide:

| Limit | Consequence |
|---|---|
| The repository has no `.trace` (the `perf-runs/` folder of the clone holds two finished summaries and their tables) and `xctrace` needs a recording | **`perf_report.py` was not run at all**: what it does with a trace is read from its code, and the tests that pin it are named |
| The session that wrote it could run read-only commands (`rg`, `sed`, `jq`, `awk`) and not Python | **No tool of `analysis.py` was run either**: the numbers they would give are evaluated by hand from the code's formulas on the two real summaries, and the text says so each time |

The tests named were **not run** for this guide.

## One example first

Two recordings of the same program, 20 seconds each (`a2-proof-first_20261115-085621` and `a2-proof-second_20261115-085735`;
a name is the label plus a time stamp). Side by side (commands E2 and E3):

| | first | second |
|---|---|---|
| `gpu.frames` | 2045 | 153 |
| `gpu.fps_estimate` | 105.4 | 102.1 |
| `gpu.fps_1pct_low` | 96.2 | 40.8 |
| `gpu.stutter_rate_pct` | 0.29 | 2.63 |
| `gpu.unpresented` | absent | present: 1776 command buffers after 3.637 s |

What a reader asks, and where the guide answers:

| Question | Short answer | Where |
|---|---|---|
| Where does 105.4 come from? | The **median gap between frame starts**, 9.4845 ms: `1000 / 9.4845 = 105.4`; recomputed from `frames.csv` (E3) | [fps_estimate](./how-numbers-are-computed.md#fps-estimate) |
| Why only 153 frames in 20 s? | The program **stopped presenting** at 3.6 s (a hidden window is the usual cause); the other 17 s of GPU work are left out of the frame numbers. 102.1 FPS is the speed of the first 3.6 s only | [Work that was never presented](./trace-to-summary.md#work-that-was-never-presented) |
| Is 102.1 against 105.4 a regression? | `perf_compare` reports the change (-3.3, -3.1 %) and nothing else. `perf_check` against a one-run reference: 102.1 is under `105.4 × 0.97 = 102.238`, so `regressed`, on a run that stopped presenting (E6) | [Noise and verdicts](./noise-and-verdicts.md) |

## Why this part is shaped this way

| Choice | Why | Alternatives left out |
|---|---|---|
| The summary is a short JSON read from the trace once; the `.trace` is deleted | A `.trace` is hundreds of MB and `xctrace` takes minutes to read it; what the tools need fits in a few KB plus two tables ([data guide](../data-and-lifecycle/index.md)). The script deletes the trace right after the report unless `KEEP_TRACE=1` (`perf_record.sh:160-163`) | Re-reading the trace on every question: **speculation** that it was left out for the time and disk each read costs (`perf_report.py:39-41`, `:126-165`); no ADR records it (ADR-0006 is about keeping the trace, not this) |
| `perf_report.py` is also a script run by path | `perf_record.sh` calls `python3 -I perf_report.py <trace>` (`perf_record.sh:160`) and the file adds the package to the path itself (`perf_report.py:24-26`) | A module only: it must work with `-I`, which ignores the environment |
| The numbers both platforms share live in `metrics.py` | Windows has no `.trace` but a summary of the same shape: `frame_pacing`, `stats` and `common_block` are one copy (`metrics.py:1-2`, `perf_record_windows.py:489`, `:917`) | Two copies of each formula: the Windows ones would drift |
| The reader never recomputes from the trace, only from `frames.csv` | `skip_s` recomputes FPS, lows, stutter and hitches from the per-frame table (`analysis.py:552-599`); other keys stay whole-run and say so (`steady.whole_run`) | Keeping the whole trace: it is what the project deletes |
| "Better" means outside a **range**, not a different number | Equal runs differ by themselves: 5 runs of one program differed 4.4 % in FPS and 6.1 % in GPU ms (`CHANGELOG.md`, `perf_baseline` entry; not re-measured here), so one run is no reference (`analysis.py:259-268`) | A fixed percentage on one run: it would call noise a regression, as the example shows |
| The decision uses few numbers | Frame pacing, short encoders and GPU idle time "vary too much between equal runs": 13 % and 7 points in the same entry (`analysis.py:338-340`) | Judging on everything: more false alarms |
| The 100-frame rule is a flag, not a refusal | `too_short` and a `hint` are added and the answer is still computed (`analysis.py:187`, `:377-378`, `:498-499`) | Refusing short runs: nothing instead of a number with a warning |

## The pieces and where they live

| Piece | File | What it does |
|---|---|---|
| The summarizer | `perf_report.py` (`summarize` `:627`, `main` `:840`) | Reads a `.trace` through `xctrace`, writes `<label>.json`, `.frames.csv.gz`, `.metal_memory.csv.gz` |
| Export and parsing | `perf_report.py` (`export` `:49`, `toc_and_tables` `:95`, `rows` `:143`) | One `xctrace export` per table, two at a time; rows resolved from xctrace's `id`/`ref` cells |
| The statistics | `perf_report.py` (`frame_pacing` `:253`, `attribute_hitches` `:283`, `unpresented` `:206`, `noisy_environment` `:565`) | The numbers of [How each number is computed](./how-numbers-are-computed.md) |
| What both platforms share | `metrics.py` (`stats` `:75`, `encoder_stats` `:94`, `idle_gaps` `:122`, `common_block` `:49`) | The same formulas for macOS and Windows |
| Reading and comparing | `analysis.py` | `perf_runs`, `perf_compare`, `perf_baseline`, `perf_check`, `perf_history`, `perf_gate`, `perf_diagnose`, `perf_memory_breakdown` |
| Experiments | `experiments.py` | `perf_baseline_record`, `perf_ab`, `perf_cold_warm`, `perf_sweep` (they record, then call `analysis`) |

## See also

- [Data and its lifecycle](../data-and-lifecycle/index.md): the summary's keys one by one, generations, tables, the baselines file, what deletes what.
- [Recording](../recording/index.md): the `.trace` and the `rss.csv` and `agx.csv` samplers, the lock, the Windows engine.
- [How it works](../how-it-works.md): which layer calls which. [Run from a clone](../run-from-a-clone.md): how to run the code and the tests.
