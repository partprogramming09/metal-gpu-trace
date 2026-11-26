"""Wine log census (release 0.33): what Wine says is missing or wrong, by message, and the longest silence between stamped lines."""
import json

import support  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import config, paths, winelog

GUID = "6f9619ff-8b86-d011-b42d-00c04fc964ff"


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


def census(folder, target=None, **kw):
    with Readable(folder):
        return winelog.tool_wine_log_census(str(target or folder), **kw)


def test_parse_reads_the_three_shapes_of_a_wine_line():
    assert winelog.parse("002c:fixme:channel:func text here") == ("fixme", "channel", "func text here", None)
    assert winelog.parse("0028:002c:err:d3d:fn Device error 0x887a0005") == ("err", "d3d", "fn Device error 0x887a0005", None)
    assert winelog.parse("12.345:0028:002c:warn:ntdll:fn something") == ("warn", "ntdll", "fn something", 12.345)
    assert winelog.parse("12.345:0028:002c:trace:loaddll:build_module Loaded L\"x\"") == (
        "trace", "loaddll", "build_module Loaded L\"x\"", 12.345)
    for other in ("warn:  a Mullion line", "plain text", "", "002c:debug:chan:fn x", "zzzz:fixme:chan:fn x"):
        assert winelog.parse(other) is None, other


def test_normalize_drops_numbers_addresses_guids_quoted_text_and_paths():
    text = f'Loaded L"C:\\\\users\\\\herda\\\\game.exe" at 0000000140000000 id {GUID} size 4096 from /Users/herda/x/y.dll ok'
    got = winelog.normalize(text)
    assert got == 'Loaded "S" at N id N size N from <path>', got
    for secret in ("herda", "game", "Users", "4096", "0000000140"):
        assert secret not in got
    assert winelog.normalize("x" * 500) == "x" * winelog.MAX_MESSAGE
    assert winelog.normalize("") == ""


def log(*lines):
    return "\n".join(lines) + "\n"


def test_messages_that_differ_only_in_numbers_are_one_message(tmp_path):
    (tmp_path / "a.log").write_text(log(
        "002c:fixme:d3d:fn 0x1234 not implemented", "002c:fixme:d3d:fn 0x9999 not implemented",
        "002c:fixme:d3d:fn 7 not implemented", "002c:err:ntdll:other Device error 0x887a0005", "plain text", "trace noise"))
    got = census(tmp_path)
    assert got["lines"] == 4 and got["by_level"] == {"fixme": 3, "err": 1}, got
    assert got["top"][0] == {"level": "fixme", "channel": "d3d", "message": "fn N not implemented", "count": 3}, got["top"]
    assert got["by_channel"] == {"d3d": 3, "ntdll": 1} and got["hresults"] == {"0x887a0005": 1}, got
    assert got["files"] == {"read": 1, "skipped": 0} and got["largest_gap"] is None, got


def test_top_limits_the_messages_and_orders_them_by_count_then_text(tmp_path):
    lines = [f"002c:warn:c{i}:fn message {'a' * i}" for i in range(1, 6)] + ["002c:warn:c1:fn message a"] * 4
    (tmp_path / "a.log").write_text(log(*lines))
    got = census(tmp_path, top=3)
    assert [g["count"] for g in got["top"]] == [5, 1, 1] and len(got["top"]) == 3, got["top"]
    for bad in (0, -1, True, "3", 1.5, 101):
        assert "top" in raises(lambda bad=bad: census(tmp_path, top=bad)), bad


def test_the_longest_silence_between_stamped_lines_names_both_sides_without_raw_text(tmp_path):
    (tmp_path / "a.log").write_text(log(
        "1.000:0028:002c:trace:loaddll:build_module Loaded L\"C:\\\\users\\\\herda\\\\a.dll\" at 00006FFF",
        "1.200:0028:002c:trace:process:fn start",
        "9.700:0028:002c:trace:loaddll:fn finally loaded 55",
        "9.800:0028:002c:trace:process:fn end"))
    got = census(tmp_path)["largest_gap"]
    assert got == {"seconds": 8.5, "file": 1, "before": "process:fn start", "after": "loaddll:fn finally loaded N"}, got
    assert "herda" not in json.dumps(census(tmp_path))


def test_a_gap_is_never_taken_across_two_files_and_unstamped_lines_do_not_count(tmp_path):
    (tmp_path / "a.log").write_text(log("1.000:0028:002c:trace:c:fn x", "1.100:0028:002c:trace:c:fn y"))
    (tmp_path / "b.log").write_text(log("50.000:0028:002c:trace:c:fn z", "50.050:0028:002c:trace:c:fn w", "0028:002c:err:c:fn q"))
    assert census(tmp_path)["largest_gap"]["seconds"] == 0.1


