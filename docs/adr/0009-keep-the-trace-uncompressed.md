# ADR-0009: Keep the `.trace` uncompressed

**Reader:** people

- **Status:** accepted
- **Date:** 2026-11-17
- **Decided by:** the maintainer (to be confirmed: the owner has not yet approved this record)

## Context
A recording's `.trace` is the largest file it leaves. The summary is kept, and the `.trace` is deleted unless `KEEP_TRACE=1`
is set. [ADR-0006](0006-compressed-tables-and-disk-quota.md) compresses the per-frame tables and sets a disk limit
(`METAL_TRACE_MAX_DISK_MB`) that removes the `.trace` files first. The open question was whether the `.trace` itself
should be compressed, with the standard library's `lzma`, so more of them fit under the limit.

The measurement, on 2026-11-17 on one Mac: a copy of one `.trace` of 269.3 MB, three runs per setting.

| Setting | Size | Saved | Compress | Decompress |
|---|---|---|---|---|
| `lzma` preset 1 | 142.9 MB (ratio 0.53) | 47% | 19.7 to 26.9 s | 5.4 to 5.8 s |
| `lzma` preset 6 | 124.9 MB (ratio 0.46) | 54% | 88.6 to 100.5 s | 5.0 to 5.6 s |

The bar was written before the measurement: save at least half, compress in under 20 s and decompress in under 10 s per
200 MB of trace (for this 269.3 MB file, about 27 s and 13 s). Neither setting meets all three. Preset 1 saves less than
half. Preset 6 takes more than three times the compress bar. The measurement ran while another recording was in progress,
so the times are upper bounds.
(Evidence: the command and its raw output are not in this record yet; evidence pending.)

## Decision
- Do not compress the `.trace`. It is written and kept as before, with no new step in a recording.
- The disk limit of [ADR-0006](0006-compressed-tables-and-disk-quota.md) stays as it is: it removes `.trace` files first.

## Alternatives considered
| Option | For | Against | Why yes / no |
|---|---|---|---|
| Keep the `.trace` as it is (chosen) | no time added to a recording; nothing new to read | a kept `.trace` takes its full size | Yes |
| `lzma` preset 1 | fastest compression | saves 47%, under the half the bar asks | No |
| `lzma` preset 6 | saves 54% | 88.6 to 100.5 s to compress, over three times the bar | No |

## Consequences
- **Positive:** no change to the code or to how long a recording takes.
- **Negative / cost:** with `KEEP_TRACE=1`, each `.trace` takes its full size on disk, and a quota removes these files first.

## Revisit when
A repeat measurement on an idle Mac gives other times, or the quota removes `.trace` files that people still need to open.
