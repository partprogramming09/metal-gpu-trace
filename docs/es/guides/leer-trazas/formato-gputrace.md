# El formato `.gputrace`, hasta donde el código lo conoce

**Lector:** personas que cambian `gputrace_read.py` o se preguntan cuánto fiarse de lo que dicen las herramientas de captura. Revisado el 2026-11-16.

English: [The `.gputrace` format](../../../guides/reading-traces/gputrace-format.md)

> **En corto:** un `.gputrace` es la captura que guarda Xcode de las órdenes de dibujo Metal de un programa. Este proyecto lee
> su archivo principal como una lista de entradas numeradas, una llamada Metal cada una, guardando el número de la llamada y el
> texto legible. **Importante:** aquí nadie ha examinado una captura real, así que todo lo de abajo es lo que el código supone,
> no algo comprobado contra Xcode.

## Léelo primero: no se examinó ninguna captura real

El docstring del módulo dice que la cabecera de 8 bytes, los ids de llamada y sus nombres «were worked out here against a
capture whose command list Xcode showed (macOS 27.0.1)» (`gputrace_read.py:7-8`). Pero la investigación del 2026-11-15 registra
que el estudio del formato **no se hizo** («necesita dos capturas reales hechas en Xcode», ninguna en ese Mac), y la prueba de
`capture_diff` (0.26.0) lista como **no probado** «dos capturas reales hechas por Xcode (ninguna había en este Mac)». Nada las
concilia (F5, [límites](./limites.md)), así que esta guía solo dice lo que hace el código y lo que construyen sus pruebas. La
disposición de los registros sigue el proyecto público [tmc/gputrace](https://github.com/tmc/gputrace) (MIT; `gputrace_read.py:6`;
no se copia código, README «Credits»); **no verificado aquí**.

## Lo que el código supone

Confirmado como suposiciones (`gputrace_read.py:1-8`, `:48-69`):

| Elemento | Suposición | Línea |
|---|---|---|
| Un `.gputrace` | una **carpeta** (paquete) guardada desde Xcode; el lector abre **un archivo**, `capture`; qué más guarda un paquete real no se examinó | `:64-69` |
| `capture` | un flujo llamado **MTSP**: 4 bytes ASCII `MTSP`, luego una palabra de 4 bytes que el lector salta (`off = 8`). Sin la marca, el lector empieza en 0 en vez de fallar | `:51` |
| Registros | uno tras otro, cada uno `[u32 size][i32 call id]`, little-endian (`struct.unpack_from("<Ii", ...)`); `size` es el registro **entero**, esos 8 bytes incluidos, así que el siguiente empieza `size` bytes después | `:53`, `:56`, `:61` |
| Firma | en el desplazamiento `0x24` (36) de un registro: una cadena ASCII corta terminada en cero (`Cuu` en las pruebas, `tests/test_capture.py:20`). **Especulación:** nombra los tipos de los argumentos | `:57-58` |
| Argumentos | no se decodifican: las **cadenas ASCII imprimibles de 3 o más caracteres** tras la firma (`re.findall(rb"[ -~]{3,}", tail)`) son `strings`. En un `pushDebugGroup` la primera es la **etiqueta** que el programa dio al grupo: el único argumento del que algo depende | `:59` |
| Un `u32` en `+0x20` | lo lista el docstring; el código nunca lo lee | `:5` |

**Datos malos.** Un registro que no se puede interpretar detiene la lectura: si `size` es menor que 8 o el registro se sale del
final, `ValueError`: `<bundle name>: record at 0x<offset> has size <n>; the stream is not MTSP as expected` (`:54-55`; solo el
nombre del paquete, nunca su ruta; `tests/test_capture.py:86-97`, no corrido). Si al final quedan menos de 8 bytes se ignoran
sin avisar (`while off + 8 <= len(data)`, `:52`, F9).

## Los ids de llamada

`CALLS` (`gputrace_read.py:20-45`) asigna a 24 ids un nombre de llamada Metal y una certeza (17 + 7, E2). Los ids son negativos;
el código no da razón de la numeración (**no verificado**). Los nombres son los de la API de Metal:

| Grupo | Llamadas | Certeza |
|---|---|---|
| Marcadores de depuración (3) | `pushDebugGroup` -16244, `insertDebugSignpost` -16245, `popDebugGroup` -16243 | `confirmado` |
| Dibujo (1) | `drawPrimitives` -16218 (una sola sobrecarga, `:88`) | `confirmado` |
| Estado del que depende un dibujo (13) | `setRenderPipelineState`, `setDepthStencilState`, `setStencilReferenceValue`, `setTriangleFillMode`, `setCullMode`, `setDepthClipMode`, `setDepthBias`, `setFrontFacingWinding`, `setBlendColor`, `setViewports`, `setScissorRects`, `setVertexBufferOffset`, `useResource` | `confirmado` |
| Estructura (3) | `renderCommandEncoder` -16353, `endEncoding` -16246, `commandBuffer` -16343 | `probable` |
| Otras (4) | `buffer contents` -10240, `drawMeshThreadgroups` -15416, `drawMeshThreadgroupsWithIndirectBuffer` -15415, `dispatchThreadgroups` -16327 | `probable` |

Las dos palabras están en español en el código y se devuelven tal cual en el campo `certainty` de `capture_summary`. `confirmado`
significa «emparejada una por una con la lista de comandos de Xcode» (`:19`); `probable` encaja pero no se emparejó. Un registro
cuyo id no está en la tabla tiene `name: None`: se cuenta, se muestra por id y firma, y nunca se nombra. Si una captura real usa
ids que no están aquí (los dibujos indexados, instanciados, indirectos y de malla tienen los suyos, según `:88`) es **desconocido**.

Siguiente: [las herramientas de captura](./herramientas-captura.md). Volver al [índice](./index.md).
