"""Editing tools for the board open in the live PCB editor (IPC API).

Every mutation is wrapped in a commit so it lands as a single undo step in
the KiCad GUI. Changes are NOT saved to disk until save_board is called.
"""

from kipy.board_types import BoardRectangle, FootprintInstance, Track, Via, Zone
from kipy.geometry import Angle, PolygonWithHoles, PolyLine, PolyLineNode
from kipy.proto.board.board_types_pb2 import ZoneType
from kipy.proto.common.types.base_types_pb2 import KIID
from kipy.util.units import from_mm
from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp.app import mcp
from kicad_mcp.backends import ipc
from kicad_mcp.util import (
    angle_deg,
    enum_to_layer,
    kiid_str,
    layer_to_enum,
    pos_to_mm,
    vec_mm,
)


def _find_footprint(board, reference: str):
    for fp in board.get_footprints():
        if fp.reference_field.text.value == reference:
            return fp
    refs = sorted(f.reference_field.text.value for f in board.get_footprints())[:60]
    raise ToolError(f"Footprint '{reference}' not found. Present: {refs}")


@mcp.tool()
def place_footprint(
    library_id: str,
    x_mm: float,
    y_mm: float,
    rotation_deg: float = 0.0,
    layer: str = "F.Cu",
    reference: str | None = None,
    value: str | None = None,
) -> dict:
    """Place a footprint from a library onto the live board.
    library_id format: 'LibraryNickname:FootprintName',
    e.g. 'Resistor_SMD:R_0603_1608Metric'. layer: F.Cu or B.Cu."""
    if ":" not in library_id:
        raise ToolError(
            "library_id must be 'LibraryNickname:FootprintName', "
            "e.g. 'Resistor_SMD:R_0603_1608Metric'."
        )
    nickname, entry = library_id.split(":", 1)
    board = ipc.get_board()
    fpi = FootprintInstance()
    fpi.proto.definition.id.library_nickname = nickname
    fpi.proto.definition.id.entry_name = entry
    fpi.position = vec_mm(x_mm, y_mm)
    fpi.orientation = Angle.from_degrees(rotation_deg)
    fpi.layer = layer_to_enum(layer)
    if reference:
        fpi.reference_field.text.value = reference
    if value:
        fpi.value_field.text.value = value

    with ipc.board_commit(board, f"MCP: place {library_id}"):
        created = board.create_items(fpi)
    if not created:
        raise ToolError(
            f"KiCad did not create the footprint. Check that '{library_id}' exists "
            "in the footprint library table (list of libraries: Preferences > "
            "Manage Footprint Libraries)."
        )
    fp = created[0]
    return {
        "board": board.name,
        "created": True,
        "id": kiid_str(fp),
        "reference": fp.reference_field.text.value,
        "library_id": library_id,
        "position_mm": pos_to_mm(fp.position),
    }


@mcp.tool()
def move_footprint(
    reference: str,
    x_mm: float | None = None,
    y_mm: float | None = None,
    rotation_deg: float | None = None,
) -> dict:
    """Move and/or rotate a footprint identified by its reference (e.g. 'R1').
    Omitted coordinates keep their current value."""
    board = ipc.get_board()
    fp = _find_footprint(board, reference)
    cur = pos_to_mm(fp.position)
    new_x = cur["x_mm"] if x_mm is None else x_mm
    new_y = cur["y_mm"] if y_mm is None else y_mm
    fp.position = vec_mm(new_x, new_y)
    if rotation_deg is not None:
        fp.orientation = Angle.from_degrees(rotation_deg)
    with ipc.board_commit(board, f"MCP: move {reference}"):
        board.update_items(fp)
    return {
        "board": board.name,
        "reference": reference,
        "position_mm": {"x_mm": new_x, "y_mm": new_y},
        "rotation_deg": rotation_deg if rotation_deg is not None else angle_deg(fp.orientation),
    }


@mcp.tool()
def remove_footprint(reference: str) -> dict:
    """Delete a footprint from the live board by reference."""
    board = ipc.get_board()
    fp = _find_footprint(board, reference)
    with ipc.board_commit(board, f"MCP: remove {reference}"):
        board.remove_items(fp)
    return {"board": board.name, "removed": reference}


