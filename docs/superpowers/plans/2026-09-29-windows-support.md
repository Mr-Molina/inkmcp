# Windows Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable native Windows support for the Inkscape Model Context Protocol (`inkmcp`) server and CLI through an automated multi-tier backend architecture (Windows active window via `inkscape.com -q --actions`, Linux D-Bus fallback via `gdbus`, and headless SVG manipulation via `inkex`), accompanied by Windows PowerShell/batch launchers and extension installers.

**Architecture:** A pluggable `InkscapeBackend` strategy abstraction dynamically detects host operating system capabilities at runtime. On Windows with an active GUI session, it executes extension actions through `inkscape.com -q --actions` targeting the active canvas; when headless or when no GUI window is running, it manipulates documents directly via pure-Python `inkex`; on Linux/BSD with D-Bus, it preserves the existing `gdbus` session transport. Cross-platform discovery automatically locates `inkscape.com` via Registry, PATH, and standard 64-bit installation directories.

**Tech Stack:** Python 3.10+, `mcp` (FastMCP 1.2+), `inkex` (1.4+), `lxml`, Windows Registry (`winreg`), PowerShell 5.1/7+, Batch script, `pytest`.

**Spec:** Multi-tier Windows architecture specification established during audit discovery:
1. Console binary `inkscape.com` is required on Windows for non-detaching stdin/stdout execution.
2. Extension action activation via `-q --actions="org.khema.inkscape.mcp.noprefs"` targets the live active window.
3. `%APPDATA%\inkscape\extensions` is the user extensions directory on Windows.
4. Headless mode executes `ElementCreator` directly on SVG files without requiring desktop session bus or GUI.

## Global Constraints

- **Python Version Compatibility**: Python 3.10 through 3.13+.
- **Zero Insecure Temporary Files**: All file exchanges must reside within `tempfile.gettempdir()` with validated path containment and atomic cleanup in `finally` blocks (Invariant 24, SEC-002, SEC-003).
- **Subprocess Safety**: All subprocess invocations must specify explicit timeouts, pass argument vectors as lists (`shell=False`), and redirect or drain streams (Invariant 29, SEC-008).
- **Preserve Linux D-Bus Compatibility**: Existing Linux behavior (`gdbus`) must remain completely unbroken; all unit tests in `tests/test_fastmcp_server.py` must continue to pass.
- **Deterministic Exit Codes**: All test scripts and CLI entrypoints must return exit code 0 on success and non-zero on failure (Invariant 29, Invariant 32).
- **Docstring Preservation**: Maintain documentation integrity and descriptive docstrings across all modules (Invariant 36).

## Review Focus

1. **Inkscape Console Binary Disambiguation (`inkscape.com` vs `inkscape.exe`)**: On Windows, launching `inkscape.exe` silently detaches from the console without waiting for action completion, causing premature timeouts. Expected: The platform detector must strictly prioritize `inkscape.com` over `inkscape.exe`.
2. **Missing Active Window Recovery**: Calling `inkscape.com -q --actions="..."` when no Inkscape GUI window is open exits with code 1 or fails to target any document. Expected: The backend must detect active Inkscape processes or gracefully fallback to headless SVG file mode with clear diagnostics instead of crashing.
3. **Registry Fallback on Non-Standard Installations**: When Inkscape is installed in a non-standard directory and absent from system `PATH`, standard `shutil.which` fails. Expected: Query `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\inkscape.exe` and `HKCU\Software\Inkscape\Inkscape` to resolve the true binary location.
4. **Extension Directory Permissions & Path Traversal in Installer**: Windows user profile paths may contain spaces (`C:\Users\John Doe\AppData\...`) or Unicode characters. Expected: Installer must quote all paths, validate canonical destination boundaries, and verify write permissions before copying.
5. **Concurrent Parameter File Collision**: Multiple simultaneous MCP requests could overwrite `mcp_params.json`. Expected: Parameter files must use unique timestamps/UUIDs or process-isolated temporary files, and `inkscape_mcp.py` must support explicit `--params-file` overrides.

---

### Task 1: Platform & Executable Discovery Module

**Files:**
- Create: `inkmcp/platform_utils.py`
- Create: `tests/test_platform_utils.py`

