"""
Linux/Unix D-Bus Backend for inkmcp
Executes extension actions against running Inkscape GUI instances via D-Bus org.gtk.Actions.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Optional

from inkmcp.backends.base import InkscapeBackend

logger = logging.getLogger("InkscapeMCP.Backend.DBus")

DEFAULT_DBUS_SERVICE = "org.inkscape.Inkscape"
DEFAULT_DBUS_PATH = "/org/inkscape/Inkscape"
DEFAULT_DBUS_INTERFACE = "org.gtk.Actions"
DEFAULT_ACTION_NAME = "org.khema.inkscape.mcp"


class DBusBackend(InkscapeBackend):
    """Executes Inkscape operations via D-Bus session bus."""

    def __init__(
        self,
        dbus_service: str = DEFAULT_DBUS_SERVICE,
        dbus_path: str = DEFAULT_DBUS_PATH,
        dbus_interface: str = DEFAULT_DBUS_INTERFACE,
        action_name: str = DEFAULT_ACTION_NAME,
    ):
        self.dbus_service = dbus_service
        self.dbus_path = dbus_path
        self.dbus_interface = dbus_interface
        self.action_name = action_name

    def is_available(self) -> bool:
        """Check if gdbus is installed and Inkscape D-Bus action is available."""
        if not shutil.which("gdbus"):
            logger.warning("gdbus executable not found in system PATH")
            return False

        try:
            cmd = [
                "gdbus",
                "call",
                "--session",
                "--dest",
                self.dbus_service,
                "--object-path",
                self.dbus_path,
                "--method",
                f"{self.dbus_interface}.List",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

            if result.returncode != 0:
                logger.warning("Inkscape D-Bus service not available")
                return False

            return self.action_name in result.stdout

        except Exception as e:
            logger.error("Error checking Inkscape D-Bus availability: %s", e)
            return False

    def get_backend_name(self) -> str:
        """Return unique backend identifier ('dbus')."""
        return "dbus"

    def execute_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute operation via D-Bus action invocation."""
        response_file = operation_data.get("response_file")
        params_file = None
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

            # 2. Write operation data to temporary parameter file
            params_fd, params_file = tempfile.mkstemp(
                suffix=".json", prefix="inkmcp_params_"
            )
            with os.fdopen(params_fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)

            # 3. Execute via D-Bus
            cmd = [
                "gdbus",
                "call",
                "--session",
                "--dest",
                self.dbus_service,
                "--object-path",
                self.dbus_path,
                "--method",
                f"{self.dbus_interface}.Activate",
                self.action_name,
                f"[<'{params_file}'>]",
                "{}",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                logger.error("D-Bus command failed: %s", result.stderr)
                return {
                    "status": "error",
                    "data": {"error": f"D-Bus call failed: {result.stderr}"},
                }

            # 4. Validate response_file realpath resides strictly inside tempfile.gettempdir() (SEC-002)
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
                    "data": {"error": f"Response file error: Path outside temp directory: {response_file}"},
                }

            # 5. Verify response file exists and has non-zero size (SEC-003)
            if not os.path.exists(resp_real) or os.path.getsize(resp_real) == 0:
                logger.error("Response file missing or empty: %s", response_file)
                return {
                    "status": "error",
                    "data": {"error": "Response file error: Extension failed to produce output (file missing or empty)"},
                }

            with open(resp_real, "r", encoding="utf-8") as f:
                return json.load(f)

        except subprocess.TimeoutExpired:
            logger.error("D-Bus operation timed out")
            return {"status": "error", "data": {"error": "Operation timed out"}}
        except Exception as e:
            logger.error("D-Bus operation execution error: %s", e)
            return {"status": "error", "data": {"error": str(e)}}
        finally:
            if response_file and (is_safe or created_temp_response) and os.path.exists(response_file):
                try:
                    os.remove(response_file)
                except OSError:
                    pass
            if params_file and os.path.exists(params_file):
                try:
                    os.remove(params_file)
                except OSError:
                    pass
