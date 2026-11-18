# metal-gpu-trace on Windows as a WinBridge job: installs the PUBLISHED package in a clean virtual environment and records
# the drawstress workload (Direct3D 11, native) twice, once with the VegaFlow daemon stopped and once with it running, so a
# regression that only shows with (or without) the daemon is caught. It takes no parameters. METAL_TRACE_E2E_VERSION
# (manifest env) pins the version. The daemon is left in the state it was found in.
#
# WARNING: the job runner is elevated, so this downloads and runs code from PyPI as an administrator (same as metal-trace-e2e).
$ErrorActionPreference = 'Continue'
$version = $env:METAL_TRACE_E2E_VERSION
if (-not $version) { Write-Output 'set METAL_TRACE_E2E_VERSION in the package manifest'; exit 2 }
$home_dir = Split-Path -Parent $env:METAL_TRACE_REPO
function Find-First($patterns) {
    foreach ($pattern in $patterns) {
        $hit = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}
function Daemon-Running { return [bool](Get-Process -Name 'vegaflow_daemon' -ErrorAction SilentlyContinue) }
function Set-Daemon($on) {
    Start-ScheduledTask -TaskName $(if ($on) { 'VegaFlow-Start' } else { 'VegaFlow-Stop' }) -ErrorAction Stop
    for ($i = 0; $i -lt 30 -and ((Daemon-Running) -ne $on); $i++) { Start-Sleep -Seconds 1 }
    if ((Daemon-Running) -ne $on) { Write-Output ('the daemon did not ' + $(if ($on) { 'start' } else { 'stop' })); return $false }
    return $true
}
$python = Find-First @((Join-Path $home_dir 'AppData\Roaming\uv\python\cpython-3.*\python.exe'), (Join-Path $home_dir 'AppData\Local\Programs\Python\Python3*\python.exe'), 'C:\Program Files\Python3*\python.exe')
if (-not $python) { Write-Output 'python not found'; exit 3 }
$venv = Join-Path $env:TEMP 'metal-trace-daemon'
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
& $python -m venv $venv 2>&1 | Write-Output
$vpy = Join-Path $venv 'Scripts\python.exe'
& $vpy -m pip install --quiet --no-cache-dir "metal-gpu-trace==$version" 2>&1 | Write-Output
if ($LASTEXITCODE -ne 0) { Write-Output 'pip install failed'; exit 4 }  # fails closed: nothing runs if the pinned version is not on PyPI
$env:METAL_TRACE_OUT = Join-Path $env:TEMP 'metal-trace-daemon-runs'
$code = @'
import json, sys
from metal_gpu_trace import workloads, recording
label = sys.argv[1]
workloads.tool_workload_fetch("drawstress")
g = recording.tool_perf_record(label, workload="drawstress", api="d3d11", seconds=8, tier="light").get("gpu", {})
print(json.dumps({"case": label, "frames": g.get("frames"), "fps_estimate": g.get("fps_estimate")}))
assert g.get("frames", 0) > 0, "no frames recorded"
'@
$pyfile = Join-Path $env:TEMP 'metal-trace-daemon.py'
Set-Content -Path $pyfile -Value $code -Encoding UTF8
$was = Daemon-Running
$exit = 0
try {
    foreach ($case in @(@('without-daemon', $false), @('with-daemon', $true))) {
        if (-not (Set-Daemon $case[1])) { $exit = 5; break }
        & $vpy -I $pyfile $case[0] 2>&1 | Write-Output
        if ($LASTEXITCODE -ne 0) { $exit = $LASTEXITCODE }
        Get-Process -Name 'drawstress' -ErrorAction SilentlyContinue | Stop-Process -Force  # no program left running
    }
} finally {
    [void](Set-Daemon $was)
}
Write-Output ('exit code: ' + $exit)
exit $exit
