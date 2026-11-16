# Cómo arranca el servidor

**Lector:** personas que cambian la línea de comandos, el arranque de los transportes o lo que se configura al importar. Revisado el 2026-11-16.

English: [Startup](../../../guides/server-and-transport/startup.md) · [Índice](./index.md)

**En corto:** un solo comando arranca el servidor. Sin palabra extra escucha por stdin/stdout (como lo lanza normalmente un agente); con `--http` escucha en una dirección web local y se niega a arrancar sin un token secreto. Antes de servir, dos piezas internas se conectan una sola vez, al importar.

## La línea de comandos

`main()` (`metal_trace_mcp.py:79-95`) la lee en este orden y se detiene en la primera que coincide:

| Línea de comandos | Qué pasa | Línea |
|---|---|---|
| `--version` | Imprime `metal-gpu-trace <versión>`; no lee el archivo de proyecto | `:82-84` |
| cualquier otra | Aplica el archivo de proyecto una vez ([How it works](../../../guides/how-it-works.md#where-recordings-live-and-what-reads-them)) | `:85` |
| `check RUN BASELINE [--margin-pct N]` | Juzga una corrida para CI, sale con 0, 1 o 2; no hay servidor | `:86-87`, `:53-76` |
| `--http [--port N]` | Sirve HTTP; puerto 8765 sin `--port`; línea de uso y salida 2 si falta el número o no es un entero | `:88-94` |
| nada más | Sirve stdio hasta que stdin se cierra | `:95` |

No existe un parámetro `--stdio`: stdio es lo que queda (véase el [límite 4](./limites.md)).

## stdio

`serve_stdio` (`stdio.py:25-53`) es todo el transporte:

- Cambia stdin y stdout a UTF-8 (`:27-29`), para que la codificación no dependa de los ajustes de idioma de quien lo lanzó.
- Lee `sys.stdin` línea a línea hasta que el cliente lo cierra (`:30`); las líneas vacías se saltan (`:31-32`).
- Cada línea es JSON, clasificada en tres clases: `notifications/cancelled` va a `worker.cancel_call` con el id de petición (`:35-37`); un `tools/call` con id de texto o número se registra (`worker.CALLS[id] = Event()`) y se encola (`:38-44`); todo lo demás lo responde `protocol.handle` en el acto (`:45`), en el hilo que lee.
- Una línea que no es JSON recibe `-32700 parse error`, `id: null` (`:46-47`). Cualquier otra excepción de `protocol.handle` se registra como `internal error <NombreDeExcepción>` y se responde `-32603 internal error` (`:48-50`): un mensaje malo no detiene el servidor.
- Cuando stdin se cierra corre `worker.stop_worker()` (`:53`): las llamadas encoladas terminan y luego el hilo acaba ([límite 3](./limites.md)).
- `send` escribe una línea JSON bajo un candado, así que el lector que responde un `ping` y el worker que envía progreso nunca mezclan bytes (`:9`, `:12-16`).

## HTTP

`serve_http(port)` (`http_transport.py:182-196`), en este orden:

| # | Paso | Línea |
|---|---|---|
| 1 | Lee `METAL_TRACE_TOKEN`. Ausente o más corto que `config.MIN_TOKEN` (16): imprime `metal-gpu-trace: set METAL_TRACE_TOKEN to a secret of at least 16 characters` en stderr y devuelve 2 (estado de salida 2). Nunca arranca sin token | `:186-189` |
| 2 | Construye un `ThreadingHTTPServer` en `("127.0.0.1", port)`: un hilo por conexión, solo loopback e IPv4. El puerto 0 deja elegir al sistema | `:190` |
| 3 | Registra `metal-trace: serving http://127.0.0.1:<puerto>/mcp` con el puerto real | `:191` |
| 4 | Sirve hasta `KeyboardInterrupt`, devuelve 0 | `:192-195` |

Cada conexión la atiende la clase `Handler` que construye `http_handler(token)` (`:85-179`). Dos hechos de la biblioteca estándar: `ThreadingHTTPServer` arranca hilos daemon (`daemon_threads = True`, [E7](./evidencia.md#e7-que-hace-la-biblioteca-estandar-bajo-threadinghttpserver)) y el manejador base habla HTTP/1.0 (`protocol_version = "HTTP/1.0"`, E7), sin cambios aquí. Así cada petición es su propia conexión, cerrada tras la respuesta, y un hilo de manejador nunca sobrevive a su petición. Ambos hechos salen de la biblioteca estándar de Python 3.9 leída para esta guía; para otras versiones son **probables**. Lo que pasa una petición está en [HTTP](./http.md).

## Qué se configura y cuándo

Importar `metal_trace_mcp` tiene dos efectos que todo transporte y prueba necesitan: `protocol.configure(instructions, version)` y `worker.configure(send=stdio.send, answer=protocol.answer, finish=protocol.finish)` (`:49-50`). Por eso las pruebas que construyen un manejador o llaman a `protocol.handle` empiezan con `import metal_trace_mcp  # noqa: F401  (configures protocol and worker)` (por ejemplo `tests/test_server.py:525-529`). Las pruebas de arquitectura comprueban que usar `worker` o `protocol` antes falla con un mensaje que nombra el arreglo (`tests/test_architecture.py:147`, `:201`).

`INSTRUCTIONS` (`:23-47`) es el texto que lee un cliente al conectarse, enviado en la respuesta a `initialize` (`protocol.py:112`) y `server/discover` (`:115`). Las reglas de uso (una grabación a la vez, 30 s o más bajo Wine, comparar grabaciones de 100 fotogramas o más) viajan con el servidor, no con un README; una prueba comprueba que cada punto va seguido de un espacio (`tests/test_server.py:1090`).
