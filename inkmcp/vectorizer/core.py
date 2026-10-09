"""VTracer core vectorizer adapter module."""

import io
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image
from shapely.geometry import Polygon
from shapely.validation import make_valid
import vtracer


@dataclass
class PathRecord:
    """Vector path record extracted from SVG."""

    id: str = ""
    color_hex: str = "#000000"
    path_data: str = ""
    area: float = 0.0
    fill_rule: str = "nonzero"
    path_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.path_id and not self.id:
            self.id = self.path_id
        elif self.id and not self.path_id:
            self.path_id = self.id


@dataclass
class RawVectorResult:
    """Raw vectorization output containing SVG markup and parsed path records."""

    svg_string: str
    path_records: List[PathRecord]
    dimensions: Tuple[int, int]

    @property
    def paths(self) -> List[PathRecord]:
        """Alias for path_records for convenience and backward compatibility."""
        return self.path_records



def normalize_color_hex(fill: Optional[str]) -> str:
    """Normalizes an SVG color string into #RRGGBB format."""
    if not fill or not fill.strip():
        return "#000000"

    val = fill.strip()
    if val.startswith("#"):
        hex_digits = val[1:]
        if len(hex_digits) == 3:
            hex_digits = "".join(c * 2 for c in hex_digits)
        elif len(hex_digits) >= 6:
            hex_digits = hex_digits[:6]
        return f"#{hex_digits.upper()}"

    if val.startswith("rgb"):
        nums = [int(float(x.strip())) for x in re.findall(r"[-+]?\d*\.?\d+", val)]
        if len(nums) >= 3:
            r = max(0, min(255, nums[0]))
            g = max(0, min(255, nums[1]))
            b = max(0, min(255, nums[2]))
            return f"#{r:02X}{g:02X}{b:02X}"

    named_colors: Dict[str, str] = {
        "black": "#000000",
        "white": "#FFFFFF",
        "red": "#FF0000",
        "green": "#00FF00",
        "blue": "#0000FF",
        "yellow": "#FFFF00",
        "cyan": "#00FFFF",
        "magenta": "#FF00FF",
        "transparent": "#000000",
        "none": "#000000",
    }
    if val.lower() in named_colors:
        return named_colors[val.lower()]

    clean = re.sub(r"[^0-9a-fA-F]", "", val)
    if len(clean) == 3:
        clean = "".join(c * 2 for c in clean)
    if len(clean) >= 6:
        return f"#{clean[:6].upper()}"

    return "#000000"

def _format_coord(v: float) -> str:
    """Formats float coordinate with up to 4 decimals, trimming unnecessary zeros."""
    s = f"{v:.4f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def parse_svg_transform_translate(transform_str: Optional[str]) -> Tuple[float, float]:
    """Extracts (tx, ty) translation from an SVG transform string."""
    if not transform_str or not transform_str.strip():
        return (0.0, 0.0)

    # Check translate(tx, ty) or translate(tx ty) or translate(tx)
    m = re.search(
        r"translate\(\s*([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)(?:[\s,]+([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?))?\s*\)",
        transform_str,
    )
    if m:
        tx = float(m.group(1))
        ty = float(m.group(2)) if m.group(2) is not None else 0.0
        return (tx, ty)

    # Check matrix(a, b, c, d, e, f) where e=tx, f=ty
    m_mat = re.search(
        r"matrix\(\s*[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?[\s,]+[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?[\s,]+[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?[\s,]+[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?[\s,]+([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)[\s,]+([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)\s*\)",
        transform_str,
    )
    if m_mat:
        tx = float(m_mat.group(1))
        ty = float(m_mat.group(2))
        return (tx, ty)

    return (0.0, 0.0)


