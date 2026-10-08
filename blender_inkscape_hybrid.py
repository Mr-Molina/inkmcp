# Blender-Inkscape Hybrid Execution
# Run this script in Blender's text editor to enable hybrid Blender/Inkscape execution.
#
# Usage:
# 1. Open Blender Text Editor
# 2. Load or paste your hybrid script
# 3. Add magic comments:
#    # @local - Execute in Blender (has bpy, bpy.context, etc.)
#    # @inkscape - Execute in Inkscape via inkmcpcli
# 4. Run this script to execute the hybrid code
#
# Example:
#     # @local
#     import bpy
#     obj = bpy.context.active_object
#     vertices = [(v.co.x, v.co.y, 0) for v in obj.data.vertices[:5]]
#     
#     # @inkscape
#     for i, (x, y, z) in enumerate(vertices):
#         circle = Circle()
#         circle.set("cx", str(x * 100))
#         circle.set("cy", str(y * 100))
#         circle.set("r", "5")
#         circle.set("fill", "red")
#         svg.append(circle)


import bpy
import subprocess
import json
import sys
import os
import re
import tempfile
from typing import List, Tuple, Dict, Any
import io
from contextlib import redirect_stdout, redirect_stderr

# Path to inkmcpcli.py
# Set via environment variable: export INKMCP_CLI_PATH=/path/to/inkmcpcli.py
# Or it will auto-detect from common locations
INKMCP_CLI_PATH = os.environ.get('INKMCP_CLI_PATH')
if INKMCP_CLI_PATH:
    import logging
    from pathlib import Path
    _resolved = Path(INKMCP_CLI_PATH).resolve()
    if _resolved.is_file() and _resolved.name == 'inkmcpcli.py':
        INKMCP_CLI_PATH = str(_resolved)
    else:
        logging.getLogger(__name__).warning("INKMCP_CLI_PATH set but not found: %s", INKMCP_CLI_PATH)
        INKMCP_CLI_PATH = None

if not INKMCP_CLI_PATH:
    # Try to auto-detect
    script_dir = os.path.dirname(os.path.abspath(__file__))
    possible_paths = [
        os.path.join(script_dir, 'inkmcp', 'inkmcpcli.py'),  # Same repo
        os.path.join(script_dir, '..', 'inkmcp', 'inkmcpcli.py'),  # Parent dir
        os.path.expanduser('~/inkmcp/inkmcp/inkmcpcli.py'),  # Home dir
    ]
    for path in possible_paths:
        if os.path.exists(path):
            INKMCP_CLI_PATH = path
            break

if not INKMCP_CLI_PATH or not os.path.exists(INKMCP_CLI_PATH):
    print("ERROR: Cannot find inkmcpcli.py")
    print("Please set INKMCP_CLI_PATH environment variable:")
    print("  export INKMCP_CLI_PATH=/path/to/inkmcp/inkmcpcli.py")
    INKMCP_CLI_PATH = None  # Will cause clear error on first use


def parse_hybrid_blocks(code: str) -> List[Tuple[str, str]]:
    """Parse code into blocks based on magic comments."""
    lines = code.split('\n')
    blocks = []
    current_type = 'local'  # Default to local (Blender)
    current_lines = []
    
    for line in lines:
        match = re.match(r'^\s*#\s*@(local|inkscape)\b', line, re.IGNORECASE)
        if match:
            block_type = match.group(1).lower()
            if current_lines:
                blocks.append((current_type, '\n'.join(current_lines)))
                current_lines = []
            current_type = block_type
        else:
            current_lines.append(line)
    
    if current_lines:
        blocks.append((current_type, '\n'.join(current_lines)))
    
    return blocks


def serialize_variables(local_vars: Dict[str, Any], exclude_names: set = None) -> Dict[str, Any]:
    """Extract JSON-serializable variables."""
    if exclude_names is None:
        exclude_names = {'__builtins__', '__name__', '__doc__', 'bpy', 'C', 'D'}
    
    serializable = {}
    
    for key, value in local_vars.items():
        if key.startswith('_') or key in exclude_names:
            continue
        
        # Skip modules and non-serializable types
        if type(value).__name__ in ('module', 'function', 'type', 'builtin_function_or_method', 'bpy_struct') or hasattr(value, 'bl_rna'):
            continue
        
        try:
            json.dumps(value)
            serializable[key] = value
        except (TypeError, ValueError):
            pass
    
    return serializable


