# metal-gpu-trace on Windows, as a WinBridge job: tests (the Windows ones) and records a BRANCH of this project without touching the
# checkout. It takes no parameters; METAL_TRACE_BRANCH (manifest env) names the branch on origin. It exports that branch
# with `git archive` to a temporary folder, runs the Windows tests from there, installs it in a clean virtual environment and
# records drawstress in Direct3D 11 and Direct3D 12 through the same tool the MCP server calls, printing the summary's
# `common` block. It then records two more Direct3D 11 runs and judges the second against the first with perf_check
# (margin 0), printing the verdict and its note.
#
# WARNING: the job runner is elevated, so this runs code from that branch as an administrator. Point METAL_TRACE_BRANCH
# only at a branch you have read, and install this job only if the checkout (METAL_TRACE_REPO) is a folder that nobody but
# you and administrators can write to: git runs elevated on it.
$ErrorActionPreference = 'Continue'
$branch = $env:METAL_TRACE_BRANCH
# no leading '-' (a git option), no '..' or '//' (an ambiguous ref)
if (-not $branch -or $branch -notmatch '^(?!-)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,80}$') { Write-Output 'set METAL_TRACE_BRANCH in the package manifest'; exit 2 }
$repo = $env:METAL_TRACE_REPO
if (-not (Test-Path (Join-Path $repo '.git'))) { Write-Output 'no checkout at METAL_TRACE_REPO'; exit 2 }
$home_dir = Split-Path -Parent $repo
function Find-First($patterns) {
    foreach ($pattern in $patterns) {
        $hit = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}
$git = Find-First @('C:\Program Files\Git\cmd\git.exe', 'C:\Program Files (x86)\Git\cmd\git.exe', (Join-Path $home_dir 'AppData\Local\Programs\Git\cmd\git.exe'))
if (-not $git) { Write-Output 'git not found'; exit 3 }
$python = Find-First @((Join-Path $home_dir 'AppData\Roaming\uv\python\cpython-3.*\python.exe'), (Join-Path $home_dir 'AppData\Local\Programs\Python\Python3*\python.exe'), 'C:\Program Files\Python3*\python.exe')
if (-not $python) { Write-Output 'python not found'; exit 3 }
Set-Location $repo
# the full ref, so a tag or HEAD named like the branch is not fetched instead
& $git fetch --quiet origin "refs/heads/$branch" 2>&1 | Write-Output
if ($LASTEXITCODE -ne 0) { Write-Output "git fetch failed for $branch"; exit 4 }
$commit = (& $git rev-parse --short FETCH_HEAD)
# a folder of its own for this run, never one that is there already
$work = Join-Path $env:TEMP ('metal-trace-branch-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work -ErrorAction Stop | Out-Null
$zip = Join-Path $work 'src.zip'
& $git archive --format=zip --output=$zip FETCH_HEAD 2>&1 | Write-Output
if ($LASTEXITCODE -ne 0) { Write-Output 'git archive failed'; exit 4 }
$src = Join-Path $work 'src'
Expand-Archive -Path $zip -DestinationPath $src -ErrorAction Stop
if (-not (Test-Path (Join-Path $src 'tests\run.py'))) { Write-Output 'the branch has no tests\run.py'; exit 4 }
Write-Output ('windows: ' + [System.Environment]::OSVersion.VersionString)
Write-Output ("branch: $branch commit: $commit")
Set-Location $src -ErrorAction Stop
Write-Output '--- test suite ---'
# the Windows tests, as the metal-trace-tests job runs them (the rest of the suite describes macOS)
& $python -m pytest tests\test_perf_record_windows.py -q --tb=short -p no:cacheprovider 2>&1 | Select-Object -Last 8 | Write-Output
$testsExit = $LASTEXITCODE
Write-Output ('tests exit code: ' + $testsExit)
$venv = Join-Path $work 'venv'
& $python -m venv $venv 2>&1 | Write-Output
if ($LASTEXITCODE -ne 0) { Write-Output 'venv failed'; exit 5 }
$vpy = Join-Path $venv 'Scripts\python.exe'
& $vpy -m pip install --quiet --no-cache-dir $src 2>&1 | Write-Output
if ($LASTEXITCODE -ne 0) { Write-Output 'pip install failed'; exit 5 }
Write-Output ('installed: ' + (& $vpy -I -c "import metal_gpu_trace.metal_trace_mcp as m; print(m.__version__)"))
$env:METAL_TRACE_OUT = Join-Path $work 'runs'
$code = @'
import json, sys
from metal_gpu_trace import workloads, recording
workloads.tool_workload_fetch("drawstress")
status = 0
for api in ("d3d11", "d3d12"):
    r = recording.tool_perf_record("branch-" + api, workload="drawstress", api=api, seconds=8, tier="light")
    g = r.get("gpu", {})
    print(json.dumps({"api": api, "schema_version": r.get("schema_version"), "frames": g.get("frames"),
                      "fps_estimate": g.get("fps_estimate"), "common": r.get("common")}))
    if not g.get("frames"):
        status = 1
# two more runs of the same load: one is saved as a reference, the other judged against it with margin 0 (so two equal
# runs can leave a range that is a point), to show the note that says a one-run reference has no measured noise
from metal_gpu_trace import analysis
for label in ("check-a", "check-b"):
    r = recording.tool_perf_record(label, workload="drawstress", api="d3d11", seconds=8, tier="light")
    if not r.get("gpu", {}).get("frames"):
        status = 1
names = {x["run"].split("_")[0]: x["run"] for x in analysis.tool_perf_runs()["rows"]}
analysis.tool_perf_baseline("branch-check", runs=[names["check-a"]])
c = analysis.tool_perf_check(names["check-b"], "branch-check", margin_pct=0)
print(json.dumps({k: c.get(k) for k in ("verdict", "margin_pct", "regressed", "improved", "note")}))
sys.exit(status)
'@
# a file, not -c: Windows drops the double quotes inside a -c argument
$pyfile = Join-Path $work 'record.py'
Set-Content -Path $pyfile -Value $code -Encoding UTF8
& $vpy -I $pyfile 2>&1 | Write-Output
$exit = $LASTEXITCODE
Write-Output ('recording exit code: ' + $exit)
Set-Location $env:TEMP
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue  # the folder this run made
if ($exit -eq 0 -and $testsExit -ne 0) { $exit = $testsExit }  # a branch with failing tests does not pass
exit $exit
