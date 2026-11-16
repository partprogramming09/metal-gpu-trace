# Tocarlo sin romperlo

**Lector:** personas que añaden o cambian un número, una tabla, una comparación o un umbral en `perf_report.py`, `metrics.py`, `analysis.py` o `experiments.py`. Revisado el 2026-11-16.

English: [Changing it](../../../guides/summarizing/changing-it.md)

**En corto:** la regla que sostiene todo es que un número que nadie pudo medir está «ausente», nunca es cero. Segunda regla:
los lectores funcionan cuando la grabación ya no existe, así que nunca abren el trazo. Con las recetas de abajo, los
resúmenes viejos siguen funcionando.

Volver al [índice de la guía](./index.md).

| Quieres | Haz | Comprueba |
|---|---|---|
| Añadir un número | cálculo en `metrics.py` si Windows también puede producirlo, en `perf_report.py` si no; añade la clave al resumen y a la [guía de datos](../datos-y-su-ciclo-de-vida/claves-del-resumen.md#el-resumen-clave-por-clave) | una entrada ausente da `None` o ninguna clave, nunca `0`: todo lector trata `None` como «desconocido» |
| Leer una tabla nueva | añade su esquema a `OPTIONAL`, léela solo `if "<schema>" in tables`, añade una prueba junto a `test_toc_and_tables` | no la pongas en `TABLES` (obligatoria) salvo que todo resumen la necesite: una tabla obligatoria ausente rompe todo el informe ([límite 3](./limites.md)) |
| Comparar algo nuevo | añádelo a `numbers` en `compare_summaries` (`analysis.py:168`) | para decidir con él, añádelo a `CHECKED` (`:246`) y fija su margen en `judge` (`:325`); para exigirlo, añádelo a `GATES` (`:466`) |
| Cambiar un umbral (`STUTTER_FLOOR_MS`, `NOISY_EXTERNAL_PCT`, el 1.5, el 3 %) | cámbialo sabiendo que los resúmenes viejos conservan sus números como se escribieron, y que `skip_s` recalcula con el `frame_pacing` **actual** pero el `threshold_ms` **guardado** (`analysis.py:573-577`): los dos discreparán en corridas viejas | actualiza `tests/golden/metrics.json` |
| Leer un trazo desde `analysis.py` | no lo hagas: lee solo resúmenes y `frames.csv`, por eso funciona cuando el trazo ya no está; leer el trazo es cosa de `perf_report.py` y de las herramientas de `traces.py` | |
| Añadir una herramienta que lee un resumen | mantén `reads_recordings` sobre ella (`analysis.py:37-48`) | mantén las rutas fuera de sus mensajes |
