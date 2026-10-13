import pytest
import numpy as np
import cv2
from PIL import Image
from inkmcp.vectorizer.outline_generator import OutlineGenerator

def test_prompt_template_contents():
    assert "coloring book" in OutlineGenerator.PROMPT_TEMPLATE.lower()
    assert "black outline" in OutlineGenerator.PROMPT_TEMPLATE.lower()

def test_load_existing_outline(tmp_path):
    img = Image.new("L", (100, 100), 255)
    path = tmp_path / "out.png"
    img.save(path)

    gen = OutlineGenerator()
    arr = gen.generate_outline("dummy_src.png", outline_path=str(path))
    assert arr.shape == (100, 100)
    assert set(np.unique(arr)).issubset({0, 255})

def test_algorithmic_edge_fallback(tmp_path):
    src = Image.new("RGB", (100, 100), (255, 255, 255))
    src_arr = np.full((100, 100, 3), 255, dtype=np.uint8)
    cv2.circle(src_arr, (50, 50), 20, (0, 0, 255), -1)
    src_path = tmp_path / "circle.png"
    Image.fromarray(src_arr).save(src_path)

    gen = OutlineGenerator()
    arr = gen.generate_outline(str(src_path), outline_path=None)
    assert arr.shape == (100, 100)
    assert 0 in arr
    assert 255 in arr
