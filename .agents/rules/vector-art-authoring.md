# Vector Art Authoring & Path Healing Protocol

This rule defines the mandatory standards for manipulating, healing, separating, and editing vector artwork (SVG, DXF, EPS).

## Core Principle: Anti-Hallucinated Vector Synthesis

Large language models lack spatial vision and real-time Bézier handle feedback. Under no circumstances should an agent attempt to "draw" or "freehand" organic shapes, wood grain, anatomy, or complex 3D perspective by inventing coordinate numbers in code (`d="M... C... Z"`).

## Mandatory Methodologies

### 1. Subpath De-duplication (Closing Holes)
When healing paths that contain cutouts/holes caused by foreground objects (crosses, bats, decorations):
- Identify the internal subpaths forming the cutout boundaries.
- Remove or bypass the internal detour subpaths while preserving the outer perimeter curve data unaltered.
- Never draw synthetic replacement polygons over authentic paths.

### 2. Symmetrical & Affine Geometric Derivation
When completing missing structural geometry (e.g. the obscured left wall of an open casket or box):
- Derive the geometry by applying exact affine transforms (reflection across symmetry axes, scaling, translation) to the author's authentic opposite-side paths.
- Retain the exact line weight, node style, and Bézier curvature created by the original artist.

### 3. Native Inkscape CLI Geometry Actions
When Boolean path operations (union, difference, intersection, division) are required:
- Utilize Inkscape's built-in geometric calculation engine via CLI actions:
  ```bash
  inkscape --actions="select-by-id:elem_a,elem_b; path-union; export-do" file.svg
  ```
- Allow the professional vector engine to compute curve intersections and node placements.

### 4. Human Collaborative Boundary
When visual artwork requires aesthetic nuance, fine texture, or creative artistic styling:
- Recognize the technical boundary between structure (layers, IDs, groups, transforms) and art.
- Scaffolding belongs in code; artistic painting/drawing belongs in the live Inkscape GUI.
- Present clean, organized layers to the human partner so they can use native drawing tools seamlessly.
