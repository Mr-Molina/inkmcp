"""Vectorization pipeline package for inkmcp."""

from inkmcp.vectorizer.cam_planner import CamPlanResult, optimize_cam_toolpaths, order_inside_out_cuts
from inkmcp.vectorizer.containment_dag import build_containment_dag, resolve_stacking_order
from inkmcp.vectorizer.core import (
    PathRecord,
    RawVectorResult,
    VTracerCore,
    apply_translate_to_svg_path,
    scale_svg_path_coordinates,
)
from inkmcp.vectorizer.node_decimator import (
    NodeMetrics,
    decimate_path_nodes,
    fair_tangents_g1,
    fit_cubic_beziers_schneider,
    prune_micro_segments,
)
from inkmcp.vectorizer.optimizer import OptimizedSvgResult, SvgOptimizer
from inkmcp.vectorizer.palette import (
    delta_e_cie76,
    hex_to_rgb,
    rgb_to_lab,
    standardize_color_palette,
)
from inkmcp.vectorizer.pipeline import (
    PipelineConfig,
    PipelineResult,
    VectorizationPipeline,
)
from inkmcp.vectorizer.preprocessor import ImagePreprocessor, PreprocessedImageData
from inkmcp.vectorizer.primitives import (
    detect_and_refit_rectangles,
    format_rect_path,
    skeletonize_thin_loops_mat,
)
from inkmcp.vectorizer.super_res import SuperResolutionProcessor
from inkmcp.vectorizer.topology import LayerGroup, StructuredLayerData, TopologyEngine
from inkmcp.vectorizer.trapping import apply_choke_spread_trapping, compute_color_luminance

__all__ = [
    "ImagePreprocessor",
    "PreprocessedImageData",
    "SuperResolutionProcessor",
    "PathRecord",
    "RawVectorResult",
    "VTracerCore",
    "apply_translate_to_svg_path",
    "scale_svg_path_coordinates",
    "LayerGroup",
    "StructuredLayerData",
    "TopologyEngine",
    "SvgOptimizer",
    "OptimizedSvgResult",
    "hex_to_rgb",
    "rgb_to_lab",
    "delta_e_cie76",
    "standardize_color_palette",
    "NodeMetrics",
    "prune_micro_segments",
    "fit_cubic_beziers_schneider",
    "fair_tangents_g1",
    "decimate_path_nodes",
    "apply_choke_spread_trapping",
    "compute_color_luminance",
    "detect_and_refit_rectangles",
    "format_rect_path",
    "skeletonize_thin_loops_mat",
    "build_containment_dag",
    "resolve_stacking_order",
    "CamPlanResult",
    "order_inside_out_cuts",
    "optimize_cam_toolpaths",
    "PipelineConfig",
    "PipelineResult",
    "VectorizationPipeline",
]
