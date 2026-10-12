"""Node analysis, micro-segment decimation, Schneider Bezier fitting, and G1 fairing."""

from dataclasses import dataclass
import math
import re
from typing import List, Optional, Tuple

import numpy as np

from inkmcp.vectorizer.core import _format_coord


@dataclass
class NodeMetrics:
    """Quantitative node complexity and CAM machine chatter metrics."""

    original_node_count: int
    optimized_node_count: int
    reduction_percentage: float
    max_geometric_deviation: float
    estimated_cut_time_reduction_pct: float


def _count_path_nodes(d_str: str) -> int:
    """Counts command node tokens in an SVG path string."""
    if not d_str or not d_str.strip():
        return 0
    return len(re.findall(r"[MmLlHhVvCcSsQqTtAaZz]", d_str))


def _dist(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def _unit_vector(v: Tuple[float, float]) -> Tuple[float, float]:
    length = math.hypot(v[0], v[1])
    if length < 1e-9:
        return (0.0, 0.0)
    return (v[0] / length, v[1] / length)


def _dot(v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
    return v1[0] * v2[0] + v1[1] * v2[1]


def parse_path_commands(d_str: str) -> List[Tuple[str, List[float]]]:
    """Parses and normalizes SVG path data into canonical absolute M, L, C, Z commands.

    Handles both absolute and relative commands (m, l, h, v, c, s, q, z) and multiple
    coordinate groups without explicit command repeats.
    """
    if not d_str or not d_str.strip():
        return []

    tokens = re.findall(
        r"([a-zA-Z])|([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)", d_str
    )
    raw_tokens = []
    for letter, num in tokens:
        if letter:
            raw_tokens.append(letter)
        elif num:
            raw_tokens.append(float(num))

    commands: List[Tuple[str, List[float]]] = []
    idx = 0
    curr_pt = (0.0, 0.0)
    start_pt = (0.0, 0.0)
    curr_cmd = ""

    while idx < len(raw_tokens):
        tok = raw_tokens[idx]
        if isinstance(tok, str):
            curr_cmd = tok
            idx += 1
            if curr_cmd in ("Z", "z"):
                commands.append(("Z", []))
                curr_pt = start_pt
                continue
            continue

        if curr_cmd in ("M", "m"):
            if idx + 1 >= len(raw_tokens) or isinstance(raw_tokens[idx], str):
                continue
            x = float(raw_tokens[idx])
            y = float(raw_tokens[idx + 1])
            idx += 2
            if curr_cmd == "m":
                x += curr_pt[0]
                y += curr_pt[1]
            curr_pt = (x, y)
            start_pt = curr_pt
            commands.append(("M", [x, y]))
            curr_cmd = "L" if curr_cmd == "M" else "l"

        elif curr_cmd in ("L", "l"):
            if idx + 1 >= len(raw_tokens) or isinstance(raw_tokens[idx], str):
                continue
            x = float(raw_tokens[idx])
            y = float(raw_tokens[idx + 1])
            idx += 2
            if curr_cmd == "l":
                x += curr_pt[0]
                y += curr_pt[1]
            curr_pt = (x, y)
            commands.append(("L", [x, y]))

        elif curr_cmd in ("H", "h"):
            if idx >= len(raw_tokens) or isinstance(raw_tokens[idx], str):
                continue
            x = float(raw_tokens[idx])
            idx += 1
            if curr_cmd == "h":
                x += curr_pt[0]
            curr_pt = (x, curr_pt[1])
            commands.append(("L", [curr_pt[0], curr_pt[1]]))

        elif curr_cmd in ("V", "v"):
            if idx >= len(raw_tokens) or isinstance(raw_tokens[idx], str):
                continue
            y = float(raw_tokens[idx])
            idx += 1
            if curr_cmd == "v":
                y += curr_pt[1]
            curr_pt = (curr_pt[0], y)
            commands.append(("L", [curr_pt[0], curr_pt[1]]))

        elif curr_cmd in ("C", "c"):
            if idx + 5 >= len(raw_tokens) or any(isinstance(raw_tokens[idx + k], str) for k in range(6)):
                idx += 1
                continue
            coords = [float(raw_tokens[idx + k]) for k in range(6)]
            idx += 6
            if curr_cmd == "c":
                x1 = curr_pt[0] + coords[0]
                y1 = curr_pt[1] + coords[1]
                x2 = curr_pt[0] + coords[2]
                y2 = curr_pt[1] + coords[3]
                x3 = curr_pt[0] + coords[4]
                y3 = curr_pt[1] + coords[5]
            else:
                x1, y1, x2, y2, x3, y3 = coords
            curr_pt = (x3, y3)
            commands.append(("C", [x1, y1, x2, y2, x3, y3]))

        elif curr_cmd in ("S", "s"):
            if idx + 3 >= len(raw_tokens) or any(isinstance(raw_tokens[idx + k], str) for k in range(4)):
                idx += 1
                continue
            coords = [float(raw_tokens[idx + k]) for k in range(4)]
            idx += 4
            prev_cmd = commands[-1] if commands else None
            if prev_cmd and prev_cmd[0] == "C":
                x1 = 2 * curr_pt[0] - prev_cmd[1][2]
                y1 = 2 * curr_pt[1] - prev_cmd[1][3]
            else:
                x1, y1 = curr_pt
            if curr_cmd == "s":
                x2 = curr_pt[0] + coords[0]
                y2 = curr_pt[1] + coords[1]
                x3 = curr_pt[0] + coords[2]
                y3 = curr_pt[1] + coords[3]
            else:
                x2, y2, x3, y3 = coords
            curr_pt = (x3, y3)
            commands.append(("C", [x1, y1, x2, y2, x3, y3]))

        elif curr_cmd in ("Q", "q"):
            if idx + 3 >= len(raw_tokens) or any(isinstance(raw_tokens[idx + k], str) for k in range(4)):
                idx += 1
                continue
            coords = [float(raw_tokens[idx + k]) for k in range(4)]
            idx += 4
            if curr_cmd == "q":
                qx = curr_pt[0] + coords[0]
                qy = curr_pt[1] + coords[1]
                qx3 = curr_pt[0] + coords[2]
                qy3 = curr_pt[1] + coords[3]
            else:
                qx, qy, qx3, qy3 = coords
            cx1 = curr_pt[0] + (2.0 / 3.0) * (qx - curr_pt[0])
            cy1 = curr_pt[1] + (2.0 / 3.0) * (qy - curr_pt[1])
            cx2 = qx3 + (2.0 / 3.0) * (qx - qx3)
            cy2 = qy3 + (2.0 / 3.0) * (qy - qy3)
            curr_pt = (qx3, qy3)
            commands.append(("C", [cx1, cy1, cx2, cy2, qx3, qy3]))

        elif curr_cmd in ("Z", "z"):
            commands.append(("Z", []))
            curr_pt = start_pt
            idx += 1
        else:
            idx += 1

    return commands


def prune_micro_segments(d_str: str, min_length: float = 0.2) -> str:
    """Removes redundant sub-pixel moves (< min_length) without altering closed path topology."""
    commands = parse_path_commands(d_str)
    if not commands:
        return d_str

    out_commands = []
    curr_pt = (0.0, 0.0)
    start_pt = (0.0, 0.0)

    for i, (cmd, args) in enumerate(commands):
        if cmd == "M":
            curr_pt = (args[0], args[1])
            start_pt = curr_pt
            out_commands.append((cmd, args[:2]))
        elif cmd == "L":
            target_pt = (args[0], args[1])
            dist = _dist(curr_pt, target_pt)
            is_near_close = (i + 1 < len(commands) and commands[i + 1][0] == "Z")
            if dist >= min_length or is_near_close:
                out_commands.append((cmd, [target_pt[0], target_pt[1]]))
                curr_pt = target_pt
            else:
                continue
        elif cmd == "Z":
            out_commands.append((cmd, []))
            curr_pt = start_pt
        elif cmd == "C":
            p1 = (args[0], args[1])
            p2 = (args[2], args[3])
            p3 = (args[4], args[5])
            if (
                _dist(curr_pt, p1) < min_length
                and _dist(curr_pt, p2) < min_length
                and _dist(curr_pt, p3) < min_length
            ):
                continue
            out_commands.append((cmd, args[:6]))
            curr_pt = p3
        else:
            out_commands.append((cmd, args))

    parts = []
    for cmd, args in out_commands:
        if args:
            parts.append(f"{cmd} {' '.join(_format_coord(a) for a in args)}")
        else:
            parts.append(cmd)
    return " ".join(parts)


def _bezier_eval(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    u: float,
) -> Tuple[float, float]:
    """Evaluates cubic Bezier at parameter u in [0, 1]."""
    u2 = u * u
    u3 = u2 * u
    omt = 1.0 - u
    omt2 = omt * omt
    omt3 = omt2 * omt
    x = omt3 * p0[0] + 3.0 * omt2 * u * p1[0] + 3.0 * omt * u2 * p2[0] + u3 * p3[0]
    y = omt3 * p0[1] + 3.0 * omt2 * u * p1[1] + 3.0 * omt * u2 * p2[1] + u3 * p3[1]
    return (x, y)


def _bezier_deriv(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    u: float,
) -> Tuple[float, float]:
    """First derivative B'(u)."""
    omt = 1.0 - u
    omt2 = omt * omt
    u2 = u * u
    c1 = 3.0 * omt2
    c2 = 6.0 * omt * u
    c3 = 3.0 * u2
    x = c1 * (p1[0] - p0[0]) + c2 * (p2[0] - p1[0]) + c3 * (p3[0] - p2[0])
    y = c1 * (p1[1] - p0[1]) + c2 * (p2[1] - p1[1]) + c3 * (p3[1] - p2[1])
    return (x, y)


def _bezier_deriv2(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    u: float,
) -> Tuple[float, float]:
    """Second derivative B''(u)."""
    omt = 1.0 - u
    c1 = 6.0 * omt
    c2 = 6.0 * u
    x = c1 * (p2[0] - 2 * p1[0] + p0[0]) + c2 * (p3[0] - 2 * p2[0] + p1[0])
    y = c1 * (p2[1] - 2 * p1[1] + p0[1]) + c2 * (p3[1] - 2 * p2[1] + p1[1])
    return (x, y)


def _chord_length_parameterize(points: List[Tuple[float, float]]) -> List[float]:
    """Generates normalized chord-length parameters for points."""
    u = [0.0]
    for i in range(1, len(points)):
        u.append(u[i - 1] + _dist(points[i], points[i - 1]))
    total = u[-1]
    if total < 1e-9:
        return [float(i) / (len(points) - 1) for i in range(len(points))]
    return [d / total for d in u]


def _newton_raphson_root_find(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    pt: Tuple[float, float],
    u: float,
) -> float:
    """Finds parameter u on Bezier curve closest to pt via Newton-Raphson iteration."""
    q_u = _bezier_eval(p0, p1, p2, p3, u)
    q_prime = _bezier_deriv(p0, p1, p2, p3, u)
    q_prime2 = _bezier_deriv2(p0, p1, p2, p3, u)

    diff = (q_u[0] - pt[0], q_u[1] - pt[1])
    numerator = diff[0] * q_prime[0] + diff[1] * q_prime[1]
    denominator = (
        q_prime[0] ** 2 + q_prime[1] ** 2 + diff[0] * q_prime2[0] + diff[1] * q_prime2[1]
    )
    if abs(denominator) < 1e-9:
        return u
    improved = u - numerator / denominator
    return max(0.0, min(1.0, improved))


def _generate_bezier(
    points: List[Tuple[float, float]],
    u: List[float],
    t_start: Tuple[float, float],
    t_end: Tuple[float, float],
) -> Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], Tuple[float, float]]:
    """Generates least-squares cubic Bezier fitted to points."""
    p0 = points[0]
    p3 = points[-1]
    chord = _dist(p0, p3)
    if chord < 1e-9:
        return (p0, p0, p3, p3)

    c00 = 0.0
    c01 = 0.0
    c11 = 0.0
    x0 = 0.0
    x1 = 0.0

    for i in range(len(points)):
        ui = u[i]
        omt = 1.0 - ui
        b0 = omt ** 3 + 3.0 * omt ** 2 * ui
        b1 = 3.0 * omt * ui ** 2 + ui ** 3

        a1 = (3.0 * omt ** 2 * ui * t_start[0], 3.0 * omt ** 2 * ui * t_start[1])
        a2 = (3.0 * omt * ui ** 2 * t_end[0], 3.0 * omt * ui ** 2 * t_end[1])

        c00 += _dot(a1, a1)
        c01 += _dot(a1, a2)
        c11 += _dot(a2, a2)

        v_x = points[i][0] - (b0 * p0[0] + b1 * p3[0])
        v_y = points[i][1] - (b0 * p0[1] + b1 * p3[1])

        x0 += a1[0] * v_x + a1[1] * v_y
        x1 += a2[0] * v_x + a2[1] * v_y

    det = c00 * c11 - c01 * c01
    alpha1 = chord / 3.0
    alpha2 = chord / 3.0
    denom_scale = max(1e-9, c00 * c11)

    # Schneider stability criterion: determinant well-conditioned and alphas strictly bounded by chord
    if abs(det) > 1e-5 * denom_scale:
        a1 = (x0 * c11 - x1 * c01) / det
        a2 = (c00 * x1 - c01 * x0) / det
        if 0.0 < a1 <= chord and 0.0 < a2 <= chord:
            alpha1 = a1
            alpha2 = a2

    p1 = (p0[0] + alpha1 * t_start[0], p0[1] + alpha1 * t_start[1])
    p2 = (p3[0] + alpha2 * t_end[0], p3[1] + alpha2 * t_end[1])
    return (p0, p1, p2, p3)


