<#
.SYNOPSIS
Installs inkmcp extension into Inkscape AppData extensions directory.
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Check,
    [switch]$DryRun,
    [string]$TargetDir
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$ArgsList = @("$ScriptDir\inkmcp\install_extension.py")
if ($Force) { $ArgsList += "--force" }
if ($Check) { $ArgsList += "--check" }
if ($DryRun) { $ArgsList += "--dry-run" }
if ($TargetDir) { $ArgsList += @("--target-dir", $TargetDir) }

Write-Host "Running inkmcp extension installer..." -ForegroundColor Cyan
& python @ArgsList
if ($LASTEXITCODE -ne 0) {
    Write-Error "Extension installation failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "Extension setup completed." -ForegroundColor Green
