"""retention: keeping a runs folder under METAL_TRACE_MAX_DISK_MB by removing the heaviest, oldest files first."""
import os

import support  # noqa: F401  (puts src/ on sys.path)
from metal_gpu_trace import config, retention

MIB = 2**20


def put(out, name, size=0, age=0):
    """Writes `name` in `out` with `size` bytes and a modification time of `age` seconds after a fixed start."""
    path = out / name
    path.write_bytes(b"x" * size)
    os.utime(path, (1_000_000 + age, 1_000_000 + age))
    return path


def names(out):
    return sorted(p.name for p in out.iterdir())


def test_removes_oldest_trace_first(tmp_path):
    put(tmp_path, "a.trace", MIB, 0)
    put(tmp_path, "b.trace", MIB, 1)
    put(tmp_path, "cur.json", 10, 9)
    got = retention.prune_to_quota(tmp_path, 2, "cur")
    assert names(tmp_path) == ["b.trace", "cur.json"] and got["removed"] == 1 and got["trace_dropped"] is False, got


def prune_order(tmp_path, quota_mb):
    put(tmp_path, "old.frames.csv.gz", MIB, 0)  # the oldest, but a table goes last
    put(tmp_path, "old.chrome-trace", MIB, 1)
    put(tmp_path, "new.trace", MIB, 2)  # the newest, but a .trace goes first
    put(tmp_path, "cur.json", 10, 9)
    retention.prune_to_quota(tmp_path, quota_mb, "cur")
    return names(tmp_path)


def test_order_trace_then_chrome_trace_then_tables(tmp_path):
    # three 1 MiB files plus a few bytes of summary: each quota is just under what is left after the previous step
    for quota, left in ((3, ["cur.json", "old.chrome-trace", "old.frames.csv.gz"]),
                        (2, ["cur.json", "old.frames.csv.gz"]), (1, ["cur.json"])):
        folder = tmp_path / f"q{quota}"
        folder.mkdir()
        assert prune_order(folder, quota) == left, (quota, names(folder))


def test_never_removes_json_baselines_panel_or_samplers(tmp_path):
    for name in ("baselines.json", "panel.json", "x.json", "x.rss.csv", "x.agx.csv", "metal-gpu-trace.json"):
        put(tmp_path, name, MIB)
    put(tmp_path, "old.trace", MIB, 0)
    got = retention.prune_to_quota(tmp_path, 1, "cur")
    assert names(tmp_path) == ["baselines.json", "metal-gpu-trace.json", "panel.json", "x.agx.csv", "x.json", "x.rss.csv"], names(tmp_path)
    assert got["removed"] == 1


def test_protects_current_runs_tables(tmp_path):
    put(tmp_path, "cur.frames.csv.gz", 2 * MIB)
    put(tmp_path, "cur.metal_memory.csv.gz", MIB)
    put(tmp_path, "cur.json", 10)
    got = retention.prune_to_quota(tmp_path, 1, "cur")
    assert names(tmp_path) == ["cur.frames.csv.gz", "cur.json", "cur.metal_memory.csv.gz"], names(tmp_path)
    assert got == {"freed_mb": 0.0, "removed": 0, "trace_dropped": False}, got


def test_drops_current_trace_last_and_says_so(tmp_path):
    put(tmp_path, "old.trace", MIB, 0)
    put(tmp_path, "cur.trace", 2 * MIB, 5)
    put(tmp_path, "cur.frames.csv.gz", 100, 5)
    put(tmp_path, "cur.json", 10, 5)
    got = retention.prune_to_quota(tmp_path, 1, "cur")
    assert names(tmp_path) == ["cur.frames.csv.gz", "cur.json"], names(tmp_path)
    assert got["trace_dropped"] is True and got["removed"] == 2, got


def test_current_trace_stays_while_older_files_are_enough(tmp_path):
    put(tmp_path, "old.trace", 2 * MIB, 0)
    put(tmp_path, "cur.trace", MIB, 5)
    got = retention.prune_to_quota(tmp_path, 2, "cur")
    assert names(tmp_path) == ["cur.trace"] and got["trace_dropped"] is False, (names(tmp_path), got)


def test_fits_means_no_change(tmp_path):
    put(tmp_path, "a.trace", MIB)
    put(tmp_path, "cur.json", 10)
    assert retention.prune_to_quota(tmp_path, 5, "cur") == {"freed_mb": 0.0, "removed": 0, "trace_dropped": False}
    assert names(tmp_path) == ["a.trace", "cur.json"]


