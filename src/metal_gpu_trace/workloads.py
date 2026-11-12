"""Test programs: the workload list, downloading and unpacking them, and PresentMon."""
import hashlib
import os
import pathlib
import re
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile

from metal_gpu_trace import config, paths
if sys.platform == "win32":
    from metal_gpu_trace import perf_record_windows


def workload_entry(name):
    """Returns a test program's entry in data/workloads.json and the directory it is fetched into."""
    if name not in config.WORKLOADS:
        raise paths.ToolError(f"no workload {name!r}; workload_list lists them")
    entry = config.WORKLOADS[name]
    return entry, config.CACHE / f"{name}-{entry['sha256'][:12]}"


def moltenvk_dir():
    """Returns the directory METAL_TRACE_MOLTENVK names. It must hold libMoltenVK.dylib (arm64) and no spaces, because
    the program's environment is passed to Instruments as space-separated NAME=VALUE pairs."""
    raw = os.environ.get("METAL_TRACE_MOLTENVK")
    if not raw:
        raise paths.ToolError("api vk runs through MoltenVK: set METAL_TRACE_MOLTENVK to the directory holding libMoltenVK.dylib")
    path = pathlib.Path(raw).expanduser().resolve()
    if not (path / "libMoltenVK.dylib").is_file():
        raise paths.ToolError("METAL_TRACE_MOLTENVK holds no libMoltenVK.dylib")
    if any(c.isspace() for c in str(path)):
        raise paths.ToolError("the METAL_TRACE_MOLTENVK path may not contain spaces: copy libMoltenVK.dylib to another directory")
    return path


def workload_layer(name, api, dim):
    """Returns the layer a workload's api runs through (MoltenVK with its size and SHA-256, or Rosetta for Metal built for
    x86_64), or None when the api is native Metal or goes through Wine."""
    entry = workload_entry(name)[0]
    if entry["apis"].get(api, {}).get("rosetta"):
        return {"rosetta": "native Metal built for x86_64 and run under Rosetta 2, like Wine's programs",
                "program_env": f"{entry['dim_variable']}={int(dim)}" if dim else ""}
    if not entry["apis"].get(api, {}).get("moltenvk"):
        return None
    return {"moltenvk": "Vulkan on Metal through MoltenVK", "dylib": file_id(moltenvk_dir() / "libMoltenVK.dylib"),
            "program_env": f"{entry['dim_variable']}={int(dim)}" if dim else ""}


def check_size(size):
    """Returns (width, height) from a "WIDTHxHEIGHT" text between 320x240 and 7680x4320, or raises ToolError."""
    match = re.fullmatch(r"(\d{3,4})x(\d{3,4})", str(size))
    if not match or not (320 <= int(match[1]) <= 7680 and 240 <= int(match[2]) <= 4320):
        raise paths.ToolError("size is WIDTHxHEIGHT, from 320x240 to 7680x4320")
    return int(match[1]), int(match[2])


def quote_path(path):
    """Returns `path` quoted so split_args keeps it as one argument even with spaces in it (a Windows user name, say)."""
    return f'"{path}"' if sys.platform == "win32" else shlex.quote(str(path))


def workload_command(name, api, dim, wine, args, example=None, size=None):
    """Returns the program, Wine, arguments and program environment that run a fetched workload with `api`; a workload
    with `examples` runs the one named by `example`."""
    entry, target = workload_entry(name)
    if api not in entry["apis"]:
        raise paths.ToolError(f"api is one of {', '.join(entry['apis'])} for {name}")
    examples = entry.get("examples")
    if examples and example not in examples:
        raise paths.ToolError(f"example is one of {', '.join(examples)} for {name}")
    if example and not examples:
        raise paths.ToolError(f"{name} takes no example")
    if dim and "dim_variable" not in entry:
        raise paths.ToolError(f"dim does not apply to {name}")
    if not target.is_dir():
        raise paths.ToolError(f"{name} is not downloaded yet; call workload_fetch first")
    run = entry["apis"][api]
    program_env = f"{entry['dim_variable']}={int(dim)}" if dim else ""
    if size is not None:
        if not entry.get("size_variables"):
            raise paths.ToolError(f"size does not apply to {name}")
        program_env = " ".join(filter(None, [program_env, *(f"{v}={n}" for v, n in zip(entry["size_variables"], check_size(size)))]))
    if run.get("moltenvk"):
        program_env = " ".join(filter(None, [program_env, f"DYLD_LIBRARY_PATH={moltenvk_dir()}"]))
    use_wine = run["wine"] and sys.platform != "win32"
    return (target / entry["dir"] / run["program"], wine if use_wine else "native",
            " ".join(filter(None, [run["args"].replace("{dir}", quote_path(target / entry["dir"])),
                                   examples[example] if example else "", args])), program_env)


def tool_workload_list():
    """Lists the test programs workload_fetch can download, such as bgfx's drawstress: what each measures, its size,
    license and APIs, and whether it is already downloaded."""
    rows = []
    for name, entry in config.WORKLOADS.items():
        rows.append({"name": name, "title": entry["title"], "about": entry["about"],
                     "bytes": entry["bytes"] + sum(d["bytes"] for d in entry.get("downloads", [])),
                     "license": entry["license"], "apis": list(entry["apis"]),
                     **({"examples": list(entry["examples"])} if entry.get("examples") else {}),
                     **({"example_traits": dict(entry["example_traits"])} if entry.get("example_traits") else {}),
                     "fetched": workload_entry(name)[1].is_dir()})
    return {"workloads": rows}


