import pytest
from unittest.mock import patch
from PIL import Image
from inkmcp.inkmcpops.vectorize_operations import vectorize_image_operation

def test_vectorize_coloring_book_dispatch(tmp_path):
    img_path = tmp_path / "test.png"
    Image.new("RGB", (50, 50), (255, 0, 0)).save(img_path)

    with patch("inkmcp.vectorizer.coloring_book_pipeline.ColoringBookPipeline.run") as mock_run:
        mock_run.return_value = {"status": "success", "data": {"regions_detected": 1}}
        result = vectorize_image_operation({
            "image_path": str(img_path),
            "mode": "coloring_book",
        })
        assert result["status"] == "success"
        mock_run.assert_called_once()
