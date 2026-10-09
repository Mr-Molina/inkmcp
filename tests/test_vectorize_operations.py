import os
from pathlib import Path
from unittest.mock import MagicMock
from PIL import Image, ImageDraw

from inkmcp.inkmcpops import VectorizeOperations, vectorize_image_operation


def _create_sample_image(path: Path) -> None:
    """Helper to create a synthetic 60x60 multi-colored image."""
    img = Image.new("RGBA", (60, 60), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Background rectangle
    draw.rectangle([10, 10, 50, 50], fill=(255, 0, 0, 255))
    # Inner circle
    draw.ellipse([20, 20, 40, 40], fill=(0, 0, 255, 255))
    img.save(path, format="PNG")


def test_vectorize_operation_file_export(tmp_path: Path):
    """Test standard file export without Inkscape injection."""
    img_path = tmp_path / "art.png"
    out_svg = tmp_path / "art.svg"
    img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([10, 10, 50, 50], fill=(255, 120, 0, 255))
    img.save(img_path)

    params = {
        "image_path": str(img_path),
        "output_path": str(out_svg),
        "mode": "cut_ready",
        "num_colors": 2,
        "inject_to_inkscape": False,
    }
    result = vectorize_image_operation(params, backend=None)

    assert result["status"] == "success"
    assert out_svg.exists()
    assert out_svg.stat().st_size > 0
    assert "data" in result
    assert "layers" in result["data"]
    assert result["data"]["injected"] is False
    assert result["data"]["output_path"] == str(out_svg.resolve())
    assert result["data"]["export_path"] == str(out_svg.resolve())


def test_vectorize_operation_offline_inkscape_fallback(tmp_path: Path):
    """Test graceful fallback when inject_to_inkscape is True but backend is offline."""
    img_path = tmp_path / "art.png"
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([5, 5, 35, 35], fill=(0, 200, 0, 255))
    img.save(img_path)

    params = {
        "image_path": str(img_path),
        "mode": "layered",
        "inject_to_inkscape": True,
    }
    # Pass backend=None to simulate offline GUI
    result = vectorize_image_operation(params, backend=None)

    assert result["status"] in ("success", "warning")
    assert result["data"]["injected"] is False
    assert "saved to" in result["data"]["message"].lower() or "export_path" in result["data"]
    assert os.path.exists(result["data"]["output_path"])
    assert os.path.getsize(result["data"]["output_path"]) > 0


def test_vectorize_operation_with_mock_backend(tmp_path: Path):
    """Test successful layer injection when backend is available."""
    img_path = tmp_path / "art.png"
    out_svg = tmp_path / "art.svg"
    _create_sample_image(img_path)

    mock_backend = MagicMock()
    mock_backend.is_available.return_value = True
    mock_backend.execute_operation.return_value = {"status": "success"}

    params = {
        "image_path": str(img_path),
        "output_path": str(out_svg),
        "mode": "cut_ready",
        "num_colors": 3,
        "inject_to_inkscape": True,
    }
    result = vectorize_image_operation(params, backend=mock_backend)

    assert result["status"] == "success"
    assert result["data"]["injected"] is True
    assert mock_backend.is_available.called
    assert mock_backend.execute_operation.called

    # Verify layer payload structure passed to backend
    call_args_list = mock_backend.execute_operation.call_args_list
    assert len(call_args_list) == len(result["data"]["layers"])
    for call in call_args_list:
        payload = call[0][0]
        assert payload["tag"] == "g"
        assert "inkscape:groupmode" in payload["attributes"]
        assert payload["attributes"]["inkscape:groupmode"] == "layer"
        assert "inkscape:label" in payload["attributes"]
        assert "children" in payload
        for child in payload["children"]:
            assert child["tag"] == "path"
            assert "d" in child["attributes"]
            assert "fill" in child["attributes"]


def test_vectorize_operation_missing_file_error():
    """Test handling of non-existent input image file."""
    params = {"image_path": "non_existent_image_12345.png"}
    result = vectorize_image_operation(params)

    assert result["status"] == "error"
    error_msg = result.get("message", "") or result.get("data", {}).get("error", "")
    assert "not found" in error_msg.lower()


def test_vectorize_operation_both_modes(tmp_path: Path):
    """Test both cut_ready and layered modes execute end-to-end cleanly."""
    img_path = tmp_path / "art.png"
    _create_sample_image(img_path)

    for mode in ("cut_ready", "layered"):
        out_svg = tmp_path / f"art_{mode}.svg"
        params = {
            "image_path": str(img_path),
            "output_path": str(out_svg),
            "mode": mode,
            "num_colors": 3,
            "inject_to_inkscape": False,
        }
        result = vectorize_image_operation(params, backend=None)

        assert result["status"] == "success", f"Mode {mode} failed: {result}"
        assert out_svg.exists()
        assert out_svg.stat().st_size > 0
        assert result["data"]["mode"] == mode
        assert result["data"]["layer_count"] > 0
        assert result["data"]["total_nodes"] > 0
        assert len(result["data"]["layers"]) == result["data"]["layer_count"]

        # Validate layer metadata fields
        for layer in result["data"]["layers"]:
            assert "layer_id" in layer
            assert "label" in layer
            assert "color_hex" in layer
            assert "path_count" in layer
            assert "z_index" in layer


def test_vectorize_operations_class_wrapper(tmp_path: Path):
    """Test VectorizeOperations class dispatcher static and class methods."""
    img_path = tmp_path / "art.png"
    out_svg = tmp_path / "art.svg"
    _create_sample_image(img_path)

    params = {
        "image_path": str(img_path),
        "output_path": str(out_svg),
        "mode": "cut_ready",
        "inject_to_inkscape": False,
    }

    # Test static method
    res1 = VectorizeOperations.vectorize_image(params, backend=None)
    assert res1["status"] == "success"

    # Test execute class method
    res2 = VectorizeOperations.execute(params, backend=None)
    assert res2["status"] == "success"

    # Test instance call
    ops = VectorizeOperations()
    res3 = ops(params, backend=None)
    assert res3["status"] == "success"


def test_vectorize_operation_backend_exception_fallback(tmp_path: Path):
    """Test fallback when backend raises an unhandled exception during injection."""
    img_path = tmp_path / "art.png"
    out_svg = tmp_path / "art.svg"
    _create_sample_image(img_path)

    mock_backend = MagicMock()
    mock_backend.is_available.return_value = True
    mock_backend.execute_operation.side_effect = RuntimeError("IPC connection broken")

    params = {
        "image_path": str(img_path),
        "output_path": str(out_svg),
        "inject_to_inkscape": True,
    }
    result = vectorize_image_operation(params, backend=mock_backend)

    assert result["status"] == "warning"
    assert result["data"]["injected"] is False
    assert out_svg.exists()


def test_vectorize_operation_invalid_mode(tmp_path: Path):
    """Test error handling when an unsupported mode is provided."""
    img_path = tmp_path / "art.png"
    _create_sample_image(img_path)

    params = {
        "image_path": str(img_path),
        "mode": "unsupported_mode_xyz",
    }
    result = vectorize_image_operation(params)
    assert result["status"] == "error"
    assert "mode" in result["message"].lower() or "mode" in result["data"].get("error", "").lower()


def test_vectorize_operation_default_output_path(tmp_path: Path):
    """Test that when output_path is omitted, a valid temp SVG file is created."""
    img_path = tmp_path / "art.png"
    _create_sample_image(img_path)

    params = {
        "image_path": str(img_path),
        "inject_to_inkscape": False,
    }
    result = vectorize_image_operation(params)

    assert result["status"] == "success"
    generated_path = result["data"]["output_path"]
    assert os.path.exists(generated_path)
    assert os.path.getsize(generated_path) > 0
    # Clean up generated temp file
    try:
        os.remove(generated_path)
    except OSError:
        pass
