# metal-gpu-trace on Windows, end to end, as a WinBridge job: installs the PUBLISHED package from PyPI in a clean virtual
# environment and records a short run of the drawstress workload (Direct3D 11, native) through the same tool the MCP
# server calls. It takes no parameters. METAL_TRACE_E2E_VERSION (manifest env) pins the version to test.
#
# WARNING: the job runner is elevated, so this downloads and runs code from PyPI and from this project's GitHub release
# (the workload archive is checked against a SHA-256 pinned in the package) as an administrator.
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
$python = Find-First @((Join-Path $home_dir 'AppData\Roaming\uv\python\cpython-3.*\python.exe'), (Join-Path $home_dir 'AppData\Local\Programs\Python\Python3*\python.exe'), 'C:\Program Files\Python3*\python.exe')
if (-not $python) { Write-Output 'python not found'; exit 3 }
$venv = Join-Path $env:TEMP 'metal-trace-e2e'
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
& $python -m venv $venv 2>&1 | Write-Output
$vpy = Join-Path $venv 'Scripts\python.exe'
& $vpy -m pip install --quiet --no-cache-dir "metal-gpu-trace==$version" 2>&1 | Write-Output
if ($LASTEXITCODE -ne 0) { Write-Output 'pip install failed'; exit 4 }
Write-Output ('windows: ' + [System.Environment]::OSVersion.VersionString)
Write-Output ('installed: ' + (& $vpy -I -c "import metal_gpu_trace.metal_trace_mcp as m; print(m.__version__)"))
$env:METAL_TRACE_OUT = Join-Path $env:TEMP 'metal-trace-e2e-runs'
$code = @'
import json, sys
from metal_gpu_trace import workloads, recording
print(json.dumps(workloads.tool_workload_fetch("drawstress")))
r = recording.tool_perf_record("e2e", workload="drawstress", api="d3d11", seconds=8, tier="light")
g = r.get("gpu", {})
print(json.dumps({"frames": g.get("frames"), "fps_estimate": g.get("fps_estimate"), "frame_gpu_ms": g.get("frame_gpu_ms"),
                  "start_latency_ms_present": "start_latency_ms" in g, "missing_tables": r.get("missing_tables"),
                  "template": r.get("template"), "noisy_environment": r.get("noisy_environment")}))
assert g.get("frames", 0) > 0, "no frames recorded"
'@
# a file, not -c: Windows drops the double quotes inside a -c argument
$pyfile = Join-Path $env:TEMP 'metal-trace-e2e.py'
Set-Content -Path $pyfile -Value $code -Encoding UTF8
& $vpy -I $pyfile 2>&1 | Write-Output
$exit = $LASTEXITCODE
Write-Output ('recording exit code: ' + $exit)
exit $exit