def test_counts_trace_folders_recursively(tmp_path):
    deep = tmp_path / "a.trace" / "sub" / "deeper"
    deep.mkdir(parents=True)
    (deep / "big.bin").write_bytes(b"x" * (2 * MIB))
    put(tmp_path, "cur.json", 10)
    got = retention.prune_to_quota(tmp_path, 1, "cur")
    assert names(tmp_path) == ["cur.json"] and got["freed_mb"] >= 2.0, got


def test_names_with_spaces_and_dots(tmp_path):
    put(tmp_path, "my run.v2.trace", MIB, 0)
    put(tmp_path, "my run.v2.frames.csv", MIB, 1)
    put(tmp_path, "cur.json", 10, 9)
    retention.prune_to_quota(tmp_path, 2, "cur")
    assert names(tmp_path) == ["cur.json", "my run.v2.frames.csv"], names(tmp_path)


def test_older_run_named_like_the_current_one_plus_a_suffix_is_pruned(tmp_path):
    """`r.v2.trace` is another run's, not the current run `r`'s: only exact names are protected."""
    put(tmp_path, "r.v2.trace", 2 * MIB, 0)
    put(tmp_path, "r.v2.frames.csv.gz", 2 * MIB, 1)
    put(tmp_path, "r.json", 10, 9)
    put(tmp_path, "r.frames.csv.gz", 100, 9)
    retention.prune_to_quota(tmp_path, 1, "r")
    assert names(tmp_path) == ["r.frames.csv.gz", "r.json"], names(tmp_path)


def test_max_disk_mb_parsing():
    saved = config.MAX_DISK_MB
    try:
        got = []
        for value in ("5", "0", "x", "-3", "2.5", " 7 ", None):
            config.reload({} if value is None else {"METAL_TRACE_MAX_DISK_MB": value})
            got.append(config.MAX_DISK_MB)
        assert got == [5, None, None, None, None, 7, None], got
    finally:
        config.reload()
        assert config.MAX_DISK_MB == saved


def test_link_is_not_followed_or_counted_through(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * (3 * MIB))
    out = tmp_path / "runs"
    out.mkdir()
    (out / "x.trace").symlink_to(outside, target_is_directory=True)
    os.utime(out / "x.trace", (1_000_000, 1_000_000), follow_symlinks=False)
    put(out, "cur.json", 10, 9)
    assert retention.prune_to_quota(out, 1, "cur")["removed"] == 0, "the link's target is not counted: the folder fits"
    put(out, "old.trace", 2 * MIB, 5)
    got = retention.prune_to_quota(out, 1, "cur")
    assert not (out / "x.trace").exists() and not (out / "old.trace").exists() and got["removed"] == 2, got
    assert (outside / "big.bin").stat().st_size == 3 * MIB, "the target of a link is never touched"


def test_link_inside_a_trace_folder_is_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * (3 * MIB))
    out = tmp_path / "runs"
    out.mkdir()
    (out / "a.trace").mkdir()
    (out / "a.trace" / "inner").symlink_to(outside, target_is_directory=True)
    put(out, "a.trace/real.bin", 2 * MIB)
    put(out, "cur.json", 10, 9)
    got = retention.prune_to_quota(out, 1, "cur")
    assert not (out / "a.trace").exists() and 2.0 <= got["freed_mb"] < 3.0, got
    assert (outside / "big.bin").stat().st_size == 3 * MIB


def test_quota_boundary_is_inclusive(tmp_path):
    """A folder of exactly max_mb MiB fits; one byte more does not; and pruning stops as soon as it fits exactly."""
    put(tmp_path, "a.trace", MIB, 0)
    assert retention.prune_to_quota(tmp_path, 1, "cur")["removed"] == 0
    put(tmp_path, "a.trace", MIB + 1, 0)
    assert retention.prune_to_quota(tmp_path, 1, "cur")["removed"] == 1
    for name, age in (("b.trace", 0), ("c.trace", 1), ("d.trace", 2)):
        put(tmp_path, name, MIB, age)
    got = retention.prune_to_quota(tmp_path, 2, "cur")  # 3 MiB: the oldest goes and 2 MiB is exactly the quota
    assert got["removed"] == 1 and names(tmp_path) == ["c.trace", "d.trace"], (got, names(tmp_path))
