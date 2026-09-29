@echo off
setlocal
cd /d "%~dp0"

rem Ensure parent directory (repo root or extensions dir) is in PYTHONPATH for inkmcp package discovery
if defined PYTHONPATH (
    set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%~dp0.."
)

if not exist "venv\" (
    echo Creating Python virtual environment... >&2
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt >&2
) else (
    call venv\Scripts\activate.bat
)

python -m inkmcp.inkscape_mcp_server
endlocal
