#!/usr/bin/env python3
"""
Comprehensive Showcase Script for inkmcp
Demonstrates full suite of inkmcp capabilities:
1. Native Element Parsing & Creation (Gradient, Circles, Rects, Text)
2. Mathematical Procedural Geometry via execute-code (Rotational Rosette)
3. Hierarchical Group Structuring (g with semantic children)
4. Document Introspection (get-info)
5. Live Active-Window GUI Synchronization (file-rebase)
6. High-Resolution PNG Rasterization (inkscape.com export)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parent
SVG_PATH = ROOT / "test_artwork.svg"
PNG_PATH = ROOT / "test_artwork.png"
INKSCAPE_COM = r"C:\Program Files\Inkscape\bin\inkscape.com"
try:
    from inkmcp.platform_utils import find_inkscape_executable
    _ink = find_inkscape_executable()
    if _ink:
        INKSCAPE_COM = str(_ink)
except ImportError:
    pass

params_file = os.path.join(tempfile.gettempdir(), "mcp_params.json")
resp_file = os.path.join(tempfile.gettempdir(), "inkmcp_showcase_resp.json")


def run_inkmcp_action(payload: dict) -> dict:
    """Execute an inkmcp payload via Inkscape extension architecture."""
    payload["response_file"] = resp_file
    with open(params_file, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    safe_svg_path = str(SVG_PATH).replace(';', '_')
    actions = f"org.khema.inkscape.mcp.noprefs;export-filename:{safe_svg_path};export-overwrite;export-do"
    cmd = [INKSCAPE_COM, f"--actions={actions}", str(SVG_PATH)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
    if res.returncode != 0:
        print(f"Error executing action: {res.stderr}")

    if os.path.exists(resp_file):
        with open(resp_file, "r", encoding="utf-8") as rf:
            data = json.load(rf)
        try:
            os.remove(resp_file)
        except OSError:
            pass
        return data
    return {"status": "error", "message": "No response file produced"}


def main():
    print("=" * 60)
    print("INKMCP SERVER SHOWCASE - RUNNING CAPABILITY SUITE")
    print("=" * 60)

    # ---------------------------------------------------------
    # CAPABILITY 1: Procedural Canvas Reset
    # ---------------------------------------------------------
    print("\n[1/5] Procedurally Resetting Canvas & Adding Defs...")
    reset_code = """
for elem_id in ['mcp_live_circle', 'status_badge_bg', 'status_badge_text', 'rosette_group', 'hud_group', 'compass_group']:
    el = get_element_by_id(elem_id)
    if el is not None:
        p = el.getparent()
        if p is not None:
            p.remove(el)
"""
    resp = run_inkmcp_action({"tag": "execute-code", "attributes": {"code": reset_code}})
    print(" -> Canvas cleaned:", resp.get("status"))

    # ---------------------------------------------------------
    # CAPABILITY 2: Mathematical Geometry via Python execute-code
    # (Sacred Geometry / Cybernetic Rosette using trigonometry)
    # ---------------------------------------------------------
    print("\n[2/5] Procedurally Generating Trigonometric Cyber Rosette via execute-code...")
    rosette_code = """
cx, cy = 400.0, 275.0
r_major = 90.0
petals = 16

rosette_g = Group()
rosette_g.set('id', 'rosette_group')

# Outer dashed tech ring
ring = Circle()
ring.set('cx', str(cx))
ring.set('cy', str(cy))
ring.set('r', str(r_major * 1.4))
ring.set('fill', 'none')
ring.set('stroke', '#4cc9f0')
ring.set('stroke-width', '2')
ring.set('stroke-dasharray', '8 4')
rosette_g.append(ring)

# Generate 16 rotated overlapping laser ellipse petals
for i in range(petals):
    angle = (2 * math.pi / petals) * i
    deg = (360.0 / petals) * i
    
    px = cx + (r_major * 0.45) * math.cos(angle)
    py = cy + (r_major * 0.45) * math.sin(angle)
    
    petal = Ellipse()
    petal.set('cx', str(px))
    petal.set('cy', str(py))
    petal.set('rx', '42')
    petal.set('ry', '18')
    petal.set('fill', 'none')
    
    stroke_color = '#4cc9f0' if i % 2 == 0 else '#f72585'
    petal.set('stroke', stroke_color)
    petal.set('stroke-width', '1.6')
    petal.set('stroke-opacity', '0.8')
    petal.set('transform', 'rotate(' + str(round(deg, 1)) + ' ' + str(round(px, 1)) + ' ' + str(round(py, 1)) + ')')
    rosette_g.append(petal)

# Central technological reticle
inner_ring = Circle()
inner_ring.set('cx', str(cx))
inner_ring.set('cy', str(cy))
inner_ring.set('r', '28')
inner_ring.set('fill', '#0e1017')
inner_ring.set('stroke', '#7209b7')
inner_ring.set('stroke-width', '3')
rosette_g.append(inner_ring)

