<#
.SYNOPSIS
Installs inkmcp extension into Inkscape AppData extensions directory.
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Check
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$ArgsList = @("$ScriptDir\inkmcp\install_extension.py")
if ($Force) { $ArgsList += "--force" }
if ($Check) { $ArgsList += "--check" }

Write-Host "Running inkmcp extension installer..." -ForegroundColor Cyan
& python @ArgsList
if ($LASTEXITCODE -ne 0) {
    Write-Error "Extension installation failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "Extension setup completed." -ForegroundColor Green