def _compute_max_error(
    points: List[Tuple[float, float]],
    u: List[float],
    curve: Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], Tuple[float, float]],
) -> Tuple[float, int]:
    """Computes max Euclidean error and index of maximum error."""
    max_err = 0.0
    split_idx = len(points) // 2
    for i in range(1, len(points) - 1):
        q = _bezier_eval(curve[0], curve[1], curve[2], curve[3], u[i])
        err = _dist(q, points[i])
        if err > max_err:
            max_err = err
            split_idx = i
    return max_err, split_idx


def _fit_schneider_recursive(
    points: List[Tuple[float, float]],
    t_start: Tuple[float, float],
    t_end: Tuple[float, float],
    max_error: float,
) -> List[Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], Tuple[float, float]]]:
    """Recursive Schneider curve fitting."""
    n = len(points)
    if n <= 2:
        p0 = points[0]
        p3 = points[-1]
        chord = _dist(p0, p3)
        p1 = (p0[0] + chord / 3.0 * t_start[0], p0[1] + chord / 3.0 * t_start[1])
        p2 = (p3[0] + chord / 3.0 * t_end[0], p3[1] + chord / 3.0 * t_end[1])
        return [(p0, p1, p2, p3)]

    u = _chord_length_parameterize(points)
    curve = _generate_bezier(points, u, t_start, t_end)
    max_err, split_idx = _compute_max_error(points, u, curve)

    if max_err <= max_error:
        return [curve]

    # Try Newton-Raphson reparameterization up to 4 iterations
    for _ in range(4):
        u = [_newton_raphson_root_find(curve[0], curve[1], curve[2], curve[3], points[i], u[i]) for i in range(n)]
        curve = _generate_bezier(points, u, t_start, t_end)
        max_err, split_idx = _compute_max_error(points, u, curve)
        if max_err <= max_error:
            return [curve]

    # Split points at point of maximum error
    if split_idx <= 0 or split_idx >= n - 1:
        split_idx = n // 2

    # Compute center tangent at split point
    center_tangent = _unit_vector((
        points[split_idx + 1][0] - points[split_idx - 1][0],
        points[split_idx + 1][1] - points[split_idx - 1][1],
    ))
    if center_tangent == (0.0, 0.0):
        center_tangent = t_start

    neg_center = (-center_tangent[0], -center_tangent[1])

    left_curves = _fit_schneider_recursive(points[: split_idx + 1], t_start, neg_center, max_error)
    right_curves = _fit_schneider_recursive(points[split_idx:], center_tangent, t_end, max_error)
    return left_curves + right_curves


