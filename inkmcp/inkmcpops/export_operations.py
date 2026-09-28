"""Document export operations module"""

import tempfile
import base64
import os
import re
from typing import Dict, Any
from inkex.command import call
from .common import create_success_response, create_error_response

UNIT_FACTORS = {
    'px': 1.0,
    'in': 96.0,
    'cm': 96.0 / 2.54,
    'mm': 96.0 / 25.4,
    'pt': 96.0 / 72.0,
    'pc': 16.0,
}


def _parse_svg_width(svg) -> float:
    """Safely parse document width with fallback to viewBox and default 100."""
    width = None

    # First attempt to read and parse the 'width' attribute
    if hasattr(svg, 'get'):
        raw_width = svg.get('width')
        if raw_width is not None:
            raw_str = str(raw_width).strip()
            # If percentage or not a valid unit format, defer to viewBox fallback
            if not raw_str.endswith('%'):
                m = re.match(r'^([0-9.]+)\s*([a-zA-Z]*)$', raw_str)
                if m:
                    val_str, unit = m.groups()
                    try:
                        val = float(val_str)
                        factor = UNIT_FACTORS.get(unit.lower(), 1.0)
                        width = val * factor
                    except (ValueError, TypeError):
                        width = None

    # Fallback to viewBox if width could not be parsed or was a percentage
    if width is None or width <= 0:
        # Check svg.viewbox object (or svg.viewbox.width)
        vb_obj = getattr(svg, 'viewbox', None)
        if vb_obj is not None:
            vb_w = getattr(vb_obj, 'width', None)
            if isinstance(vb_w, (int, float)) and vb_w > 0:
                width = float(vb_w)

        # Check viewBox attribute string (e.g., '0 0 1024 768')
        if width is None and hasattr(svg, 'get'):
            raw_vb = svg.get('viewBox') or svg.get('viewbox')
            if raw_vb:
                parts = str(raw_vb).replace(',', ' ').split()
                if len(parts) == 4:
                    try:
                        vb_w = float(parts[2])
                        if vb_w > 0:
                            width = vb_w
                    except (ValueError, TypeError):
                        pass

        # Check get_viewbox() method if available
        if width is None and hasattr(svg, 'get_viewbox') and callable(svg.get_viewbox):
            try:
                vb = svg.get_viewbox()
                if hasattr(vb, 'width') and vb.width > 0:
                    width = float(vb.width)
            except Exception:
                pass

    # Final fallback to 100
    if width is None or width <= 0:
        width = 100.0

    return width


def export_document_image(extension_instance, svg, attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Export document as image"""
    temp_svg = None
    output_path = None
    success = False
    try:
        # Get export parameters
        format_type = attributes.get('format', 'png')
        max_size = int(attributes.get('max_size', 800))
        return_base64_val = attributes.get('return_base64', 'true')
        if isinstance(return_base64_val, bool):
            return_base64 = return_base64_val
        else:
            return_base64 = str(return_base64_val).lower() == 'true'
        area = attributes.get('area', 'page')  # page, drawing, selection

        # Generate temp output path
        output_fd, output_path = tempfile.mkstemp(suffix=f'.{format_type}', prefix='inkscape_export_')
        os.close(output_fd)  # Close the file descriptor

        # Save current document to temp SVG file
        temp_svg_fd, temp_svg = tempfile.mkstemp(suffix='.svg')
        os.close(temp_svg_fd)  # Close the file descriptor
        with open(temp_svg, 'wb') as f:
            extension_instance.save(f)

        # Build export command
        if format_type == 'png':
            if area == 'page':
                export_area = '--export-area-page'
            elif area == 'drawing':
                export_area = '--export-area-drawing'
            else:
                export_area = '--export-area-page'

            # Calculate DPI to respect max_size
            dpi = 96  # Default
            if max_size:
                width = _parse_svg_width(svg)
                if max_size < width:
                    dpi = int((max_size / width) * 96)

            call('inkscape',
                 '--export-type=png',
                 f'--export-filename={output_path}',
                 f'--export-dpi={dpi}',
                 export_area,
                 temp_svg,
                 timeout=30)
        else:
            return create_error_response(f"Unsupported format: {format_type}")

        # Get file info
        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

        response_data = {
            "export_path": output_path,
            "format": format_type,
            "file_size": file_size,
            "area": area
        }

        # Add base64 data if requested
        if return_base64 and os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                response_data["base64_data"] = base64.b64encode(f.read()).decode('ascii')

        success = True
        return create_success_response(
            f"Document exported as {format_type.upper()}",
            **response_data
        )

    except Exception as e:
        return create_error_response(f"Export failed: {str(e)}")
    finally:
        if temp_svg and os.path.exists(temp_svg):
            try:
                os.unlink(temp_svg)
            except OSError:
                pass
        if not success and output_path and os.path.exists(output_path):
            try:
                os.unlink(output_path)
            except OSError:
                pass