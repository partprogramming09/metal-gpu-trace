# Límites conocidos

**Lector:** personas que deciden qué arreglar después en la grabación. Revisado el 2026-11-16. Etiquetas: véase [Grabar](./index.md#como-leer-las-etiquetas).

English: [Known limits](../../../guides/recording/limits.md)

**En corto:** esta es la lista de cosas que la grabación hace hoy y que un lector podría no esperar: algunos mensajes de
error muestran una ruta local, el README y el código no coinciden en el plazo, y algunos detalles de Windows son más
toscos que en macOS. Cada elemento dice dónde está en el código y qué tan seguros estamos. Esta guía no arregla nada:
cada elemento es un límite del comportamiento de hoy, escrito.

| # | Límite | Dónde | Estado |
|---|---|---|---|
| 1 | Los rechazos del propio script llevan una ruta local en el error del cliente: la carpeta en `not enough free disk on <dir>`, el candado en `another recording is running (<lock>)` y el `.trace` en `no recording at <path>`; llegan al cliente por la última línea de stderr. Los mensajes de preflight y el «not an executable file» del script mantienen las rutas fuera (y una prueba lo dice), así que estas son las excepciones. Normalmente preflight rechaza primero, así que solo la carrera o un script lanzado a mano las muestran | `perf_record.sh:37`, `:48`, `:156`; `recording.py:424-425`; `tests/test_recording.py:565` | Confirmado por el código |
| 2 | `README.md` dice que la llamada vence «after 10 s per recorded second plus 120 s»; el código usa 15 s por segundo más 180 (55 con contadores) desde la 0.8.1 | `README.md:135-136`, `recording.py:266-269` | Confirmado: los dos difieren; cuál debe decir el README lo decide el dueño |
| 3 | La toma de un candado muerto en Windows no es atómica. El script de macOS toma un segundo candado mientras toma uno muerto; el motor de Windows quita el candado muerto y crea uno nuevo en dos pasos, así que dos procesos que ven el mismo dueño muerto pueden acabar teniéndolo ambos | `perf_record_windows.py:583-597` frente a `perf_record.sh:44-61` | Probable (leído del código; no reproducido: es una carrera). El hilo trabajador único lo hace improbable dentro de un servidor |
| 4 | El hash de PresentMon se comprueba al instalarlo, no al usarlo; un archivo nombrado por `PRESENTMON_EXE` o hallado en el `PATH` se ejecuta sin comprobar | `perf_record_windows.py:420-430`, `workloads.py:196-204` | Confirmado |
| 5 | Una grabación de Windows con la fuente `drawstress-log` deja `<run>.drawstress.log` (y `<run>.presentmon.csv` cuando corrió PresentMon) en disco: solo una corrida fallida los borra. La tabla de archivos de la [guía de datos](../datos-y-su-ciclo-de-vida/index.md) lista `.drawstress.log`, y la cuota ignora los dos | `perf_record_windows.py:632-633`, `:762-764`, `:937-941`; `retention.py:30-43` | Confirmado por el código; no reproducido |
| 6 | Cancelar una grabación de Windows espera primero a PresentMon: `presentmon_proc.wait(timeout=15)` corre antes de la rama de cancelar, así que una cancelación puede tardar hasta 15 s en actuar | `perf_record_windows.py:711-723`, `:726-746` | Probable |
| 7 | `perf_record` detiene **todos** los procesos con el nombre del programa al terminar o cancelarse, no solo el que arrancó: una segunda copia del mismo programa, como un editor que tenías abierto, también termina | `perf_record.sh:80`, `recording.py:255-263` | Confirmado; la descripción de la herramienta dice «every process named like the program» (`recording.py:42`) |
| 8 | El primer mensaje de progreso dice «up to N s including read-back» también en Windows, donde no hay lectura de vuelta | `recording.py:371-372` | Confirmado (cosmético) |
| 9 | En Windows nada rechaza un api que no puede correr allí (`mtl`, `vk`, `mtl-x64` son programas de macOS): `os.access(..., X_OK)` es true para cualquier archivo en Windows, así que preflight pasa y `Popen` falla | `workloads.py:88-89`, `preflight.py:117-119` | Probable: no reproducido |
| 10 | Las líneas de `.drawstress.log` son medias, así que una corrida de drawstress en Windows no tiene 1% low, tasa de stutter ni jitter | `perf_record_windows.py:859-862` | Confirmado (un límite de la fuente, no un error) |
| 11 | La fuente DWM mide el compositor de todo el escritorio, no el programa | `perf_record_windows.py:351-363`, `:819-829` | Confirmado |
| 12 | La caché de programas de prueba no tiene limpieza | `workloads.py:147-176` | Véase la [guía de datos](../datos-y-su-ciclo-de-vida/cache-y-candado.md#la-cache-no-son-las-grabaciones) |
| 13 | Cuánto dura el arranque de Wine, y por tanto si 30 s es el número correcto, no se midió aquí | `metal_trace_mcp.py:27` | No reproducido |
| 14 | Qué es VegaFlow no está documentado en las guías | `perf_record_windows.py:181-283` | Pendiente de confirmar |
