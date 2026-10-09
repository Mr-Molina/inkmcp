"""Tests for vectorizer perceptual color standardization and palette clustering."""

import pytest
from inkmcp.vectorizer.core import PathRecord
from inkmcp.vectorizer.palette import (
    delta_e_cie76,
    hex_to_rgb,
    rgb_to_lab,
    standardize_color_palette,
)
from inkmcp.vectorizer.topology import TopologyEngine


def test_hex_to_rgb_conversions():
    """Verify hex color parsing across standard, shorthand, and edge cases."""
    assert hex_to_rgb("#EF6930") == (239, 105, 48)
    assert hex_to_rgb("#F06930") == (240, 105, 48)
    assert hex_to_rgb("#FFFFFF") == (255, 255, 255)
    assert hex_to_rgb("#000000") == (0, 0, 0)
    assert hex_to_rgb("#FFF") == (255, 255, 255)
    assert hex_to_rgb("#000") == (0, 0, 0)
    assert hex_to_rgb("EF6930") == (239, 105, 48)
    assert hex_to_rgb("red") == (255, 0, 0)
    assert hex_to_rgb("rgb(10, 20, 30)") == (10, 20, 30)
    assert hex_to_rgb("") == (0, 0, 0)


def test_rgb_to_lab_conversions():
    """Verify sRGB to CIELAB standard D65 observer color transformation."""
    # Pure black
    lab_black = rgb_to_lab((0, 0, 0))
    assert pytest.approx(lab_black[0], abs=1e-2) == 0.0
    assert pytest.approx(lab_black[1], abs=1e-2) == 0.0
    assert pytest.approx(lab_black[2], abs=1e-2) == 0.0

    # Pure white
    lab_white = rgb_to_lab((255, 255, 255))
    assert pytest.approx(lab_white[0], abs=1e-2) == 100.0
    assert pytest.approx(lab_white[1], abs=1e-2) == 0.0
    assert pytest.approx(lab_white[2], abs=1e-2) == 0.0

    # Pure red standard sRGB reference (L* ~ 53.24, a* ~ 80.09, b* ~ 67.20)
    lab_red = rgb_to_lab((255, 0, 0))
    assert 52.0 < lab_red[0] < 55.0
    assert 78.0 < lab_red[1] < 82.0
    assert 65.0 < lab_red[2] < 70.0


def test_delta_e_cie76_calculation():
    """Verify Delta E CIE76 calculations and near-identical color threshold."""
    # Identical colors must have distance 0
    lab_orange1 = rgb_to_lab(hex_to_rgb("#EF6930"))
    assert delta_e_cie76(lab_orange1, lab_orange1) == 0.0

    # Specifically assert delta_e between #EF6930 and #F06930 is < 1.0
    lab_orange2 = rgb_to_lab(hex_to_rgb("#F06930"))
    de_oranges = delta_e_cie76(lab_orange1, lab_orange2)
    assert de_oranges < 1.0
    assert de_oranges > 0.0

    # Black and white must have distance 100.0
    lab_black = rgb_to_lab((0, 0, 0))
    lab_white = rgb_to_lab((255, 255, 255))
    assert pytest.approx(delta_e_cie76(lab_black, lab_white), abs=1e-2) == 100.0

    # Distinct colors (red vs cyan) must have large distance
    lab_cyan = rgb_to_lab((0, 255, 255))
    lab_red = rgb_to_lab((255, 0, 0))
    assert delta_e_cie76(lab_red, lab_cyan) > 50.0


