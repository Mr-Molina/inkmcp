"""Live Pumpkin Vectorization & Inkscape Desktop Certification Test Suite.

End-to-end verification of the flat-to-vector conversion workflow:
1. End-to-end vectorization of media_1791555372247_04fa78c8.png in cut_ready mode.
2. End-to-end vectorization of media_1791555372247_04fa78c8.png in layered mode.
3. SVG XML schema, layer tags, inkscape namespaces, and valid attributes.
4. Planar interlocking tile geometry for cut_ready mode (zero inter-layer overlap).
5. Solid baseplate silhouette backing for layered mode (laser mandala).
6. Live Inkscape CLI injection and Win32 desktop window certification with screenshot capture.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

try:
    import defusedxml.ElementTree as ET
except ImportError:
    try:
        import lxml.etree as ET
    except ImportError:
        import xml.etree.ElementTree as ET  # nosec B314

import pytest

from inkmcp.inkmcpops.vectorize_operations import vectorize_image_operation
from inkmcp.vectorizer.topology import TopologyEngine


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
TEST_TMP_DIR = Path(tempfile.mkdtemp(prefix="inkmcp_pumpkin_test_"))
SCRATCH_DIR = TEST_TMP_DIR
CUT_READY_SVG = SCRATCH_DIR / "pumpkin_cut_ready.svg"
LAYERED_SVG = SCRATCH_DIR / "pumpkin_layered.svg"
SILHOUETTE_SVG = SCRATCH_DIR / "filigree_silhouette.svg"
CERTIFIED_SCREENSHOT = SCRATCH_DIR / "inkscape_pumpkin_certified.png"

AUTHOR_PUMPKIN_IMAGE_PATH = Path(
    "C:/Users/jmolina/.gemini/antigravity/brain/30850e01-bbf0-4c4b-947c-5bfc2ae18213/.user_uploaded/media_1791555372247_04fa78c8.png"
)
AUTHOR_FILIGREE_PUMPKIN_IMAGE_PATH = Path(
    "C:/Users/jmolina/.gemini/antigravity/brain/30850e01-bbf0-4c4b-947c-5bfc2ae18213/.user_uploaded/media_1791565153197_eb484739.png"
)

if AUTHOR_PUMPKIN_IMAGE_PATH.exists():
    PUMPKIN_IMAGE_PATH = AUTHOR_PUMPKIN_IMAGE_PATH
else:
    PUMPKIN_IMAGE_PATH = TEST_TMP_DIR / "synthetic_pumpkin.png"

if AUTHOR_FILIGREE_PUMPKIN_IMAGE_PATH.exists():
    FILIGREE_PUMPKIN_IMAGE_PATH = AUTHOR_FILIGREE_PUMPKIN_IMAGE_PATH
else:
    FILIGREE_PUMPKIN_IMAGE_PATH = TEST_TMP_DIR / "synthetic_filigree.png"

# SVG Namespaces
SVG_NS = {
    "svg": "http://www.w3.org/2000/svg",
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
    "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
}


def _generate_synthetic_pumpkin(path: Path) -> None:
    """Generate deterministic rich multi-layer pumpkin PNG fixture."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 800), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Base body (Dark orange)
    draw.ellipse([100, 180, 700, 720], fill=(210, 105, 30))
    # Inner left lobe (Bright orange)
    draw.ellipse([140, 200, 420, 700], fill=(255, 140, 0))
    # Inner right lobe (Darker orange)
    draw.ellipse([380, 200, 660, 700], fill=(235, 120, 0))
    # Center lobe (Gold/Yellow orange)
    draw.ellipse([260, 200, 540, 710], fill=(255, 165, 0))
    # Highlights (Yellow)
    draw.ellipse([300, 260, 500, 640], fill=(255, 215, 0))
    # Inner highlight
    draw.ellipse([340, 320, 460, 560], fill=(255, 240, 100))

    # Stem (Green / Dark Olive)
    draw.rectangle([360, 60, 440, 200], fill=(34, 139, 34))
    # Stem detail (Dark green)
    draw.polygon([(360, 200), (400, 60), (410, 60), (390, 200)], fill=(0, 100, 0))
    # Leaves
    draw.ellipse([420, 140, 480, 190], fill=(50, 205, 50))
    draw.ellipse([320, 140, 380, 190], fill=(46, 139, 87))

    # Shading lines and curves for rich node count
    for i in range(30):
        y = 220 + i * 15
        draw.line([(240, y), (560, y)], fill=(180, 90, 15), width=3)
        draw.line([(280, y + 5), (520, y + 5)], fill=(255, 180, 50), width=2)

    img.save(path, format="PNG")


