"""
Inkscape Hybrid Execution - Blender Addon
Execute hybrid code with seamless Blender/Inkscape integration

Installation:
1. Edit > Preferences > Add-ons > Install
2. Select this file
3. Enable "Scripting: Inkscape Hybrid Execution"
4. Set INKMCP_CLI_PATH in addon preferences

Usage:
1. Write hybrid code with # @local and # @inkscape magic comments
2. Text Editor > Run Hybrid Code (or Ctrl+Shift+H)
"""

import bpy
import subprocess
import json
import sys
import os
import re
import shutil
import keyword
import ast
import builtins
import io
from contextlib import redirect_stdout, redirect_stderr
from typing import Dict, Any, Optional
from bpy.types import Operator, AddonPreferences
from bpy.props import StringProperty

bl_info = {
    "name": "Inkscape Hybrid Execution",
    "description": "Execute hybrid code in Blender and Inkscape",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "Text Editor > Run Hybrid Code",
    "category": "Scripting",
}

_FORBIDDEN_MODULES = {
    'os', 'sys', 'subprocess', 'shutil', 'ctypes', 'socket', 'importlib', 'builtins'
}

_FORBIDDEN_CALLS = {
    'eval', 'exec', 'compile', 'open', '__import__', 'getattr', 'setattr', 'delattr'
}

_DANGEROUS_ATTRIBUTES = {
    'gi_frame', 'gi_code', 'f_globals', 'f_builtins', 'f_locals', 'f_back',
    'f_code', 'tb_frame', 'tb_next', 'cr_frame', 'cr_code', 'ag_frame',
    'ag_code', 'format', 'format_map'
}

_FORBIDDEN_BUILTINS = {
    'eval', 'exec', 'compile', 'open', 'getattr', 'setattr', 'delattr',
    'globals', 'locals', 'vars', 'breakpoint', 'input'
}


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root_mod = name.split('.')[0] if name else ''
    if root_mod in _FORBIDDEN_MODULES or name in _FORBIDDEN_MODULES:
        raise ImportError(f"Unauthorized dangerous module import: {name}")
    return builtins.__import__(name, globals, locals, fromlist, level)


def _get_safe_builtins() -> Dict[str, Any]:
    safe = {k: v for k, v in builtins.__dict__.items() if k not in _FORBIDDEN_BUILTINS}
    safe['__import__'] = _safe_import
    return safe


