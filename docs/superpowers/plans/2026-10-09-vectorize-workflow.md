# Flat-to-Production Vector Conversion Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an end-to-end automated raster-to-vector conversion subsystem in `inkmcp` supporting both cut-ready planar mosaic tiles (for vinyl/HTV) and layered cumulative silhouettes (for laser mandalas), with direct live Inkscape canvas injection and CLI/MCP interfaces.

**Architecture:** A modular pipeline under `inkmcp/vectorizer/` composed of `ImagePreprocessor` (denoising, alpha isolation, K-Means palette reduction), `VTracerCore` (Rust-compiled spline fitting with speckle filtering), `TopologyEngine` (planar boolean slicing vs cumulative silhouette stacking), and `SvgOptimizer` (Inkscape layer DOM structuring and Scour optimization), exposed via `VectorizeOperations`, `inkmcpcli.py`, and `inkscape_mcp_server.py`.

**Tech Stack:** Python 3.13, Pillow, vtracer 0.6.15, Shapely 2.1.2, Scikit-learn (K-Means), Scour 0.37, Pytest, Inkscape 1.4.4.

**Spec:** `docs/superpowers/specs/2026-10-09-vectorize-workflow-design.md`

**Execution Waves:**
- **Wave 1 (Parallel - Foundation Engines)**:
  - Task 1: Image Preprocessor & Color Quantization Engine (`inkmcp/vectorizer/preprocessor.py`)
  - Task 2: VTracer Core Vectorizer Adapter (`inkmcp/vectorizer/core.py`)
- **Wave 2 (Sequential - Topology Processing)**:
  - Task 3: Topology Engine: `cut_ready` vs `layered` Modes (`inkmcp/vectorizer/topology.py`)
- **Wave 3 (Sequential - SVG Scaffolding & Optimization)**:
  - Task 4: SVG Layer Builder & Scour Optimizer (`inkmcp/vectorizer/optimizer.py`)
- **Wave 4 (Sequential - Operations Layer)**:
  - Task 5: Vectorize Operations Dispatcher & Live Injection (`inkmcp/inkmcpops/vectorize_operations.py`)
- **Wave 5 (Sequential - System Interfaces)**:
  - Task 6: CLI & FastMCP Server Exposure (`inkmcp/inkmcpcli.py`, `inkmcp/inkscape_mcp_server.py`)
- **Wave 6 (Live Empirical Verification)**:
  - Task 7: Live Pumpkin Vectorization & Inkscape Desktop Certification

## Global Constraints

