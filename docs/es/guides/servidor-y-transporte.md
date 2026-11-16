# Servidor y transporte

**Lector:** personas que cambian cómo arranca, escucha y responde el servidor (`metal_trace_mcp.py`, `stdio.py`, `http_transport.py`, `worker.py`, `registry.py`, `logs.py`), que añaden o renombran una herramienta, o que necesitan saber por qué un cliente recibió un error, un estado o un silencio. Revisado el 2026-11-16.

English: [Server and transport](../../guides/server-and-transport.md)

Esta página sigue una llamada a una herramienta desde que el cliente la envía hasta que se escribe la respuesta, por stdio
y por HTTP, y dice qué hace cada pieza y qué pasa cuando falla. No repite [How it works](../../guides/how-it-works.md) (la
tabla de capas, las dos reglas que lo hacen comprobable, el recorrido de una petición en cinco líneas) ni
[ADR-0002](../../adr/0002-dual-era-mcp.md) (por qué el servidor habla dos eras de MCP); los enlaza y profundiza donde
terminan. Cómo se leen las grabaciones está en [Grabar](./grabar.md) y [Resumir y analizar](./resumir-y-analizar.md): esta
página se detiene donde empieza la función de una herramienta. Es la versión en español de la guía en inglés: mismo
contenido, mismos diagramas y la misma evidencia (los comandos y sus salidas no se traducen, ni los mensajes de error del
programa).

