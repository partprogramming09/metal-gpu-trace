"""The per-frame and Metal memory tables of a recording: written as `<stem>.csv.gz`, read from that or from the plain
`<stem>.csv` that recordings made before the gzip change left. Every reader and writer of those files goes through here."""
import csv
import gzip
import io
import os
import zlib

# what reading a table can raise, whichever format it is in (a truncated or damaged gzip is EOFError, BadGzipFile or zlib.error)
UNREADABLE = (OSError, EOFError, UnicodeDecodeError, csv.Error, gzip.BadGzipFile, zlib.error)


def find(directory, stem):
    """Returns `directory/<stem>.csv.gz` if it exists, else `directory/<stem>.csv`, else None."""
    for suffix in (".csv.gz", ".csv"):
        path = directory / (stem + suffix)
        if path.is_file():
            return path
    return None


def open_text(path):
    """Opens a table for reading as UTF-8 text with newline="" (what csv wants); gzip when the name ends in `.gz`."""
    if path.name.endswith(".gz"):
        if path.stat().st_size == 0:  # gzip reads an empty file as an empty table: a recording cut at 0 bytes is not one
            raise EOFError("empty gzip file")
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return open(path, "r", encoding="utf-8", newline="")


def write(directory, stem, header, rows, compress=True):
    """Writes the table as `<stem>.csv.gz` (`<stem>.csv` when `compress` is false) and returns its path. The same rows give
    the same bytes (no name or time in the gzip header). It is written under a temporary name beside the target and
    renamed, so an exception in `rows` leaves no half file."""
    target = directory / (stem + (".csv.gz" if compress else ".csv"))
    # a name of its own, starting like the run's files so a killed writer's leftover is removed with the run (KEEP_RUNS, a
    # cancelled recording); created exclusively and never through a link, with the mode the other outputs get (the
    # umask), which mkstemp's owner-only 0600 would not give
    temporary = directory / f"{target.name}.{os.urandom(4).hex()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o666)
    try:
        with os.fdopen(descriptor, "wb") as raw:
            if compress:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                    _dump(zipped, header, rows)
            else:
                _dump(raw, header, rows)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def _dump(binary, header, rows):
    text = io.TextIOWrapper(binary, encoding="utf-8", newline="")
    writer = csv.writer(text)
    writer.writerow(header)
    writer.writerows(rows)
    text.flush()
    text.detach()  # the caller closes the binary file