def apply_translate_to_svg_path(d: str, tx: float, ty: float) -> str:
    """Parses SVG path coordinates and shifts absolute coordinates by (+tx, +ty).

    Handles absolute M, L, C, S, Q, T, H, V, A, and Z commands. Relative deltas
    (lowercase commands) are preserved without shifting.
    """
    if not d or not d.strip():
        return ""
    if tx == 0.0 and ty == 0.0:
        return d

    tokens = re.findall(
        r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", d
    )
    if not tokens:
        return d

    result: List[str] = []
    idx = 0
    current_cmd = ""

    while idx < len(tokens):
        token = tokens[idx]
        if token.isalpha():
            current_cmd = token
            result.append(current_cmd)
            idx += 1
            continue

        if current_cmd in ("M", "L", "T"):
            if idx + 1 < len(tokens):
                x = float(tokens[idx]) + tx
                y = float(tokens[idx + 1]) + ty
                result.append(_format_coord(x))
                result.append(_format_coord(y))
                idx += 2
                if current_cmd == "M":
                    current_cmd = "L"
            else:
                idx += 1
        elif current_cmd == "C":
            if idx + 5 < len(tokens):
                x1 = float(tokens[idx]) + tx
                y1 = float(tokens[idx + 1]) + ty
                x2 = float(tokens[idx + 2]) + tx
                y2 = float(tokens[idx + 3]) + ty
                x3 = float(tokens[idx + 4]) + tx
                y3 = float(tokens[idx + 5]) + ty
                result.extend([
                    _format_coord(x1),
                    _format_coord(y1),
                    _format_coord(x2),
                    _format_coord(y2),
                    _format_coord(x3),
                    _format_coord(y3),
                ])
                idx += 6
            else:
                idx += 1
        elif current_cmd in ("S", "Q"):
            if idx + 3 < len(tokens):
                x1 = float(tokens[idx]) + tx
                y1 = float(tokens[idx + 1]) + ty
                x2 = float(tokens[idx + 2]) + tx
                y2 = float(tokens[idx + 3]) + ty
                result.extend([
                    _format_coord(x1),
                    _format_coord(y1),
                    _format_coord(x2),
                    _format_coord(y2),
                ])
                idx += 4
            else:
                idx += 1
        elif current_cmd == "H":
            x = float(tokens[idx]) + tx
            result.append(_format_coord(x))
            idx += 1
        elif current_cmd == "V":
            y = float(tokens[idx]) + ty
            result.append(_format_coord(y))
            idx += 1
        elif current_cmd == "A":
            if idx + 6 < len(tokens):
                rx = tokens[idx]
                ry = tokens[idx + 1]
                x_rot = tokens[idx + 2]
                large_arc = tokens[idx + 3]
                sweep = tokens[idx + 4]
                x = float(tokens[idx + 5]) + tx
                y = float(tokens[idx + 6]) + ty
                result.extend([
                    rx,
                    ry,
                    x_rot,
                    large_arc,
                    sweep,
                    _format_coord(x),
                    _format_coord(y),
                ])
                idx += 7
            else:
                idx += 1
        elif current_cmd in ("Z", "z"):
            idx += 1
        else:
            result.append(token)
            idx += 1

    return " ".join(result)


