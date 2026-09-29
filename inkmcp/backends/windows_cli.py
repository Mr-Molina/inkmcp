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
)

logger = logging.getLogger("InkscapeMCP.Backend.WindowsCLI")

ACTION_NOPREFS = "org.khema.inkscape.mcp.noprefs"


class WindowsCliBackend(InkscapeBackend):
    """Executes Inkscape operations on Windows via inkscape.com -q --actions."""

    def __init__(self, inkscape_path: Optional[Path] = None):
        self._inkscape_path = inkscape_path or find_inkscape_executable()

    def is_available(self) -> bool:
        """Check if Windows CLI backend is available on the current system.

        Returns:
            True if running on Windows, inkscape.com exists, and the MCP extension
            is installed in %APPDATA%\\inkscape\\extensions; False otherwise.
        """
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
        """Return the unique identifier for this backend ('windows_cli')."""
        return "windows_cli"

    def execute_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an Inkscape operation against an active Windows Inkscape session.

        Writes operation data to a temporary parameter file, invokes
        `inkscape.com -q --actions="org.khema.inkscape.mcp.noprefs"`,
        validates path containment, reads the structured response file,
        and safely cleans up temporary files.

        Args:
            operation_data: Dictionary specifying the operation type and parameters.

        Returns:
            Dictionary with operation status and response data or error details.
        """
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

        response_file = operation_data.get("response_file")
        params_file = os.path.join(tempfile.gettempdir(), "mcp_params.json")
        created_temp_response = False
        is_safe = False

        try:
            # 1. Prepare unique response file if not provided
            if not response_file:
                resp_fd, response_file = tempfile.mkstemp(
                    suffix=".json", prefix="inkmcp_response_"
                )
                os.close(resp_fd)
                created_temp_response = True

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
                err_msg = (result.stderr or "").strip() or (result.stdout or "").strip()
                logger.error(
                    "Inkscape command failed with code %d: %s",
                    result.returncode,
                    err_msg,
                )
                return {
                    "status": "error",
                    "data": {
                        "error": f"Inkscape action execution failed (code {result.returncode}): {err_msg}"
                    },
                }

            # 4. Validate response_file realpath resides strictly inside tempfile.gettempdir()
            temp_dir = os.path.realpath(tempfile.gettempdir())
            resp_real = os.path.realpath(response_file)
            try:
                is_safe = (
                    os.path.commonpath([temp_dir, resp_real]) == temp_dir
                    and resp_real != temp_dir
                )
            except (ValueError, TypeError):
                is_safe = False

            if not is_safe:
                logger.error("Response file path outside temp directory: %s", response_file)
                return {
                    "status": "error",
                    "data": {
                        "error": f"Response file error: Path outside temp directory: {response_file}"
                    },
                }

            # 5. Read response from response file
            if not os.path.exists(resp_real) or os.path.getsize(resp_real) == 0:
                return {
                    "status": "error",
                    "data": {
                        "error": "Inkscape extension executed but produced no response file."
                    },
                }

            with open(resp_real, "r", encoding="utf-8") as rf:
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
            if response_file and (is_safe or created_temp_response) and os.path.exists(response_file):
                try:
                    os.remove(response_file)
                except OSError:
                    pass
            if os.path.exists(params_file):
                try:
                    os.remove(params_file)
                except OSError:
                    pass
