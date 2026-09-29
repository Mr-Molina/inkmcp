import os
from pathlib import Path
from unittest.mock import patch
import pytest

from inkmcp.install_extension import install_extension, check_extension_status, main


def test_install_extension_copies_files(tmp_path):
    repo_root = Path(__file__).parent.parent
    dest_dir = tmp_path / "extensions"
    dest_dir.mkdir(parents=True)

    success = install_extension(repo_root=repo_root, target_dir=dest_dir)
    assert success is True
    assert (dest_dir / "inkscape_mcp.inx").is_file()
    assert (dest_dir / "inkscape_mcp.py").is_file()
    assert (dest_dir / "inkmcp" / "inkmcpops").is_dir()


def test_check_extension_status(tmp_path):
    assert check_extension_status(tmp_path) is False
    (tmp_path / "inkscape_mcp.inx").write_text("<test/>", encoding="utf-8")
    (tmp_path / "inkscape_mcp.py").write_text("# py", encoding="utf-8")
    assert check_extension_status(tmp_path) is True


def test_install_extension_dry_run(tmp_path):
    repo_root = Path(__file__).parent.parent
    dest_dir = tmp_path / "extensions"

    success = install_extension(repo_root=repo_root, target_dir=dest_dir, dry_run=True)
    assert success is True
    assert not dest_dir.exists()


def test_install_extension_force(tmp_path):
    repo_root = Path(__file__).parent.parent
    dest_dir = tmp_path / "extensions"
    dest_dir.mkdir(parents=True)

    # Initial install
    assert install_extension(repo_root=repo_root, target_dir=dest_dir) is True

    # Mutate a file to ensure force overwrites it
    target_inx = dest_dir / "inkscape_mcp.inx"
    target_inx.write_text("MODIFIED", encoding="utf-8")

    # Install without force should not overwrite
    assert install_extension(repo_root=repo_root, target_dir=dest_dir, force=False) is True
    assert target_inx.read_text(encoding="utf-8") == "MODIFIED"

    # Install with force should overwrite
    assert install_extension(repo_root=repo_root, target_dir=dest_dir, force=True) is True
    assert target_inx.read_text(encoding="utf-8") != "MODIFIED"


def test_install_extension_missing_sources(tmp_path):
    empty_root = tmp_path / "empty_repo"
    empty_root.mkdir()
    dest_dir = tmp_path / "extensions"

    assert install_extension(repo_root=empty_root, target_dir=dest_dir) is False


def test_cli_main_check(tmp_path, monkeypatch):
    dest_dir = tmp_path / "extensions"
    dest_dir.mkdir()

    # When not installed -> exits 1
    monkeypatch.setattr("sys.argv", ["install_extension", "--check", "--target-dir", str(dest_dir)])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    # When installed -> exits 0
    (dest_dir / "inkscape_mcp.inx").write_text("<test/>", encoding="utf-8")
    (dest_dir / "inkscape_mcp.py").write_text("# py", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_cli_main_install(tmp_path, monkeypatch):
    dest_dir = tmp_path / "extensions"
    monkeypatch.setattr("sys.argv", ["install_extension", "--target-dir", str(dest_dir)])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert (dest_dir / "inkscape_mcp.inx").is_file()