def parse_svg_path_to_rings(
    d: str, samples_per_curve: int = 8
) -> List[List[Tuple[float, float]]]:
    """Parses SVG path data into a list of polygonal coordinate rings."""
    tokens = re.findall(
        r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", d
    )

    rings: List[List[Tuple[float, float]]] = []
    current_ring: List[Tuple[float, float]] = []
    idx = 0
    current_x, current_y = 0.0, 0.0
    start_x, start_y = 0.0, 0.0
    current_cmd = ""
    last_c_ctrl = (0.0, 0.0)
    last_q_ctrl = (0.0, 0.0)

    while idx < len(tokens):
        token = tokens[idx]
        if token.isalpha():
            current_cmd = token
            idx += 1
            if current_cmd in ("M", "m") and current_ring:
                rings.append(current_ring)
                current_ring = []

        if current_cmd in ("M", "m"):
            x = float(tokens[idx])
            y = float(tokens[idx + 1])
            idx += 2
            if current_cmd == "m":
                x += current_x
                y += current_y
            current_x, current_y = x, y
            start_x, start_y = x, y
            current_ring.append((current_x, current_y))
            current_cmd = "L" if current_cmd == "M" else "l"
        elif current_cmd in ("L", "l"):
            x = float(tokens[idx])
            y = float(tokens[idx + 1])
            idx += 2
            if current_cmd == "l":
                x += current_x
                y += current_y
            current_x, current_y = x, y
            current_ring.append((current_x, current_y))
        elif current_cmd in ("H", "h"):
            x = float(tokens[idx])
            idx += 1
            if current_cmd == "h":
                x += current_x
            current_x = x
            current_ring.append((current_x, current_y))
        elif current_cmd in ("V", "v"):
            y = float(tokens[idx])
            idx += 1
            if current_cmd == "v":
                y += current_y
            current_y = y
            current_ring.append((current_x, current_y))
        elif current_cmd in ("C", "c"):
            x1 = float(tokens[idx])
            y1 = float(tokens[idx + 1])
            x2 = float(tokens[idx + 2])
            y2 = float(tokens[idx + 3])
            x3 = float(tokens[idx + 4])
            y3 = float(tokens[idx + 5])
            idx += 6
            if current_cmd == "c":
                x1 += current_x
                y1 += current_y
                x2 += current_x
                y2 += current_y
                x3 += current_x
                y3 += current_y
            p0 = (current_x, current_y)
            p1 = (x1, y1)
            p2 = (x2, y2)
            p3 = (x3, y3)
            last_c_ctrl = (x2, y2)
            for step in range(1, samples_per_curve + 1):
                t = step / samples_per_curve
                t_inv = 1.0 - t
                bx = (
                    t_inv**3 * p0[0]
                    + 3 * (t_inv**2) * t * p1[0]
                    + 3 * t_inv * (t**2) * p2[0]
                    + t**3 * p3[0]
                )
                by = (
                    t_inv**3 * p0[1]
                    + 3 * (t_inv**2) * t * p1[1]
                    + 3 * t_inv * (t**2) * p2[1]
                    + t**3 * p3[1]
                )
                current_ring.append((bx, by))
            current_x, current_y = x3, y3
        elif current_cmd in ("S", "s"):
            x2 = float(tokens[idx])
            y2 = float(tokens[idx + 1])
            x3 = float(tokens[idx + 2])
            y3 = float(tokens[idx + 3])
            idx += 4
            if current_cmd == "s":
                x2 += current_x
                y2 += current_y
                x3 += current_x
                y3 += current_y
            p0 = (current_x, current_y)
            p1 = (2 * current_x - last_c_ctrl[0], 2 * current_y - last_c_ctrl[1])
            p2 = (x2, y2)
            p3 = (x3, y3)
            last_c_ctrl = (x2, y2)
            for step in range(1, samples_per_curve + 1):
                t = step / samples_per_curve
                t_inv = 1.0 - t
                bx = (
                    t_inv**3 * p0[0]
                    + 3 * (t_inv**2) * t * p1[0]
                    + 3 * t_inv * (t**2) * p2[0]
                    + t**3 * p3[0]
                )
                by = (
                    t_inv**3 * p0[1]
                    + 3 * (t_inv**2) * t * p1[1]
                    + 3 * t_inv * (t**2) * p2[1]
                    + t**3 * p3[1]
                )
                current_ring.append((bx, by))
            current_x, current_y = x3, y3
        elif current_cmd in ("Q", "q"):
            x1 = float(tokens[idx])
            y1 = float(tokens[idx + 1])
            x2 = float(tokens[idx + 2])
            y2 = float(tokens[idx + 3])
            idx += 4
            if current_cmd == "q":
                x1 += current_x
                y1 += current_y
                x2 += current_x
                y2 += current_y
            p0 = (current_x, current_y)
            p1 = (x1, y1)
            p2 = (x2, y2)
            last_q_ctrl = (x1, y1)
            for step in range(1, samples_per_curve + 1):
                t = step / samples_per_curve
                t_inv = 1.0 - t
                bx = t_inv**2 * p0[0] + 2 * t_inv * t * p1[0] + t**2 * p2[0]
                by = t_inv**2 * p0[1] + 2 * t_inv * t * p1[1] + t**2 * p2[1]
                current_ring.append((bx, by))
            current_x, current_y = x2, y2
        elif current_cmd in ("T", "t"):
            x2 = float(tokens[idx])
            y2 = float(tokens[idx + 1])
            idx += 2
            if current_cmd == "t":
                x2 += current_x
                y2 += current_y
            p0 = (current_x, current_y)
            p1 = (2 * current_x - last_q_ctrl[0], 2 * current_y - last_q_ctrl[1])
            p2 = (x2, y2)
            last_q_ctrl = p1
            for step in range(1, samples_per_curve + 1):
                t = step / samples_per_curve
                t_inv = 1.0 - t
                bx = t_inv**2 * p0[0] + 2 * t_inv * t * p1[0] + t**2 * p2[0]
                by = t_inv**2 * p0[1] + 2 * t_inv * t * p1[1] + t**2 * p2[1]
                current_ring.append((bx, by))
            current_x, current_y = x2, y2
        elif current_cmd in ("Z", "z"):
            current_x, current_y = start_x, start_y
            current_ring.append((current_x, current_y))
        else:
            idx += 1

    if current_ring:
        rings.append(current_ring)
    return rings


