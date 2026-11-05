"""Pytest wrapper for root-level test_hybrid.py smoke-test script.

The original test_hybrid.py uses top-level assert statements and lives at
the repository root, so pytest (configured with testpaths = tests) never
discovers it. This module re-exercises its key assertions as proper test
functions.
"""

import random


# ---------------------------------------------------------------------------
# Helpers (mirrors of the standalone fallback classes in test_hybrid.py)
# ---------------------------------------------------------------------------

class Circle:
    def __init__(self):
        self.attrib = {}

    def set(self, key, value):
        self.attrib[str(key)] = str(value)

    def get(self, key, default=None):
        return self.attrib.get(str(key), default)

    def delete(self):
        pass


class MockSVG:
    def __init__(self):
        self.elements = []

    def append(self, elem):
        self.elements.append(elem)

    def remove(self, elem):
        if elem in self.elements:
            self.elements.remove(elem)

    def getElementById(self, elem_id):
        for elem in self.elements:
            if hasattr(elem, "get") and elem.get("id") == elem_id:
                return elem
        return None

    def iter(self):
        return iter(self.elements)


def _get_element_by_id(svg, elem_id):
    res = svg.getElementById(elem_id)
    if res is not None:
        return res
    for elem in svg.iter():
        if hasattr(elem, "get") and elem.get("id") == elem_id:
            return elem
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_random_point_generation():
    """Verify reproducible random point generation (seed=42)."""
    random.seed(42)
    points = [(random.randint(10, 200), random.randint(10, 200)) for _ in range(5)]
    assert len(points) == 5
    for pt in points:
        assert 10 <= pt[0] <= 200 and 10 <= pt[1] <= 200, f"Point {pt} out of bounds"


def test_circle_creation_and_lookup():
    """Create circles at random points and verify they are retrievable."""
    random.seed(42)
    points = [(random.randint(10, 200), random.randint(10, 200)) for _ in range(5)]
    svg = MockSVG()

    created_ids = []
    for i, (x, y) in enumerate(points):
        circle = Circle()
        elem_id = f"point_{i}"
        circle.set("id", elem_id)
        circle.set("cx", str(x))
        circle.set("cy", str(y))
        circle.set("r", "10")
        circle.set("fill", "blue")
        svg.append(circle)
        created_ids.append(elem_id)

    assert len(created_ids) == len(points)
    for elem_id in created_ids:
        elem = _get_element_by_id(svg, elem_id)
        assert elem is not None, f"Circle {elem_id} not found"
        assert elem.get("fill") == "blue"


def test_circle_modification_and_cleanup():
    """Modify circle colours, then remove all elements and verify cleanup."""
    random.seed(42)
    points = [(random.randint(10, 200), random.randint(10, 200)) for _ in range(5)]
    colors = ["red", "green", "brown", "yellow", "purple"]
    svg = MockSVG()

    for i, (x, y) in enumerate(points):
        circle = Circle()
        circle.set("id", f"point_{i}")
        circle.set("cx", str(x))
        circle.set("cy", str(y))
        circle.set("r", "10")
        circle.set("fill", "blue")
        svg.append(circle)

    # Modify
    for i, color in enumerate(colors):
        elem = _get_element_by_id(svg, f"point_{i}")
        assert elem is not None
        elem.set("fill", color)
        elem.set("r", "15")
        assert elem.get("fill") == color
        assert elem.get("r") == "15"

    # Cleanup
    for i in range(len(points)):
        elem = _get_element_by_id(svg, f"point_{i}")
        if elem is not None:
            svg.remove(elem)

    for i in range(len(points)):
        assert _get_element_by_id(svg, f"point_{i}") is None, f"Cleanup failed: point_{i} still present"
