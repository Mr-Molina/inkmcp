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

    Preserves alpha channel transparency if present.

    Args:
        image: Upscaled RGB or RGBA uint8 array.
        palette_rgb: List of (R, G, B) integer tuples.
        block_size: Vertical block height to constrain peak memory during nearest-color search.

    Returns:
        Quantized uint8 array matching palette colors with alpha preserved.
    """
    pal_arr = np.array(palette_rgb, dtype=np.float32)
    h, w = image.shape[:2]
    has_alpha = image.shape[2] == 4 if len(image.shape) > 2 else False

    if has_alpha:
        out = np.zeros((h, w, 4), dtype=np.uint8)
        out[:, :, 3] = image[:, :, 3]
    else:
        out = np.zeros((h, w, 3), dtype=np.uint8)

    num_blocks = (h + block_size - 1) // block_size
    for b in range(num_blocks):
        y_start = b * block_size
        y_end = min(h, (b + 1) * block_size)
        block = image[y_start:y_end, :, :3].astype(np.float32)
        dists = np.sum(
            (block[:, :, :, None] - pal_arr.T[None, None, :, :]) ** 2, axis=2
        )
        best_idx = np.argmin(dists, axis=-1)
        out[y_start:y_end, :, :3] = pal_arr[best_idx].astype(np.uint8)

    return out


class SuperResolutionProcessor:
    """High-resolution edge-preserving image upscaler and palette quantizer."""

    def __init__(
        self,
        scale_factor: int = 4,
        denoise: bool = True,
        block_quantize: bool = True,
    ):
        self.scale_factor = scale_factor
        self.denoise = denoise
        self.block_quantize = block_quantize

    def process(
        self,
        image_input,
        num_colors: int = 8,
    ) -> Image.Image:
        """Processes input image with Lanczos4 expansion, bilateral filtering, and palette quantization."""
        from pathlib import Path
        if isinstance(image_input, (str, Path)):
            pil_img = Image.open(str(image_input))
            if pil_img.mode in ("RGBA", "LA") or "transparency" in pil_img.info:
                pil_img = pil_img.convert("RGBA")
            else:
                pil_img = pil_img.convert("RGB")
            arr = np.array(pil_img)
        elif isinstance(image_input, Image.Image):
            if image_input.mode in ("RGBA", "LA") or "transparency" in image_input.info:
                pil_img = image_input.convert("RGBA")
            else:
                pil_img = image_input.convert("RGB")
            arr = np.array(pil_img)
        elif isinstance(image_input, np.ndarray):
            arr = image_input
        else:
            raise TypeError(f"Unsupported image type: {type(image_input)}")

        # 1. Upscale with edge-preserving bilateral filtering
        upscaled = upscale_edge_preserving(arr, scale=self.scale_factor)

        # 2. Extract discrete palette and block-quantize if requested
        if self.block_quantize and num_colors > 0:
            from inkmcp.vectorizer.preprocessor import ImagePreprocessor
            from inkmcp.vectorizer.palette import hex_to_rgb
            prep = ImagePreprocessor()
            prep_res = prep.process(
                Image.fromarray(arr), num_colors=num_colors, denoise=self.denoise
            )
            palette_rgb = [hex_to_rgb(hex_code) for hex_code in prep_res.palette]
            if palette_rgb:
                quantized = quantize_to_palette_subpixel(upscaled, palette_rgb)
                return Image.fromarray(quantized)

        return Image.fromarray(upscaled)

