# Flat-to-Production Vector Conversion Workflow Specification

**Document ID**: `SPEC-2026-1009-VECTORIZE`  
**Date**: 2026-10-09  
**Status**: Approved (Brainstorming Phase Complete)  
**Authors**: Orchestrator & User Collaborative Session  
**Target Repository**: `inkmcp` (`windows-mcp` branch)

---

## 1. Executive Summary & Objective

The objective of this subsystem is to provide an end-to-end, automated, and production-grade raster-to-vector conversion workflow inside `inkmcp`. The pipeline ingests flat raster images (PNG, JPG, WebP) and produces semantically grouped, clean, and optimized SVG vector documents tailored specifically for physical fabrication (CNC, vinyl cutting, heat transfer vinyl [HTV], and multi-layer laser cutting/mandalas) as well as direct interactive editing within Inkscape.

The system addresses the primary failure modes of conventional vector tracing (dense microscopic speckles, overlapping bulky layers unsuited for vinyl, ungrounded single-path soups, and lack of structural backings for laser cutting) by providing two distinct topological output modes:
1. **`cut_ready` (Vinyl / HTV)**: Planar, non-overlapping, interlocking abutting cut paths grouped by color.
2. **`layered` (Laser Mandala / 3D Wood / Craft)**: Cumulative, structurally rigid silhouette backings beneath ascending detail layers.

---

## 2. Architectural Components

The subsystem is implemented within the `inkmcp` package under a new dedicated module namespace `inkmcp/vectorizer/` and exposed via `inkmcp/inkmcpops/`:

```
inkmcp/
├── vectorizer/
│   ├── __init__.py           # Public API exports
│   ├── preprocessor.py       # Denoising, alpha separation, color clustering
│   ├── core.py               # VTracer adapter & spline parameterization
│   ├── topology.py           # Boolean operations: 'cut_ready' vs 'layered'
│   └── optimizer.py          # Scour SVG sanitizer & layer DOM generator
├── inkmcpops/
│   └── vectorize_operations.py # Operation dispatcher (CLI & MCP hook)
└── inkmcpcli.py              # CLI entry point: vectorize-image command
```

### 2.1. Component Responsibilities

1. **`inkmcp.vectorizer.preprocessor` (`ImagePreprocessor`)**:
   - Ingests image via Pillow (`PIL.Image`).
   - Extracts and isolates alpha transparency channels to preserve clear outer silhouettes.
   - Applies edge-preserving bilateral / median filtering to smooth out JPEG compression artifacts and anti-aliasing fuzz while keeping crisp vector boundary edges.
   - Quantizes the color space into a discrete palette (default 8, configurable 2–32) using K-Means / color frequency clustering.
   - Optional `remove_background=True` parameter to detect and strip solid backdrop colors (e.g. solid white or green-screen backgrounds).

2. **`inkmcp.vectorizer.core` (`VTracerCore`)**:
   - Integrates with the compiled Rust `vtracer` library (`vtracer.convert_image_to_svg_py` or native contour extractor).
   - Configures contour simplification and curve fitting:
     - `filter_speckle`: Minimum pixel area threshold (default 4 px) to eliminate blade-damaging specks.
     - `corner_threshold`: Controls angle detection for sharp corners vs smooth transitions.
     - `segment_length`: Path simplification and curve tightness.

3. **`inkmcp.vectorizer.topology` (`TopologyEngine`)**:
   - Ingests raw vector paths and color groups from `VTracerCore`.
   - Executes geometry transformations based on target mode:
     - **Mode `cut_ready`**: Uses 2D planar boolean operations (via `shapely` polygons or non-overlapping contour boundaries) to compute exact abutting boundaries where adjacent colors meet without stacking material.
     - **Mode `layered`**: Generates a continuous solid silhouette backing for the baseplate (Layer 0) and computes cumulative supporting backings for upper midtone and detail layers.
   - Tags every path with an explicit, deterministic element ID (e.g., `layer01_path05`).

4. **`inkmcp.vectorizer.optimizer` (`SvgOptimizer`)**:
   - Scaffolds a complete SVG document containing standard Inkscape layer markup:
     `<g inkscape:groupmode="layer" id="layer_01_base" inkscape:label="01 - Deep Orange (#D95E1E)">`.
   - Executes `scour` optimization to strip redundant XML namespace definitions, sanitize precision (default 2–3 decimal places), and ensure clean SVG standard conformance.

5. **`inkmcp.inkmcpops.vectorize_operations` (`VectorizeOperations`)**:
   - Acts as the unified execution handler for both CLI and FastMCP servers.
   - Manages file output paths and integrates with `WindowsCliBackend` / `DBusBackend` to inject the generated SVG into the live Inkscape canvas when requested.

---

## 3. Data Flow & Topological Modes

### 3.1. Pipeline Flow
```
[Input Raster: PNG / JPG / WebP]
               │
               ▼
[ImagePreprocessor: Denoise, Alpha Separation, Palette Extraction]
               │
               ▼
[VTracerCore: Contour Spline Extraction & Speckle Suppression]
               │
               ▼
[TopologyEngine: Geometry Transformation]
   ├── Mode 'cut_ready' (Vinyl/HTV): Non-overlapping planar mosaic tiles
   └── Mode 'layered' (Laser Mandala): Stacked cumulative silhouette layers
               │
               ▼
[SvgOptimizer: Inkscape Layer Scaffolding & Scour Sanitization]
               │
               ▼
[Delivery: Write to Target .SVG and/or Inject into Live Inkscape GUI]
```

