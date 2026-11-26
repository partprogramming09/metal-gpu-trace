"""Screenshot review (release 0.33): black, flat, frozen and flickering captures, read with a PNG reader of the standard library."""
import json
import struct
import zlib

import support  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import config, paths, screenshots


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def predicted(kind, line, prev, i, channels):
    a = line[i - channels] if i >= channels else 0
    b = prev[i]
    c = prev[i - channels] if i >= channels else 0
    if kind == 1:
        return a
    if kind == 2:
        return b
    if kind == 3:
        return (a + b) // 2
    if kind == 4:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else b if pb <= pc else c
    return 0


def png(width, height, pixel, channels=3, kinds=(0,), depth=8, color=None, interlace=0, filter_byte=None):
    """Returns a PNG whose pixel (x, y) is the tuple `pixel(x, y)`; row y uses filter kinds[y % len(kinds)]."""
    color = color if color is not None else (2 if channels == 3 else 6)
    raw, prev = bytearray(), bytearray(width * channels)
    for y in range(height):
        line = bytearray(v for x in range(width) for v in (pixel(x, y) + (255,))[:channels])
        kind = kinds[y % len(kinds)]
        raw.append(kind if filter_byte is None else filter_byte)
        raw += bytes((line[i] - predicted(kind, line, prev, i, channels)) & 255 for i in range(len(line)))
        prev = line
    header = struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")


def scene(seed):
    """A busy picture: stripes and a gradient that move with `seed`."""
    return lambda x, y: ((x * 7 + seed * 40) % 256, (y * 5 + seed * 90) % 256, ((x + y) * 3) % 256)


def write(folder, name, data):
    (folder / name).write_bytes(data)


def raises(call):
    try:
        call()
    except paths.ToolError as error:
        return str(error)
    raise AssertionError("no ToolError")


class Readable:
    """Makes `folder` a readable directory for the tool, as METAL_TRACE_READ would."""
    def __init__(self, folder):
        self.folder = folder

    def __enter__(self):
        self.saved = config.READ
        config.READ = [self.folder.resolve()]

    def __exit__(self, *exc):
        config.READ = self.saved


def test_the_reader_decodes_every_filter_and_both_channel_counts():
    for channels in (3, 4):
        data = png(20, 12, scene(1), channels=channels, kinds=(0, 1, 2, 3, 4))
        width, height, got, rows = screenshots.decode(data)
        assert (width, height, got) == (20, 12, channels), (width, height, got)
        for y in range(12):
            expected = bytes(v for x in range(20) for v in (scene(1)(x, y) + (255,))[:channels])
            assert bytes(rows[y]) == expected, (channels, y)


def test_a_black_a_flat_and_a_busy_frame(tmp_path):
    write(tmp_path, "a.png", png(64, 48, lambda x, y: (0, 0, 0)))
    write(tmp_path, "b.png", png(64, 48, lambda x, y: (120, 130, 140)))
    write(tmp_path, "c.png", png(64, 48, scene(1)))
    with Readable(tmp_path):
        got = screenshots.tool_screenshots_check(str(tmp_path))
    assert got["frames"] == 3 and got["ok"] is False, got
    assert got["findings"] == [{"file": "a.png", "problem": "black"}, {"file": "b.png", "problem": "uniform"}], got


def test_a_nearly_flat_frame_with_a_small_object_is_not_flat(tmp_path):
    write(tmp_path, "a.png", png(100, 100, lambda x, y: (200, 0, 0) if x < 8 and y < 8 else (10, 10, 10)))
    with Readable(tmp_path):
        got = screenshots.tool_screenshots_check(str(tmp_path / "a.png"))
    assert got == {"frames": 1, "ok": True, "findings": []}, got


def test_a_sequence_is_frozen_after_three_identical_frames(tmp_path):
    for i, seed in enumerate([1, 2, 3, 3, 3, 3, 4]):
        write(tmp_path, f"f{i:02d}.png", png(48, 32, scene(seed)))
    with Readable(tmp_path):
        got = screenshots.tool_screenshots_check(str(tmp_path), sequence=True)
        alone = screenshots.tool_screenshots_check(str(tmp_path))
    assert [f for f in got["findings"] if f["problem"] == "frozen"] == [{"file": "f02.png", "problem": "frozen"}], got
    assert alone["findings"] == [], "without sequence each frame stands alone"