- **Python Runtime**: Python 3.13.15 64-bit on Windows.
- **PowerShell & Escaping**: Adhere strictly to Invariant 53 (zero inline multi-line python, backtick escape, double quote escaping `""` or ``` `" ```).
- **Subagent Granularity**: Adhere strictly to Invariant 55 (single-concern subagents, no multi-stage sequential checklists, concurrent test swarms).
- **Deterministic Math**: Adhere strictly to Invariant 54 (zero manual/hallucinated Bézier coordinate strings; all vector paths must come from deterministic contour extraction and boolean math).
- **Inkscape 1.4 CLI Compatibility**: External process calls requiring timeouts must use `subprocess.run(creationflags=0x08000000)` instead of `inkex.command.call(timeout=...)` per Invariant/Pattern PRJ-002.

## Review Focus

1. **Solid Background Handling**: When input image is a JPEG or opaque PNG without alpha transparency, automatically detect and isolate or strip solid canvas background (e.g. pure white `#ffffff`) when `remove_background=True` is requested. Tested in Task 1 (`test_preprocessor_solid_background_removal`).
2. **Degenerate / Self-Intersecting Polygons**: Contour extraction from complex art may yield self-intersecting or invalid polygons; apply `shapely.make_valid()` and area filtering ($< \text{filter\_speckle}$) to prevent cutting blade stalls. Tested in Task 3 (`test_topology_heals_invalid_polygons`).
3. **Inkscape Headless / Offline Fallback**: If `inject_to_inkscape=True` but the GUI is not running or backend fails, gracefully fall back to writing the SVG to disk without raising an unhandled exception. Tested in Task 5 (`test_vectorize_operation_offline_inkscape_fallback`).
4. **Color Bounds Validation**: Guard against out-of-range palette counts ($2 \le \text{num\_colors} \le 32$) with clean user-facing error messages. Tested in Task 1 (`test_preprocessor_color_bounds_validation`).
5. **Windows Path Quoting**: Handle spaces and special characters in input and output file paths cleanly across all OS calls. Tested in Task 6 (`test_cli_vectorize_paths_with_spaces`).

---

### Task 1: Image Preprocessor & Color Quantization Engine

**Files:**
- Create: `inkmcp/vectorizer/__init__.py`
- Create: `inkmcp/vectorizer/preprocessor.py`
- Create: `tests/test_vectorizer_preprocessor.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: Raw image path or `PIL.Image.Image` object, `num_colors: int = 8`, `remove_background: bool = False`.
- Produces: `PreprocessedImageData` dataclass:
  - `image`: Cleaned `PIL.Image.Image` (RGBA)
  - `palette`: List of hex strings (e.g. `["#2A1810", "#FFA733", ...]`)
  - `color_masks`: Dict mapping hex color to binary mask `PIL.Image.Image` (1-bit mode "1" or grayscale "L")
  - `dimensions`: Tuple `(width, height)`

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write the failing test**

```python
# tests/test_vectorizer_preprocessor.py
import pytest
from PIL import Image, ImageDraw
from inkmcp.vectorizer.preprocessor import ImagePreprocessor

def test_preprocessor_palette_and_masks(tmp_path):
    img_path = tmp_path / "test.png"
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 50, 50], fill=(255, 165, 0, 255))
    draw.rectangle([60, 60, 90, 90], fill=(0, 128, 0, 255))
    img.save(img_path)

    preprocessor = ImagePreprocessor()
    result = preprocessor.process(str(img_path), num_colors=2)
    assert len(result.palette) == 2
    assert result.dimensions == (100, 100)
    for color in result.palette:
        assert color in result.color_masks
        mask = result.color_masks[color]
        assert mask.size == (100, 100)

def test_preprocessor_solid_background_removal(tmp_path):
    # Review Focus 1: Solid background JPEG/PNG
    img_path = tmp_path / "solid_bg.png"
    img = Image.new("RGB", (100, 100), (255, 255, 255)) # Pure white background
    draw = ImageDraw.Draw(img)
    draw.ellipse([20, 20, 80, 80], fill=(255, 100, 0))   # Orange circle
    img.save(img_path)

    preprocessor = ImagePreprocessor()
    result = preprocessor.process(str(img_path), num_colors=2, remove_background=True)
    # Check that white background was converted to transparent alpha
    assert result.image.mode == "RGBA"
    corner_pixel = result.image.getpixel((0, 0))
    assert corner_pixel[3] == 0 # Alpha must be transparent

def test_preprocessor_color_bounds_validation(tmp_path):
    # Review Focus 4: Color bounds validation
    img_path = tmp_path / "bounds.png"
    img = Image.new("RGBA", (50, 50), (255, 0, 0, 255))
    img.save(img_path)

    preprocessor = ImagePreprocessor()
    with pytest.raises(ValueError, match="num_colors must be between 2 and 32"):
        preprocessor.process(str(img_path), num_colors=1)
    with pytest.raises(ValueError, match="num_colors must be between 2 and 32"):
        preprocessor.process(str(img_path), num_colors=35)
```

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_vectorizer_preprocessor.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.vectorizer'`

