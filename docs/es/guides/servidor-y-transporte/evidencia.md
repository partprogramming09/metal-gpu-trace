# Evidencia: los comandos y su salida real

**Lector:** personas que quieren comprobar una cifra o una línea de esta guía, o ver qué no se reprodujo. Revisado el 2026-11-16.

English: [Evidence](../../../guides/server-and-transport/evidence.md) · [Índice](./index.md)

**En corto:** cada cifra de esta guía sale de un comando listado aquí, con su salida real. Todos fueron búsquedas de solo
lectura sobre el código y sobre las respuestas grabadas por las pruebas; el servidor en sí no se arrancó para esta guía, y
la última sección lista lo que por eso no se reprodujo.

Recogida el 2026-11-16 en un Mac con Apple silicon. Todos los comandos solo leen. La sesión que los recogió podía correr
comandos de lectura (`rg`, `sed`, `jq`), no Python ni el servidor, así que nada de lo que sigue es la salida de una
petición enviada a un servidor en vivo: las respuestas de E9 son las que guarda `tests/golden/protocol.json`, que
`test_golden_protocol` graba llamando a `protocol.handle` y compara en cada ejecución.

## E1 Cada estado con que responde el manejador HTTP, con su línea

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

El orden de los números de línea (120, 122, 124, 129, 133) es el orden de las comprobaciones de la [Figura 2](./http.md). El 200 de una
llamada está en `:162` y `reply` mismo en `:95`. Enviar una petición para ver cada estado **no se reprodujo**;
`tests/test_server.py:315-323` afirma 401, 403, 405, 404 y 202 (véase la lista de E8).

## E2 Qué rechaza `check_headers`, y con qué código

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

Siete rechazos, uno por fila de la tabla de `check_headers` en [HTTP](./http.md) (la primera fila de la era antigua y las dos filas que dejan
pasar devuelven `None` y no están aquí). La línea 77 es el `-32022` de `protocol.version_error` (`protocol.py:52-55`).

## E3 Los límites que aplica el servidor

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

(El segundo comando lo corta `cut` a 40 caracteres.) Son los números que usa la guía: 40 000 caracteres por resultado,
64 llamadas esperando, un token de al menos 16, un cuerpo de 1 000 000 de bytes como máximo, 15 s para enviar una petición y
0,5 s entre miradas para ver si un cliente se fue.

## E4 Cuántas herramientas, cuántas escriben, cuáles preguntan a la persona

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

## E5 Cómo se lee la línea de comandos

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

Tras `--http` solo se mira `--port` ([límite 4](./limites.md)). El valor de la variable se lee, nunca se imprime: el token no aparece en
ningún sitio de esta guía.

## E6 Cada sitio que escribe una línea de log

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

## E7 Qué hace la biblioteca estándar bajo `ThreadingHTTPServer`

```text
$ rg -n "daemon_threads|protocol_version = \"" <Command Line Tools>/.../python3.9/http/server.py
145:    daemon_threads = True
623:    protocol_version = "HTTP/1.0"
```

La ruta está acortada. Es el Python 3.9 que traen las herramientas de línea de comandos de macOS, el mínimo que admite el
proyecto ([ADR-0003](../../../adr/0003-python-3-9-floor.md)); no se leyeron las mismas líneas de otra versión de Python.

## E8 Las pruebas que fijan el comportamiento descrito aquí

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

Son las aserciones de `test_http` para 401, 403, 405, 404 y 202. **No se ejecutaron** para esta guía. El mismo
`test_http` afirma también que arrancar sin token, y con el token `short`, devuelve estado de salida 2
(`tests/test_server.py:289-291`).

## E9 Lo que responde el servidor, según lo grabaron las pruebas

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

## Lo que no se reprodujo

- Arrancar el servidor, por stdio o por HTTP, y cualquier petición enviada a él: `initialize` y `tools/list` por stdio con
  una línea JSON, lo mismo por HTTP con `curl` y un token de prueba, y las tres negativas en vivo (404, 403, 401). E1 y E8
  dan las líneas que las producen y las pruebas que las fijan; E9 da las respuestas tal como las grabaron las pruebas.
- Que `tests/test_architecture.py` y el resto de la batería estén en verde: no se ejecutó ninguna prueba para esta guía.
- Una cancelación sobre una grabación real, por stdio o por HTTP (hace falta una grabación, [Grabar](../grabar/index.md)).
- UTF-8 inválido en stdin, un puerto en uso o fuera de rango, un cuerpo `chunked`, y un `PUT` o `HEAD` (límites 2, 4 y 8, y
  la nota de la fila 0 en [HTTP](./http.md)): leídos en el código, no ejecutados.
- El SDK oficial de MCP como cliente (`tests/conformance/`): necesita el SDK y no se ejecutó.
- A dónde muestra un cliente el stderr del servidor.
