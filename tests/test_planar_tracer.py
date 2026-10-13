"""Tests for the planar shared-boundary tracer."""

import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from inkmcp.inkmcpops import vectorize_image_operation
from inkmcp.vectorizer.planar_tracer import (
    PlanarTraceConfig,
    extract_chains,
    trace_planar,
)


# ----------------------------------------------------------------------------- helpers


def _supersampled(draw_fn, size=200, ss=4, bg=(0, 0, 0, 0)):
    """Draw at ss x resolution then downsample => realistic anti-aliased raster."""
    big = Image.new("RGBA", (size * ss, size * ss), bg)
    draw_fn(ImageDraw.Draw(big), ss)
    return big.resize((size, size), Image.LANCZOS)


def _subpaths(d):
    """Parse our own M/L/C/Z output into flattened polylines."""
    toks = re.findall(r"[MLCZ]|-?\d+(?:\.\d+)?", d)
    polys, cur, i, pos = [], [], 0, None
    while i < len(toks):
        t = toks[i]
        if t == "M":
            pos = np.array([float(toks[i + 1]), float(toks[i + 2])])
            cur = [pos]
            i += 3
        elif t == "L":
            pos = np.array([float(toks[i + 1]), float(toks[i + 2])])
            cur.append(pos)
            i += 3
        elif t == "C":
            c1 = np.array([float(toks[i + 1]), float(toks[i + 2])])
            c2 = np.array([float(toks[i + 3]), float(toks[i + 4])])
            p3 = np.array([float(toks[i + 5]), float(toks[i + 6])])
            for s in np.linspace(0, 1, 17)[1:]:
                m = 1 - s
                cur.append(m ** 3 * pos + 3 * m * m * s * c1 + 3 * m * s * s * c2 + s ** 3 * p3)
            pos = p3
            i += 7
        elif t == "Z":
            polys.append(np.array(cur))
            cur = []
            i += 1
        else:
            i += 1
    return polys


def _net_area(d):
    total = 0.0
    for p in _subpaths(d):
        x, y = p[:, 0], p[:, 1]
        total += 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    return total


# ----------------------------------------------------------------------------- tests


def test_auto_palette_finds_small_distinct_regions():
    colors = [(200, 40, 40, 255), (40, 60, 200, 255), (250, 210, 40, 255), (30, 30, 30, 255)]

    def draw(dr, s):
        dr.rectangle([10 * s, 10 * s, 190 * s, 190 * s], fill=colors[0])
        dr.ellipse([40 * s, 40 * s, 160 * s, 160 * s], fill=colors[1])
        dr.ellipse([90 * s, 90 * s, 110 * s, 110 * s], fill=colors[2])  # small region
        dr.rectangle([20 * s, 170 * s, 60 * s, 180 * s], fill=colors[3])

    res = trace_planar(_supersampled(draw))
    assert len(res.palette) == 4
    for c in colors:
        dist = min(np.linalg.norm(np.array(c[:3]) - np.array(p)) for p in res.palette)
        assert dist < 8, f"palette missing {c}: {res.palette}"


def test_planar_tiling_has_no_gaps_or_overlaps():
    """Net color areas must sum to the opaque area, each matching its pixel count."""

    def draw(dr, s):
        dr.ellipse([10 * s, 10 * s, 190 * s, 190 * s], fill=(0, 0, 0, 255))
        dr.pieslice([25 * s, 25 * s, 175 * s, 175 * s], 0, 120, fill=(220, 30, 30, 255))
        dr.pieslice([25 * s, 25 * s, 175 * s, 175 * s], 120, 240, fill=(30, 160, 60, 255))
        dr.pieslice([25 * s, 25 * s, 175 * s, 175 * s], 240, 360, fill=(30, 60, 220, 255))
        dr.ellipse([85 * s, 85 * s, 115 * s, 115 * s], fill=(250, 250, 250, 255))  # island

    img = _supersampled(draw)
    res = trace_planar(img, PlanarTraceConfig(num_colors=5))
    opaque = (np.array(img)[:, :, 3] >= 128).sum()
    areas = {lyr["color_hex"]: abs(_net_area(lyr["d"])) for lyr in res.layers}
    total = sum(areas.values())
    assert abs(total - opaque) / opaque < 0.01, (total, opaque)
    for lyr in res.layers:
        a = areas[lyr["color_hex"]]
        assert abs(a - lyr["area_px"]) / lyr["area_px"] < 0.05, (lyr["color_hex"], a, lyr["area_px"])


def test_enclosed_islands_survive():
    """Regression: corner-free closed loops used to collapse to a point (zero chord)."""

    def draw(dr, s):
        dr.ellipse([10 * s, 10 * s, 190 * s, 190 * s], fill=(200, 30, 30, 255))
        dr.ellipse([50 * s, 50 * s, 150 * s, 150 * s], fill=(40, 40, 200, 255))
        dr.ellipse([85 * s, 85 * s, 115 * s, 115 * s], fill=(200, 30, 30, 255))

    res = trace_planar(_supersampled(draw), PlanarTraceConfig(num_colors=2))
    by = {lyr["color_hex"]: lyr for lyr in res.layers}
    blue = next(v for k, v in by.items() if int(k[5:7], 16) > 150)
    red = next(v for k, v in by.items() if int(k[1:3], 16) > 150)
    # blue = annulus: pi*(50^2 - 15^2); red = disc minus annulus
    assert abs(abs(_net_area(blue["d"])) - np.pi * (50 ** 2 - 15 ** 2)) / (np.pi * (50 ** 2 - 15 ** 2)) < 0.03
    assert abs(abs(_net_area(red["d"])) - np.pi * (90 ** 2 - 50 ** 2 + 15 ** 2)) / (np.pi * (90 ** 2 - 50 ** 2 + 15 ** 2)) < 0.03


