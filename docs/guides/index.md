---
title: What this is about
description: What metal-gpu-trace is, who it is for and how it is used, in plain words.
---

# What this is about

## In one sentence
metal-gpu-trace measures how hard a program works the graphics chip (the GPU) of a Mac with Apple silicon, and whether its pictures come out evenly.

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
- [How it works](./how-it-works): how the modules are layered and how one request flows through them.
- [Run from a clone](./run-from-a-clone): run and test the code without PyPI.
- [Data and its lifecycle](./data-and-lifecycle): what a recording leaves on disk, where it lives, how the summary is
  built key by key, and which of `KEEP_RUNS` and `METAL_TRACE_MAX_DISK_MB` deletes what. Español:
  [Datos y su ciclo de vida](../es/guides/datos-y-su-ciclo-de-vida).

## Words used here
The full glossary (frame, FPS, hitch, encoder, baseline, regression and more) is in the [README](https://github.com/partprogramming09/metal-gpu-trace#words-used-here).
