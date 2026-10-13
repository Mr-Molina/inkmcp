import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, Optional
from xml.sax.saxutils import escape
import cv2
import numpy as np
from PIL import Image

from inkmcp.backends.desktop_automator import InkscapeDesktopAutomator
from inkmcp.inkmcpops.common import create_error_response, create_success_response
from inkmcp.vectorizer.color_inventory import ColorInventory
from inkmcp.vectorizer.core import VTracerCore
from inkmcp.vectorizer.outline_generator import OutlineGenerator
from inkmcp.vectorizer.planar_tracer import PlanarTraceConfig, trace_planar
from inkmcp.vectorizer.region_topology import RegionTopologyAnalyzer

class ColoringBookPipeline:
    """Coordinates color inventory, outline tracing, canvas injection, and desktop bucket filling."""

    def __init__(self, automator: Optional[InkscapeDesktopAutomator] = None):
        self._automator = automator or InkscapeDesktopAutomator()
        self._topology = RegionTopologyAnalyzer()
        self._outline_gen = OutlineGenerator()

    def run(
        self,
        params: Dict[str, Any],
        backend: Optional[Any] = None,
    ) -> Dict[str, Any]:
        image_path = params.get("image_path")
        if not image_path:
            return create_error_response("image_path is required")

        if not Path(image_path).is_file():
            return create_error_response(f"Source image not found: {image_path}")

        outline_path = params.get("outline_path")
        output_path = params.get("output_path")
        num_colors = int(params.get("num_colors", 8))
        min_region_area = int(params.get("min_region_area", 25))
        click_delay_ms = int(params.get("click_delay_ms", 80))
        inject_to_inkscape = bool(params.get("inject_to_inkscape", True))

        # 1. Color Inventory
        try:
            inventory = ColorInventory.from_image(image_path, num_colors=num_colors)
        except Exception as e:
            return create_error_response(f"Failed to generate color inventory: {e}")

        # 2. Outline Ingestion
        with Image.open(image_path) as src_img:
            img_w, img_h = src_img.size

        bin_outline = self._outline_gen.generate_outline(image_path, outline_path=outline_path)
        if bin_outline.shape[:2] != (img_h, img_w):
            bin_outline = cv2.resize(bin_outline, (img_w, img_h), interpolation=cv2.INTER_NEAREST)

        engine = str(params.get("engine", "planar")).strip().lower()

        # 3. Vectorize Line Art (defaults to planar tracer for subpixel line weight preservation)
        line_path_records = []
        if engine == "planar":
            cfg = PlanarTraceConfig(
                num_colors=2,
                palette=[(0, 0, 0), (255, 255, 255)],
                min_area=4,
                supersample=4,
                subpixel_edges=True,
            )
            planar_input = outline_path if (outline_path and Path(outline_path).is_file()) else bin_outline
            planar_res = trace_planar(planar_input, cfg)
            black_paths = re.findall(r'<path[^>]*fill="#000000"[^>]*d="([^"]*)"', planar_res.svg)
            if not black_paths:
                black_paths = re.findall(r'<path[^>]*d="([^"]*)"[^>]*fill="#000000"', planar_res.svg)

            for idx, d_data in enumerate(black_paths):
                path_id = f"path_line_art_{idx+1:03d}" if len(black_paths) > 1 else "path_line_art"
                line_path_records.append({"id": path_id, "d": d_data})
        else:
            pil_outline = Image.fromarray(bin_outline)
            core = VTracerCore()
            raw_vector = core.vectorize(
                pil_outline,
                colormode="binary",
                hierarchical="stacked",
                filter_speckle=4,
            )
            line_path_records = [
                {"id": p.id, "d": p.path_data}
                for p in raw_vector.path_records
            ]

        # 4. Extract Regions & Generate Vector Fills
        h, w = bin_outline.shape[:2]
        regions = self._topology.extract_fill_regions(bin_outline, min_area=min_region_area)

        _, bin_mask = cv2.threshold(bin_outline, 127, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        inv_closed = cv2.morphologyEx(cv2.bitwise_not(bin_mask), cv2.MORPH_CLOSE, kernel)
        processed = cv2.bitwise_not(inv_closed)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(processed, connectivity=8)

        fill_paths_xml = []
        fill_paths_records = []
        choke_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        commands = []

        for idx, r in enumerate(regions):
            color = inventory.get_color_at(r.u, r.v)
            commands.append((color, r.u, r.v))
            lbl = labels[r.pixel_y, r.pixel_x]
            if lbl <= 0:
                continue

            region_mask = (labels == lbl).astype(np.uint8) * 255
            # Tuck slightly under black outlines so no white gap lines appear
            region_mask = cv2.dilate(region_mask, choke_kernel, iterations=1)
            contours, hierarchy = cv2.findContours(region_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_KCOS)
            if hierarchy is not None and len(contours) > 0:
                for c_idx, cnt in enumerate(contours):
                    # Only iterate exterior boundaries (parent == -1)
                    if hierarchy[0][c_idx][3] != -1:
                        continue
                    if len(cnt) >= 3:
                        approx = cv2.approxPolyDP(cnt, 0.75, True)
                        if len(approx) >= 3:
                            pts = [f"{pt[0][0]},{pt[0][1]}" for pt in approx]
                            d_parts = [f"M {pts[0]} L " + " ".join(pts[1:]) + " Z"]
                            # Support interior holes in fill regions
                            child_idx = hierarchy[0][c_idx][2]
                            while child_idx != -1:
                                child_cnt = contours[child_idx]
                                if len(child_cnt) >= 3:
                                    child_approx = cv2.approxPolyDP(child_cnt, 0.75, True)
                                    if len(child_approx) >= 3:
                                        h_pts = [f"{pt[0][0]},{pt[0][1]}" for pt in child_approx]
                                        d_parts.append(f"M {h_pts[0]} L " + " ".join(h_pts[1:]) + " Z")
                                child_idx = hierarchy[0][child_idx][0]
                            d = " ".join(d_parts)
                            path_id = f"fill_{idx:03d}_{c_idx}"
                            fill_paths_xml.append(
                                f'    <path id="{escape(path_id)}" fill="{escape(color)}" stroke="none" d="{escape(d)}" />'
                            )
                            fill_paths_records.append({
                                "id": path_id,
                                "fill": color,
                                "d": d,
                            })

        line_paths_xml = [
            f'    <path id="{escape(p["id"])}" fill="#000000" fill-rule="nonzero" stroke="none" d="{escape(p["d"])}" />'
            for p in line_path_records
        ]

        # 5. Generate Full SVG Document (Fills Layer + Line Art Layer)
        fills_xml_str = "\n".join(fill_paths_xml)
        lines_xml_str = "\n".join(line_paths_xml)
        svg_content = (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
            f'  <g id="layer_fills" inkscape:groupmode="layer" inkscape:label="Fills">\n'
            f'{fills_xml_str}\n'
            f'  </g>\n'
            f'  <g id="layer_line_art" inkscape:groupmode="layer" inkscape:label="Line Art">\n'
            f'{lines_xml_str}\n'
            f'  </g>\n'
            f'</svg>'
        )

        resolved_output = output_path
        if not resolved_output:
            temp_fd, temp_path = tempfile.mkstemp(suffix=".svg", prefix="coloring_book_")
            os.close(temp_fd)
            resolved_output = temp_path
        else:
            resolved_output = os.path.abspath(resolved_output)
            parent_dir = os.path.dirname(resolved_output)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

        with open(resolved_output, "w", encoding="utf-8") as f:
            f.write(svg_content)

        # 6. Canvas Injection & Viewport Normalization
        if inject_to_inkscape and backend is not None and hasattr(backend, "execute_operation"):
            # Inject Fills Layer first (underneath)
            if fill_paths_records:
                fills_payload = {
                    "tag": "g",
                    "attributes": {
                        "id": "layer_fills",
                        "inkscape:groupmode": "layer",
                        "inkscape:label": "Fills",
                    },
                    "children": [
                        {
                            "tag": "path",
                            "attributes": {
                                "id": p["id"],
                                "fill": p["fill"],
                                "stroke": "none",
                                "d": p["d"],
                            },
                        }
                        for p in fill_paths_records
                    ],
                }
                backend.execute_operation(fills_payload)

            # Inject Line Art Layer second (on top)
            lines_payload = {
                "tag": "g",
                "attributes": {
                    "id": "layer_line_art",
                    "inkscape:groupmode": "layer",
                    "inkscape:label": "Line Art",
                },
                "children": [
                    {
                        "tag": "path",
                        "attributes": {
                            "id": p["id"],
                            "fill": "#000000",
                            "fill-rule": "nonzero",
                            "stroke": "none",
                            "d": p["d"],
                        },
                    }
                    for p in line_path_records
                ],
            }
            backend.execute_operation(lines_payload)

            try:
                import subprocess
                from inkmcp.platform_utils import find_inkscape_executable
                ink_exe = find_inkscape_executable()
                if ink_exe:
                    subprocess.run(
                        [str(ink_exe), str(resolved_output), "-q", "--actions=select-all;page-fit-to-selection;zoom-drawing;select-clear"],
                        capture_output=True,
                        timeout=5,
                    )
            except Exception:
                pass

        # 7. Live Desktop Win32 Paint Bucket Automation (Optional tool trigger)
        auto_result = {"status": "skipped", "clicks_dispatched": 0}
        if inject_to_inkscape and self._automator.is_available():
            auto_result = self._automator.execute_sequence(
                commands, click_delay_ms=click_delay_ms, backend=backend
            )

        total_nodes = sum(len(p["d"].split()) for p in line_path_records) + sum(len(p["d"].split()) for p in fill_paths_records)

        return create_success_response(
            "Coloring book vectorization and fill sequence complete",
            output_path=resolved_output,
            regions_detected=len(regions),
            palette=inventory.get_palette(),
            total_nodes=total_nodes,
            layer_count=2,
            automation=auto_result,
        )