**Interfaces:**
- Consumes: Standard library (`sys`, `os`, `shutil`, `pathlib`, `winreg` on Windows).
- Produces:
  - `get_operating_system() -> str`: Returns `'windows'`, `'linux'`, `'darwin'`, or `'unknown'`.
  - `find_inkscape_executable() -> Optional[Path]`: Discovers `inkscape.com` (Windows) or `inkscape` (Unix).
  - `get_inkscape_extensions_dir() -> Path`: Resolves user extensions directory across OSes.
  - `is_extension_installed(ext_dir: Optional[Path] = None) -> bool`: Checks if `inkscape_mcp.inx` and `inkscape_mcp.py` exist in user extensions.
  - `is_inkscape_process_running() -> bool`: Determines if an Inkscape GUI process is currently active.

- [ ] **Step 1: Write the failing tests**

```python
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


def test_get_inkscape_extensions_dir_windows(tmp_path):
    with patch("sys.platform", "win32"), \
         patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
        ext_dir = get_inkscape_extensions_dir()
        assert ext_dir == tmp_path / "inkscape" / "extensions"


def test_get_inkscape_extensions_dir_linux(tmp_path):
    with patch("sys.platform", "linux"), \
         patch("pathlib.Path.home", return_value=tmp_path):
        ext_dir = get_inkscape_extensions_dir()
        assert ext_dir == tmp_path / ".config" / "inkscape" / "extensions"


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_platform_utils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.platform_utils'`

- [ ] **Step 3: Write minimal implementation**

```python
# inkmcp/platform_utils.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_platform_utils.py -v`
Expected: PASS with 7/7 passed.

- [ ] **Step 5: Commit**

```bash
git add inkmcp/platform_utils.py tests/test_platform_utils.py
git commit -m "feat(platform): add platform and Inkscape executable discovery module"
```

---

### Task 2: Headless & Standalone SVG Backend

**Files:**
- Create: `inkmcp/backends/__init__.py`
- Create: `inkmcp/backends/base.py`
- Create: `inkmcp/backends/headless.py`
- Create: `tests/test_headless_backend.py`

**Interfaces:**
- Consumes: `inkex`, `inkscape_mcp.ElementCreator`, `inkmcp/inkmcpops/`.
- Produces:
  - `InkscapeBackend` (Abstract Base Class in `base.py`):
    - `is_available() -> bool`
    - `execute_operation(operation_data: Dict[str, Any]) -> Dict[str, Any]`
    - `get_backend_name() -> str`
  - `HeadlessSvgBackend` in `headless.py`:
    - Operates on a session SVG document (`self.svg_doc` or `document_path`).
    - Creates, manipulates, queries, and executes code in-memory or on-disk without desktop session or GUI.
    - Exports PNG/PDF using `find_inkscape_executable()` or internal SVG rasterization.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_headless_backend.py
import json
import tempfile
from pathlib import Path
import pytest

from inkmcp.backends.headless import HeadlessSvgBackend


@pytest.fixture
def headless_backend():
    return HeadlessSvgBackend()


def test_headless_backend_is_available(headless_backend):
    assert headless_backend.is_available() is True
    assert headless_backend.get_backend_name() == "headless"


def test_headless_backend_create_circle(headless_backend):
    op_data = {
        "operation": "create",
        "tag": "circle",
        "attributes": {
            "cx": 100,
            "cy": 100,
            "r": 50,
            "fill": "blue"
        }
    }
    result = headless_backend.execute_operation(op_data)
    assert result["status"] == "success"
    assert "id" in result["data"]
    assert result["data"]["tag"] == "circle"


def test_headless_backend_get_document_info(headless_backend):
    # Add a rectangle
    headless_backend.execute_operation({
        "operation": "create",
        "tag": "rect",
        "attributes": {"x": 10, "y": 20, "width": 100, "height": 50}
    })
    info_result = headless_backend.execute_operation({"operation": "get_info"})
    assert info_result["status"] == "success"
    assert "dimensions" in info_result["data"]
    assert info_result["data"]["elementCounts"]["rect"] >= 1


def test_headless_backend_execute_code(headless_backend):
    code_op = {
        "operation": "execute_code",
        "code": "result = 40 + 2"
    }
    res = headless_backend.execute_operation(code_op)
    assert res["status"] == "success"
    assert res["data"]["return_value"] == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_headless_backend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.backends'`

