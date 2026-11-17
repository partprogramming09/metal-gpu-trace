"""The tables file of a recording, `<run>.tables.sqlite`: the xctrace tables a summary reads, kept beside the run so they can
be queried after the .trace is deleted.

Written by perf_report while it reads each table (`Writer`), read by `traces` through declarative filters (`select`): no
caller's text ever becomes SQL. Table and column names come from the file itself and are quoted; operators and functions
come from fixed lists; values are bound parameters. The file is opened read-only, behind an authorizer that allows only
SELECT. Each table keeps, per column `c`: `c` (the cell's text, as an integer or a decimal when it is one exactly),
`c__fmt` (the formatted value, only where it differs) and, for a `process` column, `process__pid`."""
import math
import os
import pathlib
import re
import sqlite3
import stat

from metal_gpu_trace import config, metrics

FORMAT = 1  # PRAGMA user_version of a file this module wrote
SUFFIX = ".tables.sqlite"
HIDDEN = ("__fmt", "__pid")
FLUSH_ROWS = 5000
OPS = {"=": "=", "!=": "<>", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
FUNCTIONS = ("count", "sum", "avg", "min", "max")
INT = re.compile(r"-?(0|[1-9][0-9]{0,18})")  # then kept only inside SQLite's 64 bits
DECIMAL = re.compile(r"-?(0|[1-9][0-9]*)\.[0-9]+")  # repr(float(text)) == text below drops the ones a float would rewrite
HOME = re.compile(r"(?i)(?:[A-Za-z]:)?[/\\]users[/\\][^/\\]+")  # /Users/ann, Z:\Users\ann, a Wine prefix's drive_c/users/ann


def path_for(trace):
    """Returns the tables file that goes with a .trace path: `<name>.tables.sqlite` in the same folder."""
    trace = pathlib.Path(trace)
    return trace.with_name(trace.name.removesuffix(".trace") + SUFFIX)


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def clean(text, arguments=False):
    """Returns `text` fit to share: a command line gets the summary's public_arguments, and a home folder anywhere
    (macOS, or a Windows or Wine path) becomes `~`."""
    if arguments:
        text = metrics.public_arguments(text)
    return HOME.sub("~", text)


def number_or_text(text):
    """Returns `text` as an int or float when it is one exactly, as written, else unchanged: a number is then compared as a
    number, and CAST back to text gives the same characters."""
    if INT.fullmatch(text) and -2 ** 63 <= int(text) < 2 ** 63:
        return int(text)
    if DECIMAL.fullmatch(text) and len(text.replace("-", "").replace(".", "").lstrip("0")) <= 15 and repr(float(text)) == text:
        return float(text)
    return text


def pid_of(process):
    """Returns the pid of a <process> cell, or None (the same reading as perf_report.pid_of, which cannot be imported here)."""
    pid = process.find("pid")
    try:
        return int(pid.attrib.get("fmt") or pid.text) if pid is not None and (pid.text or pid.attrib.get("fmt")) else None
    except ValueError:
        return None


class TableSink:
    """Receives one table's columns and rows from perf_report.rows and stores them; never raises into the summary."""

    def __init__(self, writer, schema):
        self.writer, self.schema, self.keys, self.names, self.pending = writer, schema, None, None, []

    def columns(self, mnemonics):
        """Creates the table: one set of SQLite columns per exported column, whatever its name."""
        if self.keys is not None or self.writer.failed:
            return
        self.keys, self.names, used = [], [], set()
        for index, mnemonic in enumerate(mnemonics):
            name = str(mnemonic) if mnemonic else f"col{index}"
            while name in used or name.endswith(HIDDEN):
                name += "_"
            used.add(name)
            self.keys.append(mnemonic)
            self.names.append(name)
        defs = [quote(n) + ", " + quote(n + "__fmt") + (", " + quote(n + "__pid") if n == "process" else "") for n in self.names]
        self.arguments = ["argument" in n.lower() for n in self.names]
        self.writer.run(f"CREATE TABLE {quote(self.schema)} ({', '.join(defs) or quote('dummy') + ', ' + quote('dummy__fmt')})")
        marks = ", ".join("?" * (sum(3 if n == "process" else 2 for n in self.names) or 1))
        self.insert = f"INSERT INTO {quote(self.schema)} VALUES ({marks})"

    def add(self, row):
        if not self.keys or self.writer.failed:
            return
        values = []
        for key, name, argument in zip(self.keys, self.names, self.arguments):
            cell = row.get(key)
            raw = cell.text if cell is not None and cell.text and cell.text.strip() else None
            shown = (cell.attrib.get("fmt") or None) if cell is not None else None  # fmt="" is no value, as in `fmt or text`
            if raw is not None:
                raw = clean(raw, argument)
            if shown is not None:
                shown = clean(shown, argument)
            values += [number_or_text(raw) if raw is not None else None, shown if shown != raw else None]
            if name == "process":
                values.append(pid_of(cell) if cell is not None else None)
        self.pending.append(values)
        if len(self.pending) >= FLUSH_ROWS:
            self.flush()

    def flush(self):
        if self.pending and not self.writer.failed:
            self.writer.run(self.insert, self.pending, many=True)
        self.pending = []


class Writer:
    """Builds the tables file in `<name>.part` in one transaction and moves it over the target in `commit`, so a reader
    sees the whole file or none. A storage error (a full disk) stops the writing and leaves `failed` set: the summary
    does not depend on this file."""

    def __init__(self, target):
        self.target = pathlib.Path(target)
        self.part = self.target.with_name(self.target.name + ".part")
        self.sinks, self.failed = [], None
        self.part.unlink(missing_ok=True)
        self.conn = sqlite3.connect(self.part, isolation_level=None)
        self.run("PRAGMA journal_mode = OFF")
        self.run("PRAGMA synchronous = OFF")
        self.run("BEGIN")

    def run(self, sql, args=(), many=False):
        try:
            (self.conn.executemany if many else self.conn.execute)(sql, args)
        except (sqlite3.Error, OverflowError) as error:
            self.failed = f"{type(error).__name__}: {error}"

    def table(self, schema):
        sink = TableSink(self, schema)
        self.sinks.append(sink)
        return sink

    def commit(self):
        """Stores what is pending and replaces the target; returns whether the file was written."""
        for sink in self.sinks:
            sink.flush()
        if not self.failed:
            self.run(f"PRAGMA user_version = {FORMAT}")
            self.run("COMMIT")
        self.conn.close()
        if self.failed:
            self.part.unlink(missing_ok=True)
            return False
        os.replace(self.part, self.target)
        return True

    def abort(self):
        self.conn.close()
        self.part.unlink(missing_ok=True)


def authorizer(action, *_):
    """Allows only what a SELECT does: reading columns and calling functions (count, sum, ...)."""
    return 0 if action in (20, 21, 31) else 1  # SQLITE_READ, SQLITE_SELECT, SQLITE_FUNCTION; anything else is denied


def connect(path):
    """Opens a tables file read-only and returns the connection. ValueError when `path` is a link, not a regular file,
    or not a file this module wrote."""
    path = pathlib.Path(path)
    if path.is_symlink():
        raise ValueError(f"{path.name} is a link and is not read")
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            raise ValueError(f"{path.name} is not a file")
    except OSError:
        raise ValueError(f"{path.name} cannot be read") from None
    conn = None
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA trusted_schema = OFF")
        if conn.execute("PRAGMA user_version").fetchone()[0] != FORMAT:
            raise ValueError(f"{path.name} is not a tables file of this version; record the run again")
        conn.set_authorizer(authorizer)
        return conn
    except sqlite3.Error:
        if conn is not None:
            conn.close()
        raise ValueError(f"{path.name} is not a readable tables file") from None
    except ValueError:
        conn.close()
        raise


def tables(conn):
    """Returns the names of the tables the file holds, sorted."""
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]


