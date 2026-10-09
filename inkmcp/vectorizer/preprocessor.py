"""Image preprocessing and color quantization module."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Union

import numpy as np
from PIL import Image
from sklearn.cluster import KMeans


@dataclass
class PreprocessedImageData:
    """Preprocessed image artifact containing cleaned image, color palette, and cluster masks."""

    image: Image.Image
    palette: List[str]
    color_masks: Dict[str, Image.Image]
    dimensions: Tuple[int, int]


def apply_bilateral_filter(
    img: Image.Image,
    diameter: int = 5,
    sigma_color: float = 25.0,
    sigma_space: float = 25.0,
) -> Image.Image:
    """Applies edge-preserving bilateral filtering to an RGBA image.

    Noise is smoothed while sharp contrast boundaries are preserved.
    The alpha channel is preserved as-is.
    """
    arr = np.array(img, dtype=np.float32)
    rgb = arr[:, :, :3]
    h, w, _ = rgb.shape
    radius = max(1, diameter // 2)

    # Spatial Gaussian weights
    y, x = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    spatial_weights = np.exp(-(x**2 + y**2) / (2.0 * (sigma_space**2)))

    padded = np.pad(rgb, ((radius, radius), (radius, radius), (0, 0)), mode="reflect")
    weight_sum = np.zeros((h, w, 1), dtype=np.float32)
    val_sum = np.zeros((h, w, 3), dtype=np.float32)

    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            sw = spatial_weights[dy + radius, dx + radius]
            neighbor = padded[
                radius + dy : radius + dy + h,
                radius + dx : radius + dx + w,
            ]
            diff = neighbor - rgb
            # Range weights based on Euclidean distance in RGB color space
            range_weights = np.exp(
                -np.sum(diff**2, axis=-1, keepdims=True) / (2.0 * (sigma_color**2))
            )
            total_w = sw * range_weights
            val_sum += total_w * neighbor
            weight_sum += total_w

    out_rgb = val_sum / np.maximum(weight_sum, 1e-6)
    out_rgb = np.clip(out_rgb, 0, 255).astype(np.uint8)

    arr[:, :, :3] = out_rgb
    return Image.fromarray(arr.astype(np.uint8), mode="RGBA")


class ImagePreprocessor:
    """Preprocesses bitmap images for vectorization workflows."""

    def __init__(
        self,
        filter_diameter: int = 5,
        sigma_color: float = 25.0,
        sigma_space: float = 25.0,
        bg_tolerance: float = 20.0,
    ) -> None:
        self.filter_diameter = filter_diameter
        self.sigma_color = sigma_color
        self.sigma_space = sigma_space
        self.bg_tolerance = bg_tolerance

    def process(
        self,
        image_input: Union[str, Path, Image.Image],
        num_colors: int = 8,
        remove_background: bool = False,
    ) -> PreprocessedImageData:
        """Process an input image: validate color count, remove background, smooth edges,

        quantize palette, and generate per-color binary masks.
        """
        if not (2 <= num_colors <= 32):
            raise ValueError("num_colors must be between 2 and 32")

        # Load and convert image to RGBA
        if isinstance(image_input, (str, Path)):
            img = Image.open(image_input).convert("RGBA")
        elif isinstance(image_input, Image.Image):
            img = image_input.convert("RGBA")
        else:
            raise TypeError(
                f"image_input must be a path or PIL.Image.Image, got {type(image_input).__name__}"
            )

        width, height = img.size

        # Background removal if requested
        if remove_background:
            corner_pixel = img.getpixel((0, 0))
            # Only remove if corner has opacity
            if corner_pixel[3] > 0:
                arr = np.array(img)
                corner_rgb = np.array(corner_pixel[:3], dtype=np.float32)
                rgb_data = arr[:, :, :3].astype(np.float32)
                diff = np.sqrt(np.sum((rgb_data - corner_rgb) ** 2, axis=-1))
                backdrop_mask = (diff <= self.bg_tolerance) & (arr[:, :, 3] > 0)
                arr[backdrop_mask, 3] = 0
                img = Image.fromarray(arr, mode="RGBA")

        # Edge-preserving bilateral filtering
        filtered_img = apply_bilateral_filter(
            img,
            diameter=self.filter_diameter,
            sigma_color=self.sigma_color,
            sigma_space=self.sigma_space,
        )

        arr = np.array(filtered_img)
        alpha = arr[:, :, 3]
        rgb = arr[:, :, :3]
        opaque_mask = alpha > 0

        # If entire image is transparent, return early
        if not np.any(opaque_mask):
            return PreprocessedImageData(
                image=filtered_img,
                palette=[],
                color_masks={},
                dimensions=(width, height),
            )

        pixels_to_cluster = rgb[opaque_mask]
        unique_colors = np.unique(pixels_to_cluster, axis=0)
        k = max(1, min(num_colors, len(unique_colors)))

        # Palette reduction via KMeans
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=1)
        cluster_labels = kmeans.fit_predict(pixels_to_cluster)
        centers = np.clip(np.round(kmeans.cluster_centers_), 0, 255).astype(int)

        # Count pixels per cluster to sort by prominence
        counts = np.bincount(cluster_labels, minlength=k)
        sorted_indices = np.argsort(-counts)

        # Map pixel positions back to image space
        full_labels = np.full((height, width), -1, dtype=int)
        full_labels[opaque_mask] = cluster_labels

        palette: List[str] = []
        color_masks: Dict[str, Image.Image] = {}
        quantized_rgb = np.copy(rgb)

        for idx in sorted_indices:
            r, g, b = centers[idx]
            hex_color = f"#{r:02X}{g:02X}{b:02X}"
            cluster_mask_arr = (full_labels == idx).astype(np.uint8) * 255

            if hex_color in color_masks:
                existing_arr = np.array(color_masks[hex_color])
                merged_arr = np.maximum(existing_arr, cluster_mask_arr)
                color_masks[hex_color] = Image.fromarray(merged_arr, mode="L")
            else:
                palette.append(hex_color)
                color_masks[hex_color] = Image.fromarray(cluster_mask_arr, mode="L")

            quantized_rgb[full_labels == idx] = [r, g, b]

        # Construct final quantized RGBA image
        cleaned_arr = np.dstack([quantized_rgb, alpha])
        cleaned_image = Image.fromarray(cleaned_arr.astype(np.uint8), mode="RGBA")

        return PreprocessedImageData(
            image=cleaned_image,
            palette=palette,
            color_masks=color_masks,
            dimensions=(width, height),
        )
