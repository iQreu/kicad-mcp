"""Fast 2D visual previews (PNG) of boards and schematics.

kicad-cli exports SVG headless; resvg rasterizes it to PNG the model can
see. Much faster than the raytraced render_board and works for schematics,
where KiCad has no direct PNG export.
"""

import re
import tempfile
from pathlib import Path

import resvg_py
from mcp.server.fastmcp import Image
from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp.app import EXPORT, mcp
from kicad_mcp.backends import cli
from kicad_mcp.tools.export import _out_dir, _resolve_board

_MM_WIDTH_RE = re.compile(r'width="([\d.]+)mm"')


def _svg_to_png(svg_path: Path, png_path: Path, width: int) -> Path:
    # resvg needs an explicit dpi to resolve KiCad's mm-based sizes; derive
    # it from the requested pixel width.
    m = _MM_WIDTH_RE.search(svg_path.read_text(encoding="utf-8", errors="replace")[:2000])
    dpi = width * 25.4 / float(m.group(1)) if m else 150.0
    png_bytes = bytes(
        resvg_py.svg_to_bytes(svg_path=str(svg_path), dpi=dpi, background="white")
    )
    png_path.write_bytes(png_bytes)
    return png_path


@mcp.tool(annotations=EXPORT)
def view_board(
    board_path: str | None = None,
    layers: str = "F.Cu,B.Cu,F.SilkS,Edge.Cuts",
    width: int = 1200,
    save_first: bool = True,
) -> Image:
    """Quick 2D top-down PNG view of the board (chosen layers, fit to board).
    Much faster than render_board; use it to visually check placement and
    routing after edits."""
    board = _resolve_board(board_path, save_first)
    out_dir = _out_dir(board, "preview", None)
    svg = out_dir / f"{board.stem}-view.svg"
    cli.run_cli(
        [
            "pcb", "export", "svg",
            "--mode-single",
            "--layers", layers,
            "--page-size-mode", "2",
            "--exclude-drawing-sheet",
            "--output", str(svg),
            str(board),
        ]
    )
    return Image(path=str(_svg_to_png(svg, svg.with_suffix(".png"), width)))


@mcp.tool(annotations=EXPORT)
def view_schematic(sch_path: str, sheet: int = 1, width: int = 1400) -> Image:
    """PNG view of a schematic sheet (1-based index for hierarchical
    designs). Use it to visually check symbol placement and wiring after
    schematic edits."""
    p = Path(sch_path)
    if not p.exists():
        raise ToolError(f"Schematic file not found: {p}")
    out_dir = Path(tempfile.mkdtemp(prefix="kicad_mcp_view_"))
    cli.run_cli(
        ["sch", "export", "svg", "--exclude-drawing-sheet", "--output", str(out_dir), str(p)]
    )
    svgs = sorted(out_dir.glob("*.svg"))
    if not svgs:
        raise ToolError("kicad-cli produced no SVG output for this schematic.")
    if not 1 <= sheet <= len(svgs):
        raise ToolError(
            f"sheet {sheet} out of range: schematic has {len(svgs)} sheet(s)."
        )
    svg = svgs[sheet - 1]
    return Image(path=str(_svg_to_png(svg, svg.with_suffix(".png"), width)))
