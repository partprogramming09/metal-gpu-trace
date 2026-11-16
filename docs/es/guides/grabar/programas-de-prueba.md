# Los programas de prueba

**Lector:** personas que añaden o cambian un programa de prueba, o que depuran `workload_fetch` y `presentmon_install` (`workloads.py`, `data/workloads.json`). Revisado el 2026-11-16. Etiquetas: véase [Grabar](./index.md#como-leer-las-etiquetas).

English: [The test programs](../../../guides/recording/test-programs.md)

**En corto:** el proyecto trae tres programas gráficos pequeños para que dos personas en dos Mac graben la misma carga y
comparen números. Cada programa se descarga una vez, y la descarga se acepta solo si su huella (SHA-256, un número que
cambia si cambia un solo byte) es igual a la escrita en el proyecto. Ejemplo, en un Mac: `workload_fetch drawstress` y
luego `perf_record label=t1 workload=drawstress api=mtl seconds=10` (llamada ilustrativa). PresentMon, el registrador de
fotogramas de Intel para Windows, se instala igual.

`workload_list` los muestra, `workload_fetch` descarga uno, y `perf_record` con `workload`, `api` (y `dim`, `example`,
`size`) lo corre.

## Qué hay en la lista (E4)

| Nombre | Qué dibuja | Valores de `api` | Descarga | Licencia |
|---|---|---|---|---|
| `drawstress` | 17-drawstress de bgfx: una cuadrícula de cubos, `dim`³ llamadas de dibujo por fotograma (64 000 con `dim` 40): el coste de un dibujo, nativo y a través de una capa | `mtl`, `mtl-x64` (Metal compilado para x86_64, corrido bajo Rosetta como un programa de Wine), `vk` (Vulkan por MoltenVK), `d3d11`, `d3d12` | 9 291 979 bytes | BSD-2-Clause (bgfx) |
| `bgfx-examples` | 30 ejemplos de bgfx, cada uno una carga distinta, elegidos con `example` | `mtl`, `d3d11`, `d3d12` | 57 350 072 bytes | BSD-2-Clause (bgfx) |
| `godot` | Una escena de Godot 4.7.2 construida desde código (400 formas, 8 luces, sombras, una cámara que orbita), sin recursos importados | `mtl`, `d3d12` | 1 525 bytes, más dos compilaciones del editor de Godot de 170 622 178 y 86 013 866 bytes | MIT (Godot); la escena es de este repositorio |

`example_traits` lista, para cada uno de los 30 ejemplos, una clase (`cpu_submit`, `compute`, `postprocess`, ...) y
cuántos encoders por fotograma esperar nativo y bajo D3D12 ([E4](./evidencia-datos.md): 30 ejemplos, 30 rasgos), de modo
que una grabación se pueda contrastar con lo que el programa debería hacer (`tool_workload_list`, `workloads.py:101-112`).

## Cómo una petición se vuelve un comando

`workload_command`, `workloads.py:65-91`:

| # | Regla | Mensaje o efecto | Línea |
|---|---|---|---|
| 1 | El `api` debe estar en la entrada | `api is one of mtl, mtl-x64, vk, d3d11, d3d12 for drawstress` | `:69-70` |
| 2 | Un workload con `examples` necesita que `example` sea uno de ellos; uno sin ellos lo rechaza | | `:71-75` |
| 3 | `dim` necesita que la entrada tenga `dim_variable` (`DRAWSTRESS_DIM`); `size` necesita `size_variables` (`DRAWSTRESS_WIDTH`, `DRAWSTRESS_HEIGHT`) y es `ANCHOxALTO` de 320x240 a 7680x4320 | | `:76-77`, `:52-57`, `:82-85` |
| 4 | La carpeta debe estar descargada | `<nombre> is not downloaded yet; call workload_fetch first` | `:78-79` |
| 5 | `vk` necesita además `METAL_TRACE_MOLTENVK`, una carpeta con `libMoltenVK.dylib` y sin espacios, que va a `DYLD_LIBRARY_PATH` | | `:25-36`, `:86-87` |
| 6 | El resultado: el programa (`<caché>/<nombre>-<12 hex>/<dir>/<programa>`), `wine` cuando el api lo necesita y la plataforma no es Windows, y si no `native`; los argumentos con cada `{dir}` reemplazado por la carpeta entrecomillada (`dir_in_args`); el entorno del programa | | `:88-89`, `:94-98`, `:81-87` |

`workload_layer` (`:39-49`) nombra la capa para el resumen: Rosetta para un api marcado `rosetta`, MoltenVK (con el
tamaño y el SHA-256 del dylib) para uno marcado `moltenvk`, y `None` en los demás: las capas normales de Wine y nativa
salen de `layer_of` ([El recorrido en macOS](./recorrido-macos.md#que-identifica-una-corrida)).

## Cómo se verifica una descarga

`tool_workload_fetch`, `workloads.py:147-176`. Esta sección no tiene figura propia: los pasos son una línea recta con un
rechazo en el 4 y en el 6.

1. Si ya existe `<caché>/<nombre>-<12 primeros hex del sha256>`, se devuelve de inmediato (`:154-155`).
2. Si no, se crea una carpeta temporal **dentro de la caché** (para que el renombrado final quede en un solo disco)
   (`:157`).
3. `download` corre `curl -fsSL --proto =https --max-filesize <bytes> --max-time 600` (`:115-120`): solo https, nunca
   más que el tamaño que dice el archivo de datos, como mucho 10 minutos. Usa `curl` porque curl usa los certificados del
   sistema.
4. El SHA-256 del archivo debe ser igual al fijado, si no `<nombre>'s download does not match the SHA-256 this package
   pins; nothing was saved` (`:160-161`).
5. `unpack` rechaza todo miembro que no sea un archivo o carpeta normal, que empiece por `/` o contenga `..`
   (`:123-129`).
6. Para cada entrada de `downloads` (los dos editores de Godot), lo mismo, con un **SHA-512** fijado en el archivo de
   datos y `unzip` rechazando enlaces y rutas malas y restaurando los modos de Unix (`:163-173`, `:132-144`).
7. Se renombra la carpeta temporal `out` al nombre final (`:174`): la carpeta aparece entera o no aparece.

Si algo falla, la carpeta temporal se va con su bloque `with` (`:157`) y nada llega a la caché. Eso es **confirmado por el
código**; una descarga fallida o un hash equivocado **no se reprodujo** (hace falta red y un archivo erróneo;
`test_workload_downloads`, `tests/test_recording.py:286`, arma uno falso y fija los rechazos; no ejecutada para esta
guía).

## Las versiones fijadas

El archivo de datos fija cada archivo comprimido por su SHA-256, y la carpeta de la caché se nombra con los 12 primeros
caracteres (`workloads.py:22`), así que una versión nueva de un archivo es una carpeta nueva, nunca una sobrescritura
([E4, E5](./evidencia-datos.md)):

| Workload | Etiqueta de la publicación | SHA-256 (completo) |
|---|---|---|
| `drawstress` | `workloads-3` | `2b3b01fa2dd0a7d5a1629046305319130d58ce4d843bd22c3f736071c0bfde2e` |
| `bgfx-examples` | `workloads-8` | `1d120363981ced4ae01dad57085258206fbc84f35bd9bcdcfe656b1af355d091` |
| `godot` | `workloads-9` | `a85320f08e1ac2721288441a5317796de4673a6df6fc727b71c135503adc09c5` |

- Los archivos los construye desde el código fuente `.github/workflows/workloads.yml` y los sube a las publicaciones de
  GitHub del proyecto con un archivo `.sha256` (`workloads.yml:35`, `:43`, `:102`, `:111`). Cada archivo trae un
  `BUILD.txt` con los commits de que se construyó (E5), y la licencia de lo que contiene.
- Que el hash del archivo publicado hoy sea igual al fijado **no se verificó** (no se hizo ninguna llamada de red para
  esta guía), y una descarga **no se reprodujo**.
- Las dos compilaciones del editor de Godot vienen directo de las publicaciones del proyecto Godot y están fijadas por
  SHA-512 en el mismo archivo (los 16 primeros caracteres en E4: `38aa16e5bba20839` para macOS, `83decd58fdf67b9d` para
  Windows).
- Como un pin nuevo crea una carpeta nueva y nada borra la vieja, la caché crece: 8 carpetas para 3 pins en la máquina
  donde se comprobó esta guía (E5). Las cifras y la pregunta abierta están en la
  [guía de datos](../datos-y-su-ciclo-de-vida/cache-y-candado.md#la-cache-no-son-las-grabaciones).

## PresentMon

`tool_presentmon_install`, `workloads.py:179-205`. PresentMon es el programa de consola de Intel (MIT) que registra cada
`Present()` de un proceso en Windows. El paquete fija la versión 2.6.0 (980 320 bytes, SHA-256
`b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af`, `workloads.py:180-184`). `presentmon_install`:

1. Se rechaza en cualquier plataforma que no sea Windows (`:191-192`).
2. No hace nada si el archivo ya está en `%LOCALAPPDATA%\metal-gpu-trace` y su hash coincide (`:194-197`).
3. Si no, descarga a una carpeta temporal (el doble del tamaño fijado es el techo, `:201`), comprueba el SHA-256 y
   reemplaza el archivo destino (`:199-204`).

Necesita derechos de administrador o pertenecer al grupo Performance Log Users para correr (la descripción de la propia
herramienta, `workloads.py:187-190`: **no verificado** contra la documentación de Intel).

Al **grabar**, el motor busca PresentMon en este orden (`find_presentmon`, `perf_record_windows.py:420-430`;
[E10](./evidencia.md)): el archivo que nombra `PRESENTMON_EXE` (y si está definida pero el archivo no existe,
**ninguno**, sin alternativa), el `PresentMon*.exe` más nuevo en la carpeta de la caché, y luego `PresentMon` o
`PresentMon-x64` en el `PATH`. El hash se comprueba solo al instalar, no al usar ([límite 4](./limites.md)).
