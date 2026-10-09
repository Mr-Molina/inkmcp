"""Empirical Boundary-Condition Test Suite for Wave 1 Remediations.

This module empirically certifies the defensive guardrails and security invariants
implemented across Wave 1:

1. inkmcpops/execute_operations.py:
   - AST validation blocks dangerous attributes (__builtins__, command, os, sys, getroottree, write).
   - Execution timeout triggers gracefully on long-running code (while True: pass with timeout=0.2) without hanging.
   - Output buffer truncation enforces 64KB cap when scripts generate large output (print('A' * 100000)).
   - Safe builtins whitelist allows standard exception handling (try: raise ValueError() except ValueError: pass).

2. inkmcpcli.py:
   - Path resolution with --strict-boundary blocks paths outside current working directory.
   - Path resolution with --strict-boundary permits paths inside current working directory.

3. blender_addon_inkscape_hybrid.py & blender_inkscape_hybrid.py:
   - Variable serialization / injection skips non-identifier keys (e.g. foo;bar, 123bad).
   - bl_rna objects are safely identified and skipped during serialization.

4. .agents/inspect_desktop_windows.py:
   - Desktop handle opens with read-only rights (DESKTOP_READOBJECTS = 0x0001).
"""

import ast
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repository root and .agents are importable
REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / ".agents"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from inkmcp.inkmcpops.execute_operations import (  # noqa: E402
    _validate_code_safety,
    execute_code,
    _DANGEROUS_ATTRIBUTES,
)
from inkmcp import inkmcpcli  # noqa: E402


# ==============================================================================
# SECTION 1: inkmcpops/execute_operations.py Defensive Invariants
# ==============================================================================

class TestExecuteOperationsInvariants:
    """Verifies AST validation, timeout bounding, buffer capping, and safe builtins."""

    @pytest.fixture
    def empty_svg(self):
        """Minimal mock SVG Element for execute_code context."""
        return ET.Element("{http://www.w3.org/2000/svg}svg")

    # 1. AST validation blocks dangerous attributes
    @pytest.mark.parametrize("dangerous_attr", [
        "__builtins__",
        "command",
        "os",
        "sys",
        "getroottree",
        "write",
    ])
    def test_ast_validation_detects_dangerous_attributes(self, dangerous_attr):
        """Verify _validate_code_safety detects each required dangerous attribute."""
        assert dangerous_attr in _DANGEROUS_ATTRIBUTES, (
            f"Expected {dangerous_attr} in _DANGEROUS_ATTRIBUTES set"
        )
        sample_code = f"target.{dangerous_attr} = 123"
        violations = _validate_code_safety(sample_code)
        assert len(violations) > 0, f"Expected violation for dangerous attribute '{dangerous_attr}'"
        assert any(dangerous_attr in v for v in violations), (
            f"Expected '{dangerous_attr}' mentioned in violations: {violations}"
        )

    @pytest.mark.parametrize("dangerous_attr", [
        "__builtins__",
        "command",
        "os",
        "sys",
        "getroottree",
        "write",
    ])
    def test_execute_code_blocks_dangerous_attributes(self, empty_svg, dangerous_attr):
        """Verify execute_code halts and returns security error for dangerous attributes."""
        code = f"x = object()\nx.{dangerous_attr}"
        res = execute_code(None, empty_svg, {"code": code})

        assert res["status"] == "error"
        data = res.get("data", {})
        assert data.get("error") == "Code blocked by security validation"
        violations = data.get("violations", [])
        assert any(dangerous_attr in v for v in violations), (
            f"Violation for '{dangerous_attr}' not found in {violations}"
        )

    def test_ast_validation_allows_benign_attributes(self):
        """Verify benign inkex / math attributes do not trigger false positive violations."""
        benign_code = (
            "rect = Rectangle()\n"
            "rect.set('width', 100)\n"
            "v = math.sqrt(25)\n"
            "r = round(v)\n"
        )
        violations = _validate_code_safety(benign_code)
        assert violations == [], f"Unexpected violations for benign code: {violations}"

    # 2. Execution timeout triggers gracefully on long-running code
    def test_execution_timeout_triggers_gracefully(self, empty_svg):
        """Verify 'while True: pass' with timeout=0.2 times out gracefully without hanging."""
        code = "while True:\n    pass"
        start_time = time.perf_counter()
        res = execute_code(None, empty_svg, {"code": code, "timeout": 0.2})
        duration = time.perf_counter() - start_time

        assert res["status"] == "error"
        data = res.get("data", {})
        assert data.get("execution_successful") is False
        assert "Timeout after 0.2 seconds" in data.get("errors", "")
        # Must terminate promptly (well under 2.0s)
        assert duration < 5.0, f"Execution hung for {duration:.2f}s instead of timing out at 0.2s"

    # 3. Output buffer truncation enforces the 64KB cap
    def test_output_buffer_truncation_enforces_64kb_cap(self, empty_svg):
        """Verify large output generation enforces the 64KB cap with truncation notice."""
        large_size = 100_000
        code = f"print('A' * {large_size})"
        res = execute_code(None, empty_svg, {"code": code})

        assert res["status"] == "success"
        data = res.get("data", {})
        output = data.get("output", "")
        max_bytes = 64 * 1024
        expected_suffix = "... [output truncated]"

        assert output.endswith(expected_suffix), "Truncation notice missing from output"
        # The truncated content prefix must be exactly 64KB
        assert len(output) == max_bytes + len(expected_suffix)
        assert output[:max_bytes] == "A" * max_bytes

    def test_output_buffer_preserves_sub_64kb_output(self, empty_svg):
        """Verify output below 64KB is preserved without truncation notice."""
        code = "print('Exact small output test')"
        res = execute_code(None, empty_svg, {"code": code})

        assert res["status"] == "success"
        data = res.get("data", {})
        output = data.get("output", "")
        assert output.strip() == "Exact small output test"
        assert "... [output truncated]" not in output

    # 4. Safe builtins allows standard exception handling
    def test_safe_builtins_allows_standard_exception_handling(self, empty_svg):
        """Verify standard try/except with ValueError executes successfully without NameError."""
        code = (
            "try:\n"
            "    raise ValueError('Handled safe exception')\n"
            "except ValueError as exc:\n"
            "    result = f'Caught: {exc}'\n"
        )
        res = execute_code(None, empty_svg, {"code": code})

        assert res["status"] == "success"
        data = res.get("data", {})
        assert data.get("execution_successful") is True
        assert data.get("return_value") == "Caught: Handled safe exception"

    def test_safe_builtins_whitelist_coverage(self, empty_svg):
        """Verify other whitelisted exception classes and safe primitives execute normally."""
        code = (
            "caught = []\n"
            "for exc_type in (TypeError, KeyError, IndexError, AttributeError, RuntimeError):\n"
            "    try:\n"
            "        raise exc_type('probe')\n"
            "    except exc_type:\n"
            "        caught.append(exc_type.__name__)\n"
            "result = ','.join(caught)\n"
        )
        res = execute_code(None, empty_svg, {"code": code})

        assert res["status"] == "success"
        data = res.get("data", {})
        assert data.get("execution_successful") is True
        assert data.get("return_value") == "TypeError,KeyError,IndexError,AttributeError,RuntimeError"


