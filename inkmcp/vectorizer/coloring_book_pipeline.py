"""Coloring book vectorization and live fill pipeline."""
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional
from PIL import Image

from inkmcp.backends.desktop_automator import InkscapeDesktopAutomator
from inkmcp.inkmcpops.common import create_error_response, create_success_response
from inkmcp.vectorizer.color_inventory import ColorInventory
from inkmcp.vectorizer.core import VTracerCore
from inkmcp.vectorizer.outline_generator import OutlineGenerator
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

        outline_path = params.get("outline_path")
        output_path = params.get("output_path")
        num_colors = int(params.get("num_colors", 8))
        min_region_area = int(params.get("min_region_area", 25))
        click_delay_ms = int(params.get("click_delay_ms", 80))
        inject_to_inkscape = bool(params.get("inject_to_inkscape", True))

        # 1. Color Inventory
        inventory = ColorInventory.from_image(image_path, num_colors=num_colors)

        # 2. Outline Ingestion
        bin_outline = self._outline_gen.generate_outline(image_path, outline_path=outline_path)

        # 3. Vectorize Line Art (Wrap ndarray in PIL.Image to prevent VTracer TypeError)
        pil_outline = Image.fromarray(bin_outline)
        core = VTracerCore()
        raw_vector = core.vectorize(
            pil_outline,
            colormode="binary",
            hierarchical="stacked",
            filter_speckle=4,
        )

        # 4. Generate SVG Document Content
        h, w = bin_outline.shape[:2]
        paths_xml = "\n".join(
            f'    <path id="{p.id}" fill="#000000" d="{p.path_data}" />'
            for p in raw_vector.path_records
        )
        svg_content = (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
            f'  <g id="layer_line_art" inkscape:groupmode="layer" inkscape:label="Line Art">\n'
            f'{paths_xml}\n'
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

        # 5. Canvas Injection & Viewport Normalization
        if inject_to_inkscape and backend is not None and hasattr(backend, "execute_operation"):
            layer_payload = {
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
                            "id": p.id,
                            "fill": "#000000",
                            "d": p.path_data,
                        },
                    }
                    for p in raw_vector.path_records
                ],
            }
            backend.execute_operation(layer_payload)

            try:
                import subprocess
                from inkmcp.platform_utils import find_inkscape_executable
                ink_exe = find_inkscape_executable()
                if ink_exe:
                    subprocess.run(
                        [str(ink_exe), "-q", "--actions=select-all;page-fit-to-selection;zoom-drawing;select-clear"],
                        capture_output=True,
                        timeout=10,
                    )
            except Exception:
                pass

        # 6. Extract Regions & Build Click Commands
        regions = self._topology.extract_fill_regions(bin_outline, min_area=min_region_area)
        commands = []
        for r in regions:
            color = inventory.get_color_at(r.u, r.v)
            commands.append((color, r.u, r.v))

        # 7. Live Desktop Win32 Paint Bucket Automation
        auto_result = {"status": "skipped", "clicks_dispatched": 0}
        if inject_to_inkscape and self._automator.is_available():
            auto_result = self._automator.execute_sequence(
                commands, click_delay_ms=click_delay_ms, backend=backend
            )

        return create_success_response(
            "Coloring book vectorization and fill sequence complete",
            output_path=resolved_output,
            regions_detected=len(regions),
            palette=inventory.get_palette(),
            total_nodes=sum(len(p.path_data.split()) for p in raw_vector.path_records),
            layer_count=1,
            automation=auto_result,
        )
