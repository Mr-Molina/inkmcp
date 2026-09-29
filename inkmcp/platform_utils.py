"""
Platform and Executable Discovery Utilities for inkmcp
Provides cross-platform resolution of Inkscape executables, extension directories,
and process states.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("InkscapeMCP.Platform")


def get_operating_system() -> str:
    """Return normalized operating system name: 'windows', 'linux', 'darwin', or 'unknown'."""
    if sys.platform in ("win32", "cygwin"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def _query_windows_registry() -> Optional[Path]:
    """Query Windows registry for Inkscape installation path."""
    if sys.platform != "win32":
        return None

    try:
        import winreg

        # 1. Check App Paths
        for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(
                    hkey,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\inkscape.exe",
                ) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val:
                        val = val.strip('" ')
                        exe_path = Path(val)
                        com_path = exe_path.with_name("inkscape.com")
                        if com_path.is_file():
                            return com_path
                        if exe_path.is_file():
                            return exe_path
            except OSError:
                pass

        # 2. Check Inkscape specific keys
        for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hkey, r"SOFTWARE\Inkscape\Inkscape") as key:
                    install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
                    if install_dir:
                        install_dir = install_dir.strip('" ')
                        com_candidate = Path(install_dir) / "bin" / "inkscape.com"
                        if com_candidate.is_file():
                            return com_candidate
                        exe_candidate = Path(install_dir) / "bin" / "inkscape.exe"
                        if exe_candidate.is_file():
                            return exe_candidate
            except OSError:
                pass
    except Exception as e:
        logger.debug("Registry query failed: %s", e)

    return None


def find_inkscape_executable() -> Optional[Path]:
    """
    Find the Inkscape executable on the host machine.
    On Windows, strictly prefers 'inkscape.com' over 'inkscape.exe' for console/action support.
    """
    os_name = get_operating_system()

    if os_name == "windows":
        # 1. Check environment variable override
        env_override = os.environ.get("INKSCAPE_PATH")
        if env_override:
            p = Path(env_override)
            if p.is_file():
                return p

        # 2. Check shutil.which for inkscape.com
        com_which = shutil.which("inkscape.com")
        if com_which:
            return Path(com_which)

        # 3. Check Windows Registry
        reg_path = _query_windows_registry()
        if reg_path and reg_path.is_file():
            return reg_path

        # 4. Check standard installation directories
        candidate_paths = [
            Path(r"C:\Program Files\Inkscape\bin\inkscape.com"),
            Path(r"C:\Program Files\Inkscape\bin\inkscape.exe"),
            Path(r"C:\Program Files (x86)\Inkscape\bin\inkscape.com"),
            Path(r"C:\Program Files (x86)\Inkscape\bin\inkscape.exe"),
        ]
        for candidate in candidate_paths:
            if candidate.is_file():
                return candidate

        # 5. Fallback to inkscape in PATH
        general_which = shutil.which("inkscape")
        if general_which:
            return Path(general_which)

        return None

    # Linux / macOS / Unix
    env_override = os.environ.get("INKSCAPE_PATH")
    if env_override and Path(env_override).is_file():
        return Path(env_override)

    which_path = shutil.which("inkscape")
    if which_path:
        return Path(which_path)

    # Standard macOS path
    if os_name == "darwin":
        mac_app = Path("/Applications/Inkscape.app/Contents/MacOS/inkscape")
        if mac_app.is_file():
            return mac_app

    return None


def get_inkscape_extensions_dir() -> Path:
    """Return the user extensions directory for the current platform."""
    os_name = get_operating_system()

    if os_name == "windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "inkscape" / "extensions"
        return Path.home() / "AppData" / "Roaming" / "inkscape" / "extensions"

    if os_name == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "org.inkscape.Inkscape"
            / "config"
            / "inkscape"
            / "extensions"
        )

    # Linux / XDG
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "inkscape" / "extensions"
    return Path.home() / ".config" / "inkscape" / "extensions"


def is_extension_installed(ext_dir: Optional[Path] = None) -> bool:
    """Check if inkmcp extension files exist in target extensions directory."""
    target_dir = ext_dir if ext_dir is not None else get_inkscape_extensions_dir()
    inx_file = target_dir / "inkscape_mcp.inx"
    py_file = target_dir / "inkscape_mcp.py"
    return inx_file.is_file() and py_file.is_file()


def is_inkscape_process_running() -> bool:
    """Check if an Inkscape process is running in the user session."""
    os_name = get_operating_system()
    try:
        if os_name == "windows":
            cmd = ["tasklist", "/FI", "IMAGENAME eq inkscape.exe", "/FO", "CSV", "/NH"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return "inkscape.exe" in result.stdout.lower()
        else:
            cmd = ["pgrep", "-f", "inkscape"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.returncode == 0
    except Exception as e:
        logger.debug("Failed to check running processes: %s", e)
        return False
