"""Unit tests for hybrid execution parser and variable serialization in inkmcp.inkmcpcli.

Tests parse_hybrid_blocks with whitespace variations (#  @local, # @inkscape, tabs),
and serialize_context_variables skipping local callables (functions, lambdas, classes, methods).
"""

import math
from inkmcp.inkmcpcli import (
    parse_hybrid_blocks,
    serialize_context_variables,
)


class TestParseHybridBlocks:
    """Tests for parse_hybrid_blocks splitting code by magic comments."""

    def test_parse_hybrid_blocks_standard(self):
        """Test standard # @local and # @inkscape block splitting."""
        code = (
            "import math\n"
            "r = 10\n"
            "# @inkscape\n"
            "circle = Circle()\n"
            "circle.set('r', str(r))\n"
            "# @local\n"
            "print('Done')"
        )
        blocks = parse_hybrid_blocks(code)
        assert len(blocks) == 3
        assert blocks[0][0] == "local"
        assert "import math" in blocks[0][1]
        assert blocks[1][0] == "inkscape"
        assert "circle = Circle()" in blocks[1][1]
        assert blocks[2][0] == "local"
        assert "print('Done')" in blocks[2][1]

    def test_parse_hybrid_blocks_whitespace_variations(self):
        """Test supporting variations with multiple spaces, tabs, and trailing whitespace."""
        code = (
            "x = 10\n"
            "#  @inkscape\n"
            "y = 20\n"
            "#   @local  \n"
            "z = 30\n"
            "#\t@inkscape\n"
            "w = 40"
        )
        blocks = parse_hybrid_blocks(code)
        # Should parse into 4 alternating blocks: local, inkscape, local, inkscape
        assert len(blocks) == 4, f"Expected 4 blocks but got {len(blocks)}: {blocks}"
        assert blocks[0][0] == "local"
        assert "x = 10" in blocks[0][1]
        assert blocks[1][0] == "inkscape"
        assert "y = 20" in blocks[1][1]
        assert blocks[2][0] == "local"
        assert "z = 30" in blocks[2][1]
        assert blocks[3][0] == "inkscape"
        assert "w = 40" in blocks[3][1]

    def test_parse_hybrid_blocks_starts_with_inkscape(self):
        """Test code starting directly with # @inkscape directive."""
        code = "# @inkscape\ncircle = Circle()\nsvg.append(circle)"
        blocks = parse_hybrid_blocks(code)
        assert len(blocks) == 1
        assert blocks[0][0] == "inkscape"
        assert "circle = Circle()" in blocks[0][1]

    def test_parse_hybrid_blocks_pure_local(self):
        """Test code without any magic comments defaults to single local block."""
        code = "a = 1\nb = 2\nprint(a + b)"
        blocks = parse_hybrid_blocks(code)
        assert len(blocks) == 1
        assert blocks[0][0] == "local"
        assert "a = 1" in blocks[0][1]


class TestSerializeContextVariables:
    """Tests for serialize_context_variables handling primitives and skipping callables."""

    def test_serialize_primitives(self):
        """Test serializing standard JSON-compatible data types."""
        locals_dict = {
            "num_int": 42,
            "num_float": 3.14159,
            "text": "Inkscape SVG",
            "flag": True,
            "items": [1, 2, "three"],
            "mapping": {"key": "value", "count": 10},
        }
        serialized = serialize_context_variables(locals_dict)
        assert serialized == locals_dict

    def test_serialize_skips_local_callables(self):
        """Test that functions, lambdas, classes, methods, and builtins are skipped rather than causing TypeError."""
        def sample_func(x):
            return x * 2

        sample_lambda = lambda y: y + 1  # noqa: E731

        class SampleClass:
            def sample_method(self):
                return True

        instance = SampleClass()

        locals_dict = {
            "valid_data": [10, 20, 30],
            "sample_func": sample_func,
            "sample_lambda": sample_lambda,
            "SampleClass": SampleClass,
            "sample_method": instance.sample_method,
            "builtin_callable": len,
        }

        # Callables must be skipped cleanly, leaving only valid serializable data
        serialized = serialize_context_variables(locals_dict)
        assert "valid_data" in serialized
        assert serialized["valid_data"] == [10, 20, 30]
        assert "sample_func" not in serialized
        assert "sample_lambda" not in serialized
        assert "SampleClass" not in serialized
        assert "sample_method" not in serialized
        assert "builtin_callable" not in serialized

    def test_serialize_skips_modules_and_private_keys(self):
        """Test that imported modules and private/builtin names are omitted."""
        locals_dict = {
            "radius": 15,
            "math": math,
            "__builtins__": {},
            "__doc__": "module doc",
            "_private_var": "hidden",
        }
        serialized = serialize_context_variables(locals_dict)
        assert serialized == {"radius": 15}
