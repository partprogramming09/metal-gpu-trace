# Diseño: por qué el servidor tiene esta forma

**Lector:** personas que cambian la estructura del servidor o se preguntan por qué se tomó una decisión. Revisado el 2026-11-16.

English: [Design](../../../guides/server-and-transport/design.md) · [Índice](./index.md)

**En corto:** el servidor hace un trabajo a la vez a propósito: dos grabaciones simultáneas estropearían las dos
mediciones. Las «puertas» (stdio y HTTP) solo reciben y encolan; un único worker hace el trabajo, así que las reglas viven
en un solo sitio. Las etiquetas (confirmada, probable, especulación) están en el [índice](./index.md#como-leer-las-etiquetas).

## Las decisiones

| Decisión | Por qué | Descartado |
|---|---|---|
| Un hilo worker, una llamada a la vez; los transportes encolan, nunca ejecutan | Dos programas que comparten la GPU estropean las dos mediciones (`stdio.py:44-45`). Solo el worker guarda las banderas de cancelación, la cola y la regla de una a la vez, así que stdio y HTTP no divergen ([How it works](../../../guides/how-it-works.md#two-rules-that-keep-it-testable)). Una cola de 64 con un hilo sustituyó a un hilo por llamada (`CHANGELOG.md`, "one queue of 64") | Un hilo por llamada (arranca varias grabaciones y rechaza todas menos una; la cola rechaza de inmediato). Que cada transporte ejecute sus llamadas |
| El transporte sigue leyendo mientras corre una llamada | Una grabación dura 30 s o más; el mismo bucle debe responder `ping` y `tools/list` y oír `notifications/cancelled` (`stdio.py:42-48`) | Ejecutar la herramienta en el bucle que lee: una cancelación no se oiría hasta que acabara la llamada |
| `configure()` da a `protocol` y `worker` lo que necesitan | `protocol` necesita el texto y la versión del punto de entrada, `worker` el `send` del transporte y el `answer` del protocolo; ambos están por debajo, así que `metal_trace_mcp.py` se lo pasa (`:49-50`). Los dos lanzan un error claro si se usan antes (`worker.py:11-12`, `protocol.py:35-37`) | Importar hacia arriba: la prueba de arquitectura lo prohíbe |
| La lista de herramientas es un diccionario, `registry.TOOLS` | `tools/list`, la comprobación de argumentos y la función leen la misma fila, así que no pueden discrepar (`protocol.py:146-150`, `worker.py:156-158`) | Un decorador por función: **especulación** de que una tabla simple se prueba entera con más facilidad; ningún ADR lo recoge |
| HTTP solo en 127.0.0.1, con token, Host local y sin Origin ajeno; un POST, una respuesta JSON, sin flujo de eventos | Una página en un navegador del mismo Mac puede enviar peticiones a `127.0.0.1`, y un nombre hostil puede apuntar allí (DNS rebinding); las comprobaciones de Host y Origin lo impiden (`http_transport.py:86-88`). Las notificaciones de progreso no se transmiten (`:145-146`). `serve_http` lee el token de `METAL_TRACE_TOKEN` (`:186`); **especulación:** un argumento de línea de comandos se vería en la lista de procesos; ningún ADR lo recoge | Otras direcciones o TLS (el README dice usar un túnel SSH, sección "HTTP"); server-sent events; un parámetro `--token` |
| Los logs van a stderr, una línea corta | Por stdio, stdout es el protocolo: cualquier otra cosa impresa ahí rompe al cliente (`logs.py:7`) | Un archivo de log: nada lo escribe |

## Las piezas y dónde viven

| Pieza | Archivo | Qué hace |
|---|---|---|
| Punto de entrada | `metal_trace_mcp.py` (`INSTRUCTIONS` `:23-47`, `main` `:79-95`, `check_cli` `:53-76`); `__main__.py` (4 líneas) llama a `main()`, de modo que `python -m metal_gpu_trace` y el comando `metal-gpu-trace` (`pyproject.toml:30-31`) arrancan el mismo servidor | Guarda el texto que leen los clientes, configura `protocol` y `worker`, aplica el archivo de proyecto, elige el transporte |
| stdio | `stdio.py` (`serve_stdio` `:25`, `send` `:12`) | Un mensaje JSON por línea en stdin y stdout |
| HTTP | `http_transport.py` (`http_handler` `:85`, `check_headers` `:46`, `serve_http` `:182`) | `POST /mcp` en 127.0.0.1 con token |
| Protocolo | `protocol.py` (`handle` `:86`, `answer` `:191`, `era` `:40`) | Entra una petición JSON-RPC, sale una respuesta ([Eras](./eras.md)) |
| Worker | `worker.py` (`submit` `:41`, `work` `:60`, `call` `:143`, `cancel_call` `:93`, `cancel_item` `:118`) | Cola, hilo, banderas de cancelación, comprobaciones antes de que corra una herramienta |
| Registro | `registry.py` (`TOOLS` `:69`, `RESOURCES` `:12`, `PROMPTS` `:193`) | Herramientas con esquemas, recursos, prompts |
| Logs, ajustes | `logs.py` (9 líneas); `config.py` (`MAX_QUEUE` `:52`, `MIN_TOKEN` `:55`, `MAX_BODY` `:56`, `HTTP_TIMEOUT` `:57`, `MAX_TEXT` `:45`) | La única función que escribe en stderr; los límites, con sus números en [E3](./evidencia.md#e3-los-limites-que-aplica-el-servidor) |

Capas: 7 punto de entrada, 6 transportes, 5 protocolo, 4 worker, 3 registro, 0 logs ([How it works](../../../guides/how-it-works.md#layers); `LAYERS`, `tests/test_architecture.py:15-23`).
