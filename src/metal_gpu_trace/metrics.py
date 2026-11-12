"""The numbers Mac (perf_report) and Windows (perf_record_windows) summaries share, in one copy so their schema
stays the same: statistics, encoder and idle-gap figures, label grouping and shareable command lines."""
import collections
import pathlib
import re
import statistics

# encoder GPU times, in µs, whose share of all encoders each summary keeps
SHORT_US = (10, 25, 50, 100, 250, 500, 1000)


def stats(values):
    """Returns count, mean, median, 95th percentile and maximum of `values`, rounded to microseconds when in ms."""
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": round(statistics.fmean(ordered), 3),
        "p50": round(ordered[len(ordered) // 2], 3),
        "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "max": round(ordered[-1], 3),
    }


def label_name(label):
    """Returns an encoder label without Instruments' "[n] " prefix and trailing index, so the same pass groups."""
    return re.sub(r" \d+$", "", re.sub(r"^\[\d+\] ", "", label)) or "?"


def encoder_stats(spans, labels):
    """Returns encoders and command buffers per frame, each encoder's GPU time, the share of encoders shorter than
    each of SHORT_US and the 20 labels with the most GPU time. `spans` holds (frame, start ns, duration ns, encoder
    id, command buffer id) and `labels` maps an encoder id to its label."""
    encoders, buffers, busy = collections.defaultdict(set), collections.defaultdict(set), collections.Counter()
    for frame, _, duration, encoder, buffer in spans:
        if encoder:
            encoders[frame].add(encoder)
            busy[encoder] += duration
        if buffer:
            buffers[frame].add(buffer)
    us = [ns / 1000 for ns in busy.values()]
    grouped = collections.defaultdict(list)
    for encoder, ns in busy.items():
        grouped[label_name(labels.get(encoder, ""))].append(ns / 1000)
    frames = len({s[0] for s in spans}) or 1
    top = sorted(grouped.items(), key=lambda kv: -sum(kv[1]))[:20]
    return {
        "per_frame": stats([len(e) for e in encoders.values()]),
        "command_buffers_per_frame": stats([len(b) for b in buffers.values()]),
        "encoder_us": stats(us),
        "short_share": {str(cut): round(sum(u < cut for u in us) / len(us), 3) for cut in SHORT_US} if us else {},
        "by_label": [{"label": name, "per_frame": round(len(v) / frames, 2), "total_ms": round(sum(v) / 1000, 3),
                      "mean_us": round(statistics.fmean(v), 1), "stdev_us": round(statistics.pstdev(v), 1)}
                     for name, v in top],
    }


def idle_gaps(spans):
    """Returns the time the GPU ran none of the process's work between its first and last interval: per frame (each
    gap counts in the frame of the work that ends it), gaps over 1 ms and share of the whole span. `spans` as in
    encoder_stats."""
    ordered = sorted((start, start + duration, frame) for frame, start, duration, _, _ in spans)
    if not ordered:
        return {"idle_ms_per_frame": {"count": 0}}
    idle, gaps, end = collections.Counter({frame: 0 for _, _, frame in ordered}), [], ordered[0][1]
    for start, stop, frame in ordered[1:]:
        if start > end:
            gaps.append((start - end) / 1e6)
            idle[frame] += (start - end) / 1e6
        end = max(end, stop)
    whole = (end - ordered[0][0]) / 1e6
    return {"idle_ms_per_frame": stats(list(idle.values())), "gaps_over_1ms": sum(g > 1 for g in gaps),
            "idle_share": round(sum(gaps) / whole, 3) if whole else None}


# one argument: an optional `--name=` prefix, then a "quoted", 'quoted' or bare value
_ARGUMENT = re.compile(r"""(?=\S)(?P<option>-[^\s=]*=)?(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)'|(?P<bare>\S*))""")
# C:\ or C:/ (a Wine program's paths), a UNC path, or a Windows path rooted without a drive (\users\name\x)
_WINDOWS_PATH = re.compile(r"^(?:[a-zA-Z]:[\\/]|\\\\|\\[^\\\s]+\\)")  # a lone \n or \d+ is not a path
# where a path starts inside a word: after a single-dash flag (-I/x, -isystem/x), after `name=`, `name:`, `@` (a
# response file), a comma (-Wl,-rpath,/x) or a quote glued to a word (-I"/x"); `://host` is a URL, not a path
_INNER_PATH = re.compile(r"""(?:^-[A-Za-z]+(?=/(?!/[^/])|\\\\)|^-[A-Za-z](?=[a-zA-Z]:[\\/])|[=:@,"'](?=/(?!/[^/])|[a-zA-Z]:[\\/]|\\\\))""")


def public_arguments(arguments):
    """Returns a command line with each absolute path cut to its file name, so summaries can be shared: POSIX paths,
    Windows drive and UNC paths (as a Wine program gets them) and the value of `--option=path`, on every platform.

    The line comes without quoting that can be trusted, so a folder name with spaces (`C:\\Users\\Ann Lee\\save.dat`)
    cannot be told from two arguments. The rule is that an unquoted absolute path runs from its first word to the next
    argument that starts with `-`, a quote or a new absolute path; the words in between belong to it and only the name
    after its last separator stays, so no folder name is left. A quoted path is one argument, ended by its quote.
    Consequences: a plain word that follows a path with no flag between them is read as part of the path, and its
    file name keeps it (`/opt/a/game.exe level1` gives `game.exe level1`, as it always did); a file name with spaces
    stays whole; a path that ends in a separator names a folder and leaves nothing; and a space followed by `/` or
    `C:\\` always starts a new path. A path inside a word is cut the same way: after a single-dash flag (`-I/x`),
    after `name=`, `name:` (`file:///x`), `@` or a comma, after a quote glued to a word or never closed, and inside a
    quoted value (`-exec "load /x/y"`). Relative paths and URLs with a host are not cut: they hold no user's folder."""
    def is_path(text):
        return text.startswith("/") or bool(_WINDOWS_PATH.match(text))

    def file_name(path):
        if path.endswith(("/", "\\")):
            return ""
        name = (pathlib.PureWindowsPath if _WINDOWS_PATH.match(path) else pathlib.PurePosixPath)(path).name
        return name.rsplit("\\", 1)[-1].strip()  # /out:C:\x\y.log is one POSIX name that holds a Windows path
    out, run = [], None  # run: [option prefix, the words of the path so far]

    def end_run():
        nonlocal run
        if run is not None:
            out.append(run[0] + file_name(" ".join(run[1])))
            run = None
    for match in _ARGUMENT.finditer(arguments or ""):
        option = match["option"] or ""
        quoted = match["double"] if match["double"] is not None else match["single"]
        value = match["bare"] if quoted is None else quoted
        if is_path(value):
            end_run()
            if quoted is None:
                run = [option, [value]]
            else:
                out.append(option + file_name(value))
        elif run is not None and quoted is None and not option and not value.startswith("-"):
            run[1].append(value)
        elif quoted is not None:  # a quoted value that is not a path may still hold one: `-exec "load /x/y"`
            end_run()
            mark = '"' if match["double"] is not None else "'"
            out.append(option + mark + public_arguments(quoted) + mark)
        elif (inner := _INNER_PATH.search(value)) is not None:  # -I/x, name=/x, file:///x
            end_run()
            run = [option + value[:inner.end()], [value[inner.end():]]]
        else:
            end_run()
            out.append(match[0])
    end_run()
    return " ".join(word for word in out if word)
