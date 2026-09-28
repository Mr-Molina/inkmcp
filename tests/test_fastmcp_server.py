"""Unit tests for FastMCP server operations in inkmcp.inkscape_mcp_server.

Tests format_response across various operation outcomes (creation, export, execution, warnings),
missing response file detection in execute_operation,
and 0-byte / corrupted response file handling.
"""

import os
import json
import tempfile
from unittest.mock import MagicMock, patch
import pytest
from inkmcp.inkscape_mcp_server import (
    format_response,
    InkscapeConnection,
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
        result = {
            "status": "success",
            "data": {
                "message": "Document exported as PNG",
                "export_path": "/tmp/output.png",
                "file_size": 4096,
            },
        }
        formatted = format_response(result)
        assert "✅ Document exported as PNG" in formatted
        assert "**File**: /tmp/output.png" in formatted
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
            conn = InkscapeConnection()
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
            conn = InkscapeConnection()
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

        non_existent_file = os.path.join(tempfile.gettempdir(), "non_existent_response_12345.json")
        if os.path.exists(non_existent_file):
            os.unlink(non_existent_file)

        conn = InkscapeConnection()
        res = conn.execute_operation({"response_file": non_existent_file})
        # Verify execute_operation returns a structured response without crashing
        assert "status" in res
        assert "data" in res
