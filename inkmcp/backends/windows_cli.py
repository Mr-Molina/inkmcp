"""
Windows CLI Active Window Backend for inkmcp
Executes extension actions against running Inkscape GUI instances on Windows via inkscape.com.
"""

import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import msvcrt
except ImportError:
    msvcrt = None

from inkmcp.backends.base import InkscapeBackend
from inkmcp.platform_utils import (
    find_inkscape_executable,
    get_operating_system,
    is_extension_installed,
)

logger = logging.getLogger("InkscapeMCP.Backend.WindowsCLI")

ACTION_NOPREFS = "org.khema.inkscape.mcp.noprefs"


class _ActionLock:
    """Exclusive file lock to serialize in-flight Windows CLI operations and prevent mcp_params.json collisions.

    On Windows, uses msvcrt.locking for kernel-level byte locking, which automatically
    releases if the process crashes or terminates. On non-Windows platforms or when msvcrt
    is unavailable, falls back to atomic file creation via os.O_CREAT | os.O_EXCL.
    """

    def __init__(
        self,
        lock_path: Optional[str] = None,
        timeout: float = 35.0,
        poll_interval: float = 0.05,
    ):
        self.lock_path = lock_path or os.path.join(
            tempfile.gettempdir(), "inkmcp_action.lock"
        )
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._fd: Optional[int] = None
        self._acquired = False

    def acquire(self) -> bool:
        """Acquire the exclusive lock within the configured timeout.

        Raises:
            TimeoutError: If the lock cannot be acquired before timeout expires.
        """
        if self._acquired:
            return True

        start_time = time.monotonic()
        while True:
            if msvcrt is not None:
                try:
                    fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR)
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        self._fd = fd
                        self._acquired = True
                        return True
                    except (OSError, PermissionError):
                        os.close(fd)
                except OSError:
                    pass
            else:
                try:
                    fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                    self._fd = fd
                    self._acquired = True
                    return True
                except (OSError, FileExistsError):
                    try:
                        mtime = os.path.getmtime(self.lock_path)
                        if (time.time() - mtime) > (self.timeout + 10.0):
                            os.remove(self.lock_path)
                    except OSError:
                        pass

            if (time.monotonic() - start_time) >= self.timeout:
                raise TimeoutError(
                    f"Timed out after {self.timeout}s waiting to acquire Windows CLI action lock: {self.lock_path}"
                )
            time.sleep(self.poll_interval)

    def release(self) -> None:
        """Release the exclusive lock."""
        if not self._acquired:
            return
        try:
            if msvcrt is not None and self._fd is not None:
                try:
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
                finally:
                    os.close(self._fd)
                    self._fd = None
            elif self._fd is not None:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None
                if os.path.exists(self.lock_path):
                    try:
                        os.remove(self.lock_path)
                    except OSError:
                        pass
        finally:
            self._acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class WindowsCliBackend(InkscapeBackend):
    """Executes Inkscape operations on Windows via inkscape.com -q --actions."""

    def __init__(
        self,
        inkscape_path: Optional[Path] = None,
        lock_path: Optional[str] = None,
        lock_timeout: float = 35.0,
    ):
        self._inkscape_path = inkscape_path or find_inkscape_executable()
        self._lock_path = lock_path
        self._lock_timeout = lock_timeout

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
            with _ActionLock(lock_path=self._lock_path, timeout=self._lock_timeout):
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

        except subprocess.TimeoutExpired:
            logger.error("Inkscape CLI action timed out")
            return {
                "status": "error",
                "data": {"error": "Inkscape action execution timed out (30s)"},
            }
        except TimeoutError as te:
            logger.error("Windows CLI action lock timed out: %s", te)
            return {
                "status": "error",
                "data": {"error": f"Windows CLI action lock timed out: {te}"},
            }
        except Exception as e:
            logger.error("Windows CLI execution failed: %s", e)
            return {"status": "error", "data": {"error": str(e)}}