- [ ] **Step 3: Implement ImagePreprocessor**
  Create `inkmcp/vectorizer/__init__.py` and `inkmcp/vectorizer/preprocessor.py` implementing:
  - Transparent alpha isolation.
  - Optional `remove_background=True` corner-flood / color thresholding.
  - Bilateral filter smoothing (`scipy.ndimage` / `cv2` / `PIL.ImageFilter.SMOOTH_MORE`).
  - K-Means palette reduction using `sklearn.cluster.KMeans` or PIL adaptive quantization.
  - Strict $2 \le \text{num\_colors} \le 32$ validation.

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_vectorizer_preprocessor.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  `git add inkmcp/vectorizer/__init__.py inkmcp/vectorizer/preprocessor.py tests/test_vectorizer_preprocessor.py`
  `git commit -m "feat(vectorizer): implement ImagePreprocessor with bilateral filtering and palette extraction"`

---

### Task 2: VTracer Core Vectorizer Adapter

**Files:**
- Create: `inkmcp/vectorizer/core.py`
- Create: `tests/test_vectorizer_core.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: Image file path or buffer, `colormode: str = "color"`, `filter_speckle: int = 4`, `corner_threshold: int = 60`, `segment_length: int = 4`, `mode: str = "spline"`.
- Produces: `RawVectorResult` dataclass:
  - `svg_string`: Raw SVG string generated by vtracer
  - `path_records`: List of `PathRecord` dataclasses (`id: str`, `color_hex: str`, `path_data: str`, `area: float`)

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write the failing test**

```python
# tests/test_vectorizer_core.py
import pytest
from PIL import Image, ImageDraw
from inkmcp.vectorizer.core import VTracerCore

def test_vtracer_vectorization(tmp_path):
    img_path = tmp_path / "square.png"
    img = Image.new("RGBA", (80, 80), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 60, 60], fill=(255, 0, 0, 255))
    img.save(img_path)

    core = VTracerCore()
    result = core.vectorize(
        str(img_path),
        colormode="color",
        filter_speckle=4,
        corner_threshold=60,
        segment_length=4
    )
    assert "<svg" in result.svg_string
    assert len(result.path_records) >= 1
    assert any("rgb(255" in p.color_hex or "#ff0000" in p.color_hex.lower() for p in result.path_records)
    for p in result.path_records:
        assert p.area > 0
        assert p.path_data.startswith("M")
```

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_vectorizer_core.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.vectorizer.core'`

- [ ] **Step 3: Implement VTracerCore**
  Create `inkmcp/vectorizer/core.py` wrapping `vtracer.convert_image_to_svg_py` with XML/SVG path extraction, `segment_length` tuning, color hex normalization, and path area parsing.

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_vectorizer_core.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  `git add inkmcp/vectorizer/core.py tests/test_vectorizer_core.py`
  `git commit -m "feat(vectorizer): implement VTracerCore adapter for high-speed curve and contour fitting"`

---

### Task 3: Topology Engine (`cut_ready` vs `layered` Modes)

**Files:**
- Create: `inkmcp/vectorizer/topology.py`
- Create: `tests/test_vectorizer_topology.py`

**Dependencies:**
- Blocked By: Task 1, Task 2
- Parallel Wave: Wave 2

**Interfaces:**
- Consumes: `RawVectorResult` from Task 2, `PreprocessedImageData` from Task 1, and `mode: str` (`"cut_ready"` | `"layered"`).
- Produces: `StructuredLayerData` dataclass:
  - `mode`: `"cut_ready"` | `"layered"`
  - `layers`: List of `LayerGroup` dataclasses (`layer_id: str`, `label: str`, `color_hex: str`, `paths: List[PathRecord]`, `z_index: int`)
  - Ensures every path is tagged with an explicit, deterministic element ID (e.g. `layer01_path05`).

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write the failing test**

