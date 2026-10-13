"""Win32 desktop automation module for live Inkscape canvas interaction."""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import win32gui
    import win32con
    import win32api
except ImportError:
    win32gui = None
    win32con = None
    win32api = None

logger = logging.getLogger(__name__)

class InkscapeDesktopAutomator:
    """Automates Paint Bucket tool selection, color styling, and canvas clicks."""

    def __init__(self):
        self._is_available = win32gui is not None

    def is_available(self) -> bool:
        return self._is_available

    def find_inkscape_window(self) -> Optional[int]:
        if not self._is_available:
            return None

        found_hwnd = []
        def _enum_cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "Inkscape" in title:
                    found_hwnd.append(hwnd)
            return True

        win32gui.EnumWindows(_enum_cb, None)
        return found_hwnd[0] if found_hwnd else None

    def _focus_window(self, hwnd: int) -> bool:
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            return True
        except Exception as e:
            logger.warning("Failed to focus Inkscape window: %s", e)
            return False

    def activate_paint_bucket(self, hwnd: int) -> bool:
        """Send 'U' key to switch to Paint Bucket tool."""
        if not self._is_available:
            return False
        try:
            win32api.keybd_event(0x55, 0, 0, 0)
            time.sleep(0.02)
            win32api.keybd_event(0x55, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.1)
            return True
        except Exception as e:
            logger.warning("Failed to send key to activate bucket tool: %s", e)
            return False

    def _get_canvas_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        rect = win32gui.GetClientRect(hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        left = rect[0] + int(w * 0.15)
        top = rect[1] + int(h * 0.15)
        right = rect[2] - int(w * 0.15)
        bottom = rect[3] - int(h * 0.15)
        return (left, top, right, bottom)

    def click_canvas_coordinate(self, hwnd: int, u: float, v: float) -> Tuple[int, int]:
        c_left, c_top, c_right, c_bottom = self._get_canvas_rect(hwnd)
        c_w = max(1, c_right - c_left)
        c_h = max(1, c_bottom - c_top)
        client_x = c_left + int(u * c_w)
        client_y = c_top + int(v * c_h)
        try:
            screen_x, screen_y = win32gui.ClientToScreen(hwnd, (client_x, client_y))
        except Exception:
            screen_x, screen_y = client_x, client_y
        self._dispatch_click(screen_x, screen_y)
        return (screen_x, screen_y)

    def _dispatch_click(self, screen_x: int, screen_y: int):
        win32api.SetCursorPos((screen_x, screen_y))
        time.sleep(0.02)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.02)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def execute_sequence(
        self,
        commands: List[Tuple[str, float, float]],
        click_delay_ms: int = 80,
        backend: Optional[Any] = None,
    ) -> Dict[str, Any]:
        hwnd = self.find_inkscape_window()
        if not hwnd:
            return {
                "status": "error",
                "message": "Inkscape window not found. Please ensure Inkscape is running with an open canvas.",
            }

        if not self._focus_window(hwnd):
            return {
                "status": "error",
                "message": "Failed to bring Inkscape window to foreground.",
            }

        self.activate_paint_bucket(hwnd)

        clicks_dispatched = 0
        aborted = False

        for hex_color, u, v in commands:
            # Check for ESC key abort
            if win32api and (win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000):
                aborted = True
                break

            # Re-assert focus if another window stole foreground
            if win32gui and win32gui.GetForegroundWindow() != hwnd:
                self._focus_window(hwnd)

            self.click_canvas_coordinate(hwnd, u, v)
            clicks_dispatched += 1

            # Enforce exact fill color on newly created & selected path
            if backend and hasattr(backend, "execute_operation") and hex_color:
                try:
                    style_op = {
                        "tag": "path",
                        "attributes": {
                            "style": f"fill:{hex_color};fill-opacity:1;stroke:none"
                        }
                    }
                    backend.execute_operation(style_op)
                except Exception as e:
                    logger.warning("Failed to apply color style: %s", e)

            if click_delay_ms > 0:
                time.sleep(click_delay_ms / 1000.0)

        return {
            "status": "aborted" if aborted else "success",
            "message": f"Dispatched {clicks_dispatched} bucket clicks" + (" (aborted by ESC)" if aborted else ""),
            "clicks_dispatched": clicks_dispatched,
            "total_commands": len(commands),
        }
