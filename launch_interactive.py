import ctypes
from ctypes import wintypes
import sys
import os
import subprocess
import sys
import time

from inkmcp.platform_utils import find_inkscape_executable

# --- Proper argtypes/restype declarations ---
k32 = ctypes.windll.kernel32
u32 = ctypes.windll.user32

k32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR,   # lpApplicationName
    wintypes.LPWSTR,    # lpCommandLine
    ctypes.c_void_p,    # lpProcessAttributes
    ctypes.c_void_p,    # lpThreadAttributes
    wintypes.BOOL,      # bInheritHandles
    wintypes.DWORD,     # dwCreationFlags
    ctypes.c_void_p,    # lpEnvironment
    wintypes.LPCWSTR,   # lpCurrentDirectory
    ctypes.c_void_p,    # lpStartupInfo
    ctypes.c_void_p,    # lpProcessInformation
]
k32.CreateProcessW.restype = wintypes.BOOL

k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.CloseHandle.restype = wintypes.BOOL

k32.GetLastError.argtypes = []
k32.GetLastError.restype = wintypes.DWORD

u32.EnumWindows.restype = wintypes.BOOL
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL


class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _verify_window_visible(target_pid: int, timeout: float = 2.0) -> bool:
    """Post-launch verification: check that at least one visible HWND belongs to the new PID."""
    time.sleep(timeout)
    visible_hwnds = []

    def enum_cb(hwnd, lparam):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == target_pid and u32.IsWindowVisible(hwnd):
            visible_hwnds.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    u32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    if visible_hwnds:
        print(f"VERIFIED: {len(visible_hwnds)} visible window(s) for PID {target_pid}")
        return True
    else:
        print(f"WARNING: No visible windows found for PID {target_pid} after {timeout}s")
        return False


def launch_on_default_desktop(svg_path: str):
    si = STARTUPINFO()
    si.cb = ctypes.sizeof(STARTUPINFO)
    si.lpDesktop = "WinSta0\\Default"
    si.dwFlags = 1  # STARTF_USESHOWWINDOW
    si.wShowWindow = 3  # SW_MAXIMIZE = 3

    pi = PROCESS_INFORMATION()

    inkscape_path = find_inkscape_executable()
    if not inkscape_path:
        print("ERROR: Could not find Inkscape executable")
        return None
    inkscape_exe = str(inkscape_path)

    cmd_str = subprocess.list2cmdline([str(inkscape_exe), str(svg_path)])
    cmd_buf = ctypes.create_unicode_buffer(cmd_str)

    res = k32.CreateProcessW(
        None,
        cmd_buf,
        None,
        None,
        False,
        0,
        None,
        str(os.path.dirname(os.path.abspath(svg_path))),
        ctypes.byref(si),
        ctypes.byref(pi),
    )

    if res:
        pid = pi.dwProcessId
        print(f"SUCCESS! Launched PID {pid} directly onto WinSta0\\Default")
        k32.CloseHandle(pi.hProcess)
        k32.CloseHandle(pi.hThread)
        _verify_window_visible(pid)
        return pid
    else:
        err = k32.GetLastError()
        print(f"FAILED to launch on WinSta0\\Default with error code {err}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: launch_interactive.py <svg_path>")
        print("ERROR: No SVG path provided. An explicit path argument is required.")
        sys.exit(1)
    target = sys.argv[1]
    launch_on_default_desktop(target)
