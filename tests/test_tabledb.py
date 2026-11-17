"""The tables file (<run>.tables.sqlite): written while a recording is summarized, read back by trace_tables, trace_count and
trace_query when the .trace is gone, with declarative filters instead of SQL."""
import pathlib
import sqlite3
import time

from support import PKG  # noqa: F401  (puts src/ on sys.path)

from metal_gpu_trace import config, paths, perf_report, tabledb, traces

GPU = ("start", "duration", "channel-name", "process")


def xml_table(tmp_path, columns, rows, name="t.xml"):
    """Writes an xctrace-style export: `rows` are lists of cell XML snippets, one per column."""
    cols = "".join(f"<col><mnemonic>{c}</mnemonic></col>" for c in columns)
    body = "".join("<row>" + "".join(cells) + "</row>" for cells in rows)
    path = tmp_path / name
    path.write_text(f"<trace-query-result><node><schema>{cols}</schema>{body}</node></trace-query-result>")
    return str(path)


def gpu_cells(start, duration, channel="Vertex", pid=7, name="Game"):
    return [f'<start fmt="{start / 1e6} ms">{start}</start>', f'<duration fmt="{duration / 1e3} us">{duration}</duration>',
            f"<channel-name>{channel}</channel-name>", f'<process fmt="{name} ({pid})"><pid fmt="{pid}">{pid}</pid></process>']


def store(tmp_path, tables, label="r"):
    """Writes the tables file of run `label` from {schema: (columns, rows)}; returns its path."""
    target = tmp_path / f"{label}.tables.sqlite"
    writer = tabledb.Writer(target)
    try:
        for schema, (columns, rows) in tables.items():
            for _ in perf_report.rows(xml_table(tmp_path, columns, rows, f"{schema}.xml"), sink=writer.table(schema)):
                pass
        writer.commit()
    except BaseException:
        writer.abort()
        raise
    return target


def use(tmp_path):
    """Points the readers at tmp_path as the runs folder; returns what to restore."""
    saved = config.OUT
    config.OUT = tmp_path
    return saved


def rows_of(tmp_path, names, rows, **kwargs):
    store(tmp_path, {"metal-gpu-intervals": (names, rows)})
    saved = use(tmp_path)
    try:
        return traces.tool_trace_query("r", "metal-gpu-intervals", **kwargs)
    finally:
        config.OUT = saved


def sample(n=6):
    return [gpu_cells(1_000_000 * (i + 1), 100_000 * (i + 1), channel="Vertex" if i % 2 else "Fragment",
                      pid=7 if i < 4 else 9, name="Game" if i < 4 else "Other") for i in range(n)]


def test_where_columns_order_and_types(tmp_path):
    got = rows_of(tmp_path, GPU, sample(), where=[{"column": "duration", "op": ">=", "value": 300_000},
                                                   {"column": "channel-name", "op": "=", "value": "Vertex"}],
                  columns=["start", "channel-name"], order_by="start", descending=True)
    assert got["rows"] == [{"start": "6.0 ms", "channel-name": "Vertex"}, {"start": "4.0 ms", "channel-name": "Vertex"}], got
    assert got["total"] == 2 and got["next_offset"] is None, got
    # a number is compared as a number (10 > 9), not as text
    got = rows_of(tmp_path, ("n",), [["<n>9</n>"], ["<n>10</n>"], ["<n>100</n>"]], order_by="n", descending=True)
    assert [r["n"] for r in got["rows"]] == ["100", "10", "9"], got
    got = rows_of(tmp_path, ("n",), [["<n>9</n>"], ["<n>10</n>"]], where=[{"column": "n", "op": ">", "value": 9}])
    assert got["rows"] == [{"n": "10"}], got
    got = rows_of(tmp_path, ("n",), [["<n>a</n>"], ["<n/>"]], where=[{"column": "n", "op": "=", "value": None}])
    assert got["rows"] == [{"n": None}], got


def test_group_by_and_aggregates(tmp_path):
    got = rows_of(tmp_path, GPU, sample(), group_by=["channel-name"],
                  aggregates=[{"fn": "count"}, {"fn": "sum", "column": "duration"}, {"fn": "max", "column": "start"}],
                  order_by="sum_duration", descending=True)
    assert got["rows"] == [{"channel-name": "Vertex", "count": 3, "sum_duration": 1_200_000, "max_start": 6_000_000},
                           {"channel-name": "Fragment", "count": 3, "sum_duration": 900_000, "max_start": 5_000_000}], got
    assert got["total"] == 2, got
    only = rows_of(tmp_path, GPU, sample(), aggregates=[{"fn": "avg", "column": "duration"}])
    assert only["rows"] == [{"avg_duration": 350_000.0}], only
    default = rows_of(tmp_path, GPU, sample(), group_by=["channel-name"], order_by="count")
    assert {r["count"] for r in default["rows"]} == {3}, default


