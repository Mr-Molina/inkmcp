"""Extended geometric primitive snapping and Medial Axis Transform centerline skeleton engine."""

import math
from typing import List, Optional, Tuple

import numpy as np
from shapely.affinity import rotate
from shapely.geometry import box, LineString, Polygon
from shapely.validation import make_valid

from inkmcp.vectorizer.core import _format_coord


def detect_and_refit_rectangles(
    ring: List[Tuple[float, float]], tolerance: float = 1.0
) -> Optional[Tuple[float, float, float, float, float]]:
    """Detects if a coordinate ring matches a sharp or rounded rectangle within tolerance.

    Returns:
        (minx, miny, width, height, corner_radius) if detected, or None.
    """
    if len(ring) < 4:
        return None

    poly = Polygon(ring)
    if not poly.is_valid:
        poly = make_valid(poly)
        if poly.geom_type != "Polygon":
            return None

    minx, miny, maxx, maxy = poly.bounds
    w = maxx - minx
    h = maxy - miny
    if w <= 0.1 or h <= 0.1:
        return None

    # Check corner distance to box vertices
    box_corners = [
        (minx, miny),
        (maxx, miny),
        (maxx, maxy),
        (minx, maxy),
    ]
    corner_dists = [
        min(math.hypot(pt[0] - cx, pt[1] - cy) for pt in ring)
        for cx, cy in box_corners
    ]
    min_corner_dist = min(corner_dists)
    max_corner_dist = max(corner_dists)

    box_poly = box(minx, miny, maxx, maxy)
    box_area = box_poly.area
    poly_area = poly.area

    # Check for rounded rectangle with corner fillets
    area_deficit = box_area - poly_area
    if area_deficit > 0:
        factor = 4.0 - math.pi
        r_candidate = math.sqrt(area_deficit / factor)
        max_r = min(w, h) / 2.0
        # If corner distance indicates rounded corners (dist > 0.8px)
        if 1.0 <= r_candidate <= max_r and min_corner_dist > 0.8:
            try:
                rounded_model = box_poly.buffer(-r_candidate).buffer(r_candidate)
                if rounded_model.is_valid:
                    model_diff = poly.symmetric_difference(rounded_model).area
                    if model_diff / box_area < 0.05:
                        return (minx, miny, w, h, round(r_candidate, 2))
            except Exception:
                pass

    # Check for sharp rectangle (corners reach near box vertices)
    sym_diff = poly.symmetric_difference(box_poly).area
    if sym_diff / box_area < 0.06 and max_corner_dist <= tolerance + 0.5:
        return (minx, miny, w, h, 0.0)

    return None


def format_rect_path(
    minx: float,
    miny: float,
    width: float,
    height: float,
    corner_radius: float = 0.0,
) -> str:
    """Formats an exact SVG path string for a sharp or rounded rectangle."""
    if width <= 0.0 or height <= 0.0:
        return ""
    r = max(0.0, min(corner_radius, width / 2.0, height / 2.0))
    maxx = minx + width
    maxy = miny + height

    if r <= 0.1:
        # Sharp 4-corner rectangle
        return (
            f"M {_format_coord(minx)} {_format_coord(miny)} "
            f"L {_format_coord(maxx)} {_format_coord(miny)} "
            f"L {_format_coord(maxx)} {_format_coord(maxy)} "
            f"L {_format_coord(minx)} {_format_coord(maxy)} Z"
        )

    # Clamp radius to half of smallest dimension
    r = max(0.0, min(r, width / 2.0, height / 2.0))
    r_str = _format_coord(r)

    # Clockwise rounded rectangle with 4 circular arcs
    p1 = (minx + r, miny)
    p2 = (maxx - r, miny)
    p3 = (maxx, miny + r)
    p4 = (maxx, maxy - r)
    p5 = (maxx - r, maxy)
    p6 = (minx + r, maxy)
    p7 = (minx, maxy - r)
    p8 = (minx, miny + r)

    return (
        f"M {_format_coord(p1[0])} {_format_coord(p1[1])} "
        f"L {_format_coord(p2[0])} {_format_coord(p2[1])} "
        f"A {r_str} {r_str} 0 0 1 {_format_coord(p3[0])} {_format_coord(p3[1])} "
        f"L {_format_coord(p4[0])} {_format_coord(p4[1])} "
        f"A {r_str} {r_str} 0 0 1 {_format_coord(p5[0])} {_format_coord(p5[1])} "
        f"L {_format_coord(p6[0])} {_format_coord(p6[1])} "
        f"A {r_str} {r_str} 0 0 1 {_format_coord(p7[0])} {_format_coord(p7[1])} "
        f"L {_format_coord(p8[0])} {_format_coord(p8[1])} "
        f"A {r_str} {r_str} 0 0 1 {_format_coord(p1[0])} {_format_coord(p1[1])} Z"
    )


