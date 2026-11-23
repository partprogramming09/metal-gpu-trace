# The `trace` argument and what a `.trace` is

**Reader:** people who call `trace_tables`, `trace_count` or `trace_query`, or who change how they find and open a trace. Reviewed 2026-11-16.

> **In short:** you name the recording by a short name, such as `a2-proof-first_20261115-085621`, or by a path. The server looks
> the name up in its runs folder and refuses anything outside the folders it may read. Then it asks Apple's `xctrace` for the
> contents, one table at a time. If the recording was already deleted you get a sentence saying so: the likeliest error here.

## How a `trace` argument is understood

The argument is described as "a run name from perf_runs whose trace_kept or tables_kept is true, or the path of a .trace" (`registry.py::TRACE`).
`paths.trace_path` (`paths.py::trace_path`) decides which:

| The text is... | It becomes | If it fails |
|---|---|---|
| a valid **name** (`name_ok`: letters, digits, `.`, `_`, `-`, at most 120 bytes; `paths.py::name_ok`) | `<runs folder>/<name>.trace` (a trailing `.trace` is accepted) | a link there: `<name>.trace cannot be read` (`paths.py::trace_path`) |
| anything else, a **path** | resolved by `allowed` (`paths.py::allowed`); inside the runs folder or a folder in `METAL_TRACE_READ` | `<name> is outside the readable directories; add its directory to METAL_TRACE_READ` (`paths.py::allowed`) |

Consequence (**confirmed**, **not run**): `foo.trace` has no `/`, so it is a run name looked up in the runs folder. A `.trace`
elsewhere needs a path with a directory (`./foo.trace`, or an absolute path inside `METAL_TRACE_READ`). The folder must exist:
`export` raises `no recording at <name>: perf_record.sh deletes the .trace once its summary is written, unless KEEP_TRACE=1`
(`perf_report.py::export`), which the three table tools turn into `no recording at <name>.trace and no <name>.tables.sqlite: ...`
(`traces.missing`). When the `.trace` is gone but the run's [tables file](tables-file.md) exists, they read that instead.

## What a `.trace` looks like from here

A `.trace` is a **bundle**: a folder Instruments writes and `xctrace` reads. This project never opens its insides; it asks
`xctrace` for two things (**confirmed**, `perf_report.py::export`):

| Ask | Command | What comes back |
|---|---|---|
| The **table of contents** | `xcrun xctrace export --input <trace> --output <temporary.xml> --toc` | XML with root `trace-toc`, `run` elements (the code always reads `run number="1"`, `perf_report.py::table_xpath`), each with a `data` element holding one `table` per table; `schema` is the table's name (`traces.py::source_of`, `traces.py::tool_trace_query`) |
| One **table** | the same with `--xpath '/trace-toc/run[@number="1"]/data/table[@schema="<name>"]'` instead of `--toc` | XML with a `schema` listing the columns (each `col` has a `mnemonic`, the column name) and one `row` per row, cells being children named after the columns (`perf_report.py:143-179`; fixture `tests/test_traces.py::table`) |

- Cells hold the value as text and often a `fmt` attribute with the formatted version (`traces.py::windows_of`).
- To keep a big table small, `xctrace` writes a repeated value once with an `id` and later cells point to it with `ref`; `rows`
  resolves them while reading (`perf_report.py:131-170`; [summarizing guide](../summarizing/trace-to-summary.md#step-1-export)).
- The table names are Instruments' own; this project does not list them: they are what `trace_tables` returns.

**One measurement of a real recording.** An 8-second recording of a test program at the `deep` tier (2026-11-15, Apple M1 Pro,
`xctrace` 27.2) exported **85 tables**, 59 with rows and 26 empty (E8; internal research note, not published; **not reproduced
here**). The summary reads the handful that matter ([table of tables](../summarizing/trace-to-summary.md#step-2-the-table-of-contents-and-missing_tables));
the rest are for `trace_query`.

Next: [`trace_tables` and `trace_count`](./trace-tables-count.md). Back to the [index](./index.md).
