"""Master pipeline orchestrating end-to-end CAM fabrication vectorization."""

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image

from inkmcp.vectorizer.cam_planner import optimize_cam_toolpaths
from inkmcp.vectorizer.core import PathRecord, VTracerCore, parse_svg_path_to_rings
from inkmcp.vectorizer.node_decimator import decimate_path_nodes
from inkmcp.vectorizer.optimizer import SvgOptimizer, refit_path_d
from inkmcp.vectorizer.preprocessor import ImagePreprocessor
from inkmcp.vectorizer.primitives import (
    detect_and_refit_rectangles,
    format_rect_path,
    skeletonize_thin_loops_mat,
)
from inkmcp.vectorizer.super_res import SuperResolutionProcessor
from inkmcp.vectorizer.topology import LayerGroup, StructuredLayerData, TopologyEngine
from inkmcp.vectorizer.trapping import apply_choke_spread_trapping

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration options for the advanced CAM vectorization pipeline."""

    super_res_scale: int = 1
    num_colors: int = 8
    filter_speckle: float = 4.0
    color_tolerance: float = 5.0
    node_tolerance: float = 0.75
    enable_trapping: bool = True
    trap_distance: float = 1.13
    refit_primitives: bool = True
    centerline_skeleton: bool = False
    optimize_cam: bool = True
    mode: str = "cut_ready"


@dataclass
class PipelineResult:
    """Comprehensive outputs and performance metrics from the CAM vectorizer."""

    svg_content: str
    cut_ready_svg: str
    layered_svg: Optional[str]
    total_nodes_original: int
    total_nodes_optimized: int
    node_reduction_pct: float
    traverse_reduction_pct: float
    layers_count: int
    dimensions: Tuple[int, int]
    metrics: Dict[str, Any] = field(default_factory=dict)


class VectorizationPipeline:
    """Master manufacturing vectorization engine with deterministic CAM optimization."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.optimizer = SvgOptimizer()
        self.topology_engine = TopologyEngine()
        self.vtracer = VTracerCore()

    def run(
        self,
        image_input: Union[str, Path, Image.Image],
        output_dir: Optional[str] = None,
    ) -> PipelineResult:
        """Executes the full 6-phase vectorization pipeline on an input image.

        Args:
            image_input: File path or PIL Image.
            output_dir: Optional directory to save output SVG files.

        Returns:
            PipelineResult containing generated SVGs and manufacturing metrics.
        """
        temp_input_to_clean: Optional[str] = None
        # 1. Resolve image and dimensions
        if isinstance(image_input, (str, Path)):
            input_path = str(image_input)
            with Image.open(input_path) as pil_img:
                original_dims = pil_img.size
        elif isinstance(image_input, Image.Image):
            original_dims = image_input.size
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_in:
                input_path = f_in.name
            temp_input_to_clean = input_path
            image_input.save(input_path, format="PNG")
        else:
            raise TypeError(f"Unsupported image input type: {type(image_input)}")

        try:
            # 2. Phase 1: Super-Resolution / Preprocessing
            scale_factor = 1.0
            if self.config.super_res_scale > 1:
                super_res = SuperResolutionProcessor(
                    scale_factor=self.config.super_res_scale,
                    denoise=True,
                    block_quantize=True,
                )
                preprocessed_img = super_res.process(
                    input_path, num_colors=self.config.num_colors
                )
                scale_factor = 1.0 / float(self.config.super_res_scale)
                img_to_trace = preprocessed_img
            else:
                preprocessor = ImagePreprocessor()
                prep_data = preprocessor.process(
                    input_path,
                    num_colors=self.config.num_colors,
                    denoise=True,
                    mode=self.config.mode,
                )
                img_to_trace = prep_data.processed_image or prep_data.image

            # 3. Phase 2: Spline Contour Extraction
            filter_speckle_int = max(0, int(round(self.config.filter_speckle)))
            raw_cut_ready = self.vtracer.vectorize(
                img_to_trace,
                colormode="color",
                hierarchical="cutout",
                filter_speckle=filter_speckle_int,
                scale_factor=scale_factor,
            )

            raw_layered = self.vtracer.vectorize(
                img_to_trace,
                colormode="color",
                hierarchical="stacked",
                filter_speckle=filter_speckle_int,
                scale_factor=scale_factor,
            )

            # 4. Phase 3 & 4: Primitive Snapping & Node Decimation
            structured_cut_ready = self.topology_engine.process(
                paths=raw_cut_ready.path_records,
                mode="cut_ready",
                dimensions=original_dims,
                filter_speckle=self.config.filter_speckle,
                color_tolerance=self.config.color_tolerance,
            )

            structured_layered = self.topology_engine.process(
                paths=raw_layered.path_records,
                mode="layered",
                dimensions=original_dims,
                filter_speckle=self.config.filter_speckle,
                color_tolerance=self.config.color_tolerance,
            )

            def process_layer_paths(layers: List[LayerGroup]) -> Tuple[List[LayerGroup], int, int]:
                orig_count = 0
                opt_count = 0
                new_layers = []
                for layer in layers:
                    new_paths = []
                    for p in layer.paths:
                        d_current = p.path_data

                        # Step A: Circle / Ellipse refitting
                        d_current = refit_path_d(
                            d_current,
                            min_circularity=0.92,
                            min_aspect=0.88,
                            regularize_lines=True,
                            max_deviation=1.0,
                        )

                        # Step B: Rectangle & Centerline Primitive snapping
                        if self.config.refit_primitives:
                            rings = parse_svg_path_to_rings(d_current)
                            if len(rings) == 1:
                                rect_info = detect_and_refit_rectangles(rings[0], tolerance=1.0)
                                if rect_info is not None:
                                    rx_min, ry_min, rw, rh, r_fillet = rect_info
                                    d_current = format_rect_path(rx_min, ry_min, rw, rh, r_fillet)

                        # Step C: Centerline skeletonization for thin lines
                        if self.config.centerline_skeleton:
                            rings = parse_svg_path_to_rings(d_current)
                            if len(rings) == 1:
                                skel = skeletonize_thin_loops_mat(rings[0], max_stroke_width=3.0, min_aspect=8.0)
                                if skel is not None:
                                    d_current = f"M {skel[0][0]:.3f} {skel[0][1]:.3f} " + " ".join(
                                        f"L {pt[0]:.3f} {pt[1]:.3f}" for pt in skel[1:]
                                    )

                        # Step D: Philip J. Schneider Adaptive Bezier Decimation & G1 fairing
                        decimated_d, metrics = decimate_path_nodes(
                            d_current, tolerance=self.config.node_tolerance
                        )
                        orig_count += metrics.original_node_count
                        opt_count += metrics.optimized_node_count

                        new_paths.append(
                            PathRecord(
                                id=p.id,
                                color_hex=p.color_hex,
                                path_data=decimated_d,
                                area=p.area,
                                fill_rule=p.fill_rule,
                            )
                        )
                    new_layers.append(
                        LayerGroup(
                            layer_id=layer.layer_id,
                            label=layer.label,
                            color_hex=layer.color_hex,
                            paths=new_paths,
                            z_index=layer.z_index,
                        )
                    )
                return new_layers, orig_count, opt_count

            cut_ready_layers, cr_orig_nodes, cr_opt_nodes = process_layer_paths(structured_cut_ready.layers)
            layered_layers, lay_orig_nodes, lay_opt_nodes = process_layer_paths(structured_layered.layers)

            # 5. Phase 5: Automated Choke & Spread Trapping
            if self.config.enable_trapping:
                layered_layers = apply_choke_spread_trapping(
                    layered_layers, trap_distance=self.config.trap_distance
                )

            # 6. Phase 6: CAM Toolpath Optimization (Inside-Out Cutting + TSP Rapid Traverse)
            total_traverse_reduction = 0.0
            if self.config.optimize_cam:
                cam_layers = []
                for layer in cut_ready_layers:
                    cam_res = optimize_cam_toolpaths(layer.paths)
                    total_traverse_reduction = max(
                        total_traverse_reduction, cam_res.traverse_reduction_percentage
                    )
                    cam_layers.append(
                        LayerGroup(
                            layer_id=layer.layer_id,
                            label=layer.label,
                            color_hex=layer.color_hex,
                            paths=cam_res.ordered_paths,
                            z_index=layer.z_index,
                        )
                    )
                cut_ready_layers = cam_layers

            # 7. Serialization and Scour optimization
            final_cut_ready_struct = StructuredLayerData(
                mode="cut_ready",
                layers=cut_ready_layers,
                dimensions=original_dims,
            )
            final_layered_struct = StructuredLayerData(
                mode="layered",
                layers=layered_layers,
                dimensions=original_dims,
            )

            cut_ready_opt = self.optimizer.build_and_optimize(
                final_cut_ready_struct, dimensions=original_dims, refit_circles=False
            )
            layered_opt = self.optimizer.build_and_optimize(
                final_layered_struct, dimensions=original_dims, refit_circles=False
            )

            # 8. Export to files if requested
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                with open(os.path.join(output_dir, "cut_ready.svg"), "w", encoding="utf-8") as f:
                    f.write(cut_ready_opt.svg_content)
                with open(os.path.join(output_dir, "layered.svg"), "w", encoding="utf-8") as f:
                    f.write(layered_opt.svg_content)

            node_red_pct = (
                max(0.0, (cr_orig_nodes - cr_opt_nodes) / float(cr_orig_nodes) * 100.0)
                if cr_orig_nodes > 0
                else 0.0
            )

            return PipelineResult(
                svg_content=cut_ready_opt.svg_content,
                cut_ready_svg=cut_ready_opt.svg_content,
                layered_svg=layered_opt.svg_content,
                total_nodes_original=cr_orig_nodes,
                total_nodes_optimized=cr_opt_nodes,
                node_reduction_pct=node_red_pct,
                traverse_reduction_pct=total_traverse_reduction,
                layers_count=len(cut_ready_layers),
                dimensions=original_dims,
                metrics={
                    "cut_ready_original_nodes": cr_orig_nodes,
                    "cut_ready_optimized_nodes": cr_opt_nodes,
                    "cut_ready_reduction_pct": node_red_pct,
                    "layered_original_nodes": lay_orig_nodes,
                    "layered_optimized_nodes": lay_opt_nodes,
                    "layered_reduction_pct": (
                        (lay_orig_nodes - lay_opt_nodes) / float(lay_orig_nodes) * 100.0
                        if lay_orig_nodes > 0
                        else 0.0
                    ),
                    "cut_ready_file_size": cut_ready_opt.file_size,
                    "layered_file_size": layered_opt.file_size,
                },
            )
        finally:
            if temp_input_to_clean and os.path.exists(temp_input_to_clean):
                try:
                    os.remove(temp_input_to_clean)
                except OSError:
                    pass
