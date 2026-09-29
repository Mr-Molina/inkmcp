"""
Extension Installation Utility for inkmcp
Installs or verifies inkmcp extension files in the user's Inkscape extensions directory.
"""

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

# Ensure parent directory is in sys.path when executed directly
_parent_dir = str(Path(__file__).parent.parent.resolve())
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

try:
    from inkmcp.platform_utils import get_inkscape_extensions_dir, is_extension_installed
except ImportError:
    from platform_utils import get_inkscape_extensions_dir, is_extension_installed

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("inkmcp.installer")


def check_extension_status(target_dir: Optional[Path] = None) -> bool:
    """Return True if extension files are present in target directory."""
    return is_extension_installed(target_dir)


def install_extension(
    repo_root: Optional[Path] = None,
    target_dir: Optional[Path] = None,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    """Copy extension files and inkmcp package to Inkscape user extensions directory."""
    root = repo_root or Path(__file__).parent.parent.resolve()
    dest = target_dir or get_inkscape_extensions_dir()

    inx_src = root / "inkscape_mcp.inx"
    py_src = root / "inkscape_mcp.py"
    pkg_src = root / "inkmcp"

    if not inx_src.is_file() or not py_src.is_file():
        logger.error("Missing source files in repository root: %s", root)
        return False

    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    logger.info("Target extensions directory: %s", dest)

    files_to_copy = [
        (inx_src, dest / "inkscape_mcp.inx"),
        (py_src, dest / "inkscape_mcp.py"),
    ]

    for src, dst in files_to_copy:
        if dst.exists() and not force:
            logger.info("Already exists (use --force to overwrite): %s", dst.name)
        else:
            logger.info("Copying %s -> %s", src.name, dst)
            if not dry_run:
                shutil.copy2(src, dst)

    # Copy inkmcp package directory
    dest_pkg = dest / "inkmcp"
    if dest_pkg.exists() and force and not dry_run:
        shutil.rmtree(dest_pkg)

    if not dest_pkg.exists():
        logger.info("Copying package %s -> %s", pkg_src, dest_pkg)
        if not dry_run:
            shutil.copytree(
                pkg_src,
                dest_pkg,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "venv", ".pytest_cache"),
            )
    else:
        logger.info("Package %s already exists", dest_pkg)

    logger.info("Installation completed successfully.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Install inkmcp extension into Inkscape")
    parser.add_argument("--check", action="store_true", help="Check if extension is installed")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without copying")
    parser.add_argument("--force", action="store_true", help="Overwrite existing extension files")
    parser.add_argument("--target-dir", type=str, default="", help="Custom extensions directory")
    args = parser.parse_args()

    custom_dir = Path(args.target_dir) if args.target_dir else None

    if args.check:
        installed = check_extension_status(custom_dir)
        if installed:
            print("Status: inkmcp extension is installed and ready.")
            sys.exit(0)
        else:
            print("Status: inkmcp extension is NOT installed.")
            sys.exit(1)

    ok = install_extension(target_dir=custom_dir, dry_run=args.dry_run, force=args.force)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
