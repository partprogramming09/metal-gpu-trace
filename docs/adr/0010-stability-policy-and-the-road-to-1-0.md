# ADR-0010: Stability policy and the road to 1.0

**Reader:** people

- **Status:** proposed (draft: nothing in the code depends on it yet)
- **Date:** 2026-11-23
- **Decided by:** the owner (not yet decided)

## Context
The project is at 0.29.0. Its first tag, `v0.2.0`, dates from 2026-10-16 and `v0.29.0` from 2026-11-22: 47 tags in 37 days, one
maintainer. People who install it with `uvx metal-gpu-trace` get the newest version every time, so a
renamed argument or a moved key reaches them without notice.

Some rules already exist and are kept by tests and by the maintainer's own notes:
- An incompatible change is listed under `### Removed (incompatible)` in the `CHANGELOG.md`, with its reason.
- Existing summary keys do not move or change meaning; `perf_compare`, `perf_history` and `perf_runs` keep reading
  summaries of `schema_version` 1, 2 and 3.
- A metric that cannot be measured the same way on both platforms is `{"comparable": false, "reason": ...}`.

What is missing is a written statement of **what counts as the public surface** and **when 1.0 happens**, so a user can
tell a change they must react to from one they can ignore.

## Decision (proposed)
Take option A below: publish the surface and the rule in the README and keep this record as the long form.

## Alternatives considered
| Option | For | Against | Why yes / no |
|---|---|---|---|
| A. Stay in 0.x, but name the public surface and promise the rule for it (proposed) | cheap; tells users what to pin against; no big step for one maintainer | 0.x still allows breaking changes, so users must read the changelog | Yes |
| B. Declare 1.0 now, with the surface frozen | strongest signal to users | 47 tags in 37 days of history; a freeze this early means a 2.0 soon, or a surface kept too small | No, not yet |
| C. Say nothing (today) | no work | users cannot tell what is safe; the pin advice has no meaning | No |

**The public surface proposed for option A** (everything else is internal and may change in any release):
1. The names of the MCP tools and the names and meaning of their arguments (26 tools today).
2. The keys of a recording's summary JSON that the documentation lists in `docs/guides/data-and-lifecycle/json-keys.md`,
   and `schema_version`. A key added is not a break; a key removed, renamed or with another meaning is.
3. The `common` block of the summary, whose keys are defined in `docs/guides/`.
4. The verdict codes of `perf_diagnose` (`bottleneck` values such as `DISPLAY_SYNCED`), not their advice text.
5. The exit codes of `metal-gpu-trace check`: 0 same or improved, 1 regressed, 2 could not be judged.
6. The environment variables the README documents (`METAL_TRACE_OUT`, `PERF_MEMORY`, and so on).

Not in the surface: the wording of any message or recommendation, the order of keys, files that are not the summary
(CSVs, `.tables.sqlite`), the Python modules inside the package, and the scripts under `windows/`.

**The rule proposed:** while the version is 0.x, a change to the public surface that is not backward compatible ships in a
minor version (0.Y.0), never in a patch, and is listed under `### Removed (incompatible)` with a way to migrate. A patch
version (0.Y.Z) only fixes and adds.

**When to go to 1.0 (proposed bar, to be confirmed):** the surface above has gone unchanged in an incompatible way for
three minor versions in a row; the summary's `schema_version` has stayed at 3 through them; and a recording on each of
macOS and Windows has been checked by hand for every version of those three (see the checklist of real-hardware checks,
when it exists). The numbers (three versions) are a starting point, not a measurement.

## Consequences
- **Positive:** a user can pin against a stated surface; the maintainer has a short test for «is this a break?».
- **Negative / cost:** one more rule to follow in every release; the README must keep the install pin advice current.

## Revisit when
The owner decides, or a break reaches users who had no way to tell it was one.