def test_a_sequence_flickers_when_a_frame_differs_from_neighbours_that_match(tmp_path):
    for i, seed in enumerate([1, 1, 2, 1, 1]):
        write(tmp_path, f"f{i}.png", png(48, 32, scene(seed)))
    with Readable(tmp_path):
        got = screenshots.tool_screenshots_check(str(tmp_path), sequence=True)
    assert got["findings"] == [{"file": "f2.png", "problem": "flicker"}], got


def test_a_changing_clock_can_be_ignored_so_a_frozen_picture_is_seen(tmp_path):
    for i in range(4):
        write(tmp_path, f"f{i}.png", png(80, 60, lambda x, y, i=i: (255, 255, 255) if x < 40 and y < 30 and (x + i) % 2 else scene(1)(x, y)))
    with Readable(tmp_path):
        busy = screenshots.tool_screenshots_check(str(tmp_path), sequence=True)
        ignored = screenshots.tool_screenshots_check(str(tmp_path), sequence=True, ignore_rects=[[0, 0, 0.5, 0.5]])
    assert not any(f["problem"] == "frozen" for f in busy["findings"]), busy
    assert [f["problem"] for f in ignored["findings"]] == ["frozen"], ignored


def test_frames_sort_by_number_not_by_text(tmp_path):
    """Shots 2, 9 and 10 are the same picture and 11 is another: in name order as text (10, 11, 2, 9) they never are
    three in a row, in the order they were taken they are, from shot-2."""
    for n, seed in ((2, 1), (9, 1), (10, 1), (11, 2)):
        write(tmp_path, f"shot-{n}.png", png(40, 30, scene(seed)))
    with Readable(tmp_path):
        got = screenshots.tool_screenshots_check(str(tmp_path), sequence=True)
    assert got["findings"] == [{"file": "shot-2.png", "problem": "frozen"}], got


def test_ignore_rects_are_checked(tmp_path):
    write(tmp_path, "a.png", png(10, 10, scene(1)))
    with Readable(tmp_path):
        for bad in ("x", [[0, 0, 1]], [[0, 0, 1, "1"]], [[0, 0, 1.5, 1]], [[0.5, 0, 0.5, 1]], [[0, 0, float("nan"), 1]],
                    [[0, 0, True, 1]], [[0, 0, 10**400, 1]], [[0, 0, 1, 1]] * 9, [[-0.1, 0, 1, 1]]):
            assert "ignore_rects" in raises(lambda bad=bad: screenshots.tool_screenshots_check(str(tmp_path), ignore_rects=bad)), bad
        full = screenshots.tool_screenshots_check(str(tmp_path), ignore_rects=[[0, 0, 1, 1]])
    assert full["findings"] == [{"file": "a.png", "problem": "nothing_to_check"}], "a rect over everything leaves nothing"


def test_bad_pngs_are_refused_with_the_file_name_and_never_a_folder(tmp_path):
    cases = {"text.png": b"not a png at all", "short.png": png(10, 10, scene(1))[:60],
             "deep.png": png(8, 8, lambda x, y: (0, 0, 0), depth=16, color=2),
             "palette.png": png(8, 8, lambda x, y: (0, 0), channels=1, color=3),
             "lace.png": png(8, 8, scene(1), interlace=1),
             "filter.png": png(8, 8, scene(1), filter_byte=9)}
    with Readable(tmp_path):
        for name, data in cases.items():
            write(tmp_path, name, data)
            message = raises(lambda name=name: screenshots.tool_screenshots_check(str(tmp_path / name)))
            assert name in message and str(tmp_path) not in message, (name, message)
            (tmp_path / name).unlink()


