"""Headless DRC, exports and renders via kicad-cli.

These tools work on .kicad_pcb files on disk. When board_path is omitted they
target the board open in the live editor (saving it first so the file matches
what is on screen).
"""

import json
from pathlib import Path

from mcp.server.fastmcp import Image
from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp.app import mcp
from kicad_mcp.backends import cli, ipc


def _resolve_board(board_path: str | None, save_first: bool) -> Path:
    if board_path:
        p = Path(board_path)
        if not p.exists():
            raise ToolError(f"Board file not found: {p}")
        return p
    path = ipc.open_board_path()
    if path is None:
        raise ToolError(
            "No board_path given and the open board's file path could not be "
            "resolved via the IPC API. Pass board_path explicitly."
        )
    if save_first:
        ipc.get_board().save()
    return path


def _out_dir(board: Path, kind: str, output_dir: str | None) -> Path:
    out = Path(output_dir) if output_dir else board.parent / "mcp-exports" / kind
    out.mkdir(parents=True, exist_ok=True)
    return out


@mcp.tool()
def run_drc(board_path: str | None = None, save_first: bool = True) -> dict:
    """Run Design Rules Check on a board file (or the board open in the
    editor). Returns violation counts and details from the JSON report."""
    board = _resolve_board(board_path, save_first)
    report = _out_dir(board, "drc", None) / f"{board.stem}-drc.json"
    cli.run_cli(
        [
            "pcb",
            "drc",
            "--format",
            "json",
            "--severity-all",
            "--output",
            str(report),
            str(board),
        ]
    )
    data = json.loads(report.read_text(encoding="utf-8"))
    violations = data.get("violations", [])
    unconnected = data.get("unconnected_items", [])
    schematic_parity = data.get("schematic_parity", [])

    def summarize(entries, limit=50):
        out = []
        for v in entries[:limit]:
            items = [i.get("description", "") for i in v.get("items", [])]
            pos = None
            if v.get("items"):
                p = v["items"][0].get("pos", {})
                pos = {"x_mm": p.get("x"), "y_mm": p.get("y")}
            out.append(
                {
                    "type": v.get("type"),
                    "severity": v.get("severity"),
                    "description": v.get("description"),
                    "position_mm": pos,
                    "items": items,
                }
            )
        return out

    by_severity: dict[str, int] = {}
    for v in violations:
        sev = v.get("severity", "unknown")
        by_severity[sev] = by_severity.get(sev, 0) + 1
    return {
        "board": str(board),
        "report_file": str(report),
        "violation_count": len(violations),
        "violations_by_severity": by_severity,
        "unconnected_count": len(unconnected),
        "schematic_parity_count": len(schematic_parity),
        "violations": summarize(violations),
        "unconnected": summarize(unconnected, limit=20),
    }


@mcp.tool()
def export_gerbers(
    board_path: str | None = None,
    output_dir: str | None = None,
    include_drill: bool = True,
    save_first: bool = True,
) -> dict:
    """Export Gerber fabrication files (plus drill files) for a board.
    Defaults to <board dir>/mcp-exports/gerbers."""
    board = _resolve_board(board_path, save_first)
    out = _out_dir(board, "gerbers", output_dir)
    cli.run_cli(["pcb", "export", "gerbers", "--output", str(out) + "\\", str(board)])
    if include_drill:
        cli.run_cli(["pcb", "export", "drill", "--output", str(out) + "\\", str(board)])
    files = sorted(p.name for p in out.iterdir() if p.is_file())
    return {"board": str(board), "output_dir": str(out), "files": files}


@mcp.tool()
def export_step(
    board_path: str | None = None,
    output_path: str | None = None,
    save_first: bool = True,
) -> dict:
    """Export the board as a STEP 3D model (with substituted models)."""
    board = _resolve_board(board_path, save_first)
    out = (
        Path(output_path)
        if output_path
        else _out_dir(board, "3d", None) / f"{board.stem}.step"
    )
    cli.run_cli(
        ["pcb", "export", "step", "--subst-models", "--output", str(out), str(board)],
        timeout=600,
    )
    return {"board": str(board), "step_file": str(out), "size_bytes": out.stat().st_size}


@mcp.tool()
def export_pdf(
    board_path: str | None = None,
    layers: str = "F.Cu,B.Cu,F.SilkS,B.SilkS,Edge.Cuts",
    output_path: str | None = None,
    save_first: bool = True,
) -> dict:
    """Plot board layers to a PDF (comma-separated canonical layer names)."""
    board = _resolve_board(board_path, save_first)
    out = (
        Path(output_path)
        if output_path
        else _out_dir(board, "pdf", None) / f"{board.stem}.pdf"
    )
    cli.run_cli(
        ["pcb", "export", "pdf", "--layers", layers, "--output", str(out), str(board)]
    )
    return {"board": str(board), "pdf_file": str(out), "layers": layers}


@mcp.tool()
def render_board(
    board_path: str | None = None,
    side: str = "top",
    width: int = 1200,
    height: int = 900,
    zoom: float = 1.0,
    save_first: bool = True,
) -> Image:
    """Render a raytraced 3D image of the board and return it as a PNG.
    side: top|bottom|left|right|front|back."""
    board = _resolve_board(board_path, save_first)
    out = _out_dir(board, "render", None) / f"{board.stem}-{side}.png"
    cli.run_cli(
        [
            "pcb",
            "render",
            "--side",
            side,
            "--width",
            str(width),
            "--height",
            str(height),
            "--zoom",
            str(zoom),
            "--output",
            str(out),
            str(board),
        ],
        timeout=600,
    )
    return Image(path=str(out))
