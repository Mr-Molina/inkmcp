import sys
import pytest
from pathlib import Path

# Add .agents to sys.path to import inspect_desktop_windows
agents_dir = Path(__file__).parent.parent / ".agents"
if str(agents_dir) not in sys.path:
    sys.path.insert(0, str(agents_dir))


class TestInspectDesktopWindows:
    def test_script_exists_and_is_file(self):
        script_path = agents_dir / "inspect_desktop_windows.py"
        assert script_path.is_file(), "inspect_desktop_windows.py must exist in .agents/"

    @pytest.mark.skipif(sys.platform != "win32", reason="Win32 API only available on Windows")
    def test_inspect_windows_returns_list_of_window_dicts(self):
        from inspect_desktop_windows import inspect_windows

        # Inspect all visible windows
        windows = inspect_windows(visible_only=True)
        assert isinstance(windows, list)
        assert len(windows) > 0, "Expected at least one top-level window on live desktop"

        # Verify schema of the first window
        first = windows[0]
        required_keys = {"hwnd", "hwnd_int", "pid", "process", "class", "title", "visible", "state", "rect"}
        assert required_keys.issubset(first.keys()), f"Missing keys in window dict: {required_keys - set(first.keys())}"
        assert first["visible"] is True
        assert first["state"] in ("Normal", "Minimized", "Maximized")
        assert "width" in first["rect"]
        assert "height" in first["rect"]

    @pytest.mark.skipif(sys.platform != "win32", reason="Win32 API only available on Windows")
    def test_inspect_windows_filtering_by_pid_or_nonexistent_process(self):
        from inspect_desktop_windows import inspect_windows

        # Filter by a PID that definitely doesn't exist
        windows = inspect_windows(target_pid=99999999)
        assert windows == []

        # Filter by a process name that doesn't exist
        windows_proc = inspect_windows(target_process="nonexistent_process_xyz_123")
        assert windows_proc == []
