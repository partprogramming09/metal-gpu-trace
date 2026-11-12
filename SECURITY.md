# Security

**Reader:** anyone who finds a security problem in metal-gpu-trace.

## Reporting

Report it privately through GitHub's **private vulnerability reporting**: the repository's *Security* tab, then
*Report a vulnerability*. Please do not open a public issue. Say what you did, what happened and which version
(`metal-gpu-trace --version`) you ran.

## Supported versions

Only the latest release gets fixes.

## What counts

The server runs programs and reads files on the machine it runs on, so the boundaries are the ones to test:

- files are read only inside `METAL_TRACE_OUT` and the directories in `METAL_TRACE_READ`;
- the HTTP mode (`--http`) listens on 127.0.0.1 only, needs `METAL_TRACE_TOKEN`, and checks `Host` and `Origin`;
- summaries are meant to be shared: they must not hold host names, user names or absolute paths.
