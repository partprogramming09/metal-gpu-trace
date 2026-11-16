# Por qué los datos tienen esta forma

**Lector:** personas que cambian el grabador o el análisis. Revisado el 2026-11-16.

English: [Why the data is shaped this way](../../../guides/data-and-lifecycle/why-this-shape.md)

> **En corto:** una grabación es un archivo pequeño con los números más archivos grandes con los datos crudos. Si borras
> los grandes, los números siguen legibles. No hay base de datos a propósito: una carpeta se copia, se sube a git o se borra a mano.

Volver al [índice](./index.md). Ejemplo: la carpeta del índice tiene un resumen de 4,9 KiB junto a un `.trace` de 259 MiB, que explica casi todas las filas.

| Decisión | Por qué | Descartado |
|---|---|---|
| Un resumen JSON pequeño por corrida | Se compara, se comparte y se pega en un issue, así que se mantiene pequeño y sin nombres de máquina, UUID ni rutas absolutas ([What this is about](../../../guides/index.md#what-to-know-before-touching-it)) | Los números solo en el `.trace`: 259 MiB y necesita Instruments |
| Datos pesados en archivos hermanos con el nombre del stem | Una herramienta que necesita fotogramas lee `<stem>.frames.csv.gz`; la que solo necesita el resumen no los toca; podar lo pesado deja el resumen legible | Un archivo por corrida: podar lo reescribiría |
| Sin base de datos, sin índice | El servidor es solo biblioteca estándar en Python 3.9 ([ADR-0003](../../../adr/0003-python-3-9-floor.md)); una carpeta se copia, se sube a git o se borra a mano | Un archivo de base de datos (SQLite): **especulación** de que se descartó por lo mismo; ningún ADR lo recoge |
| `.trace` borrado por defecto | Decenas a cientos de MB, y el resumen guarda sus números (`perf_record.sh:162-163`); consérvalo con `KEEP_TRACE=1` o el nivel `deep` para `trace_query` o Instruments | Guardar todos los trazos: la carpeta crecía sin límite ([ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md)) |
| Tablas como `.csv.gz` | Las mismas filas, una fracción del tamaño; `tables.py` lee ambos formatos y las corridas viejas funcionan ([ADR-0006](../../../adr/0006-compressed-tables-and-disk-quota.md)) | CSV simple (pesado), `zlib` crudo (ninguna herramienta estándar), podar corridas enteras (pierde el resumen) |
| Dos mecanismos de retención | Uno cuenta corridas (`KEEP_RUNS`), otro bytes (`METAL_TRACE_MAX_DISK_MB`); ver [Retención](./retencion.md) | Una sola regla: el ADR descartó podar corridas enteras por tamaño |
