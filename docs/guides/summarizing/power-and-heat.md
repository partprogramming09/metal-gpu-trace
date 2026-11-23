# Power and heat at both ends of a run

**Reader:** people who compare two recordings made on a Mac, and anyone who reads a `power` note or a `machine.power`
block and wants to know what it means. Reviewed 2026-11-17.

Back to the [guide index](./index.md).

**In short:** a Mac in low power mode, or a hot Mac, slows its chip to save power or to cool down, and the frames slow
with it. The recorder asks the Mac two questions, once before the program starts and once after the recording ends, and
writes both answers into the summary. When two runs started in different conditions, or one changed while it was
recorded, `perf_compare` says so, so a slower chip is not read as a slower program.

## An example first

Two runs of the same program, with the same code. Run A starts with low power mode off and the Mac cool. Run B starts
with low power mode on. Run B shows fewer frames per second, and that drop has nothing to do with the code.
`perf_compare` now adds a `power` block and this note: the runs "were recorded with different low power mode or thermal
state (the Mac lowers its clocks), so FPS and GPU ms are not comparable".

A real 30-second recording wrote this block ([E9](./evidence.md#e9)):

```json
"power": {"start": {"low_power_mode": false, "thermal_warning": false},
          "end": {"low_power_mode": false, "thermal_warning": false}, "changed": false}
```

It sits inside `machine`, beside the chip and the RAM, so the summary holds `machine.power`. Both answers were "no", so
`changed` is `false` and `perf_compare` adds nothing.

## What the two questions are

Two commands that ship with macOS answer them. Nothing is installed for this.

| Command | What it reports | Becomes |
|---|---|---|
| `pmset -g` (`pmset` is the macOS tool for power settings) | a line `lowpowermode 1` or `lowpowermode 0` | `low_power_mode`: `true` or `false` |
| `pmset -g therm` (the thermal state) | a line with "warning level" when the Mac warned of heat, and `CPU_Speed_Limit`, which is 100 when the CPU runs at full speed | `thermal_warning`: `true` when a warning line does not say "no", or when `CPU_Speed_Limit` is below 100 |

The rules in the code (`power_state`, `perf_report.py:653-668`):

- A fact the Mac does not give is `null`, never a guess. The same holds when `pmset` is missing or fails.
- If `pmset -g therm` shows neither a `CPU_Speed_Limit` line nor a warning line, `thermal_warning` stays `null`, not `false`.

## When the two questions are asked

1. **Before the program starts**: `record_run` calls `power_state()` (`recording.py:386`) before `perf_record.sh` runs.
2. **After the summary is written**: `record_run` calls it again, and `power_block` puts both readings in `machine.power`
   (`recording.py::run_recording`, `perf_report.py:672-676`).

The block exists only when the summary has a `machine` block. `machine` is `null` in the JSON when this Mac is not the one
that recorded the trace (its RAM or macOS version differs from the trace's device) or when a fact about the machine cannot
be read (`machine_info`, `perf_report.py:679`). Then there is no `power` either.

## What `changed` means

`changed` is `true` only when a fact is known at both ends and the two readings differ. A `null` at one end never counts,
so a fact that could not be read does not make a run look unsteady (`perf_report.py:676`). Example: low power mode `false`
at the start and `null` at the end leaves `changed` as `false`.

## What perf_compare does with it

`compare_summaries` (`analysis.py:191-203`) reads both runs' `machine.power`. It adds a `power` key only when both
summaries have the block and one of two things holds:

| Condition | Note in the answer | `changed_in` |
|---|---|---|
| At the start, the two runs differ in low power mode or in `thermal_warning` (both known) | "the runs were recorded with different low power mode or thermal state (the Mac lowers its clocks), so FPS and GPU ms are not comparable; record both with low power mode off and the Mac cool" | listed if a run also changed while it was recorded |
| The starts match, but one run changed while it was recorded | "low power mode or the thermal state changed during a recording (changed_in): the run is not steady, repeat it" | the name of that run (`a` or `b`) |

When both happen, the first note is the one written. The key always holds `a` and `b` (the start readings), so a reader
can see which fact differed. A summary with no `power` key (an older run, a Windows run, a run whose `machine` was `null`)
gets no note. No note means "not measured", not "no heat".

## How it differs from thermal_state_share

`thermal_state_share` is a full record: the time the Mac spent in each thermal state during the recording, read from the
`device-thermal-state-intervals` table (`perf_report.py:782-790`). `machine.power` is only two readings. Use
`thermal_state_share` to see a slowdown in the middle of a run; use `power` to learn whether the Mac came into the run
already slow.

## Diagram

The flow from the two readings to the note: HTML source `docs/diagrams/power-at-both-ends.html` (PNG pending export).

## Limits

- **Two readings only.** A low-power or hot period that begins and ends inside the run is not seen by `power`; only
  `thermal_state_share` covers it.
- **macOS only.** A Windows summary has no `machine` block, so it has no `power` ([data guide](../data-and-lifecycle/json-keys.md)).
- **Depends on the text `pmset` prints.** A macOS version that words it differently gives `null`, not an error. Not checked
  on other macOS versions (not verified).
- **The warning rule reads a line of text.** The code ignores a line that contains "no " (for example "No thermal warning
  level"). If a macOS version words a warning another way, it is missed (probable; not reproduced).
- **Only the `false` case was seen in a real recording.** The `true` case (low power mode on, a warning) is covered by
  tests, not by a real recording. Evidence pending: the output of those tests was not given for this page.

## Why it is shaped this way

| Choice | Why | Alternatives left out |
|---|---|---|
| Two readings, one before and one after the recording | The question is what state the Mac started and ended in; two moments answer it with no extra table | Alternatives not recorded for this change: to be confirmed |
| Two built-in commands, no library | `pmset` ships with macOS; `subprocess` is in the standard library | Not recorded: to be confirmed |
| `null` for a fact that cannot be read | A guess would make `perf_compare` blame a run for a state nobody measured | A default of `false`: it would hide a fact that was never read |

## Evidence

Nothing from this change was run again for this page. The rows below are what the session gave, with what is missing
marked. The full table is in [Evidence](./evidence.md#e9).

| What it shows | Command | Output |
|---|---|---|
| A 30-second recording: both ends false, `changed` false | evidence pending: the command that made the 30-second recording (not given) | the JSON above, as given |
| The `power` note of `perf_compare` on two runs | evidence pending: the `perf_compare` call on two runs that differ (not given) | not given |
