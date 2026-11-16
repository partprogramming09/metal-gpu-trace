# Cómo funciona [tema]

**Lector:** personas — [quién lo lee y qué sabe]. Antes: [enlace al documento previo, si lo hay]
**Última revisión:** AAAA-MM-DD
**Explica:** la función o el módulo que cubre, con su ruta (`src/pagos/`). Una guía por cada uno que tenga lógica propia: decisiones, varios pasos o reglas de negocio.
**Responde a:** la pregunta que resuelve este documento, por ejemplo "¿qué pasa cuando un usuario paga?"
**Lo esencial:** 2 o 3 líneas: qué pasa, de dónde a dónde y lo único que no hay que olvidar.
**Mapa:** qué cubre este documento y cuánto lleva leerlo (aproximado).

> Antes de rellenar esta plantilla, busca en `docs/guides/` si el tema ya está explicado. Si lo está, amplía ese documento en vez de crear otro.

## Por qué existe
<!-- El problema que resuelve, en dos o tres frases y sin jerga. -->

## Un ejemplo concreto
<!-- Un caso con datos de verdad (código real o un caso de uso), antes de cualquier teoría.
Una analogía cotidiana solo si el lector no es técnico o el concepto es nuevo. -->

## Lo que viaja de verdad
<!-- Los datos reales que pasan de una pieza a otra: un ejemplo de petición, de mensaje o de fila,
tal como se ve en ese punto del recorrido. -->

## Cómo funciona, paso a paso
![Los pasos, de principio a fin](/diagrams/[tema].png)
<!-- Dibujarlo con diagram-design: el HTML fuente en docs/diagrams/[tema].html y el PNG en docs/public/diagrams/[tema].png.
Elegir el tipo por lo que hay que mostrar: flujo si hay decisiones y ramas; secuencia si importa el orden de las llamadas; carriles si intervienen varias piezas a la vez; estados si algo cambia de fase; ER si lo importante son los datos y sus relaciones.
Los pasos del diagrama van numerados y la tabla de debajo usa los mismos números. -->

| Paso | Archivo | Qué mirar | Por qué |
|---|---|---|---|
| 1 | `ruta/archivo:línea` | | |

Si aparece un término técnico, se explica en ese mismo momento.

## Evidencia de que funciona así
<!-- Cada afirmación importante lleva su prueba: el comando o la acción corrida de verdad y su salida literal, pegada aquí (recortada, sin datos personales ni rutas de usuario; nunca en archivos .log ni en carpetas evidencias/). Un paso por fila, con el mismo número del diagrama. Si no se pudo correr, se escribe «no reproducido»: nunca se inventa una salida. -->

| Paso | Comando o acción | Salida real |
|---|---|---|
| 1 | `comando` | salida |

## Cómo comprobarlo tú
<!-- El comando o la acción más corta que demuestra que todo lo anterior sigue siendo cierto. -->

## En resumen
- Idea clave 1
- Idea clave 2

## Relacionado
<!-- Enlaces a los documentos que ya cubren temas cercanos, para no repetirlos aquí. -->