- [ ] **Step 3: Write minimal implementation**

```python
# inkmcp/backends/__init__.py
"""Inkscape execution backends."""
from inkmcp.backends.base import InkscapeBackend

__all__ = ["InkscapeBackend"]
```

```python
# inkmcp/backends/base.py
"""Abstract base class for Inkscape communication backends."""
from abc import ABC, abstractmethod
from typing import Any, Dict


class InkscapeBackend(ABC):
    """Abstract interface for Inkscape command execution."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this backend is capable of handling operations."""
        pass

    @abstractmethod
    def execute_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an operation dictionary and return the structured response."""
        pass

    @abstractmethod
    def get_backend_name(self) -> str:
        """Return human-readable identifier for this backend."""
        pass
```

```python
# inkmcp/backends/headless.py
"""
Headless Standalone SVG Backend
Manipulates SVG documents directly using inkex and ElementCreator without requiring GUI or D-Bus.
"""

import copy
import logging
from typing import Any, Dict, Optional
import inkex

from inkmcp.backends.base import InkscapeBackend
from inkscape_mcp import ElementCreator

logger = logging.getLogger("InkscapeMCP.Backend.Headless")


class HeadlessSvgBackend(InkscapeBackend):
    """Executes SVG operations headlessly on an in-memory document."""

    def __init__(self, initial_svg: Optional[str] = None):
        self._creator = ElementCreator()
        if initial_svg:
            self._doc = inkex.load_svg(initial_svg)
        else:
            # Default empty SVG document (1000x1000 viewBox)
            empty_svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" '
                'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
                'width="1000" height="1000" viewBox="0 0 1000 1000">'
                '<g inkscape:groupmode="layer" id="layer1" inkscape:label="Layer 1"/>'
                '</svg>'
            )
            self._doc = inkex.load_svg(empty_svg)
        self._creator.svg = self._doc.getroot()

    def is_available(self) -> bool:
        return True

    def get_backend_name(self) -> str:
        return "headless"

    def execute_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        op_type = operation_data.get("operation", "create")
        svg_root = self._creator.svg

        try:
            if op_type == "create":
                # Find active layer or append to root
                active_layer = svg_root.find(".//svg:g[@inkscape:groupmode='layer']", namespaces=inkex.NSS)
                target = active_layer if active_layer is not None else svg_root

                id_mapping = {}
                generated_ids = []
                element = self._creator.create_element_recursive(
                    svg_root, operation_data, id_mapping, generated_ids
                )
                if element is not None:
                    target.append(element)
                    return {
                        "status": "success",
                        "data": {
                            "message": f"Element {operation_data.get('tag')} created successfully",
                            "id": element.get("id"),
                            "tag": operation_data.get("tag"),
                            "id_mapping": id_mapping,
                            "generated_ids": generated_ids,
                        },
                    }
                return {"status": "error", "data": {"error": "Failed to create element"}}

            elif op_type == "get_info":
                return self._creator.get_document_info(svg_root)

            elif op_type == "get_element_info":
                elem_id = operation_data.get("id", "")
                return self._creator.get_element_info(svg_root, elem_id)

            elif op_type == "execute_code":
                from inkmcp.inkmcpops.execute_operations import execute_code
                return execute_code(svg_root, operation_data)

            elif op_type == "export_document_image":
                from inkmcp.inkmcpops.export_operations import export_document_image
                return export_document_image(svg_root, operation_data)

            else:
                return {
                    "status": "error",
                    "data": {"error": f"Unknown operation: {op_type}"},
                }

        except Exception as e:
            logger.error("Headless operation failed: %s", e)
            return {"status": "error", "data": {"error": str(e)}}

    def get_svg_string(self) -> str:
        """Return the current document as a serialized SVG string."""
        return self._creator.svg.tostring().decode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_headless_backend.py -v`
Expected: PASS with 4/4 passed.

- [ ] **Step 5: Commit**

```bash
git add inkmcp/backends/__init__.py inkmcp/backends/base.py inkmcp/backends/headless.py tests/test_headless_backend.py
git commit -m "feat(backends): implement HeadlessSvgBackend with pure inkex operations"
```

