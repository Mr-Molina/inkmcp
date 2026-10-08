# Infrastructure Invariants & Mechanical Guardrails

The following mechanical invariants are binding safety rules enforced across sessions and workflows:

## Invariant 13: Debug Artifact Cleanup
- **Rule**: Prior to completing a session handoff, all temporary debug scripts, scratch logs, and transient build artifacts must be sanitized or removed.

## Invariant 14: Three Strikes Rule for Troubleshooting
- **Rule**: Maximum of **three attempts** allowed to solve a specific technical error or system failure. If the third attempt fails, all modification attempts MUST stop immediately and a Deep Research Request must be compiled.

## Invariant 24: Credential Leak Scan
- **Rule**: No plain-text API keys, passwords, private tokens, or secrets may be committed or persisted in public artifacts. A secret scan must run prior to session closing.

## Invariant 28: Mechanical Mitigations for Recurring Failures
- **Rule**: Any failure identified as RECURRING must be addressed using mechanical mitigations (strict MUST/MUST NOT directives or automated scripts), not advisory comments.

## Invariant 29: Script Verification Requirement
- **Rule**: After creating or modifying helper scripts (such as Python cleaner or audit scripts), the agent MUST run a syntax check/CLI test execution before marking the task complete.

## Invariant 30: Tool Name Schema Integrity
- **Rule**: Imported skills MUST be validated against active runtime tool declarations (search_web, run_command, invoke_subagent, etc.) before integration into global config.

## Invariant 31: Python Code Generation Safety
- **Rule**: The agent MUST NOT embed Python code containing quotes or regex patterns inside PowerShell Set-Content @"..."@ heredocs. The agent MUST use native file tools or clean Python script writes to avoid string quote escaping corruption.

## Invariant 32: Strict Verification Exit Criteria
- **Rule**: When verifying script execution per Invariant 29, the agent MUST NOT accept CLI output with non-zero exit codes or usage/help messages as verification. The agent MUST execute scripts against a valid test input file and verify an exit code 0 result.

## Invariant 33: Sequential Operations Delegation Threshold
- **Rule**: The Orchestrator MUST NOT perform sequential script debugging, regex refactoring, or multi-file auditing on the main thread if the task requires more than 3 consecutive file/command operations. It MUST delegate these specialized tasks to subagents.

## Invariant 34: Orchestrator Delegation Mandate
- **Rule**: The Orchestrator agent coordinates tasks and must delegate heavy specialized sub-tasks (CVE scans, cleanups, deep research) to subagents.

## Invariant 35: Subagent Scope and Reporting
- **Rule**: Subagents operate within defined scope and must report findings back to the Orchestrator.

## Invariant 36: Invariant and Docstring Preservation
- **Rule**: Subagents must preserve existing codebase invariants and docstrings unless explicitly ordered to mutate them.

## Invariant 37: Subagent Command Exit Verification
- **Rule**: Subagents must verify all command exit codes before reporting task completion.

## Invariant 38: Three Strikes Deep Research Transition
- **Rule**: On the 3rd failed attempt to resolve a technical error or on user third-strike override, agents MUST halt all code mutations, compile all environment diagnostics, hypotheses, and logs into a structured Deep Research Request, and await verified research findings before resuming.

## Invariant 39: Evidence Before Assertions (Anti-Guessing)
- **Rule**: Agents MUST cite specific evidence (command output, API response, log line) before stating any root cause. Agents MUST NOT present a hypothesis as a conclusion or propose a fix in the same message as discovering an unverified issue.

## Invariant 40: Live Ground Truth Requirement (Anti-Stale Information)
- **Rule**: When evaluating active infrastructure state, switch port assignments, link health, or online status, agents MUST query live infrastructure (SSH, API, CLI, SNMP) rather than relying on static documentation or legacy CSV export dumps.

## Invariant 41: Anti-Simulated Tool Verification Gate
- **Rule**: Agents MUST NOT assert or imply browser rendering, UI interactions, or tool executions occurred unless backed by actual tool calls with live responses or captured image artifacts. If a tool fails to attach, agents MUST immediately notify the user.

## Invariant 42: Staged Deployment & Manual Upload Gate
- **Rule**: When deploying hardware configurations requiring manual or external staging (FTP, TFTP, file servers), file generation and device restart commands MUST be strictly decoupled into separate phases with an explicit user confirmation gate between them.

## Invariant 43: Ground Truth Entity & Acronym Verification
- **Rule**: Agents MUST verify institutional names, client identities, organization titles, and domain acronym expansions against authoritative repository documentation or device backups before scaffolding UI templates or configuration copy.

