"""Tests for vectorize-image CLI and FastMCP server interface.

Verifies:
1. CLI invocation with folder and file paths containing spaces.
2. CLI JSON output formatting via --parse-out and --pretty flags.
3. CLI error exit code 1 and error reporting for missing files.
4. CLI parameter file (-f) loading and execution.
5. CLI command alias (vectorize_image vs vectorize-image).
6. FastMCP server async vectorize_image tool output formatting and execution.
"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

from PIL import Image, ImageDraw

from inkmcp.inkscape_mcp_server import format_vectorize_response, vectorize_image


def _create_sample_image(path: Path) -> None:
    """Helper to create a synthetic 60x60 test image with distinct colors."""
    img = Image.new("RGBA", (60, 60), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    # Background shape
    draw.rectangle([10, 10, 50, 50], fill=(255, 120, 0, 255))
    # Inner shape
    draw.ellipse([20, 20, 40, 40], fill=(0, 180, 0, 255))
    img.save(path, format="PNG")


def test_cli_vectorize_paths_with_spaces(tmp_path: Path):
    """Test CLI execution with spaces in directory and filenames."""
    art_dir = tmp_path / "my art folder"
    art_dir.mkdir(parents=True, exist_ok=True)
    img_path = art_dir / "my pumpkin.png"
    out_svg = art_dir / "my pumpkin.svg"
    _create_sample_image(img_path)

    cli_path = Path(__file__).resolve().parent.parent / "inkmcp" / "inkmcpcli.py"
    cmd = [
        sys.executable,
        str(cli_path),
        "vectorize-image",
        f"image_path={img_path}",
        f"output_path={out_svg}",
        "mode=cut_ready",
        "inject_to_inkscape=false",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
    assert res.returncode == 0, f"CLI invocation failed: {res.stderr}\nstdout: {res.stdout}"
    assert out_svg.exists(), f"Expected output SVG was not created: {out_svg}"
    assert out_svg.stat().st_size > 0
    assert "my pumpkin.svg" in res.stdout
    assert "✅" in res.stdout


def test_cli_vectorize_json_output(tmp_path: Path):
    """Test vectorize-image with --parse-out and --pretty outputting structured JSON."""
    img_path = tmp_path / "badge.png"
    out_svg = tmp_path / "badge.svg"
    _create_sample_image(img_path)

    cli_path = Path(__file__).resolve().parent.parent / "inkmcp" / "inkmcpcli.py"

    # 1. Test --parse-out
    cmd_parse = [
        sys.executable,
        str(cli_path),
        "vectorize-image",
        f"image_path={img_path}",
        f"output_path={out_svg}",
        "mode=cut_ready",
        "inject_to_inkscape=false",
        "--parse-out",
    ]
    res_parse = subprocess.run(cmd_parse, capture_output=True, text=True, encoding="utf-8", check=False)
    assert res_parse.returncode == 0, f"CLI error: {res_parse.stderr}\nstdout: {res_parse.stdout}"

    data = json.loads(res_parse.stdout)
    assert "output_path" in data
    assert "layer_count" in data
    assert "mode" in data
    assert data["mode"] == "cut_ready"
    assert data["layer_count"] >= 1
    assert os.path.exists(data["output_path"])

    # 2. Test --pretty
    out_pretty_svg = tmp_path / "badge_pretty.svg"
    cmd_pretty = [
        sys.executable,
        str(cli_path),
        "vectorize-image",
        f"image_path={img_path}",
        f"output_path={out_pretty_svg}",
        "mode=layered",
        "inject_to_inkscape=false",
        "--pretty",
    ]
    res_pretty = subprocess.run(cmd_pretty, capture_output=True, text=True, encoding="utf-8", check=False)
    assert res_pretty.returncode == 0, f"CLI error: {res_pretty.stderr}\nstdout: {res_pretty.stdout}"
    assert "\n" in res_pretty.stdout, "Pretty printed JSON should contain newlines"

    data_pretty = json.loads(res_pretty.stdout)
    assert "output_path" in data_pretty
    assert "layer_count" in data_pretty
    assert "mode" in data_pretty
    assert data_pretty["mode"] == "layered"
    assert os.path.exists(data_pretty["output_path"])


def test_cli_vectorize_missing_file_error(tmp_path: Path):
    """Test non-existent input file returns exit code 1 and error diagnostic."""
    non_existent = tmp_path / "missing_graphic.png"
    cli_path = Path(__file__).resolve().parent.parent / "inkmcp" / "inkmcpcli.py"

    cmd = [
        sys.executable,
        str(cli_path),
        "vectorize-image",
        f"image_path={non_existent}",
        "inject_to_inkscape=false",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
    assert res.returncode == 1
    combined_output = (res.stdout + res.stderr).lower()
    assert "not found" in combined_output or "error" in combined_output


def test_cli_vectorize_param_file(tmp_path: Path):
    """Test CLI reading parameters from file via -f option."""
    img_path = tmp_path / "file_test.png"
    out_svg = tmp_path / "file_test.svg"
    _create_sample_image(img_path)

    params_file = tmp_path / "params.txt"
    params_file.write_text(
        f"image_path={img_path}\noutput_path={out_svg}\nmode=cut_ready\ninject_to_inkscape=false\n",
        encoding="utf-8",
    )

    cli_path = Path(__file__).resolve().parent.parent / "inkmcp" / "inkmcpcli.py"
    cmd = [
        sys.executable,
        str(cli_path),
        "vectorize-image",
        "-f",
        str(params_file),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
    assert res.returncode == 0, f"CLI error: {res.stderr}\nstdout: {res.stdout}"
    assert out_svg.exists()
    assert out_svg.stat().st_size > 0


def test_cli_vectorize_alias_command(tmp_path: Path):
    """Test CLI accepting vectorize_image (underscore alias)."""
    img_path = tmp_path / "alias_test.png"
    out_svg = tmp_path / "alias_test.svg"
    _create_sample_image(img_path)

    cli_path = Path(__file__).resolve().parent.parent / "inkmcp" / "inkmcpcli.py"
    cmd = [
        sys.executable,
        str(cli_path),
        "vectorize_image",
        f"image_path={img_path}",
        f"output_path={out_svg}",
        "inject_to_inkscape=false",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
    assert res.returncode == 0, f"CLI error: {res.stderr}\nstdout: {res.stdout}"
    assert out_svg.exists()


def test_mcp_server_vectorize_image_tool(tmp_path: Path):
    """Test async vectorize_image FastMCP server tool execution."""
    img_path = tmp_path / "server_test.png"
    out_svg = tmp_path / "server_test.svg"
    _create_sample_image(img_path)

    async def _test():
        mock_ctx = MagicMock()
        result_md = await vectorize_image(
            ctx=mock_ctx,
            image_path=str(img_path),
            output_path=str(out_svg),
            mode="cut_ready",
            num_colors=4,
            inject_to_inkscape=False,
        )

        assert isinstance(result_md, str)
        assert "✅" in result_md
        assert "Layer Breakdown" in result_md or "Layers" in result_md
        assert str(out_svg.resolve()) in result_md or str(out_svg) in result_md
        assert "Total Nodes" in result_md
        assert out_svg.exists()
        assert out_svg.stat().st_size > 0

    asyncio.run(_test())


def test_mcp_server_vectorize_image_missing_file_error(tmp_path: Path):
    """Test FastMCP server tool handles missing input file with error emoji."""
    missing_file = tmp_path / "nonexistent.png"

    async def _test():
        mock_ctx = MagicMock()
        result_md = await vectorize_image(
            ctx=mock_ctx,
            image_path=str(missing_file),
            inject_to_inkscape=False,
        )
        assert "❌" in result_md
        assert "not found" in result_md.lower() or "failed" in result_md.lower()

    asyncio.run(_test())


def test_format_vectorize_response_variations():
    """Test format_vectorize_response formats success, warning, and error outputs."""
    # 1. Success
    success_res = {
        "status": "success",
        "message": "Vectorized successfully",
        "data": {
            "output_path": "/path/to/art.svg",
            "mode": "cut_ready",
            "layer_count": 2,
            "total_nodes": 45,
            "file_size": 2048,
            "injected": True,
            "layers": [
                {"layer_id": "l1", "label": "Layer 1", "color_hex": "#ff0000", "path_count": 2},
                {"layer_id": "l2", "label": "Layer 2", "color_hex": "#00ff00", "path_count": 3},
            ],
        },
    }
    fmt_success = format_vectorize_response(success_res)
    assert "✅" in fmt_success
    assert "/path/to/art.svg" in fmt_success
    assert "Layer 1" in fmt_success
    assert "45" in fmt_success

    # 2. Warning
    warning_res = {
        "status": "warning",
        "message": "Inkscape GUI is offline; saved to file",
        "data": {
            "output_path": "/path/to/art.svg",
            "mode": "layered",
            "layer_count": 1,
            "total_nodes": 10,
            "file_size": 512,
            "injected": False,
            "layers": [],
        },
    }
    fmt_warning = format_vectorize_response(warning_res)
    assert "⚠️" in fmt_warning
    assert "Inkscape GUI is offline" in fmt_warning

    # 3. Error
    error_res = {
        "status": "error",
        "message": "Image file not found: bad.png",
        "data": {"error_details": "bad.png"},
    }
    fmt_error = format_vectorize_response(error_res)
    assert "❌" in fmt_error
    assert "bad.png" in fmt_error


def test_cli_vectorize_silhouette(tmp_path: Path):
    """Test CLI execution with mode=silhouette creates a single-layer decal SVG."""
    img_path = tmp_path / "silhouette_cli.png"
    out_svg = tmp_path / "silhouette_cli.svg"
    _create_sample_image(img_path)

    cmd = [
        sys.executable,
        "-m",
        "inkmcp.inkmcpcli",
        "vectorize-image",
        f"image_path={img_path}",
        "mode=silhouette",
        f"output_path={out_svg}",
        "inject_to_inkscape=false",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
    assert res.returncode == 0, f"CLI invocation failed: {res.stderr}\nstdout: {res.stdout}"
    assert out_svg.exists(), f"Expected output SVG was not created: {out_svg}"
    assert out_svg.stat().st_size > 0
    assert "✅" in res.stdout
    assert "1 layers" in res.stdout or "1 layer" in res.stdout


def test_cli_vectorize_invalid_mode(tmp_path: Path):
    """Test CLI returns exit code 1 when an invalid mode is specified."""
    img_path = tmp_path / "invalid_mode.png"
    _create_sample_image(img_path)

    cmd = [
        sys.executable,
        "-m",
        "inkmcp.inkmcpcli",
        "vectorize-image",
        f"image_path={img_path}",
        "mode=invalid_mode_xyz",
        "inject_to_inkscape=false",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
    assert res.returncode == 1
    assert "mode" in res.stderr.lower() or "mode" in res.stdout.lower()


def test_mcp_server_vectorize_image_silhouette_mode(tmp_path: Path):
    """Test FastMCP server vectorize_image tool with mode=silhouette."""
    img_path = tmp_path / "server_silhouette.png"
    out_svg = tmp_path / "server_silhouette.svg"
    _create_sample_image(img_path)

    async def _test():
        mock_ctx = MagicMock()
        result_md = await vectorize_image(
            ctx=mock_ctx,
            image_path=str(img_path),
            output_path=str(out_svg),
            mode="silhouette",
            inject_to_inkscape=False,
        )
        assert isinstance(result_md, str)
        assert "✅" in result_md
        assert "silhouette" in result_md
        assert out_svg.exists()
        assert out_svg.stat().st_size > 0

    asyncio.run(_test())


def test_mcp_server_vectorize_image_invalid_mode(tmp_path: Path):
    """Test FastMCP server vectorize_image tool rejects invalid mode."""
    img_path = tmp_path / "server_invalid.png"
    _create_sample_image(img_path)

    async def _test():
        mock_ctx = MagicMock()
        result_md = await vectorize_image(
            ctx=mock_ctx,
            image_path=str(img_path),
            mode="invalid_mode_xyz",
            inject_to_inkscape=False,
        )
        assert "❌" in result_md
        assert "mode" in result_md.lower()

    asyncio.run(_test())


