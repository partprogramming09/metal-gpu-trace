# Cuando falla

**Lector:** personas que necesitan saber por qué un cliente recibió un error, un estado o un silencio. Revisado el 2026-11-16.

English: [When it fails](../../../guides/server-and-transport/failures.md) · [Índice](./index.md)

**En corto:** una petición mala no detiene el servidor. Cada clase de fallo tiene una respuesta fija: un error de
protocolo para una petición mal formada, un «resultado de error» para una herramienta que falló, y a veces silencio
cuando el cliente ya se fue o canceló. La tabla da, por cada fallo, qué ve el cliente y qué hace el servidor.

La primera columna es lo que sale mal; la segunda, lo que ve el cliente.

| Qué sale mal | Qué recibe el cliente | Qué hace el servidor | Línea |
|---|---|---|---|
| Una línea que no es JSON (stdio) | `-32700 parse error`, `id: null` | Sigue con la línea siguiente | `stdio.py:46-47` |
| JSON que no es un objeto (`[1]`) | `-32600 Invalid Request` | | `protocol.py:88-89` |
| Una petición sin `jsonrpc: "2.0"` o sin un `method` de texto | `-32600 Invalid Request` | | `:94-95` |
| Un método desconocido | `-32601 unknown method <m>` | | `:173` |
| Una herramienta desconocida | `-32602 unknown tool <nombre>`: un error JSON-RPC, no un resultado `isError` | | `:167-169` |
| Argumentos erróneos a una herramienta conocida | Un resultado `isError` `bad arguments: ...` | | `worker.py:156-157` |
| Una herramienta lanza algo esperado | Un resultado `isError` con su texto | Una línea de log, `error` | `:165-166`, `:171` |
| Una herramienta lanza otra cosa | Un resultado `isError` `internal error: <NombreDeExcepción>` | Una línea de log, `error` | `:167-168` |
| Hay 64 llamadas esperando | Un resultado `isError` de inmediato | No se encola nada | `:53-57` |
| La llamada se cancela mientras está en la cola | stdio: nada. HTTP: un resultado `isError` `the call was cancelled before it started` | La llamada sale de la cola | `:101-111` |
| La llamada se cancela mientras corre | stdio: nada. HTTP, era antigua: un resultado `isError`. HTTP, moderna: nada, la conexión está cerrada | La herramienta se detiene en su siguiente mirada; una grabación limpia | `:112-115`; `http_transport.py:155-161` |
| El `metal-gpu-trace.json` está mal | Toda herramienta, y toda lectura de `metal-trace://runs/...`, responde con su mensaje | El servidor sigue funcionando; los recursos responden `-32603` | `worker.py:155`, `protocol.py:131-133` |
| Una excepción dentro de `protocol.handle` | `-32603 internal error` | Una línea de log; stdio y HTTP siguen | `stdio.py:48-50`, `http_transport.py:163-168`, `protocol.py:191-198` |
| El cliente se fue mientras el worker escribía (stdio) | Nadie a quien decírselo | Una línea de log `reply to <id> failed`; el hilo vive | `worker.py:73-74` |
| El cliente se fue mientras HTTP escribía | Nadie a quien decírselo | Una línea de log `client closed the connection` | `http_transport.py:104-106` |
| Un cliente se queda parado a mitad de una petición HTTP | La conexión se cierra a los 15 s | El hilo termina | `:93` |
| `--http` sin token, o con uno de menos de 16 caracteres | Un mensaje en stderr y estado de salida 2 | El servidor no arranca | `:186-189` |
| `--http --port` sin número, o con texto | `usage: metal-gpu-trace --http [--port N]` y estado de salida 2 | | `metal_trace_mcp.py:91-93` |
| stdin se cierra con llamadas esperando (stdio) | | Se terminan todas primero y luego acaba el proceso | `stdio.py:53`, `worker.py:83-90` |

Todo lo de esta tabla es **confirmado** por las líneas que se nombran y **no reproducido** en vivo: no se envió ninguna
petición. Las pruebas que fijan cada fila se nombran en [Arranque](./arranque.md), [Worker](./worker.md) y
[HTTP](./http.md) (`tests/test_server.py` salvo que se diga otra cosa), y no se ejecutaron para esta guía. Los estados HTTP
(404, 403, 401, 413, 400) están en [HTTP](./http.md).
