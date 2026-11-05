from pathlib import Path
import stat
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


def test_install_extension_missing_pkg_dir(tmp_path):
    fake_root = tmp_path / "fake_repo"
    fake_root.mkdir()
    (fake_root / "inkscape_mcp.inx").write_text("<test/>", encoding="utf-8")
    (fake_root / "inkscape_mcp.py").write_text("# py", encoding="utf-8")
    dest_dir = tmp_path / "extensions"

    assert install_extension(repo_root=fake_root, target_dir=dest_dir) is False


def test_install_extension_paths_with_spaces_and_unicode(tmp_path):
    repo_root = Path(__file__).parent.parent
    dest_dir = tmp_path / "Inkscape AppData 🎨 with spaces"
    dest_dir.mkdir(parents=True)

    success = install_extension(repo_root=repo_root, target_dir=dest_dir)
    assert success is True
    assert (dest_dir / "inkscape_mcp.inx").is_file()
    assert (dest_dir / "inkscape_mcp.py").is_file()
    assert (dest_dir / "inkmcp" / "inkmcpops").is_dir()


def test_install_extension_destination_not_writable(tmp_path, monkeypatch):
    repo_root = Path(__file__).parent.parent
    dest_dir = tmp_path / "unwritable_extensions"
    dest_dir.mkdir(parents=True)

    monkeypatch.setattr("inkmcp.install_extension._is_writable", lambda p: False)
    success = install_extension(repo_root=repo_root, target_dir=dest_dir)
    assert success is False


def test_install_extension_destination_out_of_bounds(tmp_path, monkeypatch):
    repo_root = Path(__file__).parent.parent
    dest_dir = tmp_path / "extensions"
    dest_dir.mkdir(parents=True)

    monkeypatch.setattr(Path, "is_relative_to", lambda self, other: False)
    success = install_extension(repo_root=repo_root, target_dir=dest_dir)
    assert success is False


def test_install_extension_handles_os_error(tmp_path, monkeypatch):
    repo_root = Path(__file__).parent.parent
    dest_dir = tmp_path / "extensions"
    dest_dir.mkdir(parents=True)

    def mock_copy2(src, dst):
        raise OSError("Disk full or permission denied")

    monkeypatch.setattr("shutil.copy2", mock_copy2)
    success = install_extension(repo_root=repo_root, target_dir=dest_dir)
    assert success is False


def test_install_extension_force_cleans_readonly_files(tmp_path):
    repo_root = Path(__file__).parent.parent
    dest_dir = tmp_path / "extensions"
    dest_dir.mkdir(parents=True)

    assert install_extension(repo_root=repo_root, target_dir=dest_dir) is True

    # Mark a file inside dest / inkmcp as read-only
    target_py = dest_dir / "inkmcp" / "__init__.py"
    target_py.chmod(stat.S_IREAD)

    # Force re-install should succeed and remove read-only files without crashing
    assert install_extension(repo_root=repo_root, target_dir=dest_dir, force=True) is True


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
