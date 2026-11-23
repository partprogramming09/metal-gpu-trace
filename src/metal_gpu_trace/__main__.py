"""Runs the MCP server: python -m metal_gpu_trace."""
import sys

from metal_gpu_trace.metal_trace_mcp import main

sys.exit(main())
