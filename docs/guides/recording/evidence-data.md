# Evidence: test programs, cache and data files

**Reader:** people who want to repeat a check on the pinned test programs, the cache or the GPU families file. Reviewed 2026-11-16. Labels: see [Recording](./index.md#how-to-read-the-labels).

Español: [Evidencia: datos](../../es/guides/grabar/evidencia-datos.md)

**In short:** this page has the commands, with their real output, behind the test programs (their sizes, hashes and the
files they hold), what the download cache contained on the machine checked, and the GPU families file (E4, E5, E7). The
other checks (E1, E2, E3, E6, E8, E9, E10) and what was not reproduced are in [Evidence](./evidence.md).

Collected on 2026-11-16 on an Apple silicon Mac. All commands only read. Paths are shortened: the home folder is `~`.
Nothing here is the output of a recording or a download.

## E4 The pinned test programs

```text
$ jq -r '.workloads|to_entries[]|"\(.key)\t\(.value.sha256)\t\(.value.bytes)\t\(.value.url|split("/")|.[7:]|join("/"))\t\(.value.apis|keys|join(","))"' src/metal_gpu_trace/data/workloads.json
drawstress	2b3b01fa2dd0a7d5a1629046305319130d58ce4d843bd22c3f736071c0bfde2e	9291979	workloads-3/drawstress-workloads-3.tar.gz	d3d11,d3d12,mtl,mtl-x64,vk
bgfx-examples	1d120363981ced4ae01dad57085258206fbc84f35bd9bcdcfe656b1af355d091	57350072	workloads-8/bgfx-examples-workloads-8.tar.gz	d3d11,d3d12,mtl
godot	a85320f08e1ac2721288441a5317796de4673a6df6fc727b71c135503adc09c5	1525	workloads-9/godot-workloads-9.tar.gz	d3d12,mtl

$ jq -r '.workloads.godot.downloads[]|"\(.into)\t\(.bytes)\t\(.sha512[0:16])"' src/metal_gpu_trace/data/workloads.json
bin/mac	170622178	38aa16e5bba20839
bin/win	86013866	83decd58fdf67b9d

$ jq -r '.workloads["bgfx-examples"].examples|length' src/metal_gpu_trace/data/workloads.json
30
$ jq -r '.workloads["bgfx-examples"].example_traits|length' src/metal_gpu_trace/data/workloads.json
30

$ jq -r '.workloads.drawstress.apis|to_entries[]|"\(.key) \(.value|tostring)"' src/metal_gpu_trace/data/workloads.json
mtl {"program":"drawstress","args":"--mtl","wine":false}
mtl-x64 {"program":"drawstress-x64","args":"--mtl","wine":false,"rosetta":true}
vk {"program":"drawstress","args":"--vk","wine":false,"moltenvk":true}
d3d11 {"program":"drawstress.exe","args":"--d3d11","wine":true}
d3d12 {"program":"drawstress.exe","args":"--d3d12","wine":true}
```

(The URL's host and project are cut by `.[7:]`; the full URL is
`https://github.com/<project>/releases/download/<tag>/<file>`.) The sizes are the ones the code uses as
`--max-filesize`. A `curl` of these URLs, and a `shasum` of what is published, were **not reproduced**. Used by
[The test programs](./test-programs.md).

## E5 What the cache holds, against the pins

```text
$ ls -a ~/Library/Caches/metal-gpu-trace
.
..
bgfx-examples-1d120363981c
bgfx-examples-320a6b3bbc11
bgfx-examples-9c1bd6164b4a
bgfx-examples-bd41458ee01e
bgfx-examples-c5b25350c15e
drawstress-2b3b01fa2dd0
drawstress-f7e25cbb8c4a
godot-a85320f08e1a

$ du -sh ~/Library/Caches/metal-gpu-trace
942M	~/Library/Caches/metal-gpu-trace

$ cd ~/Library/Caches/metal-gpu-trace
$ ls -1 drawstress-2b3b01fa2dd0/drawstress
BUILD.txt
LICENSE-bgfx
bgfx-drawstress-env.patch
drawstress
drawstress-x64
drawstress.exe

$ ls -1 godot-a85320f08e1a/godot godot-a85320f08e1a/godot/bin
godot-a85320f08e1a/godot:
BUILD.txt
bin
project

godot-a85320f08e1a/godot/bin:
mac
win

$ sed -n 2,6p drawstress-2b3b01fa2dd0/drawstress/BUILD.txt
GENie f7055e309a5c2bc28d7abd35960e14b9864fc5ea
bgfx 71539c41e7e782ccf30f19ae4498d25ddc7bc68c
bx d4e6ed3cf4f75c355bb04088bc1c13cd919aafa6
bimg 671fe06dd7012a1ab85aa931019ed16112909756
llvm-mingw 20260908 ucrt macos-universal
```

The three folder names that match a pin in E4 (`bgfx-examples-1d120363981c`, `drawstress-2b3b01fa2dd0`,
`godot-a85320f08e1a`) are the current ones; the other five do not. No `recording.lock` is in the folder: nothing is
recording. The folder names are the first 12 characters of the hash (`workloads.py:22`).

## E7 What the GPU families file holds

```text
$ jq -r '.families|keys|join(" ")' src/metal_gpu_trace/data/apple-gpu-families.json
Apple10 Apple7 Apple8 Apple9

$ jq -r '.families.Apple9|keys|join(" ")' src/metal_gpu_trace/data/apple-gpu-families.json
adds limits mac_chips other_chips

$ jq -r '.families|to_entries[]|"\(.key): \(.value.mac_chips|join(", "))"' src/metal_gpu_trace/data/apple-gpu-families.json
Apple7: M1, M1 Pro, M1 Max, M1 Ultra
Apple8: M2 series
Apple9: M3 series, M4 series
Apple10: M5 series

$ jq -r '.sources.feature_set_tables_date' src/metal_gpu_trace/data/apple-gpu-families.json
2026-05-21

$ rg -n "FAMILIES|WORKLOADS" src/metal_gpu_trace --glob '*.py' | cut -c1-120
src/metal_gpu_trace/workloads.py:19:    if name not in config.WORKLOADS:
src/metal_gpu_trace/workloads.py:21:    entry = config.WORKLOADS[name]
src/metal_gpu_trace/workloads.py:105:    for name, entry in config.WORKLOADS.items():
src/metal_gpu_trace/traces.py:180:    for key, family in config.FAMILIES["families"].items():
src/metal_gpu_trace/traces.py:193:        raise paths.ToolError(f"unknown family or chip {name!r}; try one of {', '.join
src/metal_gpu_trace/traces.py:195:    return {"family": key, **config.FAMILIES["families"][key], "same_on_all": config.F
src/metal_gpu_trace/traces.py:196:            "footnotes": config.FAMILIES["footnotes"], "guards": config.FAMILIES["guards"], "sources": config.FAMILIES["sources"]}
src/metal_gpu_trace/registry.py:12:RESOURCES = {"metal-trace://gpu-families": ("Apple GPU families", config.FAMILIES["ab
src/metal_gpu_trace/registry.py:15:    for key in config.FAMILIES["families"]}
src/metal_gpu_trace/config.py:35:FAMILIES = json.loads((PACKAGE_DIR / "data" / "apple-gpu-families.json").read_text(enco
src/metal_gpu_trace/config.py:36:WORKLOADS = json.loads((PACKAGE_DIR / "data" / "workloads.json").read_text(encoding="ut
```

The `rg` output has the readers of the two files: `workloads.py` reads `WORKLOADS`, `traces.py` and `registry.py` read
`FAMILIES`, and recording code reads neither (the `rg` finds no `FAMILIES` in `recording.py` or `preflight.py`). Used by
[The data files](./data-files.md).
