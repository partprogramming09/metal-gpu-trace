"""app_metrics: the optional telemetry file a recorded program writes (t_ms plus named numeric columns)."""
import os

from support import PKG  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import app_metrics, recording


def put(tmp_path, text, raw=None):
    path = tmp_path / "app.csv"
    path.write_bytes(raw if raw is not None else text.encode())
    return path


def test_summarises_each_column(tmp_path):
    block = app_metrics.read(put(tmp_path, "t_ms,vram_mb,uma_mb\n0,100,10\n1000,200,20\n2000,300,30\n"))
    assert block["samples"] == 3 and block["duration_ms"] == 2000
    assert block["comparable"] is False and block["source"] == "app-file"
    assert block["columns"]["vram_mb"] == {"count": 3, "mean": 200.0, "p50": 200.0, "p95": 300.0, "max": 300.0,
                                           "min": 100.0, "last": 300.0}


def test_missing_file_gives_no_block(tmp_path):
    assert app_metrics.read(tmp_path / "none.csv") is None


def test_empty_and_header_only_files_say_zero_samples(tmp_path):
    assert app_metrics.read(put(tmp_path, ""))["samples"] == 0
    assert app_metrics.read(put(tmp_path, "t_ms,a\n"))["samples"] == 0


def test_bom_crlf_nan_and_infinity(tmp_path):
    raw = b"\xef\xbb\xbft_ms,a\r\n0,1\r\n1,nan\r\n2,inf\r\n3,5\r\n"
    block = app_metrics.read(put(tmp_path, "", raw))
    assert block["samples"] == 4 and block["columns"]["a"]["count"] == 2 and block["issues"]["bad_cells"] == 2


def test_unordered_times_are_sorted_and_counted(tmp_path):
    block = app_metrics.read(put(tmp_path, "t_ms,a\n2000,3\n0,1\n1000,2\n"))
    assert block["duration_ms"] == 2000 and block["columns"]["a"]["last"] == 3.0 and block["issues"]["out_of_order_rows"] == 1


def test_repeated_column_keeps_the_first(tmp_path):
    block = app_metrics.read(put(tmp_path, "t_ms,a,a\n0,1,9\n1,3,9\n"))
    assert block["columns"]["a"]["max"] == 3.0 and block["issues"]["ignored_columns"] == ["a"]


def test_wrong_header_or_row_shape(tmp_path):
    assert app_metrics.read(put(tmp_path, "time,a\n0,1\n"))["issues"]["header"] == "first column must be t_ms"
    block = app_metrics.read(put(tmp_path, "t_ms,a\n0,1\n1\n2,x,y\n3,4\n"))
    assert block["samples"] == 2 and block["issues"]["dropped_rows"] == 2


def test_bad_column_names_and_column_cap(tmp_path):
    assert "a b" not in app_metrics.read(put(tmp_path, "t_ms,a b,c\n0,1,2\n"))["columns"]
    header = ",".join(["t_ms"] + [f"c{i}" for i in range(40)])
    assert len(app_metrics.read(put(tmp_path, header + "\n" + ",".join(["0"] * 41) + "\n"))["columns"]) == app_metrics.MAX_COLUMNS


def test_huge_file_is_cut_at_the_limit(tmp_path, monkeypatch=None):
    old = app_metrics.MAX_BYTES
    app_metrics.MAX_BYTES = 200
    try:
        text = "t_ms,a\n" + "".join(f"{i},1\n" for i in range(500))
        block = app_metrics.read(put(tmp_path, text))
    finally:
        app_metrics.MAX_BYTES = old
    assert block["truncated"] is True and 0 < block["samples"] < 500


def test_symlink_and_directory_are_not_read(tmp_path):
    real = put(tmp_path, "t_ms,a\n0,1\n")
    link = tmp_path / "link.csv"
    os.symlink(real, link)
    assert app_metrics.read(link) is None and app_metrics.read(tmp_path) is None


def test_path_for_avoids_spaces(tmp_path):
    spaced = tmp_path / "a b"
    spaced.mkdir()
    assert app_metrics.path_for([spaced, tmp_path]).parent.parent == tmp_path
    assert app_metrics.path_for([spaced]) is None


def test_finish_adds_the_block_when_the_program_wrote_a_file(tmp_path):
    path = put(tmp_path, "t_ms,a\n0,1\n1000,2\n")
    assert recording.finish({}, tmp_path / "r.json", None, None, app_file=path)["app_metrics"]["samples"] == 2
    assert "app_metrics" not in recording.finish({}, tmp_path / "s.json", None, None, app_file=tmp_path / "no.csv")


def test_record_run_hands_over_the_path_and_always_removes_it(tmp_path):
    seen = {}

    def fake(label, seconds, wine, prefix, workdir, command, program_env, app_file=None, **options):
        seen.update(env=program_env, file=app_file)
        assert app_file.parent.is_dir() and f"{app_metrics.ENV}={app_file}" in program_env
        raise RuntimeError("stop")

    old = recording.run_recording
    recording.run_recording = fake
    try:
        recording.record_run("x", 5, "native", "-", "-", ["p"], "A=1")
    except RuntimeError:
        pass
    finally:
        recording.run_recording = old
    assert seen["env"].startswith("A=1 ") and not seen["file"].parent.exists()


def test_a_huge_cell_is_one_bad_cell(tmp_path):
    block = app_metrics.read(put(tmp_path, "", b"t_ms,a\n0,1\n1," + b"9" * 200000 + b"\n2,3\n"))
    assert block["samples"] == 3 and block["issues"]["bad_cells"] == 1


def test_absurd_times_keep_every_number_finite(tmp_path):
    block = app_metrics.read(put(tmp_path, "t_ms,a\n1e308,1\n-1e308,2\n0,3\n"))
    assert block["samples"] == 1 and block["issues"]["dropped_rows"] == 2 and block["duration_ms"] == 0


def test_blank_first_line_and_quotes_do_not_hide_rows(tmp_path):
    assert app_metrics.read(put(tmp_path, "\r\n\r\n"))["samples"] == 0
    assert app_metrics.read(put(tmp_path, "\nt_ms,a\n0,1\n"))["samples"] == 1
    assert app_metrics.read(put(tmp_path, 't_ms,a\n0,1\n1,"2\n2,3\n3,4\n'))["samples"] == 4


def test_only_plain_ascii_numbers_count(tmp_path):
    block = app_metrics.read(put(tmp_path, "t_ms,a\n0,1_0\n1,٣\n2,5\n"))
    assert block["columns"]["a"]["count"] == 1 and block["issues"]["bad_cells"] == 2