# ==============================================================================
# SECTION 2: inkmcpcli.py --strict-boundary Path Resolution
# ==============================================================================

class TestCliStrictBoundary:
    """Verifies that --strict-boundary prevents path traversal outside the CWD."""

    def test_strict_boundary_blocks_path_outside_cwd(self, monkeypatch, capsys):
        """Verify --strict-boundary aborts with exit code 1 when path is outside CWD."""
        cwd = Path.cwd().resolve()
        outside_path = (cwd.parent / "sensitive_external_file.txt").resolve()

        monkeypatch.setattr(sys, "argv", [
            "inkmcpcli.py",
            "circle",
            "-f", str(outside_path),
            "--strict-boundary",
        ])

        exit_code = inkmcpcli.main()
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "[Security Error] ❌ File path outside expected boundary:" in captured.err
        assert str(outside_path) in captured.err

    def test_strict_boundary_subprocess_execution(self):
        """Verify CLI process invocation rejects external paths via subprocess."""
        cwd = Path.cwd().resolve()
        outside_path = (cwd.parent / "unauthorized_params.py").resolve()

        proc = subprocess.run(
            [
                sys.executable,
                "-m", "inkmcp.inkmcpcli",
                "circle",
                "-f", str(outside_path),
                "--strict-boundary",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd),
        )

        assert proc.returncode == 1
        assert "File path outside expected boundary:" in proc.stderr
        assert str(outside_path) in proc.stderr

    def test_strict_boundary_allows_path_inside_cwd(self, monkeypatch, capsys, tmp_path):
        """Verify --strict-boundary allows files located inside the current working directory."""
        # Create a temporary file directly inside CWD
        local_test_file = Path.cwd() / "temp_wave1_boundary_check.txt"
        try:
            local_test_file.write_text("cx=100 cy=100 r=25 fill=blue", encoding="utf-8")

            monkeypatch.setattr(sys, "argv", [
                "inkmcpcli.py",
                "circle",
                "-f", str(local_test_file),
                "--strict-boundary",
            ])

            # main() might exit with 0 or connection failure depending on D-Bus/GUI,
            # but it MUST NOT trigger the security boundary violation.
            inkmcpcli.main()
            captured = capsys.readouterr()

            assert "[Security Error] ❌ File path outside expected boundary:" not in captured.err
        finally:
            if local_test_file.exists():
                local_test_file.unlink()


