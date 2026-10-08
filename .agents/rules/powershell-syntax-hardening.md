# RULE: Windows PowerShell Quoting, Escaping & Syntax Hardening
> **Pattern Lineage**: `GLB-004` (Escalated to Level 3 Automation), `WIN-PS-001`  
> **Related Invariants**: Invariant 53, Invariant 31 (INFRASTRUCTURE_INVARIANTS.md)

## Context
Antigravity executes shell commands on Windows inside PowerShell (`pwsh`). PowerShell uses fundamentally different parsing, quoting, and escaping rules from POSIX shells (`bash`/`sh`) and legacy Windows `cmd.exe`. Conflating bash escaping (`\"`, `\$`) or cmd.exe quoting with PowerShell causes silent argument corruption, syntax errors, and broken script executions.

---

## 1. PowerShell String & Quote Evaluation Rules

### Single-Quoted Strings (`'...'`) — Verbatim Literal
- Everything inside single quotes is treated literally.
- **NO variable expansion**: `'$variable'` is literally the characters `$`, `v`, `a`, `r`, `i`, `a`, `b`, `l`, `e`.
- **NO escape character expansion**: `'\n'` is two literal characters: `\` and `n`.
- **How to escape a single quote**: Double it (`''`). Example: `'It''s working'`.
- **BEST PRACTICE**: Default to single quotes for all strings, file paths, regexes, and arguments that do not require PowerShell variable expansion.

### Double-Quoted Strings (`"..."`) — Expandable String
- Expands variables (`$var`), subexpressions (`$(command)`), and escape sequences.
- **Escape character**: In PowerShell, the escape character is the **backtick** (`` ` ``), NOT the backslash (`\`)!
  - Newline: `` `n ``
  - Tab: `` `t ``
  - Literal dollar: `` `$ ``
  - Literal backtick: `` `` ``
- **How to escape a double quote inside double quotes**:
  - Method 1 (Doubling): `"He said ""Hello"""`
  - Method 2 (Backtick): `"He said `"Hello`""`
  - **CRITICAL ANTI-PATTERN**: `"He said \"Hello\""` is **INVALID** in PowerShell! PowerShell treats `\"` as a literal backslash followed by the end of the string.

### Heredocs (Multi-line Strings)
- **Verbatim Heredoc (`@' ... '@`)**:
  - Opening `@'` must be immediately followed by a newline.
  - Closing `'@` must be on a new line with **ZERO leading whitespace**.
- **Expanding Heredoc (`@" ... "@`)**:
  - Same line-break rules, but expands `$var` and `` ` ``.
  - Invariant 31 forbids embedding Python/regex code inside `@"..."@` due to unintended variable expansions.

---

## 2. Table of Forbidden Anti-Patterns vs. Safe Equivalents

| Category | Forbidden Anti-Pattern | Why It Fails | Safe Equivalent |
|---|---|---|---|
| **Python Inline Scripts** | `python -c "import os; ..."` | Fails on nested quotes, newlines, and dictionary access | Write to `.py` file via file tools; run `python script.py` |
| **Quote Escaping** | `Get-Item "C:\Path with \"quotes\""` | In pwsh, `\"` is a backslash + string termination | `Get-Item 'C:\Path with "quotes"'` or `"C:\Path with `"quotes`""` |
| **Variable Protection** | `Write-Host "Cost: $100"` | pwsh tries to evaluate `$100` as a variable | `Write-Host 'Cost: $100'` or `Write-Host "Cost: ""`$100"` |
| **Command Chaining** | `cmd1 && cmd2` in older pwsh scripts | Legacy PowerShell 5.1 does not support `&&` | Use `; if ($?) { cmd2 }` or modern `pwsh` |
| **Call Operator** | `"C:\Program Files\App.exe" args` | String literal at start of line is echoed, not executed | `& "C:\Program Files\App.exe" args` |
| **Stop-Parsing Symbol** | Complex native CLI flags with quotes | PowerShell strips or re-quotes arguments for native EXEs | Use `--%` stop-parsing symbol or pass argument arrays |

---

## 3. Mandatory Pre-Execution Checklist for `run_command`

Before submitting any command string to `run_command`, the agent MUST verify:
1. **Is this Python?** If the command contains more than 1 statement of Python or any quotes/dicts, it MUST be written to a `.py` file. No multi-line `python -c`.
2. **Are quotes balanced?** Count single and double quotes. Every quote opened must be closed.
3. **Is `\"` used inside double quotes?** Replace with `""` or ``` `" ``` or convert to single quotes `'...'`.
4. **Are literal `$` protected?** If `$` is intended literally (regex, currency, JSON key), ensure it is inside single quotes `'...'` or escaped with ``` `$ ```.
5. **Are paths with spaces quoted?** Path arguments with spaces must be enclosed in single quotes `'C:\Program Files\...'`.
