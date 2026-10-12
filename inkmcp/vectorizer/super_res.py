"""Edge-preserving super-resolution and subpixel quantization module."""

import logging
from typing import List, Optional, Tuple
import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def upscale_edge_preserving(
    image: np.ndarray,
    scale: int = 4,
    d: int = 7,
    sigma_color: float = 30.0,
    sigma_space: float = 5.0,
) -> np.ndarray:
    """Upscales an image using Lanczos interpolation followed by bilateral edge filtering.

    This expands pixel resolution to subpixel accuracy, smoothing flat color plateaus
    while preserving and sharpening genuine boundaries without generative drift.

    Args:
        image: Input RGB or RGBA uint8 numpy array.
        scale: Upscaling factor (default: 4 for 4x subpixel density).
        d: Diameter of each pixel neighborhood for bilateral filter.
        sigma_color: Filter sigma in the color space.
        sigma_space: Filter sigma in the coordinate space.

    Returns:
        Upscaled uint8 numpy array with smoothed plateaus and sharp edges.
    """
    h, w = image.shape[:2]
    # Convert RGB to BGR for OpenCV processing
    has_alpha = image.shape[2] == 4 if len(image.shape) > 2 else False
    if has_alpha:
        bgr = cv2.cvtColor(image[:, :, :3], cv2.COLOR_RGB2BGR)
        alpha = image[:, :, 3]
    else:
        bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        alpha = None

    up_bgr = cv2.resize(
        bgr, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4
    )
    smooth_bgr = cv2.bilateralFilter(
        up_bgr, d=d, sigmaColor=sigma_color, sigmaSpace=sigma_space
    )
    smooth_rgb = cv2.cvtColor(smooth_bgr, cv2.COLOR_BGR2RGB)

    if has_alpha and alpha is not None:
        up_alpha = cv2.resize(
            alpha, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4
        )
        return np.dstack([smooth_rgb, up_alpha])
    return smooth_rgb


def quantize_to_palette_subpixel(
    image: np.ndarray,
    palette_rgb: List[Tuple[int, int, int]],
    block_size: int = 1024,
) -> np.ndarray:
    """Quantizes an upscaled image to a discrete color palette in memory-efficient blocks.

    Args:
        image: Upscaled RGB uint8 array.
        palette_rgb: List of (R, G, B) integer tuples.
        block_size: Vertical block height to constrain peak memory during nearest-color search.

    Returns:
        Quantized uint8 array matching palette colors.
    """
    pal_arr = np.array(palette_rgb, dtype=np.float32)
    h, w = image.shape[:2]
    out_rgb = np.zeros((h, w, 3), dtype=np.uint8)

    num_blocks = (h + block_size - 1) // block_size
    for b in range(num_blocks):
        y_start = b * block_size
        y_end = min(h, (b + 1) * block_size)
        block = image[y_start:y_end, :, :3].astype(np.float32)
        dists = np.sum(
            (block[:, :, :, None] - pal_arr.T[None, None, :, :]) ** 2, axis=2
        )
        best_idx = np.argmin(dists, axis=-1)
        out_rgb[y_start:y_end] = pal_arr[best_idx].astype(np.uint8)

    return out_rgb
