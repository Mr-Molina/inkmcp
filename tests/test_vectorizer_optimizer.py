"""Unit tests for SvgOptimizer and OptimizedSvgResult."""

import xml.etree.ElementTree as ET
from unittest.mock import patch

from inkmcp.vectorizer.core import PathRecord
from inkmcp.vectorizer.optimizer import OptimizedSvgResult, SvgOptimizer
from inkmcp.vectorizer.topology import LayerGroup, StructuredLayerData


INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
SVG_NS = "http://www.w3.org/2000/svg"


def test_svg_optimizer_layer_structure():
    """Validates root svg, viewBox, inkscape layer attributes, path id, and layer count."""
    path = PathRecord(
        id="layer01_path01",
        color_hex="#FF0000",
        path_data="M 0 0 L 100 0 L 100 100 L 0 100 Z",
        area=10000.0,
        fill_rule="nonzero",
    )
    layer = LayerGroup(
        layer_id="layer_01",
        label="01 - Red",
        color_hex="#FF0000",
        paths=[path],
        z_index=1,
    )
    layer_data = StructuredLayerData(
        mode="cut_ready",
        layers=[layer],
        dimensions=(200, 200),
    )

    optimizer = SvgOptimizer()
    result = optimizer.build_and_optimize(layer_data, dimensions=(200, 200))

    assert isinstance(result, OptimizedSvgResult)
    assert result.layer_count == 1
    assert result.total_nodes == 5
    assert result.file_size == len(result.svg_content.encode("utf-8"))
    assert result.file_size > 0

    # Validate SVG content string contents
    svg = result.svg_content
    assert "<svg" in svg
    assert 'viewBox="0 0 200 200"' in svg
    assert 'inkscape:groupmode="layer"' in svg
    assert 'inkscape:label="01 - Red"' in svg
    assert 'id="layer01_path01"' in svg

    # Validate XML DOM structure
    root = ET.fromstring(svg)
    assert root.tag == f"{{{SVG_NS}}}svg"
    g_elem = root.find(f"{{{SVG_NS}}}g")
    assert g_elem is not None
    assert g_elem.attrib.get(f"{{{INKSCAPE_NS}}}groupmode") == "layer"
    assert g_elem.attrib.get(f"{{{INKSCAPE_NS}}}label") == "01 - Red"
    assert g_elem.attrib.get("id") == "layer_01"


def test_svg_optimizer_scour_preserves_inkscape_metadata():
    """Verifies that Scour optimization retains inkscape:groupmode and inkscape:label."""
    path = PathRecord(
        id="p_alpha",
        color_hex="#00AA00",
        path_data="M 10.12345 10.12345 L 50.98765 10.12345 L 50.98765 50.98765 Z",
        area=800.0,
        fill_rule="nonzero",
    )
    layer = LayerGroup(
        layer_id="layer_forest",
        label="Forest Green Layer",
        color_hex="#00AA00",
        paths=[path],
        z_index=0,
    )
    layer_data = StructuredLayerData(
        mode="layered",
        layers=[layer],
        dimensions=(150, 150),
    )

    optimizer = SvgOptimizer()
    raw_svg = optimizer.build_svg(layer_data)
    scoured_svg = optimizer.optimize(raw_svg, precision=2, enable_scour=True)

    root = ET.fromstring(scoured_svg)
    g = root.find(f"{{{SVG_NS}}}g")
    assert g is not None
    assert g.attrib.get(f"{{{INKSCAPE_NS}}}groupmode") == "layer"
    assert g.attrib.get(f"{{{INKSCAPE_NS}}}label") == "Forest Green Layer"
    assert g.attrib.get("id") == "layer_forest"


