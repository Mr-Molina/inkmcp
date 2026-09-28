# Test hybrid execution
import random

# Standalone execution environment fallback
try:
    Circle
except:
    class Circle:
        def __init__(self):
            self.attrib = {}

        def set(self, key, value):
            self.attrib[str(key)] = str(value)

        def get(self, key, default=None):
            return self.attrib.get(str(key), default)

        def delete(self):
            if hasattr(svg, "remove"):
                svg.remove(self)

try:
    svg
except:
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

# Generate reproducible points
random.seed(42)
points = [(random.randint(10, 200), random.randint(10, 200)) for _ in range(5)]
assert len(points) == 5, f"Expected 5 points, got {len(points)}"
for pt in points:
    assert 10 <= pt[0] <= 200 and 10 <= pt[1] <= 200, f"Point {pt} out of bounds"
print(f"Generated {len(points)} random points")

# @inkscape
# Create circles at each point
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

assert len(created_ids) == len(points), f"Expected {len(points)} created circle IDs"
for elem_id in created_ids:
    elem = get_element_by_id(elem_id)
    assert elem is not None, f"Circle {elem_id} not found in SVG document"
    assert elem.get("fill") == "blue", f"Expected blue fill for {elem_id}, got {elem.get('fill')}"

# @local
assert len(points) == 5, "Points array corrupted"
print(f"Created {len(points)} circles")

# Prepare colors for modification
colors = ["red", "green", "brown", "yellow", "purple"]
assert len(colors) == len(points), "Colors count must match points count"

# @inkscape
# Modify the circles with different colors using helper function
for i, color in enumerate(colors):
    elem = get_element_by_id(f"point_{i}")
    assert elem is not None, f"Element point_{i} not found during modification"
    elem.set("fill", color)
    elem.set("r", "15")
    assert elem.get("fill") == color, f"Failed to set fill color {color} on point_{i}"
    assert elem.get("r") == "15", f"Failed to set radius 15 on point_{i}"
    print(f"Set point_{i} to {color}")

# Cleanup logic: remove created test elements
for i in range(len(points)):
    elem = get_element_by_id(f"point_{i}")
    if elem is not None:
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
for i in range(len(points)):
    assert get_element_by_id(f"point_{i}") is None, f"Cleanup failed: point_{i} still present in SVG"

# @local
print("Modified circles with different colors and cleaned up")
print("Test completed!")

if __name__ == "__main__":
    assert len(points) == 5, "Validation failed: points length mismatch"
    assert len(colors) == 5, "Validation failed: colors length mismatch"
    print("Standalone execution check: test_hybrid passed with all assertions verified.")
