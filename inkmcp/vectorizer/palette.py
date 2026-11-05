"""Perceptual color standardization and palette clustering for vectorization."""

import math
from typing import Dict, List, Tuple

from inkmcp.vectorizer.core import normalize_color_hex


def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    """Converts a hex color string to an (R, G, B) integer tuple (0-255)."""
    norm = normalize_color_hex(hex_str).lstrip("#")
    return int(norm[0:2], 16), int(norm[2:4], 16), int(norm[4:6], 16)


def _srgb_to_linear(c_byte: int) -> float:
    """Converts an 8-bit sRGB channel (0-255) to linear light float [0.0, 1.0]."""
    c = max(0, min(255, c_byte)) / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _f_lab(t: float) -> float:
    """Nonlinear transfer function for CIELAB conversion."""
    delta = 6.0 / 29.0
    if t > delta**3:
        return t ** (1.0 / 3.0)
    return (t / (3.0 * delta * delta)) + (4.0 / 29.0)


def rgb_to_lab(rgb: Tuple[int, int, int]) -> Tuple[float, float, float]:
    """Converts sRGB (0-255) to CIELAB (D65 standard observer).

    Pipeline: sRGB -> Linear RGB -> CIE XYZ (D65) -> CIELAB.
    """
    r_lin = _srgb_to_linear(rgb[0])
    g_lin = _srgb_to_linear(rgb[1])
    b_lin = _srgb_to_linear(rgb[2])

    # sRGB D65 transformation matrix to CIE XYZ
    x = r_lin * 0.4124564 + g_lin * 0.3575761 + b_lin * 0.1804375
    y = r_lin * 0.2126729 + g_lin * 0.7151522 + b_lin * 0.0721750
    z = r_lin * 0.0193339 + g_lin * 0.1191920 + b_lin * 0.9503041

    # D65 reference white normalization (Xn=0.95047, Yn=1.00000, Zn=1.08883)
    xr = x / 0.95047
    yr = y / 1.00000
    zr = z / 1.08883

    fx = _f_lab(xr)
    fy = _f_lab(yr)
    fz = _f_lab(zr)

    l_star = 116.0 * fy - 16.0
    a_star = 500.0 * (fx - fy)
    b_star = 200.0 * (fy - fz)

    return (l_star, a_star, b_star)


def delta_e_cie76(
    lab1: Tuple[float, float, float],
    lab2: Tuple[float, float, float],
) -> float:
    """Computes the CIE76 color difference (Euclidean distance in CIELAB space)."""
    return math.sqrt(
        (lab1[0] - lab2[0]) ** 2
        + (lab1[1] - lab2[1]) ** 2
        + (lab1[2] - lab2[2]) ** 2
    )


def standardize_color_palette(
    colors_with_areas: Dict[str, float],
    delta_e_threshold: float = 5.0,
) -> Dict[str, str]:
    """Standardizes color palette by clustering perceptually similar colors.

    Args:
        colors_with_areas: Mapping of hex color strings to their surface areas.
        delta_e_threshold: Maximum CIELAB Delta E (CIE76) distance to merge colors.
            If <= 0.0, returns identity mapping.

    Returns:
        Dictionary mapping original_hex to canonical_hex.
    """
    if not colors_with_areas:
        return {}

    if delta_e_threshold <= 0.0:
        return {color: color for color in colors_with_areas}

    # Sort colors by area descending (largest surface area acts as cluster anchor)
    sorted_colors = sorted(
        colors_with_areas.keys(),
        key=lambda c: colors_with_areas[c],
        reverse=True,
    )

    anchors: List[Tuple[str, Tuple[float, float, float]]] = []
    mapping: Dict[str, str] = {}

    for color in sorted_colors:
        rgb = hex_to_rgb(color)
        lab = rgb_to_lab(rgb)

        matched_anchor = None
        for anchor_hex, anchor_lab in anchors:
            if delta_e_cie76(lab, anchor_lab) <= delta_e_threshold:
                matched_anchor = anchor_hex
                break

        if matched_anchor is not None:
            mapping[color] = matched_anchor
        else:
            anchors.append((color, lab))
            mapping[color] = color

    return mapping