def columns(conn, table):
    """Returns (the columns a caller may name, every column of the table), in table order."""
    every = [d[0] for d in conn.execute(f"SELECT * FROM {quote(table)} LIMIT 0").description]
    return [c for c in every if not c.endswith(HIDDEN)], every


def shown(name):
    """The SQL for a column as trace_query shows it: its formatted value, else its text."""
    return f'COALESCE(t.{quote(name + "__fmt")}, CAST(t.{quote(name)} AS TEXT))'


def where_sql(allowed, every, where, pid):
    """Returns (SQL, parameters) for the filters; ValueError when one is not a {column, op, value} of the allowed kind."""
    if where is None:
        where = []
    if not isinstance(where, list) or not all(isinstance(w, dict) for w in where):
        raise ValueError("where is a list of {column, op, value} objects")
    parts, args = [], []
    for w in where:
        if set(w) != {"column", "op", "value"}:
            raise ValueError("each where filter has exactly column, op and value")
        column, op, value = w["column"], w["op"], w["value"]
        if not isinstance(column, str) or column not in allowed:
            raise ValueError(f"where column {column!r} is not a column of the table; columns come from trace_query without arguments")
        if not isinstance(op, str) or op not in OPS:
            raise ValueError(f"where op is one of {', '.join(OPS)}")
        if value is None and op in ("=", "!="):
            parts.append(f't.{quote(column)} IS {"NOT " if op == "!=" else ""}NULL')
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)) or (
                isinstance(value, float) and not math.isfinite(value)) or (isinstance(value, int) and abs(value) >= 2**63):
            raise ValueError("a where value is a string or a number (null only with = or !=)")
        parts.append(f"t.{quote(column)} {OPS[op]} ?")
        args.append(value)
    if pid is not None and "process__pid" in every:
        parts.append('t."process__pid" = ?')
        args.append(int(pid))
    return (" WHERE " + " AND ".join(parts)) if parts else "", args