def test_declarative_arguments_are_checked_before_any_query(tmp_path):
    """Names come from the file, operators and functions from a fixed list, values are bound: none of these reaches SQL."""
    store(tmp_path, {"metal-gpu-intervals": (GPU, sample())})
    saved = use(tmp_path)
    before = (tmp_path / "r.tables.sqlite").read_bytes()
    bad = [
        {"where": [{"column": 'start" OR 1=1 --', "op": "=", "value": 1}]},
        {"where": [{"column": "start", "op": "= 1 OR 1=1 --", "value": 1}]},
        {"where": [{"column": "start", "op": "LIKE", "value": "%"}]},
        {"where": [{"column": "start", "op": "=", "value": [1]}]},
        {"where": [{"column": "start", "op": "<", "value": None}]},
        {"where": [{"column": "start", "op": "=", "value": True}]},
        {"where": [{"column": "start", "op": "="}]},
        {"where": ["start = 1"]},
        {"columns": ["start, (SELECT 1)"]},
        {"columns": ["start__fmt"]},
        {"columns": []},
        {"order_by": "start; DROP TABLE x"},
        {"order_by": "nope"},
        {"group_by": ["channel-name\" --"], "aggregates": [{"fn": "count"}]},
        {"group_by": ["channel-name"], "aggregates": [{"fn": "load_extension", "column": "start"}]},
        {"group_by": ["channel-name"], "aggregates": [{"fn": "sum", "column": "start) FROM x --"}]},
        {"group_by": ["channel-name"], "columns": ["start"]},
        {"group_by": ["channel-name"], "window_ms": 5},
        {"aggregates": [{"fn": "sum"}]},
    ]
    try:
        for kwargs in bad:
            try:
                traces.tool_trace_query("r", "metal-gpu-intervals", **kwargs)
            except paths.ToolError:
                continue
            raise AssertionError(f"accepted {kwargs}")
        try:
            traces.tool_trace_query("r", 'metal-gpu-intervals" --', where=[{"column": "start", "op": "=", "value": 1}])
        except paths.ToolError:
            pass
        else:
            raise AssertionError("a table name outside the file was accepted")
    finally:
        config.OUT = saved
    assert (tmp_path / "r.tables.sqlite").read_bytes() == before


def test_a_value_that_looks_like_sql_is_only_a_value(tmp_path):
    got = rows_of(tmp_path, ("name",), [["<name>x' OR '1'='1</name>"], ["<name>y</name>"]],
                  where=[{"column": "name", "op": "=", "value": "x' OR '1'='1"}])
    assert got["rows"] == [{"name": "x' OR '1'='1"}], got
    got = rows_of(tmp_path, ("name",), [["<name>x</name>"], ["<name>y</name>"]],
                  where=[{"column": "name", "op": "=", "value": "x' OR '1'='1"}])
    assert got["rows"] == [], got


def test_the_file_is_opened_read_only(tmp_path):
    target = store(tmp_path, {"metal-gpu-intervals": (GPU, sample())})
    conn = tabledb.connect(target)
    try:
        for statement in ('INSERT INTO "metal-gpu-intervals" (start) VALUES (1)', "DROP TABLE \"metal-gpu-intervals\"",
                          "ATTACH DATABASE ':memory:' AS x", "PRAGMA query_only = OFF"):
            try:
                conn.execute(statement)
            except sqlite3.DatabaseError:
                continue
            raise AssertionError(f"ran {statement}")
    finally:
        conn.close()


def test_a_link_or_a_foreign_file_is_not_read(tmp_path):
    target = store(tmp_path, {"metal-gpu-intervals": (GPU, sample())})
    other = tmp_path / "elsewhere"
    other.mkdir()
    link = other / "x.tables.sqlite"
    link.symlink_to(target)
    try:
        tabledb.connect(link)
    except ValueError as error:
        assert "link" in str(error), error
    else:
        raise AssertionError("a link was opened")
    (tmp_path / "x.tables.sqlite").write_bytes(b"not a database at all")
    foreign = sqlite3.connect(tmp_path / "y.tables.sqlite")
    foreign.execute("CREATE TABLE a (b)")
    foreign.commit()
    foreign.close()
    for name in ("x", "y"):
        try:
            tabledb.connect(tmp_path / f"{name}.tables.sqlite")
        except ValueError:
            continue
        raise AssertionError(f"{name} was opened")
    saved = use(tmp_path)
    try:
        (tmp_path / "z.tables.sqlite").symlink_to(target)
        try:
            traces.tool_trace_tables("z")
        except paths.ToolError:
            pass
        else:
            raise AssertionError("trace_tables read a link")
    finally:
        config.OUT = saved


def test_columns_that_differ_from_the_expected_ones_are_stored(tmp_path):
    """The schema is whatever the export names: odd names, a table of no rows, a cell the first rows lack."""
    got = rows_of(tmp_path, ("a b", 'q"x', "e-f"), [["<c1>1</c1>", "<c2>2</c2>", "<c3>3</c3>"], ["<c1>4</c1>"]],
                  columns=["a b", 'q"x'], order_by="a b")
    assert got["rows"] == [{"a b": "1", 'q"x': "2"}, {"a b": "4", 'q"x': None}], got
    saved = use(tmp_path)
    try:
        assert traces.tool_trace_query("r", "metal-gpu-intervals", where=[{"column": "e-f", "op": "=", "value": 3}])["total"] == 1
    finally:
        config.OUT = saved


