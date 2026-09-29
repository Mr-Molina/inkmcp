"""Inkscape MCP package"""

import sys
from pathlib import Path

# Ensure repo root (containing inkscape_mcp.py) and user extension directory
# are in sys.path when running globally or outside repository root.
_repo_root = Path(__file__).resolve().parent.parent
if (_repo_root / "inkscape_mcp.py").exists() and str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

try:
    from inkmcp.platform_utils import get_inkscape_extensions_dir
    _ext_dir = get_inkscape_extensions_dir()
    if (_ext_dir / "inkscape_mcp.py").exists() and str(_ext_dir) not in sys.path:
        sys.path.append(str(_ext_dir))
except Exception:
    pass