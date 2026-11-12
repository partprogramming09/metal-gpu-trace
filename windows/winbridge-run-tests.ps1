# Runs metal-gpu-trace's Windows tests on this machine: updates the checkout and runs tests/test_perf_record_windows.py.
# Meant as a WinBridge task (fixed name, script pinned by SHA-256, no arguments). Edit $repo to the checkout's path,
# then register the script's new SHA-256 in the agent's TOML.
$repo = Join-Path $env:USERPROFILE 'metal-gpu-trace'
if (-not (Test-Path (Join-Path $repo 'tests\test_perf_record_windows.py'))) { Write-Output "no checkout at $repo"; exit 2 }
Set-Location $repo
git pull --ff-only 2>&1 | Write-Output
Write-Output ("windows: " + [System.Environment]::OSVersion.VersionString)
Write-Output ("python: " + (python --version 2>&1))
Write-Output ("commit: " + (git rev-parse --short HEAD))
python -m pytest --version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Output "pytest is not installed: python -m pip install pytest"; exit 3 }
python -m pytest tests\test_perf_record_windows.py -v 2>&1 | Write-Output
exit $LASTEXITCODE
