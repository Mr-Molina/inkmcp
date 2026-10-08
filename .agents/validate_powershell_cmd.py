"""PowerShell Command Syntax & Quoting Validator (Level 3 Automation Gate).

Validates command strings intended for execution via run_command (pwsh)
against known quoting, escaping, and multi-line inline Python pitfalls.
Enforces Invariant 53 and powershell-syntax-hardening.md rules.
"""

import re
import sys
from typing import List, Tuple

def validate_command(cmd: str) -> Tuple[bool, List[str]]:
    """Validate a shell command string for Windows PowerShell compatibility.

    Returns:
        (is_valid, error_list)
    """
    errors = []
    trimmed = cmd.strip()

    if not trimmed:
        return True, []

    # 1. Check for multi-line or quote-heavy inline Python (Invariant 53 Rule 1)
    python_c_match = re.search(r'(?:python(?:\.exe)?|py(?:\.exe)?)\s+-c\s+(.*)', trimmed, re.DOTALL | re.IGNORECASE)
    if python_c_match:
        py_arg = python_c_match.group(1).strip()
        # Disallow newlines in python -c
        if "\n" in py_arg or "\r" in py_arg:
            errors.append(
                "Invariant 53 Violation: Multi-line inline Python (python -c with newlines) is forbidden. "
                "Write the code to a .py file via file tools and execute with 'python script.py'."
            )
        # Disallow multiple statements separated by ';' inside python -c
        if ";" in py_arg and len(py_arg) > 40:
            errors.append(
                "Invariant 53 Violation: Complex multi-statement inline Python (python -c with ';') is forbidden. "
                "Write to a .py file instead."
            )
        # Disallow dictionaries or nested quoting
        if re.search(r'\{.*["\'].*:.*\}', py_arg):
            errors.append(
                "Invariant 53 Violation: Inline Python containing dictionary or JSON literals is forbidden. "
                "Write to a .py file instead."
            )

    # 2. Check for invalid PowerShell quote escaping (\" inside double quotes)
    # In PowerShell, \" is NOT an escape sequence for double quote; it is literal \ followed by string end.
    if re.search(r'\\"', trimmed):
        # Check if it appears inside a double-quoted region
        # Common anti-pattern: -c "print(\"hello\")" or "echo \"value\""
        errors.append(
            "PowerShell Quoting Error: Detected '\"' escape sequence. "
            "PowerShell does NOT use backslash to escape double quotes! "
            "Use doubled double quotes '\"\"' or backtick-quote '`\"' inside double quotes, "
            "or use single quotes '...' for literal strings."
        )

    # 3. Check for balanced quotes
    # Count quotes taking into account PowerShell escaping:
    # Inside single quotes: '' is an escaped single quote.
    # Inside double quotes: "" and `" are escaped double quotes.
    in_single = False
    in_double = False
    escaped_by_backtick = False
    i = 0
    while i < len(trimmed):
        char = trimmed[i]

        if not in_single and not in_double:
            if char == "'":
                in_single = True
            elif char == '"':
                in_double = True
            i += 1
            continue

        if in_single:
            if char == "'":
                # Check for doubled single quote ''
                if i + 1 < len(trimmed) and trimmed[i + 1] == "'":
                    i += 2  # skip both
                    continue
                else:
                    in_single = False
            i += 1
            continue

        if in_double:
            if escaped_by_backtick:
                escaped_by_backtick = False
                i += 1
                continue
            if char == "`":
                escaped_by_backtick = True
                i += 1
                continue
            if char == '"':
                # Check for doubled double quote ""
                if i + 1 < len(trimmed) and trimmed[i + 1] == '"':
                    i += 2  # skip both
                    continue
                else:
                    in_double = False
            i += 1
            continue

    if in_single:
        errors.append("Syntax Error: Unclosed single quote (') detected in command.")
    if in_double:
        errors.append("Syntax Error: Unclosed double quote (\") detected in command.")

    # 4. Check for unescaped currency/regex dollar signs inside double quotes
    # Match patterns like "$100" or "$#" or "$/" inside double quotes
    # (PowerShell treats $ followed by numbers as special/empty variables)
    if re.search(r'"[^"]*\$[0-9]+[^"]*"', trimmed):
        errors.append(
            "PowerShell Variable Trap: Detected literal '$<digits>' inside double quotes. "
            "PowerShell will attempt variable interpolation. Use single quotes '...' or escape with '`$'."
        )

    return len(errors) == 0, errors

def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_powershell_cmd.py \"<command-string>\"")
        sys.exit(0)

    command = " ".join(sys.argv[1:])
    valid, errors = validate_command(command)
    if not valid:
        print(f"FAILED: Command validation failed with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("PASSED: Command is safe for PowerShell execution.")
        sys.exit(0)

if __name__ == "__main__":
    main()
