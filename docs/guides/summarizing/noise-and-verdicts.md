# Noise and verdicts

**Reader:** people deciding whether a change really made a program faster or slower. Reviewed 2026-11-17.

Back to the [guide index](./index.md).

**In short:** measuring the same program twice never gives the same number. So the project does not call a change "real"
until it falls outside what equal runs already do. Four tools look alike and answer different questions; this page puts
them side by side and lists the habits that keep noise from being mistaken for an effect.

The [guide's example](./index.md#one-example-first) shows why: against `a2-proof-first` alone the second run is `regressed` (102.1 under 102.238, by-hand arithmetic, [E6](./evidence.md#e6)), yet it stopped presenting at 3.6 s and 3 % is small against how much equal runs differ ([index](./index.md#why-this-part-is-shaped-this-way)); against three equal runs of the first kind it would very probably be `same` (**speculation**).

| Tool | Reference | Margin | A single run? | Says |
|---|---|---|---|---|
| `perf_compare` | one run | none | yes | the change, and what could make it meaningless; **no verdict** |
| `perf_check` | the range of N runs | 3 % for FPS and GPU ms (`margin_pct`), 0 for the counts | yes, against N | `regressed`, `improved` or `same` |
| `perf_ab` | the range of the A runs of this experiment | none | needs 2 per side at least to mean something | `better`, `worse`, `same` or `unknown` per metric |
| `perf_gate` | a number you set | none | yes | `pass` or fail per budget |

![Eight boxes in two rows joined by arrows. Top row: read the summaries, perf_compare (changes, no verdict), perf_baseline (the range and spread of equal runs) and perf_check's decision of each metric against that range with a margin. Bottom row: the verdict regressed, improved or same; perf_ab; perf_gate; and the warnings that never change a verdict.](./img/compare-flow.png)
*Figure 2. How a run is compared and judged. HTML source: `docs/guides/summarizing/img/compare-flow.html`.*

What the project does about noise, in the order you meet it: **1 Repeat**: "Repeat a run before calling a change real" (the project's `CLAUDE.md`; the [guides index](../index.md) says the same); `perf_baseline_record` and A B B A repeat for you. **2 Measure the noise**: the `spread_pct` of a baseline is how far equal runs differ. **3 Judge outside the noise**: the range replaces the single run; the margin adds a small buffer past it. **4 Say when the run is suspect**: the flags of `perf_compare` (`unpresented`, `noisy_environment`, `screen`, `power`, `gpu_state`, `tier`, `too_short`) are visible and **do not change the verdict** of `perf_check`; only `perf_gate` fails on `unpresented`. **5 Rest**: `cooldown_s`, and a `suggested_actions` entry proposing a 60 s rest when the Mac throttled ("60 s is a starting value, not a measurement", `analysis.py:665-666`).
