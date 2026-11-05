# Advanced CAM Vectorizer & Node Decimation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-grade CAM vectorization and node decimation engine with automated trapping, primitive/centerline snapping, topological containment stacking, and toolpath optimization.

**Architecture:** A modular 6-stage pipeline that ingests super-resolved contours, applies Schneider's adaptive Bezier fitting and $G^1$ tangent fairing to eliminate node bloat, generates sub-millimeter choke/spread underlaps for vinyl registration, snags rectilinear/centerline primitives, builds a spatial containment DAG for deterministic z-ordering, and sequences CAM toolpaths inside-out with TSP traverse minimization.

**Tech Stack:** Python 3.13, Shapely (geometry/buffering), OpenCV (skeletonization/super-res), NetworkX (containment DAG), NumPy, Scour (SVG optimization), pytest.

**Spec:** [`docs/superpowers/specs/2026-10-11-vectorizer-advanced-cam-engine-design.md`](file:///s:/Github/inkmcp/docs/superpowers/specs/2026-10-11-vectorizer-advanced-cam-engine-design.md)

**Execution Waves:**
- **Wave 1 (Parallel - Disjoint Core Modules)**:
  - Task 1: Node Analysis & Decimation Engine (`inkmcp/vectorizer/node_decimator.py`)
  - Task 2: Automated Choke & Spread Trapping Engine (`inkmcp/vectorizer/trapping.py`)
- **Wave 2 (Parallel - Geometric & Topological Engines)**:
  - Task 3: Geometric Primitive Extension & Centerline Skeleton Engine (`inkmcp/vectorizer/primitives.py`)
  - Task 4: Topological Containment DAG & Automated Z-Stacking (`inkmcp/vectorizer/containment_dag.py`)
- **Wave 3 (Sequential - CAM Toolpath & Master Integration)**:
  - Task 5: CAM Toolpath Optimization & Cut Sequencing (`inkmcp/vectorizer/cam_planner.py`)
  - Task 6: Master Pipeline Orchestration & End-to-End Manufacturing Benchmarks (`inkmcp/vectorizer/pipeline.py`)

## Global Constraints
- All path coordinates must maintain exact SVG viewBox alignment with floating-point precision formatted via `_format_coord`.
- Node decimation must enforce a strict geometric error threshold ($\le 0.5\text{px}$) to guarantee zero visual drift ($MAE \Delta < 0.05$).
- Shell commands run in Windows `pwsh` (PowerShell); single quotes are literal, zero inline multi-line Python.
- All temporary scratch debug files must be placed in `scratch/` and removed per Invariant 13 upon task completion.

## Review Focus
1. **Node Decimation Stability**: High-curvature cusps ($> 45^\circ$) must never be smoothed or rounded by Schneider fitting.
2. **Trapping Boundary Conservation**: Spread operations must never bleed past the external silhouette of the outer keyline.
3. **Single-Stroke Centerline Integrity**: Centerline skeletonization must only apply to high-aspect open elements ($L/W > 8$), never to thick filled shapes.
4. **DAG Cycle Prevention**: The containment graph must strictly be acyclic; self-intersections or touching rings must be cleanly disambiguated.
5. **CAM Cut Order Invariant**: Interior holes must always be cut strictly prior to the surrounding exterior boundary contour.

---

### Task 1: Node Analysis & Decimation Engine

**Files:**
- Create: `inkmcp/vectorizer/node_decimator.py`
- Test: `tests/test_node_decimator.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: Raw SVG path string `d_str`, tolerance `max_error = 0.5`
- Produces: `decimate_path_nodes(d_str, tolerance) -> Tuple[str, NodeMetrics]`

#### Steps:
- [ ] **Step 1: Write failing tests for micro-pruning, Schneider curve fitting, and G¹ fairing**
  Create `tests/test_node_decimator.py` testing:
  - `test_prune_micro_segments`: Verifies segments with length $< 0.2\text{px}$ are removed without altering closed path topology.
  - `test_fit_cubic_beziers_schneider`: Verifies 20 densely sampled points along a known cubic Bezier arc are reduced to 1 or 2 cubic Bezier segments within $0.5\text{px}$ error.
  - `test_fair_tangents_g1`: Verifies that adjacent Bezier control handles at a smooth knot are made collinear while preserving the anchor point coordinate.
  - `test_decimate_path_nodes`: Verifies end-to-end node count reduction $> 50\%$ on a bloated circle/wave path.

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_node_decimator.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.vectorizer.node_decimator'`

- [ ] **Step 3: Implement `node_decimator.py`**
  Implement:
  - `prune_micro_segments(d_str, min_length=0.2)`
  - Philip J. Schneider's algorithm for fitting digitized curves to cubic Beziers (`fit_curve`, `generate_bezier`, `reparameterize`, `compute_max_error`).
  - `fair_tangents_g1(d_str, max_angle_deviation_deg=15.0)`
  - `decimate_path_nodes(d_str, tolerance=0.5) -> Tuple[str, NodeMetrics]`

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_node_decimator.py -v`
  Expected: PASS (4/4 tests passed)

- [ ] **Step 5: Commit**
  Run: `git add inkmcp/vectorizer/node_decimator.py tests/test_node_decimator.py`
  `git commit -m "feat(vectorizer): implement node analysis and Schneider Bezier decimation engine"`

---

### Task 2: Automated Choke & Spread Trapping Engine

**Files:**
- Create: `inkmcp/vectorizer/trapping.py`
- Test: `tests/test_trapping.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: List of `LayerGroup` instances, `trap_distance` (default $1.13\text{px} \approx 0.3\text{mm}$)
- Produces: `apply_choke_spread_trapping(layers, trap_distance) -> List[LayerGroup]`

#### Steps:
- [ ] **Step 1: Write failing tests for luminance and polygon trapping**
  Create `tests/test_trapping.py` testing:
  - `test_compute_color_luminance`: Correctly orders yellow ($L \approx 0.8$) > red ($L \approx 0.4$) > navy ($L \approx 0.1$).
  - `test_apply_choke_spread_trapping_overlap`: Verifies that two adjoining rectangular polygons (e.g. yellow and navy) produce an overlap where the lighter yellow expands underneath the navy by `trap_distance`.
  - `test_trapping_preserves_outer_silhouette`: Verifies the outer perimeter of the design is never expanded beyond the original boundary.

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_trapping.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.vectorizer.trapping'`

- [ ] **Step 3: Implement `trapping.py`**
  Implement:
  - `compute_color_luminance(hex_str)`
  - Pairwise polygon adjacency detection using Shapely `intersection(buffer(0.1))`.
  - Directional buffer expansion: lighter polygon buffered into darker neighbor.
  - Conversion back to clean SVG path data rings via `_format_coord`.

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_trapping.py -v`
  Expected: PASS (3/3 tests passed)

- [ ] **Step 5: Commit**
  Run: `git add inkmcp/vectorizer/trapping.py tests/test_trapping.py`
  `git commit -m "feat(vectorizer): implement automated choke and spread trapping engine"`

---

### Task 3: Geometric Primitive Extension & Centerline Skeleton Engine

**Files:**
- Create: `inkmcp/vectorizer/primitives.py`
- Test: `tests/test_primitives_extended.py`

**Dependencies:**
- Blocked By: Task 1
- Parallel Wave: Wave 2

**Interfaces:**
- Consumes: Polygon coordinates / subpaths
- Produces: `detect_and_refit_rectangles(ring, tolerance) -> Optional[Tuple]`, `skeletonize_thin_loops_mat(ring, max_stroke_width) -> Optional[List[Tuple]]`

#### Steps:
- [ ] **Step 1: Write failing tests for rectangle snapping and centerline skeletonization**
  Create `tests/test_primitives_extended.py` testing:
  - `test_detect_and_refit_rectangles`: Snaps a slightly rotated or jittery 4-corner box into an exact `<rect>` path.
  - `test_detect_rounded_rect_with_fillets`: Detects uniform corner radii on rounded boxes.
  - `test_skeletonize_thin_loops_mat`: Converts a 2px wide, 50px long closed loop (like a rigging rope) into a single 1-stroke centerline polyline.

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_primitives_extended.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.vectorizer.primitives'`

- [ ] **Step 3: Implement `primitives.py`**
  Implement:
  - `detect_and_refit_rectangles` using minimum rotated bounding box and corner angle deviations.
  - Corner fillet radius estimation.
  - Medial Axis Transform skeleton extraction using distance transform and thinning on rasterized micro-masks.

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_primitives_extended.py -v`
  Expected: PASS (3/3 tests passed)

- [ ] **Step 5: Commit**
  Run: `git add inkmcp/vectorizer/primitives.py tests/test_primitives_extended.py`
  `git commit -m "feat(vectorizer): implement extended geometric primitives and centerline skeleton engine"`

---

### Task 4: Topological Containment DAG & Automated Z-Stacking

**Files:**
- Create: `inkmcp/vectorizer/containment_dag.py`
- Test: `tests/test_containment_dag.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 2

**Interfaces:**
- Consumes: List of `(path_id, Polygon)` tuples
- Produces: `build_containment_dag(polys) -> nx.DiGraph`, `resolve_stacking_order(dag) -> List[str]`

#### Steps:
- [ ] **Step 1: Write failing tests for containment graph and topological sort**
  Create `tests/test_containment_dag.py` testing:
  - `test_build_containment_dag_nested_circles`: Verifies pupil $\subset$ iris $\subset$ eyeball creates directed edges eyeball $\to$ iris $\to$ pupil.
  - `test_resolve_stacking_order`: Verifies topological sort outputs base plate first, followed by successive interior layers.
  - `test_containment_dag_disjoint_islands`: Verifies multiple unconnected shapes are cleanly partitioned into independent components.

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_containment_dag.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.vectorizer.containment_dag'`

- [ ] **Step 3: Implement `containment_dag.py`**
  Implement:
  - `build_containment_dag` using Shapely `contains` and `within` with bounding box spatial indexing.
  - `resolve_stacking_order` using NetworkX topological sorting with area-based tie breaking.

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_containment_dag.py -v`
  Expected: PASS (3/3 tests passed)

- [ ] **Step 5: Commit**
  Run: `git add inkmcp/vectorizer/containment_dag.py tests/test_containment_dag.py`
  `git commit -m "feat(vectorizer): implement topological containment DAG for automated z-stacking"`

---

### Task 5: CAM Toolpath Optimization & Cut Sequencing

**Files:**
- Create: `inkmcp/vectorizer/cam_planner.py`
- Test: `tests/test_cam_planner.py`

**Dependencies:**
- Blocked By: Task 4
- Parallel Wave: Wave 3

**Interfaces:**
- Consumes: List of `PathRecord` instances
- Produces: `optimize_cam_toolpaths(paths) -> CamPlanResult`

#### Steps:
- [ ] **Step 1: Write failing tests for inside-out cut ordering and TSP traverse**
  Create `tests/test_cam_planner.py` testing:
  - `test_order_inside_out_cuts`: Verifies that an interior hole inside a donut is sequenced before the outer donut boundary.
  - `test_optimize_traverse_tsp`: Verifies that greedy nearest-neighbor reordering reduces total rapid traverse distance by $\ge 30\%$ compared to arbitrary ordering.

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_cam_planner.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.vectorizer.cam_planner'`

- [ ] **Step 3: Implement `cam_planner.py`**
  Implement:
  - `order_inside_out_cuts` using containment tree depth.
  - `optimize_traverse_tsp` computing start/end point Euclidean distance matrix and applying 2-opt trajectory optimization.

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_cam_planner.py -v`
  Expected: PASS (2/2 tests passed)

- [ ] **Step 5: Commit**
  Run: `git add inkmcp/vectorizer/cam_planner.py tests/test_cam_planner.py`
  `git commit -m "feat(vectorizer): implement CAM inside-out cut ordering and TSP traverse optimizer"`

---

### Task 6: Master Pipeline Orchestration & End-to-End Manufacturing Benchmarks

**Files:**
- Create: `inkmcp/vectorizer/pipeline.py`
- Modify: `inkmcp/vectorizer/__init__.py`
- Test: `tests/test_vectorizer_pipeline.py`

**Dependencies:**
- Blocked By: Tasks 1, 2, 3, 4, 5
- Parallel Wave: Wave 3

**Interfaces:**
- Consumes: Input raster path, output SVG directory, configuration options
- Produces: Complete Planar Cut-Ready and Layered Assembly SVGs with CAM toolpath metadata and Node Complexity Reports.

#### Steps:
- [ ] **Step 1: Write integration test for master pipeline**
  Create `tests/test_vectorizer_pipeline.py` verifying full execution from raster to cut-ready SVG with node decimation and trapping applied.
- [ ] **Step 2: Implement `pipeline.py`**
  Wire all 6 modules into `VectorizationPipeline.run()`.
- [ ] **Step 3: Run full pytest suite**
  Run: `pytest -q`
  Expected: 100% pass across all test modules.
- [ ] **Step 4: Execute on production assets (`boat`, `logo`, `phishy`)**
  Generate production vectors, record node decimation metrics ($> 50\%$ reduction), and verify zero visual drift.
- [ ] **Step 5: Clean up scratch files and publish final benchmark report**
  Remove temporary scratch scripts and update documentation.
- [ ] **Step 6: Commit**
  Run: `git add inkmcp/vectorizer/ tests/`
  `git commit -m "feat(vectorizer): integrate master CAM pipeline with node decimation and trapping"`
