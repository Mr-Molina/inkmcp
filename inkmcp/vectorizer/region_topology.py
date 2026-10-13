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
        h, w = binary_mask.shape[:2]
        processed = binary_mask.copy()

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
            dist = cv2.distanceTransform(region_mask, cv2.DIST_L2, 5)
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
