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
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from inkmcp.inkmcpops.vectorize_operations import vectorize_image_operation
from inkmcp.vectorizer.topology import TopologyEngine


PUMPKIN_IMAGE_PATH = Path(
    "C:/Users/jmolina/.gemini/antigravity/brain/30850e01-bbf0-4c4b-947c-5bfc2ae18213/.user_uploaded/media_1791555372247_04fa78c8.png"
)
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
SCRATCH_DIR = WORKSPACE_ROOT / "scratch"
CUT_READY_SVG = SCRATCH_DIR / "pumpkin_cut_ready.svg"
LAYERED_SVG = SCRATCH_DIR / "pumpkin_layered.svg"
CERTIFIED_SCREENSHOT = SCRATCH_DIR / "inkscape_pumpkin_certified.png"

# SVG Namespaces
SVG_NS = {
    "svg": "http://www.w3.org/2000/svg",
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
    "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
}


def setup_module():
    """Ensure scratch directory exists before running tests."""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)


def test_pumpkin_image_exists():
    """Verify test candidate pumpkin image exists and is readable."""
    assert PUMPKIN_IMAGE_PATH.exists(), f"Candidate pumpkin image not found at {PUMPKIN_IMAGE_PATH}"
    assert PUMPKIN_IMAGE_PATH.stat().st_size > 10000, "Pumpkin image file too small"


def test_pumpkin_vectorize_cut_ready():
    """Test full vectorization of pumpkin image in cut_ready planar mosaic mode."""
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
    assert CUT_READY_SVG.exists(), "Output SVG file was not created"
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
    assert LAYERED_SVG.exists(), "Output layered SVG was not created"
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


def test_cli_pumpkin_vectorize_execution():
    """Test CLI execution of vectorize-image with structured pretty JSON output."""
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
    # Check if Inkscape window is present on desktop
    from inkmcp.platform_utils import is_inkscape_process_running
    if not is_inkscape_process_running():
        pytest.skip("Inkscape GUI process is not running on desktop; skipping live injection certification.")

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

    # Invariant 51: True Win32 desktop window inspection & screenshot certification
    inspect_script = WORKSPACE_ROOT / ".agents" / "inspect_desktop_windows.py"
    assert inspect_script.exists(), "inspect_desktop_windows.py missing"

    shot_cmd = [
        sys.executable,
        str(inspect_script),
        "--process",
        "inkscape",
        "--screenshot",
        str(CERTIFIED_SCREENSHOT),
        "--json",
    ]

    shot_res = subprocess.run(
        shot_cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert shot_res.returncode == 0, f"inspect_desktop_windows failed: {shot_res.stderr}"

    windows = json.loads(shot_res.stdout)
    assert len(windows) > 0, "No visible Inkscape windows detected on WinSta0\\Default"
    target = next((w for w in windows if "pumpkin" in w["title"].lower()), windows[0])
    assert "inkscape" in target["process"].lower()
    assert target["visible"] is True
    assert any(
        token in target["title"].lower()
        for token in ("pumpkin", "svg", "inkscape")
    ), f"Window title does not indicate pumpkin document: {target['title']}"
    assert CERTIFIED_SCREENSHOT.exists(), "Screenshot was not created"
    assert CERTIFIED_SCREENSHOT.stat().st_size > 50000, (
        f"Screenshot file size too small: {CERTIFIED_SCREENSHOT.stat().st_size} bytes (expected > 50,000)"
    )
