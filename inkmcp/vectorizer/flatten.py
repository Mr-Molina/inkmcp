"""Edge-aware gradient flattening for raster artwork prior to planar tracing.

Illustrations exported from painting / generative tools carry soft gradients,
highlights, and shading. Quantizing those directly produces posterized bands
("blotchy windows") and wastes palette slots on gradient steps, which in turn
pushes genuinely distinct small colors (shadows, thin outlines) onto the wrong
palette entry.

This module turns such images into true flat-color art:

1. Light edge-preserving denoise (bilateral filter in RGB).
2. Build a 4-connected pixel graph in CIELAB; link two neighbours when their
   colour difference is below ``link_delta``. Smooth gradients change by a
   fraction of a unit per pixel and stay connected; real edges jump and break.
3. Connected components = regions. Each region is painted with its median
   colour, so a gradient collapses into a single flat fill.
4. Fragments smaller than ``min_region`` (anti-alias bands, noise) adopt the
   colour of the spatially nearest real region.
5. Optionally, adjacent regions with nearly identical colours are merged
   (catches gradients split by a noisy pixel).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import cv2
import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


@dataclass
class FlattenConfig:
    link_delta: float = 3.0  # CIELAB units between neighbours to stay in one region
    texture_delta: float = 8.0  # looser second pass for grainy areas left unassigned
    texture_min_region: int = 6  # grainy fragments this big keep their own colour; AA specks are 1-3px
    min_region: int = 24  # px; smaller components are treated as transition pixels
    merge_delta: float = 4.0  # merge adjacent regions whose medians differ less than this
    denoise: bool = True
    alpha_threshold: int = 128
    keep_thin_lines: bool = True
    keep_light_lines: bool = True  # also protect thin light strokes (trims, glints)
    line_width: int = 5  # max stroke width (px) detected as a thin line
    line_contrast: float = 12.0  # L* units darker than surroundings
    line_min_length: int = 10  # px; shorter ridge fragments are noise
    line_core_pct: float = 15.0  # colour strokes from their darkest N% of pixels
    drop_blend_strips: bool = True  # remove <=2px anti-alias blend bands along edges


def _to_lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def _thin_line_mask(lab: np.ndarray, opaque: np.ndarray, cfg: "FlattenConfig",
                    light: bool = False) -> np.ndarray:
    """Thin strokes via morphological black-hat (dark) or white top-hat (light) on L*.

    Closing with a kernel wider than the stroke erases it; the difference to the
    original lights up strokes narrower than ``line_width`` while leaving the
    edges of large dark shapes untouched (closing preserves step edges). The
    light variant (opening) catches cream trims and thin highlights.
    """
    L = lab[:, :, 0].astype(np.float32)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.line_width, cfg.line_width))
    resp = cv2.morphologyEx(L, cv2.MORPH_TOPHAT if light else cv2.MORPH_BLACKHAT, k)
    mask = (resp > cfg.line_contrast) & opaque
    if not mask.any():
        return mask
    n, cc, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    extent = np.maximum(stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT])
    good = extent >= cfg.line_min_length
    good[0] = False
    return good[cc]


def _line_cores(L: np.ndarray, lids: np.ndarray, nl: int, pct: float) -> np.ndarray:
    """Darkest ``pct`` percent of each thin-line component (the stroke's core).

    Thin strokes are mostly anti-aliased edge pixels: a navy outline on red has
    more red/navy blend pixels than pure navy ones, so a plain median comes out
    maroon. Colouring from the darkest pixels recovers the real ink colour.
    """
    core = np.zeros(L.shape, bool)
    for i, sl in enumerate(ndimage.find_objects(lids), start=1):
        if sl is None:
            continue
        m = lids[sl] == i
        vals = L[sl][m]
        thr = np.percentile(vals, pct)
        core[sl] |= m & (L[sl] <= thr)
    return core


def _components(lab: np.ndarray, valid: np.ndarray, delta: float) -> Tuple[int, np.ndarray]:
    h, w = valid.shape
    idx = np.arange(h * w).reshape(h, w)
    rows, cols = [], []
    # horizontal links
    d = np.sqrt(((lab[:, 1:] - lab[:, :-1]) ** 2).sum(-1))
    m = (d < delta) & valid[:, 1:] & valid[:, :-1]
    rows.append(idx[:, :-1][m])
    cols.append(idx[:, 1:][m])
    # vertical links
    d = np.sqrt(((lab[1:, :] - lab[:-1, :]) ** 2).sum(-1))
    m = (d < delta) & valid[1:, :] & valid[:-1, :]
    rows.append(idx[:-1, :][m])
    cols.append(idx[1:, :][m])
    r = np.concatenate(rows)
    c = np.concatenate(cols)
    g = coo_matrix((np.ones(len(r), np.int8), (r, c)), shape=(h * w, h * w))
    n, lab_ids = connected_components(g, directed=False)
    return n, lab_ids.reshape(h, w)


def _region_medians(values: np.ndarray, ids: np.ndarray, n: int) -> np.ndarray:
    """Per-region median of each channel (values: (N, C), ids: (N,))."""
    order = np.argsort(ids, kind="stable")
    sid = ids[order]
    sv = values[order]
    starts = np.searchsorted(sid, np.arange(n))
    ends = np.searchsorted(sid, np.arange(n), side="right")
    out = np.zeros((n, values.shape[1]), np.float32)
    for k in np.nonzero(ends > starts)[0]:
        out[k] = np.median(sv[starts[k]:ends[k]], axis=0)
    return out


def flatten_gradients(rgba: np.ndarray, cfg: FlattenConfig | None = None) -> np.ndarray:
    """Return an RGBA image where every region is a single flat colour."""
    cfg = cfg or FlattenConfig()
    rgb = rgba[:, :, :3].copy()
    alpha = rgba[:, :, 3]
    opaque = alpha >= cfg.alpha_threshold
    if cfg.denoise:
        rgb = cv2.bilateralFilter(rgb, d=5, sigmaColor=18, sigmaSpace=3)
    lab = _to_lab(rgb)
    h, w = opaque.shape

    if cfg.keep_thin_lines:
        dark = _thin_line_mask(lab, opaque, cfg)
        light = _thin_line_mask(lab, opaque, cfg, light=True) & ~dark if cfg.keep_light_lines else np.zeros_like(opaque)
    else:
        dark = light = np.zeros_like(opaque)
    lines = dark | light
    n, ids = _components(lab, opaque & ~lines, cfg.link_delta)
    counts = np.bincount(ids.ravel(), minlength=n)
    big = counts >= cfg.min_region
    keep = opaque & ~lines & big[ids]
    if cfg.texture_delta > cfg.link_delta:
        # Textured flat areas (grainy dark outlines, brush noise) shatter at link_delta into
        # fragments below min_region, which would then inherit a neighbour's colour. Re-link
        # the leftovers with a looser threshold; AA blends still break at real edges.
        rest = opaque & ~lines & ~keep
        n2, ids2 = _components(lab, rest, cfg.texture_delta)
        big2 = np.bincount(ids2[rest], minlength=n2) >= cfg.texture_min_region
        add = rest & big2[ids2]
        ids = np.where(add, ids2 + n, ids)
        keep = keep | add
        n = n + n2
    colour_px = keep.copy()  # pixels allowed to vote on region colour
    if lines.any():
        for mask, sign in ((dark, 1.0), (light, -1.0)):
            if not mask.any():
                continue
            if sign < 0:
                # split light strokes by colour (an orange trim touching a cream one are two
                # strokes). Dark strokes are not split: grainy ink would shatter into specks.
                _, sids = _components(lab, mask, cfg.texture_delta)
                sizes = np.bincount(sids[mask], minlength=sids.max() + 1)
                piece = mask & (sizes[sids] >= cfg.texture_min_region)
                uniq_s, inv = np.unique(sids[piece], return_inverse=True)
                lids = np.zeros(mask.shape, np.int32)
                lids[piece] = inv + 1
                nl = len(uniq_s) + 1
            else:
                piece = mask
                nl, lids = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
            ids = np.where(piece, lids + n, ids)
            keep = keep | piece
            colour_px = colour_px | _line_cores(sign * lab[:, :, 0], lids, nl, cfg.line_core_pct)
            n = n + nl

    # region colours (median in Lab, restricted to colour-voting pixels)
    flat_ids = ids[keep]
    remap = -np.ones(n, np.int64)
    uniq = np.unique(flat_ids)
    remap[uniq] = np.arange(len(uniq))
    rid = remap[ids]
    rid[~keep] = -1
    m = len(uniq)
    med = _region_medians(lab[colour_px], rid[colour_px], m)

    if cfg.drop_blend_strips and m > 2:
        is_line = np.zeros(m, bool)
        if lines.any():
            is_line[np.unique(rid[lines & (rid >= 0)])] = True
        med_rgb = cv2.cvtColor(med.reshape(1, -1, 3).astype(np.float32), cv2.COLOR_LAB2RGB).reshape(-1, 3) * 255.0
        rid = _drop_blend_strips(med_rgb, rid, is_line)
        keep = rid >= 0
        colour_px &= keep

    if cfg.merge_delta > 0 and m > 1:
        med, rid = _merge_similar(med, rid, colour_px, lab, cfg.merge_delta)

    # transition / tiny pixels: adopt nearest kept region (spatially)
    if (~keep & opaque).any() and keep.any():
        _, (iy, ix) = ndimage.distance_transform_edt(~keep, return_indices=True)
        fill = opaque & ~keep
        rid[fill] = rid[iy[fill], ix[fill]]

    out_lab = np.zeros_like(lab)
    valid = rid >= 0
    out_lab[valid] = med[rid[valid]]
    out_rgb = cv2.cvtColor(out_lab, cv2.COLOR_LAB2RGB)
    out_rgb = np.clip(np.round(out_rgb * 255.0), 0, 255).astype(np.uint8)
    out = np.dstack([out_rgb, np.where(opaque, 255, 0).astype(np.uint8)])
    out[~valid & opaque, :3] = rgba[~valid & opaque, :3]
    return out


def _merge_similar(med: np.ndarray, rid: np.ndarray, keep: np.ndarray, lab: np.ndarray, delta: float):
    """Union adjacent regions whose median colours are within ``delta``."""
    a_h, b_h = rid[:, :-1], rid[:, 1:]
    a_v, b_v = rid[:-1, :], rid[1:, :]
    a = np.concatenate([a_h.ravel(), a_v.ravel()])
    b = np.concatenate([b_h.ravel(), b_v.ravel()])
    sel = (a >= 0) & (b >= 0) & (a != b)
    pairs = np.unique(np.stack([np.minimum(a[sel], b[sel]), np.maximum(a[sel], b[sel])], 1), axis=0)
    if len(pairs) == 0:
        return med, rid
    d = np.sqrt(((med[pairs[:, 0]] - med[pairs[:, 1]]) ** 2).sum(-1))
    pairs = pairs[d < delta]
    m = len(med)
    if len(pairs) == 0:
        return med, rid
    g = coo_matrix((np.ones(len(pairs), np.int8), (pairs[:, 0], pairs[:, 1])), shape=(m, m))
    n2, grp = connected_components(g, directed=False)
    new = rid.copy()
    new[rid >= 0] = grp[rid[rid >= 0]]
    med2 = _region_medians(lab[keep], new[keep], n2)
    return med2, new


def _adjacent_pairs(rid: np.ndarray) -> np.ndarray:
    a = np.concatenate([rid[:, :-1].ravel(), rid[:-1, :].ravel()])
    b = np.concatenate([rid[:, 1:].ravel(), rid[1:, :].ravel()])
    sel = (a >= 0) & (b >= 0) & (a != b)
    if not sel.any():
        return np.zeros((0, 2), np.int64)
    return np.unique(np.stack([np.minimum(a[sel], b[sel]), np.maximum(a[sel], b[sel])], 1), axis=0)


def _drop_blend_strips(med: np.ndarray, rid: np.ndarray, is_line: np.ndarray) -> np.ndarray:
    """Remove <=2px-wide regions whose colour is a blend of two neighbouring regions (``med`` in sRGB 0-255).

    Along a long anti-aliased edge the 1-2px band of blend pixels is
    near-uniform in colour along the edge, so it chains into a "region" large
    enough to survive ``min_region`` and gets its own (muddy) colour - the
    maroon/grey slivers next to outlines. Such strips are reset to -1 so they
    are re-filled from the nearest real region. Thin strokes detected by the
    line mask are exempt.
    """
    m = len(med)
    valid = rid >= 0
    bnd = np.zeros(rid.shape, bool)
    dh = rid[:, 1:] != rid[:, :-1]
    dv = rid[1:, :] != rid[:-1, :]
    bnd[:, 1:] |= dh
    bnd[:, :-1] |= dh
    bnd[1:, :] |= dv
    bnd[:-1, :] |= dv
    dist = ndimage.distance_transform_edt(~bnd)
    maxd = np.zeros(m, np.float32)
    np.maximum.at(maxd, rid[valid], dist[valid].astype(np.float32))
    thin = (maxd < 1.0) & ~is_line
    if not thin.any():
        return rid
    pairs = _adjacent_pairs(rid)
    nbrs: dict = {}
    for a, b in pairs:
        nbrs.setdefault(int(a), []).append(int(b))
        nbrs.setdefault(int(b), []).append(int(a))
    drop = []
    for r in np.nonzero(thin)[0]:
        nb = nbrs.get(int(r), [])
        c = med[r]
        found = False
        for i in range(len(nb)):
            for j in range(i + 1, len(nb)):
                A, B = med[nb[i]], med[nb[j]]
                ab = B - A
                den = float((ab * ab).sum())
                if den < 1.0:
                    continue
                t = float(((c - A) * ab).sum() / den)
                err = float(np.sqrt(((c - (A + t * ab)) ** 2).sum()))
                # AA blends are linear in sRGB: a real thin feature (orange trim between red and
                # cream) sits far off the red-cream line, a blend sits on it.
                if 0.05 < t < 0.95 and err < max(10.0, 0.08 * np.sqrt(den)):
                    found = True
                    break
            if found:
                break
        if found:
            drop.append(r)
    if not drop:
        return rid
    out = rid.copy()
    out[np.isin(rid, np.array(drop))] = -1
    return out