def test_standardize_color_palette_merges_to_larger_area():
    """Verify merging clusters near-identical colors to the anchor with larger area."""
    # Scenario A: #EF6930 is larger than #F06930
    palette_a = {"#EF6930": 1000.0, "#F06930": 300.0}
    map_a = standardize_color_palette(palette_a, delta_e_threshold=5.0)
    assert map_a["#EF6930"] == "#EF6930"
    assert map_a["#F06930"] == "#EF6930"

    # Scenario B: #F06930 is larger than #EF6930
    palette_b = {"#EF6930": 200.0, "#F06930": 800.0}
    map_b = standardize_color_palette(palette_b, delta_e_threshold=5.0)
    assert map_b["#EF6930"] == "#F06930"
    assert map_b["#F06930"] == "#F06930"

    # Preserves perceptually distinct colors
    palette_multi = {
        "#EF6930": 1000.0,
        "#F06930": 300.0,
        "#0000FF": 500.0,
    }
    map_multi = standardize_color_palette(palette_multi, delta_e_threshold=5.0)
    assert map_multi["#EF6930"] == "#EF6930"
    assert map_multi["#F06930"] == "#EF6930"
    assert map_multi["#0000FF"] == "#0000FF"

    # Empty palette
    assert standardize_color_palette({}) == {}


def test_standardize_color_palette_zero_tolerance():
    """Verify delta_e_threshold <= 0.0 disables merging and preserves identity."""
    palette = {"#EF6930": 1000.0, "#F06930": 300.0}
    map_zero = standardize_color_palette(palette, delta_e_threshold=0.0)
    assert map_zero["#EF6930"] == "#EF6930"
    assert map_zero["#F06930"] == "#F06930"

    map_neg = standardize_color_palette(palette, delta_e_threshold=-1.0)
    assert map_neg["#EF6930"] == "#EF6930"
    assert map_neg["#F06930"] == "#F06930"


def test_topology_engine_color_merging_integration():
    """Verify TopologyEngine groups near-identical colors into a single LayerGroup."""
    engine = TopologyEngine()

    p1 = PathRecord(
        id="p1",
        color_hex="#EF6930",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",
        area=100.0,
    )
    p2 = PathRecord(
        id="p2",
        color_hex="#F06930",
        path_data="M 20 0 L 30 0 L 30 10 L 20 10 Z",
        area=50.0,
    )

    # 1. With color_tolerance=5.0, #EF6930 and #F06930 must be consolidated into 1 layer
    structured = engine.process([p1, p2], mode="cut_ready", color_tolerance=5.0)
    assert len(structured.layers) == 1
    consolidated_layer = structured.layers[0]
    assert consolidated_layer.color_hex == "#EF6930"
    assert len(consolidated_layer.paths) == 2
    for path in consolidated_layer.paths:
        assert path.color_hex == "#EF6930"

    # 2. With color_tolerance=0.0, both colors must remain separate layers
    p1_orig = PathRecord(
        id="p1",
        color_hex="#EF6930",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",
        area=100.0,
    )
    p2_orig = PathRecord(
        id="p2",
        color_hex="#F06930",
        path_data="M 20 0 L 30 0 L 30 10 L 20 10 Z",
        area=50.0,
    )
    structured_separate = engine.process([p1_orig, p2_orig], mode="cut_ready", color_tolerance=0.0)
    assert len(structured_separate.layers) == 2
    layer_colors = {layer.color_hex for layer in structured_separate.layers}
    assert layer_colors == {"#EF6930", "#F06930"}

    # 3. Layered mandala stack consolidation
    p1_stack = PathRecord(
        id="p1",
        color_hex="#EF6930",
        path_data="M 0 0 L 10 0 L 10 10 L 0 10 Z",
        area=100.0,
    )
    p2_stack = PathRecord(
        id="p2",
        color_hex="#F06930",
        path_data="M 20 0 L 30 0 L 30 10 L 20 10 Z",
        area=50.0,
    )
    structured_layered = engine.process([p1_stack, p2_stack], mode="layered", color_tolerance=5.0)
    # Layer 0: Base silhouette backing, Layer 1: Consolidated orange layer
    assert len(structured_layered.layers) == 2
    assert "Base Silhouette" in structured_layered.layers[0].label or "00_base" in structured_layered.layers[0].layer_id
    assert structured_layered.layers[1].color_hex == "#EF6930"
    assert len(structured_layered.layers[1].paths) == 2
