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

The `mac` and `windows` keys hold the same numbers: since 0.23.0 both come from one copy in `metrics.py`, and `test_metrics_schema_is_shared` checks that. The keys stay apart so a future copy shows up as a diff here.
