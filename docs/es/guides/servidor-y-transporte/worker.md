# El worker

**Lector:** personas que cambian cómo se encolan, comprueban, cancelan o informan las llamadas a herramientas. Revisado el 2026-11-16.

English: [Worker](../../../guides/server-and-transport/worker.md) · [Índice](./index.md)

**En corto:** el worker es el único empleado que hace el trabajo. Las peticiones esperan en una fila de 64 como máximo; el
worker las toma de una en una, comprueba cada una, la ejecuta y devuelve la respuesta. Un «para» del cliente es una
bandera que mira la herramienta en curso. Como hay un solo worker, dos grabaciones nunca pueden correr juntas.

`worker.py` ejecuta las llamadas a herramientas. Su estado son cinco objetos a nivel de módulo (`:30-33`):

| Nombre | Qué guarda |
|---|---|
| `QUEUE`, con `WAKE` (una `Condition`) | Las llamadas que esperan al hilo: tuplas `(message, reply, event)` |
| `WORKER` | Una lista vacía hasta la primera llamada, y luego con el único hilo (**especulación:** una lista para que el módulo pueda consultarla y asignarla sin `global`) |
| `CALLS` | Id de petición a bandera de cancelación, para las llamadas en curso |
| `CANCELLED` | Ids que el cliente canceló y cuya respuesta aún no ha salido |
| `CURRENT` | Un dato local al hilo que guarda la bandera de la llamada que el hilo ejecuta, cuando su transporte dio una |

## Poner una llamada en la cola (`submit`, `:41-57`)

Una llamada se añade bajo el candado si hay menos de `MAX_QUEUE` (64) esperando. La primera llamada arranca el hilo
(`daemon=True`, `:49-51`): un servidor al que nunca se le ha pedido una herramienta no tiene worker. Si ya hay 64
esperando, la llamada **no** se encola: su id sale de `CALLS` y la función `reply` del transporte recibe de inmediato un
resultado de error que dice `64 calls are already waiting; try again when one finishes` (`:53-57`), redactado en la era
de la petición con `protocol.finish` (el `finish` de `worker.configure`). Lo fijan `test_queue`
(`tests/test_server.py:354`) y las tres pruebas que comprueban que la entrada queda limpia (`:421`, `:453`).

## Ejecutar una (`work`, `:60-80`)

El hilo espera a que la cola tenga algo, toma el primer elemento y ejecuta `reply(_answer(message))`: `_answer` es
`protocol.answer`, que es `protocol.handle` con una red de seguridad (`protocol.py:191-198`), y `reply` es la función que
dio el transporte. Un elemento `None` es la señal de parada (`:67-68`). Si la respuesta falla (un cliente que se fue a mitad
de la escritura) la excepción se captura y se registra como `reply to <id> failed: <NombreDeExcepción>`, y el hilo sigue con
la llamada siguiente (`:73-74`): sin esa captura, una tubería rota acabaría con el hilo y toda llamada posterior esperaría
para siempre (`test_worker_survives_a_failing_reply`, `tests/test_server.py:951`). En el `finally`, bajo el candado, la
entrada de la llamada se quita de `CALLS` (solo si sigue siendo la suya) y su id de `CANCELLED` (`:75-80`).

## Comprobaciones antes de que corra una herramienta (`call`, `:143-172`)

`protocol.handle` llama a `worker.call` para un `tools/call` (`protocol.py:170`). Sus pasos, con lo que recibe el cliente cuando falla cada uno:

| Paso | Falla cuando | El cliente recibe | Línea |
|---|---|---|---|
| Ya cancelada | La bandera estaba activa antes de que empezara la función | `the call was cancelled before it started` (resultado de error) | `:153-154` |
| `project.check()` | El `metal-gpu-trace.json` está mal | El mensaje del propio proyecto (resultado de error); el servidor sigue funcionando | `:155` |
| `check_arguments` | `arguments` no es un objeto, o falta un nombre, o un nombre no está en el esquema | `bad arguments: unknown argument x`, `missing argument y` o `arguments must be an object` | `:156-157`, `:130-140` |
| La función | Lanza `ToolError`, `FileNotFoundError`, `ValueError`, `RuntimeError` o `TimeoutExpired` | El texto de la excepción (resultado de error) | `:158`, `:165-166` |
| La función | Lanza cualquier otra cosa | `internal error: <NombreDeExcepción>` y nada más | `:167-168` |
| El resultado | No es un diccionario | `<herramienta> returned <tipo>, not an object` | `:159-160` |
| El resultado | Su JSON pasa de `MAX_TEXT` (40 000 caracteres) | `the result has N characters; ask for a smaller page with limit` | `:161-163`, `config.py:45` |

`check_arguments` solo comprueba los nombres (`required` y los de `properties`); los tipos los comprueba cada herramienta
(`worker.py:130-132`, el docstring). Un éxito devuelve `content` (el JSON como texto) y `structuredContent` (el mismo
objeto), de modo que un cliente puede usar cualquiera (`:164`). Los 40 000 vienen de un límite de cliente: el comentario de
`config.py:44` dice que los resultados se mantienen bajo el límite de 50 000 caracteres de Claude Code, por encima del cual
lo guarda en un archivo.

Por último, `call` escribe la línea de log `<herramienta> ok|error in <segundos> s` (`:171`). Fíjate en lo que no lleva:
ningún argumento, etiqueta, ruta ni resultado. Véase [Logs](./logs.md).

## Cancelar

Hay dos cancelaciones, porque stdio y HTTP saben cosas distintas de sus clientes.

| Cancelación | Clave | Qué hace |
|---|---|---|
| `cancel_call(request_id)` (`:93-115`) | **id** | Una llamada que sigue en la cola se saca y se responde de inmediato con `the call was cancelled before it started` (`:101-111`); a una que corre se le activa la bandera (`:112-115`) y la herramienta se detiene en su siguiente mirada. En ambos casos el id va a `CANCELLED` hasta que sale la respuesta, así que un transporte que puede callar (stdio) no escribe nada (`stdio.py:19-22`). Un id que no puede ser clave de diccionario se ignora (`:96-99`) |
| `cancel_item(message, event)` (`:118-127`) | **identidad** | Lo usa HTTP cuando un cliente moderno cierra su conexión: dos clientes HTTP pueden enviar el mismo id, así que compara el mensaje exacto y la bandera exacta, saca de la cola un mensaje sin responderlo (su cliente se fue) y activa la bandera (`test_http_close_spares_another_client_with_the_same_id`, `tests/test_server.py:1107`) |

Cómo nota la grabación la bandera está en [Grabar](../grabar/index.md): `recording.cancelled()` lee un dato local al hilo
(`recording.py:224-230`) que `worker.call` llena al empezar con la bandera propia de la llamada (`worker.py:147-148`).

## Progreso

Solo una llamada cuya petición lleva un `progressToken` tiene progreso. `worker.call` pone en `recording.RUN.progress` una
función que envía `notifications/progress` (`worker.py:149-151`), salvo que el id ya se haya cancelado. `recording.progress`
la llama cada `config.PROGRESS_TICKS` (5) segundos mientras corre una grabación. La notificación sale por `_send`, que
`metal_trace_mcp.py:50` fijó a `stdio.send`. Eso es correcto para stdio e incorrecto para HTTP, y por eso el manejador HTTP
quita `progressToken` antes de encolar una llamada (`http_transport.py:145-151`; [límite 11](./limites.md)).
