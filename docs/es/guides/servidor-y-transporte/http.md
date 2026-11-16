# HTTP en detalle

**Lector:** personas que cambian lo que el endpoint HTTP acepta, rechaza o responde. Revisado el 2026-11-16.

English: [HTTP](../../../guides/server-and-transport/http.md) · [Índice](./index.md)

**En corto:** por HTTP el servidor funciona como un edificio con portero. Comprueba, en un orden fijo, que viniste a la puerta correcta, desde la calle correcta, con la llave correcta y un paquete razonable, y solo entonces lee lo que traes. Las negativas dicen lo mínimo. El arranque está en [Arranque](./arranque.md).

Un cliente que no puede arrancar un servidor stdio envía `POST http://127.0.0.1:8765/mcp` con `Authorization: Bearer <token>` y un mensaje JSON como cuerpo. El token es el de `METAL_TRACE_TOKEN`; los ejemplos escriben `<token>`, nunca uno real.

## Las comprobaciones, en orden

![Siete cajas en fila, de izquierda a derecha: ruta, host y origen, token, tamaño, JSON, cabeceras y ejecución. Bajo cada una de las seis primeras, el estado con que responde: 404, 403, 401, 413, 400 con un error de análisis, y 400 o 404 con un error JSON-RPC. Si todas pasan, la petición se ejecuta.](./img/server-http-checks.png)
*Figura 2. Lo que `do_POST` comprueba antes de que corra nada. Fuente: `img/server-http-checks.html`.*

