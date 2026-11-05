import pytest
import numpy as np
from PIL import Image
from inkmcp.vectorizer.color_inventory import ColorInventory

@pytest.fixture
def synthetic_quad_image(tmp_path):
    arr = np.zeros((100, 100, 3), dtype=np.uint8)
    arr[0:50, 0:50] = [255, 0, 0]      # Red
    arr[0:50, 50:100] = [0, 255, 0]    # Green
    arr[50:100, 0:50] = [0, 0, 255]    # Blue
    arr[50:100, 50:100] = [255, 255, 0]# Yellow
    img = Image.fromarray(arr)
    path = tmp_path / "quad.png"
    img.save(path)
    return str(path)

def test_color_inventory_palette_extraction(synthetic_quad_image):
    inventory = ColorInventory.from_image(synthetic_quad_image, num_colors=4)
    palette = inventory.get_palette()
    assert len(palette) == 4
    hex_set = {c.upper() for c in palette}
    assert "#FF0000" in hex_set
    assert "#00FF00" in hex_set
    assert "#0000FF" in hex_set

def test_color_inventory_spatial_lookup(synthetic_quad_image):
    inventory = ColorInventory.from_image(synthetic_quad_image, num_colors=4)
    assert inventory.get_color_at(0.25, 0.25).upper() == "#FF0000"
    assert inventory.get_color_at(0.75, 0.25).upper() == "#00FF00"
    assert inventory.get_color_at(0.25, 0.75).upper() == "#0000FF"
    assert inventory.get_color_at(0.75, 0.75).upper() == "#FFFF00"

def test_color_inventory_missing_file():
    with pytest.raises(FileNotFoundError):
        ColorInventory.from_image("nonexistent_test_file.png")

def test_color_inventory_monochrome(tmp_path):
    img = Image.new("RGB", (50, 50), color=(128, 128, 128))
    path = tmp_path / "gray.png"
    img.save(path)
    inventory = ColorInventory.from_image(str(path), num_colors=4)
    palette = inventory.get_palette()
    assert len(palette) >= 1
    assert inventory.get_color_at(0.5, 0.5).upper() == "#808080"
