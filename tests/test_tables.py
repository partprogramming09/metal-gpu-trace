"""tables: the one place that reads and writes the per-frame and memory tables, plain `.csv` or `.csv.gz`."""
import csv

from support import PKG  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import tables

ROWS = [(1, 0.0, 4.0), (2, 16.5, 4.25), (3, 33.0, 5.0)]
HEADER = ["frame", "start_ms", "gpu_ms_total"]


def read_all(path):
    with tables.open_text(path) as f:
        return list(csv.DictReader(f))


def test_write_then_read_gz(tmp_path):
    path = tables.write(tmp_path, "r.frames", HEADER, ROWS)
    assert path.name == "r.frames.csv.gz"
    assert [r["start_ms"] for r in read_all(path)] == ["0.0", "16.5", "33.0"]


def test_write_plain_when_not_compressed(tmp_path):
    path = tables.write(tmp_path, "r.frames", HEADER, ROWS, compress=False)
    assert path.name == "r.frames.csv" and path.read_text().splitlines()[0] == "frame,start_ms,gpu_ms_total"
    assert len(read_all(path)) == 3


def test_find_prefers_gz_and_falls_back_to_csv(tmp_path):
    assert tables.find(tmp_path, "r.frames") is None
    (tmp_path / "r.frames.csv").write_text("frame\n1\n")
    assert tables.find(tmp_path, "r.frames").name == "r.frames.csv"
    tables.write(tmp_path, "r.frames", HEADER, ROWS)
    assert tables.find(tmp_path, "r.frames").name == "r.frames.csv.gz"


def test_write_is_deterministic(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    a = tables.write(tmp_path / "x", "r.frames", HEADER, ROWS).read_bytes()
    b = tables.write(tmp_path / "y", "r.frames", HEADER, ROWS).read_bytes()
    assert a == b


def test_truncated_gz_is_unreadable(tmp_path):
    path = tables.write(tmp_path, "r.frames", HEADER, [(i, i * 1.5, 4.0) for i in range(500)])
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    try:
        read_all(path)
    except tables.UNREADABLE:
        return
    raise AssertionError("a truncated gzip must raise something in tables.UNREADABLE")


def test_corrupt_and_not_gzip_are_unreadable(tmp_path):
    path = tables.write(tmp_path, "r.frames", HEADER, [(i, i * 1.5, 4.0) for i in range(500)])
    data = bytearray(path.read_bytes())
    for i in range(len(data) // 2, len(data) // 2 + 8):  # flipped bytes in the middle: zlib.error or a bad CRC
        data[i] ^= 0xFF
    path.write_bytes(bytes(data))
    plain = tmp_path / "n.frames.csv.gz"
    plain.write_text("frame,start_ms\n1,0\n")  # named .gz, but plain text
    for target in (path, plain):
        try:
            read_all(target)
        except tables.UNREADABLE:
            continue
        raise AssertionError(f"{target.name} must be unreadable")


def test_empty_gz_is_unreadable(tmp_path):
    path = tmp_path / "r.frames.csv.gz"
    path.write_bytes(b"")
    try:
        read_all(path)
    except tables.UNREADABLE:
        return
    raise AssertionError("a zero-byte .csv.gz is a recording cut short, not an empty table")


def test_write_does_not_follow_a_planted_link(tmp_path):
    """A link where a fixed temporary name used to be (a runs folder from a clone) is never written through."""
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    out = tmp_path / "runs"
    out.mkdir()
    for name in (".r.frames.csv.gz.tmp", "r.frames.csv.gz.tmp"):
        (out / name).symlink_to(outside)
    tables.write(out, "r.frames", HEADER, ROWS)
    assert outside.read_text() == "keep"


def test_write_leaves_no_temporary_file(tmp_path):
    path = tables.write(tmp_path, "r.frames", HEADER, ROWS)
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_failed_write_leaves_nothing(tmp_path):
    def rows():
        yield (1, 0.0, 4.0)
        raise RuntimeError("boom")

    try:
        tables.write(tmp_path, "r.frames", HEADER, rows())
    except RuntimeError:
        pass
    assert list(tmp_path.iterdir()) == []


def test_find_ignores_a_temporary_name(tmp_path):
    (tmp_path / "r.frames.csv.gz.abc123.tmp").write_bytes(b"x")
    assert tables.find(tmp_path, "r.frames") is None


def test_a_written_table_gets_the_mode_the_other_outputs_get(tmp_path):
    """mkstemp makes 0600; a table is read by whoever reads the summary beside it, so it follows the umask instead."""
    import os
    import sys
    if sys.platform == "win32":
        return
    old = os.umask(0o022)
    try:
        path = tables.write(tmp_path, "r.frames", ["a"], [[1]])
    finally:
        os.umask(old)
    assert oct(path.stat().st_mode & 0o777) == oct(0o644), oct(path.stat().st_mode & 0o777)
