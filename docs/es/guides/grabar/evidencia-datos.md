# Evidencia: programas de prueba, caché y archivos de datos

**Lector:** personas que quieren repetir una comprobación sobre los programas de prueba fijados, la caché o el archivo de familias de GPU. Revisado el 2026-11-16. Etiquetas: véase [Grabar](./index.md#como-leer-las-etiquetas).

English: [Evidence: data files](../../../guides/recording/evidence-data.md)

**En corto:** esta página tiene los comandos, con su salida real, detrás de los programas de prueba (sus tamaños, hashes y
los archivos que contienen), de lo que guardaba la caché de descargas en la máquina comprobada y del archivo de familias
de GPU (E4, E5, E7). Las demás comprobaciones (E1, E2, E3, E6, E8, E9, E10) y lo que no se reprodujo están en
[Evidencia](./evidencia.md).

Recogida el 2026-11-16 en un Mac con Apple silicon. Todos los comandos solo leen. Las rutas están acortadas: la carpeta
personal es `~`. Nada de lo que sigue es la salida de una grabación ni de una descarga.

## E4 Los programas de prueba fijados

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

(El host y el proyecto de la URL los corta `.[7:]`; la URL completa es
`https://github.com/<proyecto>/releases/download/<etiqueta>/<archivo>`.) Los tamaños son los que el código usa como
`--max-filesize`. Un `curl` de estas URL, y un `shasum` de lo publicado, **no se reprodujeron**. Lo usa
[Los programas de prueba](./programas-de-prueba.md).

## E5 Qué guarda la caché, frente a los pins

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

Las tres carpetas cuyo nombre coincide con un pin de E4 (`bgfx-examples-1d120363981c`, `drawstress-2b3b01fa2dd0`,
`godot-a85320f08e1a`) son las vigentes; las otras cinco no. No hay ningún `recording.lock` en la carpeta: nada está
grabando. Los nombres de carpeta son los 12 primeros caracteres del hash (`workloads.py:22`).

## E7 Qué guarda el archivo de familias de GPU

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

La salida de `rg` muestra los lectores de los dos archivos: `workloads.py` lee `WORKLOADS`, `traces.py` y `registry.py`
leen `FAMILIES`, y el código de grabación no lee ninguno (`rg` no encuentra `FAMILIES` en `recording.py` ni en
`preflight.py`). Lo usa [Los archivos de datos](./archivos-de-datos.md).