def test_a_decompression_bomb_and_a_huge_picture_are_refused_before_they_are_expanded(tmp_path):
    huge = png(8, 8, lambda x, y: (0, 0, 0))
    header = struct.pack(">IIBBBBB", 30000, 30000, 8, 2, 0, 0, 0)
    bomb = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(1 << 20))) + chunk(b"IEND", b""))
    lie = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(bytes(64 << 20))) + chunk(b"IEND", b"")
    del huge
    for name, data in (("big.png", bomb), ("lie.png", lie)):
        write(tmp_path, name, data)
        with Readable(tmp_path):
            assert name in raises(lambda name=name: screenshots.tool_screenshots_check(str(tmp_path / name)))


def test_the_tool_reads_only_readable_folders_and_no_links(tmp_path):
    inside, outside = tmp_path / "in", tmp_path / "out"
    inside.mkdir(), outside.mkdir()
    write(outside, "a.png", png(10, 10, scene(1)))
    (inside / "link.png").symlink_to(outside / "a.png")
    with Readable(inside):
        assert raises(lambda: screenshots.tool_screenshots_check(str(outside)))
        assert raises(lambda: screenshots.tool_screenshots_check(str(inside / "link.png")))
        assert "no PNG" in raises(lambda: screenshots.tool_screenshots_check(str(inside)))
        assert raises(lambda: screenshots.tool_screenshots_check(str(inside / "missing.png")))


def test_too_many_frames_and_mixed_sizes_in_a_sequence_are_refused(tmp_path):
    write(tmp_path, "a.png", png(10, 10, scene(1)))
    write(tmp_path, "b.png", png(12, 10, scene(1)))
    with Readable(tmp_path):
        assert "size" in raises(lambda: screenshots.tool_screenshots_check(str(tmp_path), sequence=True))
        assert screenshots.tool_screenshots_check(str(tmp_path))["frames"] == 2, "alone, sizes may differ"
    many = tmp_path / "many"
    many.mkdir()
    for i in range(screenshots.MAX_FRAMES + 1):
        write(many, f"{i:03d}.png", b"x")
    with Readable(tmp_path):
        assert "at most" in raises(lambda: screenshots.tool_screenshots_check(str(many)))


def test_the_answer_names_no_folder(tmp_path):
    write(tmp_path, "a.png", png(10, 10, lambda x, y: (0, 0, 0)))
    with Readable(tmp_path):
        text = json.dumps(screenshots.tool_screenshots_check(str(tmp_path)))
    assert str(tmp_path) not in text and "/" not in text, text


def test_names_with_other_digits_sort_and_a_png_without_end_or_with_trailing_data_is_refused(tmp_path):
    good = png(8, 8, scene(1))
    write(tmp_path, "shot\u00b2.png", good)
    write(tmp_path, "shot-1.png", good)
    no_end = good[:-12]
    padded = good[:-12] + chunk(b"IEND", b"")
    write(tmp_path, "noend.png", no_end)
    with Readable(tmp_path):
        assert screenshots.tool_screenshots_check(str(tmp_path / "shot-1.png"))["frames"] == 1
        assert "noend.png" in raises(lambda: screenshots.tool_screenshots_check(str(tmp_path / "noend.png")))
        assert screenshots.tool_screenshots_check(str(tmp_path / "shot\u00b2.png"))["frames"] == 1
        assert screenshots.files_of(str(tmp_path))
    assert padded == good


def test_one_call_has_a_total_pixel_budget(tmp_path, monkeypatch=None):
    for i in range(3):
        write(tmp_path, f"a{i}.png", png(40, 30, scene(i)))
    saved = screenshots.MAX_TOTAL_PIXELS
    screenshots.MAX_TOTAL_PIXELS = 2000
    try:
        with Readable(tmp_path):
            assert "pixels" in raises(lambda: screenshots.tool_screenshots_check(str(tmp_path)))
    finally:
        screenshots.MAX_TOTAL_PIXELS = saved


def test_a_bad_path_argument_is_a_tool_error(tmp_path):
    with Readable(tmp_path):
        for bad in ("a\0b", 5, None):
            assert raises(lambda bad=bad: screenshots.tool_screenshots_check(bad)), bad
