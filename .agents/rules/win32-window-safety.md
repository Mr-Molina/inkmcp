# RULE: Fail-Safe Win32 Window Management & Process Scoping
> **Pattern Lineage**: `WIN-WIN-001` (PM-2026-0929-004)  
> **Related Invariants**: Invariant 52 (INFRASTRUCTURE_INVARIANTS.md)

## Context
When automating or focusing GUI applications on Windows using Win32 APIs (`EnumWindows`, `ShowWindow`, `SetForegroundWindow`, `BringWindowToTop`, `SetWindowPos`), unconstrained enumeration can restore, maximize, or disrupt internal operating system windows, background service wrappers, IME frames, and the user's taskbars.

## MUST
- You MUST strictly require a verified, non-null PID (`target_pid is not None and target_pid > 0`) or a verified target application window class (e.g. `gdkWindowToplevel` for Inkscape) before invoking window state mutation APIs.
- You MUST filter specifically for top-level user application windows and verify window titles.
- You MUST enforce a fail-safe upper bound on affected windows (aborting immediately if matching window count exceeds 5).
- Before calling `ShowWindow` on target windows, verify via a dry-run enumeration that ONLY the intended application's HWNDs are selected.

## MUST NOT
- MUST NOT invoke `ShowWindow`, `SetForegroundWindow`, or `BringWindowToTop` inside an unconstrained enumeration callback where `target_pid` is `None` or wildcarded.
- MUST NOT call `ShowWindow(..., SW_RESTORE)` or `ShowWindow(..., SW_MAXIMIZE)` on Windows system, shell, or background helper classes:
  - `Progman`, `WorkerW`, `Shell_TrayWnd`, `Shell_SecondaryTrayWnd`
  - `IME`, `MSCTFIME UI`, `CiceroUIWndFrame`
  - `Windows.UI.Core.CoreWindow`, `ApplicationFrameWindow`
  - `HwndWrapper[*]`, `SecHealth Window Class`, `GDI+ Hook Window Class`
  - Any window with title containing `SystemResourceNotifyWindow`, `MediaContextNotificationWindow`, `DDE Server Window`, or `Hidden Window`.
- MUST NOT alter window states of applications that do not belong to the target PID being automated.