@mcp.tool()
def add_track(
    points_mm: list[list[float]],
    width_mm: float = 0.25,
    layer: str = "F.Cu",
    net_name: str | None = None,
) -> dict:
    """Add straight track segments along a polyline of [x, y] points (mm) on a
    copper layer, optionally assigned to a net.
    Example points_mm: [[10, 10], [20, 10], [20, 20]]."""
    if len(points_mm) < 2:
        raise ToolError("points_mm needs at least 2 points.")
    board = ipc.get_board()
    net = ipc.find_net(board, net_name) if net_name else None
    layer_enum = layer_to_enum(layer)
    segments = []
    for (x1, y1), (x2, y2) in zip(points_mm, points_mm[1:]):
        t = Track()
        t.start = vec_mm(x1, y1)
        t.end = vec_mm(x2, y2)
        t.width = from_mm(width_mm)
        t.layer = layer_enum
        if net is not None:
            t.net = net
        segments.append(t)
    with ipc.board_commit(board, "MCP: add track"):
        created = board.create_items(segments)
    return {
        "board": board.name,
        "created_segments": len(created),
        "ids": [kiid_str(t) for t in created],
        "layer": layer,
        "width_mm": width_mm,
        "net": net_name,
    }


@mcp.tool()
def add_via(
    x_mm: float,
    y_mm: float,
    diameter_mm: float = 0.8,
    drill_mm: float = 0.4,
    net_name: str | None = None,
) -> dict:
    """Add a through via at the given position (mm), optionally on a net."""
    board = ipc.get_board()
    via = Via()
    via.position = vec_mm(x_mm, y_mm)
    via.diameter = from_mm(diameter_mm)
    via.drill_diameter = from_mm(drill_mm)
    if net_name:
        via.net = ipc.find_net(board, net_name)
    with ipc.board_commit(board, "MCP: add via"):
        created = board.create_items(via)
    return {
        "board": board.name,
        "created": bool(created),
        "id": kiid_str(created[0]) if created else None,
        "position_mm": {"x_mm": x_mm, "y_mm": y_mm},
        "net": net_name,
    }


@mcp.tool()
def place_footprints(items: list[dict]) -> dict:
    """Place MANY footprints in one call and one undo step - preferred over
    calling place_footprint in a loop.

    items: [{library_id, x_mm, y_mm, reference?, value?, rotation_deg?, layer?}]
    library_id format: 'LibraryNickname:FootprintName'."""
    if not items:
        raise ToolError("items is empty.")
    board = ipc.get_board()
    instances = []
    for i, it in enumerate(items):
        lib_id = it.get("library_id", "")
        if ":" not in lib_id:
            raise ToolError(
                f"items[{i}]: library_id must be 'LibraryNickname:FootprintName', got '{lib_id}'."
            )
        nickname, entry = lib_id.split(":", 1)
        fpi = FootprintInstance()
        fpi.proto.definition.id.library_nickname = nickname
        fpi.proto.definition.id.entry_name = entry
        fpi.position = vec_mm(it["x_mm"], it["y_mm"])
        fpi.orientation = Angle.from_degrees(it.get("rotation_deg", 0.0))
        fpi.layer = layer_to_enum(it.get("layer", "F.Cu"))
        if it.get("reference"):
            fpi.reference_field.text.value = it["reference"]
        if it.get("value"):
            fpi.value_field.text.value = it["value"]
        instances.append(fpi)
    with ipc.board_commit(board, f"MCP: place {len(instances)} footprints"):
        created = board.create_items(instances)
    return {
        "board": board.name,
        "requested": len(items),
        "created": len(created),
        "references": [fp.reference_field.text.value for fp in created],
    }


@mcp.tool()
def add_tracks(tracks: list[dict]) -> dict:
    """Add MANY track polylines (and optional vias) in one call and one undo
    step - preferred over calling add_track in a loop.

    tracks: [{points_mm: [[x, y], ...], width_mm?, layer?, net_name?}]"""
    if not tracks:
        raise ToolError("tracks is empty.")
    board = ipc.get_board()
    nets = {n.name: n for n in board.get_nets()}
    segments = []
    for i, tr in enumerate(tracks):
        pts = tr.get("points_mm", [])
        if len(pts) < 2:
            raise ToolError(f"tracks[{i}]: points_mm needs at least 2 points.")
        net_name = tr.get("net_name")
        if net_name and net_name not in nets:
            raise ToolError(
                f"tracks[{i}]: net '{net_name}' not found. Known nets include: "
                f"{sorted(nets)[:40]}"
            )
        layer_enum = layer_to_enum(tr.get("layer", "F.Cu"))
        width = from_mm(tr.get("width_mm", 0.25))
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            t = Track()
            t.start = vec_mm(x1, y1)
            t.end = vec_mm(x2, y2)
            t.width = width
            t.layer = layer_enum
            if net_name:
                t.net = nets[net_name]
            segments.append(t)
    with ipc.board_commit(board, f"MCP: add {len(segments)} track segments"):
        created = board.create_items(segments)
    return {"board": board.name, "polylines": len(tracks), "created_segments": len(created)}


