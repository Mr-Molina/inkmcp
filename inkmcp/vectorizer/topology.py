"""Topology engine for planar cut-ready and layered laser mandala vector conversion."""

from dataclasses import dataclass
from typing import Dict, List, Tuple
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from inkmcp.vectorizer.core import (
    PathRecord,
    normalize_color_hex,
    parse_svg_path_to_rings,
)
from inkmcp.vectorizer.palette import standardize_color_palette


@dataclass
class LayerGroup:
    """Group of vector paths belonging to a single fabrication layer."""

    layer_id: str
    label: str
    color_hex: str
    paths: List[PathRecord]
    z_index: int


@dataclass
class StructuredLayerData:
    """Topologically structured layer data for fabrication and SVG generation."""

    mode: str
    layers: List[LayerGroup]
    dimensions: Tuple[int, int] = (100, 100)


def _format_coord(v: float) -> str:
    """Formats float coordinate with up to 4 decimals, trimming unnecessary zeros."""
    s = f"{v:.4f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _linear_ring_to_svg(coords) -> str:
    """Converts a coordinate sequence into an SVG path ring string."""
    pts = list(coords)
    if not pts:
        return ""
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return ""
    start = f"M {_format_coord(pts[0][0])} {_format_coord(pts[0][1])}"
    segments = [f"L {_format_coord(x)} {_format_coord(y)}" for x, y in pts[1:]]
    return f"{start} {' '.join(segments)} Z" if segments else f"{start} Z"


def _extract_polygonal_geometry(geom: BaseGeometry) -> BaseGeometry:
    """Extracts strictly 2D Polygon and MultiPolygon geometry, discarding lines and points."""
    if geom is None or geom.is_empty:
        return Polygon()
    if geom.geom_type == "Polygon":
        return geom if geom.area > 0 else Polygon()
    if geom.geom_type == "MultiPolygon":
        valid_parts = [p for p in geom.geoms if not p.is_empty and p.area > 0]
        if not valid_parts:
            return Polygon()
        return unary_union(valid_parts)
    if geom.geom_type == "GeometryCollection":
        polys = []
        for g in geom.geoms:
            if g.geom_type in ("Polygon", "MultiPolygon"):
                sub = _extract_polygonal_geometry(g)
                if not sub.is_empty and sub.area > 0:
                    polys.append(sub)
        if not polys:
            return Polygon()
        return unary_union(polys)
    return Polygon()