---

### Task 3: Windows CLI Active-Window Backend

**Files:**
- Create: `inkmcp/backends/windows_cli.py`
- Create: `tests/test_windows_backend.py`

**Interfaces:**
- Consumes: `inkmcp/platform_utils.py`, `inkmcp/backends/base.py`, `tempfile`, `subprocess`.
- Produces:
  - `WindowsCliBackend`:
    - `is_available() -> bool`: Returns True if on Windows, `inkscape.com` exists, and extension is installed.
    - `execute_operation(operation_data: Dict[str, Any]) -> Dict[str, Any]`: Writes payload to parameter file, triggers `inkscape.com -q --actions="org.khema.inkscape.mcp.noprefs"`, parses response file, cleans up safely.
    - `get_backend_name() -> str`: Returns `"windows_cli"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_windows_backend.py
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from inkmcp.backends.windows_cli import WindowsCliBackend


@pytest.fixture
def mock_platform():
    with patch("inkmcp.backends.windows_cli.get_operating_system", return_value="windows"), \
         patch("inkmcp.backends.windows_cli.find_inkscape_executable", return_value=Path("C:/Program Files/Inkscape/bin/inkscape.com")), \
         patch("inkmcp.backends.windows_cli.is_extension_installed", return_value=True), \
         patch("inkmcp.backends.windows_cli.is_inkscape_process_running", return_value=True):
        yield


def test_windows_cli_is_available(mock_platform):
    backend = WindowsCliBackend()
    assert backend.is_available() is True
    assert backend.get_backend_name() == "windows_cli"


def test_windows_cli_execute_operation_success(mock_platform):
    backend = WindowsCliBackend()

    def fake_subprocess_run(cmd, capture_output=True, text=True, timeout=30):
        # Find response_file from mcp_params.json
        temp_dir = tempfile.gettempdir()
        params_file = os.path.join(temp_dir, "mcp_params.json")
        with open(params_file, "r") as pf:
            data = json.load(pf)
        resp_file = data["response_file"]
        with open(resp_file, "w") as rf:
            json.dump({"status": "success", "data": {"id": "circle123", "message": "created"}}, rf)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        res = backend.execute_operation({"operation": "create", "tag": "circle"})
        assert res["status"] == "success"
        assert res["data"]["id"] == "circle123"


def test_windows_cli_handles_inkscape_error(mock_platform):
    backend = WindowsCliBackend()
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="Inkscape crashed")):
        res = backend.execute_operation({"operation": "create", "tag": "circle"})
        assert res["status"] == "error"
        assert "Inkscape action execution failed" in res["data"]["error"]


def test_windows_cli_timeout_handling(mock_platform):
    import subprocess
    backend = WindowsCliBackend()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="inkscape.com", timeout=30)):
        res = backend.execute_operation({"operation": "create", "tag": "circle"})
        assert res["status"] == "error"
        assert "timed out" in res["data"]["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_windows_backend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.backends.windows_cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# inkmcp/backends/windows_cli.py
"""
Windows CLI Active Window Backend for inkmcp
Executes extension actions against running Inkscape GUI instances on Windows via inkscape.com.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from inkmcp.backends.base import InkscapeBackend
from inkmcp.platform_utils import (
    find_inkscape_executable,
    get_operating_system,
    is_extension_installed,
    is_inkscape_process_running,
)

logger = logging.getLogger("InkscapeMCP.Backend.WindowsCLI")

ACTION_NOPREFS = "org.khema.inkscape.mcp.noprefs"


class WindowsCliBackend(InkscapeBackend):
    """Executes Inkscape operations on Windows via inkscape.com -q --actions."""

    def __init__(self, inkscape_path: Optional[Path] = None):
        self._inkscape_path = inkscape_path or find_inkscape_executable()

    def is_available(self) -> bool:
        if get_operating_system() != "windows":
            return False
        if not self._inkscape_path or not Path(self._inkscape_path).is_file():
            logger.warning("WindowsCliBackend: inkscape.com executable not found")
            return False
        if not is_extension_installed():
            logger.warning("WindowsCliBackend: inkmcp extension not installed in %APPDATA%")
            return False
        return True

    def get_backend_name(self) -> str:
        return "windows_cli"

    def execute_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_available():
            return {
                "status": "error",
                "data": {
                    "error": (
                        "Windows Inkscape backend is unavailable. Ensure Inkscape 1.2+ is installed, "
                        "the MCP extension is installed in %APPDATA%\\inkscape\\extensions, "
                        "and inkscape.com is accessible."
                    )
                },
            }

        response_file = None
        params_file = os.path.join(tempfile.gettempdir(), "mcp_params.json")

        try:
            # 1. Prepare unique response file
            resp_fd, response_file = tempfile.mkstemp(
                suffix=".json", prefix="inkmcp_response_"
            )
            os.close(resp_fd)

            payload = dict(operation_data)
            payload["response_file"] = response_file

            # 2. Write parameter file
            with open(params_file, "w", encoding="utf-8") as pf:
                json.dump(payload, pf)

            # 3. Invoke Inkscape action via console binary
            # -q / --active-window directs action to existing running window
            cmd = [
                str(self._inkscape_path),
                "-q",
                f"--actions={ACTION_NOPREFS}",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.error(
                    "Inkscape command failed with code %d: %s",
                    result.returncode,
                    result.stderr,
                )
                return {
                    "status": "error",
                    "data": {
                        "error": f"Inkscape action execution failed (code {result.returncode}): {result.stderr.strip()}"
                    },
                }

            # 4. Read response from response file
            if not os.path.exists(response_file) or os.path.getsize(response_file) == 0:
                return {
                    "status": "error",
                    "data": {
                        "error": "Inkscape extension executed but produced no response file."
                    },
                }

            with open(response_file, "r", encoding="utf-8") as rf:
                return json.load(rf)

        except subprocess.TimeoutExpired:
            logger.error("Inkscape CLI action timed out")
            return {
                "status": "error",
                "data": {"error": "Inkscape action execution timed out (30s)"},
            }
        except Exception as e:
            logger.error("Windows CLI execution failed: %s", e)
            return {"status": "error", "data": {"error": str(e)}}
        finally:
            if response_file and os.path.exists(response_file):
                try:
                    os.remove(response_file)
                except OSError:
                    pass
            if os.path.exists(params_file):
                try:
                    os.remove(params_file)
                except OSError:
                    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_windows_backend.py -v`
