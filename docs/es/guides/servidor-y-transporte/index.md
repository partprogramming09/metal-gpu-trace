# Servidor y transporte

**Lector:** personas que cambian cómo arranca, escucha y responde el servidor (`metal_trace_mcp.py`, `stdio.py`, `http_transport.py`, `worker.py`, `registry.py`, `logs.py`), que añaden o renombran una herramienta, o que necesitan saber por qué un cliente recibió un error, un estado o un silencio. Revisado el 2026-11-16.

English: [Server and transport](../../../guides/server-and-transport/index.md)

**En corto:** el servidor es el programa con el que habla un agente de IA. El agente envía una petición («graba este
juego 30 segundos»); el servidor la comprueba y la ejecuta en un solo worker, para que dos grabaciones nunca se disputen
la GPU. Se llega a él por una tubería (stdio) o por una dirección web local (HTTP) que exige un token secreto. Esta guía
sigue una petición y dice qué pasa cuando falla.

No repite [How it works](../../../guides/how-it-works.md) (capas, las dos reglas, una petición en cinco líneas) ni
[ADR-0002](../../../adr/0002-dual-era-mcp.md) (por qué dos eras de MCP). Cómo se leen las grabaciones está en
[Grabar](../grabar/index.md) y [Resumir y analizar](../resumir-y-analizar/index.md): esta guía se detiene donde empieza la
función de una herramienta. Es la versión en español de la guía en inglés: mismo contenido, diagramas y evidencia (comandos,
salidas y mensajes de error del programa no se traducen).

## Las páginas

| Página | Qué responde |
|---|---|
| [Diseño](./diseno.md) | Por qué el servidor tiene esta forma; las piezas y el archivo de cada una |
| [Arranque](./arranque.md) | La línea de comandos, stdio, el arranque de HTTP, qué se configura y cuándo |
| [Registro](./registro.md) | Herramientas, recursos, prompts y lo que los fija |
| [Worker](./worker.md) | La cola, las comprobaciones antes de que corra una herramienta, cancelar, progreso |
| [Eras](./eras.md) | Dónde difieren la era antigua y la moderna de MCP |
| [HTTP](./http.md) | Las siete comprobaciones, `check_headers`, lo que pasa después, un cliente que se fue |
| [Logs](./logs.md) | La línea única en stderr y los siete sitios que la escriben |
| [Cuando falla](./fallos.md) | Qué recibe el cliente y qué hace el servidor, por cada fallo |
| [Límites conocidos](./limites.md) | Doce límites del comportamiento de hoy: once abiertos, uno arreglado (fila 2) |
| [Tocarlo sin romperlo](./tocarlo.md) | Cómo añadir una herramienta, método, comprobación, transporte o límite |
| [Evidencia](./evidencia.md) | Cada comando que se corrió (E1 a E9) y lo que no se reprodujo |

## Cómo leer las etiquetas

Cada afirmación es **confirmada** (`archivo:línea`, comprobada con `rg` o `sed` el 2026-11-16 contra el árbol de trabajo:
0.27.2 más las entradas `[Unreleased]` de `CHANGELOG.md`), **probable** (leída en el código, no ejecutada) o
**especulación** (una conjetura sobre el porqué). **No verificado** marca un dato de fuera no comparado con su fuente. Las
líneas se mueven: busca el nombre, no solo el número. Cada cifra tiene su comando en [Evidencia](./evidencia.md). **No
reproducido** significa no ejecutado: la sesión que la escribió solo podía leer, así que no se arrancó el servidor, no se
envió ninguna petición ni se ejecutó ninguna prueba; se nombran las pruebas que fijan cada comportamiento y **no se
ejecutaron**.

## Un ejemplo primero

Un agente pide, por stdio, grabar un programa 30 segundos, y a medias cambia de idea:

```text
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"perf_record","arguments":{"label":"mygame","program":"/path/to/mygame.exe","wine":"/path/to/wine","seconds":30}}}
```

| # | Qué pasa | Dónde |
|---|---|---|
| 1 | El bucle de stdio ve un `tools/call` con id y **no** lo ejecuta: crea una bandera de cancelación para el id 7, encola el mensaje y vuelve a leer | `stdio.py:42-48` |
| 2 | El hilo del worker (arrancó con la primera llamada y vive lo que el servidor) lo toma y pide al protocolo que lo responda; el protocolo comprueba que el nombre de la herramienta está en el registro y devuelve la llamada a `worker.call` | `worker.py:60-72`, `protocol.py:167-169`, `:170` |
| 3 | `worker.call` comprueba el archivo de proyecto, luego los argumentos contra el esquema y ejecuta la función del registro. Aquí se van los 30 segundos | `worker.py:155-158` |
| 4 | Mientras tanto llega `{"id":8,"method":"ping"}`. El bucle está libre y responde `ping` él mismo, en el hilo que lee, sin la cola | `stdio.py:49`, `:55-56` |
| 5 | `{"method":"notifications/cancelled","params":{"requestId":7}}` activa la bandera de la llamada 7. La grabación la mira cada segundo y se mata ([Grabar, la secuencia de cierre forzado](../grabar/recorrido-macos.md#la-secuencia-de-cierre-forzado)); la función lanza `the recording was cancelled; nothing was saved` y el worker lo convierte en un resultado de error. stdio no escribe **nada** para el id 7: la especificación dice que una llamada cancelada no recibe respuesta | `stdio.py:35-37`, `worker.py:93-115`, `stdio.py:19-22` |
| 6 | Sin cancelar, la función devuelve un diccionario, escrito como texto JSON (40 000 caracteres como máximo) y como una línea en stdout. En ambos casos el worker escribe una línea en stderr: `metal-trace: perf_record error in <segundos> s` o `... ok in <segundos> s` | `worker.py:171` |

Por HTTP el medio (pasos 2, 3 y 6) es el mismo; el principio y el final cambian: véase [HTTP](./http.md).

![El cliente MCP, el transporte, el worker, el protocolo y el registro como cinco columnas. Ocho flechas numeradas de arriba abajo: el cliente envía un tools/call al transporte; el transporte lo encola en el worker; el worker pide al protocolo que lo responda; el protocolo comprueba la era, el _meta y el nombre de la herramienta y vuelve a llamar al worker; el worker comprueba los argumentos y ejecuta la función del registro; el registro devuelve un diccionario o un error; el worker entrega la respuesta al transporte; el transporte escribe una línea en stdout o un HTTP 200. Una banda marca al worker como ocupado del paso 3 al paso 7.](./img/server-request-sequence.png)
*Figura 1. Un `tools/call`. Fuente: `img/server-request-sequence.html`.*

La figura difiere de [How it works](../../../guides/how-it-works.md#one-request-end-to-end) en un orden: la cola va **antes**
de `protocol.handle` para un `tools/call` (`stdio.py:47`, `http_transport.py:154`; el worker llama a `protocol.answer`,
`worker.py:72`). `ping`, `tools/list`, `resources/*` y `prompts/*` se saltan la cola y se responden incluso mientras corre
una grabación ([límite 1](./limites.md)).

## Véase también

[Run from a clone](../../../guides/run-from-a-clone.md) (los comandos que arrancan el servidor) y `README.md`, sección "HTTP" (el mismo endpoint desde el lado de quien lo usa).
