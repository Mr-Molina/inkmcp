from pathlib import Path

REQUIRED_VECTORIZER_DEPS = [
    "numpy>=1.24.0",
    "opencv-python-headless>=4.8.0",
    "Pillow>=9.0.0",
    "scipy>=1.10.0",
    "scikit-learn>=1.2.0",
    "shapely>=2.0.0",
    "networkx>=3.0",
    "vtracer>=0.6.0",
    "scour>=0.37.0",
]


def test_manifest_lxml_bounds():
    req_path = Path("inkmcp/requirements.txt")
    content = req_path.read_text(encoding="utf-8")
    assert "lxml>=5.3.0,<6.0.0" in content, "lxml must be constrained to >=5.3.0,<6.0.0 in requirements.txt"
    for dep in REQUIRED_VECTORIZER_DEPS:
        assert dep in content, f"Missing vectorizer dependency {dep} in requirements.txt"


def test_pyproject_lxml_and_build_bounds():
    pyproject_path = Path("pyproject.toml")
    content = pyproject_path.read_text(encoding="utf-8")
    assert "lxml>=5.3.0,<6.0.0" in content, "pyproject.toml must declare lxml>=5.3.0,<6.0.0"
    assert "setuptools>=70.0.0,<90.0.0" in content, "pyproject.toml must declare setuptools>=70.0.0,<90.0.0"
    assert "pytest>=9.0.3,<10.0.0" in content, "pyproject.toml must declare pytest>=9.0.3,<10.0.0"
    for dep in REQUIRED_VECTORIZER_DEPS:
        assert dep in content, f"Missing vectorizer dependency {dep} in pyproject.toml"