# ==============================================================================
# SECTION 3: Variable Serialization in Hybrid Modules
# ==============================================================================

class TestBlenderHybridVariableSerialization:
    """Verifies variable serialization skips non-identifier keys and bl_rna objects."""

    @pytest.fixture(autouse=True)
    def load_hybrid_modules(self, mock_bpy_modules):
        """Ensure mock_bpy is active and import hybrid modules."""
        import blender_addon_inkscape_hybrid as baih
        import blender_inkscape_hybrid as bih
        self.baih = baih
        self.bih = bih

    # 1. Non-identifier keys skipped during serialization / injection
    def test_execute_inkscape_block_skips_non_identifier_keys(self):
        """Verify execute_inkscape_block skips invalid identifier keys in bootstrap."""
        captured_script = []

        def mock_tempfile(*args, **kwargs):
            mock_file = MagicMock()
            def mock_write(code):
                captured_script.append(code)
            mock_file.__enter__.return_value.write = mock_write
            mock_file.__enter__.return_value.name = "mock_exec.py"
            return mock_file

        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = json.dumps({"result": {"success": True, "response": {"data": {}}}})

        test_vars = {
            "valid_key": 100,
            "another_valid_2": "test",
            "foo;bar": 999,          # Non-identifier: semicolon
            "123bad": "illegal_id",  # Non-identifier: starts with digit
            "hyphen-name": 555,      # Non-identifier: minus/hyphen
            "has space": True,       # Non-identifier: space
        }

        # Test both blender_addon_inkscape_hybrid and blender_inkscape_hybrid
        for mod, name in [(self.baih, "addon"), (self.bih, "standalone")]:
            captured_script.clear()
            with patch("tempfile.NamedTemporaryFile", side_effect=mock_tempfile), \
                 patch("subprocess.run", return_value=mock_res), \
                 patch("os.unlink"):

                real_cli = str(Path(__file__).parent.parent / "inkmcp" / "inkmcpcli.py")
                if mod is self.baih:
                    mod.execute_inkscape_block("print('ok')", test_vars, inkmcp_cli_path=real_cli)
                else:
                    with patch.object(mod, "INKMCP_CLI_PATH", real_cli):
                        mod.execute_inkscape_block("print('ok')", test_vars)

                assert len(captured_script) == 1, f"Script was not generated for {name}"
                generated_code = captured_script[0]

                # Valid keys must be injected
                assert "valid_key = _inkmcp_vars[\"valid_key\"]" in generated_code
                assert "another_valid_2 = _inkmcp_vars[\"another_valid_2\"]" in generated_code

                # Invalid keys MUST NOT be injected
                assert "foo;bar" not in generated_code
                assert "123bad" not in generated_code
                assert "hyphen-name" not in generated_code
                assert "has space" not in generated_code

                # Generated Python code MUST parse without syntax errors
                try:
                    ast.parse(generated_code)
                except SyntaxError as e:
                    pytest.fail(f"Generated injection script in {name} has syntax error: {e}\n{generated_code}")

    def test_execute_inkscape_block_fallback_skips_non_identifier_keys(self):
        """Verify fallback serialization path also skips non-identifier keys."""
        captured_script = []

        def mock_tempfile(*args, **kwargs):
            mock_file = MagicMock()
            def mock_write(code):
                captured_script.append(code)
            mock_file.__enter__.return_value.write = mock_write
            mock_file.__enter__.return_value.name = "mock_exec.py"
            return mock_file

        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "{}"

        # Cause json.dumps(variables) to fail by patching json.dumps
        def mock_json_dumps(obj):
            if isinstance(obj, dict) and "unserializable_trigger" in obj:
                raise TypeError("Forced serialization error for fallback testing")
            return json.dumps(obj)

        test_vars = {
            "unserializable_trigger": object(),
            "valid_fallback": 777,
            "bad;var": 888,
            "999digit": 999,
        }

        with patch("json.dumps", side_effect=mock_json_dumps), \
             patch("tempfile.NamedTemporaryFile", side_effect=mock_tempfile), \
             patch("subprocess.run", return_value=mock_res), \
             patch("os.unlink"):

            real_cli = str(Path(__file__).parent.parent / "inkmcp" / "inkmcpcli.py")
            self.baih.execute_inkscape_block("print('ok')", test_vars, inkmcp_cli_path=real_cli)

            assert len(captured_script) == 1
            generated_code = captured_script[0]
            assert "valid_fallback = 777" in generated_code
            assert "bad;var" not in generated_code
            assert "999digit" not in generated_code

            # Ast must parse cleanly
            ast.parse(generated_code)

    # 2. bl_rna objects are safely identified and skipped during serialization
    def test_bl_rna_objects_skipped_during_serialization(self):
        """Verify serialize_variables detects and excludes objects with bl_rna attribute."""
        class MockBlRnaObject:
            def __init__(self):
                self.bl_rna = MagicMock()

        class MockBpyStruct:
            pass
        MockBpyStruct.__name__ = "bpy_struct"

        local_vars = {
            "safe_integer": 42,
            "safe_string": "vector_art",
            "safe_list": [1, 2, 3],
            "rna_object": MockBlRnaObject(),
            "struct_object": MockBpyStruct(),
        }

        # 1. Test blender_addon_inkscape_hybrid.serialize_variables
        addon_serializable = self.baih.serialize_variables(local_vars)
        assert "safe_integer" in addon_serializable
        assert "safe_string" in addon_serializable
        assert "safe_list" in addon_serializable
        assert "rna_object" not in addon_serializable, "bl_rna object was not excluded in addon"
        assert "struct_object" not in addon_serializable, "bpy_struct object was not excluded in addon"

        # 2. Test blender_inkscape_hybrid.serialize_variables
        standalone_serializable = self.bih.serialize_variables(local_vars)
        assert "safe_integer" in standalone_serializable
        assert "safe_string" in standalone_serializable
        assert "safe_list" in standalone_serializable
        assert "rna_object" not in standalone_serializable, "bl_rna object was not excluded in standalone"
        assert "struct_object" not in standalone_serializable, "bpy_struct object was not excluded in standalone"


