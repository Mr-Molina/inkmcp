"""Unit tests for inkmcp.vectorizer.cam_planner."""


from inkmcp.vectorizer.core import PathRecord
from inkmcp.vectorizer.cam_planner import (
    CamPlanResult,
    order_inside_out_cuts,
    optimize_traverse_tsp,
    optimize_cam_toolpaths,
)


def test_order_inside_out_cuts():
    """Interior aperture cuts must precede the outer boundary cut."""
    # Donut: Outer boundary at [0, 0, 100, 100], Inner aperture at [30, 30, 70, 70]
    p_outer = PathRecord(
        id="outer_boundary",
        color_hex="#000000",
        path_data="M 0 0 L 100 0 L 100 100 L 0 100 Z",
        area=10000.0,
    )
    p_inner = PathRecord(
        id="inner_hole",
        color_hex="#ffffff",
        path_data="M 30 30 L 70 30 L 70 70 L 30 70 Z",
        area=1600.0,
    )

    # Pass in [outer, inner]
    ordered = order_inside_out_cuts([p_outer, p_inner])

    # Inner hole MUST be cut strictly first
    assert ordered[0].id == "inner_hole"
    assert ordered[1].id == "outer_boundary"


def test_optimize_traverse_tsp():
    """Greedy TSP reordering reduces rapid traverse distance by >= 30%."""
    # 6 square paths scattered in zig-zag order: 0, 100, 20, 80, 40, 60
    xs = [0, 100, 20, 80, 40, 60]
    paths = []
    for i, x in enumerate(xs):
        p = PathRecord(
            id=f"box_{x}",
            color_hex="#000000",
            path_data=f"M {x} 0 L {x+5} 0 L {x+5} 5 L {x} 5 Z",
            area=25.0,
        )
        paths.append(p)

    reordered, orig_dist, opt_dist = optimize_traverse_tsp(paths)

    assert orig_dist > opt_dist
    reduction = (orig_dist - opt_dist) / orig_dist * 100.0
    assert reduction >= 30.0

    # The reordered sequence should travel smoothly without large zig-zags
    reordered_ids = [p.id for p in reordered]
    assert reordered_ids in (
        ["box_0", "box_20", "box_40", "box_60", "box_80", "box_100"],
        ["box_100", "box_80", "box_60", "box_40", "box_20", "box_0"],
    )


def test_optimize_cam_toolpaths_end_to_end():
    """Verifies complete CAM plan result with inside-out precedence and traverse metrics."""
    # Enclosed donut with aperture plus a remote square
    p_outer = PathRecord(
        id="donut_outer",
        color_hex="#000000",
        path_data="M 0 0 L 100 0 L 100 100 L 0 100 Z",
        area=10000.0,
    )
    p_hole = PathRecord(
        id="donut_hole",
        color_hex="#ffffff",
        path_data="M 30 30 L 70 30 L 70 70 L 30 70 Z",
        area=1600.0,
    )
    p_remote = PathRecord(
        id="remote_box",
        color_hex="#000000",
        path_data="M 150 150 L 160 150 L 160 160 L 150 160 Z",
        area=100.0,
    )

    result = optimize_cam_toolpaths([p_outer, p_remote, p_hole])

    assert isinstance(result, CamPlanResult)
    ordered_ids = [p.id for p in result.ordered_paths]
    assert ordered_ids.index("donut_hole") < ordered_ids.index("donut_outer")
    assert result.inside_out_cut_count >= 1
    assert result.optimized_traverse_distance <= result.original_traverse_distance
