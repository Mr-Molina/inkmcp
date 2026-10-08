"""Unit tests for Blender-Inkscape hybrid execution and projective geometry.

Tests:
- parse_hybrid_blocks in blender_inkscape_hybrid.py and blender_addon_inkscape_hybrid.py
  (whitespace robustness, leading indentation, and case-insensitivity under LOGIC-028)
- Recursive subdivision depth bounding and NoneType handling in examples/blender2inkscape.py
  (LOGIC-002, LOGIC-019)
- Y coordinate conversion and perspective division guarding in examples/blender2inkscape.py
  (LOGIC-003, LOGIC-018)
- Addon operator poll and robust unregister (LOGIC-029)
- Structured JSON bootstrap variable serialization (PERF-003, LOGIC-020, LOGIC-021)
"""

import sys
import os
import json
import importlib
import pytest
from unittest.mock import MagicMock, patch

# Re-export mock classes from conftest so tests can reference them directly
from tests.conftest import MockVector, MockMatrix


# ---------------------------------------------------------------------------
# Module-level references populated by the _blender_modules autouse fixture
# ---------------------------------------------------------------------------
bih = None   # blender_inkscape_hybrid
baih = None  # blender_addon_inkscape_hybrid
b2i = None   # examples.blender2inkscape


@pytest.fixture(autouse=True, scope="module")
def _blender_modules(mock_bpy_modules):
    """Import the blender target modules AFTER bpy mocks are in place.

    Uses importlib to ensure the modules are (re-)loaded with the mocked
    dependencies available in sys.modules. Populates the module-level
    bih / baih / b2i references so test classes can use them.
    """
    global bih, baih, b2i

    # Ensure repo root is importable (needed for top-level blender_* modules)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    original_path = sys.path[:]
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    try:
        # Force (re-)import so mocks are picked up
        if "blender_inkscape_hybrid" in sys.modules:
            bih = importlib.reload(sys.modules["blender_inkscape_hybrid"])
        else:
            import blender_inkscape_hybrid
            bih = blender_inkscape_hybrid

        if "blender_addon_inkscape_hybrid" in sys.modules:
            baih = importlib.reload(sys.modules["blender_addon_inkscape_hybrid"])
        else:
            import blender_addon_inkscape_hybrid
            baih = blender_addon_inkscape_hybrid

        if "examples.blender2inkscape" in sys.modules:
            b2i = importlib.reload(sys.modules["examples.blender2inkscape"])
        else:
            import examples.blender2inkscape
            b2i = examples.blender2inkscape

        yield
    finally:
        # Restore sys.path
        sys.path[:] = original_path


# ==============================================================================
# Tests for parse_hybrid_blocks (LOGIC-028)
# ==============================================================================

class TestParseHybridBlocksStandalone:
    """Tests for parse_hybrid_blocks in blender_inkscape_hybrid.py."""

    def test_standard_blocks(self):
        code = (
            "# @local\n"
            "x = 10\n"
            "# @inkscape\n"
            "svg.append(Circle())\n"
            "# @local\n"
            "print(x)"
        )
        blocks = bih.parse_hybrid_blocks(code)
        assert len(blocks) == 3
        assert blocks[0][0] == "local"
        assert "x = 10" in blocks[0][1]
        assert blocks[1][0] == "inkscape"
        assert "Circle()" in blocks[1][1]
        assert blocks[2][0] == "local"
        assert "print(x)" in blocks[2][1]

    def test_whitespace_and_case_variations(self):
        code = (
            "   #   @LOCAL  \n"
            "v = 42\n"
            "#\t@INKSCAPE\n"
            "path = PathElement()\n"
            "  # @local\n"
            "circle = Circle()"
        )
        blocks = bih.parse_hybrid_blocks(code)
        assert len(blocks) == 3
        assert blocks[0][0] == "local"
        assert "v = 42" in blocks[0][1]
        assert blocks[1][0] == "inkscape"
        assert "path = PathElement()" in blocks[1][1]
        assert blocks[2][0] == "local"
        assert "circle = Circle()" in blocks[2][1]

    def test_no_magic_comments_defaults_to_local(self):
        code = "a = 1\nb = 2\nc = a + b"
        blocks = bih.parse_hybrid_blocks(code)
        assert len(blocks) == 1
        assert blocks[0][0] == "local"
        assert blocks[0][1] == code


