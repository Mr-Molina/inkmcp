"""Unit tests for FastMCP server operations in inkmcp.inkscape_mcp_server.

Tests format_response across various operation outcomes (creation, export, execution, warnings),
missing response file detection in execute_operation,
and 0-byte / corrupted response file handling.
"""

import asyncio
import json
import os
import subprocess
import tempfile
import uuid
from unittest.mock import MagicMock, patch

import pytest

from inkmcp.backends import DBusBackend
from inkmcp.inkscape_mcp_server import (
    InkscapeConnection,
    format_response,
)


class TestFormatResponse:
    """Tests for format_response rendering structured Markdown output."""

    def test_format_response_element_creation(self):
        """Test formatting response for element creation."""
        result = {
            "status": "success",
            "data": {
                "message": "Circle created successfully",
                "id": "circle_100",
                "tag": "circle",
            },
        }
        formatted = format_response(result)
        assert "✅ Circle created successfully" in formatted
        assert "**ID**: `circle_100`" in formatted
        assert "**Type**: circle" in formatted

    def test_format_response_export(self):
        """Test formatting response for image export."""
        export_path = os.path.join(tempfile.gettempdir(), "output.png")
        result = {
            "status": "success",
            "data": {
                "message": "Document exported as PNG",
                "export_path": export_path,
                "file_size": 4096,
            },
        }
        formatted = format_response(result)
        assert "✅ Document exported as PNG" in formatted
        assert f"**File**: {export_path}" in formatted
        assert "**Size**: 4096 bytes" in formatted

    def test_format_response_code_execution_success(self):
        """Test formatting response for successful code execution."""
        result = {
            "status": "success",
            "data": {
                "message": "Code executed successfully",
                "execution_successful": True,
                "elements_created": ["elem1", "elem2"],
            },
        }
        formatted = format_response(result)
        assert "✅ Code executed successfully" in formatted
        assert "**Execution**: ✅ Success" in formatted
        assert "**Created**: 2 elements" in formatted

    def test_format_response_code_execution_failure(self):
        """Test formatting response for failed code execution uses error indicator."""
        result = {
            "status": "success",
            "data": {
                "message": "Code execution failed",
                "execution_successful": False,
            },
        }
        formatted = format_response(result)
        assert "❌ Code execution failed" in formatted
        assert "**Execution**: ❌ Failed" in formatted

    def test_format_response_warning_unnamed_ids(self):
        """Test formatting response includes warning when elements are generated without IDs."""
        result = {
            "status": "success",
            "data": {
                "message": "Elements added",
                "generated_ids": ["circle3452"],
            },
        }
        formatted = format_response(result)
        assert "WARNING: Elements created without IDs" in formatted
        assert "circle3452" in formatted


