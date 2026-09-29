"""Inkscape execution backends."""
from inkmcp.backends.base import InkscapeBackend
from inkmcp.backends.dbus import DBusBackend
from inkmcp.backends.headless import HeadlessSvgBackend
from inkmcp.backends.windows_cli import WindowsCliBackend

__all__ = ["InkscapeBackend", "DBusBackend", "HeadlessSvgBackend", "WindowsCliBackend"]


