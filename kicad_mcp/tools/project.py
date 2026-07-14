"""Project scaffolding: create a complete empty KiCad 10 project."""

import json
from pathlib import Path

from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp.app import mcp
from kicad_mcp.backends import cli


@mcp.tool()
def create_project(directory: str, name: str, title: str | None = None) -> dict:
    """Create a new empty KiCad project: <name>.kicad_pro, an empty schematic
    and an empty board, all in the current KiCad 10 file format. Refuses to
    touch an existing project."""
    dir_path = Path(directory)
    pro = dir_path / f"{name}.kicad_pro"
    sch = dir_path / f"{name}.kicad_sch"
    pcb = dir_path / f"{name}.kicad_pcb"
    for p in (pro, sch, pcb):
        if p.exists():
            raise ToolError(f"{p} already exists. Refusing to overwrite.")
    dir_path.mkdir(parents=True, exist_ok=True)

    pro.write_text(
        json.dumps({"meta": {"filename": pro.name, "version": 3}}, indent=2),
        encoding="utf-8",
    )

    # Minimal seed files, then let KiCad itself rewrite them in its current
    # format (upgrade doubles as a validity check).
    sch.write_text(
        '(kicad_sch (version 20250114) (generator "eeschema") '
        '(uuid "00000000-0000-0000-0000-000000000000") (paper "A4"))\n',
        encoding="utf-8",
    )
    cli.run_cli(["sch", "upgrade", "--force", str(sch)])
    pcb.write_text(
        '(kicad_pcb (version 20240108) (generator "pcbnew"))\n', encoding="utf-8"
    )
    cli.run_cli(["pcb", "upgrade", str(pcb)])

    if title:
        try:
            from kicad_mcp.tools.schematic_edit import _finalize_save

            import kicad_sch_api as ksa

            s = ksa.load_schematic(str(sch))
            s.set_title_block(title=title)
            _finalize_save(s, sch)
        except Exception:
            pass

    return {
        "project": str(pro),
        "schematic": str(sch),
        "board": str(pcb),
        "note": "Open with launch_kicad or in the KiCad project manager.",
    }
