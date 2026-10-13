import logging
from pathlib import Path
from typing import Optional
import cv2
import numpy as np

logger = logging.getLogger(__name__)

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
        if outline_path:
            if Path(outline_path).is_file():
                img = cv2.imread(str(outline_path), cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    _, binarized = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
                    return binarized
                logger.warning("Could not decode outline image at %s; falling back to edge detection", outline_path)
            else:
                logger.warning("Specified outline_path does not exist: %s; falling back to edge detection", outline_path)

        src = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if src is None:
            raise FileNotFoundError(f"Source image not found: {image_path}")

        gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
        filtered = cv2.bilateralFilter(gray, 7, 75, 75)
        edges = cv2.Canny(filtered, 50, 150)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        thick_edges = cv2.dilate(edges, kernel, iterations=1)

        return cv2.bitwise_not(thick_edges)
