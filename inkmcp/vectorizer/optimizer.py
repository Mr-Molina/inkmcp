"""SVG DOM layer structuring and Scour optimization module."""

from dataclasses import dataclass
import logging
import re
from typing import Optional, Tuple
from xml.sax.saxutils import escape

from inkmcp.vectorizer.topology import StructuredLayerData

logger = logging.getLogger(__name__)


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
                    fill_rule = (
                        f' fill-rule="{_escape_attr(path.fill_rule)}"'
                        if path.fill_rule
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
        precision: int = 3,
        enable_scour: bool = True,
    ) -> str:
        """Optimizes SVG content using Scour while preserving Inkscape layer metadata.

        Args:
            svg_content: Input SVG markup string.
            precision: Decimal precision for coordinates.
            enable_scour: Whether to apply Scour optimization passes.

        Returns:
            Cleaned and optimized SVG markup string, or original content on fallback.
        """
        if not enable_scour or not svg_content or not svg_content.strip():
            return svg_content

        try:
            import scour.scour

            opts = scour.scour.sanitizeOptions()
            opts.keep_editor_data = True
            opts.remove_metadata = False
            opts.indent_type = "space"
            opts.indent_depth = 2
            opts.digits = precision

            return scour.scour.scourString(svg_content, opts)
        except Exception as e:
            logger.warning("Scour SVG optimization failed, returning unoptimized SVG: %s", e)
            return svg_content

    def build_and_optimize(
        self,
        layer_data: StructuredLayerData,
        dimensions: Optional[Tuple[int, int]] = None,
        precision: int = 3,
        enable_scour: bool = True,
    ) -> OptimizedSvgResult:
        """Builds an Inkscape layer DOM SVG and applies Scour optimization passes.

        Args:
            layer_data: StructuredLayerData containing ordered LayerGroup instances.
            dimensions: Optional (width, height) document canvas dimensions.
            precision: Decimal precision for numerical coordinates.
            enable_scour: Whether to run Scour optimization.

        Returns:
            OptimizedSvgResult containing SVG markup, layer count, node count, and byte size.
        """
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
