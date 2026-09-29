"""Inkscape execution backends."""
from inkmcp.backends.base import InkscapeBackend
from inkmcp.backends.headless import HeadlessSvgBackend
from inkmcp.backends.windows_cli import WindowsCliBackend

__all__ = ["InkscapeBackend", "HeadlessSvgBackend", "WindowsCliBackend"]

