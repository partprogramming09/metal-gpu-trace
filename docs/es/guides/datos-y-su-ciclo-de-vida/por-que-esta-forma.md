# Por qué los datos tienen esta forma

**Lector:** personas que cambian el grabador o el análisis. Revisado el 2026-11-16.

English: [Why the data is shaped this way](../../../guides/data-and-lifecycle/why-this-shape.md)

> **En corto:** una grabación se reparte en un archivo pequeño con los números y varios archivos grandes con los datos
> crudos. Se pueden borrar los grandes y los números siguen legibles. No hay base de datos a propósito: una carpeta se
> copia, se sube a una rama o se borra a mano. Esta página lista cada decisión, su porqué y lo que se descartó.

Volver al [índice](./index.md). Ejemplo: la carpeta del índice muestra un resumen de 4,9 KiB junto a un `.trace` de
259 MiB, que es la razón de casi todas las filas de abajo.

| Decisión | Por qué | Alternativas descartadas |
|---|---|---|
| Un resumen JSON pequeño por corrida | Es lo que se compara, se comparte y se pega en una incidencia, así que debe ser pequeño y sin nombres de máquina, UUID ni rutas absolutas ([What this is about](../../../guides/index.md#what-to-know-before-touching-it)) | Dejar los números solo en el `.trace`: pesa 259 MiB y hace falta Instruments para abrirlo |
| Datos pesados en archivos hermanos con el nombre del stem | Una herramienta que necesita los fotogramas lee `<stem>.frames.csv.gz`; la que solo necesita el resumen no los toca. Borrar lo pesado de una corrida vieja deja el resumen legible | Un solo archivo por corrida: podar significaría reescribirlo |
| Sin base de datos ni índice | El servidor usa solo la biblioteca estándar en Python 3.9 ([ADR-0003](../../../adr/0003-python-3-9-floor.md)) y una carpeta se copia, se sube a una rama o se borra a mano | Un archivo de base de datos (por ejemplo SQLite): **especulación** de que se dejó fuera por la misma razón; ningún ADR recoge la decisión |
| `.trace` borrado por defecto | Pesa de decenas a cientos de MB y el resumen ya tiene sus números (`perf_record.sh:162-163`); se conserva con `KEEP_TRACE=1` o con el nivel `deep` cuando se quiere `trace_query` o Instruments | Conservar todos los trazos: la carpeta crecía sin tope ([ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md)) |
| Tablas como `.csv.gz` | Las mismas filas en una fracción del tamaño, y `tables.py` lee los dos formatos para que las corridas antiguas sigan funcionando ([ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md)) | CSV sin comprimir (pesado), `zlib` crudo (ninguna herramienta estándar lo abre), podar corridas enteras (pierde el resumen) |
| Dos mecanismos de retención | Uno cuenta corridas (`KEEP_RUNS`), otro cuenta bytes (`METAL_TRACE_MAX_DISK_MB`); responden a preguntas distintas y borran cosas distintas (ver [Retención](./retencion.md)) | Una sola regla: el ADR descartó podar corridas enteras por tamaño porque pierde el resumen |