```python
# tests/test_vectorizer_topology.py
import pytest
from shapely.geometry import box
from shapely import to_wkt
from inkmcp.vectorizer.topology import TopologyEngine
from inkmcp.vectorizer.core import PathRecord

def test_cut_ready_zero_overlap():
    engine = TopologyEngine()
    # Path 1: Red box [0, 0, 10, 10]
    p1 = PathRecord(id="p1", color_hex="#ff0000", path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z", area=100.0)
    # Path 2: Blue box overlapping [5, 0, 15, 10]
    p2 = PathRecord(id="p2", color_hex="#0000ff", path_data="M 5 0 L 15 0 L 15 10 L 5 10 Z", area=100.0)

    structured = engine.process([p1, p2], mode="cut_ready")
    assert structured.mode == "cut_ready"
    assert len(structured.layers) == 2
    # In cut_ready mode, paths must have deterministic IDs
    for layer in structured.layers:
        for path in layer.paths:
            assert path.id.startswith("layer")
    # Verify zero overlap between layer 0 and layer 1
    poly0 = engine.paths_to_polygon(structured.layers[0].paths)
    poly1 = engine.paths_to_polygon(structured.layers[1].paths)
    intersection = poly0.intersection(poly1)
    assert intersection.area < 1e-4

def test_layered_mandala_solid_backing():
    engine = TopologyEngine()
    p1 = PathRecord(id="p1", color_hex="#ff0000", path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z", area=100.0)
    p2 = PathRecord(id="p2", color_hex="#00ff00", path_data="M 2 2 L 8 2 L 8 8 L 2 8 Z", area=36.0)

    structured = engine.process([p1, p2], mode="layered")
    assert structured.mode == "layered"
    # Layer 0 must be the solid base silhouette backing
    base_layer = structured.layers[0]
    assert "Base Silhouette" in base_layer.label or "00_base" in base_layer.layer_id
    base_poly = engine.paths_to_polygon(base_layer.paths)
    assert base_poly.area >= 100.0

def test_topology_heals_invalid_polygons():
    # Review Focus 2: Degenerate / self-intersecting polygon healing
    engine = TopologyEngine()
    # Figure-8 self-intersecting polygon
    p_invalid = PathRecord(id="p_inv", color_hex="#ff0000", path_data="M 0 0 L 10 10 L 10 0 L 0 10 Z", area=50.0)
    structured = engine.process([p_invalid], mode="cut_ready")
    assert len(structured.layers) >= 1
    poly = engine.paths_to_polygon(structured.layers[0].paths)
    assert poly.is_valid
```

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_vectorizer_topology.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.vectorizer.topology'`

- [ ] **Step 3: Implement TopologyEngine**
  Create `inkmcp/vectorizer/topology.py` using `shapely` for planar boolean difference (`cut_ready`) and unioned silhouette backing (`layered`). Enforce deterministic naming: `layer{z_index:02d}_path{path_index:02d}`.

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_vectorizer_topology.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  `git add inkmcp/vectorizer/topology.py tests/test_vectorizer_topology.py`
  `git commit -m "feat(vectorizer): implement TopologyEngine with cut_ready and layered laser mandala modes"`

---

### Task 4: SVG Layer Builder & Scour Optimizer

**Files:**
- Create: `inkmcp/vectorizer/optimizer.py`
- Create: `tests/test_vectorizer_optimizer.py`

**Dependencies:**
- Blocked By: Task 3
- Parallel Wave: Wave 3

**Interfaces:**
- Consumes: `StructuredLayerData` from Task 3 and image dimensions `(width, height)`.
- Produces: `OptimizedSvgResult`:
  - `svg_content`: Clean XML string containing `<g inkscape:groupmode="layer">` tags, valid viewBox, and Scour-sanitized coordinates.
  - `layer_count`: Total number of layers
  - `total_nodes`: Cumulative path node count
  - `file_size`: Byte count

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write the failing test**

```python
# tests/test_vectorizer_optimizer.py
import pytest
from inkmcp.vectorizer.optimizer import SvgOptimizer
from inkmcp.vectorizer.topology import StructuredLayerData, LayerGroup
from inkmcp.vectorizer.core import PathRecord

def test_svg_optimizer_layer_structure():
    optimizer = SvgOptimizer()
    layer1 = LayerGroup(
        layer_id="layer01_base",
        label="01 - Base Orange (#FFA500)",
        color_hex="#FFA500",
        paths=[PathRecord(id="layer01_path01", color_hex="#FFA500", path_data="M 10 10 L 50 10 L 50 50 Z", area=800.0)],
        z_index=0
    )
    layer_data = StructuredLayerData(mode="cut_ready", layers=[layer1])
    result = optimizer.build_and_optimize(layer_data, dimensions=(200, 200))

    assert "<svg" in result.svg_content
    assert 'viewBox="0 0 200 200"' in result.svg_content
    assert 'inkscape:groupmode="layer"' in result.svg_content
    assert 'inkscape:label="01 - Base Orange (#FFA500)"' in result.svg_content
    assert 'id="layer01_path01"' in result.svg_content
    assert result.layer_count == 1
    assert result.file_size > 0
```

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_vectorizer_optimizer.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.vectorizer.optimizer'`

