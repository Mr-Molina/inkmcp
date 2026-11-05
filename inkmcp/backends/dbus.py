"""
Linux/Unix D-Bus Backend for inkmcp
Executes extension actions against running Inkscape GUI instances via D-Bus org.gtk.Actions.
"""

import errno
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from inkmcp.backends.base import InkscapeBackend

logger = logging.getLogger("InkscapeMCP.Backend.DBus")

DEFAULT_DBUS_SERVICE = "org.inkscape.Inkscape"
DEFAULT_DBUS_PATH = "/org/inkscape/Inkscape"
DEFAULT_DBUS_INTERFACE = "org.gtk.Actions"
DEFAULT_ACTION_NAME = "org.khema.inkscape.mcp"
DEFAULT_TIMEOUT = 30

# Module-level lock to prevent concurrent workers from clobbering /tmp/mcp_params.json (BKD-001)
_DBUS_EXECUTION_LOCK = threading.Lock()

# Strict D-Bus identifier validation regexes (BKD-004)
# Service name: well-known (e.g. org.inkscape.Inkscape) or unique (:1.42)
_DBUS_SERVICE_REGEX = re.compile(
    r"^(:[a-zA-Z0-9_-]+|[a-zA-Z_-][a-zA-Z0-9_-]*)(\.[a-zA-Z0-9_-]+)+$"
)
# Object path: starts with '/', slash-separated elements containing [a-zA-Z0-9_]
_DBUS_PATH_REGEX = re.compile(r"^/([a-zA-Z0-9_]+(/[a-zA-Z0-9_]+)*)?$")
# Interface name: dot-separated elements containing [a-zA-Z0-9_], at least one dot
_DBUS_INTERFACE_REGEX = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$"
)
# Action name: alphanumeric, dots, underscores, hyphens (e.g. org.khema.inkscape.mcp)
_ACTION_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_]+([.-][a-zA-Z0-9_-]+)*$")


class DBusBackend(InkscapeBackend):
    """Executes Inkscape operations via D-Bus session bus."""

    def __init__(
        self,
        dbus_service: Optional[str] = None,
        dbus_path: Optional[str] = None,
        dbus_interface: Optional[str] = None,
        action_name: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        *,
        service_name: Optional[str] = None,
        object_path: Optional[str] = None,
        interface: Optional[str] = None,
    ):
        service = service_name if service_name is not None else (
            dbus_service if dbus_service is not None else DEFAULT_DBUS_SERVICE
        )
        path = object_path if object_path is not None else (
            dbus_path if dbus_path is not None else DEFAULT_DBUS_PATH
        )
        iface = interface if interface is not None else (
            dbus_interface if dbus_interface is not None else DEFAULT_DBUS_INTERFACE
        )
        action = action_name if action_name is not None else DEFAULT_ACTION_NAME

        if not _DBUS_SERVICE_REGEX.match(service):
            raise ValueError(f"Invalid D-Bus service name: {service!r}")
        if not _DBUS_PATH_REGEX.match(path):
            raise ValueError(f"Invalid D-Bus object path: {path!r}")
        if not _DBUS_INTERFACE_REGEX.match(iface):
            raise ValueError(f"Invalid D-Bus interface: {iface!r}")
        if not _ACTION_NAME_REGEX.match(action):
            raise ValueError(f"Invalid D-Bus action name: {action!r}")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(f"Timeout must be a positive number: {timeout!r}")

        self.dbus_service = service
        self.service_name = service
        self.dbus_path = path
        self.object_path = path
        self.dbus_interface = iface
        self.interface = iface
        self.action_name = action
        self.timeout = int(timeout)

    def _get_dbus_env(self) -> Dict[str, str]:
        """Return environment dictionary with XDG_RUNTIME_DIR and DBUS_SESSION_BUS_ADDRESS populated if unset."""
        env = os.environ.copy()
        if hasattr(os, "getuid"):
            uid = os.getuid()
            runtime_dir = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
            if "XDG_RUNTIME_DIR" not in env and os.path.isdir(runtime_dir):
                env["XDG_RUNTIME_DIR"] = runtime_dir
            bus_path = f"{runtime_dir}/bus"
            if "DBUS_SESSION_BUS_ADDRESS" not in env and os.path.exists(bus_path):
                env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"
        return env

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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=min(self.timeout, 5),
                env=self._get_dbus_env(),
                check=False,
            )

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
        with _DBUS_EXECUTION_LOCK:
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

                # Validate response_file realpath resides strictly inside tempfile.gettempdir() (SEC-033)
                temp_dir_path = Path(tempfile.gettempdir()).resolve()
                try:
                    resp_path = Path(response_file).resolve()
                    is_safe = resp_path.is_relative_to(temp_dir_path) and resp_path != temp_dir_path
                except (ValueError, TypeError, Exception):
                    is_safe = False

                if not is_safe:
                    logger.error("Response file path outside temp directory: %s", response_file)
                    return {
                        "status": "error",
                        "data": {"error": f"Response file error: Path outside temp directory: {response_file}"},
                    }

                payload = dict(operation_data)
                payload["response_file"] = response_file

                # 2. Write operation data to canonical parameter file expected by Inkscape action (BKD-001, BKD-005)
                params_file = os.path.join(tempfile.gettempdir(), "mcp_params.json")
                flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
                params_fd = -1
                for _ in range(3):
                    try:
                        params_fd = os.open(params_file, flags, 0o600)
                        break
                    except OSError as err:
                        if err.errno == getattr(errno, "ELOOP", 40):
                            try:
                                os.unlink(params_file)
                            except OSError:
                                pass
                            continue
                        raise

                if params_fd < 0:
                    raise OSError(f"Failed to open parameters file: {params_file}")

                if hasattr(os, "getuid"):
                    st = os.fstat(params_fd)
                    if st.st_uid != os.getuid():
                        os.close(params_fd)
                        raise PermissionError(
                            f"Parameters file {params_file} is owned by UID {st.st_uid}, expected {os.getuid()}"
                        )

                with os.fdopen(params_fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f)

                # 3. Execute via D-Bus (Inkscape Gio.Action signature for extensions is empty '')
                dbus_env = self._get_dbus_env()
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
                    "[]",
                    "{}",
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    env=dbus_env,
                    check=False,
                )

                if result.returncode != 0:
                    logger.error("D-Bus command failed: %s", result.stderr)
                    return {
                        "status": "error",
                        "data": {"error": f"D-Bus call failed: {result.stderr}"},
                    }

                # 4. Verify response file exists and has non-zero size (SEC-003)
                resp_real = str(Path(response_file).resolve())
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

    async def is_available_async(self) -> bool:
        """Async-compatible wrapper for is_available to prevent event loop starvation."""
        import asyncio
        return await asyncio.to_thread(self.is_available)

    async def execute_operation_async(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Async-compatible wrapper for execute_operation to prevent event loop starvation."""
        import asyncio
        return await asyncio.to_thread(self.execute_operation, operation_data)
