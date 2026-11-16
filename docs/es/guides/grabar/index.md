# Grabar

**Lector:** personas que cambian cómo se hace una grabación (`recording.py`, `preflight.py`, `workloads.py`, los dos scripts de grabación y los archivos de `data/`), o que necesitan saber por qué una grabación fue rechazada, detenida o volvió vacía. Revisado el 2026-11-16.

English: [Recording](../../../guides/recording/index.md)

**En corto:** cuando un agente pide grabar un programa, el servidor primero revisa el ordenador en milisegundos, luego
arranca un script que corre la herramienta Instruments de Apple sobre el programa, espera, convierte la captura cruda en
un resumen pequeño y borra la captura cruda. Si algo falla, o el cliente cancela, no queda ningún archivo. En Windows un
motor aparte mide cuándo se mostraron los fotogramas. Esta guía está partida por temas; empieza por el ejemplo de abajo.

Esta guía sigue una grabación desde la petición del agente hasta que se devuelve el resumen. No repite
[How it works](../../../guides/how-it-works.md) (qué capa llama a cuál) ni
[Datos y su ciclo de vida](../datos-y-su-ciclo-de-vida/index.md) (qué archivos deja una grabación, la vida del candado, los
ajustes de retención); los enlaza. Es la versión en español de la guía en inglés: mismo contenido, mismos diagramas y la
misma evidencia (los comandos y sus salidas no se traducen, ni los mensajes de error del programa).

## Las páginas

| Página | Qué contiene |
|---|---|
| [El recorrido en macOS](./recorrido-macos.md) | La petición se vuelve un comando, el envoltorio, el entorno del script, el bucle de vigilancia, la secuencia de cierre forzado, qué identifica una corrida |
| [Preflight](./preflight.md) | Las seis comprobaciones y cada mensaje, lo que preflight no comprueba, lo que repite cada capa |
| [Dos reglas](./reglas.md) | Una grabación a la vez; por qué 30 segundos o más bajo Wine |
| [Los programas de prueba](./programas-de-prueba.md) | La lista, cómo una petición se vuelve un comando, cómo se verifica una descarga, las versiones fijadas, PresentMon |
| [El motor de Windows](./motor-windows.md) | Por qué un motor aparte, las tres fuentes de fotogramas, paso a paso, qué cambia respecto de macOS |
| [Los archivos de datos](./archivos-de-datos.md) | El archivo de familias de GPU y el de programas de prueba |
| [Cuando falla](./fallos.md) | Lo que recibe el cliente en cada fallo; tocarlo sin romperlo |
| [Límites conocidos](./limites.md) | 14 límites del comportamiento de hoy, escritos y no arreglados |
| [Evidencia](./evidencia.md), [Evidencia: datos](./evidencia-datos.md) | Los comandos (E1 a E10) y su salida real; lo que no se reprodujo |

## Cómo leer las etiquetas

Cada afirmación técnica es **confirmada** (con `archivo:línea`, comprobada con `rg` o `sed` el 2026-11-16 contra el árbol
de trabajo, que es la 0.27.2 más las entradas `[Unreleased]` de `CHANGELOG.md`), **probable** (leída en el código pero no
ejecutada aquí) o **especulación** (una conjetura sobre el porqué). **No verificado** marca un dato de fuera que no se
comparó con su fuente. Las líneas se mueven cuando cambia el código: busca el nombre, no solo el número. Cada cifra viene
con el comando que la produjo, en las páginas de evidencia. **No reproducido** significa que el comportamiento no se pudo
ejecutar para esta guía: no se hizo ninguna grabación (hace falta Instruments, una máquina Windows y minutos de GPU) y la
sesión que la escribió solo podía correr comandos de lectura, así que tampoco se corrió ninguna comprobación en vivo; se
nombran en su lugar las pruebas que fijan cada comportamiento, y **no se ejecutaron** para esta guía.

