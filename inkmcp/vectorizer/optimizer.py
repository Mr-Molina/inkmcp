"""SVG DOM layer structuring and Scour optimization module."""

from dataclasses import dataclass
import logging
import math
import re
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape

from shapely.geometry import Polygon
from shapely.validation import make_valid

from inkmcp.vectorizer.core import (
    PathRecord,
    parse_svg_path_to_rings,
    _format_coord,
)
from inkmcp.vectorizer.topology import LayerGroup, StructuredLayerData

logger = logging.getLogger(__name__)


def is_circular_ring(
    ring: List[Tuple[float, float]],
    min_circularity: float = 0.82,
    max_area: float = 1500.0,
    min_area: float = 15.0,
    min_aspect: float = 0.75,
) -> Tuple[bool, float, float, float, float, bool]:
    """Detects if a coordinate ring is a circular/elliptical primitive.

    Returns:
        (is_circular, cx, cy, rx, ry, is_ccw)
    """
    if len(ring) < 5:
        return False, 0.0, 0.0, 0.0, 0.0, False

    poly = Polygon(ring)
    if not poly.is_valid:
        poly = make_valid(poly)
        if poly.geom_type != "Polygon":
            return False, 0.0, 0.0, 0.0, 0.0, False

    area = poly.area
    if area < min_area or area > max_area:
        return False, 0.0, 0.0, 0.0, 0.0, False

    perimeter = poly.length
    if perimeter == 0:
        return False, 0.0, 0.0, 0.0, 0.0, False

    circularity = 4.0 * math.pi * area / (perimeter * perimeter)
    if circularity < min_circularity:
        return False, 0.0, 0.0, 0.0, 0.0, False

    minx, miny, maxx, maxy = poly.bounds
    w = maxx - minx
    h = maxy - miny
    if w == 0 or h == 0:
        return False, 0.0, 0.0, 0.0, 0.0, False

    aspect = min(w, h) / max(w, h)
    if aspect < min_aspect:
        return False, 0.0, 0.0, 0.0, 0.0, False

    cx = float(poly.centroid.x)
    cy = float(poly.centroid.y)
    rx = w / 2.0
    ry = h / 2.0

    if aspect >= 0.90:
        r_mean = math.sqrt(area / math.pi)
        rx = r_mean
        ry = r_mean

    is_ccw = bool(poly.exterior.is_ccw)
    return True, cx, cy, rx, ry, is_ccw


def generate_bezier_ellipse(
    cx: float, cy: float, rx: float, ry: float, is_ccw: bool = False
) -> str:
    """Generates standard 4-arc cubic Bezier ellipse/circle."""
    kx = 0.5522847498 * rx
    ky = 0.5522847498 * ry
    x0, y0 = cx, cy - ry

    if is_ccw:
        # Shapely is_ccw=True (counter-clockwise)
        return (
            f"M {_format_coord(x0)} {_format_coord(y0)} "
            f"C {_format_coord(cx + kx)} {_format_coord(y0)} {_format_coord(cx + rx)} {_format_coord(cy - ky)} {_format_coord(cx + rx)} {_format_coord(cy)} "
            f"C {_format_coord(cx + rx)} {_format_coord(cy + ky)} {_format_coord(cx + kx)} {_format_coord(cy + ry)} {_format_coord(cx)} {_format_coord(cy + ry)} "
            f"C {_format_coord(cx - kx)} {_format_coord(cy + ry)} {_format_coord(cx - rx)} {_format_coord(cy + ky)} {_format_coord(cx - rx)} {_format_coord(cy)} "
            f"C {_format_coord(cx - rx)} {_format_coord(cy - ky)} {_format_coord(cx - kx)} {_format_coord(y0)} {_format_coord(x0)} {_format_coord(y0)} Z"
        )
    else:
        # Shapely is_ccw=False (clockwise)
        return (
            f"M {_format_coord(x0)} {_format_coord(y0)} "
            f"C {_format_coord(cx - kx)} {_format_coord(y0)} {_format_coord(cx - rx)} {_format_coord(cy - ky)} {_format_coord(cx - rx)} {_format_coord(cy)} "
            f"C {_format_coord(cx - rx)} {_format_coord(cy + ky)} {_format_coord(cx - kx)} {_format_coord(cy + ry)} {_format_coord(cx)} {_format_coord(cy + ry)} "
            f"C {_format_coord(cx + kx)} {_format_coord(cy + ry)} {_format_coord(cx + rx)} {_format_coord(cy + ky)} {_format_coord(cx + rx)} {_format_coord(cy)} "
            f"C {_format_coord(cx + rx)} {_format_coord(cy - ky)} {_format_coord(cx + kx)} {_format_coord(y0)} {_format_coord(x0)} {_format_coord(y0)} Z"
        )


