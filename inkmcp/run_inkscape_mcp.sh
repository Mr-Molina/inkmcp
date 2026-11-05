#!/bin/bash
# Inkscape MCP Server Wrapper Script
# Activates Python environment and runs the MCP server

set -e

# Resolve script directory and parent repository directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$SCRIPT_DIR"

# Activate Python virtual environment (create if doesn't exist)
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..." >&2
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt >&2
else
    source venv/bin/activate
fi

# Ensure access to the user's D-Bus session bus
# Allow overrides if already provided in the environment
# These following exports are required for sandboxed envs like codex not for Claude
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

export PYTHONPATH="${PARENT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

# Run the Inkscape MCP server
exec python -m inkmcp.inkscape_mcp_server
