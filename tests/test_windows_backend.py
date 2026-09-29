# tests/test_windows_backend.py
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from inkmcp.backends.windows_cli import WindowsCliBackend, _ActionLock


@pytest.fixture
def mock_platform():
    orig_is_file = Path.is_file
    with patch("inkmcp.backends.windows_cli.get_operating_system", return_value="windows"), \
         patch("inkmcp.backends.windows_cli.find_inkscape_executable", return_value=Path("C:/Program Files/Inkscape/bin/inkscape.com")), \
         patch("inkmcp.backends.windows_cli.is_extension_installed", return_value=True), \
         patch.object(Path, "is_file", autospec=True, side_effect=lambda p: True if "inkscape" in str(p).lower() else orig_is_file(p)):
        yield


def test_windows_cli_is_available(mock_platform):
    backend = WindowsCliBackend()
    assert backend.is_available() is True
    assert backend.get_backend_name() == "windows_cli"


def test_windows_cli_execute_operation_success(mock_platform):
    backend = WindowsCliBackend()

    def fake_subprocess_run(cmd, capture_output=True, text=True, timeout=30):
        # Find response_file from mcp_params.json
        temp_dir = tempfile.gettempdir()
        params_file = os.path.join(temp_dir, "mcp_params.json")
        with open(params_file, "r") as pf:
            data = json.load(pf)
        resp_file = data["response_file"]
        with open(resp_file, "w") as rf:
            json.dump({"status": "success", "data": {"id": "circle123", "message": "created"}}, rf)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        res = backend.execute_operation({"operation": "create", "tag": "circle"})
        assert res["status"] == "success"
        assert res["data"]["id"] == "circle123"


def test_windows_cli_handles_inkscape_error(mock_platform):
    backend = WindowsCliBackend()
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="Inkscape crashed", stdout="")):
        res = backend.execute_operation({"operation": "create", "tag": "circle"})
        assert res["status"] == "error"
        assert "Inkscape action execution failed" in res["data"]["error"]
        assert "Inkscape crashed" in res["data"]["error"]


def test_windows_cli_handles_inkscape_error_stdout_fallback(mock_platform):
    backend = WindowsCliBackend()
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="", stdout="Error logged on stdout")):
        res = backend.execute_operation({"operation": "create", "tag": "circle"})
        assert res["status"] == "error"
        assert "Inkscape action execution failed" in res["data"]["error"]
        assert "Error logged on stdout" in res["data"]["error"]


def test_windows_cli_timeout_handling(mock_platform):
    backend = WindowsCliBackend()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="inkscape.com", timeout=30)):
        res = backend.execute_operation({"operation": "create", "tag": "circle"})
        assert res["status"] == "error"
        assert "timed out" in res["data"]["error"]


def test_windows_cli_unavailable_os(mock_platform):
    with patch("inkmcp.backends.windows_cli.get_operating_system", return_value="linux"):
        backend = WindowsCliBackend()
        assert backend.is_available() is False


def test_windows_cli_unavailable_no_exe(mock_platform):
    with patch("inkmcp.backends.windows_cli.find_inkscape_executable", return_value=None):
        backend = WindowsCliBackend()
        assert backend.is_available() is False


def test_windows_cli_unavailable_no_extension(mock_platform):
    with patch("inkmcp.backends.windows_cli.is_extension_installed", return_value=False):
        backend = WindowsCliBackend()
        assert backend.is_available() is False


def test_windows_cli_execute_when_unavailable(mock_platform):
    with patch("inkmcp.backends.windows_cli.get_operating_system", return_value="linux"):
        backend = WindowsCliBackend()
        res = backend.execute_operation({"operation": "create"})
        assert res["status"] == "error"
        assert "Windows Inkscape backend is unavailable" in res["data"]["error"]


def test_windows_cli_missing_or_empty_response_file(mock_platform):
    backend = WindowsCliBackend()
    with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
        # Subprocess returns 0, but response file is never written (empty 0 bytes)
        res = backend.execute_operation({"operation": "create", "tag": "circle"})
        assert res["status"] == "error"
        assert "produced no response file" in res["data"]["error"]


def test_windows_cli_rejects_response_file_outside_temp(mock_platform):
    backend = WindowsCliBackend()
    outside_path = os.path.abspath(r"C:\Windows\System32\evil_response.json") if os.name == "nt" else "/etc/evil_response.json"
    with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
        res = backend.execute_operation({"operation": "create", "response_file": outside_path})
        assert res["status"] == "error"
        assert "Response file error: Path outside temp directory" in res["data"]["error"]