def test_private_paths_never_reach_the_file(tmp_path):
    """The argument columns get the summary's public_arguments, and a home folder anywhere else becomes ~."""
    rows = [["<name>Game</name>", "<arguments>/Users/ann/Games/game.exe --level 3 -I/Users/ann/inc</arguments>",
             '<note fmt="/Users/ann lee/Library/x /Users/bob/y">/Users/ann/z</note>', '<process fmt="G (7)"><pid>7</pid></process>']]
    target = store(tmp_path, {"process": (("name", "arguments", "note", "process"), rows)})
    assert b"Users" not in target.read_bytes()
    saved = use(tmp_path)
    try:
        got = traces.tool_trace_query("r", "process")["rows"][0]
    finally:
        config.OUT = saved
    assert got["arguments"].startswith("game.exe --level 3"), got
    assert "~" in got["note"], got
    wine = [["<name>Wine</name>", r"<arguments>Z:\Users\ann lee\save.dat</arguments>", r'<note fmt="C:\users\ann\x /prefix/drive_c/users/bob/y">Z:\Users\ann\z</note>', "<process/>"]]
    target = store(tmp_path, {"wine": (("name", "arguments", "note", "process"), wine)}, label="w")
    assert b"ann" not in target.read_bytes().replace(b"channel", b"") and b"bob" not in target.read_bytes(), target.read_bytes()


def test_the_file_is_replaced_whole_or_not_at_all(tmp_path):
    target = store(tmp_path, {"metal-gpu-intervals": (GPU, sample())})
    before = target.read_bytes()
    writer = tabledb.Writer(target)
    for _ in perf_report.rows(xml_table(tmp_path, GPU, sample(2)), sink=writer.table("metal-gpu-intervals")):
        pass
    assert target.read_bytes() == before, "nothing is visible before the commit"
    writer.abort()
    assert target.read_bytes() == before and sorted(p.name for p in tmp_path.glob("r.*")) == ["r.tables.sqlite"], list(tmp_path.iterdir())
    writer = tabledb.Writer(target)
    writer.commit()
    assert target.read_bytes() != before and not list(tmp_path.glob("*.part")), "an empty file replaces it on commit"


def test_ingest_speed_and_size(tmp_path):
    """A table of a few thousand rows is stored in one pass; the figures for 200 000 rows are in the changelog's evidence."""
    rows = [gpu_cells(i * 1000, 500 + i % 7) for i in range(3000)]
    began = time.perf_counter()
    target = store(tmp_path, {"metal-gpu-intervals": (GPU, rows)})
    assert time.perf_counter() - began < 30 and target.stat().st_size > 0
    assert pathlib.Path(target).name == "r.tables.sqlite"


def test_an_empty_cell_reads_as_none_like_the_export_route(tmp_path):
    """Found on a real recording: a cell with fmt="" and no text is None on the export route, never ''."""
    got = rows_of(tmp_path, ("a", "b"), [['<a fmt=""/>', "<b>2</b>"], ["<a>1</a>", '<b fmt="x">2</b>']],
                  columns=["a", "b"], order_by="b")
    assert got["rows"][0] == {"a": None, "b": "2"} and got["rows"][1] == {"a": "1", "b": "x"}, got


def test_decimals_ending_in_zero_and_large_integers_compare_as_numbers(tmp_path):
    """Review finding: '0.0' and '2.0' were stored as text, and in SQLite any text sorts after every number."""
    cells = [[f"<v>{v}</v>"] for v in ("0.0", "0.5", "2.0", "10.5", "1000000000000000000", "9223372036854775807")]
    got = rows_of(tmp_path, ("v",), cells, where=[{"column": "v", "op": ">", "value": 0.2}], order_by="v", descending=True)
    assert [r["v"] for r in got["rows"]] == ["9223372036854775807", "1000000000000000000", "10.5", "2.0", "0.5"], got
    top = rows_of(tmp_path, ("v",), cells, aggregates=[{"fn": "max", "column": "v"}])
    assert top["rows"] == [{"max_v": 9223372036854775807}], top  # an aggregate is a number


def test_a_number_beyond_what_sqlite_holds_is_a_tool_error(tmp_path):
    store(tmp_path, {"metal-gpu-intervals": (GPU, sample())})
    saved = use(tmp_path)
    try:
        for argument in ({"offset": 10 ** 20}, {"pid": 10 ** 20}):
            try:
                traces.tool_trace_query("r", "metal-gpu-intervals", **argument)
            except paths.ToolError:
                continue
            raise AssertionError(f"{argument} was accepted")
    finally:
        config.OUT = saved


def test_a_table_that_came_without_columns_is_still_readable(tmp_path):
    got = rows_of(tmp_path, (), [])
    assert got["total"] == 0 and got["rows"] == [], got
