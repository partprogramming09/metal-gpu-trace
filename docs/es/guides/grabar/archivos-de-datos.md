# Los archivos de datos

**Lector:** personas que añaden una familia de GPU o un programa de prueba editando el JSON de `src/metal_gpu_trace/data/`. Revisado el 2026-11-16. Etiquetas: véase [Grabar](./index.md#como-leer-las-etiquetas).

English: [The data files](../../../guides/recording/data-files.md)

**En corto:** el proyecto guarda dos listas de hechos en archivos simples en vez de en el código: qué chips gráficos de
Apple pertenecen a qué familia de GPU, y qué programas de prueba existen con sus huellas de descarga. Añadir un chip o un
programa es editar un archivo y añadir una prueba, no cambiar lógica. Ejemplo: añadir una clave `Apple11` al archivo de
familias hace que su recurso aparezca solo.

Ambos son JSON simple que `config.py:35-36` lee **una vez, al importar**. No hay `try` alrededor: un archivo ausente o
roto detiene el servidor al arrancar, no en la primera llamada (**confirmado por el código**; que ninguna prueba lo cubra
no se comprobó).

## El archivo de familias de GPU

`apple-gpu-families.json`, 63 líneas. Hechos sobre las familias de GPU de Apple silicon Apple7 a Apple10: de cada una,
los chips de Mac y otros chips, las funciones que añade y los límites que difieren (`mesh_grid_threadgroups`,
`texture_2d_px`, ...); luego lo que es igual en todas, notas al pie y `guards` como `M1 only: Apple7 && !Apple8`. Su
`about` dice que son «facts restated from Apple's public documents, not Apple's text» (hechos reformulados de documentos
públicos de Apple, no su texto), y `sources` nombra tres URL, una con la fecha 2026-05-21. Que cada hecho coincida hoy con
esos documentos **no se verificó** para esta guía ([E7](./evidencia-datos.md)).

| Lector | Qué hace | Línea |
|---|---|---|
| `traces.family_of`, `tool_gpu_family` | Busca una familia por clave (`Apple9`) o chip (`M1 Pro`, `A17 Pro`); la coincidencia por chip quita `series` y un sufijo `pro`/`max`/`ultra` | `traces.py:177-197` |
| `registry.RESOURCES` | Un recurso `metal-trace://gpu-families` para todo el archivo y uno por cada clave de familia | `registry.py:12-15` |

| Qué pasa con una entrada ausente | Etiqueta | Línea |
|---|---|---|
| `gpu_family` con un nombre desconocido lanza `unknown family or chip '<nombre>'; try one of Apple10, Apple7, Apple8, Apple9 or a chip such as M1 Pro, M2, M3 Max, A17 Pro` (la lista sale de las claves del archivo, E7) | confirmado | `traces.py:193` |
| Una familia sin `mac_chips` u `other_chips` lanzaría un `KeyError` dentro de `family_of` | **probable**, sin prueba | `traces.py:181` |
| Para añadir una familia, se añade una clave: su recurso aparece solo | confirmado | `registry.py:14-15` |

La grabación no lee este archivo. Se describe aquí porque es la otra mitad de `data/`.

## El archivo de programas de prueba

`workloads.json`, 99 líneas. Una línea `about` y un objeto `workloads` con una entrada por programa de prueba. Los campos y
quién los lee:

| Campo | Significado | Lo lee |
|---|---|---|
| `title`, `about`, `license` | Lo que muestra `workload_list` | `workloads.py:101-112` |
| `url`, `sha256`, `bytes` | El archivo fijado: dónde está, su hash, su tamaño exacto | `workloads.py:159-161` |
| `dir` | La carpeta dentro del archivo que contiene el programa | `workloads.py:89` |
| `apis` | Para cada api: `program`, `args`, `wine` (true: correr bajo Wine), y opcionalmente `rosetta` o `moltenvk` | `workloads.py:43-47`, `:80-89` |
| `dim_variable`, `size_variables` | Las variables de entorno que fijan `dim` y `size` | `workloads.py:76-85` |
| `examples`, `example_traits` | Los nombres que acepta `example`, con el prefijo que toma el programa, y la clase y número de encoders esperados | `workloads.py:71-75`, `:101-112` |
| `downloads` | Archivos extra tomados de otro editor: `url`, `sha512`, `bytes`, `into` | `workloads.py:163-173` |

Qué pasa si una entrada falta o está mal:

- Un **nombre** desconocido lanza `no workload '<nombre>'; workload_list lists them` (`workloads.py:19-20`).
- Un **api**, **example**, **dim** o **size** desconocido lanza los mensajes listados en
  [Los programas de prueba](./programas-de-prueba.md#como-una-peticion-se-vuelve-un-comando).
- Un **campo ausente** dentro de una entrada (digamos `apis`) lanzaría un `KeyError` que el envoltorio de la herramienta
  convierte en un error (**probable**: no se siguió, sin prueba).
- El archivo que se publica lo comprueban pruebas: la entrada de drawstress debe tener un hash de 64 caracteres y una
  url `https`, `mtl-x64` debe estar marcada `rosetta`, y `bgfx-examples` debe venir de `workloads-8`
  (`tests/test_recording.py:127-129`, `:281-284`; no ejecutadas).

**Para añadir un programa:** construir y subir un archivo con el workflow, tomar el SHA-256 de lo subido, añadir la
entrada con su `bytes`, y añadir una prueba que lea la entrada publicada. Fíjalo por hash: el código rechaza cualquier
otra cosa (`workloads.py:160-161`).