def execute_inkscape_block(code: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    """Execute code block in Inkscape via inkmcpcli."""
    if not INKMCP_CLI_PATH:
        return {
            'success': False,
            'error': "Cannot find inkmcpcli.py. Please set INKMCP_CLI_PATH.",
            'variables': {}
        }

    # Inject variables
    if variables:
        variables = {k: v for k, v in variables.items() if k.isidentifier()}
        try:
            serialized_json = json.dumps(variables)
            var_injections = [
                "import json",
                f"_inkmcp_vars = json.loads({json.dumps(serialized_json)})",
            ]
            for key in variables:
                if not key.isidentifier(): continue
                var_injections.append(f"{key} = _inkmcp_vars[{json.dumps(key)}]")
            var_injections.append("del _inkmcp_vars")
            full_code = '\n'.join(var_injections) + '\n' + code
        except Exception:
            var_injections = []
            for key, value in variables.items():
                if not key.isidentifier(): continue
                repr_value = repr(value)
                if repr_value.startswith('<'): continue
                var_injections.append(f"{key} = {repr_value}")
            full_code = '\n'.join(var_injections) + '\n' + code if var_injections else code
    else:
        full_code = code
    
    # Write to temp file to avoid command-line argument injection and truncation (LOGIC-021 / SEC-006)
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(full_code)
            temp_file = f.name

        try:
            result = subprocess.run(
                [sys.executable, INKMCP_CLI_PATH, 'execute-code', '--pretty', '-f', temp_file],
                capture_output=True,
                text=True,
                timeout=30
            )
        finally:
            if temp_file:
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass
        
        if result.returncode != 0:
            return {
                'success': False,
                'error': result.stderr or result.stdout,
                'variables': {}
            }
        
        # Parse JSON response
        try:
            response = json.loads(result.stdout)
            result_data = response.get('result', response)
            # Check if execute-code itself failed
            if not result_data.get('success', False):
                error = result_data.get('error') or result_data.get('response', {}).get('data', {}).get('errors', 'Unknown error')
                return {
                    'success': False,
                    'error': error,
                    'variables': {}
                }

            inner_data = result_data.get('response', {}).get('data', {})
            if not inner_data.get('execution_successful', True):
                error = inner_data.get('errors') or inner_data.get('error') or 'Code execution failed'
                return {'success': False, 'error': error, 'variables': {}}

            # LOGIC-020: Return local_variables from Inkscape execution
            return {
                'success': True,
                'output': inner_data.get('output', ''),
                'error': None,
                'variables': inner_data.get('local_variables', {})
            }
        except json.JSONDecodeError:
            return {
                'success': False,
                'error': f"Failed to parse Inkscape response: {result.stdout}",
                'variables': {}
            }
            
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': "Inkscape execution timed out",
            'variables': {}
        }
    except Exception as e:
        return {
            'success': False,
            'error': f"Failed to call Inkscape: {str(e)}",
            'variables': {}
        }


def execute_hybrid(code: str):
    """Execute hybrid Blender/Inkscape code."""
    blocks = parse_hybrid_blocks(code)
    
    if not blocks:
        print("No code blocks found")
        return
    
    shared_context = {}
    
    for block_idx, (block_type, block_code) in enumerate(blocks, 1):
        if not block_code.strip():
            continue
        
        if block_type == 'local':
            # Execute in Blender context
            try:
                global_env = {
                    '__builtins__': __builtins__,
                    'bpy': bpy,
                    'C': bpy.context,
                    'D': bpy.data,
                }
                local_env = dict(shared_context)
                
                # Validate AST to block unsafe dunder introspection
                import ast
                tree = ast.parse(block_code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute) and node.attr in ('__subclasses__', '__globals__'):
                        raise ValueError(f"Unsafe dunder introspection: {node.attr}")
                    if isinstance(node, ast.Name) and node.id in ('__subclasses__', '__globals__'):
                        raise ValueError(f"Unsafe dunder introspection: {node.id}")
                
                # Capture output
                stdout_capture = io.StringIO()
                
                with redirect_stdout(stdout_capture), redirect_stderr(stdout_capture):
                    exec(block_code, global_env, local_env)
                
                output = stdout_capture.getvalue()
                if output:
                    print(f"[Blender Block {block_idx}]")
                    print(output.rstrip())
                
                # Update shared context
                serializable = serialize_variables(local_env)
                shared_context.update(serializable)
                
            except Exception as e:
                import traceback
                print(f"Error in Blender block {block_idx}:", file=sys.stderr)
                traceback.print_exc()
                return
        
        elif block_type == 'inkscape':
            # Execute in Inkscape via CLI
            print(f"[Inkscape Block {block_idx}] Executing...")
            result = execute_inkscape_block(block_code, shared_context)
            
            if not result['success']:
                error_msg = result.get('error')
                print(f"Error in Inkscape block {block_idx}:", file=sys.stderr)
                if error_msg:
                    print(error_msg, file=sys.stderr)
                else:
                    print("Unknown error - check Inkscape and inkmcpcli.py", file=sys.stderr)
                return
            
            if result.get('output'):
                print(result['output'].rstrip())
            
            # Update context with Inkscape variables (if available)
            shared_context.update(result.get('variables', {}))
    
    print("\nHybrid execution completed successfully!")


# Main execution
if __name__ == "__main__":
    # Get the active text in Blender's text editor
    if bpy.context.space_data and bpy.context.space_data.type == 'TEXT_EDITOR':
        text = bpy.context.space_data.text
        if text:
            code = text.as_string()
            execute_hybrid(code)
        else:
            print("No text file is active in the text editor")
    else:
        print("This script must be run from Blender's text editor")