- [ ] **Step 3: Implement SvgOptimizer**
  Create `inkmcp/vectorizer/optimizer.py` building the SVG XML tree and passing it through `scour.scour.scourXml` with flags preserving Inkscape namespaces (`inkscape:groupmode`, `inkscape:label`).

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_vectorizer_optimizer.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  `git add inkmcp/vectorizer/optimizer.py tests/test_vectorizer_optimizer.py`
  `git commit -m "feat(vectorizer): implement SvgOptimizer with Inkscape layer DOM structuring and Scour optimization"`

---

### Task 5: Vectorize Operations Dispatcher & Live Injection

**Files:**
- Create: `inkmcp/inkmcpops/vectorize_operations.py`
- Modify: `inkmcp/inkmcpops/__init__.py`
- Create: `tests/test_vectorize_operations.py`

**Dependencies:**
- Blocked By: Task 1, Task 2, Task 3, Task 4
- Parallel Wave: Wave 4

**Interfaces:**
- Consumes: `vectorize_image_operation(params: dict, backend=None)`.
- Produces: `result_data: dict` conforming to canonical inkmcp operation return structure (`status: "success" | "warning" | "error"`, `data: {...}`).

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write the failing test**

```python
# tests/test_vectorize_operations.py
import pytest
from PIL import Image, ImageDraw
from inkmcp.inkmcpops.vectorize_operations import vectorize_image_operation

def test_vectorize_operation_file_export(tmp_path):
    img_path = tmp_path / "art.png"
    out_svg = tmp_path / "art.svg"
    img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([10, 10, 50, 50], fill=(255, 120, 0, 255))
    img.save(img_path)

    params = {
        "image_path": str(img_path),
        "output_path": str(out_svg),
        "mode": "cut_ready",
        "num_colors": 2,
        "inject_to_inkscape": False
    }
    result = vectorize_image_operation(params, backend=None)
    assert result["status"] == "success"
    assert out_svg.exists()
    assert out_svg.stat().st_size > 0
    assert "layers" in result["data"]

def test_vectorize_operation_offline_inkscape_fallback(tmp_path):
    # Review Focus 3: Offline Inkscape GUI fallback
    img_path = tmp_path / "art.png"
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([5, 5, 35, 35], fill=(0, 200, 0, 255))
    img.save(img_path)

    params = {
        "image_path": str(img_path),
        "mode": "layered",
        "inject_to_inkscape": True
    }
    # Pass backend=None to simulate offline GUI
    result = vectorize_image_operation(params, backend=None)
    assert result["status"] in ("success", "warning")
    assert "saved to" in result["data"]["message"].lower() or "export_path" in result["data"]
```

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_vectorize_operations.py -v`
  Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement vectorize_operations.py**
  Create `inkmcp/inkmcpops/vectorize_operations.py` orchestrating `ImagePreprocessor`, `VTracerCore`, `TopologyEngine`, and `SvgOptimizer`. Add injection logic via `backend.execute_operation()` or direct file loading, with graceful fallback if the backend is offline.

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_vectorize_operations.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  `git add inkmcp/inkmcpops/vectorize_operations.py inkmcp/inkmcpops/__init__.py tests/test_vectorize_operations.py`
  `git commit -m "feat(ops): add vectorize_operations dispatcher with live canvas injection and file export"`

---

### Task 6: CLI & FastMCP Server Exposure

**Files:**
- Modify: `inkmcp/inkmcpcli.py`
- Modify: `inkmcp/inkscape_mcp_server.py`
- Create: `tests/test_vectorize_cli.py`

**Dependencies:**
- Blocked By: Task 5
- Parallel Wave: Wave 5

**Interfaces:**
- Consumes: CLI invocation `python inkmcp/inkmcpcli.py vectorize-image ...` and FastMCP call `vectorize_image(...)`.
- Produces: JSON / Markdown formatted status and exit code 0.

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write CLI and FastMCP tool tests**

```python
# tests/test_vectorize_cli.py
import pytest
import subprocess
import sys
from PIL import Image, ImageDraw

