# El worker

**Lector:** personas que cambian cómo se encolan, comprueban, cancelan o informan las llamadas a herramientas. Revisado el 2026-11-16.

English: [Worker](../../../guides/server-and-transport/worker.md) · [Índice](./index.md)

**En corto:** el worker es el único empleado que hace el trabajo. Las peticiones esperan en una fila de 64 como máximo; las toma de una en una, comprueba cada una, la ejecuta y devuelve la respuesta. Un «para» del cliente es una bandera que mira la herramienta en curso. Con un solo worker, dos grabaciones nunca corren juntas.

El estado de `worker.py` son cinco objetos a nivel de módulo (`:30-33`):

| Nombre | Qué guarda |
|---|---|
| `QUEUE`, con `WAKE` (una `Condition`) | Las llamadas que esperan: tuplas `(message, reply, event)` |
| `WORKER` | Una lista, vacía hasta la primera llamada, y luego el único hilo (**especulación:** una lista para consultarla y asignarla sin `global`) |
| `CALLS` | Id de petición a bandera de cancelación, para las llamadas en curso |
| `CANCELLED` | Ids que el cliente canceló y cuya respuesta aún no ha salido |
| `CURRENT` | Un dato local al hilo con la bandera de la llamada que el hilo ejecuta, cuando su transporte dio una |

## Poner una llamada en la cola (`submit`, `:41-57`)

Bajo el candado, una llamada se añade si hay menos de `MAX_QUEUE` (64) esperando. La primera llamada arranca el hilo (`daemon=True`, `:49-51`): un servidor al que nunca se pidió una herramienta no tiene worker. Si ya hay 64, la llamada **no** se encola: su id sale de `CALLS` y el `reply` del transporte recibe de inmediato un resultado de error `64 calls are already waiting; try again when one finishes` (`:53-57`), redactado en la era de la petición por `protocol.finish` (el `finish` de `worker.configure`). Lo fijan `test_queue` (`tests/test_server.py:354`) y tres pruebas que comprueban que la entrada queda limpia (`:421`, `:453`).

## Ejecutar una (`work`, `:60-80`)

El hilo toma el primer elemento y ejecuta `reply(_answer(message))`: `_answer` es `protocol.answer` (`protocol.handle` con red de seguridad, `protocol.py:191-198`), `reply` la función del transporte. Un elemento `None` es la señal de parada (`:67-68`). Si la respuesta falla (cliente que se fue a mitad de la escritura) la excepción se captura, se registra como `reply to <id> failed: <NombreDeExcepción>` y el hilo sigue (`:73-74`); sin eso una tubería rota acabaría con el hilo y toda llamada posterior esperaría para siempre (`test_worker_survives_a_failing_reply`, `tests/test_server.py:951`). En el `finally`, bajo el candado, la entrada sale de `CALLS` (solo si sigue siendo la suya) y el id de `CANCELLED` (`:75-80`).

## Comprobaciones antes de que corra una herramienta (`call`, `:143-172`)

`protocol.handle` llama a `worker.call` para un `tools/call` (`protocol.py:170`):

| Paso | Falla cuando | El cliente recibe | Línea |
|---|---|---|---|
| Ya cancelada | La bandera estaba activa antes de empezar la función | `the call was cancelled before it started` (resultado de error) | `:153-154` |
| `project.check()` | El `metal-gpu-trace.json` está mal | El mensaje del proyecto (resultado de error); el servidor sigue funcionando | `:155` |
| `check_arguments` | `arguments` no es un objeto, falta un nombre o no está en el esquema | `bad arguments: unknown argument x`, `missing argument y` o `arguments must be an object` | `:156-157`, `:130-140` |
| La función | Lanza `ToolError`, `FileNotFoundError`, `ValueError`, `RuntimeError` o `TimeoutExpired` | El texto de la excepción (resultado de error) | `:158`, `:165-166` |
| La función | Lanza cualquier otra cosa | Solo `internal error: <NombreDeExcepción>` | `:167-168` |
| El resultado | No es un diccionario | `<herramienta> returned <tipo>, not an object` | `:159-160` |
| El resultado | JSON de más de `MAX_TEXT` (40 000 caracteres) | `the result has N characters; ask for a smaller page with limit` | `:161-163`, `config.py:45` |

`check_arguments` solo comprueba nombres (`required`, `properties`); los tipos los comprueba cada herramienta (`worker.py:130-132`). Un éxito devuelve `content` (JSON como texto) y `structuredContent` (el mismo objeto) (`:164`). Los 40 000 vienen de un límite de cliente: `config.py:44` dice que los resultados se mantienen bajo el límite de 50 000 caracteres de Claude Code, por encima del cual lo guarda en un archivo. Por último, `call` registra `<herramienta> ok|error in <segundos> s` (`:171`): ningún argumento, etiqueta, ruta ni resultado ([Logs](./logs.md)).

## Cancelar

Dos cancelaciones, porque stdio y HTTP saben cosas distintas de sus clientes.

| Cancelación | Clave | Qué hace |
|---|---|---|
| `cancel_call(request_id)` (`:93-115`) | **id** | Una llamada en la cola se saca y se responde de inmediato con `the call was cancelled before it started` (`:101-111`); a una que corre se le activa la bandera (`:112-115`) y se detiene en su siguiente mirada. En ambos casos el id queda en `CANCELLED` hasta que sale la respuesta, así que un transporte que puede callar (stdio) no escribe nada (`stdio.py:19-22`). Un id que no puede ser clave de diccionario se ignora (`:96-99`) |
| `cancel_item(message, event)` (`:118-127`) | **identidad** | Lo usa HTTP cuando un cliente moderno cierra su conexión: dos clientes HTTP pueden enviar el mismo id, así que compara el mensaje y la bandera exactos, saca de la cola un mensaje sin responderlo (su cliente se fue) y activa la bandera (`test_http_close_spares_another_client_with_the_same_id`, `tests/test_server.py:1107`) |

La grabación nota la bandera con `recording.cancelled()`, un dato local al hilo (`recording.py:224-230`) que `worker.call` llena al empezar con la bandera de la llamada (`worker.py:147-148`); véase [Grabar](../grabar/index.md).

## Progreso

Solo una petición con `progressToken` tiene progreso. `worker.call` pone en `recording.RUN.progress` una función que envía `notifications/progress` (`worker.py:149-151`), salvo que el id ya se haya cancelado; `recording.progress` la llama cada `config.PROGRESS_TICKS` (5) segundos mientras graba. Sale por `_send`, que `metal_trace_mcp.py:50` fijó a `stdio.send`: correcto para stdio, incorrecto para HTTP, y por eso el manejador HTTP quita `progressToken` antes de encolar (`http_transport.py:145-151`; [límite 11](./limites.md)).
