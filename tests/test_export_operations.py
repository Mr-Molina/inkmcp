"""Unit tests for document export operations in inkmcp.inkmcpops.export_operations.

Tests width parsing with various SVG units (px, mm, cm, in, pt),
viewBox fallback when width is omitted or percentage,
and temporary file cleanup on both success and error paths.
"""

import os
import subprocess
from unittest.mock import MagicMock, patch
import pytest
from inkmcp.inkmcpops.export_operations import export_document_image


class TestExportOperationsWidthParsing:
    """Tests for SVG width parsing across various unit formats and viewBox fallback."""

    @pytest.mark.parametrize(
        "width_val",
        [
            "100px",
            "100mm",
            "10cm",
            "4in",
            "120pt",
            "150",
        ],
    )
    def test_export_document_image_various_units(self, width_val):
        """Test that width attribute in various units (px, mm, cm, in, pt) parses without crashing."""
        mock_ext = MagicMock()
        mock_svg = MagicMock()
        mock_svg.get.side_effect = lambda key, default=None: width_val if key == "width" else default

        with patch("inkmcp.inkmcpops.export_operations.subprocess.run") as mock_run:
            # Simulate successful export call by creating dummy output file
            def fake_run(cmd, *args, **kwargs):
                for arg in cmd:
                    if isinstance(arg, str) and arg.startswith("--export-filename="):
                        filepath = arg.split("=", 1)[1]
                        with open(filepath, "wb") as f:
                            f.write(b"\x89PNG\r\n\x1a\nfake_png_data")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = fake_run

            res = export_document_image(mock_ext, mock_svg, {"format": "png", "max_size": 800})
            export_path = res.get("data", {}).get("export_path")
            try:
                assert res["status"] == "success", f"Export failed for width={width_val}: {res.get('data', {}).get('error')}"
            finally:
                if export_path and os.path.exists(export_path):
                    os.unlink(export_path)

    def test_export_document_image_viewbox_fallback(self):
        """Test fallback to viewBox when width attribute is missing or percentage."""
        mock_ext = MagicMock()
        mock_svg = MagicMock()

        def svg_get(key, default=None):
            if key == "width":
                return "100%"  # Percentage requires viewBox fallback
            if key == "viewBox":
                return "0 0 1024 768"
            return default

        mock_svg.get.side_effect = svg_get

        with patch("inkmcp.inkmcpops.export_operations.subprocess.run") as mock_run:
            def fake_run(cmd, *args, **kwargs):
                for arg in cmd:
                    if isinstance(arg, str) and arg.startswith("--export-filename="):
                        filepath = arg.split("=", 1)[1]
                        with open(filepath, "wb") as f:
                            f.write(b"\x89PNG\r\n\x1a\nfake_png_data")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = fake_run

            res = export_document_image(mock_ext, mock_svg, {"format": "png", "max_size": 512})
            export_path = res.get("data", {}).get("export_path")
            try:
                assert res["status"] == "success"
            finally:
                if export_path and os.path.exists(export_path):
                    os.unlink(export_path)


