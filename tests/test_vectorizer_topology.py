"""Unit tests for TopologyEngine, LayerGroup, and StructuredLayerData."""

import re
import pytest
from shapely.geometry import Polygon

from inkmcp.vectorizer.core import PathRecord
from inkmcp.vectorizer.topology import LayerGroup, StructuredLayerData, TopologyEngine


def test_dataclasses_instantiation():
    """Verify LayerGroup and StructuredLayerData instantiate with correct types and defaults."""
    path = PathRecord(
        id="layer00_path01",
        color_hex="#FFA500",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",
        area=100.0,
    )
    group = LayerGroup(
        layer_id="layer_00",
        label="00 - #FFA500",
        color_hex="#FFA500",
        paths=[path],
        z_index=0,
    )
    assert group.layer_id == "layer_00"
    assert group.label == "00 - #FFA500"
    assert group.color_hex == "#FFA500"
    assert len(group.paths) == 1
    assert group.z_index == 0

    structured = StructuredLayerData(
        mode="cut_ready",
        layers=[group],
    )
    assert structured.mode == "cut_ready"
    assert len(structured.layers) == 1
    assert structured.dimensions == (100, 100)


def test_cut_ready_zero_overlap():
    """Verify cut_ready mode slices overlapping paths so layer intersection area is zero."""
    engine = TopologyEngine()
    # Path 1: Red box [0, 0, 10, 10]
    p1 = PathRecord(
        id="p1",
        color_hex="#ff0000",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",
        area=100.0,
    )
    # Path 2: Blue box overlapping [5, 0, 15, 10]
    p2 = PathRecord(
        id="p2",
        color_hex="#0000ff",
        path_data="M 5 0 L 15 0 L 15 10 L 5 10 Z",
        area=100.0,
    )

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
    """Verify layered mode creates a continuous solid silhouette backing for Layer 0."""
    engine = TopologyEngine()
    p1 = PathRecord(
        id="p1",
        color_hex="#ff0000",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",
        area=100.0,
    )
    p2 = PathRecord(
        id="p2",
        color_hex="#00ff00",
        path_data="M 2 2 L 8 2 L 8 8 L 2 8 Z",
        area=36.0,
    )

    structured = engine.process([p1, p2], mode="layered")
    assert structured.mode == "layered"

    # Layer 0 must be the solid base silhouette backing
    base_layer = structured.layers[0]
    assert "Base Silhouette" in base_layer.label or "00_base" in base_layer.layer_id
    base_poly = engine.paths_to_polygon(base_layer.paths)
    assert base_poly.area >= 100.0

    # Ensure base silhouette encloses all input geometry
    all_inputs_poly = engine.paths_to_polygon([p1, p2])
    assert base_poly.covers(all_inputs_poly)

    # Verify subsequent layers are ordered from largest to finest
    assert len(structured.layers) == 3
    assert structured.layers[1].z_index == 1
    assert structured.layers[2].z_index == 2


def test_topology_heals_invalid_polygons():
    """Verify self-intersecting or degenerate contours are healed via shapely.make_valid()."""
    engine = TopologyEngine()
    # Figure-8 self-intersecting polygon
    p_invalid = PathRecord(
        id="p_inv",
        color_hex="#ff0000",
        path_data="M 0 0 L 10 10 L 10 0 L 0 10 Z",
        area=50.0,
    )
    structured = engine.process([p_invalid], mode="cut_ready")
    assert len(structured.layers) >= 1
    poly = engine.paths_to_polygon(structured.layers[0].paths)
    assert poly.is_valid
    assert poly.area > 0


def test_deterministic_path_and_layer_ids():
    """Verify layer and path IDs strictly adhere to deterministic formatting."""
    engine = TopologyEngine()
    # Create disjoint shapes in the same color group to produce multiple paths in a single layer
    p1 = PathRecord(
        id="raw1",
        color_hex="#FFAA00",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",
        area=100.0,
    )
    p2 = PathRecord(
        id="raw2",
        color_hex="#FFAA00",
        path_data="M 30 30 L 40 30 L 40 40 L 30 40 Z",
        area=100.0,
    )
    p3 = PathRecord(
        id="raw3",
        color_hex="#0055FF",
        path_data="M 50 50 L 60 50 L 60 60 L 50 60 Z",
        area=100.0,
    )

    for mode in ("cut_ready", "layered"):
        structured = engine.process([p1, p2, p3], mode=mode)
        assert len(structured.layers) >= 2
        for layer in structured.layers:
            # Layer ID format
            assert re.match(r"^layer_\d{2}(_base)?$", layer.layer_id)
            assert f"{layer.z_index:02d}" in layer.label
            assert len(layer.paths) >= 1

            for p_idx, path in enumerate(layer.paths, start=1):
                # Path ID format
                expected_id = f"layer{layer.z_index:02d}_path{p_idx:02d}"
                assert path.id == expected_id
                assert re.match(r"^layer\d{2}_path\d{2}$", path.id)


