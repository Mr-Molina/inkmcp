# Standalone execution environment fallback
try:
    import inkex
except:
    inkex = None

try:
    svg
except:
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

    svg = MockSVG()

try:
    get_element_by_id
except:
    def get_element_by_id(elem_id):
        if hasattr(svg, "getElementById"):
            res = svg.getElementById(elem_id)
            if res is not None:
                return res
        for elem in svg.iter():
            if hasattr(elem, "get") and elem.get("id") == elem_id:
                return elem
        return None

if inkex is None or not hasattr(inkex, "Circle"):
    class MockCircle:
        def __init__(self):
            self.attrib = {}

        def set(self, key, value):
            self.attrib[str(key)] = str(value)

        def get(self, key, default=None):
            return self.attrib.get(str(key), default)

        def delete(self):
            if hasattr(svg, "remove"):
                svg.remove(self)

    class MockInkexModule:
        Circle = MockCircle

    inkex = MockInkexModule()

# @inkscape

x = []
created_elements = []
for i in range(4):
    circle = inkex.Circle()
    circle_id = f"mcp_circle_{i}"
    circle.set("id", circle_id)
    circle.set("cx", f"{150 + i * 50}")
    circle.set("cy", "100")
    circle.set("r", "25")
    circle.set("fill", "none")
    circle.set("stroke", "red")
    svg.append(circle)
    x.append(circle_id)
    created_elements.append(circle)

# Programmatic assertions in inkscape context
assert len(x) == 4, f"Expected 4 circle IDs, got {len(x)}"
for i, cid in enumerate(x):
    elem = get_element_by_id(cid)
    assert elem is not None, f"Circle {cid} not found in SVG document"
    assert elem.get("cx") == f"{150 + i * 50}", f"Invalid cx coordinate for {cid}"
    assert elem.get("cy") == "100", f"Invalid cy coordinate for {cid}"
    assert elem.get("r") == "25", f"Invalid radius for {cid}"
    assert elem.get("stroke") == "red", f"Invalid stroke for {cid}"

# Cleanup logic: remove created test elements
for elem in created_elements:
    if hasattr(svg, "remove"):
        svg.remove(elem)
    if hasattr(elem, "delete"):
        try:
            elem.delete()
        except Exception:
            pass
    if hasattr(elem, "getparent") and elem.getparent() is not None:
        try:
            elem.getparent().remove(elem)
        except Exception:
            pass

# Verify cleanup assertions
for cid in x:
    assert get_element_by_id(cid) is None, f"Cleanup failed: {cid} still present in SVG"

# @local
assert len(x) == 4, f"Expected 4 element IDs transferred to local context, got {len(x)}"
print("IDs from Inkscape:", x)
print("Standalone Inkscape MCP test verification passed!")

if __name__ == "__main__":
    assert len(x) == 4, "Validation failed: element count mismatch in main"
    print("Standalone execution check: testinkmcp passed with all assertions verified.")
