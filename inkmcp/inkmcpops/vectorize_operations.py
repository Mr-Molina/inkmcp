"""Vectorize operations module for inkmcp.

Orchestrates the conversion of flat raster images into fabrication-ready vector SVGs,
handling preprocessing, VTracer tracing, topological restructuring, Scour optimization,
file export, and live Inkscape canvas injection.
"""

import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional

from inkmcp.inkmcpops.common import create_error_response, create_success_response
from inkmcp.vectorizer import (
    ImagePreprocessor,
    SvgOptimizer,
    TopologyEngine,
    VTracerCore,
)

logger = logging.getLogger(__name__)

VALID_MODES = ("cut_ready", "layered", "silhouette", "coloring_book")
# planar: shared-boundary tracer (no gaps/slivers; default for cut_ready)
# vtracer: legacy per-region VTracer pipeline (default for layered/silhouette)
VALID_ENGINES = ("planar", "vtracer")


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
            - mode (str, optional): 'cut_ready' (default), 'layered', 'silhouette', or 'coloring_book'.
            - engine (str, optional): 'planar' (default for cut_ready) traces a shared-boundary
              planar mosaic - every border between two colors is fitted once, so there are no
              gaps, slivers or uneven outlines. 'vtracer' uses the legacy per-region pipeline.
            - num_colors (int, optional): Clamped 2..32. Planar engine: omit/0 = auto-detect.
              VTracer engine default 8.
            - flatten (str|bool, optional): Planar engine only. 'auto' (default) flattens
              gradients/painted shading into flat regions when the image is not already flat;
              true forces it, false disables it.
            - filter_speckle (float, optional): Speckle cutoff area, default 4.0.
            - smoothness (float, optional): Curve smoothness multiplier, default 1.0.
            - color_tolerance (float, optional): CIELAB Delta E color merging threshold, default 5.0.
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

        mode = str(params.get("mode", "cut_ready")).strip()
        if mode not in VALID_MODES:
            return create_error_response(
                f"Unsupported mode: '{mode}'. Must be 'cut_ready', 'layered', 'silhouette', or 'coloring_book'"
            )

        if mode == "coloring_book":
            from inkmcp.vectorizer.coloring_book_pipeline import ColoringBookPipeline
            return ColoringBookPipeline().run(params, backend=backend)

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

        try:
            color_tolerance = float(params.get("color_tolerance", 5.0))
        except (ValueError, TypeError):
            color_tolerance = 5.0

        try:
            subpixel_scale = int(
                params.get("subpixel_scale", 2 if mode == "silhouette" else 1)
            )
        except (ValueError, TypeError):
            subpixel_scale = 2 if mode == "silhouette" else 1
        subpixel_scale = max(1, subpixel_scale)

        try:
            if "corner_threshold" in params and params["corner_threshold"] is not None:
                corner_threshold = int(params["corner_threshold"])
            elif smoothness != 1.0:
                corner_threshold = max(1, min(180, int(round(60 * smoothness))))
            else:
                corner_threshold = 60
        except (ValueError, TypeError):
            corner_threshold = 60

        try:
            if "segment_length" in params and params["segment_length"] is not None:
                segment_length = float(params["segment_length"])
            elif smoothness != 1.0:
                segment_length = max(0.5, float(4.0 * smoothness))
            else:
                segment_length = 4.0
        except (ValueError, TypeError):
            segment_length = 4.0

        colormode = "binary" if mode == "silhouette" else "color"

        denoise = _parse_bool(params.get("denoise", True), default=True)
        remove_background = _parse_bool(params.get("remove_background", False), default=False)
        inject_to_inkscape = _parse_bool(params.get("inject_to_inkscape", True), default=True)
        output_path = params.get("output_path")

        engine = str(params.get("engine") or ("planar" if mode == "cut_ready" else "vtracer")).strip().lower()
        if engine not in VALID_ENGINES:
            return create_error_response(
                f"Unsupported engine: '{engine}'. Must be one of {', '.join(VALID_ENGINES)}"
            )
        if engine == "planar" and mode == "silhouette":
            engine = "vtracer"

        if engine == "planar":
            from inkmcp.vectorizer.planar_tracer import PlanarTraceConfig, trace_planar

            raw_colors = params.get("num_colors")
            try:
                requested = (
                    int(raw_colors if raw_colors is not None else 8)
                    if raw_colors not in (None, "", "auto")
                    else 0
                )
            except (ValueError, TypeError):
                requested = 0
            raw_flatten = params.get("flatten")
            if raw_flatten is None or str(raw_flatten).strip().lower() in ("", "auto"):
                flatten_opt = None
            else:
                flatten_opt = _parse_bool(raw_flatten, default=False)
            cfg = PlanarTraceConfig(
                num_colors=max(2, min(32, requested)) if requested > 0 else None,
                min_area=max(1, int(round(filter_speckle * 3))),
                smooth_sigma=1.0 * smoothness,
                fit_tolerance=0.45 * smoothness,
                remove_background=remove_background,
                flatten=flatten_opt,
            )
            traced = trace_planar(str(image_path_obj), cfg)
            layers_info = [
                {
                    "layer_id": lyr["layer_id"],
                    "label": lyr["label"],
                    "color_hex": lyr["color_hex"],
                    "z_index": lyr["z_index"],
                    "paths": [{
                        "id": lyr["path_id"],
                        "fill": lyr["color_hex"],
                        "d": lyr["d"],
                        "fill_rule": lyr["fill_rule"],
                    }],
                }
                for lyr in traced.layers
            ]
            return _finish(
                svg_content=traced.svg,
                layers_info=layers_info,
                total_nodes=traced.node_count,
                mode=mode,
                engine=engine,
                output_path=output_path,
                inject_to_inkscape=inject_to_inkscape,
                backend=backend,
                extra={
                    "palette": [lyr["color_hex"] for lyr in traced.layers],
                    "flattened": traced.stats.get("flattened", False),
                    "gradient_score": traced.stats.get("gradient_score"),
                },
            )

        if not params.get("num_colors"):
            num_colors = 8

        # 3. Preprocess raster image
        preprocessor_kwargs = {}
        if "filter_diameter" in params and params["filter_diameter"] is not None:
            try:
                preprocessor_kwargs["filter_diameter"] = int(params["filter_diameter"])
            except (ValueError, TypeError):
                pass
        preprocessor = ImagePreprocessor(**preprocessor_kwargs)
        preprocessed = preprocessor.process(
            str(image_path_obj),
            num_colors=num_colors,
            denoise=denoise,
            remove_background=remove_background,
            mode=mode,
            subpixel_scale=subpixel_scale,
        )

        hierarchical = str(params.get("hierarchical", "cutout")).strip().lower()
        if hierarchical not in ("cutout", "stacked"):
            hierarchical = "cutout"

        # 4. Vectorize contours via VTracer
        core = VTracerCore()
        img_to_vectorize = getattr(preprocessed, "processed_image", None) or getattr(
            preprocessed, "image", None
        )
        target_img = img_to_vectorize if img_to_vectorize is not None else str(image_path_obj)
        filter_speckle_int = max(0, int(round(filter_speckle)))
        scaled_segment_length = segment_length * (
            float(subpixel_scale) if subpixel_scale > 1 else 1.0
        )
        scale_factor = (1.0 / subpixel_scale) if subpixel_scale > 1 else 1.0

        raw_vector = core.vectorize(
            target_img,
            colormode=colormode,
            hierarchical=hierarchical,
            filter_speckle=filter_speckle_int,
            corner_threshold=corner_threshold,
            segment_length=scaled_segment_length,
            scale_factor=scale_factor,
        )

        # 5. Restructure geometry into layer topology
        topology = TopologyEngine()
        canonical_color = preprocessed.palette[0] if preprocessed.palette else None
        structured_data = topology.process(
            paths=raw_vector.path_records,
            mode=mode,
            dimensions=preprocessed.dimensions,
            filter_speckle=filter_speckle,
            color_tolerance=color_tolerance,
            canonical_color=canonical_color,
        )

        # 6. Build and optimize SVG markup
        optimizer = SvgOptimizer()
        optimized_svg = optimizer.build_and_optimize(
            structured_data,
            dimensions=raw_vector.dimensions,
        )

        layers_info = [
            {
                "layer_id": layer.layer_id,
                "label": layer.label,
                "color_hex": layer.color_hex,
                "z_index": layer.z_index,
                "paths": [
                    {"id": p.id, "fill": p.color_hex, "d": p.path_data, "fill_rule": p.fill_rule}
                    for p in layer.paths
                ],
            }
            for layer in structured_data.layers
        ]
        return _finish(
            svg_content=optimized_svg.svg_content,
            layers_info=layers_info,
            total_nodes=optimized_svg.total_nodes,
            mode=mode,
            engine=engine,
            output_path=output_path,
            inject_to_inkscape=inject_to_inkscape,
            backend=backend,
            layer_count=optimized_svg.layer_count,
            file_size=optimized_svg.file_size,
        )

    except Exception as e:
        logger.exception("Vectorization operation failed unexpectedly")
        return create_error_response(f"Vectorization failed: {str(e)}", error_details=str(e))


