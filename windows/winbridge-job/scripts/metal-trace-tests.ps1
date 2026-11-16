# metal-gpu-trace on Windows, as a WinBridge job: updates a checkout and runs its tests. It takes no parameters.
#
# WARNING: the job runner is elevated, so this runs Python code from the checkout as an administrator. Install it only
# if the checkout is a folder that nobody but you (and administrators) can write to. Set METAL_TRACE_REPO in
# manifest.json before installing; the runner has a minimal PATH, so Git and Python are looked for in the usual places.
$ErrorActionPreference = 'Continue'
$repo = $env:METAL_TRACE_REPO
if (-not $repo -or -not (Test-Path (Join-Path $repo 'tests\test_perf_record_windows.py'))) {
    Write-Output 'no checkout: set METAL_TRACE_REPO in the package manifest'
    exit 2
}
function Find-First($patterns) {
    foreach ($pattern in $patterns) {
        $hit = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}
$home_dir = Split-Path -Parent $repo
$git = Find-First @('C:\Program Files\Git\cmd\git.exe', 'C:\Program Files (x86)\Git\cmd\git.exe', (Join-Path $home_dir 'AppData\Local\Programs\Git\cmd\git.exe'))
$python = Find-First @((Join-Path $home_dir 'AppData\Roaming\uv\python\cpython-3.*\python.exe'), (Join-Path $home_dir 'AppData\Local\Programs\Python\Python3*\python.exe'), 'C:\Program Files\Python3*\python.exe', 'C:\Python3*\python.exe')
Set-Location $repo
if ($git) { $env:PATH = (Split-Path -Parent $git) + ';' + $env:PATH }  # the tests call git, and the runner's PATH has none
if ($git) { & $git pull --ff-only 2>&1 | Write-Output } else { Write-Output 'git not found: testing the checkout as it is' }
Write-Output ('windows: ' + [System.Environment]::OSVersion.VersionString)
if (-not $python) { Write-Output 'python not found (looked under the parent folder of the checkout, Program Files and C:\)'; exit 3 }
Write-Output ('python: ' + (& $python --version 2>&1))
if ($git) { Write-Output ('commit: ' + (& $git rev-parse --short HEAD)) }
& $python -m pytest --version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Output 'pytest is not installed for that python: python -m pip install pytest'; exit 4 }
# Start-Process gives the real exit code (a pipeline hid a pytest that ended early); -v names the last test started, and
# -rs lists every skipped test with its reason (the ones that need a desktop session, for example).
$out = Join-Path $env:TEMP 'metal-trace-pytest.out'
$err = Join-Path $env:TEMP 'metal-trace-pytest.err'
$proc = Start-Process -FilePath $python -ArgumentList @('-m', 'pytest', 'tests\test_perf_record_windows.py', '-v', '-rs', '--tb=short', '-p', 'no:cacheprovider') `
    -WorkingDirectory $repo -NoNewWindow -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
Get-Content $out -ErrorAction SilentlyContinue | Write-Output
Get-Content $err -ErrorAction SilentlyContinue | Write-Output
$summary = Get-Content $out -Tail 1 -ErrorAction SilentlyContinue
Write-Output ('pytest exit code: ' + $proc.ExitCode)
if ($summary -notmatch '(passed|failed|error)') { Write-Output 'pytest ended without a summary line: the run is incomplete'; exit 5 }
exit $proc.ExitCode
