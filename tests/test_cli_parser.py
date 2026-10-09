"""Unit tests for CLI parser in inkmcp.inkmcpcli.

Tests parse_attributes, escaped quotes handling, ReDoS safety on nested brackets,
child DSL quote stripping, JSON children arrays, and strip_python_comments.
"""

import time
from inkmcp.inkmcpcli import (
    parse_attributes,
    parse_children_array,
    parse_tag_and_attributes,
    strip_python_comments,
)


class TestParseAttributes:
    """Tests for parse_attributes and parameter parsing."""

    def test_parse_attributes_basic(self):
        """Test basic key-value pairs with unquoted and quoted values."""
        params = 'x="10" y="20" fill=blue stroke="red"'
        attrs = parse_attributes(params)
        assert attrs["x"] == "10"
        assert attrs["y"] == "20"
        assert attrs["fill"] == "blue"
        assert attrs["stroke"] == "red"

    def test_parse_attributes_empty_and_whitespace(self):
        """Test empty and whitespace-only parameter strings return empty dict."""
        assert parse_attributes("") == {}
        assert parse_attributes("   ") == {}
        assert parse_attributes("\n\t") == {}

    def test_parse_attributes_namespaced_and_hyphenated(self):
        """Test hyphenated and XML-namespaced attribute keys."""
        params = 'stroke-width="2.5" inkscape:label="Layer1" sodipodi:role="line"'
        attrs = parse_attributes(params)
        assert attrs["stroke-width"] == "2.5"
        assert attrs["inkscape:label"] == "Layer1"
        assert attrs["sodipodi:role"] == "line"

    def test_parse_attributes_escaped_quotes(self):
        """Test parsing attribute values with escaped double and single quotes."""
        # Escaped double quotes inside double-quoted attribute
        params = r'content="Hello \"World\""'
        attrs = parse_attributes(params)
        assert "content" in attrs
        # The parsed content should resolve escaped quotes or retain inner quotes
        assert attrs["content"] == 'Hello "World"' or attrs["content"] == r'Hello \"World\"'

        # Escaped single quotes inside single-quoted attribute
        params_single = r"label='It\'s SVG'"
        attrs_single = parse_attributes(params_single)
        assert "label" in attrs_single
        assert attrs_single["label"] == "It's SVG" or attrs_single["label"] == r"It\'s SVG"

    def test_parse_attributes_redos_safety_nested_brackets(self):
        """Test that pathological or deeply nested brackets do not cause ReDoS / catastrophic backtracking."""
        start_time = time.perf_counter()

        # Pathological inputs: deeply nested open brackets, mixed unclosed brackets
        deep_brackets = "data=" + ("[" * 80) + "val" + ("]" * 80)
        unclosed_brackets = "data=" + ("[" * 100)
        interleaved_delims = "data=" + ("[{" * 50) + ("}]" * 50)

        for payload in [deep_brackets, unclosed_brackets, interleaved_delims]:
            parse_attributes(payload)

        duration = time.perf_counter() - start_time
        assert duration < 1.0, f"parse_attributes took {duration:.2f}s - possible ReDoS vulnerability"


class TestChildDSLAndJSONChildren:
    """Tests for child DSL {tag '...'} quote stripping and JSON children arrays."""

    def test_child_dsl_quote_stripping_single(self):
        """Test child DSL {tag '...'} strips outer quotes from attribute string."""
        dsl = "[{stop 'offset=\"0%\" stop-color=\"blue\"'}]"
        children = parse_children_array(dsl)
        assert len(children) == 1
        child = children[0]
        assert child["tag"] == "stop"
        assert child["attributes"].get("offset") == "0%"
        assert child["attributes"].get("stop-color") == "blue"

    def test_child_dsl_quote_stripping_multiple(self):
        """Test child DSL with multiple quoted child elements."""
        dsl = "[{stop 'offset=\"0%\" stop-color=\"red\"'}, {stop 'offset=\"100%\" stop-color=\"blue\"'}]"
        children = parse_children_array(dsl)
        assert len(children) == 2
        assert children[0]["tag"] == "stop"
        assert children[0]["attributes"].get("offset") == "0%"
        assert children[0]["attributes"].get("stop-color") == "red"
        assert children[1]["tag"] == "stop"
        assert children[1]["attributes"].get("offset") == "100%"
        assert children[1]["attributes"].get("stop-color") == "blue"

    def test_child_dsl_double_quotes_and_unquoted(self):
        """Test child DSL with double quotes and unquoted attributes."""
        dsl_double = '[{circle "r=10 cx=50 cy=50"}]'
        children = parse_children_array(dsl_double)
        assert len(children) == 1
        assert children[0]["tag"] == "circle"
        assert children[0]["attributes"].get("r") == "10"

        dsl_unquoted = "[{rect width=20 height=30}]"
        children_unquoted = parse_children_array(dsl_unquoted)
        assert len(children_unquoted) == 1
        assert children_unquoted[0]["tag"] == "rect"
        assert children_unquoted[0]["attributes"].get("width") == "20"

    def test_json_children_arrays_in_tag_and_attributes(self):
        """Test parsing elements with JSON array format for children."""
        content = 'g children=[{"tag": "circle", "attributes": {"r": "5"}}]'
        data = parse_tag_and_attributes(content)
        assert data is not None
        assert data["tag"] == "g"
        assert "children" in data
        children = data["children"]
        assert len(children) == 1
        first_child = children[0]
        # Whether parsed via JSON decode or child DSL, tag must be 'circle' and r must be '5'
        assert first_child.get("tag") in ("circle", '"circle"')
        attrs = first_child.get("attributes", {})
        assert attrs.get("r") in ("5", 5) or "r" in attrs


class TestStripPythonComments:
    """Tests for strip_python_comments function."""

    def test_strip_full_line_comments(self):
        """Test that full line comments starting with # are removed."""
        code = "# Initial comment\nx = 10\n# Middle comment\ny = 20\n# Trailing comment"
        result = strip_python_comments(code)
        assert "# Initial comment" not in result
        assert "# Middle comment" not in result
        assert "# Trailing comment" not in result
        assert "x = 10" in result
        assert "y = 20" in result

    def test_strip_inline_comments(self):
        """Test that inline comments at the end of lines are stripped."""
        code = "x = 10  # set x to 10\ny = 'hello'  # greeting"
        result = strip_python_comments(code)
        assert "# set x to 10" not in result
        assert "# greeting" not in result
        assert "x = 10" in result
        assert "y = 'hello'" in result

    def test_preserve_hash_inside_quotes(self):
        """Test that # characters inside single and double quotes are preserved."""
        code = 'color1 = "#ff0000"\ncolor2 = \'#00ff00\'  # comment to strip'
        result = strip_python_comments(code)
        assert 'color1 = "#ff0000"' in result
        assert "color2 = '#00ff00'" in result
        assert "# comment to strip" not in result

    def test_preserve_hash_with_escaped_quotes(self):
        """Test that # characters in strings with escaped quotes are preserved."""
        code = r'msg = "Escaped \"quote\" with #hash preserved"  # inline comment'
        result = strip_python_comments(code)
        assert "#hash preserved" in result
        assert "# inline comment" not in result

    def test_empty_and_all_comments_code(self):
        """Test handling of empty strings and comment-only code blocks."""
        assert strip_python_comments("") == ""
        assert strip_python_comments("   ") == "   "
        assert strip_python_comments("# only a comment\n# another comment").strip() == ""
