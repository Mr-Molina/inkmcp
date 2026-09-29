"""Inkscape execution backends."""
from inkmcp.backends.base import InkscapeBackend
from inkmcp.backends.headless import HeadlessSvgBackend

__all__ = ["InkscapeBackend", "HeadlessSvgBackend"]
