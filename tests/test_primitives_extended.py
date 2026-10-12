"""Unit tests for inkmcp.vectorizer.primitives."""

import math
import pytest
from shapely.geometry import Polygon

from inkmcp.vectorizer.primitives import (
    detect_and_refit_rectangles,
    format_rect_path,
    skeletonize_thin_loops_mat,
)


def test_detect_and_refit_rectangles():
    """Snaps a slightly jittered 4-corner box into an exact rectangle."""
    # A 90x40 rectangle from (10, 20) to (100, 60) with minor sub-pixel raster jitter
    ring = [
        (10.1, 20.05),
        (99.95, 19.98),
        (100.02, 60.05),
        (9.98, 59.95),
        (10.1, 20.05),
    ]

    rect = detect_and_refit_rectangles(ring, tolerance=1.0)
    assert rect is not None
    minx, miny, w, h, radius = rect
    assert math.isclose(minx, 10.0, abs_tol=0.2)
    assert math.isclose(miny, 20.0, abs_tol=0.2)
    assert math.isclose(w, 90.0, abs_tol=0.3)
    assert math.isclose(h, 40.0, abs_tol=0.3)
    assert radius == 0.0

    path_d = format_rect_path(minx, miny, w, h, radius)
    assert "M" in path_d
    assert "Z" in path_d or "z" in path_d


def test_detect_rounded_rect_with_fillets():
    """Detects rounded rectangles with corner fillets."""
    # Generate points of a rounded rect at [0, 0, 80, 40] with r = 5.0
    # Approximated by polyline with arc corners
    r = 5.0
    pts = []
    # Top edge
    pts.append((5.0, 0.0))
    pts.append((75.0, 0.0))
    # Top right corner: (75, 0) -> (80, 5) around (75, 5)
    for a in [15, 30, 45, 60, 75]:
        rad = math.radians(a)
        pts.append((75.0 + r * math.sin(rad), 5.0 - r * math.cos(rad)))
    pts.append((80.0, 5.0))
    # Right edge
    pts.append((80.0, 35.0))
    # Bottom right corner: (80, 35) -> (75, 40) around (75, 35)
    for a in [15, 30, 45, 60, 75]:
        rad = math.radians(a)
        pts.append((75.0 + r * math.cos(rad), 35.0 + r * math.sin(rad)))
    pts.append((75.0, 40.0))
    # Bottom edge
    pts.append((5.0, 40.0))
    # Bottom left corner: (5, 40) -> (0, 35) around (5, 35)
    for a in [15, 30, 45, 60, 75]:
        rad = math.radians(a)
        pts.append((5.0 - r * math.sin(rad), 35.0 + r * math.cos(rad)))
    pts.append((0.0, 35.0))
    # Left edge
    pts.append((0.0, 5.0))
    # Top left corner: (0, 5) -> (5, 0) around (5, 5)
    for a in [15, 30, 45, 60, 75]:
        rad = math.radians(a)
        pts.append((5.0 - r * math.cos(rad), 5.0 - r * math.sin(rad)))
    pts.append((5.0, 0.0))

    rect = detect_and_refit_rectangles(pts, tolerance=1.5)
    assert rect is not None
    minx, miny, w, h, radius = rect
    assert math.isclose(minx, 0.0, abs_tol=1.0)
    assert math.isclose(miny, 0.0, abs_tol=1.0)
    assert math.isclose(w, 80.0, abs_tol=1.5)
    assert math.isclose(h, 40.0, abs_tol=1.5)
    assert 3.5 <= radius <= 6.5


def test_skeletonize_thin_loops_mat():
    """Converts a thin closed loop (L/W > 8) into a single 1-stroke centerline polyline."""
    # Thin horizontal wire / rigging line: length 80, width 2.0
    ring = [
        (10.0, 50.0),
        (90.0, 50.0),
        (90.0, 52.0),
        (10.0, 52.0),
        (10.0, 50.0),
    ]

    centerline = skeletonize_thin_loops_mat(ring, max_stroke_width=3.0, min_aspect=8.0)
    assert centerline is not None
    assert len(centerline) >= 2
    # Check that y is approximately in the middle (51.0)
    for pt in centerline:
        assert math.isclose(pt[1], 51.0, abs_tol=0.5)
    # Check x spans from ~10 to ~90
    assert math.isclose(min(p[0] for p in centerline), 10.0, abs_tol=2.0)
    assert math.isclose(max(p[0] for p in centerline), 90.0, abs_tol=2.0)

    # Thick shape (aspect ratio 1.0) must NOT be skeletonized
    thick_square = [
        (10.0, 10.0),
        (50.0, 10.0),
        (50.0, 50.0),
        (10.0, 50.0),
        (10.0, 10.0),
    ]
    assert skeletonize_thin_loops_mat(thick_square, max_stroke_width=3.0, min_aspect=8.0) is None