def _finish(
    svg_content: str,
    layers_info: List[Dict[str, Any]],
    total_nodes: int,
    mode: str,
    engine: str,
    output_path: Optional[str],
    inject_to_inkscape: bool,
    backend: Optional[Any],
    layer_count: Optional[int] = None,
    file_size: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Write the SVG, optionally inject layers into Inkscape, and build the response."""
    # 7. Write to output file (or fallback temporary file)
    temp_svg_path: Optional[str] = None
    if output_path:
        resolved_output_path = os.path.abspath(output_path)
        parent_dir = os.path.dirname(resolved_output_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
    else:
        temp_fd, temp_svg_path = tempfile.mkstemp(suffix=".svg", prefix="inkmcp_vectorize_")
        os.close(temp_fd)
        resolved_output_path = os.path.abspath(temp_svg_path)

    try:
        with open(resolved_output_path, "w", encoding="utf-8") as f:
            f.write(svg_content)
    except Exception as e:
        if temp_svg_path and os.path.exists(temp_svg_path):
            try:
                os.remove(temp_svg_path)
            except OSError:
                pass
        return create_error_response(f"Failed to write SVG: {str(e)}")

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
                for layer in layers_info:
                    layer_payload = {
                        "tag": "g",
                        "attributes": {
                            "id": layer["layer_id"],
                            "inkscape:groupmode": "layer",
                            "inkscape:label": layer["label"],
                        },
                        "children": [
                            {
                                "tag": "path",
                                "attributes": {
                                    "id": p["id"],
                                    "fill": p["fill"],
                                    "d": p["d"],
                                    "fill-rule": p["fill_rule"],
                                },
                            }
                            for p in layer["paths"]
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
        "engine": engine,
        "layer_count": layer_count if layer_count is not None else len(layers_info),
        "total_nodes": total_nodes,
        "file_size": file_size if file_size is not None else len(svg_content.encode("utf-8")),
        "layers": [
            {
                "layer_id": layer["layer_id"],
                "label": layer["label"],
                "color_hex": layer["color_hex"],
                "path_count": len(layer["paths"]),
                "z_index": layer["z_index"],
            }
            for layer in layers_info
        ],
        "injected": injected,
    }
    if extra:
        response_data.update(extra)

    # 10. Status determination
    count = response_data["layer_count"]
    if inject_to_inkscape and not injected:
        warning_msg = f"Inkscape GUI is offline; vector SVG saved to {resolved_output_path}"
        return _create_warning_response(warning_msg, **response_data)

    if inject_to_inkscape and injected:
        success_msg = (
            f"Vectorized image with {count} layers "
            f"and injected to Inkscape canvas (saved to {resolved_output_path})"
        )
        return create_success_response(success_msg, **response_data)

    success_msg = f"Vector SVG saved successfully to {resolved_output_path}"
    return create_success_response(success_msg, **response_data)


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
