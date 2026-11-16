# Los datos de las familias de GPU

**Lector:** personas que preguntan qué puede hacer una GPU, o que cambian `gpu_family` o su archivo de datos. Revisado el 2026-11-16.

English: [The GPU family facts](../../../guides/reading-traces/gpu-families.md)

> **En corto:** esto es un librito de consulta, no un lector de grabaciones. Le das el nombre de un chip, como `M1 Pro`, y
> devuelve los datos que Apple publica de esa familia de GPU, con los enlaces de donde salen. Está aquí porque esos datos
> ayudan a leer una traza: «¿qué puede hacer esta GPU?».

`gpu_family(name)` y los recursos `metal-trace://gpu-families` y `metal-trace://gpu-families/<family>` devuelven los datos
publicados por Apple de una familia de GPU o de un chip. No leen ninguna grabación. **No ejecutado.**

| Aspecto | Comportamiento | Línea |
|---|---|---|
| Nombres aceptados | una clave de familia (`Apple7`) o un nombre de chip (`M1 Pro`, `A15`), tras pasar a minúsculas y quitar espacios; para un chip con el sufijo `ultra`, `max` o `pro` prueba también el nombre sin él | `traces.py:177-185` (`family_of`), `:182` |
| Datos | `src/metal_gpu_trace/data/apple-gpu-families.json`, leído una vez al importar; cuatro familias: `Apple7`, `Apple8`, `Apple9`, `Apple10` (E7) | `config.py:35` |
| Nombre desconocido | `unknown family or chip '<name>'; try one of Apple7, ... or a chip such as M1 Pro, M2, M3 Max, A17 Pro` | `traces.py:192-194` |
| Fuentes | los datos llevan sus URL de origen | `:195-196` |

Este proyecto reformula las páginas de Apple y no las cita (README «Credits»).

Volver al [índice](./index.md).