def test_single_corner_ring_is_not_collapsed():
    """Regression: a C-shaped ring (closed loop with one corner) vanished."""

    def draw(dr, s):
        dr.rectangle([0, 0, 200 * s, 200 * s], fill=(0, 0, 0, 255))
        dr.arc([50 * s, 50 * s, 150 * s, 150 * s], 300, 200, fill=(240, 166, 42, 255), width=12 * s)

    img = _supersampled(draw)
    res = trace_planar(img, PlanarTraceConfig(num_colors=2))
    orange = next(lyr for lyr in res.layers if lyr["color_hex"] != "#000000")
    assert abs(abs(_net_area(orange["d"])) - orange["area_px"]) / orange["area_px"] < 0.05


def test_chains_separate_exactly_two_labels():
    lab = np.zeros((30, 30), np.int32)
    lab[5:25, 5:15] = 1
    lab[5:25, 15:25] = 2
    lab[12:18, 10:20] = 3
    chains = extract_chains(lab)
    assert chains
    for c in chains:
        assert c.left != c.right
        if not c.closed:
            assert len(c.points) >= 2


def test_thin_feature_shares_boundary_without_slivers():
    """AA blend pixels between black and light gray must not become a mid-gray sliver."""

    def draw(dr, s):
        dr.rectangle([0, 0, 200 * s, 200 * s], fill=(169, 185, 201, 255))
        dr.rectangle([60 * s, 0, 140 * s, 200 * s], fill=(0, 0, 0, 255))
        dr.rectangle([150 * s, 20 * s, 190 * s, 180 * s], fill=(90, 110, 136, 255))

    res = trace_planar(_supersampled(draw), PlanarTraceConfig(num_colors=3))
    mid = next(lyr for lyr in res.layers if lyr["color_hex"].startswith("#5"))
    # mid-gray exists only as the real rectangle; no slivers along the black/light edges
    assert abs(abs(_net_area(mid["d"])) - 40 * 160) / (40 * 160) < 0.05


def test_operation_defaults_to_planar_for_cut_ready(tmp_path: Path):
    img = _supersampled(lambda dr, s: dr.ellipse([20 * s, 20 * s, 180 * s, 180 * s], fill=(255, 120, 0, 255)))
    p = tmp_path / "a.png"
    img.save(p)
    out = tmp_path / "a.svg"
    res = vectorize_image_operation(
        {"image_path": str(p), "output_path": str(out), "mode": "cut_ready", "inject_to_inkscape": False}
    )
    assert res["status"] == "success", res
    assert res["data"]["engine"] == "planar"
    assert res["data"]["layer_count"] == 1
    assert out.read_text(encoding="utf-8").count("<path") == 1


def test_operation_engine_override_and_validation(tmp_path: Path):
    img = _supersampled(lambda dr, s: dr.rectangle([20 * s, 20 * s, 180 * s, 180 * s], fill=(0, 120, 255, 255)))
    p = tmp_path / "b.png"
    img.save(p)
    res = vectorize_image_operation(
        {"image_path": str(p), "mode": "cut_ready", "engine": "vtracer", "num_colors": 2, "inject_to_inkscape": False}
    )
    assert res["status"] == "success", res
    assert res["data"]["engine"] == "vtracer"
    bad = vectorize_image_operation({"image_path": str(p), "engine": "nope", "inject_to_inkscape": False})
    assert bad["status"] == "error"


def test_remove_background_drops_border_color(tmp_path: Path):
    def draw(dr, s):
        dr.rectangle([0, 0, 200 * s, 200 * s], fill=(255, 255, 255, 255))
        dr.ellipse([40 * s, 40 * s, 160 * s, 160 * s], fill=(200, 20, 20, 255))

    img = _supersampled(draw)
    res = trace_planar(img, PlanarTraceConfig(num_colors=2, remove_background=True))
    assert [lyr["color_hex"] for lyr in res.layers] != [] and all(lyr["color_hex"] != "#ffffff" for lyr in res.layers)


@pytest.mark.parametrize("name", ["Logo", "Phishy", "Troll Hunter"])
def test_reference_examples_palette_matches(name):
    """The bundled examples have hand-made reference SVGs; auto palette should match them."""
    root = Path(__file__).resolve().parents[1] / "examples"
    png, svg = root / f"{name}.png", root / f"{name}.svg"
    if not png.exists() or not svg.exists():
        pytest.skip("example assets not present")
    txt = svg.read_text(encoding="utf-8", errors="ignore")
    ref = {c.lower() for c in re.findall(r"fill:\s*(#[0-9a-fA-F]{6})", txt)}
    ref_rgb = [np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)]) for c in ref]
    res = trace_planar(png)
    assert len(res.palette) == len(ref_rgb)
    for c in ref_rgb:
        assert min(np.linalg.norm(c - np.array(p)) for p in res.palette) < 6
