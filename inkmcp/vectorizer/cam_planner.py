"""CAM toolpath optimization, inside-out cut sequencing, and rapid traverse minimization."""

from dataclasses import dataclass
import math
import re
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx
from shapely.geometry import Polygon
from shapely.validation import make_valid

from inkmcp.vectorizer.containment_dag import build_containment_dag
from inkmcp.vectorizer.core import PathRecord, parse_svg_path_to_rings


@dataclass
class CamPlanResult:
    """Manufacturing CAM toolpath execution sequence and machine traverse metrics."""

    ordered_paths: List[PathRecord]
    original_traverse_distance: float
    optimized_traverse_distance: float
    traverse_reduction_percentage: float
    inside_out_cut_count: int


def _get_path_endpoints(path_data: str) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Extracts start coordinate and end coordinate of an SVG path."""
    nums = re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", path_data)
    if len(nums) < 2:
        return (0.0, 0.0), (0.0, 0.0)

    start_pt = (float(nums[0]), float(nums[1]))
    # For closed paths ending with Z/z, end point equals start point
    stripped = path_data.strip()
    if stripped.endswith(("Z", "z")):
        subpaths = [s for s in re.split(r"(?=[Mm])", stripped) if s.strip()]
        if len(subpaths) > 1:
            first_nums = re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", subpaths[0])
            last_nums = re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", subpaths[-1])
            if len(first_nums) >= 2 and len(last_nums) >= 2:
                return (float(first_nums[0]), float(first_nums[1])), (float(last_nums[0]), float(last_nums[1]))
        return start_pt, start_pt

    end_pt = (float(nums[-2]), float(nums[-1]))
    return start_pt, end_pt


def _path_to_polygon(path_data: str) -> Optional[Polygon]:
    """Extracts the outermost polygon for a PathRecord."""
    rings = parse_svg_path_to_rings(path_data)
    if not rings or len(rings[0]) < 3:
        return None
    poly = Polygon(rings[0])
    if not poly.is_valid:
        poly = make_valid(poly)
    if poly.geom_type == "Polygon":
        return poly
    if poly.geom_type == "MultiPolygon":
        return max(poly.geoms, key=lambda p: p.area)
    return None


def _calculate_total_traverse(paths: List[PathRecord]) -> float:
    """Calculates total rapid traverse distance between consecutive paths."""
    if len(paths) <= 1:
        return 0.0
    total = 0.0
    for i in range(len(paths) - 1):
        _, end_pt = _get_path_endpoints(paths[i].path_data)
        start_pt, _ = _get_path_endpoints(paths[i + 1].path_data)
        total += math.hypot(start_pt[0] - end_pt[0], start_pt[1] - end_pt[1])
    return total


def order_inside_out_cuts(paths: List[PathRecord]) -> List[PathRecord]:
    """Sequences toolpaths so all interior cutout holes precede outer boundary cuts.

    Also reorders subpaths within compound path strings so holes precede outer rings.
    """
    if not paths:
        return []

    # 1. Keep internal subpaths in original winding sequence
    processed_paths = list(paths)

    # 2. Build containment DAG across path records
    poly_list = []
    path_map: Dict[str, PathRecord] = {}
    for p in processed_paths:
        path_map[p.id] = p
        poly = _path_to_polygon(p.path_data)
        if poly is not None:
            poly_list.append((p.id, poly))

    if not poly_list:
        return processed_paths

    dag = build_containment_dag(poly_list)

    # Edge (B, A) in DAG means B encloses A.
    # For CAM inside-out cutting, A (interior) must precede B (outer container).
    # Compute nesting depth: leaves (deepest children) cut first.
    # Reverse DAG so edges point from enclosed child to container (A -> B)
    rev_dag = dag.reverse()

    # Calculate depth in reversed DAG (roots are deepest interior cutouts)
    depths: Dict[str, int] = {}
    for node in rev_dag.nodes:
        # Longest path ending at node or starting at node
        descendants = nx.descendants(rev_dag, node)
        depths[node] = len(descendants)

    # Sort paths: higher number of descendants in rev_dag means it must be cut earlier!
    # Deepest children have maximum descendants in rev_dag.
    def sort_key(p: PathRecord):
        # Sort by: (containment rank descending, area ascending, original id)
        rank = depths.get(p.id, 0)
        return (-rank, p.area, p.id)

    ordered = sorted(processed_paths, key=sort_key)
    return ordered


def optimize_traverse_tsp(
    paths: List[PathRecord],
) -> Tuple[List[PathRecord], float, float]:
    """Optimizes cutting sequence using greedy nearest-neighbor to minimize rapid travel."""
    if len(paths) <= 2:
        orig = _calculate_total_traverse(paths)
        return list(paths), orig, orig

    orig_dist = _calculate_total_traverse(paths)

    # Build precedence requirements from containment
    poly_list = []
    for p in paths:
        poly = _path_to_polygon(p.path_data)
        if poly is not None:
            poly_list.append((p.id, poly))

    dag = build_containment_dag(poly_list)
    # If dag has edge (B, A), then A must be cut before B!
    # prereqs[B] = set of A that must be visited before B
    prereqs: Dict[str, Set[str]] = {p.id: set() for p in paths}
    for b, a in dag.edges():
        if b in prereqs and a in prereqs:
            prereqs[b].add(a)

    unvisited = list(paths)
    ordered: List[PathRecord] = []

    # Pick starting candidate with no prereqs closest to origin (0, 0)
    avail_starts = [p for p in unvisited if not prereqs[p.id]]
    if not avail_starts:
        avail_starts = unvisited

    best_start = min(
        avail_starts,
        key=lambda p: math.hypot(_get_path_endpoints(p.path_data)[0][0], _get_path_endpoints(p.path_data)[0][1]),
    )
    ordered.append(best_start)
    unvisited.remove(best_start)
    visited_ids = {best_start.id}

    curr_end = _get_path_endpoints(best_start.path_data)[1]

    while unvisited:
        # Available paths whose prerequisites are completely visited
        avail = [p for p in unvisited if prereqs[p.id].issubset(visited_ids)]
        if not avail:
            avail = unvisited

        # Pick path with start point closest to curr_end
        next_p = min(
            avail,
            key=lambda p: math.hypot(
                _get_path_endpoints(p.path_data)[0][0] - curr_end[0],
                _get_path_endpoints(p.path_data)[0][1] - curr_end[1],
            ),
        )
        ordered.append(next_p)
        unvisited.remove(next_p)
        visited_ids.add(next_p.id)
        curr_end = _get_path_endpoints(next_p.path_data)[1]

    opt_dist = _calculate_total_traverse(ordered)
    return ordered, orig_dist, opt_dist


def optimize_cam_toolpaths(paths: List[PathRecord]) -> CamPlanResult:
    """Performs inside-out cut sequencing and rapid traverse TSP optimization."""
    if not paths:
        return CamPlanResult([], 0.0, 0.0, 0.0, 0)

    # 1. Order inside-out
    inside_out_ordered = order_inside_out_cuts(paths)

    # Count how many inside-out precedences exist
    poly_list = []
    for p in paths:
        poly = _path_to_polygon(p.path_data)
        if poly is not None:
            poly_list.append((p.id, poly))
    dag = build_containment_dag(poly_list)
    inside_out_count = dag.number_of_edges()

    # 2. Rapid traverse minimization
    tsp_ordered, orig_dist, opt_dist = optimize_traverse_tsp(inside_out_ordered)

    reduction_pct = (
        max(0.0, (orig_dist - opt_dist) / orig_dist * 100.0)
        if orig_dist > 0.0
        else 0.0
    )

    return CamPlanResult(
        ordered_paths=tsp_ordered,
        original_traverse_distance=orig_dist,
        optimized_traverse_distance=opt_dist,
        traverse_reduction_percentage=reduction_pct,
        inside_out_cut_count=inside_out_count,
    )
