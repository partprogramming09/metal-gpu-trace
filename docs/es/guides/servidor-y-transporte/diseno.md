# Diseño: por qué el servidor tiene esta forma

**Lector:** personas que cambian la estructura del servidor o se preguntan por qué se tomó una decisión. Revisado el 2026-11-16.

English: [Design](../../../guides/server-and-transport/design.md) · [Índice](./index.md)

**En corto:** el servidor hace un trabajo a la vez a propósito: dos grabaciones simultáneas estropearían las dos
mediciones. Las «puertas» (stdio y HTTP) solo reciben y encolan peticiones; un único worker hace el trabajo. Así las
puertas son simples y las reglas viven en un solo sitio. Las etiquetas (confirmada, probable, especulación) se explican en
el [índice](./index.md#como-leer-las-etiquetas).

## Las decisiones

| Decisión | Por qué | Alternativas que se descartaron |
|---|---|---|
| Un hilo worker, una llamada a la vez | Solo puede correr una grabación a la vez, porque dos programas que comparten la GPU estropean las dos mediciones (`stdio.py:40-41`, el comentario donde se encola). Una cola de 64 atendida por un hilo sustituyó a un hilo por llamada en una versión anterior (`CHANGELOG.md`, la entrada que dice "one queue of 64") | Un hilo por llamada: deja arrancar varias grabaciones y luego rechaza todas menos una; la cola rechaza de inmediato |
| El transporte sigue leyendo mientras corre una llamada | Una grabación dura 30 s o más. El mismo bucle debe responder `ping` y `tools/list` y oír `notifications/cancelled` entre tanto (`stdio.py:40-44`) | Ejecutar la herramienta en el bucle que lee: una cancelación no se oiría hasta que la llamada terminara |
| Los transportes no ejecutan herramientas; las encolan | Un solo lugar (el worker) guarda las banderas de cancelación, la cola y la regla de una a la vez, así que stdio y HTTP no pueden divergir ([How it works](../../../guides/how-it-works.md#two-rules-that-keep-it-testable), "the worker is the only place tool calls run") | Que cada transporte ejecute sus propias llamadas |
| `protocol` y `worker` reciben lo que necesitan por `configure()` | `protocol` necesita el texto y la versión del punto de entrada, y `worker` necesita el `send` del transporte y el `answer` del protocolo; ambos están por debajo de lo que necesitan, así que `metal_trace_mcp.py` se lo pasa (`metal_trace_mcp.py:49-50`). Los dos lanzan un error claro si se usan antes (`worker.py:11-12`, `protocol.py:35-37`). Véase [How it works](../../../guides/how-it-works.md#two-rules-that-keep-it-testable) | Importar hacia arriba: la prueba de arquitectura lo prohíbe |
| La lista de herramientas es un solo diccionario, `registry.TOOLS` | La lista que ve el cliente (`tools/list`), la comprobación de argumentos y la función que corre leen la misma fila, así que no pueden discrepar (`protocol.py:146-150`, `worker.py:156-158`) | Un decorador en cada función: **especulación** de que se dejó una tabla simple porque los esquemas son largos y la tabla se prueba entera con facilidad; ningún ADR recoge la decisión |
| HTTP solo en 127.0.0.1, con token, Host local y sin Origin ajeno | Una página abierta en un navegador del mismo Mac puede enviar peticiones a `127.0.0.1`, y se puede lograr que un nombre hostil apunte allí (DNS rebinding); el docstring dice que las comprobaciones de Host y Origin lo impiden (`http_transport.py:86-88`) | Escuchar en otras direcciones o con TLS: no se ofrece; el README dice que se llegue a otro Mac por un túnel SSH (`README.md`, sección "HTTP") |
| Un POST, una respuesta JSON, sin flujo de eventos | El progreso sale como notificaciones, "which this endpoint does not stream" (`http_transport.py:145-146`); el README dice que no hay flujo de progreso por HTTP | Server-sent events: no implementado |
| El token viene de una variable de entorno | `serve_http` lee `METAL_TRACE_TOKEN` (`http_transport.py:186`). **Especulación:** un argumento de línea de comandos se vería en la lista de procesos; ningún ADR recoge la decisión | Un parámetro como `--token`: no se ofrece |
| Los logs van a stderr, una línea corta | Por stdio, stdout es el protocolo: cualquier otra cosa impresa ahí rompe al cliente (`logs.py:7`, "the only log channel a stdio server may use") | Un archivo de log: nada en el código escribe uno |

## Las piezas y dónde viven

| Pieza | Archivo | Qué hace |
|---|---|---|
| Punto de entrada | `metal_trace_mcp.py` (`INSTRUCTIONS` `:23-47`, `main` `:79-95`, `check_cli` `:53-76`) | Guarda el texto que leen los clientes, configura `protocol` y `worker`, aplica el archivo de proyecto y elige el transporte según la línea de comandos |
| `python -m` | `__main__.py` (4 líneas) | Llama a `main()`, de modo que `python -m metal_gpu_trace` y el comando `metal-gpu-trace` (`pyproject.toml:30-31`) arrancan el mismo servidor |
| Transporte stdio | `stdio.py` (`serve_stdio` `:25`, `send` `:12`) | Lee un mensaje JSON por línea en stdin, escribe uno por línea en stdout |
| Transporte HTTP | `http_transport.py` (`http_handler` `:85`, `check_headers` `:46`, `serve_http` `:182`) | `POST /mcp` en 127.0.0.1 con un token |
| El protocolo | `protocol.py` (`handle` `:86`, `answer` `:191`, `era` `:40`) | Una petición JSON-RPC entra, una respuesta sale; véase [Eras](./eras.md) |
| El worker | `worker.py` (`submit` `:41`, `work` `:60`, `call` `:143`, `cancel_call` `:93`, `cancel_item` `:118`) | La cola, el hilo, las banderas de cancelación y las comprobaciones antes de que corra una herramienta |
| El registro | `registry.py` (`TOOLS` `:69`, `RESOURCES` `:12`, `PROMPTS` `:193`) | Lo que los clientes pueden pedir: herramientas con sus esquemas, recursos y prompts |
| Logs | `logs.py` (9 líneas) | La única función que escribe en stderr |
| Ajustes | `config.py` (`MAX_QUEUE` `:52`, `MIN_TOKEN` `:55`, `MAX_BODY` `:56`, `HTTP_TIMEOUT` `:57`, `MAX_TEXT` `:45`) | Los límites que usan las páginas; los números están en [E3](./evidencia.md#e3-los-limites-que-aplica-el-servidor) |

La capa de cada módulo (7 el punto de entrada, 6 los transportes, 5 el protocolo, 4 el worker, 3 el registro, 0 los logs)
está en [How it works](../../../guides/how-it-works.md#layers) y en `LAYERS` de `tests/test_architecture.py:15-23`.
