---
title: Using it
description: You installed metal-gpu-trace. What now? Five typical jobs, step by step, with the sentence to say to your AI agent.
---

# Using it: "I installed it, now what?"

**Reader:** people who installed the server and want to measure something, with no need to read code. Reviewed 2026-11-23.

**In short:** you do not run commands yourself. You tell your AI agent what you want, in plain words, and it calls the server. Each job below has the sentence to say and how to read the answer. Words in *italics* are explained in the [glossary](https://github.com/partprogramming09/metal-gpu-trace#words-used-here).

Not installed yet? Follow "Start in 4 steps" in the [README](https://github.com/partprogramming09/metal-gpu-trace#start-in-4-steps).

## Before any job

- Keep the program's window **visible** while it records: a hidden window stops drawing and the numbers are wrong.
- Keep the Mac **unlocked** and keep other heavy work (a game, a render, a video call) off it.
- One recording at a time. The server refuses a second one.
- Free disk: a recording needs about 0.8 GB per second while it runs (26 GB for 30 s). The space comes back when it ends.

## 1. Measure a game under Wine

Say: **"Record my game for 30 seconds and tell me its FPS, how long the GPU takes per frame and whether it stutters."**

Give your agent the program's path (in Finder, hold Option and right-click the file, then choose "Copy as Pathname") (and the Wine you use, if the server does not know it yet). Then play normally, or let the game sit in a busy scene, until the recording ends. Under Wine use **30 seconds or more**: Wine's own start-up eats part of a short recording.

Read the answer like this:

| You see | It means |
|---|---|
| **FPS** | Pictures per second. Higher is smoother, until the screen's refresh rate caps it. |
| **GPU ms per frame** | How long the graphics chip works on one picture. Lower is better, and the screen does not cap it. |
| **1 % low** | The FPS of the slowest 1 % of frames. A big gap from the average means stutter. |
| **frames** | How many pictures were recorded. Under **100** is too few to compare. |
| a note about "another process" or "noisy" | Something else was using the GPU. Repeat the recording before trusting it. |

One recording says little by itself. Jobs 2 and 3 are how you make it mean something.

## 2. Compare before and after a change

Say: **"I changed my graphics setting (or my code). Record it with and without the change, three times each, and tell me which is better."**

The agent records each side several times and answers **better**, **worse**, **same** or **unknown** for each number. "Same" is a real answer: it means the difference is smaller than the noise between two equal recordings. "Unknown" means there were too few recordings or frames to say.

Rules that keep the answer honest:

- Use the same program, the same scene and the same length for both sides.
- At least two recordings per side; three is better. Repeat a run before calling a difference real.
- On a laptop, ask for a pause between recordings ("wait 60 seconds between runs") so the Mac cools down.

To just see how two recordings differ, with no verdict: **"Compare these two recordings."** That lists what moved and warns when the comparison may mean nothing (for example, one run stopped drawing).

## 3. Save a baseline and catch regressions

A *baseline* is a saved reference made of several equal recordings. It shows how much a number moves by itself.

Say once: **"Record my app five times for 30 seconds and save it as the baseline called main."**

Say after each change: **"Record my app and tell me if it got worse than the baseline main."**

The answer is **same**, **improved** or **regressed**. By default it takes a 3 % margin, so a small wobble does not count as a regression. To set hard limits instead, say: **"Fail the run if it is under 60 FPS."** The agent then answers pass or fail against the limits you gave (a minimum FPS, a maximum number of stutters, a memory ceiling).

To make a build server do the same, the `metal-gpu-trace check` command gives the answer as an exit code: 0 same or improved, 1 regressed, 2 could not be judged. See [CI gate](https://github.com/partprogramming09/metal-gpu-trace#ci-gate) in the README.

### Fixed limits in a file

A baseline answers "as good as before". A budget file answers "good enough", the same on any machine. `metal-gpu-trace gate RUN [--budgets FILE]` reads `metal-gpu-trace.budgets.json` from the folder it runs in (version 1) and judges one recording against its numbers:

```json
{"version": 1,
 "budgets": {"fps": {"min": 55}, "gpu_ms_p95": {"max": 12.5}, "stutter_rate_pct": {"max": 1.0}}}
```

Each budget holds `min`, `max` or both, for `fps`, `fps_1pct_low`, `gpu_ms_mean`, `gpu_ms_p95`, `frame_interval_ms_p95`, `stutter_rate_pct`, `hitches` or `metal_mib_peak`. Exit code 0 means every number is within its limit, 1 means one is over its `max` or under its `min`, and 2 means the recording could not be judged: under 100 frames, a program that stopped drawing, no such recording, or a file that is missing or malformed, all with the fix on stderr. A number the recording does not have is never a silent pass: name it in a budget and the answer is 2 until the recording can measure it.

## 4. When a recording fails

Most failures are a refusal **before** anything starts, and the message says what to do. Nothing was recorded, so there is nothing to clean up.

| The message says | What to do |
|---|---|
| `xctrace` is missing | Install Xcode from the App Store, open it once, then point the Mac at it: `sudo xcode-select --switch /Applications/Xcode.app` (`sudo` runs a command as administrator and asks for your Mac password). The Command Line Tools alone are not enough. |
| The screen is locked | Unlock the Mac and keep it unlocked. |
| Not enough free disk | Free the space the message names. |
| Another recording is running | Wait. If none is running, the message names a folder that marks a recording in progress; delete that folder only if you are sure none is running. |
| No Wine at `bin/wine`, or not an executable file | Check the path you gave. |

To see everything the server finds missing on this computer, run `uvx metal-gpu-trace init --dry-run`: it writes nothing and prints a `note:` for each missing piece, with the fix. If a recording started but the answer looks wrong, say: **"Why does this recording look wrong?"** The agent reads the summary and the checks. Deeper detail: [Preflight](./recording/preflight.md) and [Failures](./recording/failures.md).

## 5. Windows with PresentMon

On Windows the server records a native Windows program (no Wine, no Metal). The frames come from *PresentMon*, a free tool from Intel.

1. Install and connect: `winget install --id=astral-sh.uv -e`, then `uvx metal-gpu-trace init`.
2. Say: **"Install PresentMon."** The agent downloads it for you.
3. Say: **"Record my game for 30 seconds and tell me its FPS and 1 % low."**

Without PresentMon the server falls back to a coarser source that covers the whole desktop and has no GPU time; the summary says so, and it never invents frames. Jobs 2 and 3 work the same way on Windows. Some numbers exist only on the Mac (the Metal encoders, for one); a number that cannot be measured the same way on both systems is marked as not comparable, never invented. Detail: [Windows engine](./recording/windows-engine.md).

## Where to go next

- What each number means and how it is computed: [How the numbers are computed](./summarizing/how-numbers-are-computed.md).
- Why two runs say "same" or "worse": [Noise and verdicts](./summarizing/noise-and-verdicts.md).
- What a recording leaves on disk, and how to delete it: [Data and its lifecycle](./data-and-lifecycle/index.md).
- The full list of tools your agent can call: [README, Tools](https://github.com/partprogramming09/metal-gpu-trace#tools).