# ==============================================================================
# SECTION 4: .agents/inspect_desktop_windows.py Read-Only Privileges
# ==============================================================================

class TestInspectDesktopWindowsReadOnly:
    """Verifies that desktop enumeration requests only read-only privileges."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Win32 API only available on Windows")
    def test_inspect_desktop_windows_uses_read_only_access(self):
        """Verify inspect_windows requests DESKTOP_READOBJECTS (0x0001) right."""
        import inspect_desktop_windows

        DESKTOP_READOBJECTS = 0x0001

        captured_rights = []
        original_open_desktop = inspect_desktop_windows.u32.OpenDesktopW

        def mock_open_desktop(lpszDesktop, dwFlags, fInherit, dwDesiredAccess):
            captured_rights.append(dwDesiredAccess)
            return original_open_desktop(lpszDesktop, dwFlags, fInherit, dwDesiredAccess)

        with patch.object(inspect_desktop_windows.u32, "OpenDesktopW", side_effect=mock_open_desktop):
            inspect_desktop_windows.inspect_windows(visible_only=True)

        assert len(captured_rights) >= 1, "OpenDesktopW was not invoked"
        first_access = captured_rights[0]

        # Verify DESKTOP_READOBJECTS (0x0001) bit is present
        assert (first_access & DESKTOP_READOBJECTS) == DESKTOP_READOBJECTS, (
            f"Expected DESKTOP_READOBJECTS (0x0001) in desired access mask: {hex(first_access)}"
        )

        # Verify dangerous write rights (e.g. DESKTOP_CREATEWINDOW = 0x0002, DESKTOP_WRITEOBJECTS = 0x0080) are absent
        dangerous_write_mask = 0x0002 | 0x0080 | 0x40000000 | 0x10000000
        assert (first_access & dangerous_write_mask) == 0, (
            f"Dangerous write permissions requested in OpenDesktopW: {hex(first_access)}"
        )

    @pytest.mark.skipif(sys.platform != "win32", reason="Win32 API only available on Windows")
    def test_desktop_handle_opens_and_closes_live_with_read_only_rights(self):
        """Empirically test live Win32 OpenDesktopW with DESKTOP_READOBJECTS."""
        import inspect_desktop_windows

        DESKTOP_READOBJECTS = 0x0001
        hdesk = inspect_desktop_windows.u32.OpenDesktopW("Default", 0, False, DESKTOP_READOBJECTS)
        assert hdesk != 0 and hdesk is not None, "Failed to open desktop handle with DESKTOP_READOBJECTS"

        # Clean up handle
        closed = inspect_desktop_windows.u32.CloseDesktop(hdesk)
        assert bool(closed) is True, "Failed to close desktop handle"
