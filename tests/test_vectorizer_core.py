"""Unit tests for VTracerCore vectorizer adapter."""

import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from inkmcp.vectorizer.core import (
    PathRecord,
    RawVectorResult,
    VTracerCore,
    scale_svg_path_coordinates,
)


def test_path_record_and_raw_vector_result_dataclasses():
    """Verify PathRecord and RawVectorResult instantiate with correct fields."""
    record = PathRecord(
        id="path_001",
        color_hex="#FF0000",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",
        area=100.0,
    )
    assert record.id == "path_001"
    assert record.color_hex == "#FF0000"
    assert record.path_data == "M 0 0 L 10 0 L 10 10 L 0 10 Z"
    assert record.area == 100.0
    assert record.fill_rule == "nonzero"

    result = RawVectorResult(
        svg_string="<svg></svg>",
        path_records=[record],
        dimensions=(100, 100),
    )
    assert result.svg_string == "<svg></svg>"
    assert len(result.path_records) == 1
    assert result.dimensions == (100, 100)


def test_vtracer_vectorization_file_path(tmp_path: Path):
    """Test basic vectorization of a red square on transparent background from file path."""
    img_path = tmp_path / "square.png"
    img = Image.new("RGBA", (80, 80), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 60, 60], fill=(255, 0, 0, 255))
    img.save(img_path)

    core = VTracerCore()
    result = core.vectorize(
        str(img_path),
        colormode="color",
        filter_speckle=4,
        corner_threshold=60,
        segment_length=4,
    )

    assert isinstance(result, RawVectorResult)
    assert "<svg" in result.svg_string
    assert result.dimensions == (80, 80)
    assert len(result.path_records) >= 1

    # Check valid XML in svg_string
    root = ET.fromstring(result.svg_string)
    assert root.tag.endswith("svg")

    # Check path records properties
    assert any(
        "rgb(255" in p.color_hex or "#ff0000" in p.color_hex.lower()
        for p in result.path_records
    )
    for i, p in enumerate(result.path_records, start=1):
        assert p.id == f"path_{i:03d}"
        assert p.area > 0
        assert p.path_data.startswith("M")
        assert p.color_hex.startswith("#")
        assert len(p.color_hex) == 7


def test_vtracer_vectorization_pil_image():
    """Test vectorization directly passing PIL Image instance."""
    img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([15, 15, 45, 45], fill=(0, 255, 0, 255))

    core = VTracerCore()
    result = core.vectorize(img)

    assert isinstance(result, RawVectorResult)
    assert result.dimensions == (60, 60)
    assert len(result.path_records) >= 1
    assert any(
        "#00ff00" in p.color_hex.lower() for p in result.path_records
    )
    for p in result.path_records:
        assert p.area > 0


def test_vtracer_vectorization_bytes():
    """Test vectorization passing raw image bytes."""
    import io

    img = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 40, 40], fill=(0, 0, 255, 255))
    bio = io.BytesIO()
    img.save(bio, format="PNG")

    core = VTracerCore()
    result = core.vectorize(bio.getvalue())

    assert isinstance(result, RawVectorResult)
    assert result.dimensions == (50, 50)
    assert len(result.path_records) >= 1
    assert any(
        "#0000ff" in p.color_hex.lower() for p in result.path_records
    )


def test_vtracer_filter_speckle_parameter():
    """Verify that filter_speckle eliminates micro-speckles below threshold."""
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Primary large square (40x40 -> area ~1600)
    draw.rectangle([20, 20, 60, 60], fill=(255, 0, 0, 255))
    # 2x2 micro-speckle (area ~4)
    draw.rectangle([80, 80, 81, 81], fill=(255, 0, 0, 255))

    core = VTracerCore()

    # With filter_speckle=0, speckle is preserved
    res_no_filter = core.vectorize(img, filter_speckle=0)
    assert len(res_no_filter.path_records) >= 2

    # With filter_speckle=10, 2x2 speckle (area 4 < 10) must be discarded
    res_filtered = core.vectorize(img, filter_speckle=10)
    assert len(res_filtered.path_records) == 1
    assert res_filtered.path_records[0].area > 100


