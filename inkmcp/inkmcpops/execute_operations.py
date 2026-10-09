"""Code execution operations module

SECURITY_WARNING:
    This module executes user-supplied Python code with AST-level pattern blocking.
    The exec() sandbox is NOT a security boundary — it provides defense-in-depth
    against common escape patterns but cannot prevent all attacks. Access to this
    tool should be restricted via MCP authentication/authorization.
"""

import ast
import builtins
import io
import traceback
from contextlib import redirect_stdout, redirect_stderr
from typing import Dict, Any, List
from .common import create_success_response, create_error_response


# --- AST pre-validation guard ---

_DANGEROUS_ATTRIBUTES = frozenset({
    '__builtins__', '__import__', '__subclasses__', '__globals__',
    '__class__', '__mro__', '__bases__', '__code__', '__func__',
    'command', 'os', 'sys', 'popen', 'system', 'call', 'subprocess',
    'getroottree', 'write', 'tofile'
})

_DANGEROUS_NAMES = frozenset({
    'eval', 'exec', 'compile', '__import__', 'breakpoint',
    'open', 'os', 'sys'
})


def _validate_code_safety(code: str) -> List[str]:
    """Parse *code* with :func:`ast.parse` and walk the AST to detect
    dangerous patterns.

    Returns a list of human-readable violation strings.  An empty list
    means no violations were detected.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Let exec() surface the SyntaxError with a proper traceback.
        return []

    violations: List[str] = []

    for node in ast.walk(tree):
        # Block import statements
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ''
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import) and node.names:
                module = node.names[0].name
            violations.append(f"Import statement not allowed: '{module or 'import'}'")

        # Block dangerous attribute access (e.g. obj.__builtins__)
        elif isinstance(node, ast.Attribute):
            if node.attr in _DANGEROUS_ATTRIBUTES:
                violations.append(
                    f"Access to dangerous attribute '{node.attr}' is not allowed"
                )

        # Block dangerous name references
        elif isinstance(node, ast.Name):
            if node.id in _DANGEROUS_NAMES:
                violations.append(
                    f"Reference to dangerous name '{node.id}' is not allowed"
                )

    return violations


def execute_code(extension_instance, svg, attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Execute arbitrary Python/inkex code in extension context"""
    try:
        code = attributes.get('code', '')
        if not code.strip():
            return create_error_response("No code provided")

        # AST pre-validation: block dangerous patterns before exec()
        violations = _validate_code_safety(code)
        if violations:
            return create_error_response(
                "Code blocked by security validation",
                violations=violations
            )

        return_output = attributes.get('return_output', True)

        # Restrict builtins to safe primitives whitelist
        safe_builtins = {
            name: getattr(builtins, name)
            for name in (
                "abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
                "len", "list", "max", "min", "range", "round", "set", "str",
                "sum", "tuple", "zip", "print",
                "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
                "AttributeError", "ArithmeticError", "ZeroDivisionError", "LookupError",
                "RuntimeError", "isinstance", "issubclass", "repr", "sorted",
                "reversed", "hasattr"
            )
            if hasattr(builtins, name)
        }

        # Set up execution context following inkex patterns
        # NOTE: 'self' (extension instance) is intentionally excluded —
        # it exposes .save(), .document file-write access.
        execution_globals = {
            '__builtins__': safe_builtins,
            'svg': svg,
            'document': svg,  # Alias for convenience
        }

        # Add inkex module and common classes
        try:
            import inkex
            from inkex import Rectangle, Circle, Ellipse, Line, PathElement, Polygon, Polyline, TextElement
            from inkex import Group, Layer, Use, Image, Marker, Gradient, Defs
            from inkex import Transform, Style, Color, Vector2d
            from inkex.paths import Path, Move, Line as PathLine, Curve, Arc
            from inkex.elements._base import ShapeElement

            execution_globals.update({
                'inkex': inkex,
                # Shape elements (most common)
                'Rectangle': Rectangle,
                'Circle': Circle,
                'Ellipse': Ellipse,
                'Line': Line,
                'PathElement': PathElement,
                'Polygon': Polygon,
                'Polyline': Polyline,
                'TextElement': TextElement,
                # Structural elements
                'Group': Group,
                'Layer': Layer,
                'Use': Use,
                'Image': Image,
                'Marker': Marker,
                'Gradient': Gradient,
                'Defs': Defs,
                # Utility classes
                'Transform': Transform,
                'Style': Style,
                'Color': Color,
                'Vector2d': Vector2d,
                # Path elements
                'Path': Path,
                'Move': Move,
                'PathLine': PathLine,
                'Curve': Curve,
                'Arc': Arc,
                # Base classes
                'ShapeElement': ShapeElement,
            })
        except ImportError as e:
            execution_globals['import_error'] = str(e)

        # Add common Python libraries
        try:
            import math
            import random
            import json
            import re
            execution_globals.update({
                'math': math,
                'random': random,
                'json': json,
                're': re,
            })
        except ImportError:
            pass

        # Add helper functions
        def get_element_by_id(element_id):
            """Helper function to find element by ID using iteration (getElementById doesn't work reliably)"""
            for elem in svg.iter():
                if elem.get('id') == element_id:
                    return elem
            return None
        
        execution_globals['get_element_by_id'] = get_element_by_id

        # Capture output if requested
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        result_data = {
            "code_executed": code,
            "output": "",
            "errors": "",
            "return_value": None,
            "execution_successful": False,
            "elements_created": []
        }

        # Count elements before execution
        elements_before = len(list(svg.iter()))
        
        execution_locals: Dict[str, Any] = {}
        timeout_seconds = float(attributes.get('timeout', 15.0))

        try:
            exec_exception = []
            def _run_exec():
                try:
                    if return_output:
                        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                            exec(code, execution_globals, execution_locals)
                    else:
                        exec(code, execution_globals, execution_locals)
                except Exception as e:
                    exec_exception.append((e, traceback.format_exc()))
            
            import threading
            thread = threading.Thread(target=_run_exec, daemon=True)
            thread.start()
            thread.join(timeout=timeout_seconds)

            if thread.is_alive():
                result_data["errors"] = f"Execution error: Timeout after {timeout_seconds} seconds"
                result_data["execution_successful"] = False
            elif exec_exception:
                e, tb = exec_exception[0]
                result_data["errors"] = f"Execution error: {str(e)}\n\nTraceback:\n{tb}"
                result_data["execution_successful"] = False
            else:
                result_data["execution_successful"] = True

                # Capture any return value
                if 'result' in execution_locals:
                    result_data["return_value"] = str(execution_locals['result'])

        except Exception as e:
            error_traceback = traceback.format_exc()
            result_data["errors"] = f"Execution error: {str(e)}\n\nTraceback:\n{error_traceback}"
            result_data["execution_successful"] = False

        # Get captured output
        if return_output:
            MAX_OUTPUT_BYTES = 64 * 1024
            
            stdout_content = stdout_capture.getvalue()
            if len(stdout_content) > MAX_OUTPUT_BYTES:
                stdout_content = stdout_content[:MAX_OUTPUT_BYTES] + "... [output truncated]"
            
            stderr_content = stderr_capture.getvalue()
            if len(stderr_content) > MAX_OUTPUT_BYTES:
                stderr_content = stderr_content[:MAX_OUTPUT_BYTES] + "... [output truncated]"

            if stdout_content:
                result_data["output"] = stdout_content
            if stderr_content and not result_data["errors"]:
                result_data["errors"] = stderr_content

        # Count elements after execution and detect new ones
        try:
            elements_after = len(list(svg.iter()))
            if elements_after > elements_before:
                result_data["elements_created"] = [f"{elements_after - elements_before} new elements added"]

            # Get element counts by type
            element_counts = {}
            for element in svg.iter():
                tag = element.tag.split('}')[-1] if isinstance(element.tag, str) and '}' in element.tag else str(element.tag)
                element_counts[tag] = element_counts.get(tag, 0) + 1

            result_data["current_element_counts"] = element_counts
            
            # Capture local variables for hybrid execution
            # Serialize variables that were created/modified during execution
            captured_vars = {}
            for key, value in execution_locals.items():
                # Skip private/magic variables
                if key.startswith('_'):
                    continue
                # Skip modules and non-serializable types
                if type(value).__name__ in ('module', 'function', 'type', 'builtin_function_or_method'):
                    continue
                # Try to serialize
                try:
                    json.dumps(value)  # Test if serializable
                    captured_vars[key] = value
                except (TypeError, ValueError):
                    # Skip non-serializable values
                    pass
            
            if captured_vars:
                result_data["local_variables"] = captured_vars
            
        except Exception as e:
            result_data["element_count_error"] = str(e)

        # Determine message based on execution success
        message = "Code executed successfully" if result_data["execution_successful"] else "Code execution failed"

        if not result_data["execution_successful"]:
            return create_error_response(message, **result_data)

        return create_success_response(message, **result_data)

    except Exception as e:
        return create_error_response(
            f"Failed to execute code: {str(e)}",
            traceback=traceback.format_exc()
        )