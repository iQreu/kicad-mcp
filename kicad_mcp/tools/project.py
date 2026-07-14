"""Project scaffolding and project-level settings (netclasses)."""

import json
import shutil
import time
from pathlib import Path

from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp.app import EDIT, READONLY, mcp
from kicad_mcp.backends import cli


def _load_project(project_path: str) -> tuple[Path, dict]:
    p = Path(project_path)
    if p.suffix != ".kicad_pro":
        raise ToolError(f"Not a KiCad project file (.kicad_pro): {p}")
    if not p.exists():
        raise ToolError(f"Project file not found: {p}")
    try:
        return p, json.loads(p.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ToolError(f"Cannot parse {p.name}: {exc}") from exc


@mcp.tool(annotations=EDIT)
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
    # format (upgrade doubles as a validity check). The root sheet MUST get a
    # real uuid - with a nil uuid KiCad silently drops every symbol instance
    # from netlists and plots.
    import uuid as uuid_mod

    sch.write_text(
        '(kicad_sch (version 20250114) (generator "eeschema") '
        f'(uuid "{uuid_mod.uuid4()}") (paper "A4"))\n',
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


@mcp.tool(annotations=READONLY)
def list_netclasses(project_path: str) -> dict:
    """List netclasses defined in a .kicad_pro project file (track width,
    clearance, via sizes, differential pair settings) and the patterns that
    assign nets to them."""
    p, data = _load_project(project_path)
    ns = data.get("net_settings", {})
    return {
        "project": str(p),
        "classes": ns.get("classes", []),
        "netclass_patterns": ns.get("netclass_patterns", []),
    }


@mcp.tool(annotations=EDIT)
def set_netclass(
    project_path: str,
    name: str,
    track_width_mm: float | None = None,
    clearance_mm: float | None = None,
    via_diameter_mm: float | None = None,
    via_drill_mm: float | None = None,
    diff_pair_width_mm: float | None = None,
    diff_pair_gap_mm: float | None = None,
    priority: int | None = None,
    net_patterns: list[str] | None = None,
) -> dict:
    """Create or update a netclass in the .kicad_pro project file. Only the
    given fields change. net_patterns assigns nets by wildcard pattern (e.g.
    ['GND', '/hv_*']). IMPORTANT: close the project in KiCad first - KiCad
    overwrites the project file with its in-memory state on exit."""
    p, data = _load_project(project_path)
    backup = p.with_name(f"{p.name}.mcp-backup-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(p, backup)

    ns = data.setdefault("net_settings", {"meta": {"version": 5}})
    classes = ns.setdefault("classes", [])

    def _new_class(cls_name: str) -> dict:
        return {
            "name": cls_name,
            "bus_width": 12,
            "clearance": 0.2,
            "diff_pair_gap": 0.25,
            "diff_pair_via_gap": 0.25,
            "diff_pair_width": 0.2,
            "line_style": 0,
            "microvia_diameter": 0.3,
            "microvia_drill": 0.1,
            "pcb_color": "rgba(0, 0, 0, 0.000)",
            "priority": len(classes),
            "schematic_color": "rgba(0, 0, 0, 0.000)",
            "track_width": 0.2,
            "tuning_profile": "",
            "via_diameter": 0.6,
            "via_drill": 0.3,
            "wire_width": 6,
        }

    if not any(c.get("name") == "Default" for c in classes):
        default = _new_class("Default")
        default["priority"] = 2147483647
        classes.append(default)
    cls = next((c for c in classes if c.get("name") == name), None)
    created = cls is None
    if created:
        cls = _new_class(name)
        classes.append(cls)
    updates = {
        "track_width": track_width_mm,
        "clearance": clearance_mm,
        "via_diameter": via_diameter_mm,
        "via_drill": via_drill_mm,
        "diff_pair_width": diff_pair_width_mm,
        "diff_pair_gap": diff_pair_gap_mm,
        "priority": priority,
    }
    for key, value in updates.items():
        if value is not None:
            cls[key] = value
    if net_patterns is not None:
        patterns = [pt for pt in ns.get("netclass_patterns") or [] if pt.get("netclass") != name]
        patterns.extend({"netclass": name, "pattern": pat} for pat in net_patterns)
        ns["netclass_patterns"] = patterns

    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {
        "project": str(p),
        "netclass": name,
        "created": created,
        "class": cls,
        "patterns": [pt for pt in ns.get("netclass_patterns", []) if pt.get("netclass") == name],
        "backup_file": str(backup),
        "note": "Reopen the project in KiCad to load the change.",
    }
