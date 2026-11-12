# Golden files

**Lector:** personas

These files record what the project does today, so a refactor can prove it changed nothing by accident.

| File | Recorded by | What it pins |
|---|---|---|
| `protocol.json` | `test_golden_protocol` | The server's replies to a fixed list of MCP messages (`GOLDEN_MESSAGES`); the version is replaced by `<version>` |
| `metrics.json` | `test_golden_metrics` | What `perf_report` (key `mac`) and `perf_record_windows` (key `windows`) compute from fixed inputs, plus `frame_pacing` and `attribute_hitches` (`mac_only`) |

A test fails when the output differs. When the difference is intended:

1. Re-record: `METAL_TRACE_GOLDEN=write python3 -I tests/run.py`.
2. Read the diff of the JSON file and check that only the intended values moved.
3. Name the change in `CHANGELOG.md`.

Known difference between the Mac and Windows copies when recorded (2026-11-11): with no encoders, `short_share` is `{}` on Mac and holds every cut at `0.0` on Windows. With no GPU intervals, Windows also returns `gaps_over_1ms: 0` and `idle_share: null`. `public_arguments` in `perf_report` cuts only paths that start with `/`, so a Wine program's `C:\…` argument stays whole; the Windows copy cuts it only when it runs on Windows. That case is left out of the file because it depends on the platform.