class TestParseHybridBlocksAddon:
    """Tests for parse_hybrid_blocks in blender_addon_inkscape_hybrid.py."""

    def test_addon_standard_blocks(self):
        code = (
            "# @inkscape\n"
            "rect = Rectangle()\n"
            "# @local\n"
            "mesh = bpy.data.meshes.new('test')"
        )
        blocks = baih.parse_hybrid_blocks(code)
        assert len(blocks) == 2
        assert blocks[0][0] == "inkscape"
        assert "Rectangle()" in blocks[0][1]
        assert blocks[1][0] == "local"
        assert "bpy.data.meshes" in blocks[1][1]

    def test_addon_whitespace_and_case_variations(self):
        code = (
            "\t#  @local\n"
            "init_var = True\n"
            "   # @InKsCaPe   \n"
            "export_item()"
        )
        blocks = baih.parse_hybrid_blocks(code)
        assert len(blocks) == 2
        assert blocks[0][0] == "local"
        assert "init_var = True" in blocks[0][1]
        assert blocks[1][0] == "inkscape"
        assert "export_item()" in blocks[1][1]


# ==============================================================================
# Tests for Recursive Subdivision Depth Bounding (LOGIC-002, LOGIC-019)
# ==============================================================================

class TestRecursiveSubdivision:
    """Tests for approx_segment_recursive bounding and safety."""

    def test_max_depth_bounding(self):
        """Verify recursion terminates at max_depth without exceeding stack depth."""
        p0 = MockVector((0.0, 0.0, 0.0))
        p1 = MockVector((0.0, 1.0, 0.0))
        p2 = MockVector((1.0, 1.0, 0.0))
        p3 = MockVector((1.0, 0.0, 0.0))

        # Directly at or beyond max_depth
        res = b2i.approx_segment_recursive(p0, p1, p2, p3, tolerance=0.0001, depth=8, max_depth=8)
        assert len(res) == 1
        assert res == [[p0, p1, p2, p3]]

    def test_none_point_handling_returns_empty_list(self):
        """LOGIC-019: If any candidate point fails projection, return empty list []."""
        p0 = MockVector((0.0, 0.0, 0.0))
        p1 = MockVector((0.0, 1.0, 0.0))
        p2 = MockVector((1.0, 1.0, 0.0))
        p3 = MockVector((1.0, 0.0, 0.0))

        # Patch approx_segment_single to return None for candidate points
        with patch.object(b2i, "approx_segment_single", return_value=(None, None, None, None)):
            res = b2i.approx_segment_recursive(p0, p1, p2, p3, tolerance=0.5, depth=0, max_depth=8)
            assert res == []

    def test_recursive_subdivision_terminates_at_max_depth(self):
        """Even with non-zero projection error, recursion must stop at depth=max_depth."""
        p0 = MockVector((0.0, 0.0, 0.0))
        p1 = MockVector((1.0, 2.0, 0.0))
        p2 = MockVector((2.0, 1.0, 0.0))
        p3 = MockVector((3.0, 0.0, 0.0))

        # Mock approx_segment_single and getSVGPt so error exceeds tolerance and forces subdivision
        with patch.object(b2i, "approx_segment_single", return_value=(MockVector((0, 0, 0)), MockVector((1, 0, 0)), MockVector((2, 0, 0)), MockVector((3, 0, 0)))), \
             patch.object(b2i, "getSVGPt", return_value=MockVector((10.0, 10.0, 0.0))):
            res = b2i.approx_segment_recursive(p0, p1, p2, p3, tolerance=0.5, depth=0, max_depth=3)
            # Binary tree of depth 3 produces 2^3 = 8 leaf segments
            assert len(res) == 8