@mcp.tool()
def remove_items(ids: list[str]) -> dict:
    """Delete arbitrary board items by their KIID strings (as returned by the
    list_* tools)."""
    board = ipc.get_board()
    kiids = [KIID(value=i) for i in ids]
    items = board.get_items_by_id(kiids)
    found = [i for i in items if i is not None]
    if not found:
        raise ToolError(f"No board items found for ids: {ids}")
    with ipc.board_commit(board, "MCP: remove items"):
        board.remove_items(found)
    return {"board": board.name, "requested": len(ids), "removed": len(found)}


@mcp.tool()
def add_copper_zone(
    points_mm: list[list[float]],
    layer: str = "F.Cu",
    net_name: str | None = None,
    priority: int = 0,
    min_thickness_mm: float = 0.25,
    refill: bool = True,
) -> dict:
    """Add a copper zone (pour) with a polygon outline of [x, y] points (mm)
    on one copper layer, usually assigned to a net like GND. Refills zones
    afterwards by default."""
    if len(points_mm) < 3:
        raise ToolError("A zone outline needs at least 3 points.")
    board = ipc.get_board()
    outline = PolyLine()
    for x, y in points_mm:
        outline.append(PolyLineNode.from_point(vec_mm(x, y)))
    outline.closed = True
    polygon = PolygonWithHoles()
    polygon.outline = outline

    zone = Zone()
    zone.type = ZoneType.ZT_COPPER
    zone.layers = [layer_to_enum(layer)]
    zone.outline = polygon
    zone.priority = priority
    zone.min_thickness = from_mm(min_thickness_mm)
    if net_name:
        zone.net = ipc.find_net(board, net_name)
    with ipc.board_commit(board, "MCP: add copper zone"):
        created = board.create_items(zone)
    if refill:
        board.refill_zones()
    return {
        "board": board.name,
        "created": len(created),
        "id": kiid_str(created[0]) if created else None,
        "layer": layer,
        "net": net_name,
        "refilled": refill,
    }


@mcp.tool()
def draw_board_outline(
    x_mm: float,
    y_mm: float,
    width_mm: float,
    height_mm: float,
    replace_existing: bool = False,
) -> dict:
    """Draw a rectangular board outline on Edge.Cuts (top-left corner at
    x/y, size width x height, all mm). replace_existing removes previous
    Edge.Cuts graphics first."""
    board = ipc.get_board()
    edge = layer_to_enum("Edge.Cuts")
    removed = 0
    with ipc.board_commit(board, "MCP: board outline"):
        if replace_existing:
            old = [s for s in board.get_shapes() if s.layer == edge]
            if old:
                board.remove_items(old)
                removed = len(old)
        rect = BoardRectangle()
        rect.top_left = vec_mm(x_mm, y_mm)
        rect.bottom_right = vec_mm(x_mm + width_mm, y_mm + height_mm)
        rect.layer = edge
        created = board.create_items(rect)
    return {
        "board": board.name,
        "created": len(created),
        "removed_previous": removed,
        "outline_mm": {"x": x_mm, "y": y_mm, "width": width_mm, "height": height_mm},
    }


@mcp.tool()
def refill_zones() -> dict:
    """Refill all copper zones on the live board (run after moving tracks or
    footprints so zone fills are current)."""
    board = ipc.get_board()
    board.refill_zones()
    return {"board": board.name, "refilled": True, "zones": len(board.get_zones())}


@mcp.tool()
def save_board() -> dict:
    """Save the live board to disk."""
    board = ipc.get_board()
    board.save()
    path = ipc.open_board_path()
    return {"saved": True, "path": str(path) if path else board.name}


@mcp.tool()
def select_items(ids: list[str], clear_first: bool = True) -> dict:
    """Select board items by KIID in the PCB editor (highlights them for the
    user). clear_first replaces the current selection."""
    board = ipc.get_board()
    if clear_first:
        board.clear_selection()
    kiids = [KIID(value=i) for i in ids]
    items = [i for i in board.get_items_by_id(kiids) if i is not None]
    if items:
        board.add_to_selection(items)
    return {"selected": len(items)}


@mcp.tool()
def clear_selection() -> dict:
    """Clear the selection in the PCB editor."""
    board = ipc.get_board()
    board.clear_selection()
    return {"cleared": True}
