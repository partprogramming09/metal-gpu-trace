# Reference runs on Windows

**Reader:** people

*VegaFlow and WinBridge are the maintainer's own tools; you do not need them. See [Two tools the proofs mention](internal-tools.md).*

**In short:** the same test program ran on one Windows PC twice, once with and once without the VegaFlow daemon (a system
tuning program that runs in the background). The frame numbers stayed within the normal variation between runs, so
these runs show no difference that the daemon causes. Three runs per case are few: this shows no difference, it does
not prove there is none.

**Where and when:** one Windows PC, Windows 10 build 10.0.26300, presentation mode `Hardware: Independent Flip`
(reported by PresentMon); 2026-11-18. The runs were started as jobs in the visible desktop session (see
[Limits](#limits)).

## What was run

- **Test program:** `drawstress`, using Direct3D 11 (a graphics API for Windows). Frames are counted by
  [PresentMon](https://github.com/GameTechDev/PresentMon), a tool that records when each frame is presented. The Windows
  engine that reads it is described in the [Windows engine guide](../guides/recording/windows-engine.md).
- **Cases:** `task-off` (daemon stopped) and `task-on` (daemon running).
- **Runs:** 3 runs per case, each asked for 20 seconds; the job discards the first 5 seconds as warm-up (1 800 frames at 120 fps is about 15 s). The order is the job's own: off, on, on, off, off, on.
- **Tool:** the `ab` job of VegaFlow, which runs both cases and prints one row per run.

**Command:** `winbridge jobs --host <host> run ab Api=d3d11 Reps=3 Seconds=20` (the VegaFlow and PresentMon versions were not recorded).

**Output:** the job prints no header. Its columns are: label, frames, avg_fps, fps_1pct_low, fps_0.1pct_low,
frametime_stddev_ms, present_mode.

```
task-off-d3d11-1,1799,120.1,84.14,77.14,0.665,Hardware: Independent Flip
task-on-d3d11-1,1806,120.48,86.24,77.86,0.605,Hardware: Independent Flip
task-on-d3d11-2,1814,120.97,86.99,80.02,0.593,Hardware: Independent Flip
task-off-d3d11-2,1814,121,84.42,80.17,0.73,Hardware: Independent Flip
task-off-d3d11-3,1787,119.26,82.43,73.21,0.872,Hardware: Independent Flip
task-on-d3d11-3,1785,119.17,83.63,71.32,0.847,Hardware: Independent Flip
```

In plain words: `frames` is the number of frames counted in the run; `avg_fps` is frames per second over the run;
`fps_1pct_low` is the frame rate over the slowest 1 % of frames, and `fps_0.1pct_low` over the slowest 0.1 %;
`frametime_stddev_ms` is how much the time per frame varies, in milliseconds (lower is steadier). The exact method is in
PresentMon's own documentation, which was not checked for this page.

## Results

Each figure is the mean of the case's three runs. The spread is the highest run minus the lowest run. The means were
calculated from the six rows above; they are not printed by the job.

| Metric | Daemon stopped: mean (spread) | Daemon running: mean (spread) |
|---|---|---|
| `avg_fps` | 120.12 (1.74) | 120.21 (1.80) |
| `fps_1pct_low` | 83.66 (1.99) | 85.62 (3.36) |
| `fps_0.1pct_low` | 76.84 (6.96) | 76.40 (8.70) |
| `frametime_stddev_ms` | 0.756 (0.207) | 0.682 (0.254) |

Every run has more than 100 frames (1 785 to 1 814), so each one is long enough to compare.

**Reading:** the average frame rate differs by 0.09 fps between the cases. That is smaller than the spread between runs
of the same case (1.74 without the daemon, 1.80 with it), so no difference can be measured. Each of the other three
differences is also smaller than the spread of one case's runs, so none of them is read as a result either.

## Second check: the WinBridge job

The job `metal-trace-daemon` in this repository (`windows/winbridge-job/scripts/metal-trace-daemon.ps1`) runs the same
two cases as an elevated job. It installs the published package in a clean virtual environment, records `drawstress`
(Direct3D 11) for 8 seconds once with the daemon stopped and once running, and then puts the daemon back the way it
was. It ran on the same day.

**Output:**

```
{"case": "without-daemon", "frames": 397, "fps_estimate": 49.3}
{"case": "with-daemon", "frames": 357, "fps_estimate": 49.2}
exit code: 0
```

**Reading:** the job works from start to finish on this PC. It records one run of 8 seconds per case, so it does not
compare the two cases. Its figures (about 49 fps) must not be set against the figures above (about 120 fps): each job
runs in a different display mode, so the two numbers do not measure the same thing.

## Limits

1. **Only the Windows half.** The same comparison on macOS, against Mullion (a translation layer, see the
   [README glossary](https://github.com/partprogramming09/metal-gpu-trace#words-used-here)) and against Godot, is not done yet. Those runs are made on a Mac.
2. **The `ab` figures come from PresentMon through VegaFlow.** They are not a metal-gpu-trace summary, so they do not
   carry the summary keys (`frame_pacing`, `common`).
3. **Runs started over SSH do not count.** An SSH session is outside the desktop session. There, `drawstress` does not
   load `d3d11.dll`, and its summary says `common.api.runtime: vulkan`. Only runs started as a job in the desktop session
   (session 1) are valid for Direct3D.
   pendiente de evidencia: el comando y el resumen de una grabación hecha por SSH.
4. **Which graphics library loads.** Started with the `game` job, `--d3d11` loads `d3d11.dll` and `--d3d12` loads
   `d3d12.dll`. pendiente de evidencia: la salida del job `game` con `--d3d11` y con `--d3d12` que muestre la DLL cargada.

## Not tested

- The macOS half: Mullion and Godot.
- Other Windows PCs, GPUs and drivers: this is one machine.
- Other workloads than `drawstress`, and runs longer than 20 seconds.
- The `metal-trace-daemon` job more than once: each case was run once.