Cómo leer las etiquetas: cada afirmación técnica es **confirmada** (con `archivo:línea`, comprobada con `rg` o `sed` el
2026-11-16 contra el árbol de trabajo, que es la 0.27.2 más las entradas `[Unreleased]` de `CHANGELOG.md`), **probable**
(leída en el código pero no ejecutada aquí) o **especulación** (una conjetura sobre el porqué). **No verificado** marca un
dato de fuera que no se comparó con su fuente. Las líneas se mueven cuando cambia el código: busca el nombre, no solo el
número. Cada cifra viene con el comando que la produjo, en [Evidencia](#evidencia-los-comandos-y-su-salida-real). **No
reproducido** significa que el comportamiento no se pudo ejecutar para esta página: la sesión que la escribió solo podía
correr comandos de lectura, así que no se arrancó el servidor, no se envió ninguna petición y no se ejecutó ninguna
prueba; se nombran en su lugar las pruebas que fijan cada comportamiento, y **no se ejecutaron** para esta página.

## Un ejemplo primero

Supón que un agente pide al servidor, por stdio, grabar un programa durante 30 segundos, y a medias cambia de idea:

```text
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"perf_record","arguments":{"label":"mygame","program":"/path/to/mygame.exe","wine":"/path/to/wine","seconds":30}}}
```

Qué pasa, en el orden en que pasa:

1. El bucle de stdio lee la línea, ve un `tools/call` con id y no lo ejecuta (`stdio.py:30-44`). Crea una bandera de
   cancelación para el id 7, pone el mensaje en la cola del worker y vuelve a leer la línea siguiente de inmediato.
2. El hilo del worker, que arrancó con la primera llamada y vive lo que vive el servidor, saca el mensaje de la cola
   (`worker.py:60-72`) y pide al protocolo que lo responda. El protocolo comprueba que el nombre de la herramienta está en
   el registro (`protocol.py:167-169`) y devuelve la llamada a `worker.call` (`:170`).
3. `worker.call` comprueba el archivo de proyecto, después que los argumentos encajan con el esquema de la herramienta y
   luego ejecuta la función que el registro guarda para `perf_record` (`worker.py:155-158`). Aquí se van los 30 segundos.
4. Mientras tanto el agente envía `{"id":8,"method":"ping"}`. El bucle de stdio está libre y responde `ping` él mismo, en
   el mismo hilo que lee, sin tocar la cola (`stdio.py:45`, `:51-52`).
5. El agente envía `{"method":"notifications/cancelled","params":{"requestId":7}}`. El bucle activa la bandera de la
   llamada 7 (`stdio.py:35-37`, `worker.py:93-115`). La grabación mira esa bandera cada segundo y se mata
   ([Grabar, la secuencia de cierre forzado](./grabar.md#la-secuencia-de-cierre-forzado)); la función lanza `the recording
   was cancelled; nothing was saved` y el worker lo convierte en un resultado de error. Como el cliente canceló, stdio no
   escribe **nada** para el id 7 (`stdio.py:19-22`): la especificación dice que una llamada cancelada no recibe respuesta.
6. Si el agente no hubiera cancelado, la función habría devuelto un diccionario, el worker lo habría escrito como texto JSON
   (40 000 caracteres como máximo) y el bucle lo habría escrito como una línea en stdout. En ambos casos el worker escribe
   una línea en stderr cuando la llamada termina: `metal-trace: perf_record error in <segundos> s` o `... ok in <segundos> s`
   (`worker.py:171`).

La misma llamada por HTTP tiene el mismo medio (pasos 2, 3 y 6) y un principio y un final distintos: véase
[HTTP en detalle](#http-en-detalle).

## Por qué el servidor tiene esta forma

| Decisión | Por qué | Alternativas que se descartaron |
|---|---|---|
| Un hilo worker, una llamada a la vez | Solo puede correr una grabación a la vez, porque dos programas que comparten la GPU estropean las dos mediciones (`stdio.py:40-41`, el comentario donde se encola). Una cola de 64 atendida por un hilo sustituyó a un hilo por llamada en una versión anterior (`CHANGELOG.md`, la entrada que dice "one queue of 64") | Un hilo por llamada: deja arrancar varias grabaciones y luego rechaza todas menos una; la cola rechaza de inmediato |
| El transporte sigue leyendo mientras corre una llamada | Una grabación dura 30 s o más. El mismo bucle debe responder `ping` y `tools/list` y oír `notifications/cancelled` entre tanto (`stdio.py:40-44`) | Ejecutar la herramienta en el bucle que lee: una cancelación no se oiría hasta que la llamada terminara |
| Los transportes no ejecutan herramientas; las encolan | Un solo lugar (el worker) guarda las banderas de cancelación, la cola y la regla de una a la vez, así que stdio y HTTP no pueden divergir ([How it works](../../guides/how-it-works.md#two-rules-that-keep-it-testable), "the worker is the only place tool calls run") | Que cada transporte ejecute sus propias llamadas |
| `protocol` y `worker` reciben lo que necesitan por `configure()` | `protocol` necesita el texto y la versión del punto de entrada, y `worker` necesita el `send` del transporte y el `answer` del protocolo; ambos están por debajo de lo que necesitan, así que `metal_trace_mcp.py` se lo pasa (`metal_trace_mcp.py:49-50`). Los dos lanzan un error claro si se usan antes (`worker.py:11-12`, `protocol.py:35-37`). Véase [How it works](../../guides/how-it-works.md#two-rules-that-keep-it-testable) | Importar hacia arriba: la prueba de arquitectura lo prohíbe |
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
| El protocolo | `protocol.py` (`handle` `:86`, `answer` `:191`, `era` `:40`) | Una petición JSON-RPC entra, una respuesta sale; véase [Las dos eras](#las-dos-eras-como-referencia) |
| El worker | `worker.py` (`submit` `:41`, `work` `:60`, `call` `:143`, `cancel_call` `:93`, `cancel_item` `:118`) | La cola, el hilo, las banderas de cancelación y las comprobaciones antes de que corra una herramienta |
| El registro | `registry.py` (`TOOLS` `:69`, `RESOURCES` `:12`, `PROMPTS` `:193`) | Lo que los clientes pueden pedir: herramientas con sus esquemas, recursos y prompts |
| Logs | `logs.py` (9 líneas) | La única función que escribe en stderr |
| Ajustes | `config.py` (`MAX_QUEUE` `:52`, `MIN_TOKEN` `:55`, `MAX_BODY` `:56`, `HTTP_TIMEOUT` `:57`, `MAX_TEXT` `:45`) | Los límites de abajo; los números están en [E3](#e3-los-limites-que-aplica-el-servidor) |

La capa de cada módulo (7 el punto de entrada, 6 los transportes, 5 el protocolo, 4 el worker, 3 el registro, 0 los logs)
está en [How it works](../../guides/how-it-works.md#layers) y en `LAYERS` de `tests/test_architecture.py:15-23`.

## Cómo arranca el servidor

`main()` (`metal_trace_mcp.py:79-95`) lee la línea de comandos en este orden y se detiene en la primera que coincide:

| Línea de comandos | Qué pasa | Línea |
|---|---|---|
| `--version` | Imprime `metal-gpu-trace <versión>` y vuelve; no lee el archivo de proyecto | `:82-84` |
| cualquier otra | Aplica el archivo de proyecto una vez ([How it works](../../guides/how-it-works.md#where-recordings-live-and-what-reads-them): qué carpeta guarda las grabaciones) | `:85` |
| `check RUN BASELINE [--margin-pct N]` | Juzga una corrida para CI y sale con 0, 1 o 2; no hay servidor | `:86-87`, `:53-76` |
| `--http [--port N]` | Sirve HTTP; puerto 8765 cuando no sigue `--port`, una línea de uso y salida 2 cuando falta el número o no es un entero | `:88-94` |
| nada de lo anterior | Sirve stdio hasta que stdin se cierra | `:95` |

No existe un parámetro `--stdio`: stdio es lo que queda cuando nada más coincidió (véase el [límite 4](#limites-conocidos)).

### stdio

`serve_stdio` (`stdio.py:25-53`) es todo el transporte:

- Cambia stdin y stdout a UTF-8 (`:27-29`), de modo que la codificación no depende de los ajustes de idioma de quien lo
  lanzó.
- Lee `sys.stdin` línea a línea hasta que el cliente lo cierra (`:30`). Las líneas vacías se saltan (`:31-32`).
- Cada línea es JSON. Antes que nada se distinguen tres clases de mensaje:
  - `notifications/cancelled` va a `worker.cancel_call` con el id de petición que nombra (`:35-37`);
  - un `tools/call` con id de texto o número se registra (`worker.CALLS[id] = Event()`) y se encola (`:38-44`);
  - todo lo demás lo responde `protocol.handle` en el acto (`:45`), en el hilo que lee.
- Una línea que no es JSON se responde con `-32700 parse error` e `id: null` (`:46-47`). Cualquier otra excepción de
  `protocol.handle` se registra como `internal error <NombreDeExcepción>` y se responde `-32603 internal error`
  (`:48-50`), de modo que un mensaje malo no puede detener el servidor.
- Cuando stdin se cierra corre `worker.stop_worker()` (`:53`): las llamadas ya encoladas terminan y luego el hilo acaba
  ([límite 3](#limites-conocidos)).
- `send` escribe un mensaje como una línea de JSON bajo un candado, de modo que dos hilos (el lector que responde un `ping`
  y el worker que envía una notificación de progreso) nunca mezclan sus bytes (`:9`, `:12-16`).

### HTTP

`serve_http(port)` (`http_transport.py:182-196`) hace cuatro cosas, en este orden:

1. Lee `METAL_TRACE_TOKEN`. Más corto que `config.MIN_TOKEN` (16 caracteres) o ausente: imprime
   `metal-gpu-trace: set METAL_TRACE_TOKEN to a secret of at least 16 characters` en stderr y devuelve 2, de modo que el
   proceso sale con estado 2 (`:186-189`). El servidor nunca arranca sin token.
2. Construye un `ThreadingHTTPServer` ligado a `("127.0.0.1", port)` (`:190`): un hilo por conexión, solo loopback, solo
   IPv4. El puerto 0 deja que elija el sistema.
3. Registra `metal-trace: serving http://127.0.0.1:<puerto>/mcp` con el puerto que de verdad obtuvo (`:191`).
4. Sirve hasta `KeyboardInterrupt` (`:192-195`) y devuelve 0.

Cada conexión la atiende la clase `Handler` que construye `http_handler(token)` (`:85-179`). Importan dos hechos de la
biblioteca estándar: `ThreadingHTTPServer` arranca hilos daemon (`daemon_threads = True`, E7) y el manejador base habla
HTTP/1.0 por defecto (`protocol_version = "HTTP/1.0"`, E7), cosa que este manejador no cambia. Así que cada petición es su
propia conexión, cerrada tras la respuesta, y un hilo de manejador nunca sobrevive a su petición. Ambos hechos salen de la
biblioteca estándar de Python 3.9 leída para esta página; para otra versión de Python son **probables**.

### La otra mitad del arranque: qué se configura y cuándo

Importar `metal_trace_mcp` tiene dos efectos que todo transporte y toda prueba necesitan: llama a
`protocol.configure(instructions, version)` y a `worker.configure(send=stdio.send, answer=protocol.answer,
finish=protocol.finish)` (`:49-50`). Por eso las pruebas que construyen un manejador o llaman a `protocol.handle` de forma
directa empiezan con `import metal_trace_mcp  # noqa: F401  (configures protocol and worker)` (por ejemplo
`tests/test_server.py:525-529`). Las pruebas de arquitectura comprueban que usar `worker` o `protocol` antes de eso falla
con un mensaje que nombra el arreglo (`tests/test_architecture.py:147`, `:201`).

`INSTRUCTIONS` (`:23-47`) es el texto que lee un cliente al conectarse. Se envía en la respuesta a `initialize`
(`protocol.py:112`) y a `server/discover` (`:115`). Las reglas de uso del proyecto viven ahí (una grabación a la vez, 30 s o
más bajo Wine, comparar grabaciones de 100 fotogramas o más) para que viajen con el servidor y no con un README; una prueba
comprueba que cada punto va seguido de un espacio (`tests/test_server.py:1090`).

## El registro de herramientas

`registry.py` son datos: importa los módulos de dominio (`analysis`, `experiments`, `recording`, `traces`, `workloads`,
`project`) y pone sus funciones en tres tablas. No ejecuta nada.

**Herramientas** (`TOOLS`, `registry.py:69-188`): un nombre corresponde a una tupla de tres cosas,
`(función, esquema, pistas)`.

- `función` es la función de dominio, como `recording.tool_perf_record`. Recibe argumentos con nombre y devuelve un
  diccionario.
- `esquema` es un objeto JSON Schema construido por `schema(properties, required)` (`:24-26`). Es lo que el cliente ve como
  `inputSchema`, y contra lo que `worker.check_arguments` comprueba una llamada.
- `pistas` vienen de `hints(title, destructive, idempotent, open_world)` (`:29-34`) y se vuelven las anotaciones MCP de la
  herramienta. Por defecto es de solo lectura; pasar `destructive=True` o `False` dice que la herramienta escribe y si sus
  escrituras detienen programas. Hoy 16 de las 26 herramientas son de solo lectura y 10 escriben (E4); las cinco que graban
  (`perf_record`, `perf_baseline_record`, `perf_sweep`, `perf_ab`, `perf_cold_warm`) son las que llevan
  `destructiveHint: true`, porque detienen programas.

Lo que `tools/list` construye con una fila está en `protocol.py:146-150`: la descripción es el docstring de la función
(`inspect.cleandoc`, que quita la sangría), una herramienta sin propiedades recibe `additionalProperties: false`, tres
herramientas (`perf_runs`, `trace_query`, `capture_records`, `PAGED_TOOLS` `:9`) reciben el esquema de salida paginado
(`PAGED` `:6-8`), y `META` añade `anthropic/requiresUserInteraction` a las dos herramientas que descargan e instalan cosas
(`workload_fetch`, `presentmon_install`, `registry.py:190-191`), de modo que un cliente que lo respete pregunta a la persona
antes de cada llamada (E4).

**Recursos** (`RESOURCES`, `registry.py:12-15`): uno para todas las familias de GPU y uno por familia de
`data/apple-gpu-families.json`, JSON de solo lectura: cinco en el `resources/list` grabado (E9). Las grabaciones también son
un recurso, pero no de esta tabla: `metal-trace://runs/<run>` es una plantilla (`resources/templates/list`) que
`protocol.handle` sirve leyendo el resumen (`protocol.py:118-145`).

**Prompts** (`PROMPTS`, `registry.py:193-216`): `compare-layer`, `diagnose-stutter` y `bisect-regression`. Cada uno tiene
una función `render` que construye texto para el agente; el servidor no ejecuta nada, y `prompts/list` deja fuera `render`
(`protocol.py:152-153`). `prompts/get` descarta todo argumento cuyo valor esté vacío o no pase `paths.name_ok` antes de
llamar a `render` (`:159`).

### Qué fija el registro

- `test_tool_schemas_match_signatures` (`tests/test_server.py:1137`): cada argumento que toma una función está en su
  esquema, cada argumento sin valor por defecto es obligatorio, y un nombre del esquema que la función no toma solo se
  permite cuando la función reenvía `**kwargs`. Importa porque `tools/call` rechaza los nombres que el esquema no tiene.
- `test_readme_lists_every_tool` (`tests/test_server.py:18`): los dos README tienen una fila de tabla por cada herramienta.
- El número 26 aparece en cuatro sitios (`tests/test_server.py:14`, `:139`, `:325`, `:666`), y `tests/golden/protocol.json`
  guarda la respuesta completa de `tools/list`. Añadir una herramienta cambia todo eso a propósito.

## El worker

`worker.py` ejecuta las llamadas a herramientas. Su estado son cinco objetos a nivel de módulo (`:30-33`):

| Nombre | Qué guarda |
|---|---|
| `QUEUE`, con `WAKE` (una `Condition`) | Las llamadas que esperan al hilo: tuplas `(message, reply, event)` |
| `WORKER` | Una lista vacía hasta la primera llamada, y luego con el único hilo (**especulación:** una lista para que el módulo pueda consultarla y asignarla sin `global`) |
| `CALLS` | Id de petición a bandera de cancelación, para las llamadas en curso |
| `CANCELLED` | Ids que el cliente canceló y cuya respuesta aún no ha salido |
| `CURRENT` | Un dato local al hilo que guarda la bandera de la llamada que el hilo ejecuta, cuando su transporte dio una |

### Poner una llamada en la cola (`submit`, `:41-57`)

Una llamada se añade bajo el candado si hay menos de `MAX_QUEUE` (64) esperando. La primera llamada arranca el hilo
(`daemon=True`, `:49-51`): un servidor al que nunca se le ha pedido una herramienta no tiene worker. Si ya hay 64
esperando, la llamada **no** se encola: su id sale de `CALLS` y la función `reply` del transporte recibe de inmediato un
resultado de error que dice `64 calls are already waiting; try again when one finishes` (`:53-57`), redactado en la era
de la petición con `protocol.finish` (el `finish` de `worker.configure`). Lo fijan `test_queue`
(`tests/test_server.py:354`) y las tres pruebas que comprueban que la entrada queda limpia (`:421`, `:453`).

### Ejecutar una (`work`, `:60-80`)

El hilo espera a que la cola tenga algo, toma el primer elemento y ejecuta `reply(_answer(message))`: `_answer` es
`protocol.answer`, que es `protocol.handle` con una red de seguridad (`protocol.py:191-198`), y `reply` es la función que
dio el transporte. Un elemento `None` es la señal de parada (`:67-68`). Si la respuesta falla (un cliente que se fue a mitad
de la escritura) la excepción se captura y se registra como `reply to <id> failed: <NombreDeExcepción>`, y el hilo sigue con
la llamada siguiente (`:73-74`): sin esa captura, una tubería rota acabaría con el hilo y toda llamada posterior esperaría
para siempre (`test_worker_survives_a_failing_reply`, `tests/test_server.py:951`). En el `finally`, bajo el candado, la
entrada de la llamada se quita de `CALLS` (solo si sigue siendo la suya) y su id de `CANCELLED` (`:75-80`).

### Comprobaciones antes de que corra una herramienta (`call`, `:143-172`)

`protocol.handle` llama a `worker.call` para un `tools/call` (`protocol.py:170`). Sus pasos, con lo que recibe el cliente
cuando falla cada uno:

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
ningún argumento, etiqueta, ruta ni resultado. Véase [Logs](#logs).

### Cancelar

Hay dos cancelaciones, porque stdio y HTTP saben cosas distintas de sus clientes.

- `cancel_call(request_id)` (`:93-115`), por **id**. Si la llamada sigue en la cola se saca y se responde de inmediato con
  `the call was cancelled before it started` (`:101-111`); si está corriendo, se activa su bandera (`:112-115`) y la
  herramienta se detiene en su siguiente mirada. En ambos casos el id va a `CANCELLED` hasta que sale la respuesta, así que
  un transporte que puede callar (stdio) no escribe nada (`stdio.py:19-22`). Un id que no puede ser clave de diccionario se
  ignora (`:96-99`).
- `cancel_item(message, event)` (`:118-127`), por **identidad**. Lo usa HTTP cuando un cliente moderno cierra su conexión:
  dos clientes HTTP pueden enviar el mismo id, así que compara el mensaje exacto y la bandera exacta, saca de la cola un
  mensaje sin responderlo (su cliente se fue) y activa la bandera
  (`test_http_close_spares_another_client_with_the_same_id`, `tests/test_server.py:1107`).

Cómo nota la grabación la bandera está en [Grabar](./grabar.md): `recording.cancelled()` lee un dato local al hilo
(`recording.py:224-230`) que `worker.call` llena al empezar con la bandera propia de la llamada (`worker.py:147-148`).

### Progreso

Solo una llamada cuya petición lleva un `progressToken` tiene progreso. `worker.call` pone en `recording.RUN.progress` una
función que envía `notifications/progress` (`worker.py:149-151`), salvo que el id ya se haya cancelado. `recording.progress`
la llama cada `config.PROGRESS_TICKS` (5) segundos mientras corre una grabación. La notificación sale por `_send`, que
`metal_trace_mcp.py:50` fijó a `stdio.send`. Eso es correcto para stdio e incorrecto para HTTP, y por eso el manejador HTTP
quita `progressToken` antes de encolar una llamada (`http_transport.py:145-151`; [límite 11](#limites-conocidos)).

## Una llamada por el servidor

![El cliente MCP, el transporte, el worker, el protocolo y el registro como cinco columnas. Ocho flechas numeradas de arriba abajo: el cliente envía un tools/call al transporte; el transporte lo encola en el worker; el worker pide al protocolo que lo responda; el protocolo comprueba la era, el _meta y el nombre de la herramienta y vuelve a llamar al worker; el worker comprueba los argumentos y ejecuta la función del registro; el registro devuelve un diccionario o un error; el worker entrega la respuesta al transporte; el transporte escribe una línea en stdout o un HTTP 200. Una banda marca al worker como ocupado del paso 3 al paso 7.](/diagrams/server-request-sequence.png)
*Figura 1. Un `tools/call`. Fuente HTML: `docs/diagrams/server-request-sequence.html`.*

Dos cosas que muestra la figura y que [How it works](../../guides/how-it-works.md#one-request-end-to-end) dice en otro
orden. La cola va **antes** de `protocol.handle` para un `tools/call`: el transporte encola el mensaje crudo
(`stdio.py:43`, `http_transport.py:154`) y el hilo del worker es quien llama a `protocol.answer` (`worker.py:72`). `ping`,
`tools/list`, `resources/*` y `prompts/*` nunca tocan la cola: el transporte llama él mismo a `protocol.handle`, así que se
responden incluso mientras corre una grabación ([límite 1](#limites-conocidos)).

## Las dos eras, como referencia

Esta página no decide nada sobre las dos eras; lo hace el [ADR-0002](../../adr/0002-dual-era-mcp.md), y
[How it works](../../guides/how-it-works.md#why-it-is-shaped-this-way) dice por qué. Lo que necesita quien toca los
transportes es saber dónde se traza la línea entre ellas:

| | Era antigua (`initialize`) | Era moderna (2026-07-28) | Dónde |
|---|---|---|---|
| Cómo lo sabe el servidor | Todo lo demás, y siempre `initialize` | `server/discover`, o `params._meta` lleva la versión o las capacidades del cliente | `protocol.py:40-49` |
| Versiones | `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05` | `2026-07-28` | `:23-24` |
| Primer mensaje | `initialize`: se responde con la versión del cliente si está en la lista, y si no con la más nueva | Sin saludo; `server/discover` responde las versiones admitidas, las capacidades e `INSTRUCTIONS` | `:107-115` |
| `ping` | Se responde `{}` | No es un método: `-32601 unknown method ping` | `:116-117`; `:28-29`, `:104-105` |
| Un recurso que falta | `-32002` | `-32602` | `:106` |
| El resultado | Tal cual | Añade `resultType: complete`, el nombre y la versión del servidor en `_meta` y, para listas, lecturas y discover, `ttlMs` y `cacheScope` | `:71-83` |
| Cabeceras HTTP | `MCP-Protocol-Version` es opcional y, si se envía, debe ser una versión antigua de la lista | `MCP-Protocol-Version` y `Mcp-Method` obligatorias, y `Mcp-Name` en tres métodos | `http_transport.py:58-82` |
| Cancelar por HTTP | `notifications/cancelled` por id de petición | Cerrar la conexión | `http_transport.py:137-159` |

Las respuestas grabadas en `tests/golden/protocol.json` muestran la diferencia: el mismo `resources/read` de una corrida
que falta responde `-32002` en la era antigua y `-32602` en la moderna, y `ping` es `-32601` en la moderna (E9).

## HTTP en detalle

Un cliente que no puede arrancar un servidor stdio envía `POST http://127.0.0.1:8765/mcp` con una cabecera
`Authorization: Bearer <token>` y un mensaje JSON como cuerpo. El token es el de `METAL_TRACE_TOKEN`; los ejemplos de abajo
escriben `<token>` y nunca uno real.

### Las comprobaciones, en orden

![Siete cajas en fila, de izquierda a derecha: ruta, host y origen, token, tamaño, JSON, cabeceras y ejecución. Bajo cada una de las seis primeras, el estado con que responde: 404, 403, 401, 413, 400 con un error de análisis, y 400 o 404 con un error JSON-RPC. Si todas pasan, la petición se ejecuta.](/diagrams/server-http-checks.png)
*Figura 2. Lo que `do_POST` comprueba antes de que corra nada. Fuente HTML: `docs/diagrams/server-http-checks.html`.*

Piensa en un edificio con portero: la primera pregunta es si viniste a la puerta correcta (la ruta), la segunda si vienes
de la calle de afuera o de algún sitio que finge serlo (Host y Origin), la tercera si traes la llave (el token), y solo
entonces alguien mira lo que cargas (el cuerpo). El orden importa: a un cliente sin token nunca se le lee el cuerpo.

| # | Comprobación | Estado | La respuesta | Lo fija |
|---|---|---|---|---|
| 0 | El método es POST (`do_GET`, `do_DELETE`) | 405 | Vacía; todo GET o DELETE, antes de cualquier otra comprobación. `PUT`, `HEAD` y el resto no se definen aquí: los responde la biblioteca estándar (**probable**: 501; no ejecutado) | `tests/test_server.py:321`, `:893` |
| 1 | `self.path == "/mcp"` | 404 | Cuerpo vacío | `:322` |
| 2 | Host es `localhost` o `127.0.0.1`, y un Origin, si se envía, también | 403 | Cuerpo vacío | `:317-320` |
| 3 | `Authorization` lleva el token | 401 | Cuerpo vacío | `:315-316` |
| 4 | `Content-Length` son dígitos, 12 como mucho, y está entre 0 y `MAX_BODY` (1 000 000) | 413 | Cuerpo vacío | `tests/test_adversarial.py:225` |
| 5 | El cuerpo es JSON en UTF-8 que no se anida más de lo que acepta el analizador | 400 | Un error JSON-RPC, `-32700 parse error`, `id: null` | `:1031` |
| 6 | `check_headers` | 400 o 404 | Un error JSON-RPC con los códigos de la tabla siguiente | `:838`, `:847` |

Los estados 404, 403, 401 y 413 llevan el cuerpo **vacío** a propósito (`reply(code)` sin cuerpo,
`http_transport.py:99-101`): una negativa no le dice al cliente nada que no supiera. Las líneas son `:119-129`, y E1 lista
cada `self.reply` del archivo con su línea.

**Host y Origin** (`foreign`, `:108-111`; `local_host`, `:17-20`). La función quita un `esquema://` inicial y todo lo que
sigue a un `/`, toma lo que va antes del primer `:` y solo acepta `localhost` o `127.0.0.1`. El puerto no importa. Un
`Origin` solo se comprueba cuando el cliente lo envió; un `Host` ausente cuenta como no local. Las pruebas fijan
`http://evil.example`, `http://localhost.evil.example` y `Host: evil.example` como 403 y `http://localhost:<puerto>` como 200
(`tests/test_server.py:317-320`). Por qué las dos: una página en `evil.example` cuyo nombre se hizo resolver a `127.0.0.1`
envía `Host: evil.example`, así que la comprobación de Host la detiene; un navegador también envía un `Origin` en un POST
entre sitios, así que la comprobación de Origin detiene a la página que ni siquiera necesita el rebinding.

**El token** (`unauthorized`, `:113-116`). A la cabecera se le quita `Bearer ` si empieza por eso, y el resto se compara
con `hmac.compare_digest`, que tarda lo mismo sea cual sea el primer byte erróneo. El token se lee una sola vez al arrancar
(`:186`), nunca se registra, nunca se imprime y nunca forma parte de una respuesta; el único mensaje sobre él es la negativa
a arrancar (E5, `:188`). Una cabecera ausente, una vacía y una errónea son todas 401 (`tests/test_server.py:315-316`).

**Tamaño** (`:125-129`). Un `Content-Length` que no son dígitos ASCII (`²` pasa `str.isdigit()` y falla en `int()`), o que
tiene más de 12 caracteres, o que pasa de 1 000 000, es 413 sin leer el cuerpo; una prueba lo intenta con `0xB2` y con 5 000
nueves (`tests/test_adversarial.py:225-232`). Sin `Content-Length` cuenta como 0, así que un cuerpo enviado sin él, o con
`Transfer-Encoding: chunked`, se lee como vacío y se responde 400 `-32700` ([límite 8](#limites-conocidos)).

### `check_headers`: cuando las cabeceras no coinciden con el cuerpo

`check_headers(headers, message, era)` (`:46-82`) devuelve `(estado, cuerpo)` para un POST que la especificación rechaza, o
`None`. La era sale de `protocol.era(message)` (`:134`).

| Era | Condición | Estado y código | Línea |
|---|---|---|---|
| Antigua | El mensaje es una notificación y la cabecera de versión es la moderna | Se deja pasar | `:60-61` |
| Antigua | Se envía `MCP-Protocol-Version` y no es una versión antigua | 400, `-32600` `unsupported MCP-Protocol-Version <v>` | `:62-63` |
| Moderna | Una notificación | Se deja pasar, con o sin `_meta`: la especificación no define reglas de cabeceras para ella | `:65-66` |
| Moderna | Falta `MCP-Protocol-Version` o `Mcp-Method` | 400, `-32020` `Header mismatch: ... are required` | `:70-71` |
| Moderna | `Mcp-Method` no es el `method` del cuerpo | 400, `-32020` | `:72-73` |
| Moderna | La cabecera de versión no es la versión de `_meta` | 400, `-32020` | `:74-75` |
| Moderna | La versión no es `2026-07-28` | 400, `-32022 Unsupported protocol version`, con `data` que lista las admitidas y la pedida | `:76-77`, `protocol.py:52-55` |
| Moderna | El método no es uno de los modernos (`ping` no lo es) | 404, `-32601 unknown method` | `:78-79`, `protocol.py:28-29` |
| Moderna | `tools/call`, `prompts/get` o `resources/read` y `Mcp-Name` no es `params.name` (o `params.uri`) | 400, `-32020` | `:80-81` |

El `id` de la respuesta es el de la petición cuando es texto o número, y si no `null` (`:56`). `Mcp-Name` puede enviarse como
`=?base64?<utf-8 en base64>?=` para nombres que no son ASCII puro (`header_text`, `:31-43`); un Base64 malo, un relleno de más
y bytes que no son UTF-8 dan todos "sin valor", que entonces es una discrepancia. Los estados de cada fila los fijan
`test_http_modern_headers` (`tests/test_server.py:847`) y `test_http_legacy_headers` (`:838`).

Una petición que pasa `check_headers` aún puede responderse con un error, pero entonces **no** es un error HTTP: un error
JSON-RPC como `unknown tool x` o un resultado `isError` es un `200` con el error en el cuerpo (`:162`, `:168`). Solo las
comprobaciones de cabecera y de cuerpo de arriba son 4xx.

### Después de las comprobaciones

1. **`notifications/cancelled`** (`:137-142`): se responde `202` con el cuerpo vacío. En la era antigua cancela la llamada
   por id (`worker.cancel_call`); en la moderna se acepta y se **ignora**, porque un cliente moderno cancela cerrando la
   conexión y otro cliente puede compartir el id (`tests/test_server.py:1165`).
2. **`tools/call` con id** (`:143-162`):
   - Quita lo que el endpoint no puede transmitir. En la era moderna se quita `progressToken` de `_meta` y la versión se
     queda; en la antigua se quita `_meta` (`:147-151`).
   - Crea su propia bandera de cancelación, la registra bajo el id y encola el mensaje con una función que guarda la
     respuesta y despierta al hilo del manejador (`:152-154`).
   - Espera. **Moderna:** cada `POLL_S` (0,5 s) pregunta a `client_gone`, que asoma al socket buscando un fin de archivo
     (`:23-28`); si el cliente cerró, llama a `cancel_item` y vuelve sin escribir nada (`:155-159`;
     `test_http_close_cancels`, `tests/test_server.py:817`, fija "en un segundo o dos, y nada de vuelta"). **Antigua:** espera
     el resultado, incluso uno cancelado, porque esa era no tiene tal señal (`:160-161`;
     `test_http_legacy_cancel_keeps_reply`, `:799`).
   - Escribe `200` con la respuesta guardada (`:162`).
3. **Todo lo demás** (`:163-168`): `protocol.handle` corre en el hilo del manejador, no en el del worker. Una excepción se
   registra como `internal error <NombreDeExcepción>` y se responde `200` con `-32603 internal error`. Una respuesta `None`
   (una notificación) es `202`, y si no `200`.

### La función de respuesta y un cliente que se fue

`reply` (`:95-106`) escribe el estado, un `Content-Type` solo cuando hay cuerpo, un `Content-Length` siempre, y el cuerpo.
Un `ConnectionError` al escribir (el cliente cerró durante una llamada larga) pone `close_connection` y registra
`client closed the connection` en lugar de lanzar (`:104-106`; `test_http_reply_broken_pipe`, `tests/test_server.py:1067`).
`timeout = config.HTTP_TIMEOUT` (15 s, `:93`) descarta a un cliente que abre una conexión y se queda parado antes de terminar
su petición (`test_http_timeout`, `:473`), de modo que no puede retener un hilo para siempre. `log_message` está vacío
(`:176-177`): el registro de accesos de la biblioteca estándar, que imprimiría una línea por cada petición, está apagado.

## Logs

`logs.py` es una función (`:6-9`): imprime `metal-trace: <mensaje>` en stderr y vacía el búfer, salvo que `METAL_TRACE_LOG`
sea exactamente `off`. Nada más del paquete escribe por su cuenta en stderr ni en stdout: `send` (`stdio.py:12`) es el único
que escribe en stdout, y `serve_http` imprime una línea más de forma directa (`http_transport.py:188`, el mensaje del token,
que `METAL_TRACE_LOG=off` **no** silencia).

El docstring del propio módulo dice "the one stderr line per tool call", y el README también. En el código hay siete
llamadores (E6), que son todo el log:

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
rompería sin avisar ([Tocarlo sin romperlo](#tocarlo-sin-romperlo)). A dónde va a parar stderr (un archivo, un panel,
a ningún sitio) depende del cliente que lanzó el servidor: **no verificado** aquí.

## Cuando falla

La primera columna es lo que ve el cliente.

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
petición. Las pruebas que fijan cada fila se nombran en las secciones de arriba (`tests/test_server.py` salvo que se diga
otra cosa), y no se ejecutaron para esta página.

## Límites conocidos

Cada punto es un límite del comportamiento de hoy, anotado, no arreglado aquí.

| # | Límite | Dónde | Estado |
|---|---|---|---|
| 1 | [How it works](../../guides/how-it-works.md#one-request-end-to-end) lista "`protocol.handle` checks the era, the `_meta` and that the tool exists" (paso 2) **antes** de "the call waits in the worker queue" (paso 3). En el código, para un `tools/call` el transporte encola primero el mensaje crudo y `protocol.handle` corre en el hilo del worker (una excepción: `check_headers` de HTTP corre antes de la cola). Una petición que falla la comprobación del nombre de la herramienta espera por tanto su turno en la cola antes de ser rechazada | `stdio.py:38-44`, `worker.py:72`, `protocol.py:167-169`, `http_transport.py:134-154` | Confirmado; en qué orden debe decirlo la página lo decide el dueño |
| 2 | UTF-8 inválido en stdin no se captura: el error de decodificación lo lanza el iterador `for line in sys.stdin`, que está fuera del `try` que responde `-32700`. El transporte HTTP tiene una prueba para la misma entrada (`test_http_unreadable_body_is_a_parse_error`, `:1031`); no se encontró ninguna para stdio | `stdio.py:30-34`, `:46-50` | Probable: leído en el código; no ejecutado |
| 3 | Cerrar stdin no cancela nada: `stop_worker` encola una señal de parada **después** de las llamadas que ya esperan y espera al hilo, así que una grabación en curso, y cada una de las encoladas, terminan antes de que el servidor acabe. Para entonces nadie lee las respuestas (fallan y se registran). El vigilante del propio script detiene el programa si muere el proceso del servidor ([Grabar](./grabar.md#que-pasa-si-instruments-muere-a-mitad)), pero un servidor que sigue vivo con stdin cerrado sigue grabando | `stdio.py:53`, `worker.py:83-90` | Confirmado por el código; el efecto en un cliente real es probable |
| 4 | Un primer argumento desconocido arranca stdio en silencio, y tras `--http` solo se lee `--port N`: `--http 9000` sirve en el 8765. Un puerto que el sistema rechaza (fuera de rango, en uso) no se captura y acaba en un traceback de Python | `metal_trace_mcp.py:88-95`, `http_transport.py:190` | Confirmado para los argumentos; el traceback es probable (no ejecutado) |
| 5 | El prefijo `Bearer ` es opcional y distingue mayúsculas: una cabecera que es solo el token pasa, y `bearer <token>` no | `http_transport.py:115` | Confirmado por el código; no ejecutado. Si otros clientes envían el esquema en minúsculas: no verificado |
| 6 | `local_host` toma lo que precede al primer `:`, así que `localhost:1@evil.example` cuenta como local. Un navegador no envía información de usuario en `Host` ni en `Origin`, así que no se conoce forma de aprovecharlo desde una página web; las pruebas cubren solo el truco del sufijo con puntos | `http_transport.py:17-20`, `tests/test_server.py:317-319` | Confirmado leyendo la función; lo del navegador es **no verificado** |
| 7 | GET y DELETE responden 405 antes de las comprobaciones de Host, Origin y token, así que un cliente sin autenticar puede saber que el puerto es un servidor de esta clase | `http_transport.py:170-174` | Confirmado (inofensivo, pues no responde nada más) |
| 8 | Solo se lee `Content-Length`: `Transfer-Encoding: chunked` se lee como cuerpo vacío y se responde 400 `-32700` | `http_transport.py:125-133` | Probable: no ejecutado |
| 9 | Una llamada de un cliente HTTP de la era antigua espera sin plazo propio: la duración de la llamada es la de la herramienta. Solo una grabación tiene plazo (15 s por segundo grabado más 180, [Grabar](./grabar.md#un-ejemplo-primero)); las demás herramientas son cortas | `http_transport.py:160-161` | Probable |
| 10 | Tres grafías del mismo nombre: la negativa de arranque imprime `metal-gpu-trace:` (`:188`, fuera de `logs` y sin silenciar por `METAL_TRACE_LOG=off`), las líneas de log imprimen `metal-trace:` y el nombre del propio servidor en `serverInfo` es `metal-trace`. El docstring de `logs.py` y el README dicen una línea por llamada; el código escribe siete clases de línea | `http_transport.py:188`, `logs.py:1`, `:9`, `protocol.py:78` | Confirmado (cosmético) |
| 11 | `worker._send` es `stdio.send` también cuando el servidor corre con `--http` (`metal_trace_mcp.py:50`). El progreso es seguro solo porque el manejador HTTP quita antes `progressToken`; si esa eliminación desapareciera, el progreso se escribiría en el stdout del proceso, donde ningún cliente lee | `metal_trace_mcp.py:50`, `http_transport.py:145-151`, `worker.py:149-151` | Confirmado (un acoplamiento, no un fallo hoy) |
| 12 | `worker.call` convierte `FileNotFoundError`, `ValueError` y `RuntimeError` en el texto del cliente con `str(error)`. La regla "ninguna ruta en un error" (README) la cumple cada herramienta usando `ToolError` con su propio texto, no el worker; un `FileNotFoundError` crudo de una herramienta nueva mostraría su ruta | `worker.py:165-166` | Probable: leído en el código; no se encontró hoy ninguna herramienta que lo haga |

## Tocarlo sin romperlo

- **Una herramienta nueva.** Escribe `tool_x(...)` en su módulo de dominio, devolviendo un diccionario; su docstring se vuelve
  la descripción que lee el cliente (la primera línea primero). Añade la fila en `registry.TOOLS` con un esquema cuyas
  propiedades coincidan con los parámetros de la función, y pistas que digan si escribe. Cambian con ella una fila del
  README (`test_readme_lists_every_tool`), el número 26 en cuatro sitios (`tests/test_server.py:14`, `:139`, `:325`, `:666`)
  y `tests/golden/protocol.json`: regrábalo con `METAL_TRACE_GOLDEN=write python3 -I tests/run.py` y lee el diff, como dice
  `tests/golden/README.md`.
- **Un método nuevo en `protocol.handle`.** Decide para cada era si existe: los métodos modernos están en `MODERN_METHODS`
  (`protocol.py:28-29`), y `check_headers` rechaza una petición HTTP de cualquier método que no esté ahí. Añádelo a
  `tests/golden/protocol.json` mediante `GOLDEN_MESSAGES` (`tests/test_server.py:496`, `:514`).
- **Una comprobación nueva en HTTP.** Ponla en `do_POST` antes de leer el cuerpo cuando sea barata, responde con cuerpo
  **vacío** para una negativa de política y con un error JSON-RPC para una de protocolo, y añade su prueba junto a las
  `test_http_*` con el ayudante `local_http`.
- **Escribir desde el servidor.** Nunca hagas `print` a stdout: es el protocolo. Usa `logs.log` para stderr, y no pongas
  nunca un argumento, una ruta, una etiqueta ni un token en el mensaje; hoy todos los sitios escriben solo un nombre, un
  estado, una duración o un tipo de excepción.
- **Un transporte nuevo.** Llama a `worker.submit` para un `tools/call` y a `protocol.handle` para el resto; pasa su propio
  `send` a `worker.configure` mediante `metal_trace_mcp.py`; nunca ejecuta una herramienta. Vive en la capa 6, así que
  puede importar `protocol` y `worker` pero nada por encima (`tests/test_architecture.py:15-23`).
- **Un límite nuevo.** Ponlo en `config.py` y léelo como `config.NAME` en el sitio donde se usa, para que una prueba pueda
  parchear un solo atributo (la regla de [How it works](../../guides/how-it-works.md#two-rules-that-keep-it-testable);
  `test_http_timeout` parchea `config.HTTP_TIMEOUT` así).
- **El texto que leen los clientes.** `INSTRUCTIONS` cambia la respuesta a `initialize` y a `server/discover`, así que
  `tests/golden/protocol.json` cambia también; deja un espacio tras cada punto (`tests/test_server.py:1090`).

## Evidencia: los comandos y su salida real

Recogida el 2026-11-16 en un Mac con Apple silicon. Todos los comandos solo leen. La sesión que los recogió podía correr
comandos de lectura (`rg`, `sed`, `jq`), no Python ni el servidor, así que nada de lo que sigue es la salida de una
petición enviada a un servidor en vivo: las respuestas de E9 son las que guarda `tests/golden/protocol.json`, que
`test_golden_protocol` graba llamando a `protocol.handle` y compara en cada ejecución.

### E1 Cada estado con que responde el manejador HTTP, con su línea

```text
$ rg -n "self\.reply\((404|403|401|413|405|202)|self\.reply\(400" src/metal_gpu_trace/http_transport.py | cut -c1-130
120:                return self.reply(404)
122:                return self.reply(403)
124:                return self.reply(401)
129:                return self.reply(413)
133:                return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
142:                return self.reply(202)
168:            self.reply(202 if reply is None else 200, reply)
171:            self.reply(405)  # this server has no sessions to end
174:            self.reply(405)  # no event stream: this endpoint only answers POST
```

El orden de los números de línea (120, 122, 124, 129, 133) es el orden de las comprobaciones de la Figura 2. El 200 de una
llamada está en `:162` y `reply` mismo en `:95`. Enviar una petición para ver cada estado **no se reprodujo**;
`tests/test_server.py:315-323` afirma 401, 403, 405, 404 y 202 (véase la lista de E8).

### E2 Qué rechaza `check_headers`, y con qué código

```text
$ rg -n "refuse\(|return 400" src/metal_gpu_trace/http_transport.py | rg -v "def refuse" | cut -c1-135
63:            return refuse(400, -32600, f"unsupported MCP-Protocol-Version {version}")
71:        return refuse(400, -32020, "Header mismatch: MCP-Protocol-Version and Mcp-Method are required")
73:        return refuse(400, -32020, "Header mismatch: Mcp-Method does not match the method")
75:        return refuse(400, -32020, "Header mismatch: MCP-Protocol-Version does not match _meta")
77:        return 400, protocol.version_error(mid, version)
79:        return refuse(404, -32601, f"unknown method {method}")
81:        return refuse(400, -32020, f"Header mismatch: Mcp-Name does not match params.{NAMED[method]}")
```

Siete rechazos, uno por fila de la tabla de `check_headers` (la primera fila de la era antigua y las dos filas que dejan
pasar devuelven `None` y no están aquí). La línea 77 es el `-32022` de `protocol.version_error` (`protocol.py:52-55`).

### E3 Los límites que aplica el servidor

```text
$ rg -n "^(MAX_QUEUE|MIN_TOKEN|MAX_BODY|HTTP_TIMEOUT|MAX_TEXT) " src/metal_gpu_trace/config.py
45:MAX_TEXT = 40_000
52:MAX_QUEUE = 64
55:MIN_TOKEN = 16
56:MAX_BODY = 1_000_000
57:HTTP_TIMEOUT = 15  # seconds a client may take to send its request

$ rg -n "^POLL_S" src/metal_gpu_trace/http_transport.py | cut -c1-40
13:POLL_S = 0.5  # how often a modern PO
```

(El segundo comando lo corta `cut` a 40 caracteres.) Son los números que usa la página: 40 000 caracteres por resultado,
64 llamadas esperando, un token de al menos 16, un cuerpo de 1 000 000 de bytes como máximo, 15 s para enviar una petición y
0,5 s entre miradas para ver si un cliente se fue.

### E4 Cuántas herramientas, cuántas escriben, cuáles preguntan a la persona

```text
$ rg -c '^    "[a-z_]+": \(' src/metal_gpu_trace/registry.py
26

$ jq -c '[.[2].result.tools[]|.annotations.readOnlyHint]|group_by(.)|map({readOnly:.[0],n:length})' tests/golden/protocol.json
[{"readOnly":false,"n":10},{"readOnly":true,"n":16}]

$ jq -r '[.[2].result.tools[]|select(.annotations.destructiveHint==true)|.name]|join(" ")' tests/golden/protocol.json
perf_record perf_baseline_record perf_sweep perf_ab perf_cold_warm

$ jq -c '.[2].result.tools|map(select(._meta))|map([.name,._meta])' tests/golden/protocol.json
[["workload_fetch",{"anthropic/requiresUserInteraction":true}],["presentmon_install",{"anthropic/requiresUserInteraction":true}]]
```

El primer comando cuenta las filas de `TOOLS` por su forma (26); los otros tres leen la respuesta de `tools/list` que grabó la
prueba (`tests/golden/protocol.json`, tercer mensaje), no un servidor en vivo.

### E5 Cómo se lee la línea de comandos

```text
$ rg -n "sys\.argv" src/metal_gpu_trace/metal_trace_mcp.py | cut -c1-120
82:    if sys.argv[1:] == ["--version"]:
86:    if sys.argv[1:2] == ["check"]:
87:        sys.exit(check_cli(sys.argv[2:]))
88:    if sys.argv[1:2] == ["--http"]:
90:            port = int(sys.argv[3]) if sys.argv[2:3] == ["--port"] else 8765

$ rg -n "METAL_TRACE_TOKEN|MIN_TOKEN" src/metal_gpu_trace/http_transport.py | cut -c1-150
183:    """Serves the MCP endpoint over HTTP on 127.0.0.1 only, until interrupted. METAL_TRACE_TOKEN (at least MIN_TOKEN
186:    token = os.environ.get("METAL_TRACE_TOKEN", "")
187:    if len(token) < config.MIN_TOKEN:
188:        print(f"metal-gpu-trace: set METAL_TRACE_TOKEN to a secret of at least {config.MIN_TOKEN} characters", file=sys.stderr)
```

Tras `--http` solo se mira `--port` (límite 4). El valor de la variable se lee, nunca se imprime: el token no aparece en
ningún sitio de esta página.

### E6 Cada sitio que escribe una línea de log

```text
$ rg -n "logs\.log" src/metal_gpu_trace | cut -c1-140
src/metal_gpu_trace/stdio.py:49:            logs.log(f"internal error {type(error).__name__}")
src/metal_gpu_trace/http_transport.py:106:                logs.log("client closed the connection")
src/metal_gpu_trace/http_transport.py:166:                logs.log(f"internal error {type(error).__name__}")
src/metal_gpu_trace/http_transport.py:191:    logs.log(f"serving http://127.0.0.1:{server.server_address[1]}/mcp")
src/metal_gpu_trace/protocol.py:196:        logs.log(f"internal error {type(error).__name__}")
src/metal_gpu_trace/worker.py:74:            logs.log(f"reply to {message.get('id')!r} failed: {type(error).__name__}")
src/metal_gpu_trace/worker.py:171:    logs.log(f"{name} {'error' if result.get('isError') else 'ok'} in {time.monotonic() - started:.1f} s")
```

Siete sitios. Ninguno interpola un argumento, una ruta, una etiqueta ni un token; el único texto del cliente es el id de
petición de `worker.py:74`. `logs.py:8` compara `METAL_TRACE_LOG` con `"off"` de forma exacta.

### E7 Qué hace la biblioteca estándar bajo `ThreadingHTTPServer`

```text
$ rg -n "daemon_threads|protocol_version = \"" <Command Line Tools>/.../python3.9/http/server.py
145:    daemon_threads = True
623:    protocol_version = "HTTP/1.0"
```

La ruta está acortada. Es el Python 3.9 que traen las herramientas de línea de comandos de macOS, el mínimo que admite el
proyecto ([ADR-0003](../../adr/0003-python-3-9-floor.md)); no se leyeron las mismas líneas de otra versión de Python.

### E8 Las pruebas que fijan el comportamiento descrito aquí

```text
$ rg -n "def test_http|def test_queue|def test_cancel|def test_progress|def test_golden|def test_discover" tests/test_server.py | cut -c1-90
178:def test_progress_and_cancel(tmp_path):
276:def test_http(tmp_path):
354:def test_queue(tmp_path):
473:def test_http_timeout(tmp_path):
525:def test_golden_protocol(tmp_path):
586:def test_discover(tmp_path):
718:def test_cancel_sends_nothing(tmp_path):
729:def test_cancel_running_sends_nothing(tmp_path):
799:def test_http_legacy_cancel_keeps_reply(tmp_path):
817:def test_http_close_cancels(tmp_path):
838:def test_http_legacy_headers(tmp_path):
847:def test_http_modern_headers(tmp_path):
893:def test_http_delete_is_405(tmp_path):
898:def test_http_notification_202_empty(tmp_path):
914:def test_http_cancel_hits_its_own_call():
970:def test_cancel_item_takes_a_queued_call_out():
1031:def test_http_unreadable_body_is_a_parse_error(tmp_path):
1067:def test_http_reply_broken_pipe():
1097:def test_http_modern_notification_without_meta(tmp_path):
1107:def test_http_close_spares_another_client_with_the_same_id(tmp_path):
1165:def test_http_modern_cancel_notification_cancels_nothing(tmp_path):

$ sed -n 315,323p tests/test_server.py | cut -c1-110
        assert post(ping, {"Authorization": "Bearer nope"})[0] == 401
        assert post(ping, {"Authorization": ""})[0] == 401
        assert post(ping, {"Origin": "http://evil.example"})[0] == 403
        assert post(ping, {"Origin": "http://localhost.evil.example"})[0] == 403
        assert post(ping, {"Host": "evil.example"})[0] == 403
        assert post(ping, {"Origin": f"http://localhost:{port}"})[0] == 200
        assert post(None, method="GET")[0] == 405
        assert post(ping, path="/other")[0] == 404
        assert post({"jsonrpc": "2.0", "method": "notifications/initialized"}) == (202, None)
```

Son las aserciones de `test_http` para 401, 403, 405, 404 y 202. **No se ejecutaron** para esta página. El mismo
`test_http` afirma también que arrancar sin token, y con el token `short`, devuelve estado de salida 2
(`tests/test_server.py:289-291`).

### E9 Lo que responde el servidor, según lo grabaron las pruebas

```text
$ jq -c '[.[0,1]|.result.protocolVersion]' tests/golden/protocol.json
["2025-06-18","2025-11-25"]

$ jq -c 'to_entries[] | select(.value.error) | [.key, .value.error.code, .value.error.message[0:44]]' tests/golden/protocol.json
[7,-32002,"Resource not found"]
[9,-32602,"unknown tool no_such_tool"]
[10,-32601,"unknown method no/such/method"]
[16,-32602,"Resource not found"]
[17,-32601,"unknown method ping"]
[18,-32022,"Unsupported protocol version"]
[19,-32602,"_meta must hold io.modelcontextprotocol/prot"]

$ jq -c 'to_entries[12:15][] | [.key, .value.result.resultType, .value.result.ttlMs, .value.result.cacheScope]' tests/golden/protocol.json
[12,"complete",3600000,"public"]
[13,"complete",3600000,"public"]
[14,"complete",null,null]

$ jq -c '[(.[3].result.resources|length), (.[4].result.resourceTemplates|length), (.[5].result.prompts|map(.name))]' tests/golden/protocol.json
[5,1,["compare-layer","diagnose-stutter","bisect-regression"]]
```

Cómo leerlo. La primera respuesta (mensaje 0) pidió `2025-06-18` y lo obtuvo; la segunda (mensaje 1) pidió `1999-01-01` y
obtuvo la versión antigua más nueva, `2025-11-25`. En la lista de errores, el mensaje 7 es `resources/read` de una corrida
que falta en la era antigua (`-32002`) y el 16 es lo mismo en la era moderna (`-32602`); el 17 es `ping` en la era
moderna; el 18 una versión no admitida; el 19 una petición moderna cuyo `_meta` no tiene la versión ni las capacidades. Los
mensajes 12 a 14 son `server/discover`, `tools/list` y un `tools/call` en la era moderna: los dos primeros dicen que se
pueden guardar en caché una hora (3 600 000 ms, públicos); la llamada no dice nada, porque un resultado no se guarda en
caché. El mensaje 3 lista cinco recursos, el 4 una plantilla (las grabaciones) y el 5 tres prompts.

### Lo que no se reprodujo

- Arrancar el servidor, por stdio o por HTTP, y cualquier petición enviada a él: `initialize` y `tools/list` por stdio con
  una línea JSON, lo mismo por HTTP con `curl` y un token de prueba, y las tres negativas en vivo (404, 403, 401). E1 y E8
  dan las líneas que las producen y las pruebas que las fijan; E9 da las respuestas tal como las grabaron las pruebas.
- Que `tests/test_architecture.py` y el resto de la batería estén en verde: no se ejecutó ninguna prueba para esta página.
- Una cancelación sobre una grabación real, por stdio o por HTTP (hace falta una grabación, [Grabar](./grabar.md)).
- UTF-8 inválido en stdin, un puerto en uso o fuera de rango, un cuerpo `chunked`, y un `PUT` o `HEAD` (límites 2, 4 y 8, y
  la nota de la fila 0): leídos en el código, no ejecutados.
- El SDK oficial de MCP como cliente (`tests/conformance/`): necesita el SDK y no se ejecutó.
- A dónde muestra un cliente el stderr del servidor.

## Véase también

- [How it works](../../guides/how-it-works.md): la tabla de capas, las dos reglas y una petición en cinco líneas (véase el [límite 1](#limites-conocidos) para el orden).
- [ADR-0002](../../adr/0002-dual-era-mcp.md): por qué el servidor habla las dos eras, las alternativas y las desviaciones conocidas.
- [Grabar](./grabar.md): qué pasa dentro de `perf_record` después de que el worker lo llama, y cómo nota una cancelación.
- [Run from a clone](../../guides/run-from-a-clone.md): los comandos que arrancan el servidor desde un clon.
- `README.md`, sección "HTTP": el mismo endpoint desde el lado de quien lo usa.