## Invariant 51: Windows Interactive GUI Session Desktop Routing, Window Inspection & Physical Visibility Gate
- **Rule**: When interacting with or launching desktop applications on Windows:
  1. **Interactive Process Spawning**: When launching GUI applications intended for user collaboration, agents MUST set `STARTUPINFO.lpDesktop = "WinSta0\\Default"` via `CreateProcessW`.
  2. **Banned Negative & Positive Visibility Heuristics**: Agents MUST NOT assert that a GUI window is visible, invisible, headless, or trapped on an isolated desktop session based solely on process table queries (`Get-Process`, `psutil`, or `.NET Process.MainWindowTitle`).
  3. **Non-Native Window Hierarchy Fallacy**: Agents MUST recognize that GTK3 (Inkscape, GIMP), Electron (VSCode, Slack), Qt, Blender, and game engines frequently initialize hidden message/event pump windows as their primary Win32 handle. Consequently, `.NET Process.MainWindowTitle` and `Get-Process ... | Select MainWindowTitle` routinely return empty strings (`""`) even when the application is maximized and fully visible on the physical display.
  4. **Authoritative Desktop Window Verification**: Before asserting window visibility, titles, or coordinates, agents MUST inspect `WinSta0\Default` using Win32 `EnumDesktopWindows` / `EnumWindows` verifying `IsWindowVisible(hwnd) == True`, non-zero screen coordinates (`GetWindowRect`), and true Win32 text (`GetWindowTextW`), or execute the certified inspection tool `.agents/inspect_desktop_windows.py`.


## Invariant 52: Fail-Safe Win32 Window Management & Process Scoping Invariant
- **Rule**: When invoking Win32 APIs (`EnumWindows`, `ShowWindow`, `SetForegroundWindow`, `BringWindowToTop`, `SetWindowPos`) or shell scripts to manipulate desktop windows, agents:
  1. MUST strictly require a verified, non-null PID (`target_pid is not None and target_pid > 0`) and/or verified application window class (e.g. `gdkWindowToplevel`).
  2. MUST NEVER perform window state mutations (`ShowWindow`, `SetForegroundWindow`) inside an unconstrained enumeration callback or when `target_pid` is `None`.
  3. MUST explicitly filter out and NEVER call `ShowWindow` on Windows system, shell, or IME window classes (including `Progman`, `WorkerW`, `Shell_TrayWnd`, `Shell_SecondaryTrayWnd`, `IME`, `MSCTFIME UI`, `CiceroUIWndFrame`, `Windows.UI.Core.CoreWindow`, `HwndWrapper[*]`, or `SecHealth Window Class`).
  4. MUST enforce a maximum affected window count assertion (aborting if match count > 5) before executing state changes.

## Invariant 53: Strict Windows PowerShell Quoting, Character Escaping & Command Purity
- **Rule**: When constructing and issuing shell commands on Windows:
  1. **Zero Multi-Line Inline Python**: Agents MUST NOT execute `python -c` for multi-line scripts, dictionaries, f-strings, or any logic exceeding a single trivial expression. Code MUST be written to a `.py` file via file editing tools.
  2. **PowerShell Quote Escape Parity**: In double-quoted PowerShell strings, internal double quotes MUST be escaped as `""` or ``` `" ```. Agents MUST NOT use `\"` (which PowerShell treats as a literal backslash followed by a closing quote).
  3. **Sensitive Character Protection**: Variables (`$`), command separators (`;`), redirection (`>`, `<`), pipelines (`|`), call operators (`&`), and background operators (`&`) MUST NOT appear inside double quotes unless variable evaluation or piping is explicitly intended. For literal strings, use single quotes `'...'`.
  4. **Pre-Execution Quoting Audit**: Prior to proposing any `run_command` invocation with complex arguments, the agent MUST verify quote pairing, boundary matching, and escape characters.


## Invariant 54: Prohibition of Manual Coordinate Drawing for Vector Art (Anti-Hallucinated Vector Synthesis)
- **Rule**: When creating, modifying, repairing, or healing vector artwork (SVG, DXF, EPS, CAD):
  1. **Zero Raw Coordinate Drawing**: Agents MUST NEVER attempt to "draw" or "illustrate" complex organic artwork, bevels, perspective lines, or anatomical features by hardcoding or guessing raw Bézier curve strings (`d="M... C... Z"`) in Python, XML, or shell scripts.
  2. **Deterministic Geometric Operations Only**: When repairing, completing, or healing vector paths, agents MUST use deterministic techniques:
     - **Symmetry & Affine Transforms**: Mirroring, rotating, or scaling existing artist-drawn geometry to complete missing symmetric features.
     - **Inkscape Action Booleans**: Invoking Inkscape CLI actions (`--actions="select-by-id:...; path-union; path-difference; path-break-apart"`) to let the native geometry engine calculate curves.
     - **Subpath De-duplication**: Removing internal hole subpaths (`Z M ...`) from compound paths rather than generating synthetic polygon patches.
  3. **Collaborative GUI Boundary**: When organic artistic decisions (e.g. custom wood grain, decorative styling, freehand shading) are required, the agent MUST recognize the boundary of automated code generation, provide clean layer scaffolding, and hand off fine-grained artistic node editing to the human partner via the live Inkscape session.

