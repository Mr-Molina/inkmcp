"""Planar shared-boundary tracer for flat-color artwork (logos, clip art, cut files).

Why this exists
---------------
Tracing each color region independently (vtracer/potrace style) fits every region's
outline separately, so two neighbouring colors get two *different* approximations of
the same border. The result is hairline gaps, overlaps, wobbly outline widths and
slivers. Hand-made vectors are a planar mosaic: each border between two colors exists
exactly once and both neighbours reference it.

This module reproduces that structure:

1. Palette      - k-means on "flat" pixels only (anti-aliased blends excluded).
2. Labels       - nearest palette color per pixel; alpha < 50% is background.
3. Unmix AA     - thin bands whose color is better explained as a blend of the two
                  neighbouring colors are reassigned to those neighbours (kills slivers).
4. Despeckle    - connected components below ``min_area`` merge into their neighbour.
5. Super-sample - per-label indicator maps are blurred and upsampled; argmax gives a
                  smooth label map with sub-pixel boundary placement.
6. Crack graph  - boundaries between pixels form a planar graph; junction corners
                  (3+ colors) split it into *chains* each separating exactly two labels.
7. Fit chains   - each chain is smoothed, split at corners, and Bezier fitted ONCE.
8. Assemble     - each color is one compound path built from its chains (oriented with
                  that color on the left), so neighbours share identical geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

logger = logging.getLogger(__name__)

Point = np.ndarray  # shape (2,)
Bezier = Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]


@dataclass
class PlanarTraceConfig:
    """Tuning knobs for :func:`trace_planar`.

    Distances are in source-image pixels.
    """

    num_colors: Optional[int] = None  # None = auto-detect
    max_colors: int = 32
    alpha_threshold: int = 128
    min_area: int = 12  # speckle threshold (source px^2)
    unmix_antialias: bool = True
    supersample: int = 4
    blur_sigma: float = 0.75
    subpixel_edges: bool = True  # place edges from anti-alias coverage (soft_supersample)
    subpixel_blur: float = 0.5
    smooth_sigma: float = 1.0  # along-curve smoothing
    corner_angle_deg: float = 50.0
    corner_window: float = 2.0
    fit_tolerance: float = 0.45
    line_tolerance: float = 0.30
    decimals: int = 2
    palette: Optional[Sequence[Tuple[int, int, int]]] = None
    remove_background: bool = False
    flatten: Optional[bool] = None  # None = auto (gradient_score > flatten_auto_threshold)
    flatten_auto_threshold: float = 0.04  # flat vector renders score ~0.0; painted art >0.1


@dataclass
class PlanarTraceResult:
    svg: str
    width: int
    height: int
    palette: List[Tuple[int, int, int]]
    node_count: int
    chain_count: int
    path_count: int
    layers: List[Dict[str, object]] = field(default_factory=list)
    stats: Dict[str, float] = field(default_factory=dict)


# --------------------------------------------------------------------------- palette


def _load_rgba(image: Union[str, Path, Image.Image, np.ndarray]) -> np.ndarray:
    if isinstance(image, np.ndarray):
        arr = image
        if arr.ndim == 3 and arr.shape[2] == 1:
            arr = arr[:, :, 0]
        if arr.ndim == 2:
            arr = np.stack([arr] * 3 + [np.full_like(arr, 255)], -1)
        elif arr.shape[2] == 3:
            arr = np.concatenate([arr, np.full(arr.shape[:2] + (1,), 255, arr.dtype)], -1)
        return arr.astype(np.uint8)
    if not isinstance(image, Image.Image):
        image = Image.open(str(image))
    return np.array(image.convert("RGBA"))


def _flat_mask(rgb: np.ndarray, opaque: np.ndarray, tol: float = 6.0) -> np.ndarray:
    """Pixels whose 3x3 neighbourhood is (nearly) uniform: true palette colors, not AA."""
    f = rgb.astype(np.float32)
    mx = np.stack([ndimage.maximum_filter(f[:, :, c], size=3) for c in range(3)], -1)
    mn = np.stack([ndimage.minimum_filter(f[:, :, c], size=3) for c in range(3)], -1)
    flat = (mx - mn).max(-1) <= tol
    return flat & ndimage.binary_erosion(opaque, iterations=1)


def build_palette(rgba: np.ndarray, cfg: PlanarTraceConfig, preflattened: bool = False) -> np.ndarray:
    if cfg.palette:
        return np.array(cfg.palette, dtype=np.float32)
    if preflattened and not cfg.num_colors:
        return region_palette(rgba, cfg)
    from sklearn.cluster import KMeans

    opaque = rgba[:, :, 3] >= cfg.alpha_threshold
    rgb = rgba[:, :, :3]
    flat = opaque if preflattened else _flat_mask(rgb, opaque)
    samples = rgb[flat].astype(np.float32)
    if len(samples) < 64:
        samples = rgb[opaque].astype(np.float32)
    if len(samples) == 0:
        return np.zeros((1, 3), dtype=np.float32)
    rng = np.random.default_rng(0)
    if len(samples) > 60000:
        samples = samples[rng.choice(len(samples), 60000, replace=False)]

    if cfg.num_colors:
        distinct = len(np.unique(samples.astype(np.uint8), axis=0))
        k = max(1, min(cfg.num_colors, distinct))
        km = KMeans(n_clusters=k, n_init=6, random_state=0).fit(samples)
        centers = km.cluster_centers_
        labels = km.labels_
    else:
        centers, labels = _auto_palette(samples, cfg.max_colors)
    # Snap each center to the median of its members (cleaner, true-to-art colors).
    out = []
    for i in range(len(centers)):
        m = samples[labels == i]
        out.append(np.median(m, 0) if len(m) else centers[i])
    return np.array(out, dtype=np.float32)


def region_palette(rgba: np.ndarray, cfg: PlanarTraceConfig, delta_e: float = 10.0,
                   min_share: float = 0.0002) -> np.ndarray:
    """Palette for pre-flattened images: greedy area-ordered CIELAB clustering.

    Every flat region contributes its colour once (weighted by area). Colours within
    ``delta_e`` of an existing entry join it; otherwise they open a new entry. Entries
    covering less than ``min_share`` of the artwork are dropped, then the closest pairs
    are merged until ``max_colors`` is respected.
    """
    opaque = rgba[:, :, 3] >= cfg.alpha_threshold
    cols, counts = np.unique(rgba[:, :, :3][opaque], axis=0, return_counts=True)
    if len(cols) == 0:
        return np.zeros((1, 3), np.float32)
    lab = cv2.cvtColor(cols.reshape(-1, 1, 3).astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB).reshape(-1, 3)
    order = np.argsort(-counts)
    centers: List[np.ndarray] = []
    weights: List[float] = []
    for i in order:
        if centers:
            d = np.linalg.norm(np.array(centers) - lab[i], axis=1)
            j = int(np.argmin(d))
            if d[j] < delta_e:
                wsum = weights[j] + counts[i]
                centers[j] = (centers[j] * weights[j] + lab[i] * counts[i]) / wsum
                weights[j] = wsum
                continue
        centers.append(lab[i].astype(np.float64))
        weights.append(float(counts[i]))
    C = np.array(centers)
    W = np.array(weights)
    keep = W >= min_share * opaque.sum()
    if keep.any():
        C, W = C[keep], W[keep]
    while len(C) > cfg.max_colors:
        d = np.linalg.norm(C[:, None, :] - C[None, :, :], axis=-1)
        np.fill_diagonal(d, np.inf)
        a, b = np.unravel_index(np.argmin(d), d.shape)
        C[a] = (C[a] * W[a] + C[b] * W[b]) / (W[a] + W[b])
        W[a] += W[b]
        C, W = np.delete(C, b, 0), np.delete(W, b, 0)
    rgb = cv2.cvtColor(C.reshape(-1, 1, 3).astype(np.float32), cv2.COLOR_LAB2RGB).reshape(-1, 3)
    return np.clip(rgb * 255.0, 0, 255).astype(np.float32)


def _auto_palette(samples: np.ndarray, max_colors: int, thr: float = 11.0) -> Tuple[np.ndarray, np.ndarray]:
    """Grow a palette until every coherent group of flat pixels is explained.

    A color is added when at least ``min_px`` flat samples sit farther than ``thr``
    from every palette entry *and* cluster tightly around a common color. This keeps
    small-but-distinct regions (eyes, mouths, buckles) that percentile tests discard.
    """
    from sklearn.cluster import KMeans

    min_px = max(40, int(0.0015 * len(samples)))
    centers = np.median(samples, axis=0, keepdims=True)
    for _ in range(max_colors - 1):
        d = np.sqrt(((samples[:, None, :] - centers[None, :, :]) ** 2).sum(-1)).min(1)
        un = samples[d > thr]
        if len(un) < min_px:
            break
        q = (un // 8).astype(np.int32)
        keys = q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2]
        vals, counts = np.unique(keys, return_counts=True)
        mode = vals[np.argmax(counts)]
        seed = un[keys == mode].mean(0)
        group = un[np.sqrt(((un - seed) ** 2).sum(-1)) <= thr * 1.5]
        if len(group) < min_px:
            break
        init = np.vstack([centers, np.median(group, 0)])
        km = KMeans(n_clusters=len(init), init=init, n_init=1, random_state=0).fit(samples)
        centers = km.cluster_centers_
    km = KMeans(n_clusters=len(centers), init=centers, n_init=1, random_state=0).fit(samples)
    return km.cluster_centers_, km.labels_


def label_pixels(rgba: np.ndarray, palette: np.ndarray, alpha_threshold: int, perceptual: bool = False) -> np.ndarray:
    """0 = background, 1..K = palette index + 1.

    ``perceptual`` matches in CIELAB instead of RGB: RGB distance sends dark
    saturated inks (navy/plum outlines) to a neutral grey when the exact ink is
    not in the palette.
    """
    rgb: np.ndarray = rgba[:, :, :3].astype(np.float32)
    pal: np.ndarray = np.asarray(palette, np.float32)
    if perceptual:
        rgb = cv2.cvtColor(rgb / 255.0, cv2.COLOR_RGB2LAB)
        pal = cv2.cvtColor(pal.reshape(1, -1, 3) / 255.0, cv2.COLOR_RGB2LAB).reshape(-1, 3)
    h, w = rgb.shape[:2]
    lab = np.zeros((h, w), np.int32)
    best = np.full((h, w), np.inf, np.float32)
    for i, c in enumerate(pal):
        d = ((rgb - c) ** 2).sum(-1)
        m = d < best
        best[m] = d[m]
        lab[m] = i + 1
    lab[rgba[:, :, 3] < alpha_threshold] = 0
    return lab


# --------------------------------------------------------------------------- cleanup


def unmix_antialias(rgba: np.ndarray, lab: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Reassign thin bands that are blends of their two neighbours (AA slivers)."""
    h, w = lab.shape
    rgb = rgba[:, :, :3].astype(np.float32)
    # local half-thickness of each pixel's own region
    dt = np.zeros((h, w), np.float32)
    for k in np.unique(lab):
        m = lab == k
        dt[m] = ndimage.distance_transform_edt(m)[m]
    local_thick = ndimage.maximum_filter(dt, size=5)
    boundary = np.zeros((h, w), bool)
    boundary[1:, :] |= lab[1:, :] != lab[:-1, :]
    boundary[:-1, :] |= lab[1:, :] != lab[:-1, :]
    boundary[:, 1:] |= lab[:, 1:] != lab[:, :-1]
    boundary[:, :-1] |= lab[:, 1:] != lab[:, :-1]
    cand = np.argwhere(boundary & (lab > 0) & (local_thick <= 2.0))
    out = lab.copy()
    pad = np.pad(lab, 2, constant_values=0)
    pal = palette
    for y, x in cand:
        k = lab[y, x]
        win = pad[y:y + 5, x:x + 5]
        neigh = [n for n in np.unique(win) if n != k and n > 0]
        if len(neigh) < 2:
            continue
        c = rgb[y, x]
        dk = float(np.sqrt(((c - pal[k - 1]) ** 2).sum()))
        best = None
        for i in range(len(neigh)):
            for j in range(i + 1, len(neigh)):
                a, b = neigh[i], neigh[j]
                A, B = pal[a - 1], pal[b - 1]
                ab = A - B
                den = float((ab * ab).sum())
                if den < 1.0:
                    continue
                t = float(np.clip(((c - B) * ab).sum() / den, 0.0, 1.0))
                err = float(np.sqrt(((c - (B + t * ab)) ** 2).sum()))
                if 0.08 < t < 0.92 and (best is None or err < best[0]):
                    best = (err, a if t >= 0.5 else b)
        if best is None:
            continue
        err, target = best
        if err < 0.6 * dk or (local_thick[y, x] <= 1.0 and err < 10.0):
            out[y, x] = target
    return out


