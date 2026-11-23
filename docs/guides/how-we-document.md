---
title: How this project is documented
description: The documentation habits of metal-gpu-trace, which ones a test enforces, and how to copy them in another repository.
---

# How this project is documented

**Reader:** people who want to copy these habits into their own repository, and contributors who write docs here. Reviewed 2026-11-23.

**In short:** every claim has a reader, a date and a proof, and where a mistake is cheap to make a test catches it. Eight habits follow. The first four are checked by tests; the rest are kept by habit and review. Use it as a checklist.

## Checked by a test

| Habit | What it means | Where it is checked |
|---|---|---|
| **One proof per improvement** | Each release lists its improvements in the changelog. Each one ends with a link to a heading in `docs/evidence/vX.Y.Z.md` that holds the exact command, the real output, where and when it ran, and what was not tested. The README's "What's new" links the same proofs. | `tests/test_docs.py` (the release rule) |
| **Links that work** | A relative link in any `.md` file must point at a file that exists, spelled out with `.md`, so it works on GitHub and in the VitePress site. | `tests/test_docs.py` (relative links) |
| **The version is in one story** | The package version, `server.json` and the newest changelog section agree. | `tests/test_docs.py` |
| **Layers hold** | The architecture guide lists which module may import which; the test fails on a wrong import. | `tests/test_architecture.py` |

## Kept by habit

| Habit | What it means |
|---|---|
| **A reader line** | Every page starts with `**Reader:**`, naming who it is for (people, or a more specific reader). The page is written for that reader only. |
| **A review date** | `Reviewed YYYY-MM-DD` says when someone last checked the page against the code. Update it when you change the code the page describes. |
| **Evidence labels** | A technical claim is **confirmed** (checked with a command, today), **probable** (read in code, not run) or **speculation**. A fact from outside the repository that was not checked is marked **not verified**. Never state a number you did not measure. |
| **Names, not line numbers** | Cite a function or a test by name: names stay, line numbers drift. [HTTP in detail](./server-and-transport/http.md) is the model. |

## Layers of reading

A newcomer should never face the whole folder at once:

1. The [README](https://github.com/partprogramming09/metal-gpu-trace#readme): what it is, four steps, a glossary of every term.
2. [Using it](./using-it.md): typical jobs, each with the sentence to tell the agent.
3. [Where to start](../README.md#where-to-start): what to read as a user, an AI agent or a contributor.
4. The guides: how each part works, for people who change it.
5. Architecture decision records in `docs/adr/`: why each choice was made, with its status.
6. `docs/evidence/`: the proof behind each release.

## Rules that keep it honest

- Write for a stranger: no personal tool, machine name, user name or absolute path. Where an internal tool is named, say what it is and that it is not needed ([example](../evidence/internal-tools.md)).
- Do not delete technical content when you tidy: move it, summarize it or link it.
- A change with no code (docs, wording) needs no pull request; a change to the summary contract, release facts or security does.
- Say what you did not test. A proof with "Not tested: nothing" must mean it.

## Copying this

Copy the habits, not the files: a reader line, a date, a proof per release, labels, and one test for links. The release-proof test in `tests/test_docs.py` is a small, self-contained example to adapt. [Proof rules](../evidence/README.md) shows the page format.
