"""
Headless Standalone SVG Backend
Manipulates SVG documents directly using inkex and ElementCreator without requiring GUI or D-Bus.
"""

import copy
import logging
from typing import Any, Dict, Optional
import inkex

from inkmcp.backends.base import InkscapeBackend
try:
    from inkscape_mcp import ElementCreator
except ImportError:
    import sys
    from pathlib import Path

    _repo_root = Path(__file__).resolve().parent.parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    try:
        from inkscape_mcp import ElementCreator
    except ImportError:
        from inkmcp.platform_utils import get_inkscape_extensions_dir

        _ext_dir = get_inkscape_extensions_dir()
        if str(_ext_dir) not in sys.path:
            sys.path.append(str(_ext_dir))
        from inkscape_mcp import ElementCreator
from inkmcp.inkmcpops.element_mapping import (
    get_element_class,
    should_place_in_defs,
    ensure_defs_section,
)

logger = logging.getLogger("InkscapeMCP.Backend.Headless")


class HeadlessSvgBackend(InkscapeBackend):
    """Executes SVG operations headlessly on an in-memory document."""

    def __init__(self, initial_svg: Optional[str] = None):
        self._creator = ElementCreator()
        if initial_svg:
            self._doc = inkex.load_svg(initial_svg)
        else:
            # Default empty SVG document (1000x1000 viewBox)
            empty_svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" '
                'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
                'width="1000" height="1000" viewBox="0 0 1000 1000">'
                '<g inkscape:groupmode="layer" id="layer1" inkscape:label="Layer 1"/>'
                '</svg>'
            )
            self._doc = inkex.load_svg(empty_svg)
        self._creator.svg = self._doc.getroot()
        self._creator.document = self._doc

    def is_available(self) -> bool:
        return True

    def get_backend_name(self) -> str:
        return "headless"

    def execute_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        op_type = operation_data.get("operation", "create")
        svg_root = self._creator.svg

        try:
            if op_type == "create":
                tag = operation_data.get("tag", "")
                ElementClass = get_element_class(tag)

                if ElementClass and should_place_in_defs(ElementClass):
                    target = ensure_defs_section(svg_root)
                else:
                    active_layer = svg_root.find(".//svg:g[@inkscape:groupmode='layer']", namespaces=inkex.NSS)
                    target = active_layer if active_layer is not None else svg_root

                id_mapping: Dict[str, str] = {}
                generated_ids: list[str] = []
                element = self._creator.create_element_recursive(
                    svg_root, operation_data, id_mapping, generated_ids
                )
                if element is not None:
                    target.append(element)
                    return {
                        "status": "success",
                        "data": {
                            "message": f"Element {tag} created successfully",
                            "id": element.get("id"),
                            "tag": tag,
                            "id_mapping": id_mapping,
                            "generated_ids": generated_ids,
                        },
                    }
                return {"status": "error", "data": {"error": "Failed to create element"}}

            elif op_type == "get_info":
                return self._creator.get_document_info(svg_root)

            elif op_type == "get_element_info":
                elem_id = operation_data.get("id", "")
                return self._creator.get_element_info(svg_root, elem_id)

            elif op_type == "execute_code":
                from inkmcp.inkmcpops.execute_operations import execute_code
                res = execute_code(self._creator, svg_root, operation_data)
                if (
                    isinstance(res, dict)
                    and res.get("status") == "success"
                    and isinstance(res.get("data"), dict)
                ):
                    local_vars = res["data"].get("local_variables", {})
                    if "result" in local_vars:
                        res["data"]["return_value"] = local_vars["result"]
                return res

            elif op_type == "export_document_image":
                from inkmcp.inkmcpops.export_operations import export_document_image
                return export_document_image(self._creator, svg_root, operation_data)

            else:
                return {
                    "status": "error",
                    "data": {"error": f"Unknown operation: {op_type}"},
                }

        except Exception as e:
            logger.error("Headless operation failed: %s", e)
            return {"status": "error", "data": {"error": str(e)}}

    def get_svg_string(self) -> str:
        """Return the current document as a serialized SVG string."""
        return self._creator.svg.tostring().decode("utf-8")
