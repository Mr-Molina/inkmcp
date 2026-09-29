<#
.SYNOPSIS
Inkscape MCP Server Wrapper Script for Windows PowerShell
Activates Python environment and launches the MCP server.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

# Ensure parent directory (repo root or extensions dir) is in PYTHONPATH for inkmcp package discovery
$ParentDir = Split-Path -Parent $ScriptDir
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$ParentDir;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $ParentDir
}

$VenvDir = Join-Path $ScriptDir "venv"

if (-not (Test-Path $VenvDir)) {
    [Console]::Error.WriteLine("Creating Python virtual environment...")
    & python -m venv "$VenvDir"
    & "$VenvDir\Scripts\python.exe" -m pip install -r "$ScriptDir\requirements.txt" | Out-Null
}

$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python.exe"
}

# Run the Inkscape MCP server with stdout reserved for JSON-RPC
& $PythonExe -m inkmcp.inkscape_mcp_server
exit $LASTEXITCODE