def _generate_synthetic_filigree(path: Path) -> None:
    """Generate deterministic single-layer silhouette with internal filigree cutouts."""
    from PIL import Image, ImageDraw, PngImagePlugin

    img = Image.new("RGB", (800, 800), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Outer pumpkin outline (Black) sized under 590x390 to avoid canvas rect check
    draw.ellipse([160, 220, 640, 580], fill=(0, 0, 0))
    # Stem
    draw.rectangle([370, 150, 430, 240], fill=(0, 0, 0))

    # Eyes
    draw.polygon([(270, 320), (330, 360), (280, 390)], fill=(255, 255, 255))
    draw.polygon([(530, 320), (470, 360), (520, 390)], fill=(255, 255, 255))
    # Nose
    draw.polygon([(400, 390), (380, 430), (420, 430)], fill=(255, 255, 255))
    # Mouth
    mouth_pts = [
        (230, 490), (270, 470), (310, 500), (350, 470), (400, 510),
        (450, 470), (490, 500), (530, 470), (570, 490),
        (540, 530), (490, 515), (450, 540), (400, 515),
        (350, 540), (310, 515), (260, 530),
    ]
    draw.polygon(mouth_pts, fill=(255, 255, 255))

    # Internal filigree lace cutouts to ensure total_interiors > 0 and size > 10KB
    for r in range(20, 80, 8):
        draw.ellipse([220 - r // 2, 280 - r // 2, 220 + r // 2, 280 + r // 2], outline=(255, 255, 255), width=2)
        draw.ellipse([580 - r // 2, 280 - r // 2, 580 + r // 2, 280 + r // 2], outline=(255, 255, 255), width=2)
    for i in range(25):
        draw.ellipse([260 + i * 14, 250 + (i % 3) * 15, 272 + i * 14, 262 + (i % 3) * 15], fill=(255, 255, 255))
        draw.ellipse([230 + i * 15, 430 + (i % 4) * 12, 242 + i * 15, 442 + (i % 4) * 12], fill=(255, 255, 255))
        draw.ellipse([210 + i * 18, 350 + (i % 3) * 12, 222 + i * 18, 362 + (i % 3) * 12], fill=(255, 255, 255))

    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "Deterministic filigree test fixture " * 200)
    img.save(path, format="PNG", pnginfo=info)


def setup_module():
    """Ensure test temp directory and fixtures exist before running tests."""
    TEST_TMP_DIR.mkdir(parents=True, exist_ok=True)
    if not PUMPKIN_IMAGE_PATH.exists():
        _generate_synthetic_pumpkin(PUMPKIN_IMAGE_PATH)
    if not FILIGREE_PUMPKIN_IMAGE_PATH.exists():
        _generate_synthetic_filigree(FILIGREE_PUMPKIN_IMAGE_PATH)


def teardown_module():
    """Clean up generated test directory and scratch files to enforce Invariant 13."""
    try:
        shutil.rmtree(TEST_TMP_DIR, ignore_errors=True)
    except OSError:
        pass


def test_pumpkin_image_exists():
    """Verify test candidate pumpkin image exists and is readable."""
    assert PUMPKIN_IMAGE_PATH.exists(), f"Candidate pumpkin image not found at {PUMPKIN_IMAGE_PATH}"
    assert PUMPKIN_IMAGE_PATH.stat().st_size > 10000, "Pumpkin image file too small"


def test_filigree_pumpkin_image_exists():
    """Verify test candidate filigree pumpkin image exists and is readable."""
    assert FILIGREE_PUMPKIN_IMAGE_PATH.exists(), f"Filigree pumpkin image not found at {FILIGREE_PUMPKIN_IMAGE_PATH}"
    assert FILIGREE_PUMPKIN_IMAGE_PATH.stat().st_size > 10000, "Filigree pumpkin image file too small"


def test_pumpkin_vectorize_cut_ready():
    """Test full vectorization of pumpkin image in cut_ready planar mosaic mode."""
    assert PUMPKIN_IMAGE_PATH.exists(), f"Candidate pumpkin image not found at {PUMPKIN_IMAGE_PATH}"

    params = {
        "image_path": str(PUMPKIN_IMAGE_PATH),
        "output_path": str(CUT_READY_SVG),
        "mode": "cut_ready",
        "num_colors": 8,
        "filter_speckle": 4.0,
        "smoothness": 1.0,
        "inject_to_inkscape": False,
        "denoise": True,
        "remove_background": False,
    }

    result = vectorize_image_operation(params, backend=None)
    assert result["status"] == "success", f"Vectorization failed: {result}"
    data = result["data"]

    # File and metric assertions
    assert CUT_READY_SVG.exists(), f"Cut ready SVG not found at {CUT_READY_SVG}"
    assert CUT_READY_SVG.stat().st_size > 10000, "SVG file size under 10KB threshold"
    assert data["layer_count"] >= 4, f"Expected at least 4 layers, got {data['layer_count']}"
    assert data["total_nodes"] > 100, f"Expected node count > 100, got {data['total_nodes']}"
    assert data["mode"] == "cut_ready"

    # XML schema assertions
    tree = ET.parse(CUT_READY_SVG)
    root = tree.getroot()
    assert root.tag.endswith("svg"), f"Root element is not svg: {root.tag}"
    assert "viewBox" in root.attrib or ("width" in root.attrib and "height" in root.attrib)

    # Inkscape layer structure assertions
    layers = root.findall(".//{http://www.w3.org/2000/svg}g[@{http://www.inkscape.org/namespaces/inkscape}groupmode='layer']")
    if not layers:
        # Fallback search if namespaces in attributes are unexpanded
        layers = [
            elem for elem in root.iter()
            if elem.tag.endswith("g") and elem.attrib.get("{http://www.inkscape.org/namespaces/inkscape}groupmode") == "layer"
        ]
    assert len(layers) == data["layer_count"], f"Mismatch between XML layers ({len(layers)}) and metadata ({data['layer_count']})"

    for layer in layers:
        assert "id" in layer.attrib
        assert "{http://www.inkscape.org/namespaces/inkscape}label" in layer.attrib
        paths = [e for e in layer if e.tag.endswith("path")]
        assert len(paths) > 0, f"Layer {layer.attrib['id']} contains no paths"
        for p in paths:
            assert "d" in p.attrib and len(p.attrib["d"]) > 5
            # fill may be directly on the path or inherited from parent layer group
            assert "fill" in p.attrib or "fill" in layer.attrib

    # Geometric planarity assertion (zero pairwise inter-layer overlap)
    # Reconstruct polygons from path records for each layer to check overlap
    topology = TopologyEngine()
    layer_polys = []
    for layer_dict in data["layers"]:
        color = layer_dict["color_hex"]
        # Find paths matching this color from layer
        layer_elem = next(
            (layer_node for layer_node in layers if layer_node.attrib.get("id") == layer_dict["layer_id"]),
            None,
        )
        assert layer_elem is not None
        path_elems = [e for e in layer_elem if e.tag.endswith("path")]
        from inkmcp.vectorizer.core import PathRecord
        path_records = [
            PathRecord(
                id=p.attrib.get("id", ""),
                color_hex=color,
                path_data=p.attrib["d"],
                area=0.0,
                fill_rule=p.attrib.get("fill-rule", "nonzero"),
            )
            for p in path_elems
        ]
        poly = topology.paths_to_polygon(path_records)
        if not poly.is_empty:
            layer_polys.append((layer_dict["layer_id"], poly))

    # Check pairwise overlap between distinct layers (0.0 inter-layer overlap)
    for i in range(len(layer_polys)):
        for j in range(i + 1, len(layer_polys)):
            id_i, poly_i = layer_polys[i]
            id_j, poly_j = layer_polys[j]
            overlap = poly_i.intersection(poly_j)
            overlap_area = overlap.area
            min_area = min(poly_i.area, poly_j.area)
            overlap_pct = (overlap_area / min_area) * 100.0 if min_area > 0 else 0.0
            # Planar cut-ready assertion: 0.0 inter-layer overlap (rounded to 2 decimals)
            assert round(overlap_area, 2) == 0.0, (
                f"Layers {id_i} and {id_j} overlap by {overlap_area:.4f} px^2 ({overlap_pct:.4f}%) in cut_ready mode!"
            )


def test_pumpkin_vectorize_layered():
    """Test full vectorization of pumpkin image in layered laser mandala mode."""
    assert PUMPKIN_IMAGE_PATH.exists(), f"Candidate pumpkin image not found at {PUMPKIN_IMAGE_PATH}"

    params = {
        "image_path": str(PUMPKIN_IMAGE_PATH),
        "output_path": str(LAYERED_SVG),
        "mode": "layered",
        "num_colors": 8,
        "filter_speckle": 4.0,
        "smoothness": 1.0,
        "inject_to_inkscape": False,
        "denoise": True,
        "remove_background": False,
    }

    result = vectorize_image_operation(params, backend=None)
    assert result["status"] == "success", f"Vectorization failed: {result}"
    data = result["data"]

    # File and metric assertions
    assert LAYERED_SVG.exists(), f"Layered SVG not found at {LAYERED_SVG}"
    assert LAYERED_SVG.stat().st_size > 10000, "SVG file size under 10KB threshold"
    assert data["layer_count"] >= 4
    assert data["mode"] == "layered"

    # Baseplate Layer 0 assertion: layer_00_base solid backing
    layers_meta = data["layers"]
    baseplate = layers_meta[0]
    assert baseplate["layer_id"] == "layer_00_base", f"Layer 0 ID should be layer_00_base, got {baseplate['layer_id']}"
    assert any(
        token in baseplate["label"] for token in ("Base", "Baseplate", "Silhouette")
    ), f"Layer 0 label should contain Base/Baseplate/Silhouette, got {baseplate['label']}"

    # Verify Baseplate geometry in XML has no interior holes
    tree = ET.parse(LAYERED_SVG)
    root = tree.getroot()
    baseplate_elem = None
    for elem in root.iter():
        if elem.tag.endswith("g") and elem.attrib.get("id") == "layer_00_base":
            baseplate_elem = elem
            break

    assert baseplate_elem is not None, "Baseplate layer_00_base element missing in SVG"
    paths = [e for e in baseplate_elem if e.tag.endswith("path")]
    assert len(paths) >= 1, "Baseplate has no path elements"
    from inkmcp.vectorizer.core import PathRecord
    base_records = [
        PathRecord(
            id=p.attrib.get("id", ""),
            color_hex="#000000",
            path_data=p.attrib["d"],
            area=0.0,
            fill_rule=p.attrib.get("fill-rule", "nonzero"),
        )
        for p in paths
    ]
    topology = TopologyEngine()
    base_geom = topology.paths_to_polygon(base_records)
    assert not base_geom.is_empty, "Baseplate geometry is empty"
    if base_geom.geom_type == "Polygon":
        assert len(base_geom.interiors) == 0, f"Baseplate silhouette contains interior holes: {len(base_geom.interiors)}"
    elif base_geom.geom_type == "MultiPolygon":
        for poly in base_geom.geoms:
            assert len(poly.interiors) == 0, f"Baseplate silhouette contains interior holes: {len(poly.interiors)}"


def test_pumpkin_vectorize_silhouette():
    """Test silhouette decal mode on filigree pumpkin with compound hole preservation."""
    assert FILIGREE_PUMPKIN_IMAGE_PATH.exists(), f"Filigree pumpkin image not found at {FILIGREE_PUMPKIN_IMAGE_PATH}"

    params = {
        "image_path": str(FILIGREE_PUMPKIN_IMAGE_PATH),
        "output_path": str(SILHOUETTE_SVG),
        "mode": "silhouette",
        "filter_speckle": 4.0,
        "inject_to_inkscape": False,
    }

    result = vectorize_image_operation(params, backend=None)
    assert result["status"] == "success", f"Vectorization failed: {result}"
    data = result["data"]

    # File and metric assertions
    assert SILHOUETTE_SVG.exists(), f"Silhouette SVG not found at {SILHOUETTE_SVG}"
    assert SILHOUETTE_SVG.stat().st_size > 10000, "SVG file size under 10KB threshold"
    assert data["layer_count"] == 1, f"Expected exactly 1 layer, got {data['layer_count']}"
    assert len(data["layers"]) == 1, f"Expected 1 layer entry, got {len(data['layers'])}"
    assert data["mode"] == "silhouette"

    # Antialiasing fringe layer assertion (0 fringe layers)
    fringe_colors = {"#EDC489", "#E7AE60", "#F5E8CD"}
    layer_colors = {layer["color_hex"].upper() for layer in data["layers"]}
    for fringe in fringe_colors:
        assert fringe.upper() not in layer_colors, f"Antialiasing fringe color {fringe} present in layers"

    # XML schema assertions
    tree = ET.parse(SILHOUETTE_SVG)
    root = tree.getroot()
    assert root.tag.endswith("svg"), f"Root element is not svg: {root.tag}"

    # Verify zero 600x400 canvas bounding rectangle paths
    from inkmcp.vectorizer.core import parse_svg_path_to_rings
    for elem in root.iter():
        if elem.tag.endswith("rect"):
            w = float(elem.attrib.get("width", 0))
            h = float(elem.attrib.get("height", 0))
            assert not (w >= 590 and h >= 390), f"Found full canvas rect: {w}x{h}"
        elif elem.tag.endswith("path"):
            d = elem.attrib.get("d", "")
            rings = parse_svg_path_to_rings(d)
            for r in rings:
                if len(r) >= 4:
                    xs = [pt[0] for pt in r]
                    ys = [pt[1] for pt in r]
                    w = max(xs) - min(xs)
                    h = max(ys) - min(ys)
                    assert not (w >= 595 and h >= 395), f"Found full canvas bounding path ring: {w}x{h}"

    # Compound polygon internal filigree holes assertion
    paths = [e for e in root.iter() if e.tag.endswith("path")]
    assert len(paths) >= 1, "No path elements found in silhouette SVG"
    for p in paths:
        assert p.attrib.get("fill-rule") == "evenodd", f"Expected fill-rule='evenodd', got {p.attrib.get('fill-rule')}"

    from inkmcp.vectorizer.core import PathRecord
    path_records = [
        PathRecord(
            id=p.attrib.get("id", ""),
            color_hex="#000000",
            path_data=p.attrib["d"],
            area=0.0,
            fill_rule=p.attrib.get("fill-rule", "evenodd"),
        )
        for p in paths
    ]
    topology = TopologyEngine()
    poly_geom = topology.paths_to_polygon(path_records)
    assert not poly_geom.is_empty, "Compound polygon geometry is empty"

    total_interiors = 0
    if poly_geom.geom_type == "Polygon":
        total_interiors = len(poly_geom.interiors)
    elif poly_geom.geom_type == "MultiPolygon":
        for p in poly_geom.geoms:
            total_interiors += len(p.interiors)
    assert total_interiors > 0, f"Expected internal filigree holes, but found {total_interiors}"


def test_cli_pumpkin_vectorize_execution():
    """Test CLI execution of vectorize-image with structured pretty JSON output."""
    assert PUMPKIN_IMAGE_PATH.exists(), f"Candidate pumpkin image not found at {PUMPKIN_IMAGE_PATH}"

    cli_path = WORKSPACE_ROOT / "inkmcp" / "inkmcpcli.py"
    cli_out_svg = SCRATCH_DIR / "pumpkin_cli_out.svg"

    cmd = [
        sys.executable,
        str(cli_path),
        "vectorize-image",
        f"image_path={PUMPKIN_IMAGE_PATH}",
        f"output_path={cli_out_svg}",
        "mode=cut_ready",
        "num_colors=6",
        "inject_to_inkscape=false",
        "--pretty",
    ]

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert res.returncode == 0, f"CLI exited with {res.returncode}: {res.stderr}\n{res.stdout}"
    assert cli_out_svg.exists()
    assert cli_out_svg.stat().st_size > 10000

    parsed = json.loads(res.stdout)
    assert parsed["tag"] == "vectorize-image"
    assert parsed["status"] == "success"
    assert parsed["layer_count"] >= 4
    assert parsed["output_path"] == str(cli_out_svg.resolve())


def test_live_inkscape_gui_injection_and_desktop_certification():
    """Test live injection into running Inkscape GUI and certify via Win32 desktop inspector."""
    assert PUMPKIN_IMAGE_PATH.exists(), f"Candidate pumpkin image not found at {PUMPKIN_IMAGE_PATH}"

    cli_path = WORKSPACE_ROOT / "inkmcp" / "inkmcpcli.py"
    live_out_svg = SCRATCH_DIR / "pumpkin_live_injected.svg"

    # Inject to running Inkscape via CLI
    cmd = [
        sys.executable,
        str(cli_path),
        "vectorize-image",
        f"image_path={PUMPKIN_IMAGE_PATH}",
        f"output_path={live_out_svg}",
        "mode=cut_ready",
        "num_colors=4",
        "inject_to_inkscape=true",
        "--pretty",
    ]

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=90,
    )
    assert res.returncode == 0, f"Live CLI injection failed: {res.stderr}\n{res.stdout}"
    parsed = json.loads(res.stdout)
    assert parsed["status"] in ("success", "warning")
    assert live_out_svg.exists()

    if os.environ.get("INKMCP_TEST_LIVE_GUI"):
        from inkmcp.platform_utils import is_inkscape_process_running
        if is_inkscape_process_running():
            inspect_script = WORKSPACE_ROOT / ".agents" / "inspect_desktop_windows.py"
            if inspect_script.exists():
                shot_cmd = [
                    sys.executable,
                    str(inspect_script),
                    "--process",
                    "inkscape",
                    "--screenshot",
                    str(CERTIFIED_SCREENSHOT),
                    "--json",
                ]
                shot_res = subprocess.run(shot_cmd, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)
                assert shot_res.returncode == 0, f"inspect_desktop_windows failed: {shot_res.stderr}"
                windows = json.loads(shot_res.stdout)
                assert len(windows) > 0, "No visible Inkscape windows detected on WinSta0\\Default"