def test_vtracer_parameter_acceptance():
    """Verify segment_length, corner_threshold, and mode parameter variations."""
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([5, 5, 35, 35], fill=(255, 200, 0, 255))

    core = VTracerCore()

    # Spline mode
    res_spline = core.vectorize(
        img,
        segment_length=2,
        corner_threshold=30,
        mode="spline",
    )
    assert len(res_spline.path_records) >= 1
    assert "C" in res_spline.path_records[0].path_data

    # Polygon mode
    res_poly = core.vectorize(
        img,
        segment_length=8,
        corner_threshold=80,
        mode="polygon",
    )
    assert len(res_poly.path_records) >= 1
    assert "L" in res_poly.path_records[0].path_data


def test_vtracer_invalid_input():
    """Verify error handling on non-existent file or invalid input type."""
    core = VTracerCore()

    with pytest.raises(FileNotFoundError):
        core.vectorize("non_existent_file_xyz_12345.png")

    with pytest.raises(TypeError):
        core.vectorize(12345)  # type: ignore[arg-type]


def test_vtracer_hierarchical_default_and_modes():
    """Verify VTracerCore.vectorize defaults to hierarchical='cutout' and accepts stacked."""
    import inspect

    sig = inspect.signature(VTracerCore.vectorize)
    assert "hierarchical" in sig.parameters
    assert sig.parameters["hierarchical"].default == "cutout"

    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([5, 5, 35, 35], fill=(255, 0, 0, 255))
    draw.rectangle([15, 15, 25, 25], fill=(0, 255, 0, 255))

    core = VTracerCore()
    # Default should be cutout
    res_default = core.vectorize(img)
    assert len(res_default.path_records) >= 1

    res_cutout = core.vectorize(img, hierarchical="cutout")
    assert len(res_cutout.path_records) >= 1

    res_stacked = core.vectorize(img, hierarchical="stacked")
    assert len(res_stacked.path_records) >= 1


def test_vtracer_silhouette_binary_cutout_config():
    """Verify VTracerCore traces transparent background cutout image with single canonical color."""
    img = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 40, 40], fill=(226, 131, 11, 255))

    core = VTracerCore()
    res = core.vectorize(img, hierarchical="cutout", filter_speckle=4)
    assert len(res.paths) >= 1
    assert res.paths[0].color_hex.upper() == "#E2830B"


def test_scale_svg_path_coordinates():
    """Verify scale_svg_path_coordinates scales SVG paths accurately across commands."""
    # Test identity
    assert scale_svg_path_coordinates("", 0.5) == ""
    assert scale_svg_path_coordinates("M 10 20 L 30 40 Z", 1.0) == "M 10 20 L 30 40 Z"

    # Test scaling down (0.5x)
    path_in = "M 20 40 C 40 60 80 100 120 160 Z"
    scaled = scale_svg_path_coordinates(path_in, 0.5)
    assert scaled == "M 10 20 C 20 30 40 50 60 80 Z"

    # Test scaling up (2x)
    scaled_up = scale_svg_path_coordinates("M 5 10 L 15 20 H 25 V 30 Z", 2.0)
    assert scaled_up == "M 10 20 L 30 40 H 50 V 60 Z"

    # Test arc command: rx, ry, x, y scaled, flags/rotation unchanged
    arc_path = "M 10 10 A 20 30 45 1 0 50 60 Z"
    scaled_arc = scale_svg_path_coordinates(arc_path, 0.5)
    assert scaled_arc == "M 5 5 A 10 15 45 1 0 25 30 Z"


def test_vtracer_vectorize_scale_factor():
    """Verify VTracerCore scales path coordinates and dimensions when scale_factor is set."""
    # Create 80x80 image
    img = Image.new("RGB", (80, 80), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 60, 60], fill=(0, 0, 0))

    core = VTracerCore()
    # Scale factor 0.5 should reduce dimensions to 40x40 and scale path coordinates
    res = core.vectorize(
        img,
        colormode="binary",
        scale_factor=0.5,
    )
    assert res.dimensions == (40, 40)
    assert len(res.path_records) >= 1
    # Check that coordinate values in path_data are scaled to ~10..30 instead of ~20..60
    import re
    coords = [float(x) for x in re.findall(r"[-+]?(?:\d*\.\d+|\d+)", res.path_records[0].path_data)]
    assert max(coords) < 35.0


def test_vtracer_vectorize_default_parameters():
    """Verify default corner_threshold is 60 and segment_length is 4.0."""
    import inspect
    sig = inspect.signature(VTracerCore.vectorize)
    assert sig.parameters["corner_threshold"].default == 60
    assert sig.parameters["segment_length"].default == 4.0
    assert sig.parameters["scale_factor"].default == 1.0



