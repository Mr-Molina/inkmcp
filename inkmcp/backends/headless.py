"""
Headless Standalone SVG Backend
Manipulates SVG documents directly using inkex and ElementCreator without requiring GUI or D-Bus.
"""

import copy
import logging
import threading
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
        self._lock = threading.RLock()
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

    def load_from_file(self, filepath: str) -> None:
        """Load an SVG document from a file path."""
        with self._lock:
            self._doc = inkex.load_svg(filepath)
            self._creator.svg = self._doc.getroot()
            self._creator.document = self._doc

    def load_from_string(self, svg_str: str) -> None:
        """Load an SVG document from an XML string."""
        with self._lock:
            self._doc = inkex.load_svg(svg_str)
            self._creator.svg = self._doc.getroot()
            self._creator.document = self._doc

    def to_string(self) -> str:
        """Serialize the current SVG document to a UTF-8 string."""
        with self._lock:
            return self._creator.svg.tostring().decode("utf-8")

    def save(self, filepath: str) -> None:
        """Save the current SVG document to the specified file path."""
        with self._lock:
            content = self.to_string()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

    def get_svg_string(self) -> str:
        """Return the current document as a serialized SVG string."""
        with self._lock:
            return self.to_string()

    def execute_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            tag = operation_data.get("tag", "")
            op_type = operation_data.get("operation", "")

            # Map tag values to operation types (GLB-016 / BKD-003)
            tag_to_op = {
                "execute-code": "execute_code",
                "get-info": "get_info",
                "get-info-by-id": "get_element_info",
                "get-selection": "get_selection",
                "export-document-image": "export_document_image",
            }
            if not op_type and tag in tag_to_op:
                op_type = tag_to_op[tag]
            elif not op_type:
                op_type = "create"  # default

            svg_root = self._creator.svg

            backup_doc = None
            if op_type not in ("get_info", "get_element_info", "get_selection"):
                backup_doc = copy.deepcopy(self._doc)

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
                    elem_id = operation_data.get("id") or (
                        operation_data.get("attributes", {}).get("id", "")
                        if isinstance(operation_data.get("attributes"), dict)
                        else ""
                    )
                    return self._creator.get_element_info(svg_root, elem_id)

                elif op_type == "get_selection":
                    return self._creator.get_selection_info()

                elif op_type == "execute_code":
                    from inkmcp.inkmcpops.execute_operations import execute_code
                    attrs = dict(operation_data.get("attributes", {})) if isinstance(operation_data.get("attributes"), dict) else {}
                    for k, v in operation_data.items():
                        if k not in ("attributes", "tag", "operation"):
                            attrs.setdefault(k, v)
                    res = execute_code(self._creator, svg_root, attrs)
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
                    attrs = dict(operation_data.get("attributes", {})) if isinstance(operation_data.get("attributes"), dict) else {}
                    for k, v in operation_data.items():
                        if k not in ("attributes", "tag", "operation"):
                            attrs.setdefault(k, v)
                    return export_document_image(self._creator, svg_root, attrs)

                else:
                    return {
                        "status": "error",
                        "data": {"error": f"Unknown operation: {op_type}"},
                    }

            except Exception as e:
                if backup_doc is not None:
                    self._doc = backup_doc
                    self._creator.svg = self._doc.getroot()
                    self._creator.document = self._doc
                logger.error("Headless operation failed: %s", e)
                return {"status": "error", "data": {"error": str(e)}}
