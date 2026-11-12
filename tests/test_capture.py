"""Tests of gputrace_read: reading a Metal .gputrace capture."""

from support import write_capture  # also puts src/ on sys.path
from metal_gpu_trace import gputrace_read  # noqa: E402


def test_capture(tmp_path):
    """A small MTSP stream is read record by record, and the summary names the capture without its path."""
    summary = gputrace_read.summarize(write_capture(tmp_path))
    assert summary["capture"] == "frame.gputrace" and summary["draw_primitives"] == 3, summary
