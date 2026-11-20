# Release proof

**Reader:** people

Every improvement of a release has a proof here: the command that was run, its real output, where and when. A release
(from 0.26.0 on) lists 1 to 5 improvements in the `CHANGELOG.md`, and each one links to its heading in
`docs/evidence/vX.Y.Z.md`. `tests/test_docs.py` fails the suite when the newest release does not follow this.

Runs that are not part of a release have their own page: [reference-runs-windows.md](reference-runs-windows.md).

## What a proof file holds

One `vX.Y.Z.md` per release, with one `##` heading per improvement:

```
## Thing 1 name

**Promise:** what the improvement does for the reader, in one sentence.
**Command:** the exact command or tool call.
**Output:** the real output, trimmed (no absolute paths, no machine names, no user names).
**Where and when:** platform, chip, macOS and Xcode versions, date.
**Not tested:** what this run did not cover. Say "nothing" only if it is true.
```

An improvement that was not proven end to end ships marked 🧪 (experimental), says what was not tested, still links
its proof file, and does not count toward the minimum of 1 (it counts toward the maximum of 5).

## The CHANGELOG line

Only bullets under `### Added` count. One bullet per improvement: its icon, a short title, one or two sentences, and the link.

```
- 🔍 `capture_diff`: compares two captures call by call. [proof](docs/evidence/v0.26.0.md#capture_diff-compares-two-captures)
```

Icons: ✨ new · 🔍 analysis · 🩺 diagnosis · ⚡ speed · 🛡️ safety · ⚠️ incompatible · 🧪 experimental · 🛠️ fix.

## The README

The README gets a "What's new" section when a release ships: one row per improvement, each with its icon, title,
one or two sentences and a link to its heading here (`docs/evidence/vX.Y.Z.md#anchor`).
