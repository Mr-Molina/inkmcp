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

bl_info = {
    "name": "Inkscape Hybrid Execution",
    "description": "Execute hybrid code in Blender and Inkscape",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "Text Editor > Run Hybrid Code",
    "category": "Scripting",
}

import bpy
import subprocess
import json
import sys
import os
import re
from bpy.types import Operator, AddonPreferences
from bpy.props import StringProperty

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
        except (TypeError, ValueError) as e:
            excluded.append((key, f"not JSON-serializable ({type_name})"))
    
    # Warn about excluded variables
    if excluded:
        print(f"Note: {len(excluded)} variable(s) excluded from Inkscape context:")
        for var_name, reason in excluded[:5]:  # Show first 5
            print(f"  - {var_name}: {reason}")
        if len(excluded) > 5:
            print(f"  ... and {len(excluded) - 5} more")
    
    return serializable


def execute_inkscape_block(code, variables, inkmcp_cli_path):
    """Execute code block in Inkscape via inkmcpcli."""
    if not inkmcp_cli_path:
        return {
            'success': False,
            'error': "INKMCP_CLI_PATH not configured in addon preferences",
            'variables': {}
        }
    
    import os
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
                try:
                    repr_value = repr(value)
                    if repr_value and repr_value != '' and not repr_value.startswith('<'):
                        var_injections.append(f"{key} = {repr_value}")
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Variable '%s' dropped during serialization: %s", key, e)
            full_code = '\n'.join(var_injections) + '\n' + code if var_injections else code
    else:
        full_code = code
    
    # Write to temp file to avoid shell escaping
    import tempfile
    try:
        # UTF-8 encoding to handle special characters (e.g., é in curve names)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(full_code)
            temp_file = f.name
        
        try:
            result = subprocess.run(
                [sys.executable, inkmcp_cli_path, 'execute-code', '--pretty', '-f', temp_file],
                capture_output=True,
                text=True,
                timeout=30
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
    except Exception as e:
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
                    import io
                    import ast
                    from contextlib import redirect_stdout
                    
                    parsed_ast = ast.parse(block_code)
                    for node in ast.walk(parsed_ast):
                        if isinstance(node, ast.Attribute) and node.attr in ('__subclasses__', '__globals__'):
                            raise ValueError(f"Unsafe attribute access blocked: {node.attr}")
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                if alias.name.split('.')[0] in ('os', 'sys', 'subprocess', 'shutil'):
                                    raise ValueError(f"Unauthorized dangerous module import: {alias.name}")
                        if isinstance(node, ast.ImportFrom):
                            if node.module and node.module.split('.')[0] in ('os', 'sys', 'subprocess', 'shutil'):
                                raise ValueError(f"Unauthorized dangerous module import: {node.module}")
                    
                    global_env = {
                        '__builtins__': __builtins__,
                        'bpy': bpy,
                        'C': bpy.context,
                        'D': bpy.data,
                    }
                    local_env = dict(shared_context)
                    
                    stdout_capture = io.StringIO()
                    with redirect_stdout(stdout_capture):
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
            except Exception:
                pass
        addon_keymaps.clear()
    except AttributeError:
        pass  # Keymap cleanup unavailable in background mode
    
    try:
        bpy.types.TEXT_MT_text.remove(menu_func)
    except Exception:
        pass
    bpy.utils.unregister_class(SCRIPT_OT_run_hybrid)
    bpy.utils.unregister_class(InkscapeHybridPreferences)


if __name__ == "__main__":
    register()
