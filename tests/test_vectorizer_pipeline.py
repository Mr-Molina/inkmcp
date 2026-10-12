"""Integration tests for inkmcp.vectorizer.pipeline."""

import os
import tempfile
import numpy as np
from PIL import Image
import pytest

from inkmcp.vectorizer.pipeline import (
    PipelineConfig,
    PipelineResult,
    VectorizationPipeline,
)


@pytest.fixture
def sample_test_raster():
    """Creates a temporary 200x200 test image with concentric geometric shapes."""
    img = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
    # Draw navy outer box, yellow inner box, and a red circle
    pixels = np.array(img)
    # Navy box [20:180, 20:180]
    pixels[20:180, 20:180] = [0, 0, 128, 255]
    # Yellow box [50:150, 50:150]
    pixels[50:150, 50:150] = [255, 255, 0, 255]
    # Red circle in center [80:120, 80:120]
    y, x = np.ogrid[:200, :200]
    mask = (x - 100) ** 2 + (y - 100) ** 2 <= 20 ** 2
    pixels[mask] = [220, 0, 0, 255]

    test_img = Image.fromarray(pixels)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        temp_path = f.name
    test_img.save(temp_path, format="PNG")
    yield temp_path
    if os.path.exists(temp_path):
        os.remove(temp_path)


def test_vectorization_pipeline_execution(sample_test_raster):
    """Verifies end-to-end execution of VectorizationPipeline from raster to cut-ready SVG."""
    config = PipelineConfig(
        super_res_scale=1,  # Keep scale 1 for fast unit test execution
        node_tolerance=0.5,
        enable_trapping=True,
        trap_distance=1.0,
        optimize_cam=True,
    )
    pipeline = VectorizationPipeline(config)
    result = pipeline.run(sample_test_raster)

    assert isinstance(result, PipelineResult)
    assert "<svg" in result.svg_content
    assert "</svg>" in result.svg_content
    assert result.layers_count >= 1
    assert result.total_nodes_optimized <= result.total_nodes_original
    assert result.cut_ready_svg is not None
    assert "<path" in result.cut_ready_svg


def test_vectorization_pipeline_modes(sample_test_raster):
    """Verifies pipeline generates both cut-ready and layered SVG assembly outputs."""
    pipeline = VectorizationPipeline()
    result = pipeline.run(sample_test_raster)

    assert result.cut_ready_svg is not None
    assert result.layered_svg is not None
    assert "inkscape:groupmode=\"layer\"" in result.layered_svg
