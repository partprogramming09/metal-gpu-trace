<#
.SYNOPSIS
    One command, as administrator, to update the metal-gpu-trace WinBridge jobs on this PC.
.DESCRIPTION
    Reads the SHA-256 of runner.ps1 from the manifest.json of a VERIFIED WinBridge bundle (file
    bootstrap/jobs/runner.ps1) and runs the bundle's Install-WinBridgeJobs.ps1 with -Update and the jobs in
    windows\winbridge-job\ next to this script. Nothing is run from AppData\Local\winbridge\bin\jobs: the agent
    account can write there.
.PARAMETER Bundle
    Folder of the verified, freshly extracted WinBridge bundle (the one that holds bootstrap\jobs\). Required.
.PARAMETER Packages
    Folder that holds the job packages. Default (when omitted): windows\winbridge-job\ next to this script.
.PARAMETER DryRun
    Resolve paths and the hash and print the command, without running it (works without administrator).
.EXAMPLE
    .\windows\Update-MetalTraceJobs.ps1 -Bundle C:\path\to\verified-bundle
#>
param(
    [Parameter(Mandatory = $true)][string]$Bundle,
    [string]$Packages,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'

# $PSScriptRoot is empty inside param() on Windows PowerShell 5.1, so the default is resolved here.
if (-not $Packages) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    if (-not $here) { throw 'Cannot tell where this script lives; pass -Packages explicitly.' }
    $Packages = Join-Path $here 'winbridge-job'
}

if (-not (Test-Path -LiteralPath $Bundle -PathType Container)) { throw "-Bundle folder not found: $Bundle" }
$Bundle = (Resolve-Path -LiteralPath $Bundle).Path
if (-not (Test-Path -LiteralPath $Packages -PathType Container)) { throw "-Packages folder not found: $Packages" }
$Packages = (Resolve-Path -LiteralPath $Packages).Path

$installer = Join-Path $Bundle 'bootstrap\jobs\Install-WinBridgeJobs.ps1'
if (-not (Test-Path -LiteralPath $installer)) { throw "Install-WinBridgeJobs.ps1 not found in the bundle: $installer" }
$manifestPath = Join-Path $Bundle 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw "manifest.json not found in the bundle (is it a verified WinBridge bundle?): $manifestPath" }

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$entry = @($manifest.files | Where-Object { [string]$_.path -eq 'bootstrap/jobs/runner.ps1' })
if ($entry.Count -ne 1) { throw 'manifest.json has no single entry for bootstrap/jobs/runner.ps1; cannot get the runner hash.' }
$hash = [string]$entry[0].sha256
if ($hash -notmatch '^[A-Fa-f0-9]{64}$') { throw 'the runner.ps1 hash in manifest.json is not a SHA-256.' }

Write-Output "bundle:   $Bundle"
Write-Output "packages: $Packages"
Write-Output "runner:   $hash"
Write-Output "command:  & '$installer' -Packages '$Packages' -Update -RunnerSha256 $hash"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($DryRun) {
    if (-not $admin) { Write-Output 'note: not running as administrator; the real run needs it.' }
    Write-Output 'dry run: nothing was changed.'
    return
}
if (-not $admin) { throw 'Run this script as administrator (elevated PowerShell).' }

& $installer -Packages $Packages -Update -RunnerSha256 $hash
if (-not $?) { throw 'Install-WinBridgeJobs.ps1 failed.' }

Write-Output 'Updated. If runner.ps1 changed, restart the WinBridgeJobs-Run task when no job is running. To try it from the Mac:'
Write-Output '  winbridge jobs --host hernan run metal-trace-daemon'
