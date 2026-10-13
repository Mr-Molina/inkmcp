"""Unit tests for inkmcp.vectorizer.containment_dag."""

import networkx as nx
from shapely.geometry import Point, box

from inkmcp.vectorizer.containment_dag import (
    build_containment_dag,
    resolve_stacking_order,
)


def test_build_containment_dag_nested_circles():
    """Pupil inside iris inside eyeball creates directed containment edges."""
    center = Point(100, 100)
    poly_eyeball = center.buffer(50)  # Area ~ 7854
    poly_iris = center.buffer(25)     # Area ~ 1963
    poly_pupil = center.buffer(10)    # Area ~ 314

    polys = [
        ("pupil", poly_pupil),
        ("eyeball", poly_eyeball),
        ("iris", poly_iris),
    ]

    dag = build_containment_dag(polys)

    assert nx.is_directed_acyclic_graph(dag)
    assert dag.has_edge("eyeball", "iris")
    assert dag.has_edge("iris", "pupil")
    assert not dag.has_edge("pupil", "eyeball")


def test_resolve_stacking_order():
    """Topological sort outputs base plate first, followed by successive interior layers."""
    center = Point(100, 100)
    poly_eyeball = center.buffer(50)
    poly_iris = center.buffer(25)
    poly_pupil = center.buffer(10)

    polys = [
        ("pupil", poly_pupil),
        ("eyeball", poly_eyeball),
        ("iris", poly_iris),
    ]

    dag = build_containment_dag(polys)
    order = resolve_stacking_order(dag)

    assert order == ["eyeball", "iris", "pupil"]


def test_containment_dag_disjoint_islands():
    """Multiple unconnected shapes are partitioned cleanly into independent subtrees."""
    # Island 1: at x in [0, 50]
    box1_outer = box(0, 0, 50, 50)
    box1_inner = box(10, 10, 40, 40)

    # Island 2: at x in [100, 150]
    box2_outer = box(100, 0, 150, 50)
    box2_inner = box(110, 10, 140, 40)

    polys = [
        ("island1_inner", box1_inner),
        ("island2_inner", box2_inner),
        ("island1_outer", box1_outer),
        ("island2_outer", box2_outer),
    ]

    dag = build_containment_dag(polys)
    assert nx.is_directed_acyclic_graph(dag)

    # Directed edges within each island
    assert dag.has_edge("island1_outer", "island1_inner")
    assert dag.has_edge("island2_outer", "island2_inner")

    # No cross edges between disjoint islands
    assert not dag.has_edge("island1_outer", "island2_outer")
    assert not dag.has_edge("island2_outer", "island1_outer")

    order = resolve_stacking_order(dag)
    # Both outers must precede their respective inners
    assert order.index("island1_outer") < order.index("island1_inner")
    assert order.index("island2_outer") < order.index("island2_inner")