def despeckle(lab: np.ndarray, min_area: int) -> np.ndarray:
    """Merge 4-connected components smaller than ``min_area`` into their dominant neighbour."""
    if min_area <= 1:
        return lab
    lab = lab.copy()
    h, w = lab.shape
    for _ in range(4):
        changed = 0
        for k in np.unique(lab):
            n, cc, stats, _ = cv2.connectedComponentsWithStats((lab == k).astype(np.uint8), connectivity=4)
            small = np.where(stats[1:, cv2.CC_STAT_AREA] < min_area)[0] + 1
            for s in small:
                x0, y0, bw, bh = stats[s, :4]
                xa, ya = max(0, x0 - 1), max(0, y0 - 1)
                xb, yb = min(w, x0 + bw + 1), min(h, y0 + bh + 1)
                sub_cc = cc[ya:yb, xa:xb] == s
                ring = ndimage.binary_dilation(sub_cc) & ~sub_cc
                vals = lab[ya:yb, xa:xb][ring]
                vals = vals[vals != k]
                if len(vals) == 0:
                    continue
                target = np.bincount(vals).argmax()
                lab[ya:yb, xa:xb][sub_cc] = target
                changed += 1
        if not changed:
            break
    return lab


def supersample_labels(lab: np.ndarray, scale: int, sigma: float) -> np.ndarray:
    h, w = lab.shape
    if scale <= 1 and sigma <= 0:
        return lab
    best = np.full((h * scale, w * scale), -1.0, np.float32)
    out = np.zeros((h * scale, w * scale), np.int32)
    for k in np.unique(lab):
        ind = (lab == k).astype(np.float32)
        if sigma > 0:
            ind = cv2.GaussianBlur(ind, (0, 0), sigma)
        up = cv2.resize(ind, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC) if scale > 1 else ind
        m = up > best
        best[m] = up[m]
        out[m] = k
    return out


