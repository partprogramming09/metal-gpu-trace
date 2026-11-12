# ADR-0003: Python 3.9 is the floor

**Reader:** people

- **Status:** accepted
- **Date:** 2026-11-11
- **Decided by:** the maintainer

## Context
The tool runs on Macs that record games, often with nothing installed beyond what macOS ships. The `python3` that comes
with the Xcode Command Line Tools is 3.9. GitHub's `ubuntu-latest` (26.04) no longer has 3.9, so CI runs the 3.9 job on
`ubuntu-24.04`.

## Decision
Support Python 3.9 or newer with the standard library only. The code uses `from __future__ import annotations` for
`X | None` hints, avoids `match` and other 3.10+ syntax, and CI tests 3.9 and 3.13.

## Alternatives considered
| Option | For | Against | Why yes / no |
|---|---|---|---|
| 3.9 floor (chosen) | Runs with the Python macOS ships | No `match`, no 3.10+ stdlib helpers | Yes |
| 3.10 or newer | Newer syntax | Users must install Python first | No |

## Consequences
- **Positive:** `python3 -I src/metal_gpu_trace/metal_trace_mcp.py` works on a fresh Mac with the Command Line Tools.
- **Negative / cost:** a CI job pinned to an older runner image, which GitHub will retire some day.
- **Harder:** using a library feature added after 3.9 needs a fallback.

## Revisit when
macOS ships a newer `python3`, or GitHub retires its last runner image with 3.9.