def calculate_svg_path_area(d: str) -> float:
    """Calculates the 2D planar area of an SVG path using Shapely polygon approximation."""
    if not d or not d.strip():
        return 0.0

    try:
        rings = parse_svg_path_to_rings(d)
        valid_rings = [r for r in rings if len(r) >= 3]
        if not valid_rings:
            nums = [
                float(x)
                for x in re.findall(
                    r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", d
                )
            ]
            if len(nums) >= 4:
                xs = nums[0::2]
                ys = nums[1::2]
                return float((max(xs) - min(xs)) * (max(ys) - min(ys)))
            return 0.0

        if len(valid_rings) == 1:
            poly = Polygon(valid_rings[0])
            if not poly.is_valid:
                poly = make_valid(poly)
            return float(abs(poly.area))

        ring_polys = []
        for r in valid_rings:
            p = Polygon(r)
            if not p.is_valid:
                p = make_valid(p)
            ring_polys.append((abs(p.area), r))

        ring_polys.sort(key=lambda x: x[0], reverse=True)
        exterior = ring_polys[0][1]
        interiors = [r[1] for r in ring_polys[1:]]
        poly = Polygon(exterior, interiors)
        if not poly.is_valid:
            poly = make_valid(poly)
        return float(abs(poly.area))
    except Exception:
        try:
            nums = [
                float(x)
                for x in re.findall(
                    r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", d
                )
            ]
            if len(nums) >= 4:
                xs = nums[0::2]
                ys = nums[1::2]
                return float((max(xs) - min(xs)) * (max(ys) - min(ys)))
        except Exception:
            pass
        return 0.0


