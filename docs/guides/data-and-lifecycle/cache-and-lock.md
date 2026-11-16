# The cache and the lock

**Reader:** people who wonder what is in the cache folder, or how two recordings are kept from running together. Reviewed 2026-11-16.

Español: [La caché y el candado](../../es/guides/datos-y-su-ciclo-de-vida/cache-y-candado.md)

> **In short:** the cache folder is not where recordings go: it holds the test programs the tool downloads, and nothing
> ever cleans it. The lock is a folder that says "a recording is running", so two programs never share the GPU and spoil
> each other's numbers. A recording that dies leaves a stale lock that the next one takes over.

Back to the [index](./index.md). Example: on this machine the cache weighs 942 MiB in 8 folders and no
`recording.lock` is listed, which is the normal state between recordings ([E8](./evidence-cache-and-flow.md#e8-the-cache-and-the-lock)).

## The cache is not the recordings

`~/Library/Caches/metal-gpu-trace` holds **the test programs that `workload_fetch` downloads**, not recordings. Each
folder is named `<workload>-<first 12 characters of the pinned SHA-256>` (`workloads.py:22`), is downloaded once into a
temporary folder inside the cache, verified, and renamed into place (`workloads.py:156-175`). Later calls reuse it
(`workloads.py:154-155`).

| Fact | Value | Evidence |
|---|---|---|
| Size of the cache here | 942 MiB in 8 folders | [E8](./evidence-cache-and-flow.md#e8-the-cache-and-the-lock) |
| Versions pinned by `data/workloads.json` | 3 | [E9](./evidence-cache-and-flow.md#e9-the-versions-the-package-pins) |
| Folders of older pinned versions that nothing uses | 5 of 8: 63 + 65 + 79 + 78 + 23 = 308 MiB | E8, E9 |
| Code that deletes a cache folder | none: `rg` of `rmtree` and `unlink` finds only the unpacked `part.unlink()` at `workloads.py:173` | [E10](./evidence-cache-and-flow.md#e10-nothing-deletes-a-cache-folder) |

So the cache only grows when a new release changes a pin (confirmed, with the limit that the search covers
`workloads.py` and the other modules are not known to delete there). Nothing cleans it: delete a folder by hand, it is
downloaded again when needed (known limit 3).

## The lock

One recording at a time, whatever folder each goes to: two programs sharing the GPU spoil both measurements
(`perf_record.sh:40`). The lock is a **folder** (`mkdir` is atomic: it either creates it or fails) named
`recording.lock` in the cache, with a file `pid` inside that holds the owner's process id.

| Step | What happens | Where |
|---|---|---|
| Taking it | `mkdir $lock`; if that fails and the owner is dead (`ps -p`), it takes the lock over under a second lock (`$lock.takeover`) so two recordings that find the same dead lock cannot both take it; if the owner is alive it exits with code 3 and the message `another recording is running`; then `echo $$ > $lock/pid` | `perf_record.sh:52-62`, `:44-61`, `:47-50`, `:62` |
| Checking it without taking it | `preflight.check` refuses before anything starts when the lock names a live process; `lock_owner_alive` reads at most 32 bytes of the `pid` file, never through a link, and treats a missing, odd or dead owner as not running. `recording.finish` uses the same check so it never prunes while another recording writes into the folder | `preflight.py:135-137`, `:74-94`; `recording.py:346` |
| Releasing it | The script's `EXIT` trap removes it; the server removes it if it killed the script on cancel or timeout (`recording.free_lock`), and only if the `pid` file still holds the script's own pid, so it never removes another recording's lock | `perf_record.sh:65-73`; `recording.py:326-335`, called at `:404` |
| Windows | `perf_record_windows.py` has its own version of the same idea: `mkdir` the lock, write the `pid`, take over a stale one once, release in `finally` | `perf_record_windows.py:574-597`, `:942-946` |

Right now the cache holds no lock (E8: nothing named `recording.lock`), which is the expected state between recordings.
A held lock was **not reproduced**: holding it means recording.
