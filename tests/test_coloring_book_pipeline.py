import pytest
from unittest.mock import MagicMock, patch
from PIL import Image
from inkmcp.vectorizer.coloring_book_pipeline import ColoringBookPipeline

@pytest.fixture
def mock_outline_and_source(tmp_path):
    src = Image.new("RGB", (100, 100), (255, 0, 0))
    src_path = tmp_path / "source.png"
    src.save(src_path)

    out = Image.new("L", (100, 100), 255)
    out_path = tmp_path / "outline.png"
    out.save(out_path)

    return str(src_path), str(out_path)

def test_coloring_book_pipeline_end_to_end(mock_outline_and_source, tmp_path):
    src_path, out_path = mock_outline_and_source
    out_svg = tmp_path / "output.svg"
    pipeline = ColoringBookPipeline()

    mock_backend = MagicMock()
    mock_backend.is_available.return_value = True

    with patch.object(pipeline._automator, "execute_sequence", return_value={"status": "success", "clicks_dispatched": 1}):
        result = pipeline.run({
            "image_path": src_path,
            "outline_path": out_path,
            "output_path": str(out_svg),
            "inject_to_inkscape": True,
        }, backend=mock_backend)

        assert result["status"] == "success"
        assert result["data"]["regions_detected"] >= 1
        assert out_svg.exists()
