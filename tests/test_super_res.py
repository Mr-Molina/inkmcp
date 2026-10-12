"""Unit tests for edge-preserving super-resolution and subpixel quantization."""

import numpy as np
from inkmcp.vectorizer.super_res import (
    upscale_edge_preserving,
    quantize_to_palette_subpixel,
)


def test_upscale_edge_preserving_dimensions():
    """Validates that upscale_edge_preserving expands dimensions by scale factor."""
    dummy_img = np.zeros((50, 50, 3), dtype=np.uint8)
    dummy_img[10:40, 10:40] = [200, 100, 50]

    upscaled = upscale_edge_preserving(dummy_img, scale=4)
    assert upscaled.shape == (200, 200, 3)
    assert upscaled.dtype == np.uint8


def test_upscale_edge_preserving_with_alpha():
    """Validates that RGBA images retain alpha channel after upscaling."""
    dummy_rgba = np.zeros((40, 40, 4), dtype=np.uint8)
    dummy_rgba[:, :, 3] = 255
    dummy_rgba[10:30, 10:30, :3] = [234, 63, 46]

    upscaled = upscale_edge_preserving(dummy_rgba, scale=2)
    assert upscaled.shape == (80, 80, 4)
    assert upscaled[20, 20, 3] == 255


def test_quantize_to_palette_subpixel_exact_colors():
    """Verifies that every pixel in quantized output strictly belongs to input palette."""
    palette = [
        (255, 255, 255),
        (234, 63, 46),
        (19, 150, 206),
        (0, 0, 0),
    ]

    test_img = np.array([
        [[230, 60, 40], [250, 250, 250]],
        [[15, 140, 200], [5, 5, 5]],
    ], dtype=np.uint8)

    quantized = quantize_to_palette_subpixel(test_img, palette)

    palette_set = set(palette)
    for y in range(quantized.shape[0]):
        for x in range(quantized.shape[1]):
            pixel_tuple = tuple(quantized[y, x].tolist())
            assert pixel_tuple in palette_set

    # Verify nearest mapping
    assert tuple(quantized[0, 0].tolist()) == (234, 63, 46)
    assert tuple(quantized[0, 1].tolist()) == (255, 255, 255)
    assert tuple(quantized[1, 0].tolist()) == (19, 150, 206)
    assert tuple(quantized[1, 1].tolist()) == (0, 0, 0)
