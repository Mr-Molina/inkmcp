"""Tests for gradient flattening and its integration with the planar tracer."""

import numpy as np
from PIL import Image, ImageDraw

from inkmcp.vectorizer.flatten import FlattenConfig, flatten_gradients
from inkmcp.vectorizer.planar_tracer import PlanarTraceConfig, gradient_score, trace_planar


def _gradient_panel(size=160):
    """Blue panel with a strong vertical gradient, inside a dark frame, on white."""
    img = np.full((size, size, 4), 255, np.uint8)
    y = np.linspace(0, 1, size - 40)[:, None]
    blue = np.stack([20 + 40 * y, 150 - 60 * y, 220 - 50 * y], -1)  # top light -> bottom dark
    img[20:size - 20, 20:size - 20, :3] = np.repeat(blue, size - 40, axis=1).astype(np.uint8)
    img[15:20, 15:size - 15, :3] = (30, 30, 70)
    img[size - 20:size - 15, 15:size - 15, :3] = (30, 30, 70)
    img[15:size - 15, 15:20, :3] = (30, 30, 70)
    img[15:size - 15, size - 20:size - 15, :3] = (30, 30, 70)
    return img


def test_gradient_collapses_to_single_flat_region():
    out = flatten_gradients(_gradient_panel())
    inner = out[30:130, 30:130, :3].reshape(-1, 3)
    assert len(np.unique(inner, axis=0)) == 1, "gradient fill should become one colour"
    # frame and background keep distinct colours
    assert tuple(out[17, 80, :3]) != tuple(out[80, 80, :3])
    assert tuple(out[2, 2, :3]) != tuple(out[80, 80, :3])


def test_thin_dark_line_survives_flattening():
    img = np.full((120, 120, 4), 255, np.uint8)
    img[:, :, :3] = (230, 200, 50)  # yellow panel
    img[10:110, 59:61, :3] = (60, 50, 20)  # 2px dark divider line
    out = flatten_gradients(img)
    line = out[20:100, 59:61, :3].reshape(-1, 3).astype(int)
    assert np.all(line.sum(1) < 300), "thin dark line was absorbed into the panel"


def test_anti_aliased_thin_line_survives():
    big = Image.new("RGBA", (480, 480), (230, 200, 50, 255))
    ImageDraw.Draw(big).line([(100, 40), (300, 440)], fill=(60, 50, 20, 255), width=6)
    img = np.array(big.resize((120, 120), Image.LANCZOS))
    out = flatten_gradients(img)
    dark = (out[:, :, :3].astype(int).sum(-1) < 400)
    assert dark.sum() > 60, "AA diagonal stroke should remain as a dark region"


def test_gradient_score_separates_flat_and_painted():
    flat = np.zeros((100, 100, 4), np.uint8)
    flat[:, :, 3] = 255
    flat[20:80, 20:80, :3] = (200, 30, 30)
    assert gradient_score(flat) < 0.01
    assert gradient_score(_gradient_panel()) > 0.3


def test_planar_trace_auto_flattens_gradients():
    res = trace_planar(_gradient_panel())
    # white bg, dark frame, one blue fill -- not a stack of posterized blue bands
    assert len(res.palette) == 3, res.palette


def test_flatten_can_be_forced_off():
    res = trace_planar(_gradient_panel(), PlanarTraceConfig(flatten=False))
    assert len(res.palette) > 3  # posterized bands without flattening


def test_flatten_is_noop_shape_wise_on_flat_art():
    img = np.zeros((80, 80, 4), np.uint8)
    img[10:70, 10:70] = (40, 120, 200, 255)
    img[30:50, 30:50] = (240, 240, 240, 255)
    out = flatten_gradients(img, FlattenConfig(denoise=False))
    assert np.array_equal(out[:, :, 3] > 0, img[:, :, 3] > 0)
    assert len(np.unique(out[out[:, :, 3] > 0][:, :3], axis=0)) == 2


def test_operation_flatten_param(tmp_path):
    from inkmcp.inkmcpops import vectorize_image_operation

    p = tmp_path / "grad.png"
    Image.fromarray(_gradient_panel()).save(p)
    base = {"image_path": str(p), "mode": "cut_ready", "inject_to_inkscape": False}

    auto = vectorize_image_operation(dict(base))
    assert auto["status"] == "success", auto
    assert auto["data"]["flattened"] is True
    assert len(auto["data"]["palette"]) == 3

    off = vectorize_image_operation(dict(base, flatten="false"))
    assert off["data"]["flattened"] is False
    assert len(off["data"]["palette"]) > 3


def test_soft_supersample_places_edge_from_antialias():
    from inkmcp.vectorizer.planar_tracer import soft_supersample

    img = np.full((20, 20, 4), 255, np.uint8)
    img[:, :10, :3] = 0
    img[:, 10, :3] = 64  # 75% black coverage -> edge at x = 10.75
    lab = np.where(np.arange(20)[None, :] <= 10, 1, 2).repeat(20, 0).astype(np.int32)
    pal = np.array([[0, 0, 0], [255, 255, 255]], np.float32)
    up = soft_supersample(lab, img, pal, 4, 0.0)
    black_cols = (up[40] == 1).sum()
    assert abs(black_cols - 43) <= 1, black_cols  # 10.75 px * 4


def test_antialias_blend_strip_is_removed():
    img = np.full((100, 100, 4), 255, np.uint8)
    img[:, :50, :3] = (220, 30, 30)
    img[:, 51:, :3] = (30, 60, 200)
    img[:, 50, :3] = (125, 45, 115)  # 1px blend column along a long edge
    out = flatten_gradients(img, FlattenConfig(denoise=False))
    cols = {tuple(c) for c in out[10:90, 45:56, :3].reshape(-1, 3)}
    assert len(cols) == 2, cols


def test_grainy_outline_keeps_its_own_colour():
    rng = np.random.default_rng(0)
    img = np.full((80, 80, 4), 255, np.uint8)
    img[:, :, :3] = (200, 165, 120)  # tan
    stroke = np.array([60, 40, 72], float) + rng.normal(0, 3, (80, 6, 3))
    img[:, 37:43, :3] = np.clip(stroke, 0, 255).astype(np.uint8)
    out = flatten_gradients(img, FlattenConfig(denoise=False))
    core = out[10:70, 38:42, :3].reshape(-1, 3).astype(int)
    assert core.sum(1).max() < 260, "grainy dark outline was painted with a neighbour's colour"


def test_thin_light_trim_survives_flattening():
    img = np.full((120, 120, 4), 255, np.uint8)
    img[:, :60, :3] = (200, 40, 40)  # red frame
    img[:, 62:, :3] = (30, 140, 200)  # blue glass
    img[:, 60:62, :3] = (250, 238, 198)  # 2px cream trim between them
    out = flatten_gradients(img, FlattenConfig(denoise=False))
    trim = out[10:110, 60:62, :3].reshape(-1, 3).astype(int)
    assert np.all(trim.sum(1) > 600), "thin cream trim was absorbed"
