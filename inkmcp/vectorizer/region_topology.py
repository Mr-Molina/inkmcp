"""Topological face and centroid extraction module for coloring book fills."""
from dataclasses import dataclass
from typing import List
import cv2
import numpy as np

@dataclass
class RegionTarget:
    label: int
    area: int
    u: float
    v: float
    pixel_x: int
    pixel_y: int

class RegionTopologyAnalyzer:
    """Analyzes binary line art to find closed white regions and interior click centroids."""

    def extract_fill_regions(
        self,
        binary_mask: np.ndarray,
        min_area: int = 25,
        close_gaps_kernel: int = 3,
    ) -> List[RegionTarget]:
        if binary_mask.ndim < 2:
            return []
        h, w = binary_mask.shape[:2]
        if h == 0 or w == 0:
            return []
        processed = binary_mask.copy()
        if processed.ndim == 3:
            processed = processed[:, :, 0]

        if close_gaps_kernel > 1:
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (close_gaps_kernel, close_gaps_kernel)
            )
            inv = cv2.bitwise_not(processed)
            inv_closed = cv2.morphologyEx(inv, cv2.MORPH_CLOSE, kernel)
            processed = cv2.bitwise_not(inv_closed)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            processed, connectivity=8
        )

        regions: List[RegionTarget] = []

        for lbl in range(1, num_labels):
            area = stats[lbl, cv2.CC_STAT_AREA]
            if area < min_area:
                continue

            region_mask = (labels == lbl).astype(np.uint8) * 255
            padded_mask = np.pad(region_mask, pad_width=1, mode="constant", constant_values=0)
            dist = cv2.distanceTransform(padded_mask, cv2.DIST_L2, 5)[1:-1, 1:-1]
            _, _, _, max_loc = cv2.minMaxLoc(dist)

            best_x, best_y = max_loc
            u = float(best_x) / float(w)
            v = float(best_y) / float(h)

            regions.append(
                RegionTarget(
                    label=lbl,
                    area=area,
                    u=u,
                    v=v,
                    pixel_x=best_x,
                    pixel_y=best_y,
                )
            )

        return regions