def skeletonize_thin_loops_mat(
    ring: List[Tuple[float, float]],
    max_stroke_width: float = 3.0,
    min_aspect: float = 8.0,
) -> Optional[List[Tuple[float, float]]]:
    """Computes Medial Axis Transform skeleton of thin closed loops.

    Converts thin closed double-wall loops (e.g. rigging, whiskers, antennas) into
    single-stroke polylines suitable for CAM centerline cutting/pen plotting.

    Args:
        ring: Sequence of (x, y) closed boundary coordinates.
        max_stroke_width: Maximum ribbon thickness in user units.
        min_aspect: Minimum length-to-width ratio required (must be >= 8.0).

    Returns:
        Ordered list of (x, y) centerline points, or None if shape is too thick.
    """
    if len(ring) < 4:
        return None

    poly = Polygon(ring)
    if not poly.is_valid:
        poly = make_valid(poly)
        if poly.geom_type != "Polygon":
            return None

    area = poly.area
    perimeter = poly.length
    if perimeter <= 0.0 or area <= 0.0:
        return None

    # Thin ribbon geometry: Area ~ L * W, Perimeter ~ 2L + 2W ~ 2L
    # W ~ 2 * Area / Perimeter
    est_w = 2.0 * area / perimeter
    est_l = perimeter / 2.0
    aspect_ratio = est_l / est_w if est_w > 0 else 0.0

    if est_w > max_stroke_width or aspect_ratio < min_aspect:
        return None

    # Compute oriented bounding box to determine principal orientation
    min_rect = poly.minimum_rotated_rectangle
    if min_rect.geom_type != "Polygon":
        return None

    coords = list(min_rect.exterior.coords)[:-1]
    if len(coords) < 4:
        return None

    # Identify longest edge vector
    edges = [
        ((coords[i][0], coords[i][1]), (coords[(i + 1) % 4][0], coords[(i + 1) % 4][1]))
        for i in range(4)
    ]
    edges.sort(
        key=lambda e: math.hypot(e[1][0] - e[0][0], e[1][1] - e[0][1]), reverse=True
    )
    long_edge = edges[0]
    dx = long_edge[1][0] - long_edge[0][0]
    dy = long_edge[1][1] - long_edge[0][1]
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad)

    centroid = poly.centroid
    cx, cy = centroid.x, centroid.y

    # Rotate polygon so long axis is horizontal
    rotated_poly = rotate(poly, -angle_deg, origin=(cx, cy))
    minx, miny, maxx, maxy = rotated_poly.bounds
    width_rot = maxx - minx
    if width_rot <= 0:
        return None

    # Sample cross sections along X axis
    num_samples = max(10, min(80, int(width_rot / max(0.5, est_w))))
    xs = np.linspace(minx + est_w * 0.25, maxx - est_w * 0.25, num_samples)

    centerline_rot = []
    y_span = max(1.0, (maxy - miny) * 2.0)
    for x in xs:
        scan_line = LineString([(x, miny - y_span), (x, maxy + y_span)])
        inter = rotated_poly.intersection(scan_line)
        if not inter.is_empty:
            if inter.geom_type == "LineString":
                mid_y = (inter.coords[0][1] + inter.coords[-1][1]) / 2.0
                centerline_rot.append((x, mid_y))
            elif inter.geom_type == "MultiLineString":
                # Take largest segment
                longest = max(inter.geoms, key=lambda g: g.length)
                mid_y = (longest.coords[0][1] + longest.coords[-1][1]) / 2.0
                centerline_rot.append((x, mid_y))
            elif inter.geom_type == "GeometryCollection":
                lines = [g for g in inter.geoms if g.geom_type == "LineString"]
                if lines:
                    longest = max(lines, key=lambda g: g.length)
                    mid_y = (longest.coords[0][1] + longest.coords[-1][1]) / 2.0
                    centerline_rot.append((x, mid_y))

    if len(centerline_rot) < 2:
        return None

    # Rotate centerline points back to original orientation
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    world_centerline = []
    for xr, yr in centerline_rot:
        # Shift to origin
        dx_r = xr - cx
        dy_r = yr - cy
        # Rotate back by +angle
        orig_x = dx_r * cos_a - dy_r * sin_a + cx
        orig_y = dx_r * sin_a + dy_r * cos_a + cy
        world_centerline.append((orig_x, orig_y))

    return world_centerline
