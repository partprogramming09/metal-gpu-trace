"""The one stderr log line per tool call."""
import os
import sys


def log(message):
    """Writes one line to stderr, the only log channel a stdio server may use."""
    if os.environ.get("METAL_TRACE_LOG") != "off":
        print(f"metal-trace: {message}", file=sys.stderr, flush=True)
