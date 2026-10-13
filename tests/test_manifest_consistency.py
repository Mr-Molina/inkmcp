from pathlib import Path

def test_manifest_lxml_bounds():
    req_path = Path("inkmcp/requirements.txt")
    content = req_path.read_text(encoding="utf-8")
    assert "lxml>=6.1.0,<7.0.0" in content, "lxml must be constrained to >=6.1.0,<7.0.0 in requirements.txt"

def test_pyproject_lxml_and_build_bounds():
    pyproject_path = Path("pyproject.toml")
    content = pyproject_path.read_text(encoding="utf-8")
    assert 'lxml>=6.1.0,<7.0.0' in content, "pyproject.toml must declare lxml>=6.1.0,<7.0.0"
    assert 'setuptools>=70.0.0,<90.0.0' in content, "pyproject.toml must declare setuptools>=70.0.0,<90.0.0"
    assert 'pytest>=9.0.3,<10.0.0' in content, "pyproject.toml must declare pytest>=9.0.3,<10.0.0"