class TestExportOperationsTempfileCleanup:
    """Tests verifying temporary file creation and deletion."""

    def test_temp_svg_deleted_on_success(self):
        """Verify temporary SVG file is deleted after successful export."""
        mock_ext = MagicMock()
        mock_svg = MagicMock()
        mock_svg.get.return_value = "200px"

        captured_temp_svg = None

        with patch("inkmcp.inkmcpops.export_operations.subprocess.run") as mock_run:
            def fake_run(cmd, *args, **kwargs):
                nonlocal captured_temp_svg
                for arg in cmd:
                    if isinstance(arg, str) and arg.endswith(".svg"):
                        captured_temp_svg = arg
                    elif isinstance(arg, str) and arg.startswith("--export-filename="):
                        filepath = arg.split("=", 1)[1]
                        with open(filepath, "wb") as f:
                            f.write(b"\x89PNG\r\n\x1a\nfake_png_data")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = fake_run

            res = export_document_image(mock_ext, mock_svg, {"format": "png"})
            export_path = res.get("data", {}).get("export_path")
            try:
                assert res["status"] == "success"
                assert captured_temp_svg is not None
                assert not os.path.exists(captured_temp_svg), "Temporary SVG file was not unlinked on success"
            finally:
                # Clean up generated export_path
                if export_path and os.path.exists(export_path):
                    os.unlink(export_path)

    def test_tempfile_cleanup_on_error(self):
        """Verify temporary files are deleted when Inkscape CLI call raises an error."""
        mock_ext = MagicMock()
        mock_svg = MagicMock()
        mock_svg.get.return_value = "200px"

        captured_temp_svg = None
        captured_output_png = None

        with patch("inkmcp.inkmcpops.export_operations.subprocess.run") as mock_run:
            def fake_failing_run(cmd, *args, **kwargs):
                nonlocal captured_temp_svg, captured_output_png
                for arg in cmd:
                    if isinstance(arg, str) and arg.endswith(".svg"):
                        captured_temp_svg = arg
                    elif isinstance(arg, str) and arg.startswith("--export-filename="):
                        captured_output_png = arg.split("=", 1)[1]
                raise RuntimeError("Simulated Inkscape crash")

            mock_run.side_effect = fake_failing_run

            res = export_document_image(mock_ext, mock_svg, {"format": "png"})
            assert res["status"] == "error"
            # On failure, temp files must not be leaked
            if captured_temp_svg:
                assert not os.path.exists(captured_temp_svg), "Temporary SVG leaked on error"
            if captured_output_png:
                assert not os.path.exists(captured_output_png), "Temporary output file leaked on error"

    def test_export_document_image_process_non_zero_returncode(self):
        """Verify error response when Inkscape process exits with non-zero return code."""
        mock_ext = MagicMock()
        mock_svg = MagicMock()
        mock_svg.get.return_value = "200px"

        with patch("inkmcp.inkmcpops.export_operations.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["inkscape"],
                returncode=1,
                stdout="",
                stderr="Error: invalid option",
            )
            res = export_document_image(mock_ext, mock_svg, {"format": "png"})
            assert res["status"] == "error"
            assert "Inkscape export failed: Error: invalid option" in res["data"]["error"]

    def test_export_document_image_timeout_expired(self):
        """Verify error response when Inkscape export times out."""
        mock_ext = MagicMock()
        mock_svg = MagicMock()
        mock_svg.get.return_value = "200px"

        with patch("inkmcp.inkmcpops.export_operations.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["inkscape"], timeout=30)
            res = export_document_image(mock_ext, mock_svg, {"format": "png"})
            assert res["status"] == "error"
            assert "timed out after 30 seconds" in res["data"]["error"]


class TestExportOperationsExecutableResolution:
    """Tests verifying find_inkscape_executable() resolution and fallback in export_document_image."""

    def test_export_document_image_uses_custom_executable(self):
        """Verify find_inkscape_executable() return value is passed to subprocess.run()."""
        mock_ext = MagicMock()
        mock_svg = MagicMock()
        mock_svg.get.return_value = "200px"

        custom_exe = "C:\\Program Files\\Inkscape\\bin\\inkscape.com"
        with patch("inkmcp.inkmcpops.export_operations.find_inkscape_executable", return_value=custom_exe), \
             patch("inkmcp.inkmcpops.export_operations.subprocess.run") as mock_run:
            def fake_run(cmd, *args, **kwargs):
                for arg in cmd:
                    if isinstance(arg, str) and arg.startswith("--export-filename="):
                        filepath = arg.split("=", 1)[1]
                        with open(filepath, "wb") as f:
                            f.write(b"\x89PNG\r\n\x1a\nfake_png_data")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = fake_run
            res = export_document_image(mock_ext, mock_svg, {"format": "png"})
            export_path = res.get("data", {}).get("export_path")
            try:
                assert res["status"] == "success"
                assert mock_run.call_args[0][0][0] == custom_exe
            finally:
                if export_path and os.path.exists(export_path):
                    os.unlink(export_path)

    def test_export_document_image_fallback_when_executable_none(self):
        """Verify fallback to 'inkscape' when find_inkscape_executable() returns None."""
        mock_ext = MagicMock()
        mock_svg = MagicMock()
        mock_svg.get.return_value = "200px"

        with patch("inkmcp.inkmcpops.export_operations.find_inkscape_executable", return_value=None), \
             patch("inkmcp.inkmcpops.export_operations.subprocess.run") as mock_run:
            def fake_run(cmd, *args, **kwargs):
                for arg in cmd:
                    if isinstance(arg, str) and arg.startswith("--export-filename="):
                        filepath = arg.split("=", 1)[1]
                        with open(filepath, "wb") as f:
                            f.write(b"\x89PNG\r\n\x1a\nfake_png_data")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = fake_run
            res = export_document_image(mock_ext, mock_svg, {"format": "png"})
            export_path = res.get("data", {}).get("export_path")
            try:
                assert res["status"] == "success"
                assert mock_run.call_args[0][0][0] == "inkscape"
            finally:
                if export_path and os.path.exists(export_path):
                    os.unlink(export_path)
