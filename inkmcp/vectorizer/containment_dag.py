"""Topological containment DAG and deterministic z-stacking engine."""

import logging
from typing import Dict, List, Tuple

import networkx as nx
from shapely.geometry import Polygon
from shapely.validation import make_valid

logger = logging.getLogger(__name__)


def build_containment_dag(polygons: List[Tuple[str, Polygon]]) -> nx.DiGraph:
    """Builds a Directed Acyclic Graph representing spatial containment relationships.

    Edge (A, B) indicates that polygon A spatially encloses polygon B (A is the container).
    Transitive reduction is applied so edges represent immediate nesting hierarchies.

    Args:
        polygons: List of (shape_id, shapely_geom) tuples.

    Returns:
        Acyclic networkx DiGraph with node attributes 'area' and 'geom'.
    """
    raw_dag = nx.DiGraph()

    valid_entries = []
    for shape_id, poly in polygons:
        if not poly.is_valid:
            poly = make_valid(poly)
        area = poly.area if hasattr(poly, "area") else 0.0
        raw_dag.add_node(shape_id, area=area, geom=poly)
        valid_entries.append((shape_id, poly, area))

    # Sort shapes by area descending (largest first)
    valid_entries.sort(key=lambda item: item[2], reverse=True)
    n = len(valid_entries)

    for i in range(n):
        id_i, poly_i, area_i = valid_entries[i]
        if area_i <= 0:
            continue
        minx_i, miny_i, maxx_i, maxy_i = poly_i.bounds

        for j in range(i + 1, n):
            id_j, poly_j, area_j = valid_entries[j]
            if area_j <= 0 or area_j >= area_i:
                continue

            minx_j, miny_j, maxx_j, maxy_j = poly_j.bounds

            # Quick bounding box containment check (with 0.1px tolerance)
            if (
                minx_i <= minx_j + 0.1
                and miny_i <= miny_j + 0.1
                and maxx_i >= maxx_j - 0.1
                and maxy_i >= maxy_j - 0.1
            ):
                # Detailed polygon containment check
                if poly_i.contains(poly_j) or poly_j.within(poly_i):
                    raw_dag.add_edge(id_i, id_j)
                else:
                    # Robust intersection ratio check for slightly overlapping digitized borders
                    try:
                        inter_area = poly_i.intersection(poly_j).area
                        if inter_area / area_j > 0.88:
                            raw_dag.add_edge(id_i, id_j)
                    except Exception:
                        pass

    # Ensure graph is strictly a DAG
    if not nx.is_directed_acyclic_graph(raw_dag):
        # Break any unexpected cycles by removing edges that go from smaller to larger area
        cycles = list(nx.simple_cycles(raw_dag))
        for cycle in cycles:
            for u, v in zip(cycle, cycle[1:] + [cycle[0]]):
                if (
                    raw_dag.has_edge(u, v)
                    and raw_dag.nodes[u]["area"] <= raw_dag.nodes[v]["area"]
                ):
                    raw_dag.remove_edge(u, v)

    # Apply transitive reduction to keep only direct containment relationships
    try:
        reduced_dag = nx.transitive_reduction(raw_dag)
        # Restore node attributes
        for node in raw_dag.nodes:
            reduced_dag.add_node(node, **raw_dag.nodes[node])
        return reduced_dag
    except Exception:
        return raw_dag


def resolve_stacking_order(dag: nx.DiGraph) -> List[str]:
    """Resolves deterministic physical z-stacking order from base plate to top accents.

    Orders elements so enclosing containers appear first (bottom of stack), followed by
    interior nested elements on top. Disjoint elements are ordered by area descending.

    Args:
        dag: Containment DiGraph.

    Returns:
        List of shape IDs in fabrication stacking order.
    """
    if len(dag) == 0:
        return []

    # Calculate containment depth for each node (longest path from any root)
    depths: Dict[str, int] = {node: 0 for node in dag.nodes}

    for u in nx.topological_sort(dag):
        for v in dag.successors(u):
            depths[v] = max(depths[v], depths[u] + 1)

    # Sort nodes by: (depth ascending, area descending, shape_id)
    sorted_nodes = sorted(
        dag.nodes,
        key=lambda n: (depths[n], -dag.nodes[n].get("area", 0.0), str(n)),
    )
    return sorted_nodes
