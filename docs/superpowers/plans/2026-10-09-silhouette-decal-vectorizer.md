# Silhouette & Decal Vectorizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a dedicated `mode="silhouette"` in the inkmcp vectorizer pipeline that eliminates antialiasing fringe layers and canvas bounding boxes, producing crisp, single-layer cut-ready SVGs for Cricut vinyl cutting, laser mandalas, and CNC routing.

**Architecture:** Adds binary Otsu/adaptive background segmentation and median foreground color extraction to `ImagePreprocessor`, cutout binary contour tracing to `VTracerCore`, polygon hole compound assembly and canvas-box pruning to `TopologyEngine`, and threads `mode="silhouette"` through the operations dispatcher, CLI, and FastMCP server interface.

**Tech Stack:** Python 3.10+, Shapely 2.0+, Pillow (PIL), NumPy, scikit-learn, VTracer, Scour, Inkscape CLI, FastMCP.

**Spec:** [`docs/superpowers/specs/2026-10-09-silhouette-decal-vectorizer-design.md`](file:///s:/Github/inkmcp/docs/superpowers/specs/2026-10-09-silhouette-decal-vectorizer-design.md)

**Execution Waves:**
- **Wave 1 (Parallel - Core Logic & Tracing)**:
  - Task 1: Silhouette Preprocessing & VTracer Core Engine (`inkmcp/vectorizer/preprocessor.py`, `inkmcp/vectorizer/core.py`, `tests/test_vectorizer_preprocessor.py`, `tests/test_vectorizer_core.py`)
  - Task 2: Silhouette Topology & Compound Path Hole Assembly (`inkmcp/vectorizer/topology.py`, `inkmcp/vectorizer/optimizer.py`, `tests/test_vectorizer_topology.py`)
- **Wave 2 (Integration & Interfaces)**:
  - Task 3: Operations Dispatcher, CLI & FastMCP Interface (`inkmcp/inkmcpops/vectorize_operations.py`, `inkmcp/inkscape_mcp_server.py`, `inkmcp/inkmcpcli.py`, `tests/test_vectorize_operations.py`, `tests/test_vectorize_cli.py`)
- **Wave 3 (Verification & Desktop Certification)**:
  - Task 4: Live Filigree Pumpkin Verification & Win32 Desktop Certification (`tests/verify_live_pumpkin_vectorize.py`, desktop HWND capture, full regression suite)

## Global Constraints
- Operating System: Windows (pwsh shell).
- Invariant 51: Live desktop window visibility on `WinSta0\Default` with zero phantom/leaked instances.
- Invariant 53: Zero inline multi-line Python in shell (`python -c "..."`). All test and debug code must be written to `.py` files.
- Invariant 54: Deterministic geometry operations. Zero hardcoded Bezier coordinates.
- Invariant 55: Single-concern task execution. All tests must pass with Exit Code 0.

## Review Focus
1. **Solid Background Image with Subtle Color Noise**: Corner pixels differ slightly across the 4 corners; background estimation must use corner clustering/variance, not a single naive pixel sample. (Tested in Task 1 `test_preprocessor_silhouette_mode_extracts_single_palette`)
2. **Internal Holes Floating Free**: Fine filigree cuts must be preserved as interior rings (`poly.interiors`) within the outer pumpkin envelope, not lost or discarded during unioning. (Tested in Task 2 `test_topology_silhouette_mode_compound_holes`)
3. **Canvas Bounding Box Leak**: The outer rectangular canvas border must be completely pruned and never output as a cutting layer. (Tested in Task 2 `test_topology_silhouette_strips_canvas_box`)
4. **Watermark / Edge Isolation**: Text below the main graphic must either be pruned or isolated cleanly without bridging into the main body. (Tested in Task 2 `test_topology_silhouette_mode_isolates_watermark`)
5. **Cricut & LaserGRBL Fill-Rule Compatibility**: Path elements must have `fill-rule="evenodd"` so cutting software renders interior cutouts as transparent holes without winding order bugs. (Tested in Task 2 `test_optimizer_silhouette_fill_rule_evenodd`)

---

### Task 1: Silhouette Preprocessing & VTracer Core Engine

**Files:**
- Modify: `inkmcp/vectorizer/preprocessor.py:84-189`
- Modify: `inkmcp/vectorizer/core.py:120-180`
- Modify: `tests/test_vectorizer_preprocessor.py`
- Modify: `tests/test_vectorizer_core.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: `ImagePreprocessor.process(image_input, num_colors=8, remove_background=False, mode="cut_ready")` and `VTracerCore.vectorize(image_input, mode="spline", hierarchical="cutout")`
- Produces: `PreprocessedImageData` with `palette=[canonical_fg_hex]`, `color_masks={canonical_fg_hex: mask}`, transparent alpha background for `mode="silhouette"`, and `VTracerCore` binary tracing configuration.

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write failing unit tests in `tests/test_vectorizer_preprocessor.py` and `tests/test_vectorizer_core.py`**
  ```python
  def test_preprocessor_silhouette_mode_extracts_single_palette():
      from inkmcp.vectorizer.preprocessor import ImagePreprocessor
      from PIL import Image, ImageDraw
      
      # Create 100x100 white image with an orange circle
      img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
      draw = ImageDraw.Draw(img)
      draw.ellipse([20, 20, 80, 80], fill=(226, 131, 11, 255))
      
      prep = ImagePreprocessor()
      result = prep.process(img, mode="silhouette")
      
      # Must return exactly 1 foreground color in palette
      assert len(result.palette) == 1
      assert result.palette[0] == "#E2830B"
      assert len(result.color_masks) == 1
      # Alpha channel must be transparent where background was white
      arr = np.array(result.image)
      assert arr[0, 0, 3] == 0
      assert arr[50, 50, 3] == 255

  def test_vtracer_silhouette_binary_cutout_config():
      from inkmcp.vectorizer.core import VTracerCore
      from PIL import Image, ImageDraw
      
      img = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
      draw = ImageDraw.Draw(img)
      draw.rectangle([10, 10, 40, 40], fill=(226, 131, 11, 255))
      
      core = VTracerCore()
      res = core.vectorize(img, hierarchical="cutout", filter_speckle=4)
      assert len(res.paths) >= 1
      assert res.paths[0].color_hex.upper() == "#E2830B"
  ```
- [ ] **Step 2: Run tests to verify failure**
  Run: `pytest tests/test_vectorizer_preprocessor.py::test_preprocessor_silhouette_mode_extracts_single_palette -v`
  Expected: FAIL with `TypeError: process() got an unexpected keyword argument 'mode'`
- [ ] **Step 3: Implement silhouette preprocessing and core configuration**
  - In `inkmcp/vectorizer/preprocessor.py`:
    - Update `process()` to accept `mode: str = "cut_ready"`:
    - If `mode == "silhouette"`:
      - Sample 4 corner pixels `[(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)]`.
      - Calculate Euclidean distance map from corner background.
      - Apply bilateral filter to suppress noise.
      - Compute adaptive threshold: pixels with $\text{distance} > \max(\text{bg\_tolerance}, 25.0)$ become foreground.
      - Extract median RGB of foreground pixels $\to$ `canonical_hex`.
      - Set background alpha to 0 and foreground alpha to 255.
      - Return `PreprocessedImageData(image=cleaned_img, palette=[canonical_hex], color_masks={canonical_hex: mask}, dimensions=(w, h))`.
  - In `inkmcp/vectorizer/core.py`:
    - Ensure `hierarchical="cutout"` and `filter_speckle=4` are defaults for clean silhouette contour extraction.
- [ ] **Step 4: Run tests to verify they pass**
  Run: `pytest tests/test_vectorizer_preprocessor.py tests/test_vectorizer_core.py -v`
  Expected: PASS (all tests pass with Exit Code 0)
- [ ] **Step 5: Commit**
  ```bash
  git add inkmcp/vectorizer/preprocessor.py inkmcp/vectorizer/core.py tests/test_vectorizer_preprocessor.py tests/test_vectorizer_core.py
  git commit -m "feat(preprocessor,core): implement silhouette mode with binary background segmentation and cutout tracing"
  ```

---

### Task 2: Silhouette Topology, Watermark Isolation & Compound Path Hole Assembly

**Files:**
- Modify: `inkmcp/vectorizer/topology.py:70-170`
- Modify: `inkmcp/vectorizer/optimizer.py:40-100`
- Modify: `tests/test_vectorizer_topology.py`
- Modify: `tests/test_vectorizer_optimizer.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: `TopologyEngine.process(paths, mode="silhouette", dimensions=(w, h))`
- Produces: `StructuredLayerData(layers=[layer_01], dimensions=(w, h), mode="silhouette")`, where `layer_01` is a compound polygon with interior holes, full canvas rectangles pruned, and isolated disconnected text elements.

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write failing unit tests in `tests/test_vectorizer_topology.py` and `tests/test_vectorizer_optimizer.py`**
  ```python
  def test_topology_silhouette_mode_compound_holes():
      from inkmcp.vectorizer.topology import TopologyEngine
      from inkmcp.vectorizer.core import PathRecord
      
      # Donut: outer square 10..90, inner hole 30..70
      outer_d = "M 10 10 L 90 10 L 90 90 L 10 90 Z"
      inner_d = "M 30 30 L 70 30 L 70 70 L 30 70 Z"
      paths = [
          PathRecord(path_id="p1", path_data=outer_d, color_hex="#E2830B", area=6400.0),
          PathRecord(path_id="p2", path_data=inner_d, color_hex="#E2830B", area=1600.0),
      ]
      
      engine = TopologyEngine()
      result = engine.process(paths, mode="silhouette", dimensions=(100, 100))
      
      assert result.mode == "silhouette"
      assert len(result.layers) == 1
      assert result.layers[0].layer_id == "layer_01"
      assert result.layers[0].color_hex == "#E2830B"

  def test_topology_silhouette_strips_canvas_box():
      from inkmcp.vectorizer.topology import TopologyEngine
      from inkmcp.vectorizer.core import PathRecord
      
      # 100x100 full canvas box and a 20x20 subject inside
      canvas_d = "M 0 0 L 100 0 L 100 100 L 0 100 Z"
      subject_d = "M 40 40 L 60 40 L 60 60 L 40 60 Z"
      paths = [
          PathRecord(path_id="p0", path_data=canvas_d, color_hex="#FFFFFF", area=10000.0),
          PathRecord(path_id="p1", path_data=subject_d, color_hex="#E2830B", area=400.0),
      ]
      engine = TopologyEngine()
      result = engine.process(paths, mode="silhouette", dimensions=(100, 100))
      # Canvas box must be pruned, leaving only the subject
      assert len(result.layers) == 1
      assert result.layers[0].color_hex == "#E2830B"

  def test_topology_silhouette_mode_isolates_watermark():
      from inkmcp.vectorizer.topology import TopologyEngine
      from inkmcp.vectorizer.core import PathRecord
      from shapely import wkt
      
      # Subject (pumpkin body) at y=20..80 and disconnected watermark text at y=90..95
      subject_d = "M 20 20 L 80 20 L 80 80 L 20 80 Z"
      watermark_d = "M 30 90 L 70 90 L 70 95 L 30 95 Z"
      paths = [
          PathRecord(path_id="p1", path_data=subject_d, color_hex="#E2830B", area=3600.0),
          PathRecord(path_id="p2", path_data=watermark_d, color_hex="#E2830B", area=200.0),
      ]
      engine = TopologyEngine()
      result = engine.process(paths, mode="silhouette", dimensions=(100, 100))
      assert len(result.layers) == 1
      # Must produce separate polygon components without bridging
      geom = engine.paths_to_polygon(result.layers[0].paths)
      assert geom.geom_type in ("MultiPolygon", "GeometryCollection")
      assert len(geom.geoms) == 2

  def test_optimizer_silhouette_fill_rule_evenodd():
      from inkmcp.vectorizer.optimizer import SvgOptimizer
      from inkmcp.vectorizer.topology import StructuredLayerData, LayerGroup
      from inkmcp.vectorizer.core import PathRecord
      
      layer = LayerGroup(
          layer_id="layer_01",
          label="01 - #E2830B",
          z_index=1,
          color_hex="#E2830B",
          paths=[PathRecord(path_id="p1", path_data="M 0 0 L 10 0 L 10 10 Z", color_hex="#E2830B", area=50.0)]
      )
      layer_data = StructuredLayerData(layers=[layer], dimensions=(100, 100), mode="silhouette")
      optimizer = SvgOptimizer()
      svg = optimizer.build_svg(layer_data)
      assert 'fill-rule="evenodd"' in svg
  ```
- [ ] **Step 2: Run tests to verify failure**
  Run: `pytest tests/test_vectorizer_topology.py::test_topology_silhouette_mode_compound_holes -v`
  Expected: FAIL with `ValueError: Unsupported topology mode: silhouette`
- [ ] **Step 3: Implement `mode="silhouette"` in `TopologyEngine` and `fill-rule="evenodd"` in `SvgOptimizer`**
  - In `TopologyEngine.process()`:
    - Allow `mode in ("cut_ready", "layered", "silhouette")`.
    - If `mode == "silhouette"`:
      - Filter out canvas border paths: any path with bounding box within 2px of canvas edges and area $> 0.95 \times (w \times h)$.
      - Combine all foreground geometries via `unary_union` and `make_valid`.
      - Build a single `LayerGroup(layer_id="layer_01", label=f"01 - {color_hex}", z_index=1, color_hex=color_hex, paths=[...])`.
  - In `SvgOptimizer.build_svg()`:
    - Add `fill-rule="evenodd"` attribute to `<path>` tags.
- [ ] **Step 4: Run tests to verify they pass**
  Run: `pytest tests/test_vectorizer_topology.py tests/test_vectorizer_optimizer.py -v`
  Expected: PASS
- [ ] **Step 5: Commit**
  ```bash
  git add inkmcp/vectorizer/topology.py inkmcp/vectorizer/optimizer.py tests/test_vectorizer_topology.py tests/test_vectorizer_optimizer.py
  git commit -m "feat(topology,optimizer): add silhouette compound hole assembly, canvas-box pruning, and fill-rule=evenodd"
  ```

---

### Task 3: Operations Dispatcher, CLI & FastMCP Interface

**Files:**
- Modify: `inkmcp/inkmcpops/vectorize_operations.py:65-155`
- Modify: `inkmcp/inkscape_mcp_server.py:100-150`
- Modify: `inkmcp/inkmcpcli.py:165-215`
- Modify: `tests/test_vectorize_operations.py`
- Modify: `tests/test_vectorize_cli.py`

**Dependencies:**
- Blocked By: Task 1, Task 2
- Parallel Wave: Wave 2

**Interfaces:**
- Consumes: `vectorize_image_operation(params={"mode": "silhouette", ...})`
- Produces: CLI `--mode silhouette` and FastMCP `vectorize_image(mode="silhouette")` endpoints returning valid single-layer fabrication SVGs.

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write failing tests in `tests/test_vectorize_operations.py` and `tests/test_vectorize_cli.py`**
  ```python
  def test_vectorize_operation_silhouette_mode(tmp_path):
      from inkmcp.inkmcpops.vectorize_operations import vectorize_image_operation
      from PIL import Image, ImageDraw
      
      img_path = tmp_path / "test_silhouette.png"
      out_path = tmp_path / "test_silhouette.svg"
      img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
      draw = ImageDraw.Draw(img)
      draw.rectangle([20, 20, 80, 80], fill=(200, 100, 0, 255))
      img.save(img_path)
      
      res = vectorize_image_operation({
          "image_path": str(img_path),
          "output_path": str(out_path),
          "mode": "silhouette",
      })
      assert res["status"] in ("success", "warning")
      assert res["data"]["layer_count"] == 1
  ```
- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_vectorize_operations.py::test_vectorize_operation_silhouette_mode -v`
  Expected: FAIL with invalid mode validation error.
- [ ] **Step 3: Update `vectorize_operations.py`, `inkscape_mcp_server.py`, and `inkmcpcli.py`**
  - Add `"silhouette"` to valid modes `("cut_ready", "layered", "silhouette")`.
  - Pass `mode=mode` to `preprocessor.process` and `topology.process`.
  - Expose `--mode` documentation in CLI parser and FastMCP tool docstrings.
- [ ] **Step 4: Run tests to verify they pass**
  Run: `pytest tests/test_vectorize_operations.py tests/test_vectorize_cli.py -v`
  Expected: PASS
- [ ] **Step 5: Commit**
  ```bash
  git add inkmcp/inkmcpops/vectorize_operations.py inkmcp/inkscape_mcp_server.py inkmcp/inkmcpcli.py tests/test_vectorize_operations.py tests/test_vectorize_cli.py
  git commit -m "feat(ops,cli,server): expose silhouette mode across dispatcher, CLI, and FastMCP"
  ```

---

### Task 4: Live Filigree Pumpkin Verification & Desktop Certification

**Files:**
- Modify: `tests/verify_live_pumpkin_vectorize.py`
- Test: Live Win32 desktop verification on `media_1791565153197_eb484739.png`

**Dependencies:**
- Blocked By: Task 3
- Parallel Wave: Wave 3

**Interfaces:**
- Consumes: `filigree_silhouette.svg`
- Produces: `render_filigree_silhouette.png`, `inkscape_filigree_silhouette_certified.png`, full regression suite pass.

#### Verification Pattern: Desktop Inspection & Full Suite Gate
- [ ] **Step 1: Write standalone verification script `scratch/verify_silhouette_pumpkin.py`**
  - Run `vectorize_image_operation(image_path=..., mode="silhouette", filter_speckle=4.0)`.
  - Assert layer count == 1 (`01 - #E28A1A`).
  - Assert 0 antialiasing fringe layers.
  - Assert 0 canvas bounding box paths.
  - Assert compound polygon contains internal filigree holes.
  - Export headless render via `inkscape.com` to `scratch/render_filigree_silhouette.png`.
- [ ] **Step 2: Run verification script**
  Run: `python scratch/verify_silhouette_pumpkin.py`
  Expected: PASS with Exit Code 0.
- [ ] **Step 3: Load into active Inkscape GUI & capture Win32 desktop screenshot**
  Run: `python launch_interactive.py scratch/filigree_silhouette.svg`
  Run: `python .agents/inspect_desktop_windows.py --process inkscape --screenshot scratch/inkscape_filigree_silhouette_certified.png`
  Verify single window active on `WinSta0\Default`.
- [ ] **Step 4: Copy artifacts to brain directory**
  Copy `filigree_silhouette.svg`, `render_filigree_silhouette.png`, and `inkscape_filigree_silhouette_certified.png` to `<appDataDir>\brain\<conversation-id>/`.
- [ ] **Step 5: Run full regression test suite & linter**
  Run: `pytest tests/ -v`
  Run: `ruff check inkmcp/`
  Expected: All 233+ tests pass with Exit Code 0.
- [ ] **Step 6: Commit**
  ```bash
  git add tests/verify_live_pumpkin_vectorize.py
  git commit -m "test(silhouette): add empirical verification and desktop certification for silhouette mode"
  ```
