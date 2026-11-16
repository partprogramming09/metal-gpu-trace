# Dos reglas: una a la vez, y 30 segundos bajo Wine

**Lector:** personas que cambian el candado o el consejo sobre la duración de una grabación. Revisado el 2026-11-16. Etiquetas: véase [Grabar](./index.md#como-leer-las-etiquetas).

English: [Two rules](../../../guides/recording/rules.md)

**En corto:** en un Mac solo puede correr una grabación a la vez, porque dos programas que comparten el chip gráfico se
estropean las mediciones. Bajo Wine, una grabación debería durar 30 segundos o más, porque los primeros segundos se
gastan en arrancar. Ejemplo: un segundo `perf_record` mientras otro corre se rechaza antes de arrancar nada.

## Una grabación a la vez

Lo dicen las instrucciones del servidor («One recording runs at a time», `metal_trace_mcp.py:25`); se cumple en tres niveles:

| Nivel | Qué impide | Dónde |
|---|---|---|
| El hilo trabajador | Dos llamadas de herramienta de un mismo servidor corriendo a la vez | `worker.py:1` |
| La carpeta-candado, leída por preflight | Que empiece una grabación mientras otra, de cualquier servidor o a mano, tiene el candado | `preflight.py:74-98`, `:135-137` |
| La carpeta-candado, tomada por el script (o el motor de Windows) | Lo mismo, en el momento que importa: `mkdir` es atómico, así que solo un proceso puede crearla | `perf_record.sh:52-62`, `perf_record_windows.py:577-598` |

**Por qué.** `perf_record.sh:40`: «two programs sharing the GPU spoil both measurements» (dos programas que comparten la
GPU estropean las dos mediciones; confirmado). A posteriori, `noisy_environment` compara el uso total de la GPU con la
parte ocupada del propio programa y marca una diferencia de 20 puntos o más, un umbral provisional (`how-it-works.md`,
«What to do next»; la clave está en la
[guía de datos](../datos-y-su-ciclo-de-vida/claves-del-resumen.md#claves-de-un-resumen-de-macos-presentes-solo-bajo-una-condicion)).

**Por qué un solo candado para todas las carpetas.** Cada proyecto tiene su carpeta de corridas, pero hay una sola GPU:
el candado vive en la carpeta de caché (`config.py:41-42`; `test_recordings_into_two_folders_run_one_at_a_time`, `tests/test_recording.py:854`).

La vida del candado está en la [guía de datos](../datos-y-su-ciclo-de-vida/cache-y-candado.md#el-candado). Lo nuevo aquí:
un candado tomado hace que la segunda grabación se rechace **antes** de arrancar nada (`preflight.py:135-137`), con
`another recording is running; one runs at a time. If none is, remove the lock folder (METAL_TRACE_LOCK names it)`.

## Por qué 30 segundos o más bajo Wine

La instrucción: «Under Wine record 30 s or more: Wine's start-up takes part of the recording» (bajo Wine graba 30 s o
más: el arranque de Wine ocupa parte de la grabación; `metal_trace_mcp.py:27`; también `registry.py:39` y `README.md:138`):
**confirmado como la razón que da el proyecto**. Detrás:

| Parte | Qué dice el código | Etiqueta |
|---|---|---|
| **Los primeros segundos no son el régimen estable del programa.** Wine arranca, el programa abre su ventana y compila shaders mientras Instruments ya graba | `skip_s` recorta ese arranque de una comparación (`metal_trace_mcp.py:31`); `analysis._startup_skip_s` busca hitches de compilación de shaders que terminen dentro del primer cuarto de la corrida (`analysis.py:670-690`). **Cuántos segundos dura el arranque no se midió**; el 30 es la regla práctica del proyecto | **probable** |
| **No es la regla de 100 fotogramas.** Una corrida de menos de 100 fotogramas se marca aparte | `analysis.py:378`, `:499`, `:655`: «under 100 frames: too short to judge; record 30 s or more». A 60 FPS 100 fotogramas son menos de 2 segundos: un suelo para comparar siquiera, y los 30 s son por el arranque | **especulación**: aritmética de dos reglas enunciadas, no una medición |

El lado del coste es la razón del plazo:

- Una grabación de Wine D3D12 de 30 s produjo un trace de 614 MB y unos 93 s solo para leerse (`CHANGELOG.md`, 0.8.1).
- Cada segundo grabado necesita unos 0,8 GB de disco temporal (`perf_record.sh:33`, un comentario del código: **probable**).
- Las corridas nativas de Metal son más cortas: una entrada del changelog menciona corridas nativas de 10 s junto a corridas de 30 s bajo Wine (`CHANGELOG.md:309`).