def test_windows_cli_unexpected_exception(mock_platform):
    backend = WindowsCliBackend()
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        res = backend.execute_operation({"operation": "create"})
        assert res["status"] == "error"
        assert "Permission denied" in res["data"]["error"]


def test_windows_cli_custom_inkscape_path(mock_platform):
    custom_path = Path("D:/Custom/Inkscape/bin/inkscape.com")
    backend = WindowsCliBackend(inkscape_path=custom_path)
    assert backend.is_available() is True

    captured_cmds = []

    def fake_run(cmd, **kwargs):
        captured_cmds.append(cmd)
        # write empty response file to avoid error
        temp_dir = tempfile.gettempdir()
        params_file = os.path.join(temp_dir, "mcp_params.json")
        with open(params_file, "r") as pf:
            data = json.load(pf)
        with open(data["response_file"], "w") as rf:
            json.dump({"status": "success", "data": {}}, rf)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        res = backend.execute_operation({"operation": "get_info"})
        assert res["status"] == "success"
        assert str(custom_path) in captured_cmds[0]


def test_action_lock_acquire_and_release(tmp_path):
    """Test exclusive lock acquire, contention timeout, and subsequent acquisition after release."""
    lock_file = str(tmp_path / "test.lock")
    lock1 = _ActionLock(lock_path=lock_file, timeout=0.1, poll_interval=0.01)
    lock2 = _ActionLock(lock_path=lock_file, timeout=0.05, poll_interval=0.01)

    assert lock1.acquire() is True
    # lock2 should time out waiting for lock1
    with pytest.raises(TimeoutError, match="Timed out"):
        lock2.acquire()

    lock1.release()
    # Now lock2 can be acquired
    assert lock2.acquire() is True
    lock2.release()


def test_action_lock_context_manager(tmp_path):
    """Test _ActionLock as context manager properly acquires and releases lock."""
    lock_file = str(tmp_path / "test_cm.lock")
    with _ActionLock(lock_path=lock_file, timeout=0.1):
        lock2 = _ActionLock(lock_path=lock_file, timeout=0.05, poll_interval=0.01)
        with pytest.raises(TimeoutError):
            lock2.acquire()

    with _ActionLock(lock_path=lock_file, timeout=0.1):
        pass


def test_action_lock_fallback_mode_without_msvcrt(tmp_path):
    """Test fallback atomic file lock mode when msvcrt is not available."""
    lock_file = str(tmp_path / "fallback.lock")
    with patch("inkmcp.backends.windows_cli.msvcrt", None):
        lock1 = _ActionLock(lock_path=lock_file, timeout=0.1, poll_interval=0.01)
        lock2 = _ActionLock(lock_path=lock_file, timeout=0.05, poll_interval=0.01)

        assert lock1.acquire() is True
        assert os.path.exists(lock_file)

        with pytest.raises(TimeoutError):
            lock2.acquire()

        lock1.release()
        assert not os.path.exists(lock_file)

        assert lock2.acquire() is True
        lock2.release()


def test_windows_cli_execute_operation_lock_held_during_run(mock_platform, tmp_path):
    """Verify lock is actively held during execute_operation so concurrent calls cannot collide."""
    lock_file = str(tmp_path / "action.lock")
    backend = WindowsCliBackend(lock_path=lock_file, lock_timeout=0.5)

    lock_was_held = False

    def fake_subprocess_run(cmd, capture_output=True, text=True, timeout=30):
        nonlocal lock_was_held
        test_lock = _ActionLock(lock_path=lock_file, timeout=0.05, poll_interval=0.01)
        try:
            test_lock.acquire()
            lock_was_held = False
            test_lock.release()
        except TimeoutError:
            lock_was_held = True

        temp_dir = tempfile.gettempdir()
        params_file = os.path.join(temp_dir, "mcp_params.json")
        with open(params_file, "r") as pf:
            data = json.load(pf)
        with open(data["response_file"], "w") as rf:
            json.dump({"status": "success", "data": {"result": "ok"}}, rf)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        res = backend.execute_operation({"operation": "get_info"})
        assert res["status"] == "success"
        assert lock_was_held is True


def test_windows_cli_execute_operation_lock_timeout(mock_platform, tmp_path):
    """Verify backend handles lock acquisition timeout gracefully by returning error dict."""
    lock_file = str(tmp_path / "timeout.lock")
    backend = WindowsCliBackend(lock_path=lock_file, lock_timeout=0.05)

    external_lock = _ActionLock(lock_path=lock_file, timeout=0.1)
    external_lock.acquire()
    try:
        res = backend.execute_operation({"operation": "get_info"})
        assert res["status"] == "error"
        assert "lock timed out" in res["data"]["error"].lower()
    finally:
        external_lock.release()

