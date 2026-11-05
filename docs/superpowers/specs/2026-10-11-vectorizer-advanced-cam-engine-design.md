# Advanced CAM Vectorizer & Node Decimation Engine Specification

## 1. Objective & Scope

Augment the `inkmcp.vectorizer` engine with an enterprise-grade CAM manufacturing and geometric reasoning architecture. The engine transforms raw raster illustrations into ultra-clean, machine-optimized SVGs tailored for CNC routing, laser cutting, drag-knife vinyl cutting, and multi-layer decal assembly.

This specification unifies six foundational modules:
1. **Node Analysis & Decimation Engine (`node_decimator.py`)**: Micro-segment pruning, Schneider's adaptive Bezier curve fitting ($\epsilon \le 0.5\text{px}$), collinear decimation, and $G^1$ tangent fairing to eliminate machine chatter and node bloat.
2. **Automated Choke & Spread Trapping Engine (`trapping.py`)**: Sub-millimeter Shapely polygon buffering ($0.25\text{mm} - 0.5\text{mm}$) for multi-layer vinyl assembly, expanding lighter color fills underneath adjacent darker keylines with zero light leaks.
3. **Geometric Primitive Snapping & Centerline Engine (`primitives.py`)**: Exact `<rect>` and rounded-corner fillet box detection, plus Medial Axis Transform (MAT) centerline skeletonization for thin strokes (e.g. rigging, antenna masts, whiskers) to convert closed-loop double walls into single-stroke CAM cut paths.
4. **Topological Containment DAG (`containment_dag.py`)**: Directed Acyclic Graph of polygon spatial containment for deterministic, mathematically proven z-depth stacking without manual color heuristics.
5. **CAM Toolpath & Traverse Optimization (`cam_planner.py`)**: Inside-out cutting priority (all interior holes cut before the outer boundary separates) and Greedy Nearest-Neighbor / 2-opt TSP rapid traverse minimization.
6. **Unified Pipeline Orchestration (`pipeline.py`)**: Seamless integration of all modules into a production CLI/API with before/after complexity dashboards and SVG layer exports.

---

## 2. Architecture & Data Flow

```
[Raw Raster Input]
        │
        ▼
[Phase 1: Super-Res & Palette Quantization (super_res.py)]
  ├─ 4× Lanczos expansion & bilateral edge-preserving filter
  └─ Discrete palette segmentation at 4096×4096
        │
        ▼
[Phase 2: Spline Contour Extraction (core.py)]
  ├─ High-resolution VTracer spline extraction (Cubic Beziers)
  └─ Coordinate normalization (0.25× scaling back to 1024×1024 viewBox)
        │
        ▼
[Phase 3: Geometric Primitives & Centerline (primitives.py)]
  ├─ Circles & Ellipses (strict 4-arc Bezier gating)
  ├─ Rectangles & Rounded Boxes (rectilinear bounding & corner fillets)
  └─ Centerline Skeletonization (thin closed loops ➔ single-stroke open paths)
        │
        ▼
[Phase 4: Node Analysis & Decimation Engine (node_decimator.py)]
  ├─ Micro-segment culling (L < 0.2px)
  ├─ Ramer-Douglas-Peucker collinear simplification
  ├─ Schneider adaptive cubic Bezier re-fitting (tolerance ε ≤ 0.5px)
  ├─ G¹ tangent fairing (aligning control handles across smooth nodes)
  └─ Node Complexity Metrics calculation (reduction %, density index)
        │
        ▼
[Phase 5: Trapping & Containment DAG (trapping.py & containment_dag.py)]
  ├─ Spatial containment DAG construction (A ⊂ B ⊂ C)
  ├─ Infallible topological z-order assignment
  └─ Configurable choke/spread buffering (0.3mm underlap for vinyl registration)
        │
        ▼
[Phase 6: CAM Toolpath Optimization & Serialization (cam_planner.py)]
  ├─ Inside-out cut sequencing (interior holes cut before outer boundary)
  ├─ TSP rapid traverse path reordering (minimizes cutting head travel)
  └─ Scour optimization & dual SVG export (Planar Cut-Ready & Layered Assembly)
```

---

## 3. Module Specifications & Interfaces

### 3.1 Node Analysis & Decimation Engine (`inkmcp/vectorizer/node_decimator.py`)
- **Functions**:
  - `prune_micro_segments(d_str: str, min_length: float = 0.2) -> str`: Removes redundant zero-length or sub-pixel moves.
  - `fit_cubic_beziers_schneider(points: List[Tuple[float, float]], max_error: float = 0.5) -> List[Tuple]`: Fits minimal cubic Bezier curves to a sequence of digitized points using Philip J. Schneider's algorithm (Graphics Gems, 1990).
  - `fair_tangents_g1(d_str: str, max_angle_deviation_deg: float = 15.0) -> str`: Collinearizes control handles across smooth anchor points to guarantee $G^1$ continuous tangents.
  - `decimate_path_nodes(d_str: str, tolerance: float = 0.5) -> Tuple[str, NodeMetrics]`: End-to-end decimation returning optimized path data and node reduction statistics.