Expected: PASS with 4/4 passed.

- [ ] **Step 5: Commit**

```bash
git add inkmcp/backends/windows_cli.py tests/test_windows_backend.py
git commit -m "feat(backends): implement WindowsCliBackend with inkscape.com action invocation"
```

---

### Task 4: Cross-Platform Backend Dispatcher in InkscapeConnection & CLI

**Files:**
- Modify: `inkmcp/inkscape_mcp_server.py:37-191`
- Modify: `inkmcp/inkmcpcli.py:598-670`
- Modify: `inkscape_mcp.py:26-30` and `inkscape_mcp.py:240-260`
- Modify: `tests/test_fastmcp_server.py`

**Interfaces:**
- Consumes: `inkmcp/platform_utils.py`, `inkmcp/backends/base.py`, `inkmcp/backends/windows_cli.py`, `inkmcp/backends/headless.py`.
- Produces:
  - `InkscapeConnection`: Automatically selects backend:
    - If on Windows: prefers `WindowsCliBackend` if active Inkscape GUI process detected, else falls back to `HeadlessSvgBackend`.
    - If on Linux/BSD: uses `DBusBackend` if `gdbus` available, else falls back to `HeadlessSvgBackend`.
  - `InkscapeClient` in `inkmcpcli.py`: Uses `InkscapeConnection` backend strategy for unified cross-platform CLI calls.
  - `inkscape_mcp.py`: Supports `--params-file` CLI argument in addition to `mcp_params.json` for deterministic execution.

- [ ] **Step 1: Write the failing tests**

