# Logs

**Lector:** personas que añaden o leen las líneas de log del servidor. Revisado el 2026-11-16.

English: [Logs](../../../guides/server-and-transport/logs.md) · [Índice](./index.md)

**En corto:** el servidor escribe una línea corta en el canal de errores (stderr) cuando termina una herramienta o algo se
rompe. Nunca escribe lo que pediste, una ruta de archivo ni el token secreto: solo nombres, resultados y duraciones. El
canal normal (stdout) queda reservado para la conversación con el cliente.

`logs.py` es una función (`:6-9`): imprime `metal-trace: <mensaje>` en stderr y vacía el búfer, salvo que `METAL_TRACE_LOG`
sea exactamente `off`. Nada más del paquete escribe por su cuenta en stderr ni en stdout: `send` (`stdio.py:12`) es el único
que escribe en stdout, y `serve_http` imprime una línea más de forma directa (`http_transport.py:188`, el mensaje del token,
que `METAL_TRACE_LOG=off` **no** silencia).

El docstring del propio módulo dice "the one stderr line per tool call", y el README también. En el código hay siete
llamadores ([E6](./evidencia.md#e6-cada-sitio-que-escribe-una-linea-de-log)), que son todo el log:

| Mensaje | Cuándo | Línea |
|---|---|---|
| `metal-trace: <herramienta> ok in <s> s` o `... error in <s> s` | Terminó una llamada a una herramienta (`error` significa un resultado `isError`) | `worker.py:171` |
| `metal-trace: serving http://127.0.0.1:<puerto>/mcp` | Arrancó HTTP | `http_transport.py:191` |
| `metal-trace: internal error <NombreDeExcepción>` | Una excepción en `protocol.handle`, en stdio (el lector), en HTTP (el manejador) o en `protocol.answer` (el worker) | `stdio.py:49`, `http_transport.py:166`, `protocol.py:196` |
| `metal-trace: reply to <id> failed: <NombreDeExcepción>` | El worker no pudo escribir una respuesta | `worker.py:74` |
| `metal-trace: client closed the connection` | HTTP: el cliente se fue durante la escritura | `http_transport.py:106` |

Ninguna línea lleva un argumento, una etiqueta, una ruta, un token ni un resultado: solo el nombre de la herramienta, su
estado, una duración, el tipo de una excepción (nunca su texto) y, en una línea, un id de petición que eligió el cliente.
Esto es **confirmado** para los siete sitios de hoy; nada lo obliga, así que un nuevo `logs.log(f"... {valor}")` lo
rompería sin avisar ([Tocarlo sin romperlo](./tocarlo.md)). A dónde va a parar stderr (un archivo, un panel, a ningún
sitio) depende del cliente que lanzó el servidor: **no verificado** aquí.
