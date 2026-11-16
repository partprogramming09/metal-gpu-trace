# The test programs

**Reader:** people who add or change a test program, or who debug `workload_fetch` and `presentmon_install` (`workloads.py`, `data/workloads.json`). Reviewed 2026-11-16. Labels: see [Recording](./index.md#how-to-read-the-labels).

Español: [Los programas de prueba](../../es/guides/grabar/programas-de-prueba.md)

**In short:** the project ships three small graphics programs so two people on two Macs can record the same load and
compare numbers. Each program is downloaded once, and the download is accepted only if its fingerprint (SHA-256, a
number that changes if a single byte changes) equals the one written in the project. Example, on a Mac:
`workload_fetch drawstress`, then `perf_record label=t1 workload=drawstress api=mtl seconds=10` (illustrative call).
PresentMon, Intel's frame logger for Windows, is installed the same way.

`workload_list` shows them, `workload_fetch` downloads one, `perf_record` with `workload`, `api` (and `dim`, `example`,
`size`) runs it.

## What is in the list (E4)

| Name | What it draws | `api` values | Download | License |
|---|---|---|---|---|
| `drawstress` | bgfx's 17-drawstress: a grid of cubes, `dim`³ draw calls per frame (64 000 at `dim` 40): the cost of one draw, native and through a layer | `mtl`, `mtl-x64` (Metal built for x86_64, run under Rosetta like a Wine program), `vk` (Vulkan through MoltenVK), `d3d11`, `d3d12` | 9 291 979 bytes | BSD-2-Clause (bgfx) |
| `bgfx-examples` | 30 bgfx examples, each a different load, chosen with `example` | `mtl`, `d3d11`, `d3d12` | 57 350 072 bytes | BSD-2-Clause (bgfx) |
| `godot` | A Godot 4.7.2 scene built from code (400 shapes, 8 lights, shadows, an orbiting camera), no imported assets | `mtl`, `d3d12` | 1 525 bytes, plus two Godot editor builds of 170 622 178 and 86 013 866 bytes | MIT (Godot); the scene is this repository's |

`example_traits` lists, for each of the 30 examples, a class (`cpu_submit`, `compute`, `postprocess`, ...) and how many
encoders per frame to expect native and under D3D12 ([E4](./evidence-data.md): 30 examples, 30 traits), so a recording
can be checked against what the program should do (`tool_workload_list`, `workloads.py:101-112`).

## How a request becomes a command

`workload_command`, `workloads.py:65-91`:

| # | Rule | Message or effect | Line |
|---|---|---|---|
| 1 | The `api` must be in the entry | `api is one of mtl, mtl-x64, vk, d3d11, d3d12 for drawstress` | `:69-70` |
| 2 | A workload with `examples` needs `example` to be one of them; one without them refuses it | | `:71-75` |
| 3 | `dim` needs the entry to have a `dim_variable` (`DRAWSTRESS_DIM`); `size` needs `size_variables` (`DRAWSTRESS_WIDTH`, `DRAWSTRESS_HEIGHT`) and is `WIDTHxHEIGHT` from 320x240 to 7680x4320 | | `:76-77`, `:52-57`, `:82-85` |
| 4 | The folder must be downloaded | `<name> is not downloaded yet; call workload_fetch first` | `:78-79` |
| 5 | `vk` also needs `METAL_TRACE_MOLTENVK`, a folder with `libMoltenVK.dylib` and no spaces, which goes into `DYLD_LIBRARY_PATH` | | `:25-36`, `:86-87` |
| 6 | The result: the program (`<cache>/<name>-<12 hex>/<dir>/<program>`), `wine` when the api needs it and the platform is not Windows, otherwise `native`; the arguments with each `{dir}` replaced by the quoted folder (`dir_in_args`); the program's environment | | `:88-89`, `:94-98`, `:81-87` |

`workload_layer` (`:39-49`) names the layer for the summary: Rosetta for an api marked `rosetta`, MoltenVK (with the
dylib's size and SHA-256) for one marked `moltenvk`, and `None` otherwise: the normal Wine and native layers come from
`layer_of` ([The macOS journey](./macos-journey.md#what-identifies-a-run)).

## How a download is verified

`tool_workload_fetch`, `workloads.py:147-176`. This section has no figure of its own: the steps are a straight line with
one refusal at each of 4 and 6.

1. If `<cache>/<name>-<first 12 hex of sha256>` already exists, return at once (`:154-155`).
2. Otherwise make a temporary folder **inside the cache** (so the final rename stays on one disk) (`:157`).
3. `download` runs `curl -fsSL --proto =https --max-filesize <bytes> --max-time 600` (`:115-120`): https only, never
   more than the size the data file says, at most 10 minutes. It uses `curl` because curl uses the system's certificates.
4. The archive's SHA-256 must equal the pinned one, else `<name>'s download does not match the SHA-256 this package
   pins; nothing was saved` (`:160-161`).
5. `unpack` refuses any member that is not a plain file or folder, that starts with `/` or holds `..` (`:123-129`).
6. For each entry of `downloads` (Godot's two editors), the same, with a **SHA-512** pinned in the data file and
   `unzip` refusing links and bad paths and restoring the Unix modes (`:163-173`, `:132-144`).
7. Rename the temporary `out` folder to the final name (`:174`): the folder appears whole or not at all.

If anything raises, the temporary folder goes with its `with` block (`:157`) and nothing reaches the cache. That is
**confirmed by the code**; a failed download or a wrong hash was **not reproduced** (it needs the network and a wrong
archive; `test_workload_downloads`, `tests/test_recording.py:286`, builds a fake one and pins the refusals; not run for
this guide).

## The pins

The data file pins each archive by its SHA-256, and the cache folder is named with the first 12 characters of it
(`workloads.py:22`), so a new release of an archive is a new folder, never an overwrite ([E4, E5](./evidence-data.md)):

| Workload | Release tag | SHA-256 (full) |
|---|---|---|
| `drawstress` | `workloads-3` | `2b3b01fa2dd0a7d5a1629046305319130d58ce4d843bd22c3f736071c0bfde2e` |
| `bgfx-examples` | `workloads-8` | `1d120363981ced4ae01dad57085258206fbc84f35bd9bcdcfe656b1af355d091` |
| `godot` | `workloads-9` | `a85320f08e1ac2721288441a5317796de4673a6df6fc727b71c135503adc09c5` |

- The archives are built from source by `.github/workflows/workloads.yml` and uploaded to the project's GitHub releases
  with a `.sha256` file (`workloads.yml:35`, `:43`, `:102`, `:111`). Each archive carries a `BUILD.txt` with the commits
  it was built from (E5), and the license of what it contains.
- Whether the published asset's digest today equals the pin was **not verified** (no network call was made for this
  guide), and a download was **not reproduced**.
- Godot's two editor builds come straight from the Godot project's releases and are pinned by SHA-512 in the same file
  (first 16 characters in E4: `38aa16e5bba20839` for macOS, `83decd58fdf67b9d` for Windows).
- Because a new pin makes a new folder and nothing deletes the old one, the cache grows: 8 folders for 3 pins on the
  machine this guide was checked on (E5). The numbers and the open question are in the
  [data guide](../data-and-lifecycle/cache-and-lock.md#the-cache-is-not-the-recordings).

## PresentMon

`tool_presentmon_install`, `workloads.py:179-205`. PresentMon is Intel's console program (MIT) that logs every
`Present()` of a process on Windows. The package pins version 2.6.0 (980 320 bytes, SHA-256
`b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af`, `workloads.py:180-184`). `presentmon_install`:

1. Refuses on any platform but Windows (`:191-192`).
2. Does nothing if the file is already in `%LOCALAPPDATA%\metal-gpu-trace` and its hash matches (`:194-197`).
3. Otherwise downloads into a temporary folder (twice the pinned size is the ceiling, `:201`), checks the SHA-256 and
   replaces the target file (`:199-204`).

It needs administrator rights or membership of the Performance Log Users group to run (the tool's own description,
`workloads.py:187-190`: **not verified** against Intel's documentation).

At **recording** time the engine looks for PresentMon in this order (`find_presentmon`,
`perf_record_windows.py:420-430`; [E10](./evidence.md)): the file named by `PRESENTMON_EXE` (and if that is set but
missing, **none**, with no fallback), the newest `PresentMon*.exe` in the cache folder, then `PresentMon` or
`PresentMon-x64` on the `PATH`. The hash is checked at install only, not at use ([limit 4](./limits.md)).