def _boundary_mask(lab: np.ndarray) -> np.ndarray:
    h, w = lab.shape
    pad = np.pad(lab, 1, mode="edge")
    b = np.zeros((h, w), bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                b |= pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] != lab
    return b


def soft_supersample(lab: np.ndarray, rgba: np.ndarray, palette: np.ndarray, scale: int,
                     sigma: float, local_sigma: float = 3.0) -> np.ndarray:
    """Supersample labels using anti-alias coverage to place edges at sub-pixel accuracy.

    Hard per-pixel labels turn a 2px stroke into a 1-3px staircase. The source's
    anti-aliasing encodes where each edge really lies: a pixel that is a 30/70
    blend of colours A and B is 30% covered by A. For every boundary pixel we
    unmix its colour (premultiplied RGBA, so transparency works the same way)
    against the *local* colours of its own label and each neighbouring label
    (local colour = normalized-convolution mean of nearby interior pixels, which
    tracks gradients; thin features without interior fall back to the palette).
    The resulting fractional membership fields are upsampled and arg-maxed, so
    a 50% blend pixel puts the edge through its centre.
    """
    h, w = lab.shape
    if scale <= 1:
        return lab
    a = rgba[:, :, 3:4].astype(np.float32) / 255.0
    feat = np.concatenate([rgba[:, :, :3].astype(np.float32) * a, a * 255.0], -1)  # premultiplied
    boundary = _boundary_mask(lab)
    by, bx = np.nonzero(boundary)
    labels = [int(k) for k in np.unique(lab)]
    kidx = {k: i for i, k in enumerate(labels)}
    lut = np.zeros(max(labels) + 1, np.int64)
    lut[labels] = np.arange(len(labels))
    nb = len(by)
    # local colour of every label sampled at boundary pixels: (K, nb, 4)
    local = np.zeros((len(labels), nb, 4), np.float32)
    eps = 0.02
    interior = ~boundary
    for k in labels:
        if k == 0:
            pal = np.zeros(4, np.float32)
        else:
            pal = np.concatenate([np.asarray(palette[k - 1], np.float32), [255.0]])
        m = ((lab == k) & interior).astype(np.float32)
        wgt = cv2.GaussianBlur(m, (0, 0), local_sigma)[by, bx]
        num = np.stack([cv2.GaussianBlur(feat[:, :, c] * m, (0, 0), local_sigma)[by, bx] for c in range(4)], -1)
        local[kidx[k]] = (num + eps * pal) / (wgt + eps)[:, None]

    own = lut[lab[by, bx]]
    c = feat[by, bx]
    A = local[own, np.arange(nb)]
    best_err = np.full(nb, np.inf, np.float32)
    best_t = np.zeros(nb, np.float32)
    best_k = own.copy()
    pad = np.pad(lab, 1, mode="edge")
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if not (dy or dx):
                continue
            cand = lut[pad[1 + by + dy, 1 + bx + dx]]
            diff = cand != own
            if not diff.any():
                continue
            B = local[cand, np.arange(nb)]
            ab = B - A
            den = (ab * ab).sum(-1)
            t = np.clip(((c - A) * ab).sum(-1) / np.maximum(den, 1e-6), 0.0, 1.0)
            err = np.sqrt(((c - (A + t[:, None] * ab)) ** 2).sum(-1))
            upd = diff & (den > 25.0) & (err < best_err)
            best_err[upd] = err[upd]
            best_t[upd] = t[upd]
            best_k[upd] = cand[upd]

    best = np.full((h * scale, w * scale), -1.0, np.float32)
    out = np.zeros((h * scale, w * scale), np.int32)
    for k in labels:
        i = kidx[k]
        f = (lab == k).astype(np.float32)
        # boundary pixels: own label keeps (1 - t), best neighbour receives t
        mo = own == i
        f[by[mo], bx[mo]] = 1.0 - best_t[mo]
        mn = (best_k == i) & ~mo
        f[by[mn], bx[mn]] = best_t[mn]
        if sigma > 0:
            f = cv2.GaussianBlur(f, (0, 0), sigma)
        up = cv2.resize(f, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
        m = up > best
        best[m] = up[m]
        out[m] = k
    return out


# --------------------------------------------------------------------------- crack graph

# directions: 0=right(+x) 1=down(+y) 2=left 3=up
_DX = (1, 0, -1, 0)
_DY = (0, 1, 0, -1)


@dataclass
class Chain:
    points: np.ndarray  # (N,2) corner coords in label-grid units (x, y)
    left: int
    right: int
    closed: bool


def extract_chains(lab: np.ndarray) -> List[Chain]:
    """Split label boundaries into chains separating exactly two labels."""
    P = np.pad(lab, 1, constant_values=0)
    Hp, Wp = P.shape
    # hb[i, j]: crack between P[i-1, j] and P[i, j]; from corner (i, j) to (i, j+1)
    hb = np.zeros((Hp + 1, Wp + 1), bool)
    hb[1:Hp, 0:Wp] = P[:-1, :] != P[1:, :]
    # vb[i, j]: crack between P[i, j-1] and P[i, j]; from corner (i, j) to (i+1, j)
    vb = np.zeros((Hp + 1, Wp + 1), bool)
    vb[0:Hp, 1:Wp] = P[:, :-1] != P[:, 1:]

    deg = np.zeros((Hp + 1, Wp + 1), np.int8)
    deg += hb  # right
    deg[:, 1:] += hb[:, :-1]  # left
    deg += vb  # down
    deg[1:, :] += vb[:-1, :]  # up
    junction = (deg >= 3)

    hv = np.zeros_like(hb)
    vv = np.zeros_like(vb)

    def crack(i, j, d):
        """Return (exists, visited_array, ii, jj) for crack leaving corner (i,j) in dir d."""
        if d == 0:
            return hb, hv, i, j
        if d == 2:
            return hb, hv, i, j - 1
        if d == 1:
            return vb, vv, i, j
        return vb, vv, i - 1, j

    def sides(i, j, d):
        # left = rotate dir (dx,dy)->(dy,-dx) in y-down coordinates
        if d == 0:
            return P[i - 1, j], P[i, j]
        if d == 2:
            return P[i, j - 1], P[i - 1, j - 1]
        if d == 1:
            return P[i, j], P[i, j - 1]
        return P[i - 1, j - 1], P[i - 1, j]

    def walk(i0, j0, d0, stop_at_start):
        pts = [(j0, i0)]
        left, right = sides(i0, j0, d0)
        i, j, d = i0, j0, d0
        while True:
            arr, vis, ii, jj = crack(i, j, d)
            vis[ii, jj] = True
            i, j = i + _DY[d], j + _DX[d]
            pts.append((j, i))
            if junction[i, j] or (stop_at_start and i == i0 and j == j0):
                break
            # pass-through corner: take the other crack (never reverse)
            nd = None
            for cand in ((d + 1) % 4, (d + 3) % 4, d):
                a2, v2, i2, j2 = crack(i, j, cand)
                if 0 <= i2 < a2.shape[0] and 0 <= j2 < a2.shape[1] and a2[i2, j2] and not v2[i2, j2]:
                    nd = cand
                    break
            if nd is None:
                break
            d = nd
        return pts, int(left), int(right)

    chains: List[Chain] = []
    ji, jj_ = np.nonzero(junction)
    for i, j in zip(ji.tolist(), jj_.tolist()):
        for d in range(4):
            arr, vis, ii, jj = crack(i, j, d)
            if 0 <= ii < arr.shape[0] and 0 <= jj < arr.shape[1] and arr[ii, jj] and not vis[ii, jj]:
                pts, lbl_left, lbl_right = walk(i, j, d, False)
                chains.append(Chain(np.array(pts, np.float64) - 1.0, lbl_left, lbl_right, False))
    # closed loops without junctions
    for arr, vis, d in ((hb, hv, 0), (vb, vv, 1)):
        rem = np.argwhere(arr & ~vis)
        for i, j in rem.tolist():
            if vis[i, j]:
                continue
            pts, lbl_left, lbl_right = walk(i, j, d, True)
            chains.append(Chain(np.array(pts, np.float64) - 1.0, lbl_left, lbl_right, True))
    return chains


# --------------------------------------------------------------------------- fitting


def _resample(pts: np.ndarray, step: float, closed: bool) -> np.ndarray:
    if closed:
        pts = np.vstack([pts, pts[:1]])
    seg = np.sqrt((np.diff(pts, axis=0) ** 2).sum(1))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = s[-1]
    if total < 1e-9:
        return pts[:1]
    n = max(2, int(round(total / step)) + 1)
    t = np.linspace(0.0, total, n)
    x = np.interp(t, s, pts[:, 0])
    y = np.interp(t, s, pts[:, 1])
    out = np.stack([x, y], 1)
    if closed:
        out = out[:-1]
    return out


def _smooth_open(pts: np.ndarray, sigma_pts: float) -> np.ndarray:
    n = len(pts)
    if n < 4 or sigma_pts <= 0:
        return pts
    r = int(min(3 * sigma_pts, n - 1))
    if r < 1:
        return pts
    # odd reflection about endpoints keeps endpoints fixed and preserves straight lines
    head = 2 * pts[0] - pts[1:r + 1][::-1]
    tail = 2 * pts[-1] - pts[-r - 1:-1][::-1]
    ext = np.vstack([head, pts, tail])
    out = np.stack([ndimage.gaussian_filter1d(ext[:, c], sigma_pts, mode="nearest") for c in range(2)], 1)
    out = out[r:r + n]
    out[0], out[-1] = pts[0], pts[-1]
    return out


def _smooth_closed(pts: np.ndarray, sigma_pts: float) -> np.ndarray:
    if len(pts) < 4 or sigma_pts <= 0:
        return pts
    return np.stack([ndimage.gaussian_filter1d(pts[:, c], sigma_pts, mode="wrap") for c in range(2)], 1)


def _find_corners(pts: np.ndarray, k: int, angle_deg: float, closed: bool) -> List[int]:
    n = len(pts)
    if n < 2 * k + 1:
        return []
    idx = np.arange(n)
    if closed:
        a = pts[(idx - k) % n]
        b = pts[(idx + k) % n]
        valid = np.ones(n, bool)
    else:
        a = pts[np.clip(idx - k, 0, n - 1)]
        b = pts[np.clip(idx + k, 0, n - 1)]
        valid = (idx >= k) & (idx <= n - 1 - k)
    v1 = pts - a
    v2 = b - pts
    n1 = np.linalg.norm(v1, axis=1) + 1e-12
    n2 = np.linalg.norm(v2, axis=1) + 1e-12
    cos = (v1 * v2).sum(1) / (n1 * n2)
    ang = np.degrees(np.arccos(np.clip(cos, -1, 1)))
    ang[~valid] = 0
    corners: List[int] = []
    thr = angle_deg
    for i in np.argsort(-ang):
        if ang[i] < thr:
            break
        if all(min(abs(i - c), n - abs(i - c) if closed else abs(i - c)) > k for c in corners):
            corners.append(int(i))
    return sorted(corners)


def _bez_eval(b: Bezier, t: np.ndarray) -> np.ndarray:
    p0, p1, p2, p3 = b
    t = t[:, None]
    mt = 1 - t
    return mt ** 3 * p0 + 3 * mt ** 2 * t * p1 + 3 * mt * t ** 2 * p2 + t ** 3 * p3


def _bez_d1(b: Bezier, t: np.ndarray) -> np.ndarray:
    p0, p1, p2, p3 = b
    t = t[:, None]
    mt = 1 - t
    return 3 * mt ** 2 * (p1 - p0) + 6 * mt * t * (p2 - p1) + 3 * t ** 2 * (p3 - p2)


def _bez_d2(b: Bezier, t: np.ndarray) -> np.ndarray:
    p0, p1, p2, p3 = b
    t = t[:, None]
    return 6 * (1 - t) * (p2 - 2 * p1 + p0) + 6 * t * (p3 - 2 * p2 + p1)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _chord_params(pts: np.ndarray) -> np.ndarray:
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return d / d[-1] if d[-1] > 0 else np.linspace(0, 1, len(pts))


def _gen_bezier(pts: np.ndarray, u: np.ndarray, t1: np.ndarray, t2: np.ndarray) -> Bezier:
    p0, p3 = pts[0], pts[-1]
    chord = float(np.linalg.norm(p3 - p0))
    b0, b1, b2, b3 = (1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u ** 2 * (1 - u), u ** 3
    A1 = t1[None, :] * b1[:, None]
    A2 = t2[None, :] * b2[:, None]
    c00 = (A1 * A1).sum()
    c01 = (A1 * A2).sum()
    c11 = (A2 * A2).sum()
    tmp = pts - (np.outer(b0 + b1, p0) + np.outer(b2 + b3, p3))
    x0 = (A1 * tmp).sum()
    x1 = (A2 * tmp).sum()
    det = c00 * c11 - c01 * c01
    fallback = chord / 3.0
    if abs(det) > 1e-9 * max(1e-12, c00 * c11):
        a1 = (x0 * c11 - x1 * c01) / det
        a2 = (c00 * x1 - c01 * x0) / det
    else:
        a1 = a2 = fallback
    eps = 1e-3 * chord
    if not (eps < a1 <= 1.5 * chord) or not (eps < a2 <= 1.5 * chord):
        a1 = a2 = fallback
    return (p0, p0 + t1 * a1, p3 + t2 * a2, p3)


def _reparam(b: Bezier, pts: np.ndarray, u: np.ndarray) -> np.ndarray:
    q = _bez_eval(b, u) - pts
    d1 = _bez_d1(b, u)
    d2 = _bez_d2(b, u)
    num = (q * d1).sum(1)
    den = (d1 * d1).sum(1) + (q * d2).sum(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        nu = np.where(np.abs(den) > 1e-12, u - num / den, u)
    nu = np.clip(nu, 0, 1)
    nu[0], nu[-1] = 0.0, 1.0
    return np.maximum.accumulate(nu)


def _max_err(b: Bezier, pts: np.ndarray, u: np.ndarray) -> Tuple[float, int]:
    d = np.linalg.norm(_bez_eval(b, u) - pts, axis=1)
    i = int(np.argmax(d[1:-1])) + 1 if len(d) > 2 else len(d) // 2
    return float(d.max()), i


def fit_cubic(pts: np.ndarray, t1: np.ndarray, t2: np.ndarray, tol: float, depth: int = 0) -> List[Bezier]:
    """Schneider fit. t1 points from pts[0] inward, t2 from pts[-1] inward."""
    n = len(pts)
    chord = float(np.linalg.norm(pts[-1] - pts[0]))
    if n >= 4 and depth <= 24:
        reach = np.linalg.norm(pts - pts[0], axis=1)
        if chord < 0.25 * float(reach.max()):
            # (near-)closed piece: least squares is ill-posed; split at the farthest point
            split = int(min(max(int(np.argmax(reach)), 1), n - 2))
            tc = _unit(pts[split + 1] - pts[split - 1])
            return fit_cubic(pts[:split + 1], t1, -tc, tol, depth + 1) + fit_cubic(pts[split:], tc, t2, tol, depth + 1)
    if n <= 2 or chord < 1e-9:
        return [(pts[0], pts[0] + t1 * chord / 3, pts[-1] + t2 * chord / 3, pts[-1])]
    u = _chord_params(pts)
    b = _gen_bezier(pts, u, t1, t2)
    err, split = _max_err(b, pts, u)
    if err <= tol:
        return [b]
    if err <= tol * 4:
        for _ in range(6):
            u = _reparam(b, pts, u)
            b = _gen_bezier(pts, u, t1, t2)
            err, split = _max_err(b, pts, u)
            if err <= tol:
                return [b]
    if depth > 24 or n <= 3:
        return [b]
    split = min(max(split, 1), n - 2)
    tc = _unit(pts[split + 1] - pts[split - 1])
    return fit_cubic(pts[:split + 1], t1, -tc, tol, depth + 1) + fit_cubic(pts[split:], tc, t2, tol, depth + 1)


def _tangent_at(pts: np.ndarray, i: int, forward: bool, span: int) -> np.ndarray:
    n = len(pts)
    if forward:
        j = min(n - 1, i + span)
        return _unit(pts[j] - pts[i])
    j = max(0, i - span)
    return _unit(pts[j] - pts[i])


@dataclass
class FittedChain:
    start: np.ndarray
    segs: List[Tuple[str, Tuple[np.ndarray, ...]]]  # ('L', (p,)) or ('C', (c1, c2, p))

    def reversed(self) -> "FittedChain":
        pts = [self.start]
        for kind, args in self.segs:
            pts.append(args[-1])
        new_segs: List[Tuple[str, Tuple[np.ndarray, ...]]] = []
        for idx in range(len(self.segs) - 1, -1, -1):
            kind, args = self.segs[idx]
            p_to = pts[idx]
            if kind == "L":
                new_segs.append(("L", (p_to,)))
            else:
                new_segs.append(("C", (args[1], args[0], p_to)))
        return FittedChain(pts[-1], new_segs)

    @property
    def end(self) -> np.ndarray:
        return self.segs[-1][1][-1] if self.segs else self.start


def _fit_piece(piece: np.ndarray, cfg: PlanarTraceConfig, step: float) -> List[Tuple[str, Tuple[np.ndarray, ...]]]:
    p0, p1 = piece[0], piece[-1]
    chord = float(np.linalg.norm(p1 - p0))
    extent = float(np.linalg.norm(piece - p0, axis=1).max()) if len(piece) else 0.0
    if len(piece) <= 2 or extent < 1e-6:
        return [("L", (p1,))]
    # straight line?
    if chord > 0.5:
        dvec = (p1 - p0) / chord
        perp = np.abs((piece[:, 0] - p0[0]) * -dvec[1] + (piece[:, 1] - p0[1]) * dvec[0])
        if perp.max() <= cfg.line_tolerance:
            return [("L", (p1,))]
    span = max(1, int(round(1.0 / step)))
    t1 = _tangent_at(piece, 0, True, span)
    t2 = _tangent_at(piece, len(piece) - 1, False, span)
    out: List[Tuple[str, Tuple[np.ndarray, ...]]] = []
    for b in fit_cubic(piece, t1, t2, cfg.fit_tolerance):
        # degenerate-to-line detection per segment
        out.append(("C", (b[1], b[2], b[3])))
    return out


def fit_chain(chain: Chain, scale: int, cfg: PlanarTraceConfig) -> FittedChain:
    pts = chain.points / float(scale)
    closed = chain.closed
    if closed and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    # crack midpoints remove the staircase bias; keep fixed endpoints for open chains
    if closed:
        mids = (pts + np.roll(pts, -1, axis=0)) / 2.0
    else:
        mids = np.vstack([pts[:1], (pts[:-1] + pts[1:]) / 2.0, pts[-1:]]) if len(pts) > 2 else pts
    step = 0.5
    rs = _resample(mids, step, closed)
    if not closed:
        rs[0], rs[-1] = pts[0], pts[-1]
    k = max(2, int(round(cfg.corner_window / step)))
    corners = _find_corners(rs, k, cfg.corner_angle_deg, closed)
    sig = cfg.smooth_sigma / step

    if closed:
        if not corners:
            sm = _smooth_closed(rs, sig)
            n = len(sm)
            if n < 6:
                return FittedChain(sm[0], [("L", (p,)) for p in sm[1:]] + [("L", (sm[0],))])
            # A closed curve has zero chord: split at evenly spaced seams (G1 continuous).
            nseg = 4 if n >= 16 else 2
            seams = [round(i * n / nseg) for i in range(nseg)] + [n]
            loop = np.vstack([sm, sm[:1]])
            tang = [_unit(sm[(s + 1) % n] - sm[(s - 1) % n]) for s in seams[:-1]]
            tang.append(tang[0])
            closed_segs: List[Tuple[str, Tuple[np.ndarray, ...]]] = []
            for a, b, ta, tb in zip(seams[:-1], seams[1:], tang[:-1], tang[1:]):
                piece = loop[a:b + 1]
                closed_segs.extend(("C", (bz[1], bz[2], bz[3])) for bz in fit_cubic(piece, ta, -tb, cfg.fit_tolerance))
            return FittedChain(loop[0], closed_segs)
        rs = np.roll(rs, -corners[0], axis=0)
        corners = [(c - corners[0]) % len(rs) for c in corners] + [len(rs)]
        rs = np.vstack([rs, rs[:1]])
    else:
        corners = [0] + [c for c in corners if 0 < c < len(rs) - 1] + [len(rs) - 1]

    segs: List[Tuple[str, Tuple[np.ndarray, ...]]] = []
    for a, b in zip(corners[:-1], corners[1:]):
        piece = _smooth_open(rs[a:b + 1].copy(), sig)
        segs.extend(_fit_piece(piece, cfg, step))
    return FittedChain(rs[0], segs)


# --------------------------------------------------------------------------- assembly


def _fmt(v: float, decimals: int) -> str:
    if not math.isfinite(v):
        return "0"
    s = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def assemble_paths(chains: List[Chain], fitted: List[FittedChain], decimals: int) -> Dict[int, str]:
    """Build one compound path per label from shared fitted chains."""
    by_label: Dict[int, List[FittedChain]] = {}
    for ch, fc in zip(chains, fitted):
        if ch.left > 0:
            by_label.setdefault(ch.left, []).append(fc)
        if ch.right > 0:
            by_label.setdefault(ch.right, []).append(fc.reversed())

    def key(p):
        return (round(float(p[0]) * 1000), round(float(p[1]) * 1000))

    def pt(p):
        return f"{_fmt(p[0], decimals)},{_fmt(p[1], decimals)}"

    out: Dict[int, str] = {}
    for lab, fcs in by_label.items():
        starts: Dict[Tuple[int, int], List[int]] = {}
        for i, fc in enumerate(fcs):
            starts.setdefault(key(fc.start), []).append(i)
        used = [False] * len(fcs)
        parts = []
        for i in range(len(fcs)):
            if used[i]:
                continue
            loop_start = key(fcs[i].start)
            cmds = [f"M{pt(fcs[i].start)}"]
            cur = i
            guard = 0
            while True:
                used[cur] = True
                for kind, args in fcs[cur].segs:
                    if kind == "L":
                        cmds.append(f"L{pt(args[0])}")
                    else:
                        cmds.append(f"C{pt(args[0])} {pt(args[1])} {pt(args[2])}")
                end = key(fcs[cur].end)
                if end == loop_start:
                    break
                nxt = [j for j in starts.get(end, []) if not used[j]]
                if not nxt:
                    logger.warning("Chain discontinuity encountered for label %s at point %s", lab, end)
                    break
                cur = nxt[0]
                guard += 1
                if guard > 1_000_000:
                    logger.warning("Loop guard limit exceeded for label %s at point %s", lab, end)
                    break
            cmds.append("Z")
            parts.append("".join(cmds))
        out[lab] = "".join(parts)
    return out


# --------------------------------------------------------------------------- driver


def gradient_score(rgba: np.ndarray, alpha_threshold: int = 128, top_n: int = 32) -> float:
    """Share of interior (non-edge) opaque pixels NOT covered by the ``top_n`` most
    frequent exact colours.

    Flat vector-style art: interiors use a handful of exact colours -> ~0.
    Painted / generated art (gradients, shading, noise): thousands of colours -> high.
    Independent of how gentle the gradients are. Returns a value in [0, 1].
    """
    opaque = rgba[:, :, 3] >= alpha_threshold
    f = rgba[:, :, :3].astype(np.int16)
    mx = np.stack([ndimage.maximum_filter(f[:, :, c], size=3) for c in range(3)], -1)
    mn = np.stack([ndimage.minimum_filter(f[:, :, c], size=3) for c in range(3)], -1)
    edge = ndimage.binary_dilation((mx - mn).max(-1) > 24, iterations=1)
    pool = ndimage.binary_erosion(opaque, iterations=2) & ~edge
    total = int(pool.sum())
    if total == 0:
        return 0.0
    px = rgba[:, :, :3][pool].astype(np.int32)
    keys = (px[:, 0] << 16) | (px[:, 1] << 8) | px[:, 2]
    _, counts = np.unique(keys, return_counts=True)
    covered = np.sort(counts)[::-1][:top_n].sum()
    return float(1.0 - covered / total)


def trace_planar(image: Union[str, Path, Image.Image, np.ndarray], config: Optional[PlanarTraceConfig] = None) -> PlanarTraceResult:
    cfg = config or PlanarTraceConfig()
    rgba = _load_rgba(image)
    source = rgba
    h, w = rgba.shape[:2]
    score = gradient_score(rgba, cfg.alpha_threshold)
    do_flatten = cfg.flatten if cfg.flatten is not None else score > cfg.flatten_auto_threshold
    if do_flatten:
        from inkmcp.vectorizer.flatten import FlattenConfig, flatten_gradients

        rgba = flatten_gradients(rgba, FlattenConfig(alpha_threshold=cfg.alpha_threshold))
    palette = build_palette(rgba, cfg, preflattened=do_flatten)
    lab = label_pixels(rgba, palette, cfg.alpha_threshold, perceptual=do_flatten)
    if cfg.remove_background:
        lab = _drop_border_background(lab)
    if cfg.unmix_antialias and not do_flatten:
        lab = unmix_antialias(rgba, lab, palette)
    lab = despeckle(lab, cfg.min_area)
    s = max(1, int(cfg.supersample))
    if cfg.subpixel_edges and s > 1:
        up = soft_supersample(lab, source, palette, s, cfg.subpixel_blur)
    else:
        up = supersample_labels(lab, s, cfg.blur_sigma)
    up = despeckle(up, cfg.min_area * s * s // 2)
    chains = extract_chains(up)
    fitted = [fit_chain(c, s, cfg) for c in chains]
    paths = assemble_paths(chains, fitted, cfg.decimals)

    pal_int: List[Tuple[int, int, int]] = [(int(round(c[0])), int(round(c[1])), int(round(c[2]))) for c in palette]
    # painter order: largest area first (irrelevant for planar output, nicer in editors)
    areas = {k: int((lab == k).sum()) for k in paths}
    order = sorted(paths, key=lambda k: -areas[k])
    body = []
    layers = []
    nodes = 0
    for idx, k in enumerate(order):
        r, g, b = pal_int[k - 1]
        hexc = f"#{r:02x}{g:02x}{b:02x}"
        d = paths[k]
        n = d.count("L") + d.count("C") + d.count("M")
        nodes += n
        layers.append({
            "layer_id": f"layer_{idx:02d}",
            "label": f"{idx:02d} - {hexc}",
            "color_hex": hexc,
            "path_id": f"color_{idx:02d}",
            "d": d,
            "fill_rule": "nonzero",
            "z_index": idx,
            "nodes": n,
            "area_px": areas[k],
        })
        body.append(
            f'  <g inkscape:groupmode="layer" id="layer_{idx:02d}" inkscape:label="{idx:02d} - {hexc}">\n'
            f'    <path id="color_{idx:02d}" fill="{hexc}" fill-rule="nonzero" d="{d}"/>\n'
            f"  </g>"
        )
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n' + "\n".join(body) + "\n</svg>\n"
    )
    stats = {"gradient_score": round(float(score), 4), "flattened": bool(do_flatten)}
    return PlanarTraceResult(svg, w, h, pal_int, nodes, len(chains), len(order), layers=layers, stats=stats)


def _drop_border_background(lab: np.ndarray) -> np.ndarray:
    """Treat the label dominating the image border (>60%) as background."""
    border = np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]])
    border = border[border > 0]
    if len(border) == 0:
        return lab
    counts = np.bincount(border)
    k = int(counts.argmax())
    if counts[k] < 0.6 * (2 * (lab.shape[0] + lab.shape[1])):
        return lab
    # only remove the region(s) of that color connected to the border
    n, cc = cv2.connectedComponents((lab == k).astype(np.uint8), connectivity=4)
    edge_ids = np.unique(np.concatenate([cc[0, :], cc[-1, :], cc[:, 0], cc[:, -1]]))
    edge_ids = edge_ids[edge_ids > 0]
    out = lab.copy()
    out[np.isin(cc, edge_ids) & (lab == k)] = 0
    return out