def test_cli_vectorize_paths_with_spaces(tmp_path):
    # Review Focus 5: Paths with spaces on Windows
    folder_with_spaces = tmp_path / "my art folder"
    folder_with_spaces.mkdir()
    img_path = folder_with_spaces / "my pumpkin.png"
    out_path = folder_with_spaces / "my pumpkin.svg"

    img = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 40, 40], fill=(255, 100, 0, 255))
    img.save(img_path)

    cmd = [
        sys.executable,
        "inkmcp/inkmcpcli.py",
        "vectorize-image",
        f"image_path={img_path}",
        f"output_path={out_path}",
        "mode=cut_ready",
        "inject_to_inkscape=false"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0
    assert out_path.exists()
    assert out_path.stat().st_size > 0
```

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest tests/test_vectorize_cli.py -v`
  Expected: FAIL with unrecognized command `vectorize-image`

- [ ] **Step 3: Implement CLI and MCP Server tools**
  - Add `vectorize-image` parser and execution mapping to `inkmcp/inkmcpcli.py`.
  - Add `@mcp.tool() async def vectorize_image(...)` tool definition to `inkmcp/inkscape_mcp_server.py`.

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest tests/test_vectorize_cli.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  `git add inkmcp/inkmcpcli.py inkmcp/inkscape_mcp_server.py tests/test_vectorize_cli.py`
  `git commit -m "feat(cli,server): expose vectorize-image command in CLI and FastMCP server interface"`

---

### Task 7: Live Pumpkin Vectorization & Inkscape Desktop Certification

**Files:**
- Test input: `C:/Users/jmolina/.gemini/antigravity/brain/30850e01-bbf0-4c4b-947c-5bfc2ae18213/.user_uploaded/media_1791555372247_04fa78c8.png`
- Outputs:
  - `scratch/pumpkin_cut_ready.svg`
  - `scratch/pumpkin_layered.svg`
- Verification script: `tests/verify_live_pumpkin_vectorize.py`

**Dependencies:**
- Blocked By: Task 6
- Parallel Wave: Wave 6

#### Verification Pattern: Live End-to-End Certification
- [ ] **Step 1: Run automated live verification script**
  Write and execute `tests/verify_live_pumpkin_vectorize.py`:
  - Run conversion on `media_1791555372247_04fa78c8.png` in `cut_ready` mode $\to$ `scratch/pumpkin_cut_ready.svg`.
  - Run conversion on `media_1791555372247_04fa78c8.png` in `layered` mode $\to$ `scratch/pumpkin_layered.svg`.
  - Assert both SVGs are valid XML, file size $> 10$ KB, and layer labels reflect extracted colors.
  - Run full test suite: `pytest -v tests/test_vectorizer*.py tests/test_vectorize*.py`.
  Expected: All tests pass with exit code 0.

- [ ] **Step 2: Inject live into active Inkscape GUI**
  Inject `pumpkin_cut_ready.svg` and `pumpkin_layered.svg` into Inkscape 1.4.4 via `inkmcpcli.py vectorize-image`.
  Verify physical HWND visibility and layer display using `.agents/inspect_desktop_windows.py` per Invariant 51.

- [ ] **Step 3: Final Commit & Ledger Update**
  Commit all new features, tests, and updated sessions ledger:
  `feat(vectorizer): complete flat-to-production vector conversion pipeline with live certification`
