import pytest
from PIL import Image, ImageDraw
from pathlib import Path
import numpy as np
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


def test_preprocessor_silhouette_mode_extracts_single_palette():
    import numpy as np
    from PIL import ImageDraw

    # Create 100x100 white image with an orange circle
    img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse([20, 20, 80, 80], fill=(226, 131, 11, 255))

    prep = ImagePreprocessor()
    result = prep.process(img, mode="silhouette")

    # Must return exactly 1 foreground color in palette
    assert len(result.palette) == 1
    assert result.palette[0] == "#E2830B"
    assert len(result.color_masks) == 1
    assert "#E2830B" in result.color_masks

    # Alpha channel must be transparent where background was white
    arr = np.array(result.image)
    assert arr[0, 0, 3] == 0
    assert arr[50, 50, 3] == 255
    # Foreground RGB must match median color
    assert tuple(arr[50, 50, :3]) == (226, 131, 11)


def test_preprocessor_silhouette_solid_white():
    prep = ImagePreprocessor()
    img = Image.new("RGBA", (50, 50), (255, 255, 255, 255))
    result = prep.process(img, mode="silhouette")

    assert result.palette == []
    assert result.color_masks == {}
    assert result.dimensions == (50, 50)
    arr = np.array(result.image)
    assert arr[:, :, 3].max() == 0


def test_preprocessor_silhouette_solid_color():
    prep = ImagePreprocessor()
    img = Image.new("RGBA", (50, 50), (200, 50, 50, 255))
    result = prep.process(img, mode="silhouette")

    assert result.palette == []
    assert result.color_masks == {}
    assert result.dimensions == (50, 50)
    arr = np.array(result.image)
    assert arr[:, :, 3].max() == 0


def test_preprocessor_silhouette_subtle_corner_noise():
    import numpy as np
    from PIL import ImageDraw

    # 80x80 image with subtle noise across corners
    img = Image.new("RGBA", (80, 80), (255, 255, 255, 255))
    img.putpixel((0, 0), (254, 255, 255, 255))
    img.putpixel((79, 0), (255, 254, 255, 255))
    img.putpixel((0, 79), (255, 255, 254, 255))
    img.putpixel((79, 79), (253, 254, 255, 255))

    # Black square in center
    draw = ImageDraw.Draw(img)
    draw.rectangle([25, 25, 55, 55], fill=(10, 10, 10, 255))

    prep = ImagePreprocessor()
    result = prep.process(img, mode="silhouette")

    assert len(result.palette) == 1
    assert result.palette[0] == "#0A0A0A"
    arr = np.array(result.image)
    assert arr[0, 0, 3] == 0
    assert arr[79, 79, 3] == 0
    assert arr[40, 40, 3] == 255


def test_preprocessor_silhouette_otsu_bimodal_gradient():
    from inkmcp.vectorizer.preprocessor import compute_otsu_threshold

    # Synthetic bimodal data: background cluster around 5, foreground cluster around 220
    np.random.seed(42)
    bg_distances = np.random.normal(loc=5.0, scale=2.0, size=1000)
    fg_distances = np.random.normal(loc=220.0, scale=15.0, size=1000)
    # Add gradient ramp values between 30 and 190
    ramp = np.linspace(30.0, 190.0, 100)
    combined = np.concatenate([bg_distances, fg_distances, ramp])
    combined = np.clip(combined, 0.0, 255.0)

    thresh = compute_otsu_threshold(combined, min_threshold=25.0)
    # Optimal Otsu threshold must lie in the valley between the two peaks (70..150)
    assert 70.0 < thresh < 150.0

    # Image-level test: White canvas with black subject and antialiased gray fringe
    img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Inner solid black circle
    draw.ellipse([30, 30, 70, 70], fill=(0, 0, 0, 255))
    # Intermediate gray fringe ring around it
    draw.ellipse([27, 27, 73, 73], outline=(150, 150, 150, 255), width=2)

    prep = ImagePreprocessor()
    result = prep.process(img, mode="silhouette")

    assert len(result.palette) == 1
    assert result.palette[0] == "#000000"
    arr = np.array(result.image)
    # Corners are transparent background
    assert arr[0, 0, 3] == 0
    # Center is solid foreground
    assert arr[50, 50, 3] == 255
    assert tuple(arr[50, 50, :3]) == (0, 0, 0)


def test_preprocessor_silhouette_subpixel_scale():
    """Verify silhouette mode with subpixel_scale=2 upscales processed_image while preserving 1x output dimensions."""
    img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse([20, 20, 80, 80], fill=(226, 131, 11, 255))

    prep = ImagePreprocessor()
    result = prep.process(img, mode="silhouette", subpixel_scale=2)

    assert result.subpixel_scale == 2
    assert result.dimensions == (100, 100)
    assert result.image.size == (100, 100)
    assert result.processed_image is not None
    assert result.processed_image.size == (200, 200)
    assert len(result.palette) == 1
    assert result.palette[0] == "#E2830B"
    assert result.color_masks["#E2830B"].size == (100, 100)