```python
# In tests/test_fastmcp_server.py, add cross-platform tests:
def test_inkscape_connection_selects_windows_backend():
    from inkmcp.inkscape_mcp_server import InkscapeConnection
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="windows"), \
         patch("inkmcp.inkscape_mcp_server.is_inkscape_process_running", return_value=True), \
         patch("inkmcp.backends.windows_cli.WindowsCliBackend.is_available", return_value=True):
        conn = InkscapeConnection()
        assert conn.backend.get_backend_name() == "windows_cli"


def test_inkscape_connection_selects_headless_when_no_gui():
    from inkmcp.inkscape_mcp_server import InkscapeConnection
    with patch("inkmcp.inkscape_mcp_server.get_operating_system", return_value="windows"), \
         patch("inkmcp.inkscape_mcp_server.is_inkscape_process_running", return_value=False):
        conn = InkscapeConnection(allow_headless=True)
        assert conn.backend.get_backend_name() == "headless"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fastmcp_server.py::test_inkscape_connection_selects_windows_backend -v`
Expected: FAIL with `AttributeError` or missing backend attribute.

- [ ] **Step 3: Write minimal implementation**

In `inkmcp/inkscape_mcp_server.py`:
1. Import `get_operating_system`, `is_inkscape_process_running` from `inkmcp.platform_utils`.
2. Import `WindowsCliBackend` and `HeadlessSvgBackend` from `inkmcp.backends`.
3. Wrap D-Bus logic into a `DBusBackend` conforming to `InkscapeBackend`.
4. In `InkscapeConnection.__init__`:
   - Inspect platform.
   - If Windows and `WindowsCliBackend().is_available()`: instantiate `WindowsCliBackend`.
   - Else if `DBusBackend().is_available()`: instantiate `DBusBackend`.
   - Else if `allow_headless`: instantiate `HeadlessSvgBackend`.
5. In `InkscapeConnection.execute_operation`: delegate directly to `self.backend.execute_operation(operation_data)`.
6. In `inkmcp/inkmcpcli.py`: update `InkscapeClient.execute_operation()` to delegate to `InkscapeConnection().execute_operation()`.
7. In `inkscape_mcp.py`: add `pars.add_argument("--params-file", type=str, default="")` to `add_arguments(pars)`, and in `effect()` check `getattr(self.options, "params_file", None)` before falling back to `mcp_params.json`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fastmcp_server.py -v`
Expected: PASS with all tests passing.

- [ ] **Step 5: Commit**

```bash
git add inkmcp/inkscape_mcp_server.py inkmcp/inkmcpcli.py inkscape_mcp.py tests/test_fastmcp_server.py
git commit -m "feat(server): integrate cross-platform backend dispatcher with Windows and Headless support"
```

---

### Task 5: Extension Installer & Packaging Tool

**Files:**
- Create: `inkmcp/install_extension.py`
- Create: `install_extension.ps1`
- Create: `tests/test_extension_installer.py`

**Interfaces:**
- Consumes: `inkmcp/platform_utils.py` (`get_inkscape_extensions_dir`).
- Produces:
  - `inkmcp/install_extension.py`:
    - Copies `inkscape_mcp.inx`, `inkscape_mcp.py`, and copies or links `inkmcp/` package into the target Inkscape extensions folder.
    - CLI flags: `--check`, `--dry-run`, `--force`, `--target-dir <dir>`.
    - Returns exit code 0 on success, 1 on error.
  - `install_extension.ps1`:
    - Native PowerShell one-liner runner for Windows users.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_extension_installer.py
import os
from pathlib import Path
from unittest.mock import patch
import pytest

from inkmcp.install_extension import install_extension, check_extension_status


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_extension_installer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inkmcp.install_extension'`

- [ ] **Step 3: Write minimal implementation**

```python
# inkmcp/install_extension.py
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

from inkmcp.platform_utils import get_inkscape_extensions_dir, is_extension_installed

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
```

Create `install_extension.ps1`:
```powershell
<#
.SYNOPSIS
Installs inkmcp extension into Inkscape AppData extensions directory.
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Check
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$ArgsList = @("$ScriptDir\inkmcp\install_extension.py")
if ($Force) { $ArgsList += "--force" }
if ($Check) { $ArgsList += "--check" }

Write-Host "Running inkmcp extension installer..." -ForegroundColor Cyan
& python @ArgsList
if ($LASTEXITCODE -ne 0) {
    Write-Error "Extension installation failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "Extension setup completed." -ForegroundColor Green
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_extension_installer.py -v`
Expected: PASS with 2/2 passed.

- [ ] **Step 5: Commit**