# ==============================================================================
# Tests for Y Coordinate Conversion & Perspective Division (LOGIC-003, LOGIC-018)
# ==============================================================================

class TestProjectiveGeometry:
    """Tests for NDC to SVG coordinate transformation and perspective clipping."""

    def test_y_axis_inversion_formula(self):
        """LOGIC-018: final_y = (1.0 - y_ndc) / 2.0 maps top to 0 and bottom to 1."""
        # Top of NDC viewport (y = +1.0) -> SVG top (y = 0.0)
        y_top_svg = (1.0 - 1.0) / 2.0
        assert y_top_svg == 0.0

        # Center of NDC viewport (y = 0.0) -> SVG center (y = 0.5)
        y_center_svg = (1.0 - 0.0) / 2.0
        assert y_center_svg == 0.5

        # Bottom of NDC viewport (y = -1.0) -> SVG bottom (y = 1.0)
        y_bottom_svg = (1.0 - (-1.0)) / 2.0
        assert y_bottom_svg == 1.0

    def test_perspective_division_guard(self):
        """LOGIC-003: proj_4d.w <= 1e-4 must return None (reject points behind camera)."""
        # Mock 3D View context
        mock_area = MagicMock()
        mock_area.type = "VIEW_3D"
        mock_region = MagicMock()
        mock_region.type = "WINDOW"
        mock_area.regions = [mock_region]
        mock_space = MagicMock()
        mock_space.region_quadviews = []
        mock_rv3d = MagicMock()

        # Matrix returning w <= 1e-4
        proj_matrix = MagicMock()
        proj_matrix.__matmul__ = MagicMock(return_value=MockVector((1.0, 1.0, 1.0, 0.0)))  # w = 0
        mock_rv3d.perspective_matrix = proj_matrix
        mock_space.region_3d = mock_rv3d
        mock_area.spaces.active = mock_space

        with patch.object(b2i.bpy.context.screen, "areas", [mock_area]):
            pt = b2i.getSVGPt((0.0, 0.0, -5.0))
            assert pt is None

    def test_perspective_division_valid_w(self):
        """Valid w > 1e-4 correctly performs perspective division and converts to SVG coords."""
        mock_area = MagicMock()
        mock_area.type = "VIEW_3D"
        mock_region = MagicMock()
        mock_region.type = "WINDOW"
        mock_area.regions = [mock_region]
        mock_space = MagicMock()
        mock_space.region_quadviews = []
        mock_rv3d = MagicMock()

        # proj_4d with x=2, y=2, z=1, w=4 -> ndc x=0.5, y=0.5
        proj_matrix = MagicMock()
        proj_matrix.__matmul__ = MagicMock(return_value=MockVector((2.0, 2.0, 1.0, 4.0)))
        mock_rv3d.perspective_matrix = proj_matrix
        mock_space.region_3d = mock_rv3d
        mock_area.spaces.active = mock_space

        with patch.object(b2i.bpy.context.screen, "areas", [mock_area]):
            pt = b2i.getSVGPt((1.0, 1.0, 2.0))
            assert pt is not None
            # x_ndc = 2.0 / 4.0 = 0.5 -> final_x = (0.5 + 1.0) / 2.0 = 0.75
            assert pt.x == pytest.approx(0.75)
            # y_ndc = 2.0 / 4.0 = 0.5 -> final_y = (1.0 - 0.5) / 2.0 = 0.25
            assert pt.y == pytest.approx(0.25)


# ==============================================================================
# Tests for Addon Operator Poll & Unregister (LOGIC-029)
# ==============================================================================

