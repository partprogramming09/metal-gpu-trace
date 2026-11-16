# La caché y el candado

**Lector:** personas que se preguntan qué hay en la carpeta de caché o cómo se evita que dos grabaciones corran a la vez. Revisado el 2026-11-16.

English: [The cache and the lock](../../../guides/data-and-lifecycle/cache-and-lock.md)

> **En corto:** la carpeta de caché no es donde van las grabaciones: guarda los programas de prueba que descarga la
> herramienta, y nada la limpia nunca. El candado es una carpeta que dice «hay una grabación en marcha», para que dos
> programas no compartan la GPU y estropeen los números del otro. Una grabación que muere deja un candado caducado que
> la siguiente toma por encima.

Volver al [índice](./index.md). Ejemplo: en esta máquina la caché pesa 942 MiB en 8 carpetas y no aparece ningún
`recording.lock`, que es el estado normal entre grabaciones ([E8](./evidencia-cache-y-flujo.md#e8-la-cache-y-el-candado)).

## La caché no son las grabaciones

`~/Library/Caches/metal-gpu-trace` guarda **los programas de prueba que descarga `workload_fetch`**, no grabaciones.
Cada carpeta se llama `<workload>-<primeros 12 caracteres del SHA-256 fijado>` (`workloads.py:22`), se descarga una vez
en una carpeta temporal dentro de la caché, se verifica y se renombra a su sitio (`workloads.py:156-175`). Las llamadas
posteriores la reutilizan (`workloads.py:154-155`).

| Hecho | Valor | Evidencia |
|---|---|---|
| Tamaño de la caché aquí | 942 MiB en 8 carpetas | [E8](./evidencia-cache-y-flujo.md#e8-la-cache-y-el-candado) |
| Versiones fijadas por `data/workloads.json` | 3 | [E9](./evidencia-cache-y-flujo.md#e9-las-versiones-que-fija-el-paquete) |
| Carpetas de versiones fijadas antiguas que nadie usa | 5 de 8: 63 + 65 + 79 + 78 + 23 = 308 MiB | E8, E9 |
| Código que borra una carpeta de la caché | ninguno: el `rg` de `rmtree` y `unlink` solo encuentra el `part.unlink()` del zip desempaquetado en `workloads.py:173` | [E10](./evidencia-cache-y-flujo.md#e10-nada-borra-una-carpeta-de-la-cache) |

Así que la caché solo crece cuando una versión nueva cambia un valor fijado (confirmado, con el límite de que la
búsqueda cubre `workloads.py` y no se sabe de otros módulos que borren ahí). Nada la limpia: borra una carpeta a mano y
se vuelve a descargar cuando haga falta (límite conocido 3).

## El candado

Una grabación a la vez, vaya a la carpeta que vaya: dos programas que comparten la GPU estropean las dos mediciones
(`perf_record.sh:40`). El candado es una **carpeta** (`mkdir` es atómico: o la crea o falla) llamada `recording.lock`
en la caché, con un archivo `pid` dentro que guarda el id de proceso de su dueño.

| Paso | Qué pasa | Dónde |
|---|---|---|
| Tomarlo | `mkdir $lock`; si falla y el dueño está muerto (`ps -p`), lo toma por encima con un segundo candado (`$lock.takeover`) para que dos grabaciones que encuentren el mismo candado muerto no puedan tomarlo las dos; si el dueño está vivo sale con el código 3 y el mensaje `another recording is running`; después `echo $$ > $lock/pid` | `perf_record.sh:52-62`, `:44-61`, `:47-50`, `:62` |
| Comprobarlo sin tomarlo | `preflight.check` rechaza antes de empezar nada cuando el candado nombra un proceso vivo; `lock_owner_alive` lee como mucho 32 bytes del archivo `pid`, nunca a través de un enlace, y trata un dueño ausente, raro o muerto como que no hay grabación. `recording.finish` usa la misma comprobación para no podar mientras otra grabación escribe en la carpeta | `preflight.py:135-137`, `:74-94`; `recording.py:346` |
| Soltarlo | La trampa `EXIT` del script lo borra; el servidor lo borra si mató el script al cancelar o por tiempo agotado (`recording.free_lock`), y solo si el archivo `pid` aún guarda el pid del propio script, así que nunca borra el candado de otra grabación | `perf_record.sh:65-73`; `recording.py:326-335`, llamada en `:404` |
| Windows | `perf_record_windows.py` tiene su propia versión de la misma idea: crea el candado con `mkdir`, escribe el `pid`, toma por encima uno caducado una vez y lo suelta en `finally` | `perf_record_windows.py:574-597`, `:942-946` |

Ahora mismo la caché no tiene ningún candado (E8: nada llamado `recording.lock`), que es el estado esperado entre
grabaciones. Un candado tomado **no se reprodujo**: tenerlo tomado significa estar grabando.