def point_line_distance(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    """Calculates perpendicular Euclidean distance from point (px, py) to line segment (x1, y1)-(x2, y2)."""
    dx = x2 - x1
    dy = y2 - y1
    denom = math.hypot(dx, dy)
    if denom == 0:
        return math.hypot(px - x1, py - y1)
    return abs(dy * px - dx * py + x2 * y1 - y2 * x1) / denom


def simplify_polyline_rdp(
    points: List[Tuple[float, float]], max_deviation: float = 1.0
) -> List[Tuple[float, float]]:
    """Simplifies a sequence of (x, y) coordinates using Ramer-Douglas-Peucker algorithm."""
    if len(points) < 3:
        return points

    x1, y1 = points[0]
    x2, y2 = points[-1]
    max_d = 0.0
    index = 0

    for i in range(1, len(points) - 1):
        d = point_line_distance(points[i][0], points[i][1], x1, y1, x2, y2)
        if d > max_d:
            max_d = d
            index = i

    if max_d > max_deviation:
        left = simplify_polyline_rdp(points[: index + 1], max_deviation)
        right = simplify_polyline_rdp(points[index:], max_deviation)
        return left[:-1] + right
    else:
        return [points[0], points[-1]]


def regularize_svg_path_rdp(d_str: str, max_deviation: float = 1.0) -> str:
    """Simplifies consecutive straight polyline runs in an SVG path using Ramer-Douglas-Peucker.

    Collapses jagged raster staircases along shadows, straight edges, and window casings
    into clean straight line segments, while keeping curves (C commands) completely intact.
    """
    if not d_str or not d_str.strip():
        return d_str

    tokens = re.findall(
        r"([a-zA-Z])|([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)", d_str
    )
    commands = []
    curr_cmd = None
    curr_args: List[float] = []
    for letter, num in tokens:
        if letter:
            if curr_cmd is not None:
                commands.append((curr_cmd, curr_args))
            curr_cmd = letter
            curr_args = []
        elif num:
            curr_args.append(float(num))
    if curr_cmd is not None:
        commands.append((curr_cmd, curr_args))

    out_parts = []
    i = 0
    curr_pt = (0.0, 0.0)

    while i < len(commands):
        cmd, args = commands[i]
        if cmd == "M" and len(args) >= 2:
            curr_pt = (args[0], args[1])
            out_parts.append(f"M {_format_coord(curr_pt[0])} {_format_coord(curr_pt[1])}")
            poly = [curr_pt]
            j = i + 1
            while (
                j < len(commands)
                and commands[j][0] == "L"
                and len(commands[j][1]) >= 2
            ):
                poly.append((commands[j][1][0], commands[j][1][1]))
                j += 1
            if len(poly) > 2:
                simplified = simplify_polyline_rdp(poly, max_deviation=max_deviation)
                for p in simplified[1:]:
                    out_parts.append(f"L {_format_coord(p[0])} {_format_coord(p[1])}")
                curr_pt = simplified[-1]
                i = j
                continue
            else:
                i += 1
        elif cmd == "L" and len(args) >= 2:
            poly = [curr_pt]
            j = i
            while (
                j < len(commands)
                and commands[j][0] == "L"
                and len(commands[j][1]) >= 2
            ):
                poly.append((commands[j][1][0], commands[j][1][1]))
                j += 1
            if len(poly) > 2:
                simplified = simplify_polyline_rdp(poly, max_deviation=max_deviation)
                for p in simplified[1:]:
                    out_parts.append(f"L {_format_coord(p[0])} {_format_coord(p[1])}")
                curr_pt = simplified[-1]
                i = j
                continue
            else:
                curr_pt = (args[0], args[1])
                out_parts.append(f"L {_format_coord(curr_pt[0])} {_format_coord(curr_pt[1])}")
                i += 1
        elif cmd in ("C", "c") and len(args) >= 6:
            curr_pt = (
                (args[4], args[5])
                if cmd == "C"
                else (curr_pt[0] + args[4], curr_pt[1] + args[5])
            )
            formatted_args = " ".join(_format_coord(a) for a in args)
            out_parts.append(f"{cmd} {formatted_args}")
            i += 1
        elif cmd in ("Z", "z"):
            out_parts.append("Z")
            i += 1
        else:
            formatted_args = " ".join(_format_coord(a) for a in args)
            out_parts.append(f"{cmd} {formatted_args}".strip())
            i += 1

    return " ".join(out_parts)


def _convert_initial_m_to_absolute(sp: str, abs_start: Tuple[float, float]) -> str:
    """Converts a leading relative 'm' command in a subpath to an absolute 'M' command."""
    if not sp.startswith("m"):
        return sp
    tokens = re.findall(r"([a-zA-Z])|([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)", sp)
    raw = [letter if letter else num for letter, num in tokens]
    if len(raw) < 3 or raw[0] != "m":
        return sp
    rem_tokens = raw[3:]
    if rem_tokens and not rem_tokens[0].isalpha():
        rem_str = "l " + " ".join(rem_tokens)
    else:
        rem_str = " ".join(rem_tokens)
    new_sp = f"M {_format_coord(abs_start[0])} {_format_coord(abs_start[1])}"
    if rem_str:
        new_sp += f" {rem_str}"
    return new_sp


def refit_path_d(
    d_str: str,
    min_circularity: float = 0.92,
    max_area: float = 1500.0,
    min_area: float = 15.0,
    min_aspect: float = 0.88,
    regularize_lines: bool = True,
    max_deviation: float = 1.0,
) -> str:
    """Refits circular subpaths and optionally regularizes straight staircases."""
    if not d_str or not d_str.strip():
        return d_str

    subpath_tokens = re.split(r"(?=[mM])", d_str.strip())
    subpaths = [s.strip() for s in subpath_tokens if s.strip()]
    if not subpaths:
        return d_str

    all_rings = parse_svg_path_to_rings(d_str)
    have_all_rings = len(all_rings) == len(subpaths)

    any_change = False
    new_subpaths = []
    curr_origin = (0.0, 0.0)

    for idx, sp in enumerate(subpaths):
        sp_abs = sp
        if sp.startswith("m") and idx > 0:
            if have_all_rings and all_rings[idx]:
                abs_start = all_rings[idx][0]
                sp_abs = _convert_initial_m_to_absolute(sp, abs_start)
            else:
                tokens = re.findall(
                    r"([a-zA-Z])|([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)", sp
                )
                raw_nums = [float(num) for _, num in tokens if num]
                if len(raw_nums) >= 2:
                    abs_start = (curr_origin[0] + raw_nums[0], curr_origin[1] + raw_nums[1])
                    sp_abs = _convert_initial_m_to_absolute(sp, abs_start)

        rings = [all_rings[idx]] if (have_all_rings and all_rings[idx]) else parse_svg_path_to_rings(sp_abs)
        if len(rings) == 1:
            is_circ, cx, cy, rx, ry, is_ccw = is_circular_ring(
                rings[0],
                min_circularity=min_circularity,
                max_area=max_area,
                min_area=min_area,
                min_aspect=min_aspect,
            )
            if is_circ:
                any_change = True
                ellipse_d = generate_bezier_ellipse(cx, cy, rx, ry, is_ccw=is_ccw)
                new_subpaths.append(ellipse_d)
                curr_origin = (cx, cy - ry)
                continue

        if regularize_lines:
            reg_sp = regularize_svg_path_rdp(sp_abs, max_deviation=max_deviation)
            if reg_sp != sp_abs:
                any_change = True
                new_subpaths.append(reg_sp)
                if rings and rings[0]:
                    curr_origin = rings[0][0] if sp.lower().endswith("z") else rings[0][-1]
                continue

        new_subpaths.append(sp_abs)
        if rings and rings[0]:
            curr_origin = rings[0][0] if sp.lower().endswith("z") else rings[0][-1]

    return " ".join(new_subpaths) if any_change else d_str



@dataclass
class OptimizedSvgResult:
    """Optimized SVG output with DOM layer hierarchy and fabrication metrics."""

    svg_content: str
    layer_count: int
    total_nodes: int
    file_size: int


def _escape_attr(val: str) -> str:
    """Escapes special characters in XML attribute values."""
    return escape(str(val), {'"': "&quot;"})


class SvgOptimizer:
    """Builds Inkscape-compatible layer DOMs and performs Scour cleanup."""

    @staticmethod
    def count_nodes(layer_data: StructuredLayerData) -> int:
        """Counts total SVG path command tokens across all paths in layer_data.

        Matches standard SVG path command letters: M, m, L, l, H, h, V, v,
        C, c, S, s, Q, q, T, t, A, a, Z, z.
        """
        if not layer_data or not layer_data.layers:
            return 0
        total = 0
        cmd_regex = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")
        for layer in layer_data.layers:
            for path in layer.paths:
                if path and path.path_data:
                    total += len(cmd_regex.findall(path.path_data))
        return total

    def build_svg(
        self,
        layer_data: StructuredLayerData,
        dimensions: Optional[Tuple[int, int]] = None,
    ) -> str:
        """Serializes StructuredLayerData into clean SVG XML with Inkscape layer DOM.

        Args:
            layer_data: Topologically ordered layer groups and path contours.
            dimensions: Optional (width, height) canvas dimensions; defaults to layer_data.dimensions.

        Returns:
            SVG XML markup string.
        """
        if dimensions is not None:
            width, height = dimensions
        elif layer_data and layer_data.dimensions:
            width, height = layer_data.dimensions
        else:
            width, height = (100, 100)

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
                f'viewBox="0 0 {width} {height}" '
                f'width="{width}" height="{height}">'
            ),
        ]

        if layer_data and layer_data.layers:
            for layer in layer_data.layers:
                layer_id = _escape_attr(layer.layer_id)
                layer_label = _escape_attr(layer.label)
                lines.append(
                    f'  <g id="{layer_id}" inkscape:groupmode="layer" inkscape:label="{layer_label}">'
                )
                for path in layer.paths:
                    path_id = _escape_attr(path.id)
                    fill_color = _escape_attr(path.color_hex)
                    fill_rule_val = (
                        "evenodd"
                        if (layer_data and getattr(layer_data, "mode", None) == "silhouette")
                        else path.fill_rule
                    )
                    fill_rule = (
                        f' fill-rule="{_escape_attr(fill_rule_val)}"'
                        if fill_rule_val
                        else ""
                    )
                    path_data = _escape_attr(path.path_data)
                    lines.append(
                        f'    <path id="{path_id}" fill="{fill_color}"{fill_rule} d="{path_data}" />'
                    )
                lines.append("  </g>")

        lines.append("</svg>\n")
        return "\n".join(lines)

    def optimize(
        self,
        svg_content: str,
        precision: int = 7,
        enable_scour: bool = True,
    ) -> str:
        """Optimizes SVG content using Scour while preserving Inkscape layer metadata.

        Args:
            svg_content: Input SVG markup string.
            precision: Decimal precision for coordinates (default: 7 for high fabrication fidelity).
            enable_scour: Whether to apply Scour optimization passes.

        Returns:
            Cleaned and optimized SVG markup string, or original content on fallback.
        """
        if not enable_scour or not svg_content or not svg_content.strip():
            return svg_content

        try:
            # Strip <!DOCTYPE ...> and <!ENTITY ...> declarations before Scour to prevent XML entity expansion bombs (CWE-776 / CWE-611)
            sanitized_svg = re.sub(
                r"<!DOCTYPE\b(?:\[[^\]]*\]|[^>])*>",
                "",
                svg_content,
                flags=re.IGNORECASE | re.DOTALL,
            )
            sanitized_svg = re.sub(
                r"<!ENTITY\b[^>]*>",
                "",
                sanitized_svg,
                flags=re.IGNORECASE | re.DOTALL,
            )

            import scour.scour

            opts = scour.scour.sanitizeOptions()
            opts.keep_editor_data = True
            opts.remove_metadata = False
            opts.indent_type = "space"
            opts.indent_depth = 2
            opts.digits = precision

            scoured = scour.scour.scourString(sanitized_svg, opts)
            return self._propagate_fill_rule_to_paths(scoured)
        except Exception as e:
            logger.warning("Scour SVG optimization failed, returning unoptimized SVG: %s", e)
            return svg_content

    @staticmethod
    def _propagate_fill_rule_to_paths(svg_str: str) -> str:
        """Ensure child <path> elements explicitly retain fill-rule from parent <g>.

        Scour hoists common fill-rule attributes to parent <g> elements.
        Primitive CAM/cutter software (Cricut Design Space, LaserGRBL) requires
        fill-rule directly on <path> tags to render cutout holes correctly.
        """
        def _replace_group(match: re.Match) -> str:
            group_open = match.group(1)
            rule = match.group(2)
            body = match.group(3)

            def _add_fill_rule(p_match: re.Match) -> str:
                path_tag = p_match.group(0)
                if "fill-rule=" not in path_tag:
                    return path_tag[:5] + f' fill-rule="{rule}"' + path_tag[5:]
                return path_tag

            updated_body = re.sub(r"<path\b[^>]*>", _add_fill_rule, body)
            return f"{group_open}{updated_body}</g>"

        pattern = re.compile(
            r'(<g\b[^>]*\bfill-rule="([^"]+)"[^>]*>)(.*?)(</g>)',
            re.DOTALL,
        )
        return pattern.sub(_replace_group, svg_str)

    def refit_circular_primitives(
        self,
        layer_data: StructuredLayerData,
        min_circularity: float = 0.82,
        max_area: float = 1500.0,
        min_area: float = 15.0,
        min_aspect: float = 0.75,
    ) -> StructuredLayerData:
        """Refits circular micro-primitives across all paths in layer_data.

        Transforms faceted polygons (such as 8-sided octagonal buttons, dots, or
        spots) into mathematically smooth 4-arc cubic Bezier circles/ellipses,
        while leaving all non-circular contours (such as sharp 90-degree pocket
        corners) 100% untouched.
        """
        if not layer_data or not layer_data.layers:
            return layer_data

        new_layers = []
        for layer in layer_data.layers:
            new_paths = []
            for path in layer.paths:
                new_d = refit_path_d(
                    path.path_data,
                    min_circularity=min_circularity,
                    max_area=max_area,
                    min_area=min_area,
                    min_aspect=min_aspect,
                )
                if new_d != path.path_data:
                    new_paths.append(
                        PathRecord(
                            id=path.id,
                            color_hex=path.color_hex,
                            path_data=new_d,
                            area=path.area,
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

        return StructuredLayerData(
            mode=layer_data.mode,
            layers=new_layers,
            dimensions=layer_data.dimensions,
        )

    def build_and_optimize(
        self,
        layer_data: StructuredLayerData,
        dimensions: Optional[Tuple[int, int]] = None,
        precision: int = 7,
        enable_scour: bool = True,
        refit_circles: bool = True,
    ) -> OptimizedSvgResult:
        """Builds an Inkscape layer DOM SVG and applies Scour optimization passes.

        Args:
            layer_data: StructuredLayerData containing ordered LayerGroup instances.
            dimensions: Optional (width, height) document canvas dimensions.
            precision: Decimal precision for numerical coordinates.
            enable_scour: Whether to run Scour optimization.
            refit_circles: Whether to refit circular micro-primitives into smooth Bezier arcs.

        Returns:
            OptimizedSvgResult containing SVG markup, layer count, node count, and byte size.
        """
        if refit_circles:
            layer_data = self.refit_circular_primitives(layer_data)

        raw_svg = self.build_svg(layer_data, dimensions=dimensions)
        optimized_svg = self.optimize(raw_svg, precision=precision, enable_scour=enable_scour)

        layer_count = len(layer_data.layers) if layer_data and layer_data.layers else 0
        total_nodes = self.count_nodes(layer_data) if layer_data else 0
        file_size = len(optimized_svg.encode("utf-8"))

        return OptimizedSvgResult(
            svg_content=optimized_svg,
            layer_count=layer_count,
            total_nodes=total_nodes,
            file_size=file_size,
        )

