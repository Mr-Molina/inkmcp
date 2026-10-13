# Coloring Book Outline & Live Desktop Paint Bucket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a 4-phase coloring book vectorization pipeline that extracts a CIELAB color inventory, generates a clean black-and-white outline via `OutlineGenerator`, injects the outline into Inkscape, and automates Inkscape's native Paint Bucket tool via Win32 desktop automation.

**Architecture:** Decouples CIELAB color quantization (`ColorInventory`), outline generation with edge fallback (`OutlineGenerator`), morphological region topology analysis (`RegionTopologyAnalyzer`), Win32 GUI tool automation (`InkscapeDesktopAutomator`), and pipeline orchestration (`ColoringBookPipeline`) exposed via MCP and CLI operations.

**Tech Stack:** Python 3.13, OpenCV (`opencv-python`), PIL (`pillow`), `scikit-learn` / K-Means, `pywin32` (`win32gui`, `win32con`, `win32api`), `vtracer`, `inkex`, `fastmcp`, `pytest`.

**Spec:** [`s:/Github/inkmcp/docs/superpowers/specs/2026-10-13-coloring-book-paint-bucket-design.md`](file:///s:/Github/inkmcp/docs/superpowers/specs/2026-10-13-coloring-book-paint-bucket-design.md)

**Execution Waves:**
- **Wave 1 (Parallel - Disjoint files)**:
  - Task 1: Upstream Manifest Constraints & CVE Remediations (`inkmcp/requirements.txt`, `pyproject.toml`, `.agents/.manifest_hash`)
  - Task 2: Color Inventory & Spatial Indexing Engine with CIELAB Quantization (`inkmcp/vectorizer/color_inventory.py`, `tests/test_color_inventory.py`)
  - Task 3: Region Topology & Pole of Inaccessibility Analyzer (`inkmcp/vectorizer/region_topology.py`, `tests/test_region_topology.py`)
  - Task 4: Win32 Desktop Paint Bucket Automator with Color Enforcement & ESC Abort (`inkmcp/backends/desktop_automator.py`, `tests/test_desktop_automator.py`)
  - Task 5: Outline Generator Protocol & Fallback Engine (`inkmcp/vectorizer/outline_generator.py`, `tests/test_outline_generator.py`)
- **Wave 2 (Sequential/Integration)**:
  - Task 6: Coloring Book Pipeline Orchestrator & Viewport Calibrator (`inkmcp/vectorizer/coloring_book_pipeline.py`, `tests/test_coloring_book_pipeline.py`) - Blocked by Tasks 2, 3, 4, 5
  - Task 7: MCP Operation Dispatcher, FastMCP Schema & CLI Integration (`inkmcp/inkmcpops/vectorize_operations.py`, `inkmcp/inkscape_mcp_server.py`, `inkmcp/inkmcpcli.py`, `tests/test_vectorize_coloring_book_op.py`) - Blocked by Task 6

---

## Global Constraints

- Python compatibility: 3.10 to 3.13+ on Windows (PowerShell environment).
- All Win32 API interactions must be non-blocking with configurable delays and mockable for headless CI.
- All commands run in `pwsh` on Windows. Quote escaping in PowerShell must use `""` or ``` `" ``` — never `\"`.
- Single-concern subagent slicing: Each task operates strictly within its designated file boundaries.

---

## Review Focus

1. **`source_image_missing_or_corrupt`**: `ColorInventory.from_image("nonexistent.png")` raises `FileNotFoundError` with clear message. (Covered in Task 2)
2. **`pure_monochrome_source_image`**: Pure white/black or flat 1-color image produces valid palette without zero-division or K-Means crash. (Covered in Task 2)
3. **`outline_with_unclosed_boundary`**: Morphological closing seals 1–2px micro-gaps; unclosed boundaries do not trigger an infinite loop or unhandled exception. (Covered in Task 3)
4. **`inkscape_window_not_found`**: `InkscapeDesktopAutomator.execute_sequence()` returns graceful error response (`status="error"`) without throwing unhandled Win32 exceptions. (Covered in Task 4)
5. **`user_presses_escape_abort`**: Triggering `VK_ESCAPE` mid-sequence halts clicks immediately within 100ms and returns partial fill metrics with `status="aborted"`. (Covered in Task 4)

---

## Task Decomposition

### Task 1: Upstream Manifest Constraints & CVE Remediations

**Files:**
- Modify: `inkmcp/requirements.txt:1-6`
- Modify: `pyproject.toml:1-40`
- Modify: `.agents/.manifest_hash:1`
- Test: `tests/test_manifest_consistency.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: Wakeup audit findings from `Reconnaissance Lookout`
- Produces: Patched dependency bounds (`lxml>=6.1.0,<7.0.0`, `setuptools>=70.0.0,<90.0.0`, `pytest>=9.0.3,<10.0.0`) and updated `.agents/.manifest_hash`

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write test verifying manifest constraint bounds and hash sync**

Create `tests/test_manifest_consistency.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**
```powershell
pytest tests/test_manifest_consistency.py -v
```
Expected: FAIL due to existing `<6.0.0` ceiling on `lxml` and `<70.0.0` on `setuptools`.

- [ ] **Step 3: Update `inkmcp/requirements.txt` and `pyproject.toml`**
Update `lxml` bound in both files to `lxml>=6.1.0,<7.0.0`, `setuptools>=70.0.0,<90.0.0`, `pytest>=9.0.3,<10.0.0`.
Recalculate hash by running:
```powershell
python "C:\Users\jmolina\.gemini\config\skills\wakeup\scripts\wakeup_bootstrap.py"
```

- [ ] **Step 4: Run test to verify it passes**
```powershell
pytest tests/test_manifest_consistency.py -v
```
Expected: PASS (2/2 passing).

- [ ] **Step 5: Commit**
```powershell
git add inkmcp/requirements.txt pyproject.toml .agents/.manifest_hash tests/test_manifest_consistency.py
git commit -m "fix(deps): raise lxml ceiling to >=6.1.0 and harden setuptools bounds"
```

---

### Task 2: Color Inventory & Spatial Indexing Engine with CIELAB Quantization

**Files:**
- Create: `inkmcp/vectorizer/color_inventory.py`
- Test: `tests/test_color_inventory.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: Source raster file path (`str` or `Path`)
- Produces: `ColorInventory` class with methods:
  - `ColorInventory.from_image(path: str, num_colors: int = 8) -> ColorInventory`
  - `get_palette() -> List[str]` (HEX strings, e.g. `["#FFFFFF", "#FF0000", ...]`)
  - `get_color_at(u: float, v: float) -> str` (Returns closest HEX color for normalized coordinate)

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write failing unit tests for ColorInventory**

Create `tests/test_color_inventory.py`:
```python
import pytest
import numpy as np
from PIL import Image
from inkmcp.vectorizer.color_inventory import ColorInventory

@pytest.fixture
def synthetic_quad_image(tmp_path):
    arr = np.zeros((100, 100, 3), dtype=np.uint8)
    arr[0:50, 0:50] = [255, 0, 0]      # Red
    arr[0:50, 50:100] = [0, 255, 0]    # Green
    arr[50:100, 0:50] = [0, 0, 255]    # Blue
    arr[50:100, 50:100] = [255, 255, 0]# Yellow
    img = Image.fromarray(arr)
    path = tmp_path / "quad.png"
    img.save(path)
    return str(path)

def test_color_inventory_palette_extraction(synthetic_quad_image):
    inventory = ColorInventory.from_image(synthetic_quad_image, num_colors=4)
    palette = inventory.get_palette()
    assert len(palette) == 4
    hex_set = {c.upper() for c in palette}
    assert "#FF0000" in hex_set
    assert "#00FF00" in hex_set
    assert "#0000FF" in hex_set

def test_color_inventory_spatial_lookup(synthetic_quad_image):
    inventory = ColorInventory.from_image(synthetic_quad_image, num_colors=4)
    assert inventory.get_color_at(0.25, 0.25).upper() == "#FF0000"
    assert inventory.get_color_at(0.75, 0.25).upper() == "#00FF00"
    assert inventory.get_color_at(0.25, 0.75).upper() == "#0000FF"
    assert inventory.get_color_at(0.75, 0.75).upper() == "#FFFF00"

def test_color_inventory_missing_file():
    with pytest.raises(FileNotFoundError):
        ColorInventory.from_image("nonexistent_test_file.png")

def test_color_inventory_monochrome(tmp_path):
    img = Image.new("RGB", (50, 50), color=(128, 128, 128))
    path = tmp_path / "gray.png"
    img.save(path)
    inventory = ColorInventory.from_image(str(path), num_colors=4)
    palette = inventory.get_palette()
    assert len(palette) >= 1
    assert inventory.get_color_at(0.5, 0.5).upper() == "#808080"
```

- [ ] **Step 2: Run test to verify failure**
```powershell
pytest tests/test_color_inventory.py -v
```
Expected: FAIL (`ModuleNotFoundError: No module named 'inkmcp.vectorizer.color_inventory'`).

- [ ] **Step 3: Implement `ColorInventory` with CIELAB conversion**

Create `inkmcp/vectorizer/color_inventory.py`:
```python
"""Color inventory and spatial indexing module using CIELAB color clustering."""
from pathlib import Path
from typing import List
import cv2
import numpy as np

class ColorInventory:
    """Extracts dominant palette using CIELAB K-Means and provides spatial coordinate color queries."""

    def __init__(self, palette: List[str], spatial_map: np.ndarray):
        self._palette = [p.upper() for p in palette]
        self._spatial_map = spatial_map  # Downscaled RGB array (H, W, 3)

    @classmethod
    def from_image(cls, image_path: str, num_colors: int = 8) -> "ColorInventory":
        path_obj = Path(image_path)
        if not path_obj.exists() or not path_obj.is_file():
            raise FileNotFoundError(f"Source image not found: {image_path}")

        img = cv2.imread(str(path_obj), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Could not decode image at {image_path}")

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img_rgb.shape[:2]

        max_dim = 256
        scale = min(1.0, max_dim / max(h, w))
        if scale < 1.0:
            thumb_rgb = cv2.resize(img_rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        else:
            thumb_rgb = img_rgb.copy()

        # Convert to CIELAB for perceptual color clustering
        thumb_lab = cv2.cvtColor(thumb_rgb, cv2.COLOR_RGB2Lab)
        pixels_lab = thumb_lab.reshape(-1, 3).astype(np.float32)

        unique_pixels = np.unique(pixels_lab, axis=0)
        actual_k = min(max(1, num_colors), len(unique_pixels))

        if actual_k <= 1:
            mean_rgb = np.round(np.mean(thumb_rgb.reshape(-1, 3), axis=0)).astype(int)
            hex_color = f"#{mean_rgb[0]:02X}{mean_rgb[1]:02X}{mean_rgb[2]:02X}"
            return cls(palette=[hex_color], spatial_map=thumb_rgb)

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        flags = cv2.KMEANS_PP_CENTERS
        _, labels, centers_lab = cv2.kmeans(pixels_lab, actual_k, None, criteria, 10, flags)

        # Convert CIELAB cluster centers back to RGB
        centers_lab_reshaped = np.clip(centers_lab, 0, 255).astype(np.uint8).reshape(1, -1, 3)
        centers_rgb = cv2.cvtColor(centers_lab_reshaped, cv2.COLOR_Lab2RGB).reshape(-1, 3)
        palette = [f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}" for c in centers_rgb]

        clustered_rgb = centers_rgb[labels.flatten()].reshape(thumb_rgb.shape)
        return cls(palette=palette, spatial_map=clustered_rgb)

    def get_palette(self) -> List[str]:
        return list(self._palette)

    def get_color_at(self, u: float, v: float) -> str:
        u_clamped = max(0.0, min(1.0, float(u)))
        v_clamped = max(0.0, min(1.0, float(v)))
        h, w = self._spatial_map.shape[:2]
        x = min(int(u_clamped * w), w - 1)
        y = min(int(v_clamped * h), h - 1)
        pixel = self._spatial_map[y, x]
        return f"#{pixel[0]:02X}{pixel[1]:02X}{pixel[2]:02X}"
```

- [ ] **Step 4: Run test to verify it passes**
```powershell
pytest tests/test_color_inventory.py -v
```
Expected: PASS (4/4 passing).

- [ ] **Step 5: Commit**
```powershell
git add inkmcp/vectorizer/color_inventory.py tests/test_color_inventory.py
git commit -m "feat(vectorizer): implement ColorInventory with CIELAB clustering and spatial lookup"
```

---

### Task 3: Region Topology & Pole of Inaccessibility Analyzer

**Files:**
- Create: `inkmcp/vectorizer/region_topology.py`
- Test: `tests/test_region_topology.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: Binary line art image (0 = black line, 255 = white region)
- Produces: `RegionTopologyAnalyzer` with method:
  - `extract_fill_regions(binary_mask: np.ndarray, min_area: int = 25, close_gaps_kernel: int = 3) -> List[RegionTarget]`
  - `RegionTarget`: Dataclass containing `label: int`, `area: int`, `u: float`, `v: float`, `pixel_x: int`, `pixel_y: int`

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write failing unit tests for RegionTopologyAnalyzer**

Create `tests/test_region_topology.py`:
```python
import pytest
import numpy as np
import cv2
from inkmcp.vectorizer.region_topology import RegionTopologyAnalyzer

def test_extract_fill_regions_circle():
    mask = np.full((100, 100), 255, dtype=np.uint8)
    cv2.circle(mask, (50, 50), 30, 0, thickness=2)

    analyzer = RegionTopologyAnalyzer()
    regions = analyzer.extract_fill_regions(mask, min_area=25)

    assert len(regions) >= 2
    inside_region = min(regions, key=lambda r: (r.pixel_x - 50)**2 + (r.pixel_y - 50)**2)
    assert abs(inside_region.pixel_x - 50) <= 2
    assert abs(inside_region.pixel_y - 50) <= 2
    assert 0.45 <= inside_region.u <= 0.55
    assert 0.45 <= inside_region.v <= 0.55

def test_extract_fill_regions_gap_healing():
    mask = np.full((100, 100), 255, dtype=np.uint8)
    cv2.circle(mask, (50, 50), 30, 0, thickness=2)
    mask[19:22, 49:52] = 255

    analyzer = RegionTopologyAnalyzer()
    regions = analyzer.extract_fill_regions(mask, min_area=25, close_gaps_kernel=5)
    inside_region = min(regions, key=lambda r: (r.pixel_x - 50)**2 + (r.pixel_y - 50)**2)
    assert abs(inside_region.pixel_x - 50) <= 2

def test_speckle_filtering():
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[10:13, 10:13] = 255
    analyzer = RegionTopologyAnalyzer()
    regions = analyzer.extract_fill_regions(mask, min_area=25)
    assert len(regions) == 0
```

- [ ] **Step 2: Run test to verify failure**
```powershell
pytest tests/test_region_topology.py -v
```
Expected: FAIL (`ModuleNotFoundError: No module named 'inkmcp.vectorizer.region_topology'`).

- [ ] **Step 3: Implement `RegionTopologyAnalyzer`**

Create `inkmcp/vectorizer/region_topology.py`:
```python
"""Topological face and centroid extraction module for coloring book fills."""
from dataclasses import dataclass
from typing import List
import cv2
import numpy as np

@dataclass
class RegionTarget:
    label: int
    area: int
    u: float
    v: float
    pixel_x: int
    pixel_y: int

class RegionTopologyAnalyzer:
    """Analyzes binary line art to find closed white regions and interior click centroids."""

    def extract_fill_regions(
        self,
        binary_mask: np.ndarray,
        min_area: int = 25,
        close_gaps_kernel: int = 3,
    ) -> List[RegionTarget]:
        h, w = binary_mask.shape[:2]
        processed = binary_mask.copy()

        if close_gaps_kernel > 1:
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (close_gaps_kernel, close_gaps_kernel)
            )
            inv = cv2.bitwise_not(processed)
            inv_closed = cv2.morphologyEx(inv, cv2.MORPH_CLOSE, kernel)
            processed = cv2.bitwise_not(inv_closed)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            processed, connectivity=8
        )

        regions: List[RegionTarget] = []

        for lbl in range(1, num_labels):
            area = stats[lbl, cv2.CC_STAT_AREA]
            if area < min_area:
                continue

            region_mask = (labels == lbl).astype(np.uint8) * 255
            dist = cv2.distanceTransform(region_mask, cv2.DIST_L2, 5)
            _, _, _, max_loc = cv2.minMaxLoc(dist)

            best_x, best_y = max_loc
            u = float(best_x) / float(w)
            v = float(best_y) / float(h)

            regions.append(
                RegionTarget(
                    label=lbl,
                    area=area,
                    u=u,
                    v=v,
                    pixel_x=best_x,
                    pixel_y=best_y,
                )
            )

        return regions
```

- [ ] **Step 4: Run test to verify it passes**
```powershell
pytest tests/test_region_topology.py -v
```
Expected: PASS (3/3 passing).

- [ ] **Step 5: Commit**
```powershell
git add inkmcp/vectorizer/region_topology.py tests/test_region_topology.py
git commit -m "feat(vectorizer): implement RegionTopologyAnalyzer with distance-transform centroids"
```

---

### Task 4: Win32 Desktop Paint Bucket Automator with Color Enforcement & ESC Abort

**Files:**
- Create: `inkmcp/backends/desktop_automator.py`
- Test: `tests/test_desktop_automator.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: List of `(hex_color: str, u: float, v: float)` commands, optional backend for post-click styling
- Produces: `InkscapeDesktopAutomator` class:
  - `find_inkscape_window() -> Optional[int]`
  - `activate_paint_bucket(hwnd: int) -> bool`
  - `click_canvas_coordinate(hwnd: int, u: float, v: float) -> Tuple[int, int]`
  - `execute_sequence(commands: List[Tuple[str, float, float]], click_delay_ms: int = 80, backend: Optional[Any] = None) -> Dict[str, Any]`

#### Verification Pattern: Standard TDD (Mocked Win32)
- [ ] **Step 1: Write unit tests including ESC abort, focus guard, and color styling**

Create `tests/test_desktop_automator.py`:
```python
import pytest
from unittest.mock import MagicMock, patch
from inkmcp.backends.desktop_automator import InkscapeDesktopAutomator

def test_automator_window_not_found():
    automator = InkscapeDesktopAutomator()
    with patch.object(automator, "find_inkscape_window", return_value=None):
        result = automator.execute_sequence([("#FF0000", 0.5, 0.5)])
        assert result["status"] == "error"
        assert "Inkscape window not found" in result["message"]

def test_automator_click_sequence_execution():
    automator = InkscapeDesktopAutomator()
    mock_backend = MagicMock()
    with patch.object(automator, "find_inkscape_window", return_value=12345), \
         patch.object(automator, "_focus_window", return_value=True), \
         patch.object(automator, "activate_paint_bucket", return_value=True), \
         patch.object(automator, "_get_canvas_rect", return_value=(100, 100, 900, 700)), \
         patch.object(automator, "_dispatch_click") as mock_click, \
         patch("win32gui.GetForegroundWindow", return_value=12345), \
         patch("win32api.GetAsyncKeyState", return_value=0), \
         patch("time.sleep"):

        commands = [
            ("#FF0000", 0.25, 0.25),
            ("#00FF00", 0.75, 0.75),
        ]
        result = automator.execute_sequence(commands, click_delay_ms=0, backend=mock_backend)
        assert result["status"] == "success"
        assert result["clicks_dispatched"] == 2
        assert mock_click.call_count == 2
        assert mock_backend.execute_operation.call_count == 2

def test_automator_escape_abort():
    automator = InkscapeDesktopAutomator()
    with patch.object(automator, "find_inkscape_window", return_value=12345), \
         patch.object(automator, "_focus_window", return_value=True), \
         patch.object(automator, "activate_paint_bucket", return_value=True), \
         patch.object(automator, "_get_canvas_rect", return_value=(100, 100, 900, 700)), \
         patch.object(automator, "_dispatch_click"), \
         patch("win32gui.GetForegroundWindow", return_value=12345), \
         patch("win32api.GetAsyncKeyState", side_effect=[0, 0x8000]), \
         patch("time.sleep"):

        commands = [
            ("#FF0000", 0.25, 0.25),
            ("#00FF00", 0.75, 0.75),
        ]
        result = automator.execute_sequence(commands, click_delay_ms=0)
        assert result["status"] == "aborted"
        assert result["clicks_dispatched"] == 1
```

- [ ] **Step 2: Run test to verify failure**
```powershell
pytest tests/test_desktop_automator.py -v
```
Expected: FAIL (`ModuleNotFoundError: No module named 'inkmcp.backends.desktop_automator'`).

- [ ] **Step 3: Implement `InkscapeDesktopAutomator`**

Create `inkmcp/backends/desktop_automator.py`:
```python
"""Win32 desktop automation module for live Inkscape canvas interaction."""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import win32gui
    import win32con
    import win32api
except ImportError:
    win32gui = None
    win32con = None
    win32api = None

logger = logging.getLogger(__name__)

class InkscapeDesktopAutomator:
    """Automates Paint Bucket tool selection, color styling, and canvas clicks."""

    def __init__(self):
        self._is_available = win32gui is not None

    def is_available(self) -> bool:
        return self._is_available

    def find_inkscape_window(self) -> Optional[int]:
        if not self._is_available:
            return None

        found_hwnd = []
        def _enum_cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "Inkscape" in title:
                    found_hwnd.append(hwnd)
            return True

        win32gui.EnumWindows(_enum_cb, None)
        return found_hwnd[0] if found_hwnd else None

    def _focus_window(self, hwnd: int) -> bool:
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            return True
        except Exception as e:
            logger.warning("Failed to focus Inkscape window: %s", e)
            return False

    def activate_paint_bucket(self, hwnd: int) -> bool:
        """Send 'U' key to switch to Paint Bucket tool."""
        if not self._is_available:
            return False
        try:
            win32api.keybd_event(0x55, 0, 0, 0)
            time.sleep(0.02)
            win32api.keybd_event(0x55, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.1)
            return True
        except Exception as e:
            logger.warning("Failed to send key to activate bucket tool: %s", e)
            return False

    def _get_canvas_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        rect = win32gui.GetClientRect(hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        left = rect[0] + int(w * 0.15)
        top = rect[1] + int(h * 0.15)
        right = rect[2] - int(w * 0.15)
        bottom = rect[3] - int(h * 0.15)
        return (left, top, right, bottom)

    def click_canvas_coordinate(self, hwnd: int, u: float, v: float) -> Tuple[int, int]:
        c_left, c_top, c_right, c_bottom = self._get_canvas_rect(hwnd)
        c_w = max(1, c_right - c_left)
        c_h = max(1, c_bottom - c_top)
        client_x = c_left + int(u * c_w)
        client_y = c_top + int(v * c_h)
        screen_x, screen_y = win32gui.ClientToScreen(hwnd, (client_x, client_y))
        self._dispatch_click(screen_x, screen_y)
        return (screen_x, screen_y)

    def _dispatch_click(self, screen_x: int, screen_y: int):
        win32api.SetCursorPos((screen_x, screen_y))
        time.sleep(0.02)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.02)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def execute_sequence(
        self,
        commands: List[Tuple[str, float, float]],
        click_delay_ms: int = 80,
        backend: Optional[Any] = None,
    ) -> Dict[str, Any]:
        hwnd = self.find_inkscape_window()
        if not hwnd:
            return {
                "status": "error",
                "message": "Inkscape window not found. Please ensure Inkscape is running with an open canvas.",
            }

        if not self._focus_window(hwnd):
            return {
                "status": "error",
                "message": "Failed to bring Inkscape window to foreground.",
            }

        self.activate_paint_bucket(hwnd)

        clicks_dispatched = 0
        aborted = False

        for hex_color, u, v in commands:
            # Check for ESC key abort
            if win32api and (win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000):
                aborted = True
                break

            # Re-assert focus if another window stole foreground
            if win32gui and win32gui.GetForegroundWindow() != hwnd:
                self._focus_window(hwnd)

            self.click_canvas_coordinate(hwnd, u, v)
            clicks_dispatched += 1

            # Enforce exact fill color on newly created & selected path
            if backend and hasattr(backend, "execute_operation") and hex_color:
                try:
                    style_op = {
                        "tag": "path",
                        "attributes": {
                            "style": f"fill:{hex_color};fill-opacity:1;stroke:none"
                        }
                    }
                    backend.execute_operation(style_op)
                except Exception as e:
                    logger.warning("Failed to apply color style: %s", e)

            if click_delay_ms > 0:
                time.sleep(click_delay_ms / 1000.0)

        return {
            "status": "aborted" if aborted else "success",
            "message": f"Dispatched {clicks_dispatched} bucket clicks" + (" (aborted by ESC)" if aborted else ""),
            "clicks_dispatched": clicks_dispatched,
            "total_commands": len(commands),
        }
```

- [ ] **Step 4: Run test to verify it passes**
```powershell
pytest tests/test_desktop_automator.py -v
```
Expected: PASS (3/3 passing).

- [ ] **Step 5: Commit**
```powershell
git add inkmcp/backends/desktop_automator.py tests/test_desktop_automator.py
git commit -m "feat(backends): implement InkscapeDesktopAutomator with color styling and ESC abort"
```

---

### Task 5: Outline Generator Protocol & Fallback Engine

**Files:**
- Create: `inkmcp/vectorizer/outline_generator.py`
- Test: `tests/test_outline_generator.py`

**Dependencies:**
- Blocked By: None
- Parallel Wave: Wave 1

**Interfaces:**
- Consumes: Source raster path (`str` or `Path`), optional pre-generated outline path
- Produces: `OutlineGenerator` class:
  - `PROMPT_TEMPLATE: str`
  - `generate_outline(image_path: str, outline_path: Optional[str] = None) -> np.ndarray` (Returns 2D uint8 binary array, 0=lines, 255=regions)

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write unit tests for OutlineGenerator**

Create `tests/test_outline_generator.py`:
```python
import pytest
import numpy as np
import cv2
from PIL import Image
from inkmcp.vectorizer.outline_generator import OutlineGenerator

def test_prompt_template_contents():
    assert "coloring book" in OutlineGenerator.PROMPT_TEMPLATE.lower()
    assert "black outline" in OutlineGenerator.PROMPT_TEMPLATE.lower()

def test_load_existing_outline(tmp_path):
    img = Image.new("L", (100, 100), 255)
    path = tmp_path / "out.png"
    img.save(path)

    gen = OutlineGenerator()
    arr = gen.generate_outline("dummy_src.png", outline_path=str(path))
    assert arr.shape == (100, 100)
    assert set(np.unique(arr)).issubset({0, 255})

def test_algorithmic_edge_fallback(tmp_path):
    # Create synthetic colored circle on white
    src = Image.new("RGB", (100, 100), (255, 255, 255))
    src_arr = np.full((100, 100, 3), 255, dtype=np.uint8)
    cv2.circle(src_arr, (50, 50), 20, (0, 0, 255), -1)
    src_path = tmp_path / "circle.png"
    Image.fromarray(src_arr).save(src_path)

    gen = OutlineGenerator()
    arr = gen.generate_outline(str(src_path), outline_path=None)
    assert arr.shape == (100, 100)
    # Boundaries detected as 0 (black), background as 255 (white)
    assert 0 in arr
    assert 255 in arr
```

- [ ] **Step 2: Run test to verify failure**
```powershell
pytest tests/test_outline_generator.py -v
```
Expected: FAIL (`ModuleNotFoundError: No module named 'inkmcp.vectorizer.outline_generator'`).

- [ ] **Step 3: Implement `OutlineGenerator`**

Create `inkmcp/vectorizer/outline_generator.py`:
```python
"""Outline generator protocol and local edge-detection fallback."""
from pathlib import Path
from typing import Optional
import cv2
import numpy as np

class OutlineGenerator:
    """Manages coloring-book line art generation protocol and high-quality edge fallback."""

    PROMPT_TEMPLATE = (
        "Convert this image into a clean, pure black-and-white coloring book style outline. "
        "Thick, closed black outlines on a pure white background (#FFFFFF). "
        "Zero shading, zero textures, zero cross-hatching, zero grayscale gradients. "
        "High contrast crisp line art."
    )

    def generate_outline(
        self,
        image_path: str,
        outline_path: Optional[str] = None,
    ) -> np.ndarray:
        """Load pre-generated AI outline or execute local edge-detection fallback."""
        if outline_path and Path(outline_path).is_file():
            img = cv2.imread(str(outline_path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                _, binarized = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
                return binarized

        # Local algorithmic fallback: bilateral filter + Canny edges + dilation
        src = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if src is None:
            raise FileNotFoundError(f"Source image not found: {image_path}")

        gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
        filtered = cv2.bilateralFilter(gray, 7, 75, 75)
        edges = cv2.Canny(filtered, 50, 150)

        # Dilate edges slightly (thickness 2)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        thick_edges = cv2.dilate(edges, kernel, iterations=1)

        # Invert so black lines are 0 and white regions are 255
        return cv2.bitwise_not(thick_edges)
```

- [ ] **Step 4: Run test to verify it passes**
```powershell
pytest tests/test_outline_generator.py -v
```
Expected: PASS (3/3 passing).

- [ ] **Step 5: Commit**
```powershell
git add inkmcp/vectorizer/outline_generator.py tests/test_outline_generator.py
git commit -m "feat(vectorizer): implement OutlineGenerator with prompt protocol and Canny fallback"
```

---

### Task 6: Coloring Book Pipeline Orchestrator & Viewport Calibrator

**Files:**
- Create: `inkmcp/vectorizer/coloring_book_pipeline.py`
- Test: `tests/test_coloring_book_pipeline.py`

**Dependencies:**
- Blocked By: Tasks 2, 3, 4, 5
- Parallel Wave: Wave 2

**Interfaces:**
- Consumes: `ColorInventory`, `OutlineGenerator`, `RegionTopologyAnalyzer`, `InkscapeDesktopAutomator`, `VTracerCore`, `WindowsCliBackend`
- Produces: `ColoringBookPipeline` with method:
  - `run(params: Dict[str, Any], backend: Optional[Any] = None) -> Dict[str, Any]`

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write integration unit tests for ColoringBookPipeline**

Create `tests/test_coloring_book_pipeline.py`:
```python
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image
from inkmcp.vectorizer.coloring_book_pipeline import ColoringBookPipeline

@pytest.fixture
def mock_outline_and_source(tmp_path):
    src = Image.new("RGB", (100, 100), (255, 0, 0))
    src_path = tmp_path / "source.png"
    src.save(src_path)

    out = Image.new("L", (100, 100), 255)
    out_path = tmp_path / "outline.png"
    out.save(out_path)

    return str(src_path), str(out_path)

def test_coloring_book_pipeline_end_to_end(mock_outline_and_source, tmp_path):
    src_path, out_path = mock_outline_and_source
    out_svg = tmp_path / "output.svg"
    pipeline = ColoringBookPipeline()

    mock_backend = MagicMock()
    mock_backend.is_available.return_value = True

    with patch.object(pipeline._automator, "execute_sequence", return_value={"status": "success", "clicks_dispatched": 1}):
        result = pipeline.run({
            "image_path": src_path,
            "outline_path": out_path,
            "output_path": str(out_svg),
            "inject_to_inkscape": True,
        }, backend=mock_backend)

        assert result["status"] == "success"
        assert result["data"]["regions_detected"] >= 1
        assert out_svg.exists()
```

- [ ] **Step 2: Run test to verify failure**
```powershell
pytest tests/test_coloring_book_pipeline.py -v
```
Expected: FAIL (`ModuleNotFoundError: No module named 'inkmcp.vectorizer.coloring_book_pipeline'`).

- [ ] **Step 3: Implement `ColoringBookPipeline` with `PIL.Image` VTracer adapter and SVG export**

Create `inkmcp/vectorizer/coloring_book_pipeline.py`:
```python
"""Coloring book vectorization and live fill pipeline."""
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional
from PIL import Image

from inkmcp.backends.desktop_automator import InkscapeDesktopAutomator
from inkmcp.inkmcpops.common import create_error_response, create_success_response
from inkmcp.vectorizer.color_inventory import ColorInventory
from inkmcp.vectorizer.core import VTracerCore
from inkmcp.vectorizer.outline_generator import OutlineGenerator
from inkmcp.vectorizer.region_topology import RegionTopologyAnalyzer

class ColoringBookPipeline:
    """Coordinates color inventory, outline tracing, canvas injection, and desktop bucket filling."""

    def __init__(self, automator: Optional[InkscapeDesktopAutomator] = None):
        self._automator = automator or InkscapeDesktopAutomator()
        self._topology = RegionTopologyAnalyzer()
        self._outline_gen = OutlineGenerator()

    def run(
        self,
        params: Dict[str, Any],
        backend: Optional[Any] = None,
    ) -> Dict[str, Any]:
        image_path = params.get("image_path")
        if not image_path:
            return create_error_response("image_path is required")

        outline_path = params.get("outline_path")
        output_path = params.get("output_path")
        num_colors = int(params.get("num_colors", 8))
        min_region_area = int(params.get("min_region_area", 25))
        click_delay_ms = int(params.get("click_delay_ms", 80))
        inject_to_inkscape = bool(params.get("inject_to_inkscape", True))

        # 1. Color Inventory
        inventory = ColorInventory.from_image(image_path, num_colors=num_colors)

        # 2. Outline Ingestion
        bin_outline = self._outline_gen.generate_outline(image_path, outline_path=outline_path)

        # 3. Vectorize Line Art (Wrap ndarray in PIL.Image to prevent VTracer TypeError)
        pil_outline = Image.fromarray(bin_outline)
        core = VTracerCore()
        raw_vector = core.vectorize(
            pil_outline,
            colormode="binary",
            hierarchical="stacked",
            filter_speckle=4,
        )

        # 4. Generate SVG Document Content
        h, w = bin_outline.shape[:2]
        paths_xml = "\n".join(
            f'    <path id="{p.id}" fill="#000000" d="{p.path_data}" />'
            for p in raw_vector.path_records
        )
        svg_content = (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
            f'  <g id="layer_line_art" inkscape:groupmode="layer" inkscape:label="Line Art">\n'
            f'{paths_xml}\n'
            f'  </g>\n'
            f'</svg>'
        )

        resolved_output = output_path
        if not resolved_output:
            temp_fd, temp_path = tempfile.mkstemp(suffix=".svg", prefix="coloring_book_")
            os.close(temp_fd)
            resolved_output = temp_path

        with open(resolved_output, "w", encoding="utf-8") as f:
            f.write(svg_content)

        # 5. Canvas Injection & Viewport Normalization
        if inject_to_inkscape and backend is not None and hasattr(backend, "execute_operation"):
            layer_payload = {
                "tag": "g",
                "attributes": {
                    "id": "layer_line_art",
                    "inkscape:groupmode": "layer",
                    "inkscape:label": "Line Art",
                },
                "children": [
                    {
                        "tag": "path",
                        "attributes": {
                            "id": p.id,
                            "fill": "#000000",
                            "d": p.path_data,
                        },
                    }
                    for p in raw_vector.path_records
                ],
            }
            backend.execute_operation(layer_payload)

            try:
                import subprocess
                from inkmcp.platform_utils import find_inkscape_executable
                ink_exe = find_inkscape_executable()
                if ink_exe:
                    subprocess.run(
                        [str(ink_exe), "-q", "--actions=select-all;page-fit-to-selection;zoom-drawing;select-clear"],
                        capture_output=True,
                        timeout=10,
                    )
            except Exception:
                pass

        # 6. Extract Regions & Build Click Commands
        regions = self._topology.extract_fill_regions(bin_outline, min_area=min_region_area)
        commands = []
        for r in regions:
            color = inventory.get_color_at(r.u, r.v)
            commands.append((color, r.u, r.v))

        # 7. Live Desktop Win32 Paint Bucket Automation
        auto_result = {"status": "skipped", "clicks_dispatched": 0}
        if inject_to_inkscape and self._automator.is_available():
            auto_result = self._automator.execute_sequence(
                commands, click_delay_ms=click_delay_ms, backend=backend
            )

        return create_success_response(
            "Coloring book vectorization and fill sequence complete",
            output_path=resolved_output,
            regions_detected=len(regions),
            palette=inventory.get_palette(),
            total_nodes=sum(len(p.path_data.split()) for p in raw_vector.path_records),
            layer_count=1,
            automation=auto_result,
        )
```

- [ ] **Step 4: Run test to verify it passes**
```powershell
pytest tests/test_coloring_book_pipeline.py -v
```
Expected: PASS (1/1 passing).

- [ ] **Step 5: Commit**
```powershell
git add inkmcp/vectorizer/coloring_book_pipeline.py tests/test_coloring_book_pipeline.py
git commit -m "feat(vectorizer): implement ColoringBookPipeline with VTracer adapter and SVG export"
```

---

### Task 7: MCP Operation Dispatcher, FastMCP Schema & CLI Integration

**Files:**
- Modify: `inkmcp/inkmcpops/vectorize_operations.py:24-30, 80-165`
- Modify: `inkmcp/inkscape_mcp_server.py:520-560`
- Modify: `inkmcp/inkmcpcli.py:120-160`
- Test: `tests/test_vectorize_coloring_book_op.py`

**Dependencies:**
- Blocked By: Task 6
- Parallel Wave: Wave 2

**Interfaces:**
- Consumes: MCP tool calls `vectorize_image(mode="coloring_book")` and CLI `inkmcpcli vectorize-image --mode coloring_book`
- Produces: Seamless MCP tool execution matching canonical response schema.

#### Verification Pattern: Standard TDD
- [ ] **Step 1: Write failing operation test**

Create `tests/test_vectorize_coloring_book_op.py`:
```python
import pytest
from unittest.mock import patch
from PIL import Image
from inkmcp.inkmcpops.vectorize_operations import vectorize_image_operation

def test_vectorize_coloring_book_dispatch(tmp_path):
    img_path = tmp_path / "test.png"
    Image.new("RGB", (50, 50), (255, 0, 0)).save(img_path)

    with patch("inkmcp.vectorizer.coloring_book_pipeline.ColoringBookPipeline.run") as mock_run:
        mock_run.return_value = {"status": "success", "data": {"regions_detected": 1}}
        result = vectorize_image_operation({
            "image_path": str(img_path),
            "mode": "coloring_book",
        })
        assert result["status"] == "success"
        mock_run.assert_called_once()
```

- [ ] **Step 2: Run test to verify failure**
```powershell
pytest tests/test_vectorize_coloring_book_op.py -v
```
Expected: FAIL (`Unsupported mode: 'coloring_book'`).

- [ ] **Step 3: Update `vectorize_operations.py`, `inkscape_mcp_server.py`, and `inkmcpcli.py`**
In `inkmcp/inkmcpops/vectorize_operations.py`:
- Update `VALID_MODES = ("cut_ready", "layered", "silhouette", "coloring_book")`
- Route `if mode == "coloring_book":` to `from inkmcp.vectorizer.coloring_book_pipeline import ColoringBookPipeline; return ColoringBookPipeline().run(params, backend=backend)`

In `inkmcp/inkscape_mcp_server.py`:
- Update description of `mode` parameter in `vectorize_image` FastMCP tool definition to include `'coloring_book'`.

In `inkmcp/inkmcpcli.py`:
- Add `'coloring_book'` to `--mode` choices and add alias command `vectorize-coloring-book`.

- [ ] **Step 4: Run test to verify it passes**
```powershell
pytest tests/test_vectorize_coloring_book_op.py -v
```
Expected: PASS (1/1 passing).

- [ ] **Step 5: Run full test suite regression**
```powershell
pytest -v
```
Expected: All tests passing (100% green).

- [ ] **Step 6: Commit**
```powershell
git add inkmcp/inkmcpops/vectorize_operations.py inkmcp/inkscape_mcp_server.py inkmcp/inkmcpcli.py tests/test_vectorize_coloring_book_op.py
git commit -m "feat(mcp): expose coloring_book mode in vectorize_image MCP tool and CLI"
```

---

## Final Review & Certification Gate

After all 7 tasks are completed:
1. Run full test suite: `pytest -v` (assert 0 failures).
2. Clean all scratch files and verify git status.
3. Update `.agents/sessions.md` with session summary.