def name_list(value, what, allowed):
    """Returns `value` as a non-empty list of distinct names from `allowed`, or raises ValueError."""
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value) or len(set(value)) != len(value):
        raise ValueError(f"{what} is a non-empty list of distinct column names")
    for name in value:
        if name not in allowed:
            raise ValueError(f"{what} column {name!r} is not a column of the table")
    return value


def select(conn, table, where=None, columns_=None, order_by=None, descending=None, group_by=None, aggregates=None,
           pid=None, offset=0, limit=50):
    """Returns one page of a table as {total, offset, rows, next_offset}: the rows (or the groups, with `group_by` or
    `aggregates`) as {column: value}. ValueError says what is wrong with an argument; nothing reaches the file before
    every argument is checked."""
    if table not in tables(conn):
        raise ValueError(f"{table} is not in the tables file; trace_tables lists its tables")
    allowed, every = columns(conn, table)
    if descending is not None and not isinstance(descending, bool):
        raise ValueError("descending is true or false")
    clause, args = where_sql(allowed, every, where, pid)
    grouped = group_by is not None or aggregates is not None
    if grouped and columns_ is not None:
        raise ValueError("columns lists rows' columns; with group_by or aggregates the result's columns are the groups and aggregates")
    order = ""
    if grouped:
        keys = name_list(group_by, "group_by", allowed) if group_by is not None else []
        if aggregates is None:
            aggregates = [{"fn": "count"}]
        if not isinstance(aggregates, list) or not aggregates or not all(isinstance(a, dict) for a in aggregates):
            raise ValueError("aggregates is a non-empty list of {fn, column} objects")
        names, exprs = list(keys), [shown(k) for k in keys]
        for a in aggregates:
            fn, column = a.get("fn"), a.get("column")
            if set(a) - {"fn", "column"} or fn not in FUNCTIONS:
                raise ValueError(f"an aggregate is {{fn, column}} with fn one of {', '.join(FUNCTIONS)}")
            if column is None and fn != "count":
                raise ValueError(f"the aggregate {fn} needs a column")
            if column is not None and (not isinstance(column, str) or column not in allowed):
                raise ValueError(f"aggregate column {column!r} is not a column of the table")
            names.append(fn if column is None else f"{fn}_{column}")
            exprs.append(f"{fn.upper()}({'*' if column is None else 't.' + quote(column)})")
        if len(set(names)) != len(names):
            raise ValueError("two columns of the result would have the same name")
        select_list = ", ".join(f"{e} AS {quote(n)}" for e, n in zip(exprs, names))
        from_sql = f"FROM {quote(table)} AS t{clause}" + (" GROUP BY " + ", ".join(exprs[:len(keys)]) if keys else "")
        if order_by is not None:
            if order_by not in names:
                raise ValueError(f"order_by is one of {', '.join(names)}")
            order = f" ORDER BY {names.index(order_by) + 1}{' DESC' if descending else ''}" + "".join(
                f", {i + 1}" for i in range(len(keys)))
        elif keys:
            order = " ORDER BY " + ", ".join(str(i + 1) for i in range(len(keys)))
        count_sql = f"SELECT COUNT(*) FROM (SELECT {select_list} {from_sql})"
    else:
        names = name_list(columns_, "columns", allowed) if columns_ is not None else allowed
        select_list = ", ".join(f"{shown(n)} AS {quote(n)}" for n in names)
        from_sql = f"FROM {quote(table)} AS t{clause}"
        if order_by is not None and order_by not in allowed:
            raise ValueError(f"order_by is one of {', '.join(allowed)}")
        order = " ORDER BY " + (f"t.{quote(order_by)}{' DESC' if descending else ''}, " if order_by is not None else "") + "t.rowid"
        count_sql = f"SELECT COUNT(*) {from_sql}"
    offset, limit = max(0, int(offset)), min(max(1, int(limit)), config.MAX_LIMIT)
    total = conn.execute(count_sql, args).fetchone()[0]
    rows = [dict(zip(names, r)) for r in conn.execute(f"SELECT {select_list} {from_sql}{order} LIMIT ? OFFSET ?", [*args, limit, offset])]
    more = offset + len(rows) < total
    return {"total": total, "offset": offset, "rows": rows, "next_offset": offset + len(rows) if more else None}


