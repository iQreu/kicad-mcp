"""Schematic file editing (opt-in, experimental).

KiCad 10 has no official schematic-editing API, so these tools rewrite
.kicad_sch files directly via the kicad-sch-api library. That carries real
risk (format drift, subtle corruption), therefore:

- every mutating tool is disabled unless the server runs with
  KICAD_MCP_ENABLE_SCH_EDIT=1,
- a timestamped backup of the file is created before the first mutation
  in this session,
- KiCad does not hot-reload: close/reopen the schematic in eeschema to see
  changes, and never edit a file that is open with unsaved GUI changes.
"""

import shutil
import time
from pathlib import Path

from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp import config
from kicad_mcp.app import mcp
from kicad_mcp.backends import cli

_backed_up: set[str] = set()


def _require_enabled():
    if not config.SCH_EDIT_ENABLED:
        raise ToolError(
            "Schematic editing is disabled. It rewrites .kicad_sch files directly "
            "(experimental, corruption risk). To enable, set the environment "
            "variable KICAD_MCP_ENABLE_SCH_EDIT=1 for this MCP server (e.g. in "
            ".mcp.json 'env') and restart it. Read-only schematic tools work "
            "without this."
        )


def _load(sch_path: str, must_exist: bool = True):
    import kicad_sch_api as ksa

    p = Path(sch_path)
    if must_exist and not p.exists():
        raise ToolError(f"Schematic file not found: {p}")
    return p, ksa


def _finalize_save(sch, p: Path, new_file: bool = False):
    """Persist the schematic and normalize it to the current KiCad format.

    kicad-sch-api writes the KiCad 9 dialect (version 20250114), so after
    every save the file is rewritten by `kicad-cli sch upgrade` to the format
    of the installed KiCad. The upgrade doubles as a parse check by KiCad
    itself: if it fails, the previous file content is restored."""
    snapshot = p.read_bytes() if p.exists() else None
    try:
        if new_file:
            p.parent.mkdir(parents=True, exist_ok=True)
            sch.save_as(p)
        else:
            sch.save()
    except Exception as exc:
        issues = ""
        try:
            summary = sch.get_validation_summary()
            issues = f" Validation summary: {summary}"
        except Exception:
            pass
        raise ToolError(
            f"kicad-sch-api refused to save {p.name}: {exc}.{issues} The file on "
            "disk was NOT modified. This typically happens on schematics using "
            "legacy or project-local symbols the library cannot validate - edit "
            "such schematics in eeschema instead."
        ) from exc
    try:
        cli.run_cli(["sch", "upgrade", str(p)], timeout=120)
    except ToolError as exc:
        if snapshot is not None:
            p.write_bytes(snapshot)
        else:
            p.unlink(missing_ok=True)
        raise ToolError(
            f"KiCad could not parse the file just written by kicad-sch-api "
            f"({exc}). The previous content of {p.name} was restored."
        ) from exc


def _backup(p: Path) -> str | None:
    key = str(p.resolve()).lower()
    if key in _backed_up or not p.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = p.with_name(f"{p.name}.mcp-backup-{stamp}")
    shutil.copy2(p, backup)
    _backed_up.add(key)
    return str(backup)


@mcp.tool()
def sch_edit_status() -> dict:
    """Report whether experimental schematic editing is enabled and how to
    enable it."""
    return {
        "enabled": config.SCH_EDIT_ENABLED,
        "how_to_enable": "Set KICAD_MCP_ENABLE_SCH_EDIT=1 in the MCP server environment.",
        "warning": (
            "Editing rewrites .kicad_sch files directly (no official API in "
            "KiCad 10). Backups are created automatically; reopen the file in "
            "eeschema after edits."
        ),
    }


@mcp.tool()
def sch_create_schematic(sch_path: str, title: str | None = None) -> dict:
    """Create a new empty .kicad_sch file (fails if it already exists)."""
    _require_enabled()
    p, ksa = _load(sch_path, must_exist=False)
    if p.exists():
        raise ToolError(f"File already exists: {p}. Refusing to overwrite.")
    sch = ksa.create_schematic(p.stem)
    if title:
        sch.set_title_block(title=title)
    _finalize_save(sch, p, new_file=True)
    return {"created": str(p)}


@mcp.tool()
def sch_add_component(
    sch_path: str,
    lib_id: str,
    reference: str | None = None,
    value: str = "",
    x_mm: float = 100.0,
    y_mm: float = 100.0,
    rotation_deg: float = 0.0,
    footprint: str | None = None,
) -> dict:
    """Add a symbol to a schematic file. lib_id e.g. 'Device:R'. Position in
    mm on the sheet. Reference is auto-assigned when omitted."""
    _require_enabled()
    p, ksa = _load(sch_path)
    backup = _backup(p)
    sch = ksa.load_schematic(str(p))
    comp = sch.components.add(
        lib_id=lib_id,
        reference=reference,
        value=value,
        position=(x_mm, y_mm),
        rotation=rotation_deg,
        footprint=footprint,
    )
    _finalize_save(sch, p)
    return {
        "added": getattr(comp, "reference", reference),
        "lib_id": lib_id,
        "position_mm": {"x_mm": x_mm, "y_mm": y_mm},
        "backup_file": backup,
        "note": "Reopen the schematic in eeschema to see the change.",
    }