class TopologyEngine:
    """Transforms raw vector contours into cut-ready planar mosaic or layered mandala geometries."""

    def _path_to_geometry(self, d: str) -> BaseGeometry:
        """Converts an SVG path string into a valid Shapely geometry."""
        if not d or not d.strip():
            return Polygon()
        rings = parse_svg_path_to_rings(d)
        valid_rings = [r for r in rings if len(r) >= 3]
        if not valid_rings:
            return Polygon()
        if len(valid_rings) == 1:
            p = Polygon(valid_rings[0])
            if not p.is_valid:
                p = make_valid(p)
            return _extract_polygonal_geometry(p)

        ring_polys = []
        for r in valid_rings:
            p = Polygon(r)
            if not p.is_valid:
                p = make_valid(p)
            ring_polys.append((p, r))
        ring_polys.sort(key=lambda x: x[0].area, reverse=True)

        largest_p, largest_r = ring_polys[0]
        all_inside = True
        for p, _ in ring_polys[1:]:
            if not largest_p.contains(p.representative_point()):
                all_inside = False
                break

        if all_inside:
            try:
                poly = Polygon(largest_r, [r for _, r in ring_polys[1:]])
                if not poly.is_valid:
                    poly = make_valid(poly)
                return _extract_polygonal_geometry(poly)
            except Exception:
                pass

        # Fallback for complex nested or disjoint rings
        res = Polygon()
        for p, _ in ring_polys:
            res = res.symmetric_difference(p)
        return _extract_polygonal_geometry(make_valid(res))

    def paths_to_polygon(self, paths: List[PathRecord]) -> BaseGeometry:
        """Converts a list of PathRecord objects into a valid Shapely Polygon or MultiPolygon."""
        if not paths:
            return Polygon()
        geoms = []
        for p in paths:
            g = self._path_to_geometry(p.path_data)
            if not g.is_empty and g.area > 0:
                geoms.append(g)
        if not geoms:
            return Polygon()
        if len(geoms) == 1:
            return _extract_polygonal_geometry(make_valid(geoms[0]))
        union_geom = unary_union(geoms)
        return _extract_polygonal_geometry(make_valid(union_geom))

    def polygon_to_path_data(self, geometry: BaseGeometry) -> str:
        """Converts Shapely polygons (exteriors and interior holes) into SVG path d strings."""
        if geometry is None or geometry.is_empty:
            return ""

        if geometry.geom_type == "Polygon":
            polys = [geometry]
        elif geometry.geom_type == "MultiPolygon":
            polys = list(geometry.geoms)
        elif geometry.geom_type == "GeometryCollection":
            extracted = _extract_polygonal_geometry(geometry)
            if extracted.is_empty:
                return ""
            polys = [extracted] if extracted.geom_type == "Polygon" else list(extracted.geoms)
        else:
            return ""

        subpaths = []
        for poly in polys:
            if poly.is_empty or poly.area <= 0:
                continue
            ext = _linear_ring_to_svg(poly.exterior.coords)
            if ext:
                subpaths.append(ext)
            for interior in poly.interiors:
                hole = _linear_ring_to_svg(interior.coords)
                if hole:
                    subpaths.append(hole)

        return " ".join(subpaths)

    def _decompose_into_path_records(
        self, geometry: BaseGeometry, color_hex: str, z_index: int, filter_speckle: float
    ) -> List[PathRecord]:
        """Decomposes geometry into non-overlapping PathRecord instances with deterministic IDs."""
        if geometry is None or geometry.is_empty or geometry.area < filter_speckle:
            return []

        if geometry.geom_type == "Polygon":
            polys = [geometry]
        elif geometry.geom_type == "MultiPolygon":
            polys = list(geometry.geoms)
        else:
            extracted = _extract_polygonal_geometry(geometry)
            if extracted.is_empty:
                return []
            polys = [extracted] if extracted.geom_type == "Polygon" else list(extracted.geoms)

        valid_polys = [p for p in polys if not p.is_empty and p.area >= filter_speckle]
        if not valid_polys:
            return []

        # Sort polygons by area descending for deterministic ordering
        valid_polys.sort(key=lambda p: p.area, reverse=True)

        records = []
        for path_idx, poly in enumerate(valid_polys, start=1):
            path_id = f"layer{z_index:02d}_path{path_idx:02d}"
            d = self.polygon_to_path_data(poly)
            records.append(
                PathRecord(
                    id=path_id,
                    color_hex=color_hex,
                    path_data=d,
                    area=float(poly.area),
                    fill_rule="nonzero",
                )
            )
        return records

    def process(
        self,
        paths: List[PathRecord],
        mode: str = "cut_ready",
        dimensions: Tuple[int, int] = (100, 100),
        filter_speckle: float = 4.0,
        color_tolerance: float = 5.0,
    ) -> StructuredLayerData:
        """Processes raw vector paths into topologically organized layers.

        Args:
            paths: Input list of PathRecord objects extracted by VTracerCore.
            mode: 'cut_ready' for planar mosaic vinyl cuts, or 'layered' for laser mandala stack.
            dimensions: Document width and height tuple.
            filter_speckle: Minimum polygon area threshold to drop slivers.
            color_tolerance: CIELAB Delta E threshold to merge near-identical colors (default 5.0).
                If <= 0.0, color merging is disabled.

        Returns:
            StructuredLayerData containing ordered LayerGroup instances.
        """
        if mode not in ("cut_ready", "layered"):
            raise ValueError(f"Unsupported mode: '{mode}'. Must be 'cut_ready' or 'layered'")

        if not paths:
            return StructuredLayerData(mode=mode, layers=[], dimensions=dimensions)

        # 1. Group paths by normalized color_hex and merge perceptually similar colors
        color_areas: Dict[str, float] = {}
        for p in paths:
            hex_code = normalize_color_hex(p.color_hex)
            color_areas[hex_code] = color_areas.get(hex_code, 0.0) + max(0.0, getattr(p, "area", 0.0))

        color_map: Dict[str, str] = {}
        if color_tolerance > 0.0:
            color_map = standardize_color_palette(color_areas, delta_e_threshold=color_tolerance)

        color_groups_map: Dict[str, List[PathRecord]] = {}
        for p in paths:
            hex_code = normalize_color_hex(p.color_hex)
            canonical_color = color_map.get(hex_code, hex_code)
            p.color_hex = canonical_color
            if canonical_color not in color_groups_map:
                color_groups_map[canonical_color] = []
            color_groups_map[canonical_color].append(p)

        # 2. Convert each group into unified Shapely geometry and calculate total area
        group_items = []
        for hex_code, group_paths in color_groups_map.items():
            geom = self.paths_to_polygon(group_paths)
            if not geom.is_empty and geom.area >= filter_speckle:
                group_items.append({"color_hex": hex_code, "geom": geom, "area": geom.area})

        if not group_items:
            return StructuredLayerData(mode=mode, layers=[], dimensions=dimensions)

        # Sort color groups by area descending (largest background first, smallest foreground last)
        group_items.sort(key=lambda item: item["area"], reverse=True)

        layers: List[LayerGroup] = []

        if mode == "cut_ready":
            # Planar boolean difference: higher layers (smaller foreground) punch out of lower layers (background)
            n = len(group_items)
            processed_geoms: List[BaseGeometry] = [Polygon()] * n

            for i in range(n):
                current_geom = group_items[i]["geom"]
                higher_geoms = [group_items[j]["geom"] for j in range(i + 1, n)]
                if higher_geoms:
                    mask = unary_union(higher_geoms)
                    subtracted = current_geom.difference(mask)
                    subtracted = _extract_polygonal_geometry(make_valid(subtracted))
                    processed_geoms[i] = subtracted
                else:
                    processed_geoms[i] = current_geom

            z_idx = 0
            for i, item in enumerate(group_items):
                geom = processed_geoms[i]
                path_records = self._decompose_into_path_records(
                    geom, item["color_hex"], z_idx, filter_speckle
                )
                if path_records:
                    layer_id = f"layer_{z_idx:02d}"
                    label = f"{z_idx:02d} - {item['color_hex']}"
                    layers.append(
                        LayerGroup(
                            layer_id=layer_id,
                            label=label,
                            color_hex=item["color_hex"],
                            paths=path_records,
                            z_index=z_idx,
                        )
                    )
                    z_idx += 1

        elif mode == "layered":
            # Layer 0: Solid baseplate silhouette backing formed by unioning all input paths
            all_valid_geoms = [item["geom"] for item in group_items]
            unioned_base = make_valid(unary_union(all_valid_geoms))
            unioned_base = _extract_polygonal_geometry(unioned_base)

            # Solid silhouette backing: fill all interior holes so nothing falls through laser bed
            base_polys = (
                [unioned_base]
                if unioned_base.geom_type == "Polygon"
                else list(unioned_base.geoms)
            )
            solid_base_polys = [
                make_valid(Polygon(p.exterior))
                for p in base_polys
                if not p.is_empty and p.area >= filter_speckle
            ]
            solid_base_geom = _extract_polygonal_geometry(unary_union(solid_base_polys))

            base_color = "#000000"
            base_records = self._decompose_into_path_records(
                solid_base_geom, base_color, 0, filter_speckle
            )
            if base_records:
                layers.append(
                    LayerGroup(
                        layer_id="layer_00_base",
                        label="00 - Base Silhouette",
                        color_hex=base_color,
                        paths=base_records,
                        z_index=0,
                    )
                )

            # Subsequent layers (1..N): Ordered from largest background to finest top accents
            curr_z = 1
            for item in group_items:
                path_records = self._decompose_into_path_records(
                    item["geom"], item["color_hex"], curr_z, filter_speckle
                )
                if path_records:
                    layer_id = f"layer_{curr_z:02d}"
                    label = f"{curr_z:02d} - {item['color_hex']}"
                    layers.append(
                        LayerGroup(
                            layer_id=layer_id,
                            label=label,
                            color_hex=item["color_hex"],
                            paths=path_records,
                            z_index=curr_z,
                        )
                    )
                    curr_z += 1

        return StructuredLayerData(mode=mode, layers=layers, dimensions=dimensions)
