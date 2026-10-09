import pytest
from PIL import Image
from pathlib import Path
from inkmcp.vectorizer import ImagePreprocessor, PreprocessedImageData


def test_preprocessor_color_bounds_validation():
    preprocessor = ImagePreprocessor()
    img = Image.new("RGBA", (20, 20), (255, 0, 0, 255))

    with pytest.raises(ValueError, match="num_colors must be between 2 and 32"):
        preprocessor.process(img, num_colors=1)

    with pytest.raises(ValueError, match="num_colors must be between 2 and 32"):
        preprocessor.process(img, num_colors=0)

    with pytest.raises(ValueError, match="num_colors must be between 2 and 32"):
        preprocessor.process(img, num_colors=33)

    # Valid boundaries (2 and 32) should not raise ValueError
    res2 = preprocessor.process(img, num_colors=2)
    assert isinstance(res2, PreprocessedImageData)
    assert len(res2.palette) <= 2

    res32 = preprocessor.process(img, num_colors=32)
    assert isinstance(res32, PreprocessedImageData)
    assert len(res32.palette) <= 32


def test_preprocessor_solid_background_removal(tmp_path: Path):
    preprocessor = ImagePreprocessor()

    # Create a 40x40 image: white background with a 20x20 blue center square
    img = Image.new("RGBA", (40, 40), (255, 255, 255, 255))
    for x in range(10, 30):
        for y in range(10, 30):
            img.putpixel((x, y), (0, 0, 255, 255))

    # Also test passing a file path (str)
    img_path = tmp_path / "test_bg.png"
    img.save(img_path)

    result = preprocessor.process(str(img_path), num_colors=2, remove_background=True)
    assert isinstance(result, PreprocessedImageData)
    assert result.dimensions == (40, 40)
    assert result.image.mode == "RGBA"

    # Top-left corner (0, 0) should be transparent (alpha == 0)
    corner_pixel = result.image.getpixel((0, 0))
    assert corner_pixel[3] == 0, f"Expected transparent alpha at (0, 0), got {corner_pixel}"

    # Center pixel (20, 20) should remain opaque (alpha == 255) and blue-ish
    center_pixel = result.image.getpixel((20, 20))
    assert center_pixel[3] == 255, f"Expected opaque alpha at (20, 20), got {center_pixel}"
    assert center_pixel[2] > 200, f"Expected blue color at (20, 20), got {center_pixel}"


def test_preprocessor_palette_and_masks():
    preprocessor = ImagePreprocessor()

    # Create an image with 3 distinct color regions: Red, Green, Blue
    img = Image.new("RGBA", (60, 60), (255, 0, 0, 255))
    for x in range(20, 40):
        for y in range(60):
            img.putpixel((x, y), (0, 255, 0, 255))
    for x in range(40, 60):
        for y in range(60):
            img.putpixel((x, y), (0, 0, 255, 255))

    result = preprocessor.process(img, num_colors=3, remove_background=False)
    assert isinstance(result, PreprocessedImageData)
    assert result.dimensions == (60, 60)
    assert result.image.size == (60, 60)
    assert len(result.palette) >= 2 and len(result.palette) <= 3

    # Verify palette hex format #RRGGBB
    import re
    hex_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
    for hex_color in result.palette:
        assert hex_pattern.match(hex_color), f"Invalid hex color format: {hex_color}"

    # Verify color masks
    assert set(result.color_masks.keys()) == set(result.palette)
    for hex_color, mask in result.color_masks.items():
        assert mask.size == (60, 60)
        assert mask.mode in ("1", "L")
        # Ensure mask is not empty (has foreground pixels)
        extrema = mask.getextrema()
        assert extrema[1] > 0, f"Mask for {hex_color} has no active pixels"


def test_preprocessor_invalid_input_type():
    preprocessor = ImagePreprocessor()
    with pytest.raises(TypeError, match="image_input must be a path or PIL.Image.Image"):
        preprocessor.process(12345)


def test_preprocessor_grayscale_and_fully_transparent():
    preprocessor = ImagePreprocessor()

    # Grayscale image input
    gray_img = Image.new("L", (30, 30), 128)
    res_gray = preprocessor.process(gray_img, num_colors=2)
    assert res_gray.image.mode == "RGBA"
    assert len(res_gray.palette) >= 1

    # Fully transparent image
    transparent_img = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    res_trans = preprocessor.process(transparent_img, num_colors=4)
    assert res_trans.palette == []
    assert res_trans.color_masks == {}
    assert res_trans.dimensions == (20, 20)

