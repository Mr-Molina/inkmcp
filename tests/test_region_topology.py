import numpy as np
import cv2
from inkmcp.vectorizer.region_topology import RegionTopologyAnalyzer

def test_extract_fill_regions_circle():
    mask = np.full((100, 100), 255, dtype=np.uint8)
    cv2.circle(mask, (50, 50), 30, 0, thickness=2)

    analyzer = RegionTopologyAnalyzer()
    regions = analyzer.extract_fill_regions(mask, min_area=25)

    assert len(regions) >= 2
    inside_region = min(regions, key=lambda r: (r.pixel_x - 50)**2 + (r.pixel_y - 50)**2)
    assert abs(inside_region.pixel_x - 50) <= 2
    assert abs(inside_region.pixel_y - 50) <= 2
    assert 0.45 <= inside_region.u <= 0.55
    assert 0.45 <= inside_region.v <= 0.55

def test_extract_fill_regions_gap_healing():
    mask = np.full((100, 100), 255, dtype=np.uint8)
    cv2.circle(mask, (50, 50), 30, 0, thickness=2)
    mask[19:22, 49:52] = 255

    analyzer = RegionTopologyAnalyzer()
    regions = analyzer.extract_fill_regions(mask, min_area=25, close_gaps_kernel=5)
    inside_region = min(regions, key=lambda r: (r.pixel_x - 50)**2 + (r.pixel_y - 50)**2)
    assert abs(inside_region.pixel_x - 50) <= 2

def test_speckle_filtering():
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[10:13, 10:13] = 255
    analyzer = RegionTopologyAnalyzer()
    regions = analyzer.extract_fill_regions(mask, min_area=25)
    assert len(regions) == 0
