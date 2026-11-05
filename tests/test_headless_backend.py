import subprocess
from unittest.mock import patch
import pytest

from inkmcp.backends.headless import HeadlessSvgBackend


@pytest.fixture
def headless_backend():
    return HeadlessSvgBackend()


def test_headless_backend_is_available(headless_backend):
    assert headless_backend.is_available() is True
    assert headless_backend.get_backend_name() == "headless"


def test_headless_backend_create_circle(headless_backend):
    op_data = {
        "operation": "create",
        "tag": "circle",
        "attributes": {
            "cx": 100,
            "cy": 100,
            "r": 50,
            "fill": "blue"
        }
    }
    result = headless_backend.execute_operation(op_data)
    assert result["status"] == "success"
    assert "id" in result["data"]
    assert result["data"]["tag"] == "circle"


def test_headless_backend_get_document_info(headless_backend):
    # Add a rectangle
    headless_backend.execute_operation({
        "operation": "create",
        "tag": "rect",
        "attributes": {"x": 10, "y": 20, "width": 100, "height": 50}
    })
    info_result = headless_backend.execute_operation({"operation": "get_info"})
    assert info_result["status"] == "success"
    assert "dimensions" in info_result["data"]
    assert info_result["data"]["elementCounts"]["rect"] >= 1


def test_headless_backend_execute_code(headless_backend):
    code_op = {
        "operation": "execute_code",
        "code": "result = 40 + 2"
    }
    res = headless_backend.execute_operation(code_op)
    assert res["status"] == "success"
    assert res["data"]["return_value"] == 42


def test_headless_backend_get_element_info(headless_backend):
    create_res = headless_backend.execute_operation({
        "operation": "create",
        "tag": "rect",
        "attributes": {"id": "my_rect", "width": 100, "height": 50}
    })
    assert create_res["status"] == "success"
    elem_id = create_res["data"]["id"]

    info_res = headless_backend.execute_operation({
        "operation": "get_element_info",
        "id": elem_id
    })
    assert info_res["status"] == "success"
    assert info_res["data"]["id"] == elem_id
    assert info_res["data"]["tag"] == "rect"


def test_headless_backend_get_element_info_nonexistent(headless_backend):
    info_res = headless_backend.execute_operation({
        "operation": "get_element_info",
        "id": "nonexistent_id_123"
    })
    assert info_res["status"] == "error"
    assert "not found" in info_res["data"]["error"]


def test_headless_backend_initial_svg():
    custom_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="400"><circle id="c1" r="10"/></svg>'
    backend = HeadlessSvgBackend(initial_svg=custom_svg)
    info_res = backend.execute_operation({"operation": "get_info"})
    assert info_res["status"] == "success"
    assert info_res["data"]["dimensions"]["width"] == "500"
    assert info_res["data"]["elementCounts"]["circle"] == 1


def test_headless_backend_get_svg_string(headless_backend):
    svg_str = headless_backend.get_svg_string()
    assert "<svg" in svg_str
    assert "</svg>" in svg_str


def test_headless_backend_unknown_operation(headless_backend):
    res = headless_backend.execute_operation({"operation": "unknown_action_xyz"})
    assert res["status"] == "error"
    assert "Unknown operation" in res["data"]["error"]


def test_headless_backend_export_document_image(headless_backend):
    with patch("inkmcp.inkmcpops.export_operations.subprocess.run") as mock_run, \
         patch("os.path.exists", return_value=True), \
         patch("os.path.getsize", return_value=1234):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        export_op = {
            "operation": "export_document_image",
            "format": "png",
            "max_size": 800
        }
        res = headless_backend.execute_operation(export_op)
        assert res["status"] == "success"
        assert res["data"]["format"] == "png"
        assert res["data"]["file_size"] == 1234
        mock_run.assert_called_once()