- **Data Model**:
  ```python
  @dataclass
  class NodeMetrics:
      original_node_count: int
      optimized_node_count: int
      reduction_percentage: float
      max_geometric_deviation: float
      estimated_cut_time_reduction_pct: float
  ```

### 3.2 Automated Choke & Spread Trapping Engine (`inkmcp/vectorizer/trapping.py`)
- **Functions**:
  - `compute_color_luminance(hex_color: str) -> float`: Calculates relative luminance ($0.299R + 0.587G + 0.114B$).
  - `apply_choke_spread_trapping(layers: List[LayerGroup], trap_distance: float = 1.13) -> List[LayerGroup]`:
    - For each pair of adjoining polygons $P_A$ (lighter) and $P_B$ (darker):
    - Computes shared boundary line $L_{AB} = \partial P_A \cap \partial P_B$.
    - Buffers lighter polygon $P_A$ into $P_B$ by `trap_distance` (default $1.13\text{px} \approx 0.3\text{mm}$ at 96 DPI).
    - Preserves exact outer boundary of the top-most keylines.

### 3.3 Geometric Primitive Snapping & Centerline Engine (`inkmcp/vectorizer/primitives.py`)
- **Functions**:
  - `detect_and_refit_rectangles(ring: List[Tuple[float, float]], tolerance: float = 1.0) -> Optional[Tuple[float, float, float, float, float]]`: Detects rectilinear bounds `(minx, miny, width, height, corner_radius)`.
  - `skeletonize_thin_loops_mat(ring: List[Tuple[float, float]], max_stroke_width: float = 3.0, min_aspect: float = 8.0) -> Optional[List[Tuple[float, float]]]`: Computes medial axis skeleton of thin elongated loops, returning an open polyline/spline for centerline stroke cutting.

### 3.4 Topological Containment DAG (`inkmcp/vectorizer/containment_dag.py`)
- **Functions**:
  - `build_containment_dag(polygons: List[Tuple[str, Polygon]]) -> nx.DiGraph`: Builds a directed acyclic graph where edge $(A, B)$ indicates polygon $A$ is topologically enclosed by polygon $B$.
  - `resolve_stacking_order(dag: nx.DiGraph) -> List[str]`: Performs topological sort to determine physical stacking hierarchy from largest enclosing background to smallest nested foreground accents.

### 3.5 CAM Toolpath & Traverse Optimization (`inkmcp/vectorizer/cam_planner.py`)
- **Functions**:
  - `order_inside_out_cuts(paths: List[PathRecord]) -> List[PathRecord]`: Ensures all interior aperture cuts precede the outer boundary separation cut for each physical piece.
  - `optimize_traverse_tsp(paths: List[PathRecord]) -> List[PathRecord]`: Orders cutting sequences using greedy nearest-neighbor and 2-opt heuristics on start/end coordinates to minimize rapid travel head repositioning.

---

## 4. Verification & Testing Strategy
- **Unit Test Coverage**: Dedicated test files in `tests/`:
  - `tests/test_node_decimator.py`: Schneider curve fitting, micro-segment pruning, node reduction assertions.
  - `tests/test_trapping.py`: Polygon buffering, luminance choke/spread assertions.
  - `tests/test_primitives_extended.py`: Rectangles, corner fillets, centerline skeletonization.
  - `tests/test_containment_dag.py`: Containment graph construction, topological sorting.
  - `tests/test_cam_planner.py`: Inside-out ordering, TSP traverse distance reduction.
- **Empirical Manufacturing Benchmarks**:
  - Run the enhanced pipeline on [`input_raster_boat.png`](file:///C:/Users/jmolina/.gemini/antigravity/brain/796a0142-0b18-4bb3-9442-297ec4c2fb06/input_raster_boat.png), [`Logo.png`](file:///C:/Users/jmolina/OneDrive%20-%20ROBERTO%20CLEMENTE%20CHARTER%20SCHOOL/Desktop/Logo.png), and [`Phishy.svg`](file:///C:/Users/jmolina/OneDrive%20-%20ROBERTO%20CLEMENTE%20CHARTER%20SCHOOL/Desktop/Phishy.svg).
  - Verify node count reduction $> 50\%$ while maintaining $\text{MAE} < 3.0 / 255$.