def test_filter_speckle_removal():
    """Verify small speckles/slivers below filter_speckle area threshold are removed."""
    engine = TopologyEngine()
    # Large square (area 100) and tiny micro-speckle (area 2)
    large = PathRecord(
        id="p_large",
        color_hex="#FF0000",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",
        area=100.0,
    )
    speckle = PathRecord(
        id="p_speckle",
        color_hex="#00FF00",
        path_data="M 50 50 L 51 50 L 51 52 L 50 52 Z",
        area=2.0,
    )

    structured = engine.process([large, speckle], mode="cut_ready", filter_speckle=4.0)
    # The speckle layer should be completely filtered out
    assert len(structured.layers) == 1
    assert structured.layers[0].color_hex == "#FF0000"


def test_empty_paths_handling():
    """Verify processing empty path input returns empty layers safely."""
    engine = TopologyEngine()
    res = engine.process([], mode="cut_ready", dimensions=(200, 150))
    assert res.mode == "cut_ready"
    assert res.layers == []
    assert res.dimensions == (200, 150)

    empty_poly = engine.paths_to_polygon([])
    assert empty_poly.is_empty

    empty_path_str = engine.polygon_to_path_data(Polygon())
    assert empty_path_str == ""


def test_unsupported_mode_raises_value_error():
    """Verify unknown mode parameter raises explicit ValueError."""
    engine = TopologyEngine()
    p = PathRecord(
        id="p1",
        color_hex="#FF0000",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",
        area=100.0,
    )
    with pytest.raises(ValueError, match="Unsupported mode"):
        engine.process([p], mode="unsupported_mode")


def test_polygon_to_path_data_roundtrip():
    """Verify polygon_to_path_data generates valid SVG path data that can be parsed back."""
    engine = TopologyEngine()
    poly = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
    d = engine.polygon_to_path_data(poly)
    assert d.startswith("M")
    assert d.endswith("Z")

    reconstructed_poly = engine.paths_to_polygon(
        [PathRecord(id="test", color_hex="#000000", path_data=d, area=400.0)]
    )
    assert reconstructed_poly.is_valid
    assert abs(reconstructed_poly.area - 400.0) < 1e-2


def test_donut_with_holes_zero_overlap():
    """Verify donut shapes with holes maintain hollow center during difference."""
    engine = TopologyEngine()
    # Red donut: [0, 0] to [20, 20], hole [5, 5] to [15, 15] (area 300)
    donut = PathRecord(
        id="p_donut",
        color_hex="#FF0000",
        path_data="M 0 0 L 20 0 L 20 20 L 0 20 Z M 5 5 L 15 5 L 15 15 L 5 15 Z",
        area=300.0,
    )
    # Blue peg located entirely within the donut's hole: [8, 8] to [12, 12] (area 16)
    peg = PathRecord(
        id="p_peg",
        color_hex="#0000FF",
        path_data="M 8 8 L 12 8 L 12 12 L 8 12 Z",
        area=16.0,
    )

    structured = engine.process([donut, peg], mode="cut_ready")
    assert len(structured.layers) == 2
    poly0 = engine.paths_to_polygon(structured.layers[0].paths)
    poly1 = engine.paths_to_polygon(structured.layers[1].paths)

    assert poly0.intersection(poly1).area < 1e-4
    # The donut's area should remain approximately 300 since peg was inside the hole
    assert abs(poly0.area - 300.0) < 1.0
    assert abs(poly1.area - 16.0) < 1e-2


def test_topology_silhouette_mode_compound_holes():
    """Verify outer polygon with an inner hole results in a compound polygon with interior ring intact in 1 layer."""
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

    # Verify compound polygon has interior hole intact
    geom = engine.paths_to_polygon(result.layers[0].paths)
    assert geom.is_valid
    assert len(geom.interiors) == 1
    assert abs(geom.area - 4800.0) < 1.0


def test_topology_silhouette_strips_canvas_box():
    """Verify a 100x100 canvas rectangle is completely removed, leaving only the subject geometry."""
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
    geom = engine.paths_to_polygon(result.layers[0].paths)
    assert abs(geom.area - 400.0) < 1.0


def test_topology_silhouette_mode_isolates_watermark():
    """Verify primary body with disconnected bottom text produces distinct polygon components with zero bridging."""
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
