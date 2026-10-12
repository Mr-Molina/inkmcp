"""Automated choke and spread trapping engine for multi-layer vinyl and screen printing."""

import logging
import re
from typing import List, Optional, Tuple

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

from inkmcp.vectorizer.core import PathRecord, parse_svg_path_to_rings, _format_coord
from inkmcp.vectorizer.topology import LayerGroup

logger = logging.getLogger(__name__)


def compute_color_luminance(hex_str: str) -> float:
    """Computes relative perceptual luminance for a hex color code.

    Formula: Y = 0.299*R + 0.587*G + 0.114*B, where R, G, B in [0, 1].
    """
    clean_hex = hex_str.strip().lstrip("#")
    if len(clean_hex) == 3:
        clean_hex = "".join([c * 2 for c in clean_hex])
    if len(clean_hex) != 6:
        return 0.5

    try:
        r = int(clean_hex[0:2], 16) / 255.0
        g = int(clean_hex[2:4], 16) / 255.0
        b = int(clean_hex[4:6], 16) / 255.0
        return 0.299 * r + 0.587 * g + 0.114 * b
    except ValueError:
        return 0.5


def _polygon_to_path_d(geom) -> str:
    """Converts a Shapely Polygon or MultiPolygon into an SVG path d string."""
    if geom.is_empty:
        return ""

    if geom.geom_type == "Polygon":
        polys = [geom]
    elif geom.geom_type == "MultiPolygon":
        polys = list(geom.geoms)
    else:
        # If geometry collection or unexpected type
        polys = [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]
        if not polys:
            return ""

    d_parts = []
    for poly in polys:
        # Exterior
        ext_coords = list(poly.exterior.coords)
        if len(ext_coords) > 1:
            # Drop redundant closing coord if identical
            if ext_coords[0] == ext_coords[-1]:
                ext_coords = ext_coords[:-1]
            if ext_coords:
                first = ext_coords[0]
                part = f"M {_format_coord(first[0])} {_format_coord(first[1])}"
                for pt in ext_coords[1:]:
                    part += f" L {_format_coord(pt[0])} {_format_coord(pt[1])}"
                part += " Z"
                d_parts.append(part)

        # Interiors (holes)
        for interior in poly.interiors:
            hole_coords = list(interior.coords)
            if len(hole_coords) > 1:
                if hole_coords[0] == hole_coords[-1]:
                    hole_coords = hole_coords[:-1]
                if hole_coords:
                    first = hole_coords[0]
                    part = f"M {_format_coord(first[0])} {_format_coord(first[1])}"
                    for pt in hole_coords[1:]:
                        part += f" L {_format_coord(pt[0])} {_format_coord(pt[1])}"
                    part += " Z"
                    d_parts.append(part)

    return " ".join(d_parts)


def _path_to_polygon(path_data: str):
    """Converts SVG path data to a Shapely Polygon or MultiPolygon."""
    rings = parse_svg_path_to_rings(path_data)
    if not rings:
        return None

    if len(rings) == 1:
        poly = Polygon(rings[0])
    else:
        # Assume largest is shell, others are holes or separate islands
        sorted_rings = sorted(rings, key=lambda r: Polygon(r).area if len(r) >= 3 else 0.0, reverse=True)
        poly = Polygon(sorted_rings[0], sorted_rings[1:])

    if not poly.is_valid:
        poly = make_valid(poly)
    return poly


def apply_choke_spread_trapping(
    layers: List[LayerGroup], trap_distance: float = 1.13
) -> List[LayerGroup]:
    """Applies sub-millimeter choke and spread trapping for multi-layer fabrication.

    Buffers lighter color polygons underneath adjacent darker keylines by trap_distance
    while strictly conserving the external silhouette of the total design.

    Args:
        layers: List of LayerGroup instances with PathRecord items.
        trap_distance: Distance in SVG user units (default: 1.13px ~= 0.3mm at 96 DPI).

    Returns:
        New List of LayerGroup instances with trapped path data.
    """
    if not layers or trap_distance <= 0:
        return layers

    # 1. Parse all paths into Shapely geometries
    path_entries = []
    all_geoms = []

    for l_idx, layer in enumerate(layers):
        for p_idx, path in enumerate(layer.paths):
            geom = _path_to_polygon(path.path_data)
            if geom is not None and not geom.is_empty:
                lum = compute_color_luminance(path.color_hex or layer.color_hex or "#000000")
                path_entries.append({
                    "layer_idx": l_idx,
                    "path_idx": p_idx,
                    "record": path,
                    "geom": geom,
                    "luminance": lum,
                })
                all_geoms.append(geom)

    if not path_entries:
        return layers

    # 2. Compute the exact total outer design silhouette
    total_silhouette = unary_union(all_geoms)

    # 3. Perform pairwise trapping: lighter expands into adjacent darker
    n = len(path_entries)
    for i in range(n):
        entry_a = path_entries[i]
        geom_a = entry_a["geom"]
        lum_a = entry_a["luminance"]

        for j in range(n):
            if i == j:
                continue
            entry_b = path_entries[j]
            geom_b = entry_b["geom"]
            lum_b = entry_b["luminance"]

            # Only expand if A is noticeably lighter than B, or if equal luminance, tie-break
            is_lighter = (lum_a - lum_b > 0.05) or (
                abs(lum_a - lum_b) <= 0.05 and i < j
            )
            if not is_lighter:
                continue

            # Check if A and B are touching/adjacent
            # Buffer slightly to detect touching boundary
            touch_zone = geom_a.buffer(0.2).intersection(geom_b)
            if not touch_zone.is_empty and touch_zone.area > 0.01:
                # Expand A into B by trap_distance
                expanded = geom_a.buffer(trap_distance, join_style="mitre")
                overlap_with_b = expanded.intersection(geom_b)
                if not overlap_with_b.is_empty:
                    new_geom_a = geom_a.union(overlap_with_b)
                    # Boundary conservation: never expand past total silhouette
                    new_geom_a = new_geom_a.intersection(total_silhouette)
                    if not new_geom_a.is_valid:
                        new_geom_a = make_valid(new_geom_a)
                    geom_a = new_geom_a
                    entry_a["geom"] = geom_a

    # 4. Reconstruct LayerGroups
    new_layers = []
    # Index path_entries by (layer_idx, path_idx)
    lookup = {(e["layer_idx"], e["path_idx"]): e["geom"] for e in path_entries}

    for l_idx, layer in enumerate(layers):
        new_paths = []
        for p_idx, path in enumerate(layer.paths):
            key = (l_idx, p_idx)
            if key in lookup:
                updated_geom = lookup[key]
                new_d = _polygon_to_path_d(updated_geom)
                if not new_d:
                    new_d = path.path_data
                new_paths.append(
                    PathRecord(
                        id=path.id,
                        color_hex=path.color_hex,
                        path_data=new_d,
                        area=updated_geom.area if hasattr(updated_geom, "area") else path.area,
                        fill_rule=path.fill_rule,
                    )
                )
            else:
                new_paths.append(path)

        new_layers.append(
            LayerGroup(
                layer_id=layer.layer_id,
                label=layer.label,
                color_hex=layer.color_hex,
                paths=new_paths,
                z_index=layer.z_index,
            )
        )

    return new_layers
