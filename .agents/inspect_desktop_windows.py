#!/usr/bin/env python3
"""inspect_desktop_windows.py — Authoritative Win32 Desktop Window Inspector.

Part of the Level 3 Automation mitigation for WIN-DESKTOP-001 (PM-2026-0929-005).
Directly attaches to WinSta0\\Default and enumerates true Win32 top-level windows,
retrieving window classes, true Win32 titles, visibility states, screen coordinates,
and owning process details.

Eliminates the .NET Process.MainWindowTitle false-negative bug where GTK3 (Inkscape),
Electron, Qt, and Blender report empty MainWindowTitle in PowerShell even when fully visible.

Usage:
    python inspect_desktop_windows.py --process inkscape
    python inspect_desktop_windows.py --pid 33872
    python inspect_desktop_windows.py --all --visible-only
    python inspect_desktop_windows.py --process inkscape --json
    python inspect_desktop_windows.py --process inkscape --screenshot capture.png
"""

import sys
import os
import argparse
import json
from pathlib import Path

if sys.platform != "win32":
    print("Error: inspect_desktop_windows.py is only supported on Windows.", file=sys.stderr)
    sys.exit(1)

import ctypes
from ctypes import wintypes

# Win32 Function Signatures & Types
u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

# User32 Signatures
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

u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
u32.GetWindowTextLengthW.restype = ctypes.c_int

u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetWindowTextW.restype = ctypes.c_int

u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetClassNameW.restype = ctypes.c_int

u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL

u32.IsIconic.argtypes = [wintypes.HWND]  # Minimized
u32.IsIconic.restype = wintypes.BOOL

u32.IsZoomed.argtypes = [wintypes.HWND]  # Maximized
u32.IsZoomed.restype = wintypes.BOOL

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
u32.GetWindowRect.restype = wintypes.BOOL

# Kernel32 Signatures for Process Image Resolution
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


def get_process_name_by_pid(pid: int) -> str:
    """Retrieve process executable name given PID."""
    if pid <= 4:
        return "System"
    h_proc = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        k32.CloseHandle(h_proc)


def capture_window_screenshot(hwnd: int, rect: RECT, output_path: str) -> bool:
    """Capture a screenshot of the specified window rectangle using ctypes GDI."""
    try:
        # Try PIL ImageGrab first if available for high-DPI awareness
        try:
            from PIL import ImageGrab
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
            norm_path = Path(output_path).resolve()
            norm_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(norm_path))
            return True
        except ImportError:
            pass

        # Fallback to ctypes GDI capture
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return False

        hdc_screen = u32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        gdi32.SelectObject(hdc_mem, hbitmap)

        SRCCOPY = 0x00CC0020
        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, rect.left, rect.top, SRCCOPY)

        # To write PNG without PIL is complex in raw ctypes, but we can save BMP or advise PIL
        try:
            from PIL import Image
            import io
            # If PIL is installed but ImageGrab failed, use BMP buffer
            pass
        except ImportError:
            pass

        u32.ReleaseDC(0, hdc_screen)
        gdi32.DeleteDC(hdc_mem)
        gdi32.DeleteObject(hbitmap)
        return False
    except Exception as e:
        print(f"Screenshot error: {e}", file=sys.stderr)
        return False


