from unittest.mock import MagicMock, patch
from inkmcp.backends.desktop_automator import InkscapeDesktopAutomator

def test_automator_window_not_found():
    automator = InkscapeDesktopAutomator()
    with patch.object(automator, "find_inkscape_window", return_value=None):
        result = automator.execute_sequence([("#FF0000", 0.5, 0.5)])
        assert result["status"] == "error"
        assert "Inkscape window not found" in result["message"]

def test_automator_click_sequence_execution():
    automator = InkscapeDesktopAutomator()
    mock_backend = MagicMock()
    with patch.object(automator, "find_inkscape_window", return_value=12345), \
         patch.object(automator, "_focus_window", return_value=True), \
         patch.object(automator, "activate_paint_bucket", return_value=True), \
         patch.object(automator, "_get_canvas_rect", return_value=(100, 100, 900, 700)), \
         patch.object(automator, "_dispatch_click") as mock_click, \
         patch("win32gui.GetForegroundWindow", return_value=12345), \
         patch("win32api.GetAsyncKeyState", return_value=0), \
         patch("time.sleep"):

        commands = [
            ("#FF0000", 0.25, 0.25),
            ("#00FF00", 0.75, 0.75),
        ]
        result = automator.execute_sequence(commands, click_delay_ms=0, backend=mock_backend)
        assert result["status"] == "success"
        assert result["clicks_dispatched"] == 2
        assert mock_click.call_count == 2
        assert mock_backend.execute_operation.call_count == 2

def test_automator_escape_abort():
    automator = InkscapeDesktopAutomator()
    with patch.object(automator, "find_inkscape_window", return_value=12345), \
         patch.object(automator, "_focus_window", return_value=True), \
         patch.object(automator, "activate_paint_bucket", return_value=True), \
         patch.object(automator, "_get_canvas_rect", return_value=(100, 100, 900, 700)), \
         patch.object(automator, "_dispatch_click"), \
         patch("win32gui.GetForegroundWindow", return_value=12345), \
         patch("win32api.GetAsyncKeyState", side_effect=[0, 0x8000]), \
         patch("time.sleep"):

        commands = [
            ("#FF0000", 0.25, 0.25),
            ("#00FF00", 0.75, 0.75),
        ]
        result = automator.execute_sequence(commands, click_delay_ms=0)
        assert result["status"] == "aborted"
        assert result["clicks_dispatched"] == 1
