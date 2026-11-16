# Las dos eras, como referencia

**Lector:** personas que tocan los transportes o el protocolo y necesitan saber dónde se separan el comportamiento antiguo y el moderno de MCP. Revisado el 2026-11-16.

English: [Eras](../../../guides/server-and-transport/eras.md) · [Índice](./index.md)

**En corto:** MCP, el idioma que hablan agentes y servidores, tiene una forma antigua y otra más nueva («eras»). Este servidor entiende las dos y las distingue por el primer mensaje. Decide el [ADR-0002](../../../adr/0002-dual-era-mcp.md); esto es una consulta.

| | Era antigua (`initialize`) | Era moderna (2026-07-28) | Dónde |
|---|---|---|---|
| Cómo lo sabe el servidor | Todo lo demás, y siempre `initialize` | `server/discover`, o `params._meta` lleva la versión o las capacidades del cliente | `protocol.py:40-49` |
| Versiones | `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05` | `2026-07-28` | `:23-24` |
| Primer mensaje | `initialize`: se responde con la versión del cliente si está en la lista, si no con la más nueva | Sin saludo; `server/discover` responde versiones, capacidades e `INSTRUCTIONS` | `:107-115` |
| `ping` | Se responde `{}` | No es un método: `-32601 unknown method ping` | `:116-117`; `:28-29`, `:104-105` |
| Un recurso que falta | `-32002` | `-32602` | `:106` |
| El resultado | Tal cual | Añade `resultType: complete`, nombre y versión en `_meta` y, para listas, lecturas y discover, `ttlMs` y `cacheScope` | `:71-83` |
| Cabeceras HTTP | `MCP-Protocol-Version` opcional y, si se envía, una versión antigua de la lista | `MCP-Protocol-Version` y `Mcp-Method` obligatorias, `Mcp-Name` en tres métodos | `http_transport.py:58-82` |
| Cancelar por HTTP | `notifications/cancelled` por id de petición | Cerrar la conexión | `http_transport.py:137-159` |

`tests/golden/protocol.json` lo muestra: el mismo `resources/read` de una corrida que falta es `-32002` en la era antigua y `-32602` en la moderna, y `ping` es `-32601` en la moderna ([E9](./evidencia.md#e9-lo-que-responde-el-servidor-segun-lo-grabaron-las-pruebas)). Por qué dos eras: [How it works](../../../guides/how-it-works.md#why-it-is-shaped-this-way).