class Cell:
    """A stand-in for an exported element, for traces.windows_of, which reads `.text`."""

    def __init__(self, text):
        self.text = text


def time_rows(conn, table, names, pid=None, where=None):
    """Yields, per row, {name: Cell} for those of `names` (time and duration columns) that the table has: what
    traces.windows_of needs from the table's rows."""
    allowed, every = columns(conn, table)
    clause, args = where_sql(allowed, every, where, pid)
    present = [n for n in names if n in allowed]
    if not present:
        yield from ({} for _ in conn.execute(f"SELECT 1 FROM {quote(table)} AS t{clause}", args))
        return
    sql = f"SELECT {', '.join('CAST(t.' + quote(n) + ' AS TEXT)' for n in present)} FROM {quote(table)} AS t{clause} ORDER BY t.rowid"
    for r in conn.execute(sql, args):
        yield {n: Cell(v) for n, v in zip(present, r)}


def process_counts(conn, table, top=10):
    """Returns (row count, {process name: rows} for the `top` busiest) of a table, naming a process as trace_count does."""
    allowed, every = columns(conn, table)
    total = conn.execute(f"SELECT COUNT(*) FROM {quote(table)}").fetchone()[0]
    if "process__pid" not in every:
        return total, {}
    name = 'COALESCE(t."process__fmt", CAST(t."process__pid" AS TEXT))'
    sql = (f'SELECT {name} AS n, COUNT(*) AS c FROM {quote(table)} AS t WHERE t."process__fmt" IS NOT NULL '
           f'OR t."process__pid" IS NOT NULL GROUP BY n ORDER BY c DESC, n LIMIT ?')
    return total, dict(conn.execute(sql, [top]).fetchall())
