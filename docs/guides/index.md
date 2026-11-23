---
title: What this is about
description: What metal-gpu-trace is, who it is for and how it is used, in plain words.
---

# What this is about

**Reader:** anyone arriving at the project: what it is, who it is for, and which guide to read next. Reviewed 2026-11-16.

**In short:** metal-gpu-trace measures how hard a program works the graphics chip of a Mac and whether its pictures come out evenly; each guide below explains one part.

## In one sentence
metal-gpu-trace measures how hard a program works the graphics chip (the GPU) of a Mac with Apple silicon, and whether its pictures come out evenly.

## Install it in one command
`uvx metal-gpu-trace init` adds the server to the AI apps it finds (Claude Code, Claude Desktop, Cursor, Codex CLI) with the absolute path of `uvx`, and never overwrites your other servers (a `.bak` copy is made first). `--dry-run` shows what it would write; `--client` names one app; `--wine DIR` sets the Wine directory; `--project` writes the project's own file instead (it holds paths of this machine: keep it out of git). The README has the details.

## What problem it solves
People who port or test games and apps on a Mac, Windows games run through Wine included, need numbers, not impressions, to know whether a change made the program faster. This tool has Instruments (Apple's profiler, installed with Xcode) record the program and hands back a short summary; run it again after a change and it says whether the program got faster, slower or stayed the same. It does not fix the program, and it needs Xcode to record.

## How it is used, with an example
You ask your AI agent: "Record my app for 30 seconds, then tell me its FPS and how long the GPU takes per frame." The agent calls the server, which records, and answers with frames per second, the GPU time per frame, how often the picture stutters and how much memory was used. After a change you ask for the same recording and a comparison. Repeat a run before calling a difference real.

## The main pieces

| Piece | What it is | What it is for |
|---|---|---|
| MCP server | A small helper program that gives an AI agent new tools | Receives the agent's requests over stdio or HTTP |
| Recording | `perf_record` and its scripts, driving Instruments | Produces a `.trace` and a short summary |
| Summary and analysis | `perf_report`, `analysis` | Turns a `.trace` into numbers and compares two runs |
| `.gputrace` reader | `gputrace_read` | Reads a Metal capture of a few frames without Xcode |
| Project file | `metal-gpu-trace.json` | Names the project and the folder of its recordings |

## What to know before touching it
- Summaries are shared: no machine name, UUID or absolute path may appear in them or in the repository.
- Standard library only, Python 3.9 or newer; scripts run with `python3 -I`.
- One recording at a time; under Wine record 30 s or more; compare recordings of 100 frames or more.
- A locked Mac session leaves native windows unpaced: record unlocked.

## Guides
- [Using it](./using-it.md): "I installed it, now what?" Five typical jobs, each with the sentence to say to your agent.
- [How it works](./how-it-works.md): how the modules are layered and how one request flows through them.
- [Run from a clone](./run-from-a-clone.md): run and test the code without PyPI.
- [How this project is documented](./how-we-document.md): the habits behind these pages, which ones a test checks, and how to copy them.
- [How it works](./how-it-works): how the modules are layered and how one request flows through them.
- [Run from a clone](./run-from-a-clone): run and test the code without PyPI.
- [Data and its lifecycle](./data-and-lifecycle/): what a recording leaves on disk, where it lives, how the summary is
  built key by key, and which of `KEEP_RUNS` and `METAL_TRACE_MAX_DISK_MB` deletes what.
- [Recording](./recording/): the whole path of a recording, why one runs at a time and 30 s or more under Wine, what
  `preflight` checks and what it says when it refuses, the test programs and their pinned downloads, the Windows engine,
  and what happens when a recording fails.
- [Summarizing and analyzing](./summarizing/): how a `.trace` becomes the summary (the tables read and what a missing one
  does), how FPS, the 1 % low, stutter and hitches are computed, what `perf_compare`, `perf_check` and `perf_gate` compare,
  the experiments, how better, worse and same are decided, and what happens when it fails.
- [Reading traces](./reading-traces/): the seven tools that read a `.trace` or a `.gputrace`, how the `trace` argument is
  read, windows and paging in `trace_query`, how a `.chrome-trace` is exported, what the code assumes about a capture,
  and what happens when it fails.
- [Server and transport](./server-and-transport/): how the server starts over stdio and HTTP, the tool registry, the
  worker, the HTTP checks (route, Host, Origin, token, size, JSON), the logs, and what happens when it fails.

## Words used here
The full glossary (frame, FPS, hitch, encoder, baseline, regression and more) is in the [README](https://github.com/partprogramming09/metal-gpu-trace#words-used-here).
