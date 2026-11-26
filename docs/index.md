---
layout: home
hero:
  name: metal-gpu-trace
  text: See what the GPU did, with numbers
  tagline: Record Wine or macOS programs with Metal System Trace and read the recordings back
  actions:
    - theme: brand
      text: What this is about
      link: /guides/
features:
  - title: Guides
    details: What the project is, how it works and how to run it, explained without jargon.
  - title: Diagrams
    details: How a request flows through the server, drawn and exported as PNG.
  - title: Proof
    details: Every release lists the command that was run for each improvement and its real output, under docs/evidence.
---

## Where the project stands

Taken from the [changelog](https://github.com/partprogramming09/metal-gpu-trace/blob/main/CHANGELOG.md) and the proof
files of each release. Status as of 2026-11-16.

| | State | Source |
|---|---|---|
| Version | 0.32.0, 2026-11-26 | [changelog](https://github.com/partprogramming09/metal-gpu-trace/blob/main/CHANGELOG.md) |
| Works, run on a real recording (macOS, Apple M1 Pro) | How long the GPU takes to start, how many other processes load the GPU, what is still allocated at the end; since 0.27.0 also the refusal of a recording that cannot work, compressed tables with a size limit, a cheaper read of big tables, `tier`, next actions and cooldown | [0.27.2](evidence/v0.27.2.md), [0.27.0](evidence/v0.27.0.md) |
| Works, run on a real recording (macOS), 0.27.3 | The `common` block of `schema_version` 3, `perf_memory_breakdown`, the `perf_check` note for a one-run reference; links in the runs folder are no longer followed | [0.27.3](evidence/v0.27.3.md) |
| Works, run end to end on Windows | A published 0.27.2 installed and recorded a real run on one Windows PC | [0.27.2, Windows](evidence/v0.27.2.md) |
| Experimental | Shader register spills: no real recording had a spill event, so only tests with synthetic rows cover it | [0.27.2](evidence/v0.27.2.md) |
| Pending | A trace that really leaks; `perf_compare` on two real runs (tests only); a Windows recording longer than 8 s; the three improvements of 0.27.2 that read Metal tables do not exist on Windows | [0.27.2](evidence/v0.27.2.md) |

New here? Start with [What this is about](guides/index.md). To know what a recording leaves on disk, where and for how long,
read [Data and its lifecycle](guides/data-and-lifecycle/index.md).
