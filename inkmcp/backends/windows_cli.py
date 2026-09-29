"""
Windows CLI Active Window Backend for inkmcp
Executes extension actions against running Inkscape GUI instances on Windows via inkscape.com.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from inkmcp.backends.base import InkscapeBackend
from inkmcp.platform_utils import (
    find_inkscape_executable,
    get_operating_system,
    is_extension_installed,
    is_inkscape_process_running,
)

logger = logging.getLogger("InkscapeMCP.Backend.WindowsCLI")

ACTION_NOPREFS = "org.khema.inkscape.mcp.noprefs"


class WindowsCliBackend(InkscapeBackend):
    """Executes Inkscape operations on Windows via inkscape.com -q --actions."""

    def __init__(self, inkscape_path: Optional[Path] = None):
        self._inkscape_path = inkscape_path or find_inkscape_executable()

    def is_available(self) -> bool:
        if get_operating_system() != "windows":
            return False
        if not self._inkscape_path or not Path(self._inkscape_path).is_file():
            logger.warning("WindowsCliBackend: inkscape.com executable not found")
            return False
        if not is_extension_installed():
            logger.warning("WindowsCliBackend: inkmcp extension not installed in %APPDATA%")
            return False
        return True

    def get_backend_name(self) -> str:
        return "windows_cli"

    def execute_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_available():
            return {
                "status": "error",
                "data": {
                    "error": (
                        "Windows Inkscape backend is unavailable. Ensure Inkscape 1.2+ is installed, "
                        "the MCP extension is installed in %APPDATA%\\inkscape\\extensions, "
                        "and inkscape.com is accessible."
                    )
                },
            }

        response_file = None
        params_file = os.path.join(tempfile.gettempdir(), "mcp_params.json")

        try:
            # 1. Prepare unique response file
            resp_fd, response_file = tempfile.mkstemp(
                suffix=".json", prefix="inkmcp_response_"
            )
            os.close(resp_fd)

            payload = dict(operation_data)
            payload["response_file"] = response_file

            # 2. Write parameter file
            with open(params_file, "w", encoding="utf-8") as pf:
                json.dump(payload, pf)

            # 3. Invoke Inkscape action via console binary
            # -q / --active-window directs action to existing running window
            cmd = [
                str(self._inkscape_path),
                "-q",
                f"--actions={ACTION_NOPREFS}",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.error(
                    "Inkscape command failed with code %d: %s",
                    result.returncode,
                    result.stderr,
                )
                return {
                    "status": "error",
                    "data": {
                        "error": f"Inkscape action execution failed (code {result.returncode}): {result.stderr.strip()}"
                    },
                }

            # 4. Read response from response file
            if not os.path.exists(response_file) or os.path.getsize(response_file) == 0:
                return {
                    "status": "error",
                    "data": {
                        "error": "Inkscape extension executed but produced no response file."
                    },
                }

            with open(response_file, "r", encoding="utf-8") as rf:
                return json.load(rf)

        except subprocess.TimeoutExpired:
            logger.error("Inkscape CLI action timed out")
            return {
                "status": "error",
                "data": {"error": "Inkscape action execution timed out (30s)"},
            }
        except Exception as e:
            logger.error("Windows CLI execution failed: %s", e)
            return {"status": "error", "data": {"error": str(e)}}
        finally:
            if response_file and os.path.exists(response_file):
                try:
                    os.remove(response_file)
                except OSError:
                    pass
            if os.path.exists(params_file):
                try:
                    os.remove(params_file)
                except OSError:
                    pass