class TestExecuteOperationResponseHandling:
    """Tests for InkscapeConnection.execute_operation file handling."""

    @patch("subprocess.run")
    def test_execute_operation_valid_response_file(self, mock_subprocess):
        """Test that a valid response file is parsed and unlinked."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump({"status": "success", "data": {"id": "circle_1"}}, tf)
            resp_path = tf.name

        try:
            conn = InkscapeConnection(backend=DBusBackend())
            res = conn.execute_operation({"response_file": resp_path})
            assert res["status"] == "success"
            assert res["data"]["id"] == "circle_1"
            assert not os.path.exists(resp_path), "Response file should be deleted after reading"
        finally:
            if os.path.exists(resp_path):
                os.unlink(resp_path)

    @patch("subprocess.run")
    def test_execute_operation_zero_byte_response_file(self, mock_subprocess):
        """Test that a 0-byte response file is handled gracefully without unhandled crashes."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Create an empty 0-byte file
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            resp_path = tf.name

        try:
            conn = InkscapeConnection(backend=DBusBackend())
            res = conn.execute_operation({"response_file": resp_path})
            # Should return error status indicating response file error
            assert res["status"] == "error"
            assert "error" in res["data"]
            assert "Response file error" in res["data"]["error"]
        finally:
            if os.path.exists(resp_path):
                os.unlink(resp_path)

    @patch("subprocess.run")
    def test_execute_operation_missing_response_file(self, mock_subprocess):
        """Test detection when a specified response_file does not exist on disk."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        non_existent_file = os.path.join(
            tempfile.gettempdir(), f"non_existent_response_{uuid.uuid4().hex}.json"
        )
        if os.path.exists(non_existent_file):
            os.unlink(non_existent_file)

        conn = InkscapeConnection(backend=DBusBackend())
        res = conn.execute_operation({"response_file": non_existent_file})
        # Verify execute_operation returns a structured response without crashing
        assert "status" in res
        assert "data" in res
        assert res["status"] == "error"
        assert "error" in res["data"]


def test_inkscape_connection_selects_windows_backend():
    from inkmcp.inkscape_mcp_server import InkscapeConnection
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="windows"), \
         patch("inkmcp.inkscape_mcp_server.is_inkscape_process_running", return_value=True), \
         patch("inkmcp.backends.windows_cli.WindowsCliBackend.is_available", return_value=True):
        conn = InkscapeConnection()
        assert conn.backend.get_backend_name() == "windows_cli"


def test_inkscape_connection_selects_headless_when_no_gui():
    from inkmcp.inkscape_mcp_server import InkscapeConnection
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="windows"), \
         patch("inkmcp.inkscape_mcp_server.is_inkscape_process_running", return_value=False):
        conn = InkscapeConnection(allow_headless=True)
        assert conn.backend.get_backend_name() == "headless"


def test_inkscape_connection_selects_dbus_backend():
    from inkmcp.inkscape_mcp_server import InkscapeConnection
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="linux"), \
         patch("inkmcp.backends.dbus.DBusBackend.is_available", return_value=True):
        conn = InkscapeConnection()
        assert conn.backend.get_backend_name() == "dbus"


def test_inkscape_connection_selects_headless_on_linux_when_no_dbus():
    from inkmcp.inkscape_mcp_server import InkscapeConnection
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="linux"), \
         patch("inkmcp.backends.dbus.DBusBackend.is_available", return_value=False):
        conn = InkscapeConnection(allow_headless=True)
        assert conn.backend.get_backend_name() == "headless"


def test_inkscape_connection_none_backend_when_no_gui_and_no_headless():
    from inkmcp.inkscape_mcp_server import InkscapeConnection
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="windows"), \
         patch("inkmcp.inkscape_mcp_server.is_inkscape_process_running", return_value=False):
        conn = InkscapeConnection(allow_headless=False)
        assert conn.backend is None
        assert conn.is_available() is False
        res = conn.execute_operation({"operation": "get_info"})
        assert res["status"] == "error"
        assert "No Inkscape backend available" in res["data"]["error"]


def test_inkscape_client_delegates_to_connection():
    from inkmcp.inkmcpcli import InkscapeClient
    with patch("inkmcp.inkscape_mcp_server.InkscapeConnection.execute_operation") as mock_exec:
        mock_exec.return_value = {"status": "success", "data": {"id": "circle_1", "message": "created"}}
        client = InkscapeClient()
        res = client.execute_operation({"tag": "circle"})
        assert res["success"] is True
        assert res["response"]["data"]["id"] == "circle_1"


def test_inkscape_client_handles_error():
    from inkmcp.inkmcpcli import InkscapeClient
    with patch("inkmcp.inkscape_mcp_server.InkscapeConnection.execute_operation") as mock_exec:
        mock_exec.return_value = {"status": "error", "data": {"error": "Connection failed"}}
        client = InkscapeClient()
        res = client.execute_operation({"tag": "circle"})
        assert res["success"] is False
        assert res["error"] == "Connection failed"


def test_element_creator_params_file_argument():
    import argparse
    from inkscape_mcp import ElementCreator

    creator = ElementCreator()
    parser = argparse.ArgumentParser()
    creator.add_arguments(parser)
    args = parser.parse_args(["--params-file", "test_params.json"])
    assert args.params_file == "test_params.json"


def test_element_creator_effect_reads_custom_params_file():
    from inkscape_mcp import ElementCreator
    import inkex

    # Create a custom params file
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(
            {
                "tag": "circle",
                "attributes": {
                    "cx": "50",
                    "cy": "50",
                    "r": "25",
                    "id": "custom_circle",
                },
            },
            tf,
        )
        params_path = tf.name

    try:
        creator = ElementCreator()
        creator.options = MagicMock()
        creator.options.params_file = params_path
        creator.svg = inkex.load_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            '<g id="layer1"/>'
            '</svg>'
        ).getroot()

        creator.effect()
        # The custom params file should have been read and removed
        assert not os.path.exists(params_path)
        # Check that the element was added to the svg
        circle = creator.svg.find(".//*[@id='custom_circle']")
        assert circle is not None
    finally:
        if os.path.exists(params_path):
            os.unlink(params_path)


def test_dbus_backend_is_available():
    from inkmcp.backends.dbus import DBusBackend

    # 1. When gdbus not found
    with patch("shutil.which", return_value=None):
        backend = DBusBackend()
        assert backend.is_available() is False

    # 2. When gdbus call succeeds and action is present
    with patch("shutil.which", return_value="/usr/bin/gdbus"), \
         patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="['org.khema.inkscape.mcp', 'other']")):
        backend = DBusBackend()
        assert backend.is_available() is True
        assert backend.get_backend_name() == "dbus"

    # 3. When gdbus call returns error
    with patch("shutil.which", return_value="/usr/bin/gdbus"), \
         patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="Error")):
        backend = DBusBackend()
        assert backend.is_available() is False


def test_inkscape_connection_dynamic_reprobe():
    """Verify that InkscapeConnection dynamically detects a backend becoming available after __init__."""
    from inkmcp.inkscape_mcp_server import InkscapeConnection

    # Initially: Inkscape is not running
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="windows"), \
         patch("inkmcp.inkscape_mcp_server.is_inkscape_process_running", return_value=False):
        conn = InkscapeConnection(allow_headless=False)
        assert conn.backend is None
        assert conn.is_available() is False

        # Later: User launches Inkscape, so is_inkscape_process_running becomes True
        with patch("inkmcp.inkscape_mcp_server.is_inkscape_process_running", return_value=True), \
             patch("inkmcp.backends.windows_cli.WindowsCliBackend.is_available", return_value=True):
            # Calling is_available() should re-probe and find the backend
            assert conn.is_available() is True
            assert conn.backend is not None
            assert conn.backend.get_backend_name() == "windows_cli"


def test_get_inkscape_connection_dynamic_reprobe(monkeypatch):
    """Verify get_inkscape_connection re-attempts when previous connection was unavailable."""
    import inkmcp.inkscape_mcp_server as server_module

    # Reset global via monkeypatch so original value is restored after the test
    monkeypatch.setattr(server_module, '_inkscape_connection', None)

    # First attempt: no GUI running -> raises exception
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="windows"), \
         patch("inkmcp.inkscape_mcp_server.is_inkscape_process_running", return_value=False):
        with pytest.raises(Exception, match="Inkscape is not running"):
            server_module.get_inkscape_connection()

    # Second attempt: GUI started -> succeeds
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="windows"), \
         patch("inkmcp.inkscape_mcp_server.is_inkscape_process_running", return_value=True), \
         patch("inkmcp.backends.windows_cli.WindowsCliBackend.is_available", return_value=True):
        conn = server_module.get_inkscape_connection()
        assert conn.is_available() is True
        assert conn.backend.get_backend_name() == "windows_cli"


def test_element_creator_effect_rejects_outside_params_file():
    """Verify that ElementCreator.effect() rejects parameter files outside temp directory."""
    from inkscape_mcp import ElementCreator

    creator = ElementCreator()
    creator.options = MagicMock()
    outside_file = os.path.abspath(
        os.path.join(tempfile.gettempdir(), "..", f"outside_params_{uuid.uuid4().hex}.json")
    )
    creator.options.params_file = outside_file

    with patch.object(creator, "write_response") as mock_write:
        creator.effect()
        assert mock_write.called
        args, _ = mock_write.call_args
        assert args[0]["status"] == "error"
        assert "outside temp directory" in args[0]["data"]["error"]


class TestDBusBackendExecuteOperation:
    """Tests for DBusBackend.execute_operation, timeout handling, security checks, and async wrappers."""

    def test_execute_operation_success_auto_response_file(self):
        """Test successful DBusBackend.execute_operation with auto-generated temp response file."""
        backend = DBusBackend()

        def fake_subprocess_run(cmd, *args, **kwargs):
            params_file = os.path.join(tempfile.gettempdir(), "mcp_params.json")
            if os.path.exists(params_file):
                with open(params_file, "r", encoding="utf-8") as f:
                    params_data = json.load(f)
                resp_path = params_data.get("response_file")
                if resp_path:
                    with open(resp_path, "w", encoding="utf-8") as f:
                        json.dump({"status": "success", "data": {"id": "circle_auto"}}, f)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            res = backend.execute_operation({"action": "circle", "radius": 50})
            assert res["status"] == "success"
            assert res["data"]["id"] == "circle_auto"

    def test_execute_operation_success_caller_response_file(self):
        """Test successful DBusBackend.execute_operation with caller-provided response file."""
        backend = DBusBackend()
        resp_file = os.path.join(tempfile.gettempdir(), f"inkmcp_test_resp_{uuid.uuid4().hex}.json")

        def fake_subprocess_run(cmd, *args, **kwargs):
            with open(resp_file, "w", encoding="utf-8") as f:
                json.dump({"status": "success", "data": {"id": "rect_caller"}}, f)
            return MagicMock(returncode=0, stdout="", stderr="")

        try:
            with patch("subprocess.run", side_effect=fake_subprocess_run):
                res = backend.execute_operation({"action": "rect", "response_file": resp_file})
                assert res["status"] == "success"
                assert res["data"]["id"] == "rect_caller"
        finally:
            if os.path.exists(resp_file):
                try:
                    os.remove(resp_file)
                except OSError:
                    pass

    def test_execute_operation_rejects_path_traversal(self):
        """Test that DBusBackend rejects response_file located outside temp directory."""
        backend = DBusBackend()
        outside_resp = os.path.abspath(
            os.path.join(tempfile.gettempdir(), "..", f"malicious_resp_{uuid.uuid4().hex}.json")
        )
        res = backend.execute_operation({"action": "circle", "response_file": outside_resp})
        assert res["status"] == "error"
        assert "Path outside temp directory" in res["data"]["error"]

    def test_execute_operation_subprocess_timeout(self):
        """Test DBusBackend handles subprocess timeout cleanly."""
        backend = DBusBackend()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["gdbus"], timeout=30)):
            res = backend.execute_operation({"action": "circle"})
            assert res["status"] == "error"
            assert "Operation timed out" in res["data"]["error"]

    def test_execute_operation_gdbus_call_failure(self):
        """Test DBusBackend handles non-zero exit from gdbus."""
        backend = DBusBackend()
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="GDBus.Error")):
            res = backend.execute_operation({"action": "circle"})
            assert res["status"] == "error"
            assert "D-Bus call failed: GDBus.Error" in res["data"]["error"]

    def test_execute_operation_missing_or_empty_output(self):
        """Test DBusBackend handles missing or empty response file."""
        backend = DBusBackend()
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            res = backend.execute_operation({"action": "circle"})
            assert res["status"] == "error"
            assert "Extension failed to produce output" in res["data"]["error"]

    def test_dbus_backend_async_wrappers(self):
        """Test DBusBackend is_available_async and execute_operation_async delegate correctly."""
        backend = DBusBackend()
        with patch.object(backend, "is_available", return_value=True) as mock_avail:
            assert asyncio.run(backend.is_available_async()) is True
            mock_avail.assert_called_once()

        expected = {"status": "success", "data": {"result": "ok"}}
        with patch.object(backend, "execute_operation", return_value=expected) as mock_exec:
            res = asyncio.run(backend.execute_operation_async({"action": "test"}))
            assert res == expected
            mock_exec.assert_called_once_with({"action": "test"})


def test_inkscape_connection_dynamic_reprobe_linux():
    """Verify that InkscapeConnection dynamically detects Linux D-Bus backend becoming available."""
    from inkmcp.inkscape_mcp_server import InkscapeConnection

    # Initially: D-Bus backend not available
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="linux"), \
         patch("inkmcp.backends.dbus.DBusBackend.is_available", return_value=False):
        conn = InkscapeConnection(allow_headless=False)
        assert conn.backend is None
        assert conn.is_available() is False

        # Later: Inkscape D-Bus service becomes available
        with patch("inkmcp.backends.dbus.DBusBackend.is_available", return_value=True):
            assert conn.is_available() is True
            assert conn.backend is not None
            assert conn.backend.get_backend_name() == "dbus"


def test_get_inkscape_connection_dynamic_reprobe_linux(monkeypatch):
    """Verify get_inkscape_connection re-attempts on Linux when D-Bus was previously unavailable."""
    import inkmcp.inkscape_mcp_server as server_module

    monkeypatch.setattr(server_module, '_inkscape_connection', None)

    # First attempt: D-Bus unavailable -> raises exception
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="linux"), \
         patch("inkmcp.backends.dbus.DBusBackend.is_available", return_value=False):
        with pytest.raises(Exception, match="Inkscape is not running"):
            server_module.get_inkscape_connection()

    # Second attempt: D-Bus available -> succeeds
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="linux"), \
         patch("inkmcp.backends.dbus.DBusBackend.is_available", return_value=True):
        conn = server_module.get_inkscape_connection()
        assert conn.is_available() is True
        assert conn.backend.get_backend_name() == "dbus"




