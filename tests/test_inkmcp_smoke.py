"""Pytest wrapper for root-level testinkmcp.py smoke-test script.

The original testinkmcp.py uses top-level assert statements and lives at
the repository root, so pytest (configured with testpaths = tests) never
discovers it. This module re-exercises its key assertions as proper test
functions.
"""


# ---------------------------------------------------------------------------
# Helpers (mirrors of the standalone fallback classes in testinkmcp.py)
# ---------------------------------------------------------------------------

class MockCircle:
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
        self._counter = 0

    def append(self, elem):
        if hasattr(elem, "get") and not elem.get("id"):
            self._counter += 1
            elem.set("id", f"circle_{self._counter}")
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

def test_circle_creation_and_attributes():
    """Create 4 circles with explicit IDs and verify attributes."""
    svg = MockSVG()
    created_ids = []
    created_elements = []

    for i in range(4):
        circle = MockCircle()
        circle_id = f"mcp_circle_{i}"
        circle.set("id", circle_id)
        circle.set("cx", f"{150 + i * 50}")
        circle.set("cy", "100")
        circle.set("r", "25")
        circle.set("fill", "none")
        circle.set("stroke", "red")
        svg.append(circle)
        created_ids.append(circle_id)
        created_elements.append(circle)

    assert len(created_ids) == 4
    for i, cid in enumerate(created_ids):
        elem = _get_element_by_id(svg, cid)
        assert elem is not None, f"Circle {cid} not found in SVG"
        assert elem.get("cx") == f"{150 + i * 50}"
        assert elem.get("cy") == "100"
        assert elem.get("r") == "25"
        assert elem.get("stroke") == "red"


def test_circle_cleanup():
    """Create circles then remove them and verify none remain."""
    svg = MockSVG()
    created_ids = []
    created_elements = []

    for i in range(4):
        circle = MockCircle()
        circle_id = f"mcp_circle_{i}"
        circle.set("id", circle_id)
        circle.set("cx", f"{150 + i * 50}")
        circle.set("cy", "100")
        circle.set("r", "25")
        svg.append(circle)
        created_ids.append(circle_id)
        created_elements.append(circle)

    # Cleanup
    for elem in created_elements:
        svg.remove(elem)

    for cid in created_ids:
        assert _get_element_by_id(svg, cid) is None, f"Cleanup failed: {cid} still present"


def test_id_transfer_to_local_context():
    """Verify that IDs list propagates correctly (simulating @local context)."""
    svg = MockSVG()
    x = []

    for i in range(4):
        circle = MockCircle()
        circle_id = f"mcp_circle_{i}"
        circle.set("id", circle_id)
        svg.append(circle)
        x.append(circle_id)

    assert len(x) == 4, f"Expected 4 element IDs, got {len(x)}"
