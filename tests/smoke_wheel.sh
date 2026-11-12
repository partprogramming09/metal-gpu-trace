#!/bin/sh
# Builds and installs the wheel in a fresh venv, then checks --version and one initialize reply (needs uv).
# Usage: sh tests/smoke_wheel.sh [python]
set -eu
python=${1:-python3}
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
uv build --quiet --wheel --out-dir "$work/dist" "$root"
"$python" -m venv "$work/venv"
"$work/venv/bin/python" -m pip install --quiet --no-index "$work"/dist/*.whl
version=$("$work/venv/bin/metal-gpu-trace" --version)
case $version in
  "metal-gpu-trace "*) ;;
  *) echo "smoke: unexpected --version output: $version" >&2; exit 1 ;;
esac
reply=$(cd "$work" && printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
  | METAL_TRACE_OUT="$work/out" METAL_TRACE_LOG=off "$work/venv/bin/metal-gpu-trace")
case $reply in
  *'"protocolVersion": "2025-06-18"'*'"serverInfo"'*) ;;
  *) echo "smoke: unexpected initialize reply: $reply" >&2; exit 1 ;;
esac
echo "wheel ok ($version)"
