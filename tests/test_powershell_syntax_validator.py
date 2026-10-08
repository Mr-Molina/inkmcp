import pytest
import sys
from pathlib import Path

# Add .agents to sys.path to import validate_powershell_cmd
agents_dir = Path(__file__).parent.parent / ".agents"
if str(agents_dir) not in sys.path:
    sys.path.insert(0, str(agents_dir))

from validate_powershell_cmd import validate_command

class TestPowerShellSyntaxValidator:
    def test_valid_simple_commands(self):
        valid, errors = validate_command("Get-Process -Name inkscape")
        assert valid is True
        assert len(errors) == 0

        valid, errors = validate_command("python script.py --arg value")
        assert valid is True
        assert len(errors) == 0

    def test_valid_single_quoted_strings(self):
        valid, errors = validate_command("Write-Host 'Literal $100 and \"quotes\" are safe'")
        assert valid is True
        assert len(errors) == 0

    def test_valid_doubled_quotes(self):
        valid, errors = validate_command('Write-Host "He said ""Hello World"""')
        assert valid is True
        assert len(errors) == 0

    def test_valid_backtick_escaped_quotes(self):
        valid, errors = validate_command('Write-Host "He said `"Hello World`""')
        assert valid is True
        assert len(errors) == 0

    def test_detects_multiline_inline_python(self):
        multiline_cmd = 'python -c "import json\nimport os\nprint(1)"'
        valid, errors = validate_command(multiline_cmd)
        assert valid is False
        assert any("Multi-line inline Python" in e for e in errors)

    def test_detects_backslash_quote_in_powershell(self):
        cmd = 'python -c "print(\\"hello\\")"'
        valid, errors = validate_command(cmd)
        assert valid is False
        assert any("PowerShell Quoting Error" in e for e in errors)

    def test_detects_unclosed_single_quote(self):
        cmd = "Get-ChildItem -Path 'C:\\test\\folder"
        valid, errors = validate_command(cmd)
        assert valid is False
        assert any("Unclosed single quote" in e for e in errors)

    def test_detects_unclosed_double_quote(self):
        cmd = 'Get-ChildItem -Path "C:\\test\\folder'
        valid, errors = validate_command(cmd)
        assert valid is False
        assert any("Unclosed double quote" in e for e in errors)

    def test_detects_currency_variable_trap(self):
        cmd = 'Write-Host "Price is $100 dollars"'
        valid, errors = validate_command(cmd)
        assert valid is False
        assert any("PowerShell Variable Trap" in e for e in errors)

    def test_detects_dict_literal_in_python_c(self):
        cmd = "python -c 'import json; d = {\"a\": 1}'"
        valid, errors = validate_command(cmd)
        assert valid is False
        assert any("dictionary or JSON literals" in e for e in errors)
