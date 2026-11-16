# Cuando falla

**Lector:** personas que necesitan saber por qué un cliente recibió un error, un estado o un silencio. Revisado el 2026-11-16.

English: [When it fails](../../../guides/server-and-transport/failures.md) · [Índice](./index.md)

**En corto:** una petición mala no detiene el servidor. Una petición mal formada recibe un error de protocolo, una herramienta que falló un «resultado de error», y a veces la respuesta es silencio porque el cliente se fue o canceló.

| Qué sale mal | Qué recibe el cliente | Qué hace el servidor | Línea |
|---|---|---|---|
| Una línea que no es JSON ni UTF-8 (stdio) | `-32700 parse error`, `id: null` | Sigue con la línea siguiente | `stdio.py:33`, `:50-51` |
| JSON que no es un objeto (`[1]`); sin `jsonrpc: "2.0"` o sin `method` de texto | `-32600 Invalid Request` | | `protocol.py:88-89`, `:94-95` |
| Un método desconocido | `-32601 unknown method <m>` | | `:173` |
| Una herramienta desconocida | `-32602 unknown tool <nombre>`: un error JSON-RPC, no un resultado `isError` | | `:167-169` |
| Argumentos erróneos a una herramienta conocida | Un resultado `isError` `bad arguments: ...` | | `worker.py:156-157` |
| Una herramienta lanza algo esperado / otra cosa | Un resultado `isError` con su texto / `internal error: <NombreDeExcepción>` | Una línea de log, `error` | `:165-168`, `:171` |
| Hay 64 llamadas esperando | Un resultado `isError` de inmediato | No se encola nada | `:53-57` |
| Cancelada en la cola | stdio: nada. HTTP: un resultado `isError` `the call was cancelled before it started` | Sale de la cola | `:101-111` |
| Cancelada mientras corre | stdio: nada. HTTP era antigua: un resultado `isError`; moderna: nada, conexión cerrada | La herramienta se detiene en su siguiente mirada; una grabación limpia | `:112-115`; `http_transport.py:155-161` |
| El `metal-gpu-trace.json` está mal | Toda herramienta, y toda lectura de `metal-trace://runs/...`, responde con su mensaje | Sigue funcionando; los recursos responden `-32603` | `worker.py:155`, `protocol.py:131-133` |
| Una excepción dentro de `protocol.handle` | `-32603 internal error` | Una línea de log; stdio y HTTP siguen | `stdio.py:52-54`, `http_transport.py:163-168`, `protocol.py:191-198` |
| El cliente se fue mientras el worker escribía (stdio) | Nadie a quien decírselo | Log `reply to <id> failed`; el hilo vive | `worker.py:73-74` |
| El cliente se fue mientras HTTP escribía | Nadie a quien decírselo | Log `client closed the connection` | `http_transport.py:104-106` |
| Un cliente se para a mitad de una petición (HTTP) | Conexión cerrada a los 15 s | El hilo termina | `:93` |
| `--http` sin token, o de menos de 16 caracteres | Un mensaje en stderr, estado de salida 2 | No arranca | `:186-189` |
| `--http --port` sin número, o con texto | `usage: metal-gpu-trace --http [--port N]`, estado de salida 2 | | `metal_trace_mcp.py:91-93` |
| stdin se cierra con llamadas esperando (stdio) | | Terminan todas primero y luego acaba el proceso | `stdio.py:57`, `worker.py:83-90` |

Todo **confirmado** por las líneas nombradas, **no reproducido** en vivo (no se envió ninguna petición). Las pruebas de cada fila están en [Arranque](./arranque.md), [Worker](./worker.md) y [HTTP](./http.md) (`tests/test_server.py` salvo que se diga otra cosa) y no se ejecutaron. Los estados HTTP (404, 403, 401, 413, 400) están en [HTTP](./http.md).
