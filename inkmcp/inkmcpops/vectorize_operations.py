"""Vectorize operations module for inkmcp.

Orchestrates the conversion of flat raster images into fabrication-ready vector SVGs,
handling preprocessing, VTracer tracing, topological restructuring, Scour optimization,
file export, and live Inkscape canvas injection.
"""

import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional

from inkmcp.inkmcpops.common import create_error_response, create_success_response
from inkmcp.vectorizer import (
    ImagePreprocessor,
    SvgOptimizer,
    TopologyEngine,
    VTracerCore,
)

logger = logging.getLogger(__name__)

def _create_warning_response(message: str, **data: Any) -> Dict[str, Any]:
    """Create a standardized warning response matching inkmcp common response schema."""
    response_data = {"message": message}
    response_data.update(data)
    return {
        "status": "warning",
        "message": message,
        "data": response_data,
    }


def _parse_bool(val: Any, default: bool = False) -> bool:
    """Helper to parse boolean flags from bool, int, or string representations."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes", "on")


def vectorize_image_operation(
    params: Dict[str, Any],
    backend: Optional[Any] = None,
) -> Dict[str, Any]:
    """Convert a raster image to a structured vector SVG and optionally inject to Inkscape.

    Args:
        params: Dictionary of parameters controlling the vectorization pipeline.
            - image_path (str, required): Path to source raster image.
            - output_path (str, optional): Target file path for SVG export.
            - mode (str, optional): 'cut_ready' (default) or 'layered'.
            - num_colors (int, optional): Clamped 2..32, default 8.
            - filter_speckle (float, optional): Speckle cutoff area, default 4.0.
            - smoothness (float, optional): Curve smoothness multiplier, default 1.0.
            - denoise (bool, optional): Bilateral filter denoising, default True.
            - remove_background (bool, optional): Backdrop removal, default False.
            - inject_to_inkscape (bool, optional): Live GUI injection, default True.
        backend: Optional Inkscape communication backend (e.g. Headless or Windows CLI).

    Returns:
        Canonical inkmcp response dictionary with status 'success', 'warning', or 'error'.
    """
    try:
        # 1. Validate image_path
        image_path = params.get("image_path")
        if not image_path:
            return create_error_response("image_path is required")

        image_path_obj = Path(image_path)
        if not image_path_obj.exists() or not image_path_obj.is_file():
            return create_error_response(f"Image file not found: {image_path}")

        # 2. Parse & sanitize parameters
        mode = str(params.get("mode", "cut_ready")).strip()
        if mode not in ("cut_ready", "layered"):
            return create_error_response(
                f"Unsupported mode: '{mode}'. Must be 'cut_ready' or 'layered'"
            )

        try:
            num_colors = int(params.get("num_colors", 8))
        except (ValueError, TypeError):
            num_colors = 8
        num_colors = max(2, min(32, num_colors))

        try:
            filter_speckle = float(params.get("filter_speckle", 4.0))
        except (ValueError, TypeError):
            filter_speckle = 4.0

        try:
            smoothness = float(params.get("smoothness", 1.0))
        except (ValueError, TypeError):
            smoothness = 1.0
        smoothness = max(0.1, smoothness)

        # Map smoothness multiplier to VTracer curve fitting thresholds
        segment_length = max(1, int(round(4 * smoothness)))
        corner_threshold = max(1, min(180, int(round(60 * smoothness))))

        denoise = _parse_bool(params.get("denoise", True), default=True)
        remove_background = _parse_bool(params.get("remove_background", False), default=False)
        inject_to_inkscape = _parse_bool(params.get("inject_to_inkscape", True), default=True)
        output_path = params.get("output_path")

        # 3. Preprocess raster image
        preprocessor = ImagePreprocessor()
        try:
            preprocessed = preprocessor.process(
                str(image_path_obj),
                num_colors=num_colors,
                denoise=denoise,
                remove_background=remove_background,
            )
        except TypeError:
            preprocessed = preprocessor.process(
                str(image_path_obj),
                num_colors=num_colors,
                remove_background=remove_background,
            )

        hierarchical = str(params.get("hierarchical", "cutout")).strip().lower()
        if hierarchical not in ("cutout", "stacked"):
            hierarchical = "cutout"

        # 4. Vectorize contours via VTracer
        core = VTracerCore()
        img_to_vectorize = getattr(preprocessed, "processed_image", None) or getattr(
            preprocessed, "image", None
        )
        filter_speckle_int = max(0, int(round(filter_speckle)))
        raw_vector = core.vectorize(
            img_to_vectorize,
            hierarchical=hierarchical,
            filter_speckle=filter_speckle_int,
            corner_threshold=corner_threshold,
            segment_length=segment_length,
        )

        # 5. Restructure geometry into layer topology
        topology = TopologyEngine()
        structured_data = topology.process(
            raw_vector.path_records,
            mode=mode,
            dimensions=raw_vector.dimensions,
            filter_speckle=filter_speckle,
        )

        # 6. Build and optimize SVG markup
        optimizer = SvgOptimizer()
        optimized_svg = optimizer.build_and_optimize(
            structured_data,
            dimensions=raw_vector.dimensions,
        )

        # 7. Write to output file (or fallback temporary file)
        if output_path:
            resolved_output_path = os.path.abspath(output_path)
            parent_dir = os.path.dirname(resolved_output_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
        else:
            temp_fd, temp_svg_path = tempfile.mkstemp(suffix=".svg", prefix="inkmcp_vectorize_")
            os.close(temp_fd)
            resolved_output_path = os.path.abspath(temp_svg_path)

        with open(resolved_output_path, "w", encoding="utf-8") as f:
            f.write(optimized_svg.svg_content)

        # 8. Live Inkscape injection or graceful fallback
        injected = False
        backend_available = False

        if inject_to_inkscape and backend is not None:
            is_avail = getattr(backend, "is_available", None)
            if callable(is_avail):
                try:
                    backend_available = bool(is_avail())
                except Exception as e:
                    logger.warning("Error checking backend availability: %s", e)
                    backend_available = False
            elif isinstance(is_avail, bool):
                backend_available = is_avail
            elif hasattr(backend, "execute_operation"):
                backend_available = True

            if backend_available:
                try:
                    for layer in structured_data.layers:
                        layer_payload = {
                            "tag": "g",
                            "attributes": {
                                "id": layer.layer_id,
                                "inkscape:groupmode": "layer",
                                "inkscape:label": layer.label,
                            },
                            "children": [
                                {
                                    "tag": "path",
                                    "attributes": {
                                        "id": p.id,
                                        "fill": p.color_hex,
                                        "d": p.path_data,
                                        "fill-rule": p.fill_rule,
                                    },
                                }
                                for p in layer.paths
                            ],
                        }
                        backend.execute_operation(layer_payload)
                    injected = True
                except Exception as e:
                    logger.warning("Failed injecting layers into Inkscape GUI: %s", e)
                    injected = False


        # 9. Format response payload
        response_data = {
            "output_path": resolved_output_path,
            "export_path": resolved_output_path,  # alias for backward/caller compatibility
            "mode": mode,
            "layer_count": optimized_svg.layer_count,
            "total_nodes": optimized_svg.total_nodes,
            "file_size": optimized_svg.file_size,
            "layers": [
                {
                    "layer_id": layer.layer_id,
                    "label": layer.label,
                    "color_hex": layer.color_hex,
                    "path_count": len(layer.paths),
                    "z_index": layer.z_index,
                }
                for layer in structured_data.layers
            ],
            "injected": injected,
        }

        # 10. Status determination
        if inject_to_inkscape and not injected:
            warning_msg = f"Inkscape GUI is offline; vector SVG saved to {resolved_output_path}"
            return _create_warning_response(warning_msg, **response_data)

        if inject_to_inkscape and injected:
            success_msg = (
                f"Vectorized image with {optimized_svg.layer_count} layers "
                f"and injected to Inkscape canvas (saved to {resolved_output_path})"
            )
            return create_success_response(success_msg, **response_data)

        success_msg = f"Vector SVG saved successfully to {resolved_output_path}"
        return create_success_response(success_msg, **response_data)

    except Exception as e:
        logger.exception("Vectorization operation failed unexpectedly")
        return create_error_response(f"Vectorization failed: {str(e)}", error_details=str(e))


class VectorizeOperations:
    """Dispatcher and orchestrator for flat-image to vector operations."""

    @staticmethod
    def vectorize_image(
        params: Dict[str, Any],
        backend: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Orchestrate flat-image to vector conversion."""
        return vectorize_image_operation(params, backend=backend)

    @classmethod
    def execute(
        cls,
        params: Dict[str, Any],
        backend: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Generic operation execution entrypoint for dispatcher compatibility."""
        return cls.vectorize_image(params, backend=backend)

    def __call__(
        self,
        params: Dict[str, Any],
        backend: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Instance invocation entrypoint."""
        return vectorize_image_operation(params, backend=backend)