def download(url, path, max_bytes):
    """Saves `url` to `path` over https with curl, which uses the system's certificates; fails above `max_bytes`."""
    proc = subprocess.run(["curl", "-fsSL", "--proto", "=https", "--max-filesize", str(max_bytes), "--max-time", "600",
                           "-o", str(path), url], capture_output=True, text=True)
    if proc.returncode:
        raise paths.ToolError(f"the download failed (curl exit {proc.returncode}); check the network and try again")


def unpack(archive, target):
    """Extracts a .tar.gz into `target`, refusing links and any member that would land outside it."""
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not (member.isfile() or member.isdir()) or member.name.startswith("/") or ".." in member.name.split("/"):
                raise paths.ToolError(f"the archive holds {member.name!r}, which may not be extracted; nothing was saved")
        tar.extractall(target, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))


def unzip(archive, target):
    """Extracts a .zip into `target`, refusing links and any member that would land outside it, and restores the
    Unix file modes the archive records (the zipfile module drops them)."""
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if (stat.S_ISLNK(info.external_attr >> 16) or info.filename.startswith("/")
                    or ".." in info.filename.split("/")):
                raise paths.ToolError(f"the archive holds {info.filename!r}, which may not be extracted; nothing was saved")
        zf.extractall(target)
        for info in zf.infolist():
            mode = (info.external_attr >> 16) & 0o777
            if mode and not info.is_dir():
                (pathlib.Path(target) / info.filename).chmod(mode)


def tool_workload_fetch(name):
    """Downloads a test program from this project's GitHub releases once, checks its SHA-256 against the one this
    package pins, and keeps it in ~/Library/Caches/metal-gpu-trace; later calls reuse it. The programs are built
    from source by the project's workloads workflow. A workload with `downloads` (Godot) also fetches each of those
    zip files from its own publisher, checks its SHA-512 against the one data/workloads.json pins and unzips it into
    the workload's folder."""
    entry, target = workload_entry(name)
    if target.is_dir():
        return {"name": name, "downloaded": False, "fetched": True, "apis": list(entry["apis"])}
    config.CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=config.CACHE) as tmp:
        archive = pathlib.Path(tmp) / "archive.tar.gz"
        download(entry["url"], archive, entry["bytes"])
        if file_id(archive)["sha256"] != entry["sha256"]:
            raise paths.ToolError(f"{name}'s download does not match the SHA-256 this package pins; nothing was saved")
        unpack(archive, pathlib.Path(tmp) / "out")
        for item in entry.get("downloads", []):
            part = pathlib.Path(tmp) / "part.zip"
            download(item["url"], part, item["bytes"])
            digest = hashlib.sha512()
            with open(part, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    digest.update(block)
            if digest.hexdigest() != item["sha512"]:
                raise paths.ToolError(f"{name}'s {item['into']} download does not match the SHA-512 this package pins; nothing was saved")
            unzip(part, pathlib.Path(tmp) / "out" / entry["dir"] / item["into"])
            part.unlink()
        (pathlib.Path(tmp) / "out").rename(target)
    return {"name": name, "downloaded": True, "fetched": True, "bytes": entry["bytes"] + sum(d["bytes"] for d in entry.get("downloads", [])),
            "apis": list(entry["apis"])}


# the PresentMon console application perf_record uses on Windows, pinned by size and SHA-256
PRESENTMON = {
    "version": "2.6.0", "bytes": 980320,
    "sha256": "b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af",
    "url": "https://github.com/GameTechDev/PresentMon/releases/download/v2.6.0/PresentMon-2.6.0-x64.exe",
}


def tool_presentmon_install():
    """Windows only: downloads Intel's PresentMon console application (MIT) from its GitHub release, checks its
    SHA-256 against the one this package pins, and keeps it in %LOCALAPPDATA%\\metal-gpu-trace, where perf_record and
    perf_attach find it; later calls reuse it. It needs administrator rights or the Performance Log Users group to run."""
    if sys.platform != "win32":
        raise paths.ToolError("PresentMon runs only on Windows")
    target_dir = perf_record_windows.presentmon_dir()
    target = target_dir / f"PresentMon-{PRESENTMON['version']}-x64.exe"
    if target.is_file() and file_id(target)["sha256"] == PRESENTMON["sha256"]:
        return {"installed": False, "path": str(target), "version": PRESENTMON["version"]}
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target_dir) as tmp:
        part = pathlib.Path(tmp) / "PresentMon.exe"
        download(PRESENTMON["url"], part, PRESENTMON["bytes"] * 2)
        if file_id(part)["sha256"] != PRESENTMON["sha256"]:
            raise paths.ToolError("PresentMon's download does not match the SHA-256 this package pins; nothing was saved")
        part.replace(target)
    return {"installed": True, "path": str(target), "version": PRESENTMON["version"], "bytes": PRESENTMON["bytes"]}


def file_id(path):
    """Returns a file's size and SHA-256, read in 1 MiB blocks, or None when there is no such file."""
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
