"""Unit tests for inkmcp.vectorizer.trapping."""

import pytest
from shapely.geometry import box, MultiPolygon, Polygon

from inkmcp.vectorizer.core import PathRecord, parse_svg_path_to_rings
from inkmcp.vectorizer.topology import LayerGroup
from inkmcp.vectorizer.trapping import (
    compute_color_luminance,
    apply_choke_spread_trapping,
)


def test_compute_color_luminance():
    """Correctly orders yellow > red > navy."""
    lum_yellow = compute_color_luminance("#ffff00")
    lum_red = compute_color_luminance("#ff0000")
    lum_navy = compute_color_luminance("#000080")
    lum_white = compute_color_luminance("#ffffff")
    lum_black = compute_color_luminance("#000000")

    assert lum_white > lum_yellow > lum_red > lum_navy > lum_black
    assert 0.8 <= lum_yellow <= 0.95
    assert 0.25 <= lum_red <= 0.4
    assert 0.05 <= lum_navy <= 0.15


def test_apply_choke_spread_trapping_overlap():
    """Two adjoining polygons produce an underlap where lighter expands under darker."""
    # Yellow box at [0, 0, 50, 100]
    p_yellow = PathRecord(
        id="p_yellow",
        color_hex="#ffff00",
        path_data="M 0 0 L 50 0 L 50 100 L 0 100 Z",
        area=5000.0,
    )
    # Navy box at [50, 0, 100, 100]
    p_navy = PathRecord(
        id="p_navy",
        color_hex="#000080",
        path_data="M 50 0 L 100 0 L 100 100 L 50 100 Z",
        area=5000.0,
    )

    layer_yellow = LayerGroup(
        layer_id="layer_yellow",
        label="Yellow",
        color_hex="#ffff00",
        paths=[p_yellow],
        z_index=1,
    )
    layer_navy = LayerGroup(
        layer_id="layer_navy",
        label="Navy",
        color_hex="#000080",
        paths=[p_navy],
        z_index=0,
    )

    trapped_layers = apply_choke_spread_trapping(
        [layer_yellow, layer_navy], trap_distance=1.0
    )

    trapped_yellow_path = trapped_layers[0].paths[0]
    rings = parse_svg_path_to_rings(trapped_yellow_path.path_data)
    poly_yellow = Polygon(rings[0])

    # Yellow area must expand from 5000 to approximately 5100 (50 to 51 x-span)
    assert poly_yellow.area > 5050.0
    # The max x-coordinate of yellow must now be ~51 (extended under navy)
    minx, miny, maxx, maxy = poly_yellow.bounds
    assert maxx >= 50.9


def test_trapping_preserves_outer_silhouette():
    """Verifies that trapping never expands beyond the total outer design boundary."""
    # A design spanning [10, 10, 90, 90]
    p_yellow = PathRecord(
        id="p1",
        color_hex="#ffff00",
        path_data="M 10 10 L 50 10 L 50 90 L 10 90 Z",
        area=3200.0,
    )
    p_navy = PathRecord(
        id="p2",
        color_hex="#000080",
        path_data="M 50 10 L 90 10 L 90 90 L 50 90 Z",
        area=3200.0,
    )

    layer1 = LayerGroup(layer_id="l1", label="L1", color_hex="#ffff00", paths=[p_yellow], z_index=1)
    layer2 = LayerGroup(layer_id="l2", label="L2", color_hex="#000080", paths=[p_navy], z_index=0)

    trapped = apply_choke_spread_trapping([layer1, layer2], trap_distance=2.0)

    # Check that neither polygon extends beyond minx < 10, miny < 10, maxx > 90, maxy > 90
    for l in trapped:
        for p in l.paths:
            rings = parse_svg_path_to_rings(p.path_data)
            poly = Polygon(rings[0])
            minx, miny, maxx, maxy = poly.bounds
            assert minx >= 9.9
            assert miny >= 9.9
            assert maxx <= 90.1
            assert maxy <= 90.1
