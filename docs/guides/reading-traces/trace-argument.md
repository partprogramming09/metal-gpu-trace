# The `trace` argument and what a `.trace` is

**Reader:** people who call `trace_tables`, `trace_count` or `trace_query`, or who change how they find and open a trace. Reviewed 2026-11-16.

Español: [El argumento `trace`](../../es/guides/leer-trazas/argumento-trace.md)

> **In short:** you tell the three tools which recording to open by a short name, such as `a2-proof-first_20261115-085621`,
> or by a path. The server looks the name up in its own runs folder and refuses anything outside the folders it may read.
> Then it asks Apple's `xctrace` program for the contents, one table at a time. If the recording was already deleted, you get
> a sentence saying so: it is the most likely error of the whole guide.

## How a `trace` argument is understood

The argument of all three tools is described as "a run name from perf_runs whose trace_kept is true, or the path of a .trace"
(`registry.py:20`). `paths.trace_path` (`:83-91`) decides which:

| The text is... | It becomes | If it fails |
|---|---|---|
| a valid **name** (`name_ok`: letters, digits, `.`, `_`, `-`, at most 120 bytes; `paths.py:25-30`) | `<runs folder>/<name>.trace` (a trailing `.trace` on the name is accepted) | a link at that place: `<name>.trace cannot be read` (`:88-89`) |
| anything else, a **path** | resolved by `allowed` (`:91`); it must lie inside the runs folder or a folder in `METAL_TRACE_READ` | `<name> is outside the readable directories; add its directory to METAL_TRACE_READ` (`paths.py:20-21`) |

A consequence (**confirmed** from the code, **not run**): `foo.trace` has no `/`, so it counts as a run name and is looked up
in the runs folder. A `.trace` that lives elsewhere needs a path with a directory in it (for example `./foo.trace`, or an
absolute path inside `METAL_TRACE_READ`).

The folder must exist as a directory: `export` checks first and raises `no recording at <name>: perf_record.sh deletes the
.trace once its summary is written, unless KEEP_TRACE=1` (`perf_report.py:52-54`). That is what a client sees for a trace
that was already deleted.

## What a `.trace` looks like from here

A `.trace` is a **bundle**: a folder Instruments writes and `xctrace` reads. This project never opens its insides; it asks
`xctrace` for two things (**confirmed**, `perf_report.py:49-66`):

| Ask | Command | What comes back |
|---|---|---|
| The **table of contents** | `xcrun xctrace export --input <trace> --output <temporary.xml> --toc` | XML with root `trace-toc`, `run` elements (the code always reads `run number="1"`, `perf_report.py:92`), each with a `data` element holding one `table` per table; the `schema` attribute is the table's name (`traces.py:36`, `:100`) |
| One **table** | the same command with `--xpath '/trace-toc/run[@number="1"]/data/table[@schema="<name>"]'` instead of `--toc` | XML with a `schema` listing the columns (each `col` has a `mnemonic`, the column's name) and one `row` per row, whose cells are children named after the columns (`perf_report.py:143-179`; the shape is the fixture of `tests/test_traces.py:11-16`) |

- Cells carry the value as text and often a `fmt` attribute with the formatted version (`traces.py:111`).
- To keep a big table small, `xctrace` writes a repeated value once with an `id` and later cells point to it with `ref`;
  `rows` resolves those references while it reads (`perf_report.py:131-170`; see the
  [summarizing guide](../summarizing/trace-to-summary.md#step-1-export)).
- The names of the tables are Instruments' own and are not listed by this project: they are whatever `trace_tables`
  returns.

**One measurement of a real recording.** An 8-second recording of a test program at the `deep` tier, made on 2026-11-15 on
an Apple M1 Pro with `xctrace` 27.2, exported **85 tables**, 59 with rows and 26 empty (E8; the project's own research note of
that date, not published; **not reproduced here**). The summary reads the handful that matter
([the table of tables](../summarizing/trace-to-summary.md#step-2-the-table-of-contents-and-missing_tables)); the rest are there for
`trace_query`.

Next: [`trace_tables` and `trace_count`](./trace-tables-count.md). Back to the [index](./index.md).