class VTracerCore:
    """Core adapter wrapping VTracer vectorization engine."""

    def vectorize(
        self,
        image_input: Union[str, Path, Image.Image, bytes],
        colormode: str = "color",
        hierarchical: str = "cutout",
        filter_speckle: int = 4,
        corner_threshold: int = 30,
        segment_length: float = 2.0,
        mode: str = "spline",
        **kwargs: Any,
    ) -> RawVectorResult:
        """Vectorizes an input image into SVG markup and structured path records.

        Args:
            image_input: File path (str or Path), PIL.Image.Image, or raw bytes.
            colormode: Color mode ("color" or "binary").
            hierarchical: Hierarchical layering mode ("cutout" or "stacked").
            filter_speckle: Minimum pixel patch area threshold for noise filtering.
            corner_threshold: Threshold angle for corner detection (default 30, or 25 for binary).
            segment_length: Curve fitting threshold (mapped to vtracer length_threshold, default 2.0).
            mode: Curve mode ("spline", "polygon", "none").
            **kwargs: Extra parameters passed to vtracer.
        """
        temp_input_path: Optional[str] = None
        dimensions: Tuple[int, int] = (0, 0)

        if colormode == "binary" and corner_threshold == 30:
            corner_threshold = 25

        def _prepare_image_for_tracing(pil_img: Image.Image) -> Image.Image:
            if colormode == "binary":
                has_alpha = (
                    pil_img.mode in ("RGBA", "LA")
                    or "A" in pil_img.getbands()
                    or (pil_img.mode == "P" and "transparency" in pil_img.info)
                )
                if has_alpha:
                    rgba = pil_img.convert("RGBA")
                    white_bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                    return Image.alpha_composite(white_bg, rgba).convert("RGB")
            return pil_img

        # Resolve image input and dimensions
        if isinstance(image_input, (str, Path)):
            input_path_obj = Path(image_input)
            if not input_path_obj.exists():
                raise FileNotFoundError(f"Image file not found: {image_input}")
            with Image.open(input_path_obj) as img:
                img.load()
                dimensions = img.size
                prepared = _prepare_image_for_tracing(img)
                if prepared is not img:
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_in:
                        temp_input_path = f_in.name
                    prepared.save(temp_input_path, format="PNG")
                    file_to_trace = temp_input_path
                else:
                    file_to_trace = str(input_path_obj)
        elif isinstance(image_input, Image.Image):
            dimensions = image_input.size
            prepared = _prepare_image_for_tracing(image_input)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_in:
                temp_input_path = f_in.name
            prepared.save(temp_input_path, format="PNG")
            file_to_trace = temp_input_path
        elif isinstance(image_input, (bytes, bytearray)):
            with Image.open(io.BytesIO(image_input)) as img:
                img.load()
                dimensions = img.size
                prepared = _prepare_image_for_tracing(img)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_in:
                temp_input_path = f_in.name
                if prepared is not img:
                    prepared.save(temp_input_path, format="PNG")
                else:
                    f_in.write(image_input)
            file_to_trace = temp_input_path
        else:
            raise TypeError(
                f"Unsupported image_input type: {type(image_input).__name__}. "
                "Expected str, Path, PIL.Image.Image, or bytes."
            )

        length_threshold = kwargs.pop("length_threshold", segment_length)

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f_out:
            temp_output_path = f_out.name

        try:
            res = vtracer.convert_image_to_svg_py(
                file_to_trace,
                temp_output_path,
                colormode=colormode,
                hierarchical=hierarchical,
                filter_speckle=filter_speckle,
                corner_threshold=corner_threshold,
                length_threshold=length_threshold,
                mode=mode,
                **kwargs,
            )

            if isinstance(res, str) and res.strip():
                svg_string = res
            else:
                with open(temp_output_path, "r", encoding="utf-8") as f:
                    svg_string = f.read()

        finally:
            if temp_input_path and os.path.exists(temp_input_path):
                try:
                    os.remove(temp_input_path)
                except OSError:
                    pass
            if os.path.exists(temp_output_path):
                try:
                    os.remove(temp_output_path)
                except OSError:
                    pass

        # Parse SVG to extract paths
        root = ET.fromstring(svg_string)

        # Update dimensions from SVG root if not set
        if dimensions == (0, 0):
            try:
                w = int(float(root.attrib.get("width", 0)))
                h = int(float(root.attrib.get("height", 0)))
                dimensions = (w, h)
            except (ValueError, TypeError):
                pass

        path_records: List[PathRecord] = []
        path_idx = 1

        for elem in root.iter():
            if elem.tag.endswith("path") or elem.tag == "path":
                raw_d = elem.attrib.get("d", "").strip()
                if not raw_d:
                    continue

                transform_attr = elem.attrib.get("transform")
                tx, ty = parse_svg_transform_translate(transform_attr)
                path_data = apply_translate_to_svg_path(raw_d, tx, ty)

                area = calculate_svg_path_area(path_data)
                if area <= 0.0:
                    continue

                if filter_speckle > 0 and area < float(filter_speckle):
                    continue

                fill_attr = elem.attrib.get("fill")
                fill_rule = elem.attrib.get("fill-rule", "nonzero")
                color_hex = normalize_color_hex(fill_attr)

                record = PathRecord(
                    id=f"path_{path_idx:03d}",
                    color_hex=color_hex,
                    path_data=path_data,
                    area=area,
                    fill_rule=fill_rule,
                )
                path_records.append(record)
                path_idx += 1

        return RawVectorResult(
            svg_string=svg_string,
            path_records=path_records,
            dimensions=dimensions,
        )