@mcp.tool()
def sch_add_wire(sch_path: str, points_mm: list[list[float]]) -> dict:
    """Add wire segments along a polyline of [x, y] sheet coordinates (mm)."""
    _require_enabled()
    if len(points_mm) < 2:
        raise ToolError("points_mm needs at least 2 points.")
    p, ksa = _load(sch_path)
    backup = _backup(p)
    sch = ksa.load_schematic(str(p))
    ids = []
    for (x1, y1), (x2, y2) in zip(points_mm, points_mm[1:]):
        ids.append(sch.add_wire((x1, y1), (x2, y2)))
    _finalize_save(sch, p)
    return {"added_segments": len(ids), "backup_file": backup}


@mcp.tool()
def sch_connect_pins(
    sch_path: str, ref1: str, pin1: str, ref2: str, pin2: str
) -> dict:
    """Draw a wire connecting two component pins (e.g. R1 pin 2 to C1 pin 1)."""
    _require_enabled()
    p, ksa = _load(sch_path)
    backup = _backup(p)
    sch = ksa.load_schematic(str(p))
    wire_id = sch.connect_pins_with_wire(ref1, pin1, ref2, pin2)
    if not wire_id:
        raise ToolError(
            f"Could not connect {ref1}.{pin1} to {ref2}.{pin2} - check that both "
            "references and pin numbers exist."
        )
    _finalize_save(sch, p)
    return {"connected": f"{ref1}.{pin1} -> {ref2}.{pin2}", "backup_file": backup}


@mcp.tool()
def sch_add_label(sch_path: str, text: str, x_mm: float, y_mm: float) -> dict:
    """Add a local net label at the given sheet position (mm)."""
    _require_enabled()
    p, ksa = _load(sch_path)
    backup = _backup(p)
    sch = ksa.load_schematic(str(p))
    sch.add_label(text, position=(x_mm, y_mm))
    _finalize_save(sch, p)
    return {"added_label": text, "backup_file": backup}


@mcp.tool()
def sch_apply_edits(
    sch_path: str,
    components: list[dict] | None = None,
    pin_connections: list[dict] | None = None,
    wires: list[dict] | None = None,
    labels: list[dict] | None = None,
    create_if_missing: bool = False,
) -> dict:
    """Apply a whole batch of schematic edits in ONE call (one file load, one
    save) - strongly preferred over calling sch_add_component etc. in a loop.

    components: [{lib_id, x_mm, y_mm, reference?, value?, rotation_deg?, footprint?}]
    pin_connections: [{ref1, pin1, ref2, pin2}]  (wires between component pins)
    wires: [{points_mm: [[x, y], ...]}]          (free-routed polylines)
    labels: [{text, x_mm, y_mm}]

    Operations apply in the order above. If any operation fails, nothing is
    saved and the file on disk stays untouched."""
    _require_enabled()
    p, ksa = _load(sch_path, must_exist=not create_if_missing)
    backup = _backup(p)
    if p.exists():
        sch = ksa.load_schematic(str(p))
    else:
        sch = ksa.create_schematic(p.stem)
    done = {"components": [], "pin_connections": 0, "wire_segments": 0, "labels": 0}
    for i, c in enumerate(components or []):
        try:
            comp = sch.components.add(
                lib_id=c["lib_id"],
                reference=c.get("reference"),
                value=c.get("value", ""),
                position=(c["x_mm"], c["y_mm"]),
                rotation=c.get("rotation_deg", 0.0),
                footprint=c.get("footprint"),
            )
            done["components"].append(getattr(comp, "reference", c.get("reference")))
        except Exception as exc:
            raise ToolError(
                f"components[{i}] ({c.get('lib_id')}) failed: {exc}. "
                "Nothing was saved; the file is unchanged."
            ) from exc
    for i, pc in enumerate(pin_connections or []):
        wire_id = sch.connect_pins_with_wire(
            pc["ref1"], str(pc["pin1"]), pc["ref2"], str(pc["pin2"])
        )
        if not wire_id:
            raise ToolError(
                f"pin_connections[{i}] ({pc}) failed - check references and pin "
                "numbers. Nothing was saved; the file is unchanged."
            )
        done["pin_connections"] += 1
    for i, w in enumerate(wires or []):
        pts = w["points_mm"]
        if len(pts) < 2:
            raise ToolError(f"wires[{i}]: needs at least 2 points. Nothing was saved.")
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            sch.add_wire((x1, y1), (x2, y2))
            done["wire_segments"] += 1
    for lb in labels or []:
        sch.add_label(lb["text"], position=(lb["x_mm"], lb["y_mm"]))
        done["labels"] += 1
    _finalize_save(sch, p, new_file=not p.exists())
    return {
        "schematic": str(p),
        "applied": done,
        "backup_file": backup,
        "note": "Reopen the schematic in eeschema to see the changes.",
    }


@mcp.tool()
def sch_statistics(sch_path: str) -> dict:
    """Read-only summary of a schematic file via kicad-sch-api (component,
    wire and label counts). Works without the edit opt-in."""
    p, ksa = _load(sch_path)
    sch = ksa.load_schematic(str(p))
    return {"schematic": str(p), "statistics": sch.get_statistics()}