### 3.2. Detailed Mode Specifications

#### Mode A: `cut_ready` (Vinyl & Heat Transfer Vinyl)
- **Problem**: Layered vinyl on t-shirts or signs creates bulky, heavy ridges that peel off in the wash and jam vinyl cutter blades.
- **Specification**:
  - All color paths are planar and mutually exclusive.
  - Intersection area between any two distinct color layers: $A(L_i \cap L_j) = 0$ for $i \neq j$.
  - Grouped strictly by color hex code into distinct Inkscape layers.
  - Users can toggle layer visibility in Inkscape to cut each colored vinyl sheet independently.

#### Mode B: `layered` (Laser Mandala & 3D Craft)
- **Problem**: Multi-layer laser wood projects require that thin, delicate cutouts (e.g. eyes, mouth, stems) have continuous material support underneath so pieces do not fall through the laser honeycomb bed or separate upon assembly.
- **Specification**:
  - **Layer 0 (`00_base_silhouette`)**: Complete outer boundary silhouette unioned into a single solid backing plate.
  - **Intermediate Layers (`01_midtone_structure`)**: Large structural bodies with decorative negative cutouts.
  - **Top Layers (`02_accents_highlights`)**: Fine detail cutouts positioned to register onto underlying wood/acrylic sheets.
  - Sorted strictly from lowest index (bottom backing) to highest (top accent).

---

## 4. Interface Contracts

### 4.1. FastMCP Tool Interface
Registered in `inkmcp/inkscape_mcp_server.py`:

```python
@mcp.tool()
async def vectorize_image(
    ctx: Context,
    image_path: str,
    mode: str = "cut_ready",
    num_colors: int = 8,
    filter_speckle: int = 4,
    smoothness: float = 1.0,
    inject_to_inkscape: bool = True,
    output_path: Optional[str] = None,
) -> str:
    """
    Convert a raster image into a production-ready vector SVG.

    Args:
        image_path: Absolute file path to the source image.
        mode: 'cut_ready' (vinyl/HTV mosaic) or 'layered' (laser mandala stack).
        num_colors: Target quantized color palette count (2 to 32, default 8).
        filter_speckle: Minimum pixel area cutoff to drop micro-speckles (default 4).
        smoothness: Curve smoothing and tension factor (default 1.0).
        inject_to_inkscape: If True, injects into active Inkscape canvas.
        output_path: Target SVG file path on disk.
    """
```

### 4.2. CLI Command Interface
Exposed in `inkmcp/inkmcpcli.py`:

```powershell
python inkmcp/inkmcpcli.py vectorize-image image_path="<path>" mode="cut_ready|layered" num_colors=8 [output_path="<path>"] [inject_to_inkscape=true|false]
```

---

## 5. Error Handling & Defensive Boundaries

1. **File Validation**:
   - Check file existence before reading.
   - Verify image format with Pillow; raise descriptive `ValueError` on corrupt or unreadable files.
2. **Color Bounds**:
   - Enforce $2 \le \text{num\_colors} \le 32$. If user requests out-of-range values, clamp or raise an explicit validation error.
3. **Geometry Healing**:
   - Apply `shapely.make_valid()` on all extracted polygon contours.
   - Drop degenerate polygons where area $< \text{filter\_speckle}$.
4. **Inkscape Connection Fallback**:
   - If `inject_to_inkscape=True` but the Inkscape process is not running or backend fails, gracefully save the SVG to disk, return status `warning`, and notify the user with the file path.
5. **Windows Subprocess & Path Safety**:
   - Comply with **Invariant 53** (strict quoting and no inline multi-line Python) and **Invariant 24** (zero credential leaks).

---

## 6. Verification & Test Plan

In compliance with **Invariant 55** and the multi-agent testing standard, validation is divided across three isolated test suites:

1. **Unit Test Suite (`tests/test_vectorizer.py`)**:
   - `test_preprocessor_palette_quantization`: Asserts palette reduction extracts expected colors on synthetic test images.
   - `test_vtracer_spline_generation`: Validates curve generation and speckle filtering.
   - `test_cut_ready_zero_overlap`: Computes pairwise geometric intersections of all output paths in `cut_ready` mode to guarantee zero overlap.
   - `test_layered_mandala_solid_backing`: Asserts that Layer 0 contains a continuous silhouette enclosing the entire artwork geometry.
   - `test_scour_svg_layer_markup`: Verifies SVG XML tree contains valid `inkscape:groupmode="layer"` and valid viewBox.
2. **CLI & Server Integration Suite (`tests/test_vectorize_cli.py`)**:
   - Tests `inkmcpcli.py vectorize-image` argument parsing and execution with mock image.
   - Tests FastMCP `vectorize_image` tool dispatch.
3. **Live Production Validation**:
   - Run live conversion against the user-provided pumpkin artwork (`media_1791555372247_04fa78c8.png`).
   - Validate both `cut_ready` and `layered` outputs.
   - Inject the resulting vector document into the active Inkscape 1.4.4 GUI window and verify visual quality and layer structure on screen.
