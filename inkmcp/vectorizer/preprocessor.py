"""Image preprocessing and color quantization module."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

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
    processed_image: Optional[Image.Image] = None


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
    if diameter <= 0:
        return img.copy()

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


def compute_otsu_threshold(
    distances: np.ndarray, min_threshold: float = 25.0
) -> float:
    """Computes the optimal binary threshold using Otsu's method on a distance map.

    Calculates between-class variance across 256 histogram bins and selects the
    threshold that maximizes separation between foreground and background, clamped
    to min_threshold as a lower bound.
    """
    if distances.size == 0 or np.all(distances == distances[0]):
        return min_threshold

    max_val = max(255.0, float(np.max(distances)))
    hist, bin_edges = np.histogram(distances, bins=256, range=(0.0, max_val))
    total = distances.size

    # Probability mass function
    p = hist.astype(np.float64) / total

    # Cumulative sums of class weights
    w0 = np.cumsum(p)
    w1 = 1.0 - w0

    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    mu_k = np.cumsum(p * bin_centers)
    mu_t = mu_k[-1]

    valid = (w0 > 1e-6) & (w1 > 1e-6)
    if not np.any(valid):
        return min_threshold

    # Between-class variance: (mu_t * w0 - mu_k)^2 / (w0 * w1)
    variance = np.zeros_like(p)
    variance[valid] = ((mu_t * w0[valid] - mu_k[valid]) ** 2) / (w0[valid] * w1[valid])

    best_idx = np.argmax(variance)
    threshold = float(bin_centers[best_idx])

    return max(threshold, min_threshold)


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
        mode: str = "cut_ready",
        denoise: bool = True,
    ) -> PreprocessedImageData:
        """Process an input image for vectorization.

        Args:
            image_input: File path (str or Path) or PIL.Image.Image instance.
            num_colors: Target number of colors for quantization (2-32). Ignored in silhouette mode.
            remove_background: If True, detects background from corner pixels and makes it transparent.
            mode: Processing mode - "cut_ready" (default, multi-color quantization),
                "layered", or "silhouette" (Otsu-binarized single foreground layer with
                transparent background and compound hole preservation).
            denoise: Whether to apply bilateral filter denoising (default: True).

        Returns:
            PreprocessedImageData containing cleaned RGBA image, palette, color masks,
            dimensions, and processed_image.
        """
        if mode != "silhouette":
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

        if mode == "silhouette":
            if self.filter_diameter > 0 and denoise:
                filtered_img = apply_bilateral_filter(
                    img,
                    diameter=self.filter_diameter,
                    sigma_color=self.sigma_color,
                    sigma_space=self.sigma_space,
                )
            else:
                filtered_img = img.copy()

            arr = np.array(filtered_img)
            corner_coords = [
                (0, 0),
                (max(0, width - 1), 0),
                (0, max(0, height - 1)),
                (max(0, width - 1), max(0, height - 1)),
            ]
            corners = [arr[y, x] for x, y in corner_coords]
            transparent_corners = [c for c in corners if c[3] == 0]

            if len(transparent_corners) >= 2:
                fg_mask = arr[:, :, 3] > 0
            else:
                opaque_corners = [c[:3].astype(np.float32) for c in corners if c[3] > 0]
                if opaque_corners:
                    bg_color = np.median(opaque_corners, axis=0)
                    diff = np.sqrt(
                        np.sum(
                            (arr[:, :, :3].astype(np.float32) - bg_color) ** 2,
                            axis=-1,
                        )
                    )
                    min_thresh = max(self.bg_tolerance, 25.0)
                    opaque_mask = arr[:, :, 3] > 0
                    threshold = compute_otsu_threshold(
                        diff[opaque_mask], min_threshold=min_thresh
                    )
                    fg_mask = (diff > threshold) & opaque_mask
                else:
                    fg_mask = arr[:, :, 3] > 0

            if not np.any(fg_mask):
                cleaned_arr = np.zeros((height, width, 4), dtype=np.uint8)
                blank_proc = Image.new("RGB", (width, height), (255, 255, 255))
                return PreprocessedImageData(
                    image=Image.fromarray(cleaned_arr, mode="RGBA"),
                    palette=[],
                    color_masks={},
                    dimensions=(width, height),
                    processed_image=blank_proc,
                )

            orig_arr = np.array(img)
            fg_pixels = orig_arr[fg_mask, :3]
            median_rgb = np.median(fg_pixels, axis=0)
            r, g, b = [int(np.clip(np.round(c), 0, 255)) for c in median_rgb]
            canonical_hex = f"#{r:02X}{g:02X}{b:02X}"

            cleaned_arr = np.zeros((height, width, 4), dtype=np.uint8)
            cleaned_arr[fg_mask, :3] = [r, g, b]
            cleaned_arr[fg_mask, 3] = 255
            cleaned_image = Image.fromarray(cleaned_arr, mode="RGBA")

            # Binary tracing image: foreground is black [0, 0, 0], background is white [255, 255, 255]
            binary_arr = np.full((height, width, 3), 255, dtype=np.uint8)
            binary_arr[fg_mask] = [0, 0, 0]
            processed_image = Image.fromarray(binary_arr, mode="RGB")

            palette = [canonical_hex]
            color_masks = {
                canonical_hex: Image.fromarray(
                    (fg_mask * 255).astype(np.uint8), mode="L"
                )
            }

            return PreprocessedImageData(
                image=cleaned_image,
                palette=palette,
                color_masks=color_masks,
                dimensions=(width, height),
                processed_image=processed_image,
            )

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
        if self.filter_diameter > 0 and denoise:
            filtered_img = apply_bilateral_filter(
                img,
                diameter=self.filter_diameter,
                sigma_color=self.sigma_color,
                sigma_space=self.sigma_space,
            )
        else:
            filtered_img = img.copy()

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
