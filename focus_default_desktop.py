import os
import sys

try:
    import psutil
except ImportError:
    psutil = None

# --- System-class denylist: never interact with these window classes ---
SYSTEM_DENYLIST_CLASSES = {
    'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd',
    'IME', 'MSCTFIME UI', 'CiceroUIWndFrame', 'Windows.UI.Core.CoreWindow',
    'ApplicationFrameWindow', 'HwndWrapper', 'SecHealth Window Class',
    'GDI+ Hook Window Class',
}

# --- System-title denylist: never interact with these internal system windows ---
SYSTEM_DENYLIST_TITLES = (
    'SystemResourceNotifyWindow',
    'MediaContextNotificationWindow',
    'DDE Server Window',
    'Hidden Window',
)

# Upper-bound abort threshold (Invariant 52)
MAX_MATCHING_WINDOWS = 5

if sys.platform != "win32":
    u32 = None
    k32 = None
    WNDENUMPROC = None
else:
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32

    # --- Proper argtypes/restype declarations (prevents 64-bit HWND truncation) ---
    u32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    u32.OpenDesktopW.restype = wintypes.HANDLE
    u32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
    u32.SetThreadDesktop.restype = wintypes.BOOL
    u32.CloseDesktop.argtypes = [wintypes.HANDLE]
    u32.CloseDesktop.restype = wintypes.BOOL

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
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

    # Kernel32 process query fallback when psutil is absent
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL


def _get_process_name_by_pid(pid: int) -> str:
    """Retrieve process executable name by PID using psutil or Win32 QueryFullProcessImageNameW."""
    if pid <= 4:
        return "system"
    if psutil is not None:
        try:
            return psutil.Process(pid).name().lower()
        except Exception:
            return ""
    if sys.platform == "win32" and k32 is not None:
        h_proc = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_proc:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if k32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            k32.CloseHandle(h_proc)
    return ""


def main():
    if sys.platform != "win32":
        print("ERROR: focus_default_desktop.py is only supported on Windows.", file=sys.stderr)
        return

    # Only target Inkscape or a specific PID explicitly passed as an argument
    target_pid = None
    if len(sys.argv) > 1:
        try:
            target_pid = int(sys.argv[1])
        except ValueError:
            print(f"ERROR: target_pid must be an integer, got: {sys.argv[1]!r}", file=sys.stderr)
            return
        if target_pid <= 0:
            print(f"ERROR: Invalid target_pid: {target_pid}. Must be > 0 (Invariant 52).", file=sys.stderr)
            return

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
        if cls.value in SYSTEM_DENYLIST_CLASSES or cls.value.startswith("HwndWrapper"):
            return True

        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        proc_name = _get_process_name_by_pid(pid.value)
        if proc_name != "inkscape.exe":
            return True

        # STRICT FILTER: Never touch arbitrary windows.
        # Only process if PID matches target_pid or window title explicitly contains "Inkscape"
        if target_pid is not None and pid.value != target_pid:
            return True

        buf = ctypes.create_unicode_buffer(512)
        u32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()

        # Denylist check for internal system notification titles
        if any(denied_title in title for denied_title in SYSTEM_DENYLIST_TITLES):
            return True

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

    cb = WNDENUMPROC(enum_cb)
    u32.EnumWindows(cb, 0)

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
