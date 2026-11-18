# metal-gpu-trace on Windows as a WinBridge job: installs the PUBLISHED package in a clean virtual environment and records,
# with perf_attach, a program that is already running (start it first, visible on the desktop, e.g. with the app-run job).
# Parameters: Process (the program's .exe name), Seconds, Label. METAL_TRACE_E2E_VERSION (manifest env) pins the version.
#
# WARNING: the job runner is elevated, so this downloads and runs code from PyPI as an administrator (same as metal-trace-e2e).
param(
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9_.-]{1,60}\.exe$')][string]$Process,
    [ValidatePattern('^[0-9]{1,3}$')][string]$Seconds = '30',
    [ValidatePattern('^[A-Za-z0-9_.-]{1,30}$')][string]$Label = 'attach'
)
$ErrorActionPreference = 'Continue'
$version = $env:METAL_TRACE_E2E_VERSION
if (-not $version) { Write-Output 'set METAL_TRACE_E2E_VERSION in the package manifest'; exit 2 }
if (-not (Get-Process -Name ($Process -replace '\.exe$', '') -ErrorAction SilentlyContinue)) { Write-Output "$Process is not running: start it first"; exit 6 }
$home_dir = Split-Path -Parent $env:METAL_TRACE_REPO
function Find-First($patterns) {
    foreach ($pattern in $patterns) {
        $hit = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}
$python = Find-First @((Join-Path $home_dir 'AppData\Roaming\uv\python\cpython-3.*\python.exe'), (Join-Path $home_dir 'AppData\Local\Programs\Python\Python3*\python.exe'), 'C:\Program Files\Python3*\python.exe')
if (-not $python) { Write-Output 'python not found'; exit 3 }
$venv = Join-Path $env:TEMP 'metal-trace-attach'
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
& $python -m venv $venv 2>&1 | Write-Output
$vpy = Join-Path $venv 'Scripts\python.exe'
& $vpy -m pip install --quiet --no-cache-dir "metal-gpu-trace==$version" 2>&1 | Write-Output
if ($LASTEXITCODE -ne 0) { Write-Output 'pip install failed'; exit 4 }  # fails closed: nothing runs if the pinned version is not on PyPI
$env:METAL_TRACE_OUT = Join-Path $env:TEMP 'metal-trace-attach-runs'
$code = @'
import json, sys
from metal_gpu_trace import recording
r = recording.tool_perf_attach(sys.argv[1], sys.argv[2], seconds=int(sys.argv[3]))
g = r.get("gpu", {})
print(json.dumps({"frames": g.get("frames"), "fps_estimate": g.get("fps_estimate"), "frame_gpu_ms": g.get("frame_gpu_ms"),
                  "api": (r.get("common") or {}).get("api"), "source": g.get("source")}))
assert g.get("frames", 0) >= 100, "fewer than 100 frames recorded"
'@
$pyfile = Join-Path $env:TEMP 'metal-trace-attach.py'
Set-Content -Path $pyfile -Value $code -Encoding UTF8
& $vpy -I $pyfile $Label $Process $Seconds 2>&1 | Write-Output
$exit = $LASTEXITCODE
Write-Output ('recording exit code: ' + $exit)
exit $exit
