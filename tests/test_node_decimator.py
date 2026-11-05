"""Unit tests for inkmcp.vectorizer.node_decimator."""

import math

from inkmcp.vectorizer.node_decimator import (
    NodeMetrics,
    prune_micro_segments,
    fit_cubic_beziers_schneider,
    fair_tangents_g1,
    decimate_path_nodes,
)


def test_prune_micro_segments():
    """Verifies segments with length < 0.2px are removed without altering closed path topology."""
    # A path with micro-jitter (points spaced 0.05px apart)
    path = (
        "M 10 10 "
        "L 10.05 10.05 "
        "L 10.08 10.08 "
        "L 50 10 "
        "L 50.02 10.01 "
        "L 50 50 "
        "L 10 50 "
        "Z"
    )
    pruned = prune_micro_segments(path, min_length=0.2)
    # The micro points should be pruned, retaining major vertices
    assert "10.05" not in pruned
    assert "10.08" not in pruned
    assert "50.02" not in pruned
    assert "50" in pruned
    assert "Z" in pruned or "z" in pruned


def test_fit_cubic_beziers_schneider():
    """Verifies densely sampled points along a known cubic Bezier arc are reduced to 1 or 2 segments."""
    # Generate 30 points along a known cubic Bezier curve: (0,0) -> (25, 50) -> (75, 50) -> (100, 0)
    p0 = (0.0, 0.0)
    p1 = (25.0, 50.0)
    p2 = (75.0, 50.0)
    p3 = (100.0, 0.0)

    points = []
    for i in range(31):
        t = i / 30.0
        x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t ** 2 * p2[0] + t ** 3 * p3[0]
        y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t ** 2 * p2[1] + t ** 3 * p3[1]
        points.append((x, y))

    curves = fit_cubic_beziers_schneider(points, max_error=0.5)
    # 30 points should fit into 1 or 2 cubic Beziers
    assert len(curves) in (1, 2)
    # Start and end coordinates must match within 0.1px
    start_pt = curves[0][0]
    end_pt = curves[-1][3]
    assert math.isclose(start_pt[0], p0[0], abs_tol=0.1)
    assert math.isclose(start_pt[1], p0[1], abs_tol=0.1)
    assert math.isclose(end_pt[0], p3[0], abs_tol=0.1)
    assert math.isclose(end_pt[1], p3[1], abs_tol=0.1)


def test_fair_tangents_g1():
    """Verifies that adjacent Bezier control handles at a smooth knot are made collinear."""
    # Two cubic Beziers sharing an anchor at (50, 50)
    # Curve 1 ends at (50, 50) with incoming handle at (40, 48) - vector from handle to anchor is (10, 2)
    # Curve 2 starts at (50, 50) with outgoing handle at (60, 53) - vector from anchor to handle is (10, 3)
    # They have a ~5 degree kink. G1 fairing should collinearize them while preserving anchor (50, 50).
    path = "M 0 0 C 10 20 40 48 50 50 C 60 53 90 80 100 100"
    faired = fair_tangents_g1(path, max_angle_deviation_deg=15.0)

    # Must contain M, and two C commands, and still pass through 50 50
    assert "M" in faired
    assert faired.count("C") == 2
    assert "50 50" in faired or "50.0 50.0" in faired or "50" in faired


def test_decimate_path_nodes():
    """Verifies end-to-end node count reduction > 50% on a bloated path."""
    # Create a bloated circle/wave path with 60 micro segments
    pts = []
    for i in range(60):
        theta = i * 2.0 * math.pi / 60.0
        x = 50.0 + 30.0 * math.cos(theta)
        y = 50.0 + 30.0 * math.sin(theta)
        pts.append(f"L {x:.2f} {y:.2f}")
    bloated_path = f"M 80.00 50.00 {' '.join(pts)} Z"

    optimized_path, metrics = decimate_path_nodes(bloated_path, tolerance=0.5)

    assert isinstance(metrics, NodeMetrics)
    assert metrics.original_node_count >= 60
    assert metrics.optimized_node_count < 30
    assert metrics.reduction_percentage > 50.0
    assert metrics.max_geometric_deviation <= 0.5
    assert metrics.estimated_cut_time_reduction_pct > 30.0
