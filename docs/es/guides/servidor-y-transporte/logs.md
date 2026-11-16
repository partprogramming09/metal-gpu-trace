# Logs

**Lector:** personas que añaden o leen las líneas de log del servidor. Revisado el 2026-11-16.

English: [Logs](../../../guides/server-and-transport/logs.md) · [Índice](./index.md)

**En corto:** el servidor escribe una línea corta en stderr cuando termina una herramienta o algo se rompe. Nunca lo que pediste, una ruta ni el token: solo nombres, resultados y duraciones. stdout queda reservado para la conversación con el cliente.

`logs.py` (`:6-9`) imprime `metal-trace: <mensaje>` en stderr y vacía el búfer, salvo que `METAL_TRACE_LOG` sea exactamente `off`. `send` (`stdio.py:12`) es el único que escribe en stdout; `serve_http` imprime una línea más directamente (`http_transport.py:188`, el mensaje del token), que `METAL_TRACE_LOG=off` **no** silencia.

El docstring y el README dicen "the one stderr line per tool call"; el código tiene siete llamadores ([E6](./evidencia.md#e6-cada-sitio-que-escribe-una-linea-de-log)):

| Mensaje | Cuándo | Línea |
|---|---|---|
| `metal-trace: <herramienta> ok in <s> s` o `... error in <s> s` | Terminó una llamada (`error` = un resultado `isError`) | `worker.py:171` |
| `metal-trace: serving http://127.0.0.1:<puerto>/mcp` | Arrancó HTTP | `http_transport.py:191` |
| `metal-trace: internal error <NombreDeExcepción>` | Excepción en `protocol.handle` (lector stdio, manejador HTTP) o `protocol.answer` (worker) | `stdio.py:49`, `http_transport.py:166`, `protocol.py:196` |
| `metal-trace: reply to <id> failed: <NombreDeExcepción>` | El worker no pudo escribir una respuesta | `worker.py:74` |
| `metal-trace: client closed the connection` | HTTP: el cliente se fue durante la escritura | `http_transport.py:106` |

Ninguna línea lleva un argumento, etiqueta, ruta, token ni resultado: solo un nombre de herramienta, estado, duración, el tipo de una excepción (nunca su texto) y, una vez, un id de petición elegido por el cliente. **Confirmado** para los siete sitios; nada lo obliga, así que un nuevo `logs.log(f"... {valor}")` lo rompería sin avisar ([Tocarlo sin romperlo](./tocarlo.md)). A dónde va a parar stderr depende del cliente que lanzó el servidor: **no verificado**.