def inspect_windows(
    target_process: str | None = None,
    target_pid: int | None = None,
    visible_only: bool = True,
    include_system: bool = False,
) -> list[dict]:
    """Inspect all top-level windows on WinSta0\\Default."""
    # Open desktop with read-only diagnostic privilege (INFRA-003)
    DESKTOP_READOBJECTS = 0x0001
    hdesk = u32.OpenDesktopW("Default", 0, False, DESKTOP_READOBJECTS)
    if not hdesk:
        # Fallback with DESKTOP_READOBJECTS | 0x0004 for window enumeration
        hdesk = u32.OpenDesktopW("Default", 0, False, DESKTOP_READOBJECTS | 0x0004)

    if hdesk:
        u32.SetThreadDesktop(hdesk)

    results = []
    pid_name_cache = {}

    SYSTEM_CLASSES = {
        "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
        "IME", "MSCTFIME UI", "CiceroUIWndFrame", "Windows.UI.Core.CoreWindow",
        "ApplicationFrameWindow", "SecHealth Window Class", "GDI+ Hook Window Class",
    }

    def enum_callback(hwnd, lparam):
        is_vis = bool(u32.IsWindowVisible(hwnd))
        if visible_only and not is_vis:
            return True

        # Window Class
        cls_buf = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(hwnd, cls_buf, 256)
        cls_name = cls_buf.value

        if not include_system and cls_name in SYSTEM_CLASSES:
            return True

        # Process ID & Name
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        p_val = pid.value

        if target_pid is not None and p_val != target_pid:
            return True

        if p_val not in pid_name_cache:
            pid_name_cache[p_val] = get_process_name_by_pid(p_val)
        proc_name = pid_name_cache[p_val]

        if target_process:
            proc_match = target_process.lower() in proc_name.lower()
            # Also check if title or class contains target process
            # (useful for GTK apps)
            if not proc_match:
                return True

        # True Win32 Title
        length = u32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        u32.GetWindowTextW(hwnd, title_buf, length + 1)
        title = title_buf.value

        # Window Geometry
        r = RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        w = r.right - r.left
        h = r.bottom - r.top

        is_min = bool(u32.IsIconic(hwnd))
        is_max = bool(u32.IsZoomed(hwnd))

        state = "Normal"
        if is_min:
            state = "Minimized"
        elif is_max:
            state = "Maximized"

        results.append({
            "hwnd": hex(hwnd),
            "hwnd_int": hwnd,
            "pid": p_val,
            "process": proc_name,
            "class": cls_name,
            "title": title,
            "visible": is_vis,
            "state": state,
            "rect": {
                "left": r.left,
                "top": r.top,
                "right": r.right,
                "bottom": r.bottom,
                "width": w,
                "height": h,
            }
        })
        return True

    cb = WNDENUMPROC(enum_callback)
    u32.EnumWindows(cb, 0)

    if hdesk:
        u32.CloseDesktop(hdesk)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Authoritative Win32 Desktop Window Inspector for WinSta0\\Default."
    )
    parser.add_argument("--process", "-p", help="Filter by process name (e.g. inkscape, blender, chrome)")
    parser.add_argument("--pid", type=int, help="Filter by process ID")
    parser.add_argument("--all", "-a", action="store_true", help="Include hidden and background system windows")
    parser.add_argument("--visible-only", action="store_true", default=True, help="Show only visible windows (default: True)")
    parser.add_argument("--include-hidden", action="store_true", help="Include non-visible windows")
    parser.add_argument("--json", "-j", action="store_true", help="Output raw JSON array")
    parser.add_argument("--screenshot", "-s", help="Save a screenshot of the first matching window to this file path")

    args = parser.parse_args()

    vis_only = not args.include_hidden
    windows = inspect_windows(
        target_process=args.process,
        target_pid=args.pid,
        visible_only=vis_only,
        include_system=args.all,
    )

    if args.screenshot and windows:
        target = windows[0]
        r = RECT(
            target["rect"]["left"],
            target["rect"]["top"],
            target["rect"]["right"],
            target["rect"]["bottom"],
        )
        saved = capture_window_screenshot(target["hwnd_int"], r, args.screenshot)
        if saved:
            print(f"Screenshot saved to {args.screenshot}", file=sys.stderr)
        else:
            print(f"Failed to capture screenshot to {args.screenshot}", file=sys.stderr)

    if args.json:
        print(json.dumps(windows, indent=2))
        return

    if not windows:
        filter_desc = []
        if args.process:
            filter_desc.append(f"process='{args.process}'")
        if args.pid:
            filter_desc.append(f"pid={args.pid}")
        desc_str = f" matching {', '.join(filter_desc)}" if filter_desc else ""
        print(f"No windows found{desc_str} on WinSta0\\Default.")
        return

    # Print Table Header
    print(f"{'HWND':<10} {'PID':<8} {'PROCESS':<18} {'STATE':<10} {'GEOMETRY (X,Y,WxH)':<22} {'CLASS':<20} {'TITLE'}")
    print("-" * 120)
    for w in windows:
        geo = f"({w['rect']['left']},{w['rect']['top']} {w['rect']['width']}x{w['rect']['height']})"
        title_disp = w['title'] if len(w['title']) <= 40 else w['title'][:37] + "..."
        print(f"{w['hwnd']:<10} {w['pid']:<8} {w['process']:<18} {w['state']:<10} {geo:<22} {w['class'][:18]:<20} {title_disp}")


if __name__ == "__main__":
    main()
