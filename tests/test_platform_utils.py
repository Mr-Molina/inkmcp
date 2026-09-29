# tests/test_platform_utils.py
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from inkmcp.platform_utils import (
    get_operating_system,
    find_inkscape_executable,
    get_inkscape_extensions_dir,
    is_extension_installed,
    is_inkscape_process_running,
    _query_windows_registry,
)


def test_get_operating_system():
    os_name = get_operating_system()
    if sys.platform == "win32":
        assert os_name == "windows"
    elif sys.platform == "darwin":
        assert os_name == "darwin"
    else:
        assert os_name == "linux"


def test_find_inkscape_executable_mock_windows():
    with patch("sys.platform", "win32"), \
         patch("shutil.which") as mock_which, \
         patch("pathlib.Path.is_file") as mock_is_file:
        mock_which.return_value = "C:\\Program Files\\Inkscape\\bin\\inkscape.com"
        mock_is_file.return_value = True

        exe = find_inkscape_executable()
        assert exe is not None
        assert str(exe).endswith("inkscape.com")


def test_find_inkscape_executable_prefers_com_over_exe():
    with patch("sys.platform", "win32"), \
         patch("shutil.which") as mock_which, \
         patch("pathlib.Path.is_file") as mock_is_file:
        # Simulate PATH having inkscape.exe first
        def side_effect(cmd):
            if cmd == "inkscape.com":
                return "C:\\Program Files\\Inkscape\\bin\\inkscape.com"
            return "C:\\Program Files\\Inkscape\\bin\\inkscape.exe"

        mock_which.side_effect = side_effect
        mock_is_file.return_value = True

        exe = find_inkscape_executable()
        assert exe is not None
        assert str(exe).endswith("inkscape.com")


def test_find_inkscape_executable_registry_fallback():
    candidate = Path(r"C:\Program Files\Inkscape\bin\inkscape.com")
    with patch("sys.platform", "win32"), \
         patch.dict(os.environ, {"INKSCAPE_PATH": ""}, clear=False), \
         patch("shutil.which", return_value=None), \
         patch("inkmcp.platform_utils._query_windows_registry", return_value=candidate) as mock_reg, \
         patch.object(Path, "is_file", return_value=True):
        exe = find_inkscape_executable()
        assert exe == candidate
        mock_reg.assert_called_once()


def test_get_inkscape_extensions_dir_windows(tmp_path):
    with patch("sys.platform", "win32"), \
         patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
        ext_dir = get_inkscape_extensions_dir()
        assert ext_dir == tmp_path / "inkscape" / "extensions"


def test_get_inkscape_extensions_dir_linux(tmp_path):
    with patch("sys.platform", "linux"), \
         patch.dict(os.environ, {"XDG_CONFIG_HOME": ""}), \
         patch("pathlib.Path.home", return_value=tmp_path):
        ext_dir = get_inkscape_extensions_dir()
        assert ext_dir == tmp_path / ".config" / "inkscape" / "extensions"


def test_get_inkscape_extensions_dir_linux_custom_xdg(tmp_path):
    custom_xdg = tmp_path / "custom_config"
    with patch("sys.platform", "linux"), \
         patch.dict(os.environ, {"XDG_CONFIG_HOME": str(custom_xdg)}):
        ext_dir = get_inkscape_extensions_dir()
        assert ext_dir == custom_xdg / "inkscape" / "extensions"


def test_is_extension_installed(tmp_path):
    assert is_extension_installed(tmp_path) is False

    (tmp_path / "inkscape_mcp.inx").write_text("<inkscape-extension/>", encoding="utf-8")
    assert is_extension_installed(tmp_path) is False

    (tmp_path / "inkscape_mcp.py").write_text("# python", encoding="utf-8")
    assert is_extension_installed(tmp_path) is True


def test_is_inkscape_process_running_mock():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="inkscape.exe  1234  Console")
        assert is_inkscape_process_running() is True

        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert is_inkscape_process_running() is False


def test_query_windows_registry_strips_quotes(tmp_path):
    fake_exe = tmp_path / "inkscape.exe"
    fake_exe.touch()
    fake_com = tmp_path / "inkscape.com"
    fake_com.touch()

    mock_winreg = MagicMock()
    mock_winreg.HKEY_LOCAL_MACHINE = 1
    mock_winreg.HKEY_CURRENT_USER = 2
    mock_winreg.OpenKey.return_value.__enter__.return_value = MagicMock()
    mock_winreg.QueryValueEx.return_value = (f'"{fake_exe}" ', 1)

    with patch("sys.platform", "win32"), \
         patch.dict(sys.modules, {"winreg": mock_winreg}):
        res = _query_windows_registry()
        assert res == fake_com
