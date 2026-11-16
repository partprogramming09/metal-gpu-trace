# Por qué tiene esta forma

**Lector:** personas que cambian `traces.py` o `gputrace_read.py` y quieren saber por qué está construido así. Revisado el 2026-11-16.

English: [Why it is shaped this way](../../../guides/reading-traces/why-this-shape.md)

> **En corto:** cada decisión de abajo responde a una preocupación: no llenar el disco, no exigir Xcode, no informar de un
> cambio que quizá no existe, no dejar que un cliente abra cualquier archivo de la máquina. Cada fila nombra también la opción
> más simple que se descartó y qué habría salido mal con ella.

| Decisión | Por qué | Alternativas descartadas |
|---|---|---|
| Un `.trace` se lee **una tabla por llamada**, con `xctrace export` | Una grabación tiene 85 tablas en la medida (E8); cada exportación guarda un almacén temporal que puede llegar a gigabytes en una traza grande (`perf_report.py:39`), así que pedir solo la tabla que se quiere acota disco y tiempo | Exportar la traza entera una vez y responder desde ahí: gigabytes de XML en disco para una pregunta sobre una tabla |
| `trace_query` no guarda nada en caché: cada página vuelve a correr la exportación | Construye sus filas desde una exportación nueva en cada llamada y borra el archivo al terminar (`traces.py:101`, `:113-114`); el código no tiene caché. **Especulación:** la razón es el coste en disco de conservar un XML de la tabla | Conservar el XML exportado entre páginas: podría leerse un archivo viejo cuando la traza ya no está, y tendría la tabla dos veces |
| `window_ms` suma una tabla por ventana de tiempo | Una tabla de cientos de miles de filas no se puede leer fila a fila; el docstring la llama «un resumen de una tabla demasiado larga para leerla fila a fila» (`traces.py:93-96`) | Devolver más filas por página: una página tiene tope de 500 filas y 40 000 caracteres ([límites](./limites.md)) |
| `perf_export_trace` lee la tabla por fotograma, no el `.trace` | El `.trace` se borra por defecto ([ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md), `perf_record.sh:162-163`) y la tabla por fotograma se queda, así que la exportación funciona en una corrida cuya traza ya no existe (`traces.py:15`) | Leer el `.trace`: solo funcionaría con `KEEP_TRACE=1` y volvería a necesitar `xctrace` |
| El lector de `.gputrace` está escrito a mano con `struct` | No hace falta Xcode en la máquina que lee, y el servidor usa solo la biblioteca estándar (`CLAUDE.md`, [ADR-0003](../../../adr/0003-python-3-9-floor.md)); `struct` y `re` bastan para un flujo de registros (`gputrace_read.py:9-14`) | Llamar a Xcode o a un framework privado: ata la herramienta a una máquina con Xcode, y el formato de la lista de llamadas no es público |
| Cada llamada Metal lleva una **certeza**; `capture_diff` cuenta solo las confirmadas | Los ids de llamada se dedujeron a mano: 17 de los 24 ids con nombre son `"confirmado"`, 7 son `"probable"` (E2). Un diff que contara una suposición informaría de un cambio que quizá no existe (`gputrace_read.py:117`) | Contar todos los ids: un nombre equivocado aparecería como un cambio |
| `capture_diff` alinea por **etiqueta de grupo de depuración**, no por posición | Dos capturas de la misma escena suelen dibujar en otro orden; un grupo se empareja por su etiqueta, así que un grupo reordenado no es una diferencia (`gputrace_read.py:124-128`; E1 de la prueba de la 0.26.0) | Comparar registro a registro: una llamada añadida desplaza todo lo que viene después |
| Las rutas se comprueban antes de abrir nada | La ruta de un `.gputrace` debe estar dentro de `METAL_TRACE_OUT` o `METAL_TRACE_READ` (`paths.py:17-22`); un nombre de `.trace` se resuelve dentro de la carpeta de corridas y un enlace se rechaza (`paths.py:83-91`) | Leer cualquier ruta: un cliente podría hacer que el servidor abra un archivo en cualquier sitio al que llegue el usuario |

Volver al [índice](./index.md).
