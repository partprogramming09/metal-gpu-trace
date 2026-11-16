# Tocarlo sin romperlo

**Lector:** personas que añaden una herramienta, un método, una comprobación HTTP, un transporte o un límite. Revisado el 2026-11-16.

English: [Touching it](../../../guides/server-and-transport/touching.md) · [Índice](./index.md)

**En corto:** una lista corta por cada clase de cambio. La mayoría de los cambios tocan más de un archivo porque las
pruebas y el README cuentan las herramientas a propósito; la lista dice cuáles.

| Para añadir... | Haz esto |
|---|---|
| **Una herramienta nueva** | Escribe `tool_x(...)` en su módulo de dominio, devolviendo un diccionario; su docstring se vuelve la descripción que lee el cliente (la primera línea primero). Añade la fila en `registry.TOOLS` con un esquema cuyas propiedades coincidan con los parámetros de la función, y pistas que digan si escribe. Cambian con ella una fila del README (`test_readme_lists_every_tool`), el número 26 en cuatro sitios (`tests/test_server.py:14`, `:139`, `:325`, `:666`) y `tests/golden/protocol.json`: regrábalo con `METAL_TRACE_GOLDEN=write python3 -I tests/run.py` y lee el diff, como dice `tests/golden/README.md`. Véase [Registro](./registro.md) |
| **Un método nuevo en `protocol.handle`** | Decide para cada era si existe: los métodos modernos están en `MODERN_METHODS` (`protocol.py:28-29`), y `check_headers` rechaza una petición HTTP de cualquier método que no esté ahí. Añádelo a `tests/golden/protocol.json` mediante `GOLDEN_MESSAGES` (`tests/test_server.py:496`, `:514`). Véase [Eras](./eras.md) |
| **Una comprobación nueva en HTTP** | Ponla en `do_POST` antes de leer el cuerpo cuando sea barata, responde con cuerpo **vacío** para una negativa de política y con un error JSON-RPC para una de protocolo, y añade su prueba junto a las `test_http_*` con el ayudante `local_http`. Véase [HTTP](./http.md) |
| **Escribir desde el servidor** | Nunca hagas `print` a stdout: es el protocolo. Usa `logs.log` para stderr, y no pongas nunca un argumento, una ruta, una etiqueta ni un token en el mensaje; hoy todos los sitios escriben solo un nombre, un estado, una duración o un tipo de excepción. Véase [Logs](./logs.md) |
| **Un transporte nuevo** | Llama a `worker.submit` para un `tools/call` y a `protocol.handle` para el resto; pasa su propio `send` a `worker.configure` mediante `metal_trace_mcp.py`; nunca ejecuta una herramienta. Vive en la capa 6, así que puede importar `protocol` y `worker` pero nada por encima (`tests/test_architecture.py:15-23`). Véase [Worker](./worker.md) |
| **Un límite nuevo** | Ponlo en `config.py` y léelo como `config.NAME` en el sitio donde se usa, para que una prueba pueda parchear un solo atributo (la regla de [How it works](../../../guides/how-it-works.md#two-rules-that-keep-it-testable); `test_http_timeout` parchea `config.HTTP_TIMEOUT` así) |
| **El texto que leen los clientes** | `INSTRUCTIONS` cambia la respuesta a `initialize` y a `server/discover`, así que `tests/golden/protocol.json` cambia también; deja un espacio tras cada punto (`tests/test_server.py:1090`). Véase [Arranque](./arranque.md) |
