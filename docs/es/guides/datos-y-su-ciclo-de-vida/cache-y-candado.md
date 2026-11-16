# La caché y el candado

**Lector:** personas que se preguntan qué hay en la carpeta de caché o cómo se evita que dos grabaciones corran a la vez. Revisado el 2026-11-16.

English: [The cache and the lock](../../../guides/data-and-lifecycle/cache-and-lock.md)

> **En corto:** la carpeta de caché no es donde van las grabaciones: guarda los programas de prueba que descarga la
> herramienta, y nada la limpia nunca. El candado es una carpeta que dice «hay una grabación en curso», para que dos
> programas no compartan la GPU y estropeen los números del otro. Una grabación que muere deja un candado viejo que la siguiente toma.

Volver al [índice](./index.md). Ejemplo: aquí la caché pesa 942 MiB en 8 carpetas y no aparece ningún `recording.lock`, el estado normal entre grabaciones ([E8](./evidencia-cache-y-flujo.md#e8-la-cache-y-el-candado)).

## La caché no son las grabaciones

`~/Library/Caches/metal-gpu-trace` guarda **los programas de prueba que descarga `workload_fetch`**. Cada carpeta se llama `<workload>-<primeros 12 caracteres del SHA-256 fijado>` (`workloads.py:22`), se descarga una vez a una carpeta temporal dentro de la caché, se verifica y se renombra a su sitio (`workloads.py:156-175`); las llamadas siguientes la reutilizan (`workloads.py:154-155`).

| Dato | Valor | Evidencia |
|---|---|---|
| Tamaño de la caché aquí | 942 MiB en 8 carpetas | [E8](./evidencia-cache-y-flujo.md#e8-la-cache-y-el-candado) |
| Versiones fijadas por `data/workloads.json` | 3 | [E9](./evidencia-cache-y-flujo.md#e9-las-versiones-que-fija-el-paquete) |
| Carpetas de versiones fijadas antiguas que nada usa | 5 de 8: 63 + 65 + 79 + 78 + 23 = 308 MiB | E8, E9 |
| Código que borra una carpeta de la caché | ninguno: `rg` de `rmtree` y `unlink` solo halla el `part.unlink()` del desempaquetado en `workloads.py:173` | [E10](./evidencia-cache-y-flujo.md#e10-nada-borra-una-carpeta-de-la-cache) |

Así que la caché solo crece cuando una versión nueva cambia un pin (confirmado; la búsqueda cubre `workloads.py`, no se sabe que otros módulos borren ahí). Si borras una carpeta a mano, se vuelve a descargar (límite conocido 3).

## El candado

Una grabación a la vez, sea cual sea la carpeta de cada una (`perf_record.sh:40`). El candado es una **carpeta** (`mkdir` es atómico: la crea o falla) llamada `recording.lock` en la caché, con un archivo `pid` que guarda el id de proceso del dueño.

| Paso | Qué pasa | Dónde |
|---|---|---|
| Tomarlo | `mkdir $lock`; si falla y el dueño está muerto (`ps -p`), lo toma bajo un segundo candado (`$lock.takeover`) para que dos grabaciones que encuentran el mismo candado muerto no lo tomen ambas; si el dueño está vivo, sale con código 3 y `another recording is running`; luego `echo $$ > $lock/pid` | `perf_record.sh:52-62`, `:44-61`, `:47-50`, `:62` |
| Comprobarlo sin tomarlo | `preflight.check` rechaza cuando el candado nombra un proceso vivo; `lock_owner_alive` lee como mucho 32 bytes de `pid`, nunca a través de un enlace, y trata un dueño ausente, raro o muerto como no activo. `recording.finish` usa la misma comprobación para no podar mientras otra grabación escribe | `preflight.py:135-137`, `:74-94`; `recording.py:346` |
| Soltarlo | La trampa `EXIT` del script; el servidor al cancelar o por tiempo (`recording.free_lock`), solo si `pid` aún guarda el pid del propio script | `perf_record.sh:65-73`; `recording.py:326-335`, llamado en `:404` |
| Windows | `perf_record_windows.py`: `mkdir` del candado, escribe `pid`, toma uno viejo una vez, suelta en `finally` | `perf_record_windows.py:574-597`, `:942-946` |

La caché no tiene candado ahora (E8), lo esperado entre grabaciones. Un candado tomado **no se reprodujo**: tomarlo significa grabar.
