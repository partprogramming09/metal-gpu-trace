# The data files

**Reader:** people who add a GPU family or a test program by editing JSON in `src/metal_gpu_trace/data/`. Reviewed 2026-11-16. Labels: see [Recording](./index.md#how-to-read-the-labels).

Español: [Los archivos de datos](../../es/guides/grabar/archivos-de-datos.md)

**In short:** the project keeps two lists of facts in plain files instead of in the code: which Apple graphics chips
belong to which GPU family, and which test programs exist with their download fingerprints. Adding a chip or a program is
an edit of a file plus a test, not a change of logic. Example: adding a key `Apple11` to the families file makes its
resource appear by itself.

Both files are plain JSON read **once, at import**, by `config.py:35-36`. There is no `try` around them: a missing or
broken file stops the server at start-up, not at the first call (**confirmed by the code**; that no test covers it was
not checked).

## The GPU families file

`apple-gpu-families.json`, 63 lines. Facts about Apple silicon GPU families Apple7 to Apple10: for each, the Mac chips
and other chips, the features it adds and the limits that differ (`mesh_grid_threadgroups`, `texture_2d_px`, ...); then
what is the same on all, footnotes and `guards` such as `M1 only: Apple7 && !Apple8`. Its `about` says these are "facts
restated from Apple's public documents, not Apple's text", and `sources` names three URLs, one with the date 2026-05-21.
Whether each fact matches those documents today was **not verified** for this guide ([E7](./evidence-data.md)).

| Reader | What it does | Line |
|---|---|---|
| `traces.family_of`, `tool_gpu_family` | Finds a family by key (`Apple9`) or chip (`M1 Pro`, `A17 Pro`); the chip match drops `series` and a `pro`/`max`/`ultra` suffix | `traces.py:177-197` |
| `registry.RESOURCES` | One resource `metal-trace://gpu-families` for the whole file and one per family key | `registry.py:12-15` |

| What happens with a missing entry | Label | Line |
|---|---|---|
| `gpu_family` with an unknown name raises `unknown family or chip '<name>'; try one of Apple10, Apple7, Apple8, Apple9 or a chip such as M1 Pro, M2, M3 Max, A17 Pro` (the list is built from the file's keys, E7) | confirmed | `traces.py:193` |
| A family without `mac_chips` or `other_chips` would raise a `KeyError` inside `family_of` | **probable**, not tested | `traces.py:181` |
| To add a family, add a key: its resource appears by itself | confirmed | `registry.py:14-15` |

Recording does not read this file. It is described here because it is the other half of `data/`.

## The workloads file

`workloads.json`, 99 lines. An `about` line and a `workloads` object with one entry per test program. The fields and who
reads them:

| Field | Meaning | Read by |
|---|---|---|
| `title`, `about`, `license` | What `workload_list` shows | `workloads.py:101-112` |
| `url`, `sha256`, `bytes` | The pinned archive: where it is, its hash, its exact size | `workloads.py:159-161` |
| `dir` | The folder inside the archive that holds the program | `workloads.py:89` |
| `apis` | For each api: `program`, `args`, `wine` (true: run under Wine), and optionally `rosetta` or `moltenvk` | `workloads.py:43-47`, `:80-89` |
| `dim_variable`, `size_variables` | The environment variables that `dim` and `size` set | `workloads.py:76-85` |
| `examples`, `example_traits` | The names `example` accepts, with the prefix the program takes, and the expected class and encoder counts | `workloads.py:71-75`, `:101-112` |
| `downloads` | Extra archives fetched from another publisher: `url`, `sha512`, `bytes`, `into` | `workloads.py:163-173` |

What happens if an entry is missing or wrong:

- An unknown **name** raises `no workload '<name>'; workload_list lists them` (`workloads.py:19-20`).
- An unknown **api**, **example**, **dim** or **size** raises the messages listed in
  [The test programs](./test-programs.md#how-a-request-becomes-a-command).
- A **missing field** inside an entry (say `apis`) would raise a `KeyError` that the tool wrapper turns into an error
  (**probable**: not traced, not tested).
- The shipped file is checked by tests: the drawstress entry must have a 64-character hash and an `https` url,
  `mtl-x64` must be marked `rosetta`, and `bgfx-examples` must come from `workloads-8`
  (`tests/test_recording.py:127-129`, `:281-284`; not run).

**To add a program:** build and upload an archive with the workflow, take the SHA-256 of what was uploaded, add the entry
with its `bytes`, and add a test that reads the shipped entry. Pin by hash: the code refuses anything else
(`workloads.py:160-161`).