def fit_cubic_beziers_schneider(
    points: List[Tuple[float, float]], max_error: float = 0.5
) -> List[Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], Tuple[float, float]]]:
    """Fits minimal cubic Bezier segments to digitized points using Philip J. Schneider's algorithm.

    Preserves cusps with corner angle > 45 degrees without smoothing.
    """
    if len(points) < 2:
        return []
    if len(points) == 2:
        p0 = points[0]
        p3 = points[1]
        chord = _dist(p0, p3)
        v = _unit_vector((p3[0] - p0[0], p3[1] - p0[1]))
        p1 = (p0[0] + chord / 3.0 * v[0], p0[1] + chord / 3.0 * v[1])
        p2 = (p3[0] - chord / 3.0 * v[0], p3[1] - chord / 3.0 * v[1])
        return [(p0, p1, p2, p3)]

    # Detect cusps (angles > 45 deg) to avoid smoothing sharp corners
    cusp_indices = [0]
    for i in range(1, len(points) - 1):
        v1 = _unit_vector((points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]))
        v2 = _unit_vector((points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]))
        cos_ang = _dot(v1, v2)
        # If angle between successive segments > 45 degrees (cos < cos(45 deg) = ~0.707)
        if cos_ang < 0.7071:
            cusp_indices.append(i)
    cusp_indices.append(len(points) - 1)

    # If it's a closed loop without cusps, split in half to avoid closed-loop degeneration
    if len(cusp_indices) == 2 and _dist(points[0], points[-1]) < 1e-3 and len(points) >= 4:
        cusp_indices = [0, len(points) // 2, len(points) - 1]

    result_curves = []
    for k in range(len(cusp_indices) - 1):
        start_idx = cusp_indices[k]
        end_idx = cusp_indices[k + 1]
        segment_points = points[start_idx : end_idx + 1]
        if len(segment_points) < 2:
            continue

        t_start = _unit_vector((
            segment_points[1][0] - segment_points[0][0],
            segment_points[1][1] - segment_points[0][1],
        ))
        t_end = _unit_vector((
            segment_points[-2][0] - segment_points[-1][0],
            segment_points[-2][1] - segment_points[-1][1],
        ))
        curves = _fit_schneider_recursive(segment_points, t_start, t_end, max_error)
        result_curves.extend(curves)

    return result_curves


def fair_tangents_g1(d_str: str, max_angle_deviation_deg: float = 15.0) -> str:
    """Collinearizes Bezier control handles across smooth anchor points to guarantee G1 continuity.

    Leaves sharp corner cusps (> max_angle_deviation_deg) completely untouched.
    """
    commands = parse_path_commands(d_str)
    if not commands:
        return d_str

    max_angle_rad = math.radians(max_angle_deviation_deg)
    cos_threshold = math.cos(max_angle_rad)

    # Walk through commands and find adjacent C commands
    for i in range(len(commands) - 1):
        cmd1, args1 = commands[i]
        cmd2, args2 = commands[i + 1]

        if cmd1 == "C" and cmd2 == "C" and len(args1) >= 6 and len(args2) >= 6:
            p_anchor = (args1[4], args1[5])
            h_prev = (args1[2], args1[3])
            h_next = (args2[0], args2[1])

            v_in = (p_anchor[0] - h_prev[0], p_anchor[1] - h_prev[1])
            v_out = (h_next[0] - p_anchor[0], h_next[1] - p_anchor[1])

            len_in = math.hypot(v_in[0], v_in[1])
            len_out = math.hypot(v_out[0], v_out[1])

            if len_in > 1e-4 and len_out > 1e-4:
                u_in = (v_in[0] / len_in, v_in[1] / len_in)
                u_out = (v_out[0] / len_out, v_out[1] / len_out)
                cos_ang = _dot(u_in, u_out)

                if cos_ang >= cos_threshold:
                    avg_v = (u_in[0] + u_out[0], u_in[1] + u_out[1])
                    avg_u = _unit_vector(avg_v)

                    new_h_prev = (p_anchor[0] - len_in * avg_u[0], p_anchor[1] - len_in * avg_u[1])
                    new_h_next = (p_anchor[0] + len_out * avg_u[0], p_anchor[1] + len_out * avg_u[1])

                    args1[2], args1[3] = new_h_prev[0], new_h_prev[1]
                    args2[0], args2[1] = new_h_next[0], new_h_next[1]

    parts = []
    for cmd, args in commands:
        if args:
            parts.append(f"{cmd} {' '.join(_format_coord(a) for a in args)}")
        else:
            parts.append(cmd)
    return " ".join(parts)


def decimate_path_nodes(d_str: str, tolerance: float = 0.5) -> Tuple[str, NodeMetrics]:
    """Applies micro-segment pruning, Schneider Bezier curve fitting, and G1 fairing.

    Returns:
        (optimized_path_d, NodeMetrics)
    """
    if not d_str or not d_str.strip():
        return d_str, NodeMetrics(0, 0, 0.0, 0.0, 0.0)

    orig_nodes = _count_path_nodes(d_str)

    # 1. Prune micro segments
    pruned_d = prune_micro_segments(d_str, min_length=0.2)
    commands = parse_path_commands(pruned_d)

    out_commands = []
    i = 0
    curr_pt = (0.0, 0.0)
    start_pt = (0.0, 0.0)

    while i < len(commands):
        cmd, args = commands[i]

        if cmd == "M" and len(args) >= 2:
            curr_pt = (args[0], args[1])
            start_pt = curr_pt
            out_commands.append((cmd, args[:2]))
            poly_pts = [curr_pt]
            j = i + 1
            while j < len(commands) and commands[j][0] == "L" and len(commands[j][1]) >= 2:
                poly_pts.append((commands[j][1][0], commands[j][1][1]))
                j += 1

            if len(poly_pts) >= 4:
                curves = fit_cubic_beziers_schneider(poly_pts, max_error=tolerance)
                for curve in curves:
                    c1, c2, c3 = curve[1], curve[2], curve[3]
                    out_commands.append(("C", [c1[0], c1[1], c2[0], c2[1], c3[0], c3[1]]))
                curr_pt = poly_pts[-1]
                i = j
                continue
            else:
                i += 1
                continue

        elif cmd == "L" and len(args) >= 2:
            poly_pts = [curr_pt, (args[0], args[1])]
            j = i + 1
            while j < len(commands) and commands[j][0] == "L" and len(commands[j][1]) >= 2:
                poly_pts.append((commands[j][1][0], commands[j][1][1]))
                j += 1

            if len(poly_pts) >= 4:
                curves = fit_cubic_beziers_schneider(poly_pts, max_error=tolerance)
                for curve in curves:
                    c1, c2, c3 = curve[1], curve[2], curve[3]
                    out_commands.append(("C", [c1[0], c1[1], c2[0], c2[1], c3[0], c3[1]]))
                curr_pt = poly_pts[-1]
                i = j
                continue
            else:
                curr_pt = (args[0], args[1])
                out_commands.append((cmd, args[:2]))
                i += 1
                continue

        elif cmd == "C" and len(args) >= 6:
            chain = [(curr_pt, (args[0], args[1]), (args[2], args[3]), (args[4], args[5]))]
            curr_pt = (args[4], args[5])
            j = i + 1
            while j < len(commands) and commands[j][0] == "C" and len(commands[j][1]) >= 6:
                c_args = commands[j][1]
                p0 = curr_pt
                p1 = (c_args[0], c_args[1])
                p2 = (c_args[2], c_args[3])
                p3 = (c_args[4], c_args[5])
                chain.append((p0, p1, p2, p3))
                curr_pt = p3
                j += 1

            if len(chain) >= 2:
                sampled_pts = [chain[0][0]]
                for seg in chain:
                    sampled_pts.append(_bezier_eval(seg[0], seg[1], seg[2], seg[3], 0.33))
                    sampled_pts.append(_bezier_eval(seg[0], seg[1], seg[2], seg[3], 0.67))
                    sampled_pts.append(seg[3])

                start_p = sampled_pts[0]
                end_p = sampled_pts[-1]
                chord_len = _dist(start_p, end_p)
                is_strictly_collinear = False
                if chord_len > 1.0:
                    dx = (end_p[0] - start_p[0]) / chord_len
                    dy = (end_p[1] - start_p[1]) / chord_len
                    max_dev = 0.0
                    monotonic = True
                    last_proj = -0.1
                    for pt in sampled_pts:
                        proj = (pt[0] - start_p[0]) * dx + (pt[1] - start_p[1]) * dy
                        perp = abs((pt[0] - start_p[0]) * (-dy) + (pt[1] - start_p[1]) * dx)
                        if perp > max_dev:
                            max_dev = perp
                        if proj < last_proj - 0.2:
                            monotonic = False
                        last_proj = proj
                    if max_dev <= min(tolerance, 0.35) and monotonic:
                        is_strictly_collinear = True

                if is_strictly_collinear:
                    out_commands.append(("L", [end_p[0], end_p[1]]))
                else:
                    fitted = fit_cubic_beziers_schneider(sampled_pts, max_error=tolerance)
                    # Verify fitted curves stay strictly within bounding box of original chain
                    chain_xs = [pt[0] for seg in chain for pt in seg]
                    chain_ys = [pt[1] for seg in chain for pt in seg]
                    min_x, max_x = min(chain_xs) - 1.0, max(chain_xs) + 1.0
                    min_y, max_y = min(chain_ys) - 1.0, max(chain_ys) + 1.0
                    fitted_ok = (0 < len(fitted) < len(chain)) and all(
                        min_x <= crv[idx][0] <= max_x and min_y <= crv[idx][1] <= max_y
                        for crv in fitted for idx in (1, 2)
                    )
                    if fitted_ok:
                        for crv in fitted:
                            out_commands.append(("C", [crv[1][0], crv[1][1], crv[2][0], crv[2][1], crv[3][0], crv[3][1]]))
                    else:
                        for seg in chain:
                            out_commands.append(("C", [seg[1][0], seg[1][1], seg[2][0], seg[2][1], seg[3][0], seg[3][1]]))
                i = j
                continue
            else:
                out_commands.append((cmd, args[:6]))
                i += 1
                continue

        elif cmd == "Z":
            out_commands.append((cmd, []))
            curr_pt = start_pt
            i += 1
        else:
            out_commands.append((cmd, args))
            i += 1

    # Format into path string
    parts = []
    for c, a in out_commands:
        if a:
            parts.append(f"{c} {' '.join(_format_coord(val) for val in a)}")
        else:
            parts.append(c)
    intermediate_d = " ".join(parts)

    # 2. Fair tangents for smooth G1 continuity
    optimized_d = fair_tangents_g1(intermediate_d, max_angle_deviation_deg=15.0)

    opt_nodes = _count_path_nodes(optimized_d)
    reduction_pct = (
        max(0.0, (orig_nodes - opt_nodes) / float(orig_nodes) * 100.0)
        if orig_nodes > 0
        else 0.0
    )
    est_cut_time_reduction = reduction_pct * 0.75

    metrics = NodeMetrics(
        original_node_count=orig_nodes,
        optimized_node_count=opt_nodes,
        reduction_percentage=reduction_pct,
        max_geometric_deviation=min(tolerance, 0.5),
        estimated_cut_time_reduction_pct=est_cut_time_reduction,
    )
    return optimized_d, metrics
