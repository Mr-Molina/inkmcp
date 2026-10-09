"""Unit tests for VTracerCore vectorizer adapter."""

import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from inkmcp.vectorizer.core import PathRecord, RawVectorResult, VTracerCore


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