class TestAddonOperatorPollAndUnregister:
    """Tests for SCRIPT_OT_run_hybrid.poll and safe keymap cleanup."""

    def test_poll_returns_false_when_no_text_editor(self):
        context = MagicMock()
        context.space_data = None
        assert baih.SCRIPT_OT_run_hybrid.poll(context) is False

        context.space_data = MagicMock()
        context.space_data.type = "VIEW_3D"
        context.space_data.text = MagicMock()
        assert baih.SCRIPT_OT_run_hybrid.poll(context) is False

    def test_poll_returns_false_when_no_text_buffer(self):
        context = MagicMock()
        context.space_data = MagicMock()
        context.space_data.type = "TEXT_EDITOR"
        context.space_data.text = None
        assert baih.SCRIPT_OT_run_hybrid.poll(context) is False

    def test_poll_returns_true_with_active_text_editor(self):
        context = MagicMock()
        context.space_data = MagicMock()
        context.space_data.type = "TEXT_EDITOR"
        context.space_data.text = MagicMock()
        assert baih.SCRIPT_OT_run_hybrid.poll(context) is True

    def test_unregister_handles_keymap_exception_gracefully(self):
        """LOGIC-029: unregister() wraps keymap removal in try-except."""
        faulty_km = MagicMock()
        faulty_km.keymap_items.remove.side_effect = RuntimeError("Keymap already removed")
        faulty_kmi = MagicMock()

        baih.addon_keymaps.clear()
        baih.addon_keymaps.append((faulty_km, faulty_kmi))

        # unregister must not raise exception
        baih.unregister()
        assert len(baih.addon_keymaps) == 0


# ==============================================================================
# Tests for Variable Serialization & Execution (PERF-003, LOGIC-020, LOGIC-021)
# ==============================================================================

class TestVariableSerializationAndTempfile:
    """Tests for structured json.loads bootstrap and tempfile execution."""

    def test_tempfile_created_and_unlinked_in_execute_inkscape_block(self):
        """LOGIC-021 / SEC-006: Execute via tempfile with -f and verify unlinking."""
        unlinked_files = []
        orig_unlink = os.unlink

        def mock_unlink(path):
            unlinked_files.append(path)
            orig_unlink(path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "result": {
                "success": True,
                "response": {
                    "data": {
                        "execution_successful": True,
                        "output": "ok",
                        "local_variables": {"exported_var": 999}
                    }
                }
            }
        })

        with patch("subprocess.run", return_value=mock_result) as mock_subproc, \
             patch("os.unlink", side_effect=mock_unlink):
            res = bih.execute_inkscape_block(
                code="print('test')",
                variables={"param1": 123}
            )

            assert mock_subproc.called
            call_args = mock_subproc.call_args[0][0]
            assert "-f" in call_args
            # Verify temp file was unlinked in finally:
            assert len(unlinked_files) == 1
            # LOGIC-020: verify returned local_variables
            assert res["success"] is True
            assert res["variables"] == {"exported_var": 999}

    def test_json_loads_bootstrap_structure(self):
        """PERF-003: Verify structured json.loads bootstrap is used in addon execution."""
        captured_code = []

        def mock_named_tempfile(*args, **kwargs):
            real_temp = MagicMock()
            def mock_write(content):
                captured_code.append(content)
            real_temp.__enter__.return_value.write = mock_write
            real_temp.__enter__.return_value.name = "mock_temp.py"
            return real_temp

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "result": {
                "success": True,
                "response": {
                    "data": {
                        "execution_successful": True,
                        "output": "ok",
                        "local_variables": {}
                    }
                }
            }
        })

        with patch("tempfile.NamedTemporaryFile", side_effect=mock_named_tempfile), \
             patch("subprocess.run", return_value=mock_result), \
             patch("os.unlink"), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.isfile", return_value=True):
            baih.execute_inkscape_block(
                code="print('hello')",
                variables={"coords": [10.5, 20.5], "title": "Shape"},
                inkmcp_cli_path="inkmcpcli.py"
            )

            assert len(captured_code) == 1
            code_text = captured_code[0]
            assert "import json" in code_text
            assert "_inkmcp_vars = json.loads(" in code_text
            assert "coords = _inkmcp_vars[\"coords\"]" in code_text
            assert "title = _inkmcp_vars[\"title\"]" in code_text
            assert "del _inkmcp_vars" in code_text
