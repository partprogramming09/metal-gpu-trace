# El formato `.gputrace`, hasta donde el código lo conoce

**Lector:** personas que cambian `gputrace_read.py` o se preguntan cuánto fiarse de lo que dicen las herramientas de captura. Revisado el 2026-11-16.

English: [The `.gputrace` format](../../../guides/reading-traces/gputrace-format.md)

> **En corto:** un `.gputrace` es la captura que guarda Xcode de las órdenes de dibujo Metal de un programa. Este proyecto lee
> su archivo principal como una lista de entradas numeradas, cada una una llamada Metal. No las decodifica del todo: guarda el
> número de la llamada y el texto legible que lleva dentro. **Importante:** aquí nadie ha examinado una captura real, así que
> todo lo de abajo es lo que el código supone, no algo comprobado contra Xcode.

## Léelo primero: no se examinó ninguna captura real

El docstring del módulo dice que la cabecera de 8 bytes, los ids de llamada y sus nombres «were worked out here against a
capture whose command list Xcode showed (macOS 27.0.1)» (`gputrace_read.py:7-8`). Pero la investigación del 2026-11-15 que debía
estudiar el formato registra que **no se hizo**, porque «necesita dos capturas reales hechas en Xcode» y no había ninguna en
ese Mac; y la prueba de `capture_diff` (0.26.0) lista como **no probado** «dos capturas reales hechas por Xcode (ninguna había
en este Mac)». Las dos afirmaciones no se concilian en ningún sitio del repositorio (hallazgo F5, [límites](./limites.md)). Por
eso esta guía solo puede decir lo que hace el código y lo que construyen sus pruebas. La disposición de los registros sigue el
proyecto público [tmc/gputrace](https://github.com/tmc/gputrace) (MIT; el módulo lo dice en `gputrace_read.py:6`, y no se
copia código, README «Credits»); **no verificado aquí** contra el código de ese proyecto.

## Lo que el código supone

Confirmado como suposiciones (`gputrace_read.py:1-8`, `:48-69`):

| Elemento | Suposición | Línea |
|---|---|---|
| Un `.gputrace` | una **carpeta** (paquete) guardada desde Xcode; el lector abre **un archivo** de ella, `capture`; ningún otro se lee, y qué más guarda un paquete real no se examinó | `:64-69` |
| `capture` | un flujo llamado **MTSP**: los primeros 4 bytes son ASCII `MTSP`, los 4 siguientes son una palabra que el lector salta (`off = 8`). Sin la marca, el lector empieza en 0 en vez de fallar | `:51` |
| Registros | uno tras otro; cada uno empieza con `[u32 size][i32 call id]`, little-endian (`struct.unpack_from("<Ii", ...)`); `size` es el largo del registro **entero**, esos 8 bytes incluidos, así que el siguiente empieza `size` bytes después | `:53`, `:56`, `:61` |
| Firma | en el desplazamiento `0x24` (36) de un registro: una cadena ASCII corta terminada en un byte cero. Los registros sintéticos de las pruebas usan `Cuu` (`tests/test_capture.py:20`). **Especulación:** nombra los tipos de los argumentos de la llamada | `:57-58` |
| Argumentos | no se decodifican: el lector toma las **cadenas ASCII imprimibles de 3 o más caracteres** tras la firma (`re.findall(rb"[ -~]{3,}", tail)`) y las llama `strings`. En un `pushDebugGroup` la primera es la **etiqueta** que el programa le dio al grupo: el único argumento del que algo depende | `:59` |
| Un `u32` en `+0x20` | lo lista el docstring (`:5`); el código nunca lo lee | `:5` |

```text
 el archivo:  [MTSP][palabra][registro 1][registro 2] ... hasta el final del archivo
              bytes 0-3  4-7   desde el byte 8, uno tras otro

 un registro: [u32 size][i32 id de llamada][ ... ][firma, NUL][argumentos ...]
              la firma empieza en el desplazamiento 0x24 del registro
              size cuenta el registro entero, esos 8 bytes incluidos
```

**Datos malos.** Un registro que no se puede interpretar detiene toda la lectura. Si `size` es menor que 8, o el registro se
saldría del final del archivo, el lector lanza `ValueError`: `<bundle name>: record at 0x<offset> has size <n>; the stream is
not MTSP as expected` (`:54-55`; solo el nombre de la carpeta del paquete, nunca su ruta; anclado por
`tests/test_capture.py:86-97`, no corrido). Si al final quedan menos de 8 bytes se ignoran sin avisar
(`while off + 8 <= len(data)`, `:52`, hallazgo F9).

## Los ids de llamada

`CALLS` (`gputrace_read.py:20-45`) asigna a 24 ids de llamada un nombre de llamada Metal y una certeza (17 + 7, E2). Los ids
son números negativos; el código no da razón de la numeración (**no verificado**). Los nombres son los de la API de Metal:

| Grupo | Llamadas | Certeza |
|---|---|---|
| Marcadores de depuración (3) | `pushDebugGroup` -16244, `insertDebugSignpost` -16245, `popDebugGroup` -16243 | `confirmado` |
| Dibujo (1) | `drawPrimitives` -16218 (una sola sobrecarga, `:88`) | `confirmado` |
| Estado del que depende un dibujo (13) | `setRenderPipelineState`, `setDepthStencilState`, `setStencilReferenceValue`, `setTriangleFillMode`, `setCullMode`, `setDepthClipMode`, `setDepthBias`, `setFrontFacingWinding`, `setBlendColor`, `setViewports`, `setScissorRects`, `setVertexBufferOffset`, `useResource` | `confirmado` |
| Estructura (3) | `renderCommandEncoder` -16353, `endEncoding` -16246, `commandBuffer` -16343 | `probable` |
| Otras (4) | `buffer contents` -10240, `drawMeshThreadgroups` -15416, `drawMeshThreadgroupsWithIndirectBuffer` -15415, `dispatchThreadgroups` -16327 | `probable` |

Las dos palabras están en español en el código (`"confirmado"`, `"probable"`) y se devuelven tal cual en el campo `certainty`
de `capture_summary`. `confirmado` significa «emparejada una por una con la lista de comandos de Xcode» (`:19`); `probable` es
un nombre que encaja pero no se emparejó. Un registro cuyo id no está en la tabla tiene `name: None`: se cuenta, se muestra por
id y firma, y nunca se nombra. Si una captura real usa ids que no están aquí (los dibujos indexados, instanciados, indirectos y
de malla tienen los suyos, según el comentario de `:88`) es **desconocido**.

Siguiente: [las herramientas de captura](./herramientas-captura.md). Volver al [índice](./index.md).
