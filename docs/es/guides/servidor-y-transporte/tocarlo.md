# Tocarlo sin romperlo

**Lector:** personas que añaden una herramienta, un método, una comprobación HTTP, un transporte o un límite. Revisado el 2026-11-16.

English: [Touching it](../../../guides/server-and-transport/touching.md) · [Índice](./index.md)

**En corto:** una lista por cada clase de cambio. La mayoría tocan varios archivos porque las pruebas y el README cuentan las herramientas a propósito.

| Para añadir... | Haz esto |
|---|---|
| **Una herramienta** | `tool_x(...)` en su módulo de dominio, devolviendo un diccionario; su docstring es la descripción (la primera línea primero). Añade la fila de `registry.TOOLS` con un esquema que coincida con los parámetros y pistas que digan si escribe. Cambian también: una fila del README (`test_readme_lists_every_tool`), el número 26 (`tests/test_server.py:14`, `:139`, `:325`, `:666`) y `tests/golden/protocol.json` (regrábalo con `METAL_TRACE_GOLDEN=write python3 -I tests/run.py`, lee el diff, según `tests/golden/README.md`). Véase [Registro](./registro.md) |
| **Un método en `protocol.handle`** | Decide por era si existe: los modernos están en `MODERN_METHODS` (`protocol.py:28-29`) y `check_headers` rechaza todo método HTTP que no esté ahí. Añádelo a `tests/golden/protocol.json` con `GOLDEN_MESSAGES` (`tests/test_server.py:496`, `:514`). Véase [Eras](./eras.md) |
| **Una comprobación HTTP** | En `do_POST` antes de leer el cuerpo si es barata; cuerpo **vacío** para una negativa de política, error JSON-RPC para una de protocolo; su prueba junto a las `test_http_*` con `local_http`. Véase [HTTP](./http.md) |
| **Escribir desde el servidor** | Nunca `print` a stdout (es el protocolo). Usa `logs.log`, nunca con un argumento, ruta, etiqueta ni token: hoy cada sitio escribe un nombre, estado, duración o tipo de excepción. Véase [Logs](./logs.md) |
| **Un transporte** | Llama a `worker.submit` para `tools/call` y a `protocol.handle` para el resto, pasa su `send` a `worker.configure` mediante `metal_trace_mcp.py`, nunca ejecuta una herramienta. Capa 6: puede importar `protocol` y `worker`, nada por encima (`tests/test_architecture.py:15-23`). Véase [Worker](./worker.md) |
| **Un límite** | En `config.py`, leído como `config.NAME` donde se usa para que una prueba parchee un solo atributo ([How it works](../../../guides/how-it-works.md#two-rules-that-keep-it-testable); `test_http_timeout` parchea `config.HTTP_TIMEOUT`) |
| **El texto que leen los clientes** | `INSTRUCTIONS` cambia la respuesta a `initialize` y `server/discover`, así que `tests/golden/protocol.json` cambia también; deja un espacio tras cada punto (`tests/test_server.py:1090`). Véase [Arranque](./arranque.md) |