def test_the_census_reads_a_file_or_the_files_of_a_folder_and_skips_what_it_cannot(tmp_path):
    (tmp_path / "a.log").write_text(log("002c:fixme:c:fn one"))
    (tmp_path / "b.txt").write_text(log("002c:fixme:c:fn one"))
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.log").write_text(log("002c:fixme:c:fn one"))
    outside = tmp_path.parent / (tmp_path.name + "-out")
    outside.mkdir()
    (outside / "secret.log").write_text(log("002c:fixme:c:fn secret"))
    (tmp_path / "link.log").symlink_to(outside / "secret.log")
    (tmp_path / "big.log").write_bytes(b"x" * (winelog.MAX_FILE_BYTES + 1))
    got = census(tmp_path)
    assert got["by_level"] == {"fixme": 2} and got["files"] == {"read": 2, "skipped": 1}, got
    assert census(tmp_path, tmp_path / "a.log")["lines"] == 1


def test_paths_outside_the_readable_folders_and_empty_folders_are_refused(tmp_path):
    inside, outside = tmp_path / "in", tmp_path / "out"
    inside.mkdir(), outside.mkdir()
    (outside / "a.log").write_text(log("002c:fixme:c:fn one"))
    with Readable(inside):
        assert raises(lambda: winelog.tool_wine_log_census(str(outside)))
        assert "no log files" in raises(lambda: winelog.tool_wine_log_census(str(inside)))
        assert raises(lambda: winelog.tool_wine_log_census(str(inside / "missing.log")))
    for i in range(winelog.MAX_FILES + 1):
        (inside / f"{i:03d}.log").write_text("x")
    with Readable(inside):
        assert "at most" in raises(lambda: winelog.tool_wine_log_census(str(inside)))


def test_a_flood_of_distinct_messages_is_capped_and_says_so(tmp_path):
    (tmp_path / "a.log").write_text(log(*[f"002c:warn:c:fn word{'x' * (i % 40)}{chr(97 + i % 26)}{chr(97 + i // 26 % 26)}{chr(97 + i // 676)}"
                                           for i in range(winelog.MAX_GROUPS + 50)]))
    got = census(tmp_path)
    assert got["groups_truncated"] is True and got["lines"] == winelog.MAX_GROUPS + 50, got["lines"]


def test_the_answer_names_no_folder_and_keeps_no_raw_line(tmp_path):
    (tmp_path / "a.log").write_text(log('002c:err:c:fn failed for L"C:\\\\users\\\\herda\\\\x" and /Users/herda/y', "plain secret herda"))
    text = json.dumps(census(tmp_path))
    assert str(tmp_path) not in text and "herda" not in text and "secret" not in text, text


def test_a_hostile_line_of_quotes_is_cut_and_does_not_stall_the_scan(tmp_path):
    import time
    (tmp_path / "a.log").write_text(log("002c:warn:c:fn " + '"' * 400_000, "002c:warn:c:fn " + 'L"\\' * 100_000, "002c:fixme:c:fn ok"))
    start = time.monotonic()
    got = census(tmp_path)
    assert time.monotonic() - start < 5 and got["by_level"] == {"warn": 2, "fixme": 1}, got


def test_unclosed_quotes_are_linear_and_closed_ones_still_collapse():
    import time
    start = time.monotonic()
    for _ in range(200):
        winelog.normalize('x ' + '"\\' * 1000)
    assert time.monotonic() - start < 1
    assert winelog.unquote('a "b c" d L"e\\"f" g "open') == 'a "S" d "S" g "open'


def test_the_gap_names_the_file_by_position_and_hostile_logs_keep_counters_bounded(tmp_path):
    (tmp_path / "alice-macbook.log").write_text(log("1.000:0028:002c:trace:c:fn x", "4.000:0028:002c:trace:c:fn y"))
    got = census(tmp_path)
    assert got["largest_gap"]["file"] == 1 and "alice" not in json.dumps(got), got
    (tmp_path / "alice-macbook.log").write_text(log(*[f"002c:warn:chan{i}:fn m 0x8{i:07x}" for i in range(winelog.MAX_KEYS + 50)]))
    got = census(tmp_path)
    assert got["lines"] == winelog.MAX_KEYS + 50 and got["by_channel"].get("other") == 50, got["by_channel"]


def test_a_path_with_spaces_is_hidden_to_the_end_of_the_line():
    assert winelog.normalize("Cannot open /Users/Mary Ann") == "Cannot open <path>"
    assert winelog.normalize("Cannot open C:\\Users\\Mary Ann\\x.dll now") == "Cannot open <path>"


def test_gaps_are_positive_and_finite_and_a_non_finite_stamp_is_not_a_line(tmp_path):
    assert winelog.parse("1" + "0" * 400 + ".000:0024:002c:err:x:f a") is None
    (tmp_path / "a.log").write_text(log("5.000:0024:002c:err:x:f a", "2.000:0024:002c:err:x:f b", "2.500:0024:002c:err:x:f c"))
    got = census(tmp_path)["largest_gap"]
    assert got["seconds"] == 0.5, got
    (tmp_path / "a.log").write_text(log("5.000:0024:002c:err:x:f a", "2.000:0024:002c:err:x:f b"))
    assert census(tmp_path)["largest_gap"] is None
    json.dumps(census(tmp_path), allow_nan=False)


def test_a_bad_path_argument_is_a_tool_error(tmp_path):
    with Readable(tmp_path):
        for bad in ("a\0b", 5, None):
            assert raises(lambda bad=bad: winelog.tool_wine_log_census(bad)), bad
