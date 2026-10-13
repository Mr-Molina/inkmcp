"""Color inventory and spatial indexing module using CIELAB color clustering."""
import math
from pathlib import Path
from typing import List
import cv2
import numpy as np


class ColorInventory:
    """Extracts dominant palette using CIELAB K-Means and provides spatial coordinate color queries."""

    def __init__(self, palette: List[str], spatial_map: np.ndarray):
        self._palette = [p.upper() for p in palette]
        self._spatial_map = spatial_map  # Downscaled RGB array (H, W, 3)

    @classmethod
    def from_image(cls, image_path: str, num_colors: int = 8) -> "ColorInventory":
        if num_colors <= 0:
            raise ValueError(f"num_colors must be greater than 0, got {num_colors}")

        path_obj = Path(image_path)
        if not path_obj.exists() or not path_obj.is_file():
            raise FileNotFoundError(f"Source image not found: {image_path}")

        img = cv2.imread(str(path_obj), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Could not decode image at {image_path}")

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img_rgb.shape[:2]
        if h <= 0 or w <= 0:
            raise ValueError(f"Invalid image dimensions: {w}x{h}")

        max_dim = 256
        scale = min(1.0, max_dim / max(h, w))
        if scale < 1.0:
            thumb_w = max(1, int(w * scale))
            thumb_h = max(1, int(h * scale))
            thumb_rgb = cv2.resize(img_rgb, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        else:
            thumb_rgb = img_rgb.copy()

        # Convert to CIELAB float for perceptual color clustering without 8-bit quantization loss
        thumb_f = thumb_rgb.astype(np.float32) / 255.0
        thumb_lab = cv2.cvtColor(thumb_f, cv2.COLOR_RGB2Lab)
        pixels_lab = thumb_lab.reshape(-1, 3)

        unique_pixels = np.unique(pixels_lab, axis=0)
        actual_k = min(max(1, num_colors), len(unique_pixels))

        if actual_k <= 1:
            mean_rgb = np.round(np.mean(thumb_rgb.reshape(-1, 3), axis=0)).astype(int)
            hex_color = f"#{mean_rgb[0]:02X}{mean_rgb[1]:02X}{mean_rgb[2]:02X}"
            return cls(palette=[hex_color], spatial_map=thumb_rgb)

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        flags = cv2.KMEANS_PP_CENTERS
        best_labels = np.empty((0, 0), dtype=np.int32)
        _, labels, centers_lab = cv2.kmeans(
            pixels_lab.astype(np.float32), actual_k, best_labels, criteria, 10, flags
        )

        flat_labels = labels.flatten()
        pixels_rgb = thumb_rgb.reshape(-1, 3)

        # Compute cluster RGB colors from cluster pixel assignments
        centers_rgb = np.zeros((actual_k, 3), dtype=np.uint8)
        for k in range(actual_k):
            mask = flat_labels == k
            if np.any(mask):
                centers_rgb[k] = np.round(np.mean(pixels_rgb[mask], axis=0)).astype(np.uint8)
            else:
                # Fallback to CIELAB cluster center conversion
                center_lab = centers_lab[k : k + 1].reshape(1, 1, 3).astype(np.float32)
                rgb_f = cv2.cvtColor(center_lab, cv2.COLOR_Lab2RGB).reshape(3)
                centers_rgb[k] = np.clip(np.round(rgb_f * 255.0), 0, 255).astype(np.uint8)

        palette = [f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}" for c in centers_rgb]
        clustered_rgb = centers_rgb[flat_labels].reshape(thumb_rgb.shape)
        return cls(palette=palette, spatial_map=clustered_rgb)

    def get_palette(self) -> List[str]:
        return list(self._palette)

    def get_color_at(self, u: float, v: float) -> str:
        h, w = self._spatial_map.shape[:2]
        if h <= 0 or w <= 0:
            return "#000000"
        if math.isnan(u) or math.isinf(u):
            u = 0.0
        if math.isnan(v) or math.isinf(v):
            v = 0.0
        u_clamped = max(0.0, min(1.0, float(u)))
        v_clamped = max(0.0, min(1.0, float(v)))
        x = max(0, min(int(u_clamped * w), w - 1))
        y = max(0, min(int(v_clamped * h), h - 1))
        pixel = self._spatial_map[y, x]
        return f"#{pixel[0]:02X}{pixel[1]:02X}{pixel[2]:02X}"
