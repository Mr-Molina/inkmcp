# Inkscape MCP (`inkmcp`) Project Guidelines & Architecture

## Project Overview
**Repository**: `Mr-Molina/inkmcp`  
**Purpose**: Model Context Protocol (MCP) server providing live, bidirectional natural language and programmatic control over Inkscape vector graphics documents via D-Bus, FastMCP, and hybrid Python execution environments (including Blender 3D integration).

## Core Architecture
- **Inkscape Extension (`inkscape_mcp.py`, `inkscape_mcp.inx`)**:
  - Inkscape extension responding to D-Bus signals and method calls under `org.inkscape.Inkscape`.
- **FastMCP Server (`inkmcp/inkscape_mcp_server.py`)**:
  - Exposes MCP tools (`inkscape_operation`, `vectorize_image`) for shape creation, style manipulation, layer management, code execution, viewport exports, and multi-mode raster-to-SVG vectorization.
- **CLI Client (`inkmcp/inkmcpcli.py`)**:
  - Direct execution harness and hybrid code executor (`execute-hybrid`) that handles `# @local` and `# @inkscape` block switching with bidirectional state sharing, plus vectorization CLI commands (`vectorize-image`, `vectorize-coloring-book`).
- **Modular SVG Operations (`inkmcp/inkmcpops/`)**:
  - Individual operation implementations (`circle`, `rect`, `path`, `linearGradient`, `execute-code`, `get-info`, `vectorize_operations.py`, etc.).
- **Vectorizer & Coloring Book Pipeline (`inkmcp/vectorizer/`)**:
  - Multi-stage vectorization engine (`pipeline.py`, `core.py`, `planar_tracer.py`) and 4-Phase Coloring Book Vectorization Pipeline (`coloring_book_pipeline.py`, `color_inventory.py`, `outline_generator.py`, `region_topology.py`) with high-fidelity `trace_planar` + `VTracerCore` fallback.
- **Backends & Desktop Automation (`inkmcp/backends/`)**:
  - Cross-platform execution backends (`windows_cli.py`, `dbus.py`, `headless.py`) and Win32 live Paint Bucket automation (`desktop_automator.py`).
- **Blender Integration (`blender_addon_inkscape_hybrid.py`, `blender_inkscape_hybrid.py`)**:
  - Add-on bridging Blender Bezier curves, meshes, and animation frames into live Inkscape vector art.

## Operational & Governance Invariants
- **Multi-Agent Governance**: Refer to [`.agents/AGENTS.md`](file:///s:/Github/inkmcp/.agents/AGENTS.md) for cognitive persona assignments.
- **Infrastructure Invariants**: Enforce [`.agents/INFRASTRUCTURE_INVARIANTS.md`](file:///s:/Github/inkmcp/.agents/INFRASTRUCTURE_INVARIANTS.md):
  - Invariant 13: Debug artifact cleanup before session handoff.
  - Invariant 14 / 38: Three Strikes Rule with Deep Research escalation.
  - Invariant 24: Zero credential leaks or plain-text secrets.
  - Invariant 33 / 34: Orchestrator delegation to specialized subagents for heavy scans and refactors.
  - Invariant 39: Evidence before assertions (anti-guessing).
- **Session Ledger**: Maintain local session records in [`.agents/sessions.md`](file:///s:/Github/inkmcp/.agents/sessions.md).
