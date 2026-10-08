import ctypes
from ctypes import wintypes
import sys

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32

# --- Proper argtypes/restype declarations (prevents 64-bit HWND truncation) ---
u32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
u32.OpenDesktopW.restype = wintypes.HANDLE
u32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
u32.SetThreadDesktop.restype = wintypes.BOOL
u32.CloseDesktop.argtypes = [wintypes.HANDLE]
u32.CloseDesktop.restype = wintypes.BOOL
u32.EnumWindows.restype = wintypes.BOOL
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetWindowTextW.restype = ctypes.c_int
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u32.ShowWindow.restype = wintypes.BOOL
u32.SetForegroundWindow.argtypes = [wintypes.HWND]
u32.SetForegroundWindow.restype = wintypes.BOOL
u32.BringWindowToTop.argtypes = [wintypes.HWND]
u32.BringWindowToTop.restype = wintypes.BOOL

# --- System-class denylist: never interact with these window classes ---
SYSTEM_DENYLIST_CLASSES = {
    'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd',
    'IME', 'MSCTFIME UI', 'CiceroUIWndFrame', 'Windows.UI.Core.CoreWindow',
    'ApplicationFrameWindow', 'HwndWrapper', 'SecHealth Window Class',
    'GDI+ Hook Window Class',
}

# Upper-bound abort threshold (Invariant 52)
MAX_MATCHING_WINDOWS = 5


def main():
    # Only target Inkscape or a specific PID explicitly passed as an argument
    target_pid = int(sys.argv[1]) if len(sys.argv) > 1 else None

    DESKTOP_ALL = 0x01FF
    hdesk = u32.OpenDesktopW("Default", 0, False, DESKTOP_ALL)
    if not hdesk:
        print("Failed to open Default desktop, err:", k32.GetLastError())
        return

    if not u32.SetThreadDesktop(hdesk):
        print("ERROR: SetThreadDesktop failed, err:", k32.GetLastError())
        u32.CloseDesktop(hdesk)
        return

    # --- Pass 1: Enumerate only, collect matching HWNDs ---
    found = []

    def enum_cb(hwnd, lparam):
        # Denylist check first — skip system window classes immediately
        cls = ctypes.create_unicode_buffer(512)
        u32.GetClassNameW(hwnd, cls, 512)
        if cls.value in SYSTEM_DENYLIST_CLASSES:
            return True

        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        try:
            import psutil
            if psutil.Process(pid.value).name().lower() != "inkscape.exe":
                return True
        except Exception:
            return True

        # STRICT FILTER: Never touch arbitrary windows.
        # Only process if PID matches target_pid or window title explicitly contains "Inkscape"
        if target_pid is not None and pid.value != target_pid:
            return True

        buf = ctypes.create_unicode_buffer(512)
        u32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()

        # If no PID was passed, strictly match only Inkscape windows
        is_inkscape = "Inkscape" in title or cls.value.startswith("gdkWindowToplevel")
        if target_pid is None and not is_inkscape:
            return True

        if is_inkscape or (target_pid is not None and pid.value == target_pid):
            vis = u32.IsWindowVisible(hwnd)
            # Only collect top-level application windows with titles
            if title:
                found.append((hwnd, pid.value, cls.value, title, vis))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    u32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    # --- Between passes: upper-bound abort check (Invariant 52) ---
    if len(found) > MAX_MATCHING_WINDOWS:
        print(
            f"ERROR: Aborting — found {len(found)} matching windows "
            f"(exceeds safety limit of {MAX_MATCHING_WINDOWS}). "
            "This may indicate a runaway match. No windows were modified."
        )
        u32.CloseDesktop(hdesk)
        return

    # --- Pass 2: Mutate — restore/focus collected windows ---
    for hwnd, pid_val, cls_val, title, vis in found:
        print(f"Inkscape Window Target: PID {pid_val} | HWND {hwnd} | Title: '{title}'")
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
        u32.BringWindowToTop(hwnd)

    u32.CloseDesktop(hdesk)
    print(f"Inkscape windows focused: {len(found)}")

if __name__ == "__main__":
    main()
