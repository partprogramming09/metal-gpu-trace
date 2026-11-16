# Las dos eras, como referencia

**Lector:** personas que tocan los transportes o el protocolo y necesitan saber dónde se separan el comportamiento antiguo y el moderno de MCP. Revisado el 2026-11-16.

English: [Eras](../../../guides/server-and-transport/eras.md) · [Índice](./index.md)

**En corto:** MCP, el idioma que hablan agentes y servidores, existe en una forma antigua y otra más nueva («eras»). Este
servidor entiende las dos y las distingue por el primer mensaje. La tabla de abajo es una consulta de dónde difieren.

Esta guía no decide nada sobre las dos eras; lo hace el [ADR-0002](../../../adr/0002-dual-era-mcp.md), y
[How it works](../../../guides/how-it-works.md#why-it-is-shaped-this-way) dice por qué.

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
que falta responde `-32002` en la era antigua y `-32602` en la moderna, y `ping` es `-32601` en la moderna
([E9](./evidencia.md#e9-lo-que-responde-el-servidor-segun-lo-grabaron-las-pruebas)).
