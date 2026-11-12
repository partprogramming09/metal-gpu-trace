# Contributing

**Reader:** anyone sending a change to metal-gpu-trace.

The code is standard-library Python 3.9 or newer in `src/metal_gpu_trace/`; the tests are in `tests/`.

## Checks

```sh
python3 -I tests/run.py                       # the self-check, prints ok; needs nothing installed
python -m pytest tests                        # the same tests, plus the Windows ones on Windows
uvx --python 3.13 --with mcp==2.3.0 --with pytest pytest tests/conformance   # the official MCP SDK as a client
sh tests/smoke_wheel.sh                       # builds, installs and starts the wheel (needs uv)
uvx ruff@0.14.0 check src tests               # the lint CI runs (settings in pyproject.toml)
```

Optional: a local hook that scans what you are about to commit for secrets with
[gitleaks](https://github.com/gitleaks/gitleaks). Put this in `.git/hooks/pre-commit` and make it executable:

```sh
#!/bin/sh
exec gitleaks git --pre-commit --staged --redact --no-banner
```

## Rules

- Every change comes with a test and a line in `CHANGELOG.md` under the version it ships in.
- Write the test first and see it fail.
- The golden files in `tests/golden/` pin the server's replies and the summary numbers. When a change moves them on
  purpose, follow `tests/golden/README.md` and name the change in the CHANGELOG.
- Modules import other package modules as modules (`from metal_gpu_trace import config`), never names from them;
  `tests/test_architecture.py` checks this and the layers listed in `docs/architecture.md`.
- Summaries are shared: no machine name, user name, UUID or absolute path in them or in the repository.
