"""Unit tests for element mapping and placement in inkmcp.inkmcpops.element_mapping.

Tests get_element_class (including BaseElement exclusion),
should_place_in_defs (marker, clipPath, symbol, gradients),
get_unique_id with collision detection and reserved_ids,
and ensure_defs_section.
"""

from unittest.mock import MagicMock
import inspect
import pytest
import inkex
from inkmcp.inkmcpops.element_mapping import (
    get_element_class,
    should_place_in_defs,
    get_unique_id,
    ensure_defs_section,
)


class TestGetElementClass:
    """Tests for get_element_class resolution and filtering."""

    def test_get_element_class_standard_elements(self):
        """Test resolving standard SVG element classes."""
        assert get_element_class("circle") == inkex.Circle
        assert get_element_class("rect") == inkex.Rectangle
        assert get_element_class("path") == inkex.PathElement
        assert get_element_class("text") == inkex.TextElement
        assert get_element_class("g") == inkex.Group
        assert get_element_class("use") == inkex.Use
        assert get_element_class("image") == inkex.Image

    def test_get_element_class_excludes_base_element(self):
        """Test that BaseElement and generic element bases are excluded from instantiation."""
        # BaseElement is an abstract base and should not be returned as an instantiable element
        assert get_element_class("baseElement") is None, "BaseElement must be excluded from instantiable classes"
        assert get_element_class("BaseElement") is None, "BaseElement must be excluded from instantiable classes"
        assert get_element_class("element") is None or get_element_class("element") != getattr(inkex, "BaseElement", None)

    def test_get_element_class_unknown_tag(self):
        """Test that unknown or empty tags return None."""
        assert get_element_class("nonExistentElementTagXYZ") is None
        assert get_element_class("") is None


class TestShouldPlaceInDefs:
    """Tests for should_place_in_defs categorizing elements for <defs> placement."""

    def test_defs_elements_return_true(self):
        """Test that marker, clipPath, symbol, and filter/gradient elements return True."""
        # Check standard defs-bound classes in inkex
        defs_classes = [
            inkex.Marker,
            inkex.ClipPath,
            inkex.Symbol,
            inkex.LinearGradient,
            inkex.Pattern,
        ]
        for cls in defs_classes:
            assert should_place_in_defs(cls) is True, f"{cls.__name__} should be placed in defs"

    def test_graphic_elements_return_false(self):
        """Test that normal renderable graphic elements return False."""
        graphic_classes = [
            inkex.Circle,
            inkex.Rectangle,
            inkex.PathElement,
            inkex.Group,
            inkex.TextElement,
        ]
        for cls in graphic_classes:
            assert should_place_in_defs(cls) is False, f"{cls.__name__} should not be placed in defs"

    def test_none_and_invalid_inputs(self):
        """Test that None or non-class inputs safely return False."""
        assert should_place_in_defs(None) is False
        assert should_place_in_defs(object()) is False
        assert should_place_in_defs("not_a_class") is False


class TestGetUniqueId:
    """Tests for get_unique_id with auto-increment and reserved_ids collision avoidance."""

    def test_get_unique_id_auto_increments_existing_svg_id(self):
        """Test auto-increment when custom_id exists in the SVG document."""
        mock_svg = MagicMock()
        # First call returns an existing element, second call returns None
        mock_svg.getElementById.side_effect = lambda eid: MagicMock() if eid == "circle_1" else None

        unique_id = get_unique_id(mock_svg, "circle", custom_id="circle_1")
        assert unique_id == "circle_1_1"

    def test_get_unique_id_avoids_reserved_ids(self):
        """Test that duplicate IDs are avoided when reserved_ids set is provided."""
        mock_svg = MagicMock()
        mock_svg.getElementById.return_value = None
        mock_svg.get_unique_id.return_value = "box_1"

        reserved = {"box_1", "box_1_1"}

        sig = inspect.signature(get_unique_id)
        if "reserved_ids" in sig.parameters:
            unique_id = get_unique_id(mock_svg, "rect", custom_id="box_1", reserved_ids=reserved)
            assert unique_id not in reserved, f"Generated ID {unique_id} collided with reserved_ids"
            assert unique_id == "box_1_2"
        else:
            # Document and verify reserved_ids parameter contract
            try:
                unique_id = get_unique_id(mock_svg, "rect", custom_id="box_1", reserved_ids=reserved)
                assert unique_id not in reserved
            except TypeError:
                pytest.fail("get_unique_id must accept reserved_ids parameter to prevent batch collisions")

    def test_get_unique_id_default_tag_prefix(self):
        """Test default prefix derivation when custom_id is not supplied."""
        mock_svg = MagicMock()
        mock_svg.get_unique_id.return_value = "circle123"

        unique_id = get_unique_id(mock_svg, "circle")
        mock_svg.get_unique_id.assert_called_with(prefix="circle")
        assert unique_id == "circle123"


class TestEnsureDefsSection:
    """Tests for ensure_defs_section creation and idempotency."""

    def test_ensure_defs_creates_defs_if_none(self):
        """Test creating <defs> when svg.defs is None."""
        mock_svg = MagicMock()
        mock_svg.defs = None

        defs = ensure_defs_section(mock_svg)
        assert defs is not None
        assert isinstance(defs, inkex.Defs)
        assert mock_svg.defs == defs

    def test_ensure_defs_reuses_existing_defs(self):
        """Test reusing existing <defs> when already present."""
        mock_svg = MagicMock()
        existing_defs = inkex.Defs()
        mock_svg.defs = existing_defs

        defs = ensure_defs_section(mock_svg)
        assert defs is existing_defs