core_node = Circle()
core_node.set('cx', str(cx))
core_node.set('cy', str(cy))
core_node.set('r', '7')
core_node.set('fill', '#06d6a0')
core_node.set('stroke', '#ffffff')
core_node.set('stroke-width', '1.5')
rosette_g.append(core_node)

svg.append(rosette_g)
"""
    resp = run_inkmcp_action({"tag": "execute-code", "attributes": {"code": rosette_code}})
    print(" -> 16-Petal Trigonometric Rosette & Reticle created:", resp.get("status"))

    # ---------------------------------------------------------
    # CAPABILITY 3: HUD Cards & Metric Dashboard Composition
    # ---------------------------------------------------------
    print("\n[3/5] Composing Semantic HUD Metric Cards...")
    hud_code = """
hud_g = Group()
hud_g.set('id', 'hud_group')

# Header text update
t = get_element_by_id('title_text')
if t is not None:
    t.text = 'INKMCP AUTOMATION ENGINE'

sub = get_element_by_id('subtitle_text')
if sub is not None:
    sub.text = 'ACTIVE SESSION CAPABILITY VERIFICATION // WINDOWS 11 64-BIT'

cards_data = [
    ('MCP PROTOCOL', 'ACTIVE & STABLE', '#06d6a0', 70),
    ('EXECUTION ENGINE', 'PYTHON 3.13 INKEX', '#4cc9f0', 310),
    ('DESKTOP STATUS', 'SYNCHRONIZED', '#f72585', 550)
]

for label, val, color, x_pos in cards_data:
    card = Group()
    card.set('transform', 'translate(' + str(x_pos) + ', 470)')
    
    # Background Box
    box = Rectangle()
    box.set('x', '0')
    box.set('y', '0')
    box.set('width', '180')
    box.set('height', '60')
    box.set('rx', '8')
    box.set('fill', '#141824')
    box.set('stroke', color)
    box.set('stroke-width', '1.5')
    box.set('stroke-opacity', '0.85')
    card.append(box)
    
    # Label
    lbl = TextElement()
    lbl.set('x', '90')
    lbl.set('y', '24')
    lbl.set('font-family', 'Segoe UI, sans-serif')
    lbl.set('font-size', '10')
    lbl.set('font-weight', 'bold')
    lbl.set('text-anchor', 'middle')
    lbl.set('fill', '#94a3b8')
    lbl.set('letter-spacing', '1')
    lbl.text = label
    card.append(lbl)
    
    # Value
    v_txt = TextElement()
    v_txt.set('x', '90')
    v_txt.set('y', '46')
    v_txt.set('font-family', 'Segoe UI, sans-serif')
    v_txt.set('font-size', '12')
    v_txt.set('font-weight', 'bold')
    v_txt.set('text-anchor', 'middle')
    v_txt.set('fill', color)
    v_txt.text = val
    card.append(v_txt)
    
    hud_g.append(card)

svg.append(hud_g)
"""
    resp = run_inkmcp_action({"tag": "execute-code", "attributes": {"code": hud_code}})
    print(" -> HUD Telemetry Cards created:", resp.get("status"))

    # ---------------------------------------------------------
    # CAPABILITY 4: Document Introspection (get-info)
    # ---------------------------------------------------------
    print("\n[4/5] Introspecting Resulting Document Topology (get-info)...")
    info_resp = run_inkmcp_action({"tag": "get-info", "attributes": {}})
    data = info_resp.get("data", {})
    counts = data.get("elementCounts", {})
    print(f" -> Total Nodes in Canvas: {sum(counts.values())}")
    print(f" -> Node Breakdown: {json.dumps(counts)}")

    # ---------------------------------------------------------
    # CAPABILITY 5: Live Desktop Sync & High-Res PNG Export
    # ---------------------------------------------------------
    print("\n[5/5] Synchronizing Desktop GUI & Rasterizing Output...")
    # Refresh running GUI window
    subprocess.run([INKSCAPE_COM, "-q", "--actions=file-rebase"], capture_output=True, timeout=10)
    # Export PNG
    export_result = subprocess.run([INKSCAPE_COM, f"--export-filename={PNG_PATH}", str(SVG_PATH)], capture_output=True, timeout=30)
    if export_result.returncode != 0:
        print(f"WARNING: Inkscape export returned non-zero exit code: {export_result.returncode}")
    if os.path.exists(PNG_PATH):
        print(f" -> Exported PNG size: {os.path.getsize(PNG_PATH)} bytes")
    else:
        print(f"WARNING: Export file not created: {PNG_PATH}")
    print("\n[SUCCESS] SHOWCASE COMPLETE!")


if __name__ == "__main__":
    main()
