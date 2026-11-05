# RULE: Windows Interactive GUI Session Desktop Routing & Physical Visibility Gate
> **Pattern Lineage**: `WIN-DESKTOP-001` (PM-2026-0929-001), `GLB-005`, `GLB-006`  
> **Related Invariants**: Invariant 51 (INFRASTRUCTURE_INVARIANTS.md)

## Context
Antigravity and automated test harnesses on Windows run inside isolated Win32 desktop sandboxes (e.g. `WinSta0\exebox-...`). Child processes spawned via standard APIs inherit this hidden desktop, rendering GUI applications invisible on physical monitors even while active in memory.

## MUST
- When launching interactive desktop applications intended for user collaboration or visual interaction, you MUST explicitly specify `STARTUPINFO.lpDesktop = "WinSta0\\Default"` using Win32 `CreateProcessW`.
- When verifying or reporting whether a GUI window is open, titled, or visible to the user on Windows, you MUST:
  1. Attach to `WinSta0\Default` via `OpenDesktopW("Default", ...)` or execute `.agents/inspect_desktop_windows.py`.
  2. Enumerate windows via `EnumDesktopWindows` / `EnumWindows` on that desktop thread.
  3. Verify true Win32 title (`GetWindowTextW`), window class (`GetClassNameW`), `IsWindowVisible(hwnd) == True`, and `GetWindowRect` confirming non-zero physical coordinates.
- You MUST cite the verified HWND, window class, true Win32 title, and screen coordinates before claiming whether a window is present, visible, or invisible.

## MUST NOT
- MUST NOT assert that an interactive GUI window is visible on screen based solely on process memory presence (`Get-Process`, `psutil`, or PID checks).
- MUST NOT assert that an interactive GUI window is INVISIBLE, headless, or on an isolated desktop based on `.NET Process.MainWindowTitle` or `Get-Process ... | Select MainWindowTitle` returning an empty string. Non-native frameworks (GTK3, Electron, Qt, Blender) frequently have empty .NET `MainWindowTitle` properties even when their rendered windows are fully visible and maximized.
- MUST NOT spawn interactive GUI applications via unrouted `subprocess.Popen` or `Start-Process` without explicitly declaring `lpDesktop = "WinSta0\\Default"`.

