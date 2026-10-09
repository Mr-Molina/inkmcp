"""Shared pytest fixtures for the inkmcp test suite.

Provides session-scoped mock modules for bpy/mathutils/bpy_extras so that
tests requiring Blender stubs can run in a standard Python environment without
polluting sys.modules for the rest of the session.
"""

import sys
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Mock classes (mirrors of what test_blender_hybrid.py previously defined at
# module level). Kept here so fixtures and tests can reference them.
# ---------------------------------------------------------------------------

class MockVector(tuple):
    """Minimal mathutils.Vector mock for testing geometric algorithms."""

    def __new__(cls, coords):
        return super().__new__(cls, tuple(float(c) for c in coords))

    @property
    def x(self):
        return self[0]

    @property
    def y(self):
        return self[1]

    @property
    def z(self):
        return self[2] if len(self) > 2 else 0.0

    @property
    def w(self):
        return self[3] if len(self) > 3 else 1.0

    @property
    def length_squared(self):
        return sum(c * c for c in self)

    def __add__(self, other):
        return MockVector(tuple(a + b for a, b in zip(self, other)))

    def __sub__(self, other):
        return MockVector(tuple(a - b for a, b in zip(self, other)))

    def __mul__(self, scalar):
        return MockVector(tuple(a * scalar for a in self))

    def __rmul__(self, scalar):
        return MockVector(tuple(a * scalar for a in self))

    def __truediv__(self, scalar):
        return MockVector(tuple(a / scalar for a in self))


class MockMatrix:
    """Minimal mathutils.Matrix mock."""

    def __init__(self, data=None):
        self.data = data

    def __matmul__(self, other):
        if hasattr(self, "_proj_result"):
            return self._proj_result
        return other


# ---------------------------------------------------------------------------
# Session-scoped fixture: inject bpy / mathutils / bpy_extras mocks
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mock_bpy_modules():
    """Inject mock bpy, mathutils, and bpy_extras modules into sys.modules.

    Saves any pre-existing keys so they can be restored during teardown,
    preventing cross-test pollution.
    """
    MOCK_KEYS = [
        "bpy", "bpy.types", "bpy.props",
        "mathutils",
        "bpy_extras", "bpy_extras.view3d_utils",
    ]

    # Snapshot current state
    saved = {key: sys.modules[key] for key in MOCK_KEYS if key in sys.modules}

    # Build mock objects
    mock_bpy = MagicMock()
    mock_types = MagicMock()
    mock_types.Operator = type("Operator", (), {})
    mock_types.AddonPreferences = type("AddonPreferences", (), {})
    mock_props = MagicMock()
    mock_props.StringProperty = MagicMock(return_value="")
    mock_bpy.types = mock_types
    mock_bpy.props = mock_props

    mock_mathutils = MagicMock()
    mock_mathutils.Vector = MockVector
    mock_mathutils.Matrix = MockMatrix

    mock_bpy_extras = MagicMock()
    mock_bpy_extras_view3d = MagicMock()

    # Inject
    sys.modules["bpy"] = mock_bpy
    sys.modules["bpy.types"] = mock_types
    sys.modules["bpy.props"] = mock_props
    sys.modules["mathutils"] = mock_mathutils
    sys.modules["bpy_extras"] = mock_bpy_extras
    sys.modules["bpy_extras.view3d_utils"] = mock_bpy_extras_view3d

    yield

    # Teardown: restore original state
    for key in MOCK_KEYS:
        if key in saved:
            sys.modules[key] = saved[key]
        else:
            sys.modules.pop(key, None)
