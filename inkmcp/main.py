#!/usr/bin/env python3
"""
Entry point for Inkscape MCP Server
"""

try:
    from inkmcp.inkscape_mcp_server import main
except ImportError:
    from inkscape_mcp_server import main

if __name__ == "__main__":
    main()