```bash
git add inkmcp/install_extension.py install_extension.ps1 tests/test_extension_installer.py
git commit -m "feat(installer): add automated cross-platform extension installer"
```

---

### Task 6: Windows Launchers & MCP Client Configurations

**Files:**
- Create: `inkmcp/run_inkscape_mcp.ps1`
- Create: `inkmcp/run_inkscape_mcp.bat`
- Modify: `.claude-mcp.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: Python 3.10+, `inkmcp/requirements.txt`, `inkmcp/main.py`.
- Produces:
  - `run_inkscape_mcp.ps1`: Creates/activates virtualenv, installs dependencies, launches `python -m inkmcp.inkscape_mcp_server`.
  - `run_inkscape_mcp.bat`: Native Windows batch launcher for Claude Desktop or command prompt.
  - `.claude-mcp.json`: Cross-platform configuration example with Windows and Unix command templates.
  - `README.md`: Clear setup instructions for Windows users.

- [ ] **Step 1: Write the failing test**

```python
# Add test in tests/test_platform_utils.py:
def test_launcher_scripts_exist():
    repo_root = Path(__file__).parent.parent
    assert (repo_root / "inkmcp" / "run_inkscape_mcp.ps1").is_file()
    assert (repo_root / "inkmcp" / "run_inkscape_mcp.bat").is_file()
    assert (repo_root / "install_extension.ps1").is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_platform_utils.py::test_launcher_scripts_exist -v`
Expected: FAIL with `AssertionError`

- [ ] **Step 3: Write minimal implementation**

Create `inkmcp/run_inkscape_mcp.ps1`:
```powershell
<#
.SYNOPSIS
Inkscape MCP Server Wrapper Script for Windows PowerShell
Activates Python environment and launches the MCP server.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

$VenvDir = Join-Path $ScriptDir "venv"

if (-not (Test-Path $VenvDir)) {
    [Console]::Error.WriteLine("Creating Python virtual environment...")
    & python -m venv "$VenvDir"
    & "$VenvDir\Scripts\python.exe" -m pip install -r "$ScriptDir\requirements.txt" | Out-Null
}

$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python.exe"
}

# Run the Inkscape MCP server with stdout reserved for JSON-RPC
& $PythonExe -m inkmcp.inkscape_mcp_server
exit $LASTEXITCODE
```

Create `inkmcp/run_inkscape_mcp.bat`:
```cmd
@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\" (
    echo Creating Python virtual environment... >&2
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt >&2
) else (
    call venv\Scripts\activate.bat
)

python -m inkmcp.inkscape_mcp_server
endlocal
```

Update `README.md` with:
- Windows quickstart guide.
- Running `.\install_extension.ps1`.
- Starting the server via `run_inkscape_mcp.ps1` or `.bat`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_platform_utils.py::test_launcher_scripts_exist -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add inkmcp/run_inkscape_mcp.ps1 inkmcp/run_inkscape_mcp.bat README.md tests/test_platform_utils.py
git commit -m "feat(windows): add PowerShell and Batch server launchers and Windows documentation"
```

---

### Task 7: End-to-End Verification on Windows

**Files:**
- Run: `python install_extension.py --check`
- Run: `python -m inkmcp.install_extension --force`
- Run: `python -m pytest -v`

**Interfaces:**
- Consumes: All modules from Tasks 1-6.
- Produces: Live verified verification evidence showing green test runs and successful extension installation on Windows 11 host.

- [ ] **Step 1: Execute extension installer on Windows host**

Run: `python inkmcp/install_extension.py --force`
Expected: Copies files to `%APPDATA%\inkscape\extensions` with exit code 0.

- [ ] **Step 2: Verify installation check**

Run: `python inkmcp/install_extension.py --check`
Expected: `Status: inkmcp extension is installed and ready.` with exit code 0.

- [ ] **Step 3: Run comprehensive pytest test suite**

Run: `python -m pytest -v`
Expected: All tests pass (75+ passing, 0 failing, 0 errors).

- [ ] **Step 4: Verify standalone script assertions**

Run: `python testinkmcp.py`
Expected: `Standalone execution check: testinkmcp passed with all assertions verified.` with exit code 0.

- [ ] **Step 5: Commit and clean working tree**

```bash
git status
git commit -m "chore(release): verify complete Windows support integration"
```