def test_svg_optimizer_multiple_layers_and_nodes():
    """Verifies multi-layer count and total node counting."""
    p1 = PathRecord(
        id="l0_p1",
        color_hex="#000000",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",  # 5 nodes
        area=100.0,
    )
    p2 = PathRecord(
        id="l1_p1",
        color_hex="#FF0000",
        path_data="M 20 20 L 30 20 L 30 30 L 20 30 Z",  # 5 nodes
        area=100.0,
    )
    p3 = PathRecord(
        id="l2_p1",
        color_hex="#0000FF",
        path_data="M 40 40 C 45 40 50 45 50 50 C 50 55 45 60 40 60 Z",  # 4 nodes (M, C, C, Z)
        area=80.0,
    )

    l0 = LayerGroup(layer_id="layer_00", label="00 - Base", color_hex="#000000", paths=[p1], z_index=0)
    l1 = LayerGroup(layer_id="layer_01", label="01 - Red", color_hex="#FF0000", paths=[p2], z_index=1)
    l2 = LayerGroup(layer_id="layer_02", label="02 - Blue", color_hex="#0000FF", paths=[p3], z_index=2)

    layer_data = StructuredLayerData(
        mode="layered",
        layers=[l0, l1, l2],
        dimensions=(300, 300),
    )

    optimizer = SvgOptimizer()
    result = optimizer.build_and_optimize(layer_data)

    assert result.layer_count == 3
    assert result.total_nodes == 14  # 5 + 5 + 4
    assert result.file_size == len(result.svg_content.encode("utf-8"))

    root = ET.fromstring(result.svg_content)
    groups = root.findall(f"{{{SVG_NS}}}g")
    assert len(groups) == 3
    assert [g.attrib.get("id") for g in groups] == ["layer_00", "layer_01", "layer_02"]


def test_svg_optimizer_disable_scour():
    """Verifies clean output when enable_scour=False."""
    path = PathRecord(
        id="path_raw",
        color_hex="#123456",
        path_data="M 0 0 L 50 50 Z",
        area=25.0,
        fill_rule="evenodd",
    )
    layer = LayerGroup(
        layer_id="layer_raw",
        label="Raw Layer",
        color_hex="#123456",
        paths=[path],
        z_index=0,
    )
    layer_data = StructuredLayerData(
        mode="cut_ready",
        layers=[layer],
        dimensions=(100, 100),
    )

    optimizer = SvgOptimizer()
    built = optimizer.build_svg(layer_data)
    optimized = optimizer.optimize(built, enable_scour=False)

    assert optimized == built
    assert 'fill-rule="evenodd"' in optimized

    result = optimizer.build_and_optimize(layer_data, enable_scour=False)
    assert result.svg_content == built
    assert result.layer_count == 1
    assert result.total_nodes == 3


def test_svg_optimizer_empty_layer_data():
    """Verifies graceful handling of empty layers."""
    layer_data = StructuredLayerData(
        mode="cut_ready",
        layers=[],
        dimensions=(250, 250),
    )

    optimizer = SvgOptimizer()
    result = optimizer.build_and_optimize(layer_data)

    assert result.layer_count == 0
    assert result.total_nodes == 0
    assert result.file_size == len(result.svg_content.encode("utf-8"))
    assert "<svg" in result.svg_content

    root = ET.fromstring(result.svg_content)
    assert root.tag == f"{{{SVG_NS}}}svg"
    assert len(root.findall(f"{{{SVG_NS}}}g")) == 0


def test_svg_optimizer_scour_failure_fallback():
    """Verifies fallback to unoptimized SVG string if Scour encounters an unexpected error."""
    svg_input = '<svg xmlns="http://www.w3.org/2000/svg"><g id="l1"></g></svg>'
    optimizer = SvgOptimizer()

    with patch("scour.scour.scourString", side_effect=RuntimeError("Scour internal failure")):
        result = optimizer.optimize(svg_input, enable_scour=True)
        assert result == svg_input


def test_svg_optimizer_default_dimensions_fallback():
    """Verifies dimensions fall back to layer_data.dimensions when dimensions is None."""
    layer_data = StructuredLayerData(
        mode="cut_ready",
        layers=[],
        dimensions=(420, 280),
    )
    optimizer = SvgOptimizer()
    svg = optimizer.build_svg(layer_data, dimensions=None)
    assert 'viewBox="0 0 420 280"' in svg
    assert 'width="420"' in svg
    assert 'height="280"' in svg


def test_optimizer_silhouette_fill_rule_evenodd():
    """Assert fill-rule="evenodd" is rendered in <path> tags for silhouette mode."""
    layer = LayerGroup(
        layer_id="layer_01",
        label="01 - #E2830B",
        z_index=1,
        color_hex="#E2830B",
        paths=[PathRecord(path_id="p1", path_data="M 0 0 L 10 0 L 10 10 Z", color_hex="#E2830B", area=50.0)],
    )
    layer_data = StructuredLayerData(layers=[layer], dimensions=(100, 100), mode="silhouette")
    optimizer = SvgOptimizer()
    svg = optimizer.build_svg(layer_data)
    assert 'fill-rule="evenodd"' in svg