## Un ejemplo primero

Supón que un agente le pide al servidor que grabe un programa de Windows bajo Wine durante 30 segundos:

```text
perf_record label=mygame program=~/Games/mygame.exe wine=~/wine seconds=30
```

Qué pasa, en el orden en que pasa:

| # | Quién | Qué | Línea |
|---|---|---|---|
| 1 | Servidor | Revisa la petición: el nivel (tier), las palancas, los pares de entorno, que el programa exista, y luego la etiqueta. Todavía no ha empezado nada | `recording.py:48-70`, `:312` |
| 2 | **Preflight** | ¿Hay Wine?, ¿está instalado `xcrun`?, ¿hay sitio en el disco?, ¿está desbloqueada la pantalla?, ¿hay otra grabación en marcha? Para 30 segundos pide `2 + (30 × 8 + 9) / 10 = 26` GB libres ([E3](./evidencia.md)). Si algo falla la llamada termina con una frase que dice qué hacer, y no se arrancó ningún proceso | `preflight.py` |
| 3 | Servidor | Arranca `perf_record.sh` en su propio grupo de procesos y le dice al cliente el peor caso: «recording: up to 630 s including read-back» (15 s por cada segundo grabado más 180). Después mira cada segundo el reloj y la señal de cancelar del cliente | `recording.py:371-372`, `:394-421` |
| 4 | Script | Toma el candado, arranca Instruments sobre el programa y dos muestreadores pequeños, espera 30 s, corre el informe y borra el `.trace` crudo (la [Figura 2 de la guía de datos](../datos-y-su-ciclo-de-vida/de-grabacion-a-disco.md#de-una-grabacion-a-disco)) | `perf_record.sh` |
| 5 | Servidor | Lee el resumen que escribió el informe, añade lo que solo él sabe (la capa de traducción, de dónde salió el código, el tier) y responde con él | `recording.py:437` |

La respuesta es el mismo resumen que leen todas las demás herramientas. Cancelar en cualquier momento, o pasar de 630 s,
mata todo y no deja ningún archivo.

## Por qué la grabación tiene esta forma

| Decisión | Por qué | Alternativas descartadas |
|---|---|---|
| Revisar todo primero en el servidor (`preflight`), en milisegundos | Una grabación de Wine D3D12 que falla tarde ya gastó hasta 630 s y gigabytes de disco temporal. Cada rechazo dice cómo arreglarlo (`preflight.py:1-3`, el docstring del propio módulo). El script repite las comprobaciones de programa, disco y candado como «defensa en profundidad» (`preflight.py:1-3`) | Solo las comprobaciones del script: sus fallos llegan al cliente como `recording failed (exit N): <última línea de stderr>` (`recording.py:425`) y algunos llevan una ruta local ([límite 1](./limites.md)) |
| Un script de zsh maneja Instruments; Python maneja el script | El script es lo que puede morir: su trampa `EXIT` quita el candado, los muestreadores y los archivos a medias se acabe como se acabe (`perf_record.sh:65-73`). El servidor sigue vivo, mata el grupo de procesos del script al cancelar y limpia lo que dejó (`recording.py:396-413`) | Python llamando a `xctrace` directamente: **especulación** de que se dejó fuera porque la limpieza tiene forma de shell (bucles en segundo plano, trampas); ningún ADR registra la elección |
| Una grabación a la vez, con una carpeta-candado | Dos programas que comparten la GPU estropean las dos mediciones (`perf_record.sh:40`). Véase [Dos reglas](./reglas.md) | Fiarse solo del hilo trabajador: serializa las llamadas de un solo servidor (`worker.py:1`), no dos servidores ni un script lanzado a mano |
| Un plazo de 15 s por segundo grabado más 180 s | Cerrar y leer de vuelta un trace de Wine D3D12 es lento: una grabación de 30 s produjo un trace de 614 MB que tardó minutos en cerrarse y 93 s en leerse, y pasó el límite anterior (`CHANGELOG.md`, 0.8.1). Los contadores lo suben a 55 s por segundo (`recording.py:266-269`) | Un límite fijo: el primero (420 s) perdió una grabación real |
| Cancelar y pasarse del plazo matan el grupo de procesos, luego el programa, y borran los archivos nuevos | Una grabación a medias es peor que ninguna: aparecería listada como una corrida. El programa se detiene por nombre porque un juego que atrapa `SIGTERM` siguió corriendo 40 minutos (`recording.py:255-258`) | Dejar los archivos parciales a las reglas de retención: saldrían en `perf_runs` |
| Un motor aparte para Windows | Windows no tiene Instruments ni `xctrace`. El motor mide con PresentMon, o con el compositor del escritorio cuando falta PresentMon, y escribe la misma forma de resumen con código compartido en `metrics.py` (`perf_record_windows.py:24-28`) | Un solo motor con `if`: el camino de macOS es un script de shell, así que no hay nada que compartir salvo el resumen |
| Programas de prueba fijados por SHA-256 y construidos por el workflow de este proyecto | Un programa descargado se ejecuta, así que importan los bytes exactos; la construcción se reproduce desde el código fuente (`data/workloads.json`: «built from source by .github/workflows/workloads.yml») | Descargar binarios de los autores directamente: los editores de Godot son la excepción, y están fijados por SHA-512 (`workloads.py:166-171`) |
| Las familias de GPU y los programas de prueba viven en archivos JSON de `data/` | Los hechos cambian más rápido que el código: un chip nuevo o un programa nuevo es una edición de datos con su prueba, no un cambio de lógica. Ambos se leen una vez al importar (`config.py:35-36`) | Constantes en Python: **especulación**; ningún ADR registra la elección |

## Las piezas y dónde viven

| Pieza | Archivo | Qué hace | Página |
|---|---|---|---|
| Las herramientas | `recording.py` (`tool_perf_record` `:36`, `tool_perf_attach` `:91`) | Revisan la petición, arman el comando, llaman a `record` | [Recorrido](./recorrido-macos.md) |
| El envoltorio del servidor | `recording.py` (`record` `:309`, `record_run` `:354`, `finish` `:337`) | Preflight, presión de memoria, arrancar el script, vigilarlo, limpiar, terminar el resumen | [Recorrido](./recorrido-macos.md) |
| Lo que identifica una corrida | `recording.py` (`layer_of` `:127`, `run_context` `:168`) | La huella de la capa de traducción y de dónde salió el código | [Recorrido](./recorrido-macos.md) |
| Las comprobaciones | `preflight.py` | Lo que necesita una grabación, rechazado en milisegundos | [Preflight](./preflight.md) |
| El grabador de macOS | `perf_record.sh` | Candado, muestreadores, `xctrace`, informe, limpieza | [Recorrido](./recorrido-macos.md) |
| El grabador de Windows | `perf_record_windows.py` | Toda la grabación de Windows; también se puede lanzar a mano | [Motor de Windows](./motor-windows.md) |
| Los programas de prueba | `workloads.py`, `data/workloads.json` | La lista, la descarga, los hashes fijados, PresentMon | [Programas de prueba](./programas-de-prueba.md) |
| Los datos de GPU | `data/apple-gpu-families.json` | La grabación no lo usa; lo lee `gpu_family` | [Archivos de datos](./archivos-de-datos.md) |

## Véase también

- [How it works](../../../guides/how-it-works.md): las capas y el recorrido de una petición.
- [Datos y su ciclo de vida](../datos-y-su-ciclo-de-vida/index.md): los archivos que deja una grabación, el candado y los dos
  ajustes de retención.
- [Prueba de la 0.27.0](../../../evidence/v0.27.0.md#the-runs-folder-compressed-tables-and-a-size-limit): el límite de tamaño medido.