def _validate_hybrid_ast(code: str) -> None:
    """Validate AST for hybrid block execution in Blender context.
    
    Rejects:
    - Imports of forbidden modules: os, sys, subprocess, shutil, ctypes, socket, importlib, builtins
    - Calls to forbidden functions: eval, exec, compile, open, __import__, getattr, setattr, delattr
    - Unsafe attribute access: all dunders (starts with '__') and frame/generator attributes
    """
    tree = ast.parse(code)
    for node in ast.walk(tree):
        # 1. Reject forbidden module imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_root = alias.name.split('.')[0]
                if mod_root in _FORBIDDEN_MODULES or alias.name in _FORBIDDEN_MODULES:
                    raise ValueError(f"Unauthorized dangerous module import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod_root = node.module.split('.')[0]
                if mod_root in _FORBIDDEN_MODULES or node.module in _FORBIDDEN_MODULES:
                    raise ValueError(f"Unauthorized dangerous module import: {node.module}")
            for alias in node.names:
                if alias.name in _FORBIDDEN_MODULES:
                    raise ValueError(f"Unauthorized dangerous module import: {alias.name}")

        # 2. Reject unsafe attribute access (dunders and frame attributes)
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith('__') or node.attr in _DANGEROUS_ATTRIBUTES:
                raise ValueError(f"Unsafe attribute access blocked: {node.attr}")

        # 3. Reject unsafe identifiers
        elif isinstance(node, ast.Name):
            if node.id in ('__subclasses__', '__globals__', '__bases__', '__mro__', '__code__') or node.id in _DANGEROUS_ATTRIBUTES:
                raise ValueError(f"Unsafe identifier blocked: {node.id}")

        # 4. Reject forbidden function calls
        elif isinstance(node, ast.Call):
            call_name = None
            if isinstance(node.func, ast.Name):
                call_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                call_name = node.func.attr
            if call_name in _FORBIDDEN_CALLS:
                raise ValueError(f"Unauthorized dangerous call: {call_name}")

# Import the hybrid executor functions
# (We'll inline them here to make the addon self-contained)

def parse_hybrid_blocks(code):
    """Parse code into blocks based on magic comments."""
    lines = code.split('\n')
    blocks = []
    current_type = 'local'
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


def serialize_variables(local_vars, exclude_names=None):
    """Extract JSON-serializable variables."""
    if exclude_names is None:
        exclude_names = {'__builtins__', '__name__', '__doc__', 'bpy', 'C', 'D'}
    
    serializable = {}
    excluded = []
    
    for key, value in local_vars.items():
        if key.startswith('_') or key in exclude_names:
            continue
        
        type_name = type(value).__name__
        if type_name in ('module', 'function', 'type', 'builtin_function_or_method', 'bpy_struct') or hasattr(value, 'bl_rna'):
            excluded.append((key, f"non-serializable type ({type_name})"))
            continue
        
        try:
            json.dumps(value)
            serializable[key] = value
        except (TypeError, ValueError):
            excluded.append((key, f"not JSON-serializable ({type_name})"))
    
    # Warn about excluded variables
    if excluded:
        print(f"Note: {len(excluded)} variable(s) excluded from Inkscape context:")
        for var_name, reason in excluded[:5]:  # Show first 5
            print(f"  - {var_name}: {reason}")
        if len(excluded) > 5:
            print(f"  ... and {len(excluded) - 5} more")
    
    return serializable


def get_python_executable() -> str:
    """Resolve a real Python binary for subprocess invocation.

    When running inside Blender, sys.executable points to blender.exe.
    Resolves the bundled or system python executable instead.
    """
    exe = sys.executable
    if "blender" in os.path.basename(exe).lower():
        candidates = [
            os.path.join(sys.prefix, "bin", "python.exe"),
            os.path.join(sys.prefix, "python.exe"),
            os.path.join(os.path.dirname(exe), "python.exe"),
            os.path.join(sys.prefix, "bin", "python3"),
            os.path.join(sys.prefix, "python3"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        system_py = shutil.which("python") or shutil.which("python3")
        if system_py:
            return system_py
    return exe


def execute_inkscape_block(code: str, variables: Optional[Dict[str, Any]] = None, inkmcp_cli_path: Optional[str] = None) -> Dict[str, Any]:
    """Execute code block in Inkscape via inkmcpcli."""
    if inkmcp_cli_path is None:
        inkmcp_cli_path = os.environ.get('INKMCP_CLI_PATH')

    if not inkmcp_cli_path:
        return {
            'success': False,
            'error': "INKMCP_CLI_PATH not configured in addon preferences",
            'variables': {}
        }
    
    if not os.path.exists(inkmcp_cli_path):
        return {'success': False, 'error': f"CLI path does not exist: {inkmcp_cli_path}", 'variables': {}}
    if not os.path.isfile(inkmcp_cli_path):
        return {'success': False, 'error': f"CLI path is not a regular file: {inkmcp_cli_path}", 'variables': {}}
    if not inkmcp_cli_path.endswith('.py'):
        return {'success': False, 'error': f"CLI path must be a .py file: {inkmcp_cli_path}", 'variables': {}}
    if os.path.basename(inkmcp_cli_path) != 'inkmcpcli.py':
        return {'success': False, 'error': f"CLI path must be named inkmcpcli.py: {inkmcp_cli_path}", 'variables': {}}

    # PERF-003: Serialize variables with a structured json.loads bootstrap when present
    if variables:
        valid_variables = {
            k: v for k, v in variables.items()
            if isinstance(k, str)
            and k.isidentifier()
            and not keyword.iskeyword(k)
            and not k.startswith('_')
        }
        try:
            serialized_json = json.dumps(valid_variables)
            var_injections = [
                "import json",
                f"_inkmcp_vars = json.loads({json.dumps(serialized_json)})",
            ]
            for key in valid_variables:
                var_injections.append(f"{key} = _inkmcp_vars[{json.dumps(key)}]")
            var_injections.append("del _inkmcp_vars")
            full_code = '\n'.join(var_injections) + '\n' + code
        except (TypeError, ValueError, OverflowError) as e:
            import logging
            logging.getLogger(__name__).warning(
                "Variable serialization failed, executing without injected variables: %s", e
            )
            full_code = code
    else:
        full_code = code
    
    # Write to temp file to avoid shell escaping
    import tempfile
    try:
        # UTF-8 encoding to handle special characters (e.g., é in curve names)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(full_code)
            temp_file = f.name
        
        py_exe = get_python_executable()
        creationflags = 0x08000000 if os.name == 'nt' else 0
        try:
            result = subprocess.run(
                [py_exe, inkmcp_cli_path, 'execute-code', '--pretty', '-f', temp_file],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                creationflags=creationflags,
            )
        finally:
            try:
                os.unlink(temp_file)
            except OSError:
                pass
        
        if result.returncode != 0:
            error_detail = result.stderr or result.stdout or "No output"
            return {
                'success': False,
                'error': error_detail,
                'variables': {}
            }
        
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            return {
                'success': False,
                'error': f"Failed to parse response: {str(e)}\nOutput: {result.stdout[:200]}",
                'variables': {}
            }
        
        # Response structure: {"result": {"success": true, "response": {"data": {...}}}}
        result_data = response.get('result', response)  # Fallback to response itself
        if not result_data.get('success', False):
            error = result_data.get('error', 'Unknown error')
            return {'success': False, 'error': error, 'variables': {}}
        
        # Check inner execution status
        inner_data = result_data.get('response', {}).get('data', {})
        
        # Check if execution failed
        if not inner_data.get('execution_successful', True):
            error = inner_data.get('errors') or inner_data.get('error') or 'Code execution failed'
            return {'success': False, 'error': error, 'variables': {}}
        
        return {
            'success': True,
            'output': inner_data.get('output', ''),
            'error': None,
            'variables': inner_data.get('local_variables', {})
        }
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        return {
            'success': False,
            'error': f"Failed to execute Inkscape block: {str(e)}",
            'variables': {}
        }


class InkscapeHybridPreferences(AddonPreferences):
    bl_idname = __name__

    inkmcp_cli_path: StringProperty(
        name="INKMCP CLI Path",
        description="Path to inkmcpcli.py (e.g., /path/to/inkmcp/inkmcp/inkmcpcli.py)",
        default="",
        subtype='FILE_PATH',
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Configure path to inkmcpcli.py:")
        layout.prop(self, "inkmcp_cli_path")


class SCRIPT_OT_run_hybrid(Operator):
    """Run hybrid Blender/Inkscape code"""
    bl_idname = "script.run_hybrid"
    bl_label = "Run Hybrid Code"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return (
            context.space_data is not None
            and context.space_data.type == 'TEXT_EDITOR'
            and getattr(context.space_data, 'text', None) is not None
        )

    def execute(self, context):
        # Get preferences
        preferences = context.preferences.addons[__name__].preferences
        inkmcp_cli_path = preferences.inkmcp_cli_path
        
        if not inkmcp_cli_path:
            self.report({'ERROR'}, "Please set INKMCP CLI Path in addon preferences")
            return {'CANCELLED'}
        
        # Get active text
        if not context.space_data or context.space_data.type != 'TEXT_EDITOR':
            self.report({'ERROR'}, "Must be run from Text Editor")
            return {'CANCELLED'}
        
        text = context.space_data.text
        if not text:
            self.report({'ERROR'}, "No active text file")
            return {'CANCELLED'}
        
        code = text.as_string()
        blocks = parse_hybrid_blocks(code)
        
        if not blocks:
            self.report({'ERROR'}, "No code blocks found")
            return {'CANCELLED'}
        
        shared_context = {}
        
        for block_idx, (block_type, block_code) in enumerate(blocks, 1):
            if not block_code.strip():
                continue
            
            if block_type == 'local':
                try:
                    _validate_hybrid_ast(block_code)
                    
                    global_env = {
                        '__builtins__': _get_safe_builtins(),
                        'bpy': bpy,
                        'C': bpy.context,
                        'D': bpy.data,
                    }
                    local_env = dict(shared_context)
                    
                    stdout_capture = io.StringIO()
                    with redirect_stdout(stdout_capture), redirect_stderr(stdout_capture):
                        exec(block_code, global_env, local_env)
                    
                    output = stdout_capture.getvalue()
                    if output:
                        print(f"[Blender Block {block_idx}]")
                        print(output.rstrip())
                    
                    serializable = serialize_variables(local_env)
                    shared_context.update(serializable)
                    
                except Exception as e:
                    import traceback
                    self.report({'ERROR'}, f"Error in Blender block {block_idx}: {str(e)}")
                    traceback.print_exc()
                    return {'CANCELLED'}
            
            elif block_type == 'inkscape':
                print(f"[Inkscape Block {block_idx}] Executing...")
                result = execute_inkscape_block(block_code, shared_context, inkmcp_cli_path)
                
                if not result['success']:
                    error_msg = result.get('error', 'Unknown error')
                    self.report({'ERROR'}, f"Error in Inkscape block {block_idx}")
                    print(f"Error: {error_msg}")
                    return {'CANCELLED'}
                
                if result.get('output'):
                    print(result['output'].rstrip())
                
                shared_context.update(result.get('variables', {}))
        
        self.report({'INFO'}, "Hybrid execution completed!")
        return {'FINISHED'}


def menu_func(self, context):
    self.layout.operator(SCRIPT_OT_run_hybrid.bl_idname, icon='PLAY')


addon_keymaps = []

def register():
    bpy.utils.register_class(InkscapeHybridPreferences)
    bpy.utils.register_class(SCRIPT_OT_run_hybrid)
    bpy.types.TEXT_MT_text.append(menu_func)
    
    # Add keymap
    try:
        wm = bpy.context.window_manager
        kc = wm.keyconfigs.addon
        if kc:
            km = kc.keymaps.new(name='Text', space_type='TEXT_EDITOR')
            kmi = km.keymap_items.new(SCRIPT_OT_run_hybrid.bl_idname, 'H', 'PRESS', ctrl=True, shift=True)
            addon_keymaps.append((km, kmi))
    except AttributeError:
        pass  # Keymap registration unavailable in background mode


def unregister():
    try:
        for km, kmi in addon_keymaps:
            try:
                km.keymap_items.remove(kmi)
            except (KeyError, RuntimeError, AttributeError):
                pass
        addon_keymaps.clear()
    except AttributeError:
        pass  # Keymap cleanup unavailable in background mode
    
    try:
        bpy.types.TEXT_MT_text.remove(menu_func)
    except (ValueError, RuntimeError, AttributeError):
        pass
    bpy.utils.unregister_class(SCRIPT_OT_run_hybrid)
    bpy.utils.unregister_class(InkscapeHybridPreferences)


if __name__ == "__main__":
    register()