El orden importa: a un cliente sin token nunca se le lee el cuerpo. Los estados 404, 403, 401 y 413 llevan el cuerpo **vacío** a propósito (`reply(code)` sin cuerpo, `http_transport.py:99-101`, líneas `:119-129`): una negativa no dice al cliente nada que no supiera. [E1](./evidencia.md#e1-cada-estado-con-que-responde-el-manejador-http-con-su-linea) lista cada `self.reply` con su línea.

| # | Comprobación | Estado | La respuesta | Lo fija |
|---|---|---|---|---|
| 0 | El método es POST (`do_GET`, `do_DELETE`) | 405 | Vacía; antes de cualquier otra comprobación. `PUT`, `HEAD` y el resto los responde la biblioteca estándar (**probable**: 501; no ejecutado) | `tests/test_server.py:321`, `:893` |
| 1 | `self.path == "/mcp"` | 404 | Vacía | `:322` |
| 2 | Host es `localhost` o `127.0.0.1`, y un Origin, si se envía, también | 403 | Vacía | `:317-320` |
| 3 | `Authorization` lleva el token | 401 | Vacía | `:315-316` |
| 4 | `Content-Length` son dígitos, 12 como mucho, entre 0 y `MAX_BODY` (1 000 000) | 413 | Vacía | `tests/test_adversarial.py:225` |
| 5 | El cuerpo es JSON en UTF-8 no anidado más de lo que acepta el analizador | 400 | `-32700 parse error`, `id: null` | `:1031` |
| 6 | `check_headers` | 400 o 404 | Un error JSON-RPC (códigos abajo) | `:838`, `:847` |

| Comprobación | Detalle |
|---|---|
| **Host y Origin** (`foreign`, `:108-111`; `local_host`, `:17-20`) | Quita un `esquema://` inicial y todo tras un `/`, toma lo que va antes del primer `:` y solo acepta `localhost` o `127.0.0.1`; el puerto no importa. Un `Origin` solo se comprueba cuando se envía; un `Host` ausente no es local. Pruebas: `http://evil.example`, `http://localhost.evil.example` y `Host: evil.example` dan 403, `http://localhost:<puerto>` da 200 (`tests/test_server.py:317-320`). Por qué las dos: una página en `evil.example` cuyo nombre resuelve a `127.0.0.1` envía `Host: evil.example` (la comprobación de Host la detiene); un navegador envía un `Origin` en un POST entre sitios, lo que detiene a una página que no necesita rebinding |
| **El token** (`unauthorized`, `:113-116`) | Se quita `Bearer ` si está y el resto se compara con `hmac.compare_digest` (mismo tiempo sea cual sea el primer byte erróneo). Se lee una vez al arrancar (`:186`), nunca se registra, imprime ni responde; el único mensaje es la negativa a arrancar ([E5](./evidencia.md#e5-como-se-lee-la-linea-de-comandos), `:188`). Ausente, vacío y erróneo son todos 401 (`tests/test_server.py:315-316`) |
| **Tamaño** (`:125-129`) | Un `Content-Length` que no son dígitos ASCII (`²` pasa `str.isdigit()` y falla en `int()`), con más de 12 caracteres o que pasa de 1 000 000 es 413 sin leer el cuerpo; una prueba usa `0xB2` y 5 000 nueves (`tests/test_adversarial.py:225-232`). Sin `Content-Length` cuenta como 0: un cuerpo sin él, o con `Transfer-Encoding: chunked`, se lee como vacío y se responde 400 `-32700` ([límite 8](./limites.md)) |

## `check_headers`: cuando las cabeceras no coinciden con el cuerpo

`check_headers(headers, message, era)` (`:46-82`) devuelve `(estado, cuerpo)` para un POST que la especificación rechaza, o `None`. La era sale de `protocol.era(message)` (`:134`).

| Era | Condición | Estado y código | Línea |
|---|---|---|---|
| Antigua | Una notificación y la cabecera de versión es la moderna | Se deja pasar | `:60-61` |
| Antigua | Se envía `MCP-Protocol-Version` y no es una versión antigua | 400, `-32600` `unsupported MCP-Protocol-Version <v>` | `:62-63` |
| Moderna | Una notificación | Se deja pasar, con o sin `_meta` (la especificación no define reglas de cabeceras para ella) | `:65-66` |
| Moderna | Falta `MCP-Protocol-Version` o `Mcp-Method` | 400, `-32020` `Header mismatch: ... are required` | `:70-71` |
| Moderna | `Mcp-Method` no es el `method` del cuerpo | 400, `-32020` | `:72-73` |
| Moderna | La cabecera de versión no es la versión de `_meta` | 400, `-32020` | `:74-75` |
| Moderna | La versión no es `2026-07-28` | 400, `-32022 Unsupported protocol version`, `data` lista admitidas y pedida | `:76-77`, `protocol.py:52-55` |
| Moderna | El método no es uno moderno (`ping` no lo es) | 404, `-32601 unknown method` | `:78-79`, `protocol.py:28-29` |
| Moderna | `tools/call`, `prompts/get` o `resources/read` y `Mcp-Name` no es `params.name` (o `params.uri`) | 400, `-32020` | `:80-81` |

El `id` de la respuesta es el de la petición si es texto o número, si no `null` (`:56`). `Mcp-Name` puede ser `=?base64?<utf-8 en base64>?=` para nombres no ASCII (`header_text`, `:31-43`); un Base64 malo, relleno de más y bytes que no son UTF-8 dan "sin valor", una discrepancia. Lo fijan `test_http_modern_headers` (`tests/test_server.py:847`) y `test_http_legacy_headers` (`:838`).

Una petición que pasa `check_headers` aún puede fallar, pero no como error HTTP: un error JSON-RPC como `unknown tool x` o un resultado `isError` es un `200` con el error en el cuerpo (`:162`, `:168`). Solo las comprobaciones de arriba son 4xx.

## Después de las comprobaciones

1. **`notifications/cancelled`** (`:137-142`): `202`, cuerpo vacío. Era antigua: cancela la llamada por id (`worker.cancel_call`). Era moderna: se acepta y se **ignora**, porque un cliente moderno cancela cerrando la conexión y otro cliente puede compartir el id (`tests/test_server.py:1165`).
2. **`tools/call` con id** (`:143-162`):
   - Quita lo que el endpoint no puede transmitir: la era moderna quita `progressToken` de `_meta` y deja la versión; la antigua quita `_meta` (`:147-151`).
   - Crea su bandera de cancelación, la registra bajo el id y encola el mensaje con una función que guarda la respuesta y despierta al hilo del manejador (`:152-154`).
   - Espera. **Moderna:** cada `POLL_S` (0,5 s) `client_gone` asoma al socket buscando un fin de archivo (`:23-28`); si cerró, llama a `cancel_item` y no escribe nada (`:155-159`; `test_http_close_cancels`, `tests/test_server.py:817`: "en un segundo o dos, y nada de vuelta"). **Antigua:** espera el resultado, incluso uno cancelado, pues esa era no tiene tal señal (`:160-161`; `test_http_legacy_cancel_keeps_reply`, `:799`).
   - Escribe `200` con la respuesta guardada (`:162`).
3. **Todo lo demás** (`:163-168`): `protocol.handle` corre en el hilo del manejador, no en el del worker. Una excepción se registra como `internal error <NombreDeExcepción>` y se responde `200` con `-32603 internal error`. Una respuesta `None` (una notificación) es `202`, si no `200`.

## La función de respuesta y un cliente que se fue

`reply` (`:95-106`) escribe el estado, un `Content-Type` solo con cuerpo, un `Content-Length` siempre, y el cuerpo. Un `ConnectionError` al escribir pone `close_connection` y registra `client closed the connection` en lugar de lanzar (`:104-106`; `test_http_reply_broken_pipe`, `tests/test_server.py:1067`). `timeout = config.HTTP_TIMEOUT` (15 s, `:93`) descarta a un cliente que se para antes de terminar su petición, así que no retiene un hilo para siempre (`test_http_timeout`, `:473`). `log_message` está vacío (`:176-177`): el registro de accesos por petición de la biblioteca estándar está apagado.
