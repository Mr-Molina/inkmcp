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

    def test_system_classes_membership(self):
        from inspect_desktop_windows import SYSTEM_CLASSES
        expected_system_classes = {
            "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
            "IME", "MSCTFIME UI", "CiceroUIWndFrame", "Windows.UI.Core.CoreWindow",
            "ApplicationFrameWindow", "SecHealth Window Class", "GDI+ Hook Window Class",
        }
        assert expected_system_classes.issubset(SYSTEM_CLASSES)

    def test_screenshot_safety_target_pid_required(self):
        from inspect_desktop_windows import RECT, capture_window_screenshot
        rect = RECT(0, 0, 100, 100)
        assert capture_window_screenshot(100, rect, "test.png", target_pid=None) is False
        assert capture_window_screenshot(100, rect, "test.png", target_pid=0) is False
        assert capture_window_screenshot(100, rect, "test.png", target_pid=-5) is False

    def test_screenshot_safety_system_classes_rejected(self):
        from inspect_desktop_windows import RECT, capture_window_screenshot
        rect = RECT(0, 0, 100, 100)
        assert capture_window_screenshot(100, rect, "test.png", target_pid=1234, target_class="Progman") is False
        assert capture_window_screenshot(100, rect, "test.png", target_pid=1234, target_class="Shell_TrayWnd") is False
        assert capture_window_screenshot(100, rect, "test.png", target_pid=1234, target_class="HwndWrapper[App.exe]") is False
        assert capture_window_screenshot(100, rect, "test.png", target_pid=1234, target_class="SecHealth Window Class") is False

    def test_mocked_inspect_windows_excludes_system_classes(self, monkeypatch):
        from unittest.mock import MagicMock
        import inspect_desktop_windows

        mock_u32 = MagicMock()
        mock_k32 = MagicMock()
        monkeypatch.setattr(inspect_desktop_windows, "u32", mock_u32)
        monkeypatch.setattr(inspect_desktop_windows, "k32", mock_k32)
        monkeypatch.setattr(inspect_desktop_windows, "get_process_name_by_pid", lambda pid: "test_app.exe")

        def fake_enum_windows(callback, lparam):
            mock_u32.IsWindowVisible.return_value = 1

            def get_class(hwnd, buf, maxlen):
                if hwnd == 1:
                    buf.value = "Progman"
                elif hwnd == 2:
                    buf.value = "HwndWrapper[Background.exe]"
                else:
                    buf.value = "InkscapeApp"
                return 1

            mock_u32.GetClassNameW.side_effect = get_class

            def get_pid(hwnd, byref_pid):
                byref_pid._obj.value = 1000
                return 1000

            mock_u32.GetWindowThreadProcessId.side_effect = get_pid
            mock_u32.GetWindowTextLengthW.return_value = 20

            def get_text(hwnd, buf, maxlen):
                buf.value = "Inkscape Doc"
                return 12

            mock_u32.GetWindowTextW.side_effect = get_text
            mock_u32.IsIconic.return_value = 0
            mock_u32.IsZoomed.return_value = 0

            callback(1, lparam)
            callback(2, lparam)
            callback(3, lparam)
            return True

        mock_u32.EnumWindows.side_effect = fake_enum_windows
        mock_u32.OpenDesktopW.return_value = 123

        # Exclude system classes (default)
        windows = inspect_desktop_windows.inspect_windows(visible_only=False, include_system=False)
        classes = [w["class"] for w in windows]
        assert "Progman" not in classes
        assert "HwndWrapper[Background.exe]" not in classes
        assert "InkscapeApp" in classes

        # Include system classes
        windows_all = inspect_desktop_windows.inspect_windows(visible_only=False, include_system=True)
        classes_all = [w["class"] for w in windows_all]
        assert "Progman" in classes_all
        assert "HwndWrapper[Background.exe]" in classes_all
        assert "InkscapeApp" in classes_all

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